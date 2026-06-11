# PyCANoe 프로젝트 설계 명세서

> **Rev. 13.0** — Rev 13 검수보고서 반영. DB 핫스왑 race condition 수정, IG QSettings 직렬화 범위 정정, WaveformGenerator 스레드 소유권 명확화, LIN 컬러링·TraceModel 관계 명세, SimMessage msg_id 기반 삭제, TraceModel 표시 상한, Graph 신호별 색상 정책, 메모리 예산 보정, Dock 레이아웃 정책 반영. Trace Monitor / Graphics / Simulation·IG를 QDockWidget 기반으로 on/off 및 위치 이동 가능하도록 정정하고, Graphics와 Simulation·IG는 floating 허용. 상단 메뉴바와 하단 상태바는 고정 영역으로 명시.
>
> | 버전 | 주요 변경 |
> |---|---|
> | Rev 1.0~6.0 | 아키텍처 확립, 버그 수정 6종, 설계 개선 다수 |
> | Rev 7.0 | sentinel 패턴, stop() 폴링, QueuedConnection 명시, AsyncDbLoader 연속 로드 수정 |
> | Rev 8.0 | AI 구현 명세서로 전면 리팩토링. AI Rules / Thread Ownership / Error Policy / Implementation Order / 누락 인터페이스 명세 추가. 버전 히스토리 상세 제거. 토큰 최적화. |
> | Rev 9.0 | AI 구현 안전성 강화: SimWorker 복사 규칙, Shutdown 시퀀스, LogWorker while-else 설명, SignalBuffer 활성화 트리거, update_db() lock 주석, STEP 완료 기준, AsyncDbLoader disconnect 위치, conftest.py fixture 목록 추가. |
> | Rev 10.0 | M8 LIN H/W 지원 스코프 추가 (ChannelConfig.bus_type, build_bus_kwargs LIN 분기). pytest 환경 규칙 추가 (uv 환경 금지, 시스템 Python 사용). |
> | Rev 11.0 | 동시성 안전성 강화(LogQueue Lock, SignalBufferRegistry Lock), tx_bits 통계 수정(increment_tx frame_bits 인자 추가), Worker State Machine 규칙 추가, Config Validation 추가, SimStateStore 명세 추가, Virtual Node Thread Ownership 추가, AsyncDbLoader Shutdown 규칙 추가, UI Throttling 규칙 추가, LIN 지원 범위 명확화, Rev 11 비반영 항목 명시. |
> | **Rev 12.0** | **GUI Mockup 기준 UI/UX 명세 전면 업데이트 (§8 전면 재작성): 툴바 버튼 순서·구성, Trace 컬럼 Dir 추가·ID/PID 변경, 레이아웃 2컬럼(좌 Trace+IG / 우 Graph), 상태바 Memory/LDF 표시 추가. remove_channel() SimWorker 먼저 종료하도록 수정(§5.3). WaveformGenerator 클래스 명세 추가(§5.5, §6.4). IG Toolbar(New/Clone/SpecialFrame/Cut/Copy/Paste) 명세 추가(§8.3). Graph Dock 세부 UI 명세 추가(§8.4). Channel Configurator 팝업 명세 추가(§8.5). QSettings 신규 항목 추가(§7.4). ChannelStats.bus_load_pct 경과 시간 기반 계산으로 수정(§4.2). 데이터 흐름도 tx_echo 경로 추가(§3.3).** |
> | **Rev 13.0** | **검수보고서 P0/P1/P2 반영: CANWorker.update_db() clear_cache 순서 수정(§5.1), DbParser.update_db() 죽은 코드 제거(§5.4), WaveformGenerator 스레드 안전성 주석 보강(§8.4a), TraceModel LIN 색상 주입 방식 및 표시 row 상한 추가(§7.3), SimMessage.msg_id 및 remove_message(msg_id) 명세(§5.5), encode_fn 바인딩 경로 명시(§8.4a, M5), Graph 색상 정책을 신호별 고유 색상으로 확정(§8.5, §13), QSettings app_name 추가 및 ig/messages v1.1 예정으로 정정(§7.4), 메모리 예산 200신호 시나리오 보정(§10)., **Dock 레이아웃 정책 변경: Trace Monitor / Graphics / Simulation·IG를 QDockWidget으로 전환해 on/off 및 위치 이동 가능. Graphics와 Simulation·IG floating 허용. 상단 메뉴바와 하단 상태바는 고정 영역으로 명시. QSettings window/state에 Dock visibility/floating/position 저장 요구 추가.** |

---

## 0. AI 구현 규칙 (최우선 적용)

> **이 섹션은 AI가 코드를 생성하기 전에 반드시 읽어야 한다. 아래 규칙은 어떤 상황에서도 변경 불가.**

### 0.1 아키텍처 불변 규칙

```
[AI IMPLEMENTATION RULES]

1. DO NOT change architecture without explicit instruction.
2. DO NOT move decode logic outside CANWorker.
3. DO NOT access UI widgets from worker threads — Signal only.
4. ALWAYS use locks where specified (_stats_lock, _parser_lock, _messages_lock).
5. ParsedMessage is FROZEN (immutable). DO NOT modify after creation.
6. ALL inter-thread communication MUST use Qt Signal (QueuedConnection).
7. DO NOT replace numpy-based NumpySignalBuffer with list-based structures.
8. DO NOT introduce blocking calls in UI thread.
9. DO NOT implement classes in a different order than [IMPLEMENTATION ORDER].
10. DO NOT add fields to ParsedMessage — it is P0 frozen.
11. SimWorker.run() 내부 리스트 복사는 반드시 list() 생성자 사용 — 아래 [SimWorker 복사 규칙] 참조.
12. 비동기 작업 객체(AsyncDbLoader 등)는 절대 함수 내 로컬 변수로 할당 금지 — 즉시 GC되어 Segfault 발생. 반드시 self._loader 형태로 인스턴스 변수에 바인딩.
```

```
[WORKER STATE MACHINE — AI STRICT]

INIT
  ↓ start()
RUNNING
  ↓ stop()
STOPPING
  ↓ run() 종료
STOPPED

예외 경로:
RUNNING
  ↓ CAN Error + Retry 초과
STOPPED (error_occurred Signal emit 후 자동 전이)

금지:
INIT    → STOPPED  (start() 없이 stop() 호출 금지)
STOPPED → RUNNING  (재사용 금지 — 새 인스턴스 생성)
RUNNING → INIT     (상태 롤백 금지)
```

```
[SimWorker 복사 규칙 — AI STRICT]
- list(self._messages) : 반드시 list() 생성자 사용. 얕은 복사 의도적.
- SimMessage 객체는 원본 공유 — next_send_at 갱신이 원본에 반영되는 것이 의도.
- deepcopy 교체 금지 : 타이밍 드리프트 보정 무력화됨.
- = 단순 할당 금지 : 순회 중 RuntimeError 유발.
- .copy() 메서드 금지 : list()와 동일하나 의도 불명확 — list() 통일.
```

### 0.2 스레드 소유권

```
[THREAD OWNERSHIP]

Main Thread (UI):
  - 모든 UI 위젯 접근
  - MessageDispatcher.on_message() (QueuedConnection으로 수신)
  - QTimer 핸들러 (flush_trace, flush_graph, flush_stats)
  - AsyncDbLoader 완료 슬롯 (_on_db_loaded)
  - ChannelManager.add_channel() / remove_channel()

Worker Threads:
  - CANWorker.run()  → recv() + decode() + emit Signal
  - SimWorker.run()  → perf_counter 루프 + bus.send()
  - LogWorker.run()  → queue 소비 + 파일 write
  - AsyncDbLoader._run() → DbParser.load() (daemon thread)

Cross-Thread Rules:
  Worker → UI direct access : FORBIDDEN (crash 유발)
  UI → Worker direct call   : ALLOWED (thread-safe 메서드만)
  Cross-thread data transfer : Qt Signal (QueuedConnection) ONLY

VirtualNodeWorker Thread:
  - on_message(msg: ParsedMessage) 콜백 (CANWorker Signal → QueuedConnection으로 수신)
  - on_timer(interval_ms) 주기 콜백
  - bus.send() → CANWorker.send() thread-safe API만 호출 가능
  주의: UI 접근 금지, 노드 예외는 반드시 격리 (전체 시스템 전파 금지)
```

### 0.3 전역 에러 정책

```
[ERROR POLICY]

CANWorker.recv() 실패:
  → exponential backoff [1,2,4,8,16]초, MAX_RETRY=5
  → error_occurred Signal emit
  → MAX_RETRY 초과 시 break (수동 재연결 필요)

DbParser.decode() 실패 / arb_id 없음:
  → (None, None) 반환
  → exception raise 절대 금지

DbParser.load() 실패:
  → False 반환, self._db = None 유지
  → 시스템 계속 동작 (Graceful Degradation)

LogQueue.put() 실패 (Queue Full):
  → drop_count 증가
  → 통신 루프 blocking 절대 금지

MessageStore overflow:
  → drop_count 정확히 계산 (flush() 시점에 산출)
  → deque auto-drop 활용

예외 미처리:
  → logging 후 가능하면 continue
  → UI thread exception: StatusBar 표시 후 계속
```

### 0.4 구현 순서

```
[IMPLEMENTATION ORDER — 이 순서를 반드시 따를 것]

STEP 1 : ParsedMessage          ← P0 동결. 이후 변경 금지.
STEP 2 : ChannelStats
STEP 3 : MessageStore
STEP 4 : DbParser + 단위 테스트
STEP 5 : CANWorker (virtual 인터페이스, DB 없이)
STEP 6 : MessageDispatcher
STEP 7 : NumpySignalBuffer + SignalBufferRegistry
STEP 8 : LogQueue + LogWorker
STEP 9 : SimMessage + SimWorker
STEP 10: UI 통합 (TraceModel → Trace Dock → MainWindow)
STEP 11: 4채널 + DB 핫스왑 + Bus Statistics
```

```
[STEP 완료 기준 — AI는 다음 STEP 진행 전 이 기준을 확인할 것]

STEP 1 : ParsedMessage(ch_id=0, timestamp=0.0, arb_id=0x1A0, dlc=8, data=b'\x00'*8) 생성 후
         pm.ch_id = 1 시도 → FrozenInstanceError 발생하면 OK.
STEP 4 : pytest tests/test_db_parser.py -v 전체 통과.
STEP 5 : virtual 인터페이스로 CANWorker 실행 시 콘솔에 ParsedMessage repr 출력 확인.
STEP 8 : stop() 직전 큐에 남은 메시지가 ASC 파일 End TriggerBlock 앞에 기록됨 확인.
STEP 9 : 100ms 주기 메시지 전송 → 실제 간격 95~105ms 이내 (time.perf_counter()로 측정).
```

### 0.5 컴포넌트 계약 템플릿

> 모든 주요 클래스의 docstring은 아래 형식을 따른다.

```python
"""
THREAD  : Main Thread | Worker Thread (실행 스레드 명시)
INPUT   : 허용 입력 타입 및 제약
OUTPUT  : emit Signal 또는 반환값
DO NOT  : 이 클래스에서 절대 하지 말아야 할 것
"""
```

---

## 1. 프로젝트 개요

### 1.1 목표

PySide6 기반 경량 고성능 CAN/LIN 네트워크 분석·시뮬레이션 도구.

- UI 멈춤 없이 **5,000 fps** 이상 수신 처리
- **최대 4채널** 독립 동시 운용
- DBC/LDF 없이 RAW 통신 가능. DB 로드 시 신호 해석·Graph 자동 활성
- **프로세스 메모리 200MB 이하** (4채널 풀 가동)
- 단일 실행 파일 `.exe` 배포 (PyInstaller)

### 1.2 기능 범위

| In-Scope (v1.0) | 상태 | Future Scope |
|:---|:---:|:---|
| **Trace:** CAN/LIN 실시간 추적, 4채널, HW/SW 필터, Tx/Rx/Error 컬러링 | ✅ M3 | UDS 진단 |
| **Graph:** DBC/LDF 기반 신호 그래프 (DB 없으면 비활성) | ✅ M4 | Replay (ASC/BLF) |
| **Sim:** CANoe IG 스타일 주기 전송, Physical/Raw Hex 입력 | ✅ M5 | BLF 고급 포맷 |
| **DB:** DBC/LDF 비동기 로딩, Graceful Degradation, 메시지 정의 캐싱 | ✅ M6 | |
| **Log:** ASC 우선, BLF/CSV 추가, 비동기, Log Rotation 100MB | ✅ M6 | |
| **Virtual Node Engine:** Python 스크립트 기반 CAPL 대체 노드 | ✅ M7 | 핫리로드, arb_id 필터링 |
| **H/W:** Vector (VN16xx), Kvaser, virtual, SocketCAN, PCAN — CAN 버스 | ✅ M6 | |
| **H/W:** LIN 버스 (python-can LinBus, Vector LIN) | 🔲 M8 | |
| **배포:** PyInstaller 단일 .exe | 🔲 최종 검증 필요 | |

---

## 2. 기술 스택

| 구분 | 기술 | 라이선스 |
|:---|:---|:---|
| UI | PySide6 | LGPL |
| 그래프 | PyQtGraph | MIT |
| 통신 | python-can | MIT |
| DB 파싱 | cantools (DBC), ldfparser (LDF) | MIT |
| 데이터 구조 | collections.deque, queue.Queue | 표준 |
| 수치 연산 | numpy | BSD |
| 동시성 | threading.Lock, threading.Thread | 표준 |
| 배포 | PyInstaller | MIT |
| 테스트 | pytest, pytest-qt, pytest-mock, pytest-cov | MIT |

**개발환경 설정:**

```bash
python -m venv venv && venv\Scripts\activate   # Windows
pip install -r requirements.txt -r requirements-dev.txt
```

`requirements.txt`: `PySide6 pyqtgraph python-can cantools ldfparser numpy`

`requirements-dev.txt`: `pytest pytest-qt pytest-mock pytest-cov pyinstaller`

```
[PYTEST ENVIRONMENT RULES]

사용:  python -m pytest
금지:  uv run pytest  /  uv 가상환경

이유:
pytest-qt + PySide6 조합에서 uv isolated environment는
Qt plugin 경로 충돌을 유발하여 Qt Warning 발생 또는
테스트 실패 원인이 됨.
반드시 python -m venv 로 생성한 시스템 Python 환경 사용.
```

**.gitignore 핵심:**
```
venv/ __pycache__/ *.pyc dist/ build/
*.spec
!build.spec          # 배포 핵심 설정 — 버전관리 필수
*.dbc *.ldf
!tests/fixtures/*.dbc !tests/fixtures/*.ldf
```

---

## 3. 시스템 아키텍처

### 3.1 계층 구조

```
┌─────────────────────────────────────────────┐
│  Presentation  app/, widgets/               │
│  Main Thread 전용. 렌더링 + QTimer만.         │
├─────────────────────────────────────────────┤
│  Service       core/                        │
│  ChannelManager, CANWorker×4, SimWorker×4,  │
│  LogWorker, MessageDispatcher, AsyncDbLoader│
├─────────────────────────────────────────────┤
│  Data          models/                      │
│  ParsedMessage, ChannelStats, MessageStore, │
│  NumpySignalBuffer, LogQueue, SimStateStore │
├─────────────────────────────────────────────┤
│  Infrastructure  python-can                 │
│  Vector / Kvaser / virtual                  │
└─────────────────────────────────────────────┘
```

### 3.2 스레드 구성

| 스레드 | 역할 |
|:---|:---|
| Main Thread | UI, QTimer 배치 갱신. decode·파일 I/O 금지. |
| CANWorker×N (QThread) | recv() → decode() → ParsedMessage emit |
| LogWorker (QThread) | LogQueue 소비, 파일 write, 1초 flush, Log Rotation |
| SimWorker×N (QThread) | perf_counter 루프, 주기 전송. 유휴 시 sleep(0.1). |
| DB 로딩 (daemon Thread) | DbParser.load() 비동기. 완료 시 Signal emit. |

### 3.3 데이터 흐름

```
[H/W Bus CH1~4]
  │ python-can Bus.recv() (blocking, timeout=0.1s)
  ▼
[CANWorker-N]  ← DbParser 주입 (_parser_lock 보호)
  1) recv() → python-can Message
  2) DbParser.decode_with_name(arb_id, data) → signals | None
  3) ParsedMessage 생성 (frozen)
  4) _rx_bits 누적
  Signal: parsed_message_received(ParsedMessage)  ← QueuedConnection
  ▼
[MessageDispatcher]  ← Main Thread. fan-out만. decode 없음.
  ├─► [MessageStore]         deque(100k) + Lock
  ├─► [SignalBufferRegistry] NumpySignalBuffer × 신호 수
  ├─► [LogQueue]             Queue(50k), drop 정책
  └─► [SimStateStore]        dict{ch_id: {sig: val}}

[SimWorker-N]  ← Worker Thread
  1) SimMessage.is_due() 확인
  2) CANWorker.send() 호출 (is_tx=True 에코 생성)
  3) CANWorker.increment_tx(frame_bits) 호출
  Signal: tx_echo(ParsedMessage[is_tx=True])  ← QueuedConnection
  ▼
[MessageDispatcher]  ← Main Thread. tx_echo도 동일 fan-out 경로.
  └─► [MessageStore] → TraceModel (파랑 컬러링)

[QTimer  50ms] → MessageStore.flush() → TraceModel.append_batch()
[QTimer 100ms] → SignalBufferRegistry.get_view() → pyqtgraph setData()
[QTimer   1s ] → CANWorker.get_stats() → Bus Statistics UI
[LogWorker]    → LogQueue.get() → 파일 write (청크 5,000건)
```

```
[CRITICAL SHUTDOWN SEQUENCE — closeEvent() 구현 시 이 순서 100% 준수]

1. 모든 QTimer 정지 (UI 갱신 중단)
2. AsyncDbLoader Signal disconnect (self._db_loader.db_loaded.disconnect)
3. ChannelManager.all() 순회 → ctx.worker.stop() 호출
4. ctx.sim_worker가 있다면 stop() 호출
5. self._log_worker.stop() 호출
6. 모든 Worker/QThread에 대해 .wait() 호출 — 스레드 완전 종료 보장
7. self._db_loader = None (GC 허용)

★ terminate() 사용 절대 금지 — 하드웨어 포트 미해제 → BSoD/Segfault
★ stop()은 종료 플래그만 설정하고 wait()는 호출하지 않는다. wait()는 closeEvent()/remove_channel()에서만 수행한다.
★ stop() 없이 .wait() 단독 호출 금지 — 데드락
★ QTimer 정지 전 stop() 호출 금지 — 타이머 슬롯이 종료된 Worker 접근 가능
★ AsyncDbLoader disconnect는 QTimer 정지 직후, Worker stop() 전에 수행
```

```
[UI THROTTLING RULE — _flush_trace() 구현 시 준수]

_flush_trace() 1회 호출 당 최대 2,000 row append 제한.
초과 데이터는 MessageStore._pending에 잔류 → 다음 flush(50ms) 주기에 처리.

목적:
  5,000fps 이상 고부하 시 TraceModel.append_batch()가
  UI Thread를 독점(> 50ms)하여 다른 QTimer 슬롯이
  기아 상태(starvation)에 빠지는 현상 방지.

구현 힌트:
  batch = self._message_store.flush(limit=2000)
```

---

## 4. 핵심 데이터 모델

### 4.1 ParsedMessage — P0 동결. 절대 변경 금지.

```python
# models/parsed_message.py
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class ParsedMessage:
    """
    THREAD  : 생성=CANWorker, 읽기=모든 스레드 (immutable이므로 Lock 불필요)
    DO NOT  : 필드 추가·변경. frozen이므로 생성 후 수정 불가.
    """
    # H/W 원시 필드
    ch_id:     int          # 0~3
    timestamp: float        # python-can 타임스탬프 (초)
    arb_id:    int          # CAN Arbitration ID | LIN Protected ID (8비트)
    dlc:       int          # 0~15 (CAN FD: 9→12B … 15→64B)
    data:      bytes        # 최대 64바이트

    is_fd:     bool = False
    is_remote: bool = False
    is_error:  bool = False
    is_tx:     bool = False  # SimWorker 송신 에코 (Trace 파랑 컬러링)
    is_brs:    bool = False  # CAN FD BRS 플래그

    # 디코딩 결과 (CANWorker 내부에서 채움)
    signals:   dict | None = None   # {"EngSpeed": 1200.0} | None
    msg_name:  str  | None = None   # "EngineData" | None

# CAN FD DLC 매핑: 9→12, 10→16, 11→20, 12→24, 13→32, 14→48, 15→64
# LIN arb_id decode 시: arb_id & 0x3F 로 Frame ID 추출
# is_tx 사용: SimWorker 전송 시 is_tx=True ParsedMessage를 Dispatcher에 emit
```

### 4.2 ChannelStats

```python
# models/channel_stats.py
from dataclasses import dataclass

@dataclass
class ChannelStats:
    """THREAD: 생성=Main Thread (get_stats() 반환값). 불변 스냅샷."""
    rx_count:    int = 0
    tx_count:    int = 0
    error_count: int = 0
    rx_bits:     int = 0
    tx_bits:     int = 0
    bitrate:     int = 500_000
    elapsed_sec: float = 1.0   # get_stats() 호출 간격 (실제 경과 시간)

    @staticmethod
    def calc_frame_bits(dlc: int, is_fd: bool) -> int:
        # CAN 2.0B: 47 + dlc*8 bits (bit stuffing 미포함)
        # CAN FD  : 67 + dlc*8 bits (Arbitration Phase 보수적 근사)
        # TODO(v1.1): data_bitrate 분리 계산, LIN 프레임(~34bit) 분기 추가
        return (67 if is_fd else 47) + dlc * 8

    @property
    def bus_load_pct(self) -> float:
        """
        실제 경과 시간(elapsed_sec) 기반으로 계산.
        QTimer 주기 변경에도 정확한 수치 유지.
        elapsed_sec는 CANWorker.get_stats()에서 perf_counter() 차분으로 산출.
        """
        if self.bitrate <= 0 or self.elapsed_sec <= 0:
            return 0.0
        total_bits = self.rx_bits + self.tx_bits
        return min(100.0, total_bits / (self.bitrate * self.elapsed_sec) * 100.0)
```

---

## 5. 서비스 레이어 (core/)

### 5.1 CANWorker

```python
# core/can_worker.py
import can
from enum import Enum, auto
from threading import Lock
from PySide6.QtCore import QThread, Signal
from models.parsed_message import ParsedMessage
from models.channel_stats import ChannelStats

MAX_RETRY = 5
RETRY_BACKOFF_SEC = [1, 2, 4, 8, 16]
_CAN_OVERHEAD_BITS = 47

class WorkerState(Enum):
    INIT     = auto()
    RUNNING  = auto()
    STOPPING = auto()
    STOPPED  = auto()

class CANWorker(QThread):
    """
    THREAD  : Worker Thread (QThread)
    INPUT   : ChannelConfig, DbParser (주입)
    OUTPUT  : parsed_message_received(ParsedMessage), error_occurred(str),
              connection_state_changed(int, bool)
    DO NOT  : UI 접근, decode 외부 위탁, blocking call in stop()
    """
    parsed_message_received  = Signal(object)
    error_occurred           = Signal(str)
    connection_state_changed = Signal(int, bool)   # ch_id, is_connected

    def __init__(self, ch_id: int, config: "ChannelConfig", db: "DbParser") -> None:
        super().__init__()
        self._ch_id       = ch_id
        self._config      = config
        self._db          = db
        self._state       = WorkerState.INIT
        self._stop        = False
        self._stats_lock  = Lock()   # get_stats() 원자성 보장
        self._parser_lock = Lock()   # DB 핫스왑 레이스 컨디션 방어
        self._bus         = None
        self._rx_count = self._rx_bits = self._err_count = self._tx_count = self._tx_bits = 0
        self._last_stats_time: float = 0.0   # bus_load_pct 경과 시간 측정용

    def update_db(self, db: "DbParser") -> None:
        """Main Thread에서 호출. parser_lock + clear_cache() 포함."""
        db.clear_cache()
        with self._parser_lock:
            self._db = db

    def send(self, msg: "can.Message") -> None:
        """SimWorker에서 호출. bus 참조는 _connect_and_listen 범위 내에서만 유효."""
        if self._bus is not None:
            self._bus.send(msg)

    def increment_tx(self, frame_bits: int) -> None:
        """SimWorker가 전송 시 호출. frame_bits는 ChannelStats.calc_frame_bits() 결과값."""
        with self._stats_lock:
            self._tx_count += 1
            self._tx_bits  += frame_bits

    def get_stats(self) -> ChannelStats:
        """QTimer(1s) 슬롯에서 호출. read + clear 원자적 수행."""
        import time
        now = time.perf_counter()
        with self._stats_lock:
            elapsed = now - self._last_stats_time if self._last_stats_time > 0 else 1.0
            s = ChannelStats(
                rx_count=self._rx_count, tx_count=self._tx_count,
                error_count=self._err_count, rx_bits=self._rx_bits,
                tx_bits=self._tx_bits,
                bitrate=self._config.bitrate,
                elapsed_sec=elapsed,
            )
            self._rx_count = self._tx_count = self._err_count = self._rx_bits = self._tx_bits = 0
            self._last_stats_time = now
        return s

    def run(self) -> None:
        self._state = WorkerState.RUNNING
        self._bus   = None
        retry_count = 0
        while not self._stop:
            try:
                self._connect_and_listen()
                break   # 정상 종료 (stop() 호출)
            except can.CanError as e:
                retry_count += 1
                self.connection_state_changed.emit(self._ch_id, False)
                if retry_count > MAX_RETRY:
                    self.error_occurred.emit(
                        f"CH{self._ch_id}: 재연결 한계 초과. 수동 재연결 필요.")
                    break
                wait = RETRY_BACKOFF_SEC[min(retry_count - 1, len(RETRY_BACKOFF_SEC) - 1)]
                self.error_occurred.emit(
                    f"CH{self._ch_id}: 연결 오류 — {wait}초 후 재시도 ({retry_count}/{MAX_RETRY})")
                # 0.1초 폴링으로 _stop 플래그 확인 (최대 16초 블로킹 방지)
                for _ in range(int(wait * 10)):
                    if self._stop:
                        self._state = WorkerState.STOPPED
                        return
                    self.msleep(100)
        self._state = WorkerState.STOPPED

    def _connect_and_listen(self) -> None:
        with can.Bus(interface=self._config.interface,
                     channel=self._config.channel,
                     bitrate=self._config.bitrate,
                     fd=self._config.fd_mode) as bus:
            self._bus = bus
            if self._config.hw_id_filter is not None:
                bus.set_filters([{
                    "can_id": self._config.hw_id_filter,
                    "can_mask": self._config.hw_id_mask or 0x7FF,
                    "extended": False,
                }])
            self.connection_state_changed.emit(self._ch_id, True)
            while not self._stop:
                raw = bus.recv(timeout=0.1)
                if raw is None:
                    continue
                with self._parser_lock:
                    signals, msg_name = self._db.decode_with_name(
                        raw.arbitration_id, raw.data)
                msg = ParsedMessage(
                    ch_id=self._ch_id, timestamp=raw.timestamp,
                    arb_id=raw.arbitration_id, dlc=raw.dlc,
                    data=bytes(raw.data), is_fd=raw.is_fd,
                    is_remote=raw.is_remote_frame, is_error=raw.is_error_frame,
                    is_brs=getattr(raw, 'bitrate_switch', False),
                    signals=signals, msg_name=msg_name,
                )
                frame_bits = ChannelStats.calc_frame_bits(len(raw.data), raw.is_fd)
                with self._stats_lock:
                    self._rx_count += 1
                    self._rx_bits  += frame_bits
                    if raw.is_error_frame:
                        self._err_count += 1
                self.parsed_message_received.emit(msg)
            self._bus = None

    def stop(self) -> None:
        """종료 플래그만 설정. wait()는 호출자가 수행(closeEvent/remove_channel)."""
        if self._state == WorkerState.INIT:
            return
        if self._state == WorkerState.STOPPED:
            return
        self._state = WorkerState.STOPPING
        self._stop  = True
```

### 5.2 MessageDispatcher

```python
# core/dispatcher.py
from PySide6.QtCore import QObject, Slot

class MessageDispatcher(QObject):
    """
    THREAD  : Main Thread (QueuedConnection으로 수신)
    INPUT   : ParsedMessage (CANWorker Signal)
    OUTPUT  : 각 데이터 모델로 fan-out
    DO NOT  : decode 수행, blocking call
    """
    def __init__(self, store, registry, log_queue, sim_store) -> None:
        super().__init__()
        self._store    = store
        self._registry = registry
        self._log_q    = log_queue
        self._sim      = sim_store

    @Slot(object)
    def on_message(self, msg: "ParsedMessage") -> None:
        self._store.append(msg)
        self._log_q.put(msg)
        if msg.signals:
            for sig_name, value in msg.signals.items():
                self._registry.append(msg.ch_id, sig_name, msg.timestamp, float(value))
            self._sim.update(msg.ch_id, msg.signals)

    @Slot(str)
    def on_error(self, error_msg: str) -> None:
        pass  # MainWindow에서 별도 연결
```

### 5.3 ChannelManager

```python
# core/channel_manager.py
from dataclasses import dataclass
from PySide6.QtCore import Qt

@dataclass
class ChannelConfig:
    interface:    str
    channel:      int
    bitrate:      int
    bus_type:     str  = "can"          # "can" | "lin"  ← M8 신규
    lin_mode:     str  = "slave"        # "master" | "slave" | "listen_only"  ← M8 신규
    fd_mode:      bool = False
    data_bitrate: int  = 2_000_000
    app_name:     str  = "PyCANoe"
    db_path:      str | None = None
    hw_id_filter: int | None = None
    hw_id_mask:   int | None = None
    socketcan_ifname: str = "vcan0"     # ← M8 신규
    pcan_channel:     str = "PCAN_USBBUS1"  # ← M8 신규

    def validate(self) -> None:
        """add_channel() 호출 전 필수 검증. 실패 시 ValueError."""
        if self.channel < 0:
            raise ValueError("channel은 0 이상이어야 함")
        if self.bus_type not in {"can", "lin"}:
            raise ValueError("bus_type은 'can' 또는 'lin'만 허용")
        if self.bitrate <= 0:
            raise ValueError("bitrate는 0보다 커야 함")
        if self.fd_mode and self.data_bitrate < self.bitrate:
            raise ValueError("CAN FD data_bitrate는 bitrate 이상이어야 함")
        if self.bus_type == "lin":
            if self.bitrate not in {9600, 19200}:
                raise ValueError("LIN bitrate는 9600 또는 19200만 허용")
            if self.lin_mode not in {"master", "slave", "listen_only"}:
                raise ValueError("lin_mode는 master/slave/listen_only만 허용")

@dataclass
class ChannelContext:
    ch_id:      int
    config:     ChannelConfig
    worker:     "CANWorker"
    db_parser:  "DbParser"
    sim_worker: "SimWorker | None" = None

class ChannelManager:
    MAX_CHANNELS = 4

    def __init__(self, dispatcher: "MessageDispatcher") -> None:
        self._channels: dict[int, ChannelContext] = {}
        self._dispatcher = dispatcher

    def add_channel(self, ch_id: int, config: ChannelConfig) -> ChannelContext:
        if len(self._channels) >= self.MAX_CHANNELS:
            raise ValueError(f"최대 채널 수({self.MAX_CHANNELS}) 초과")
        config.validate()
        db     = DbParser(config.db_path)
        worker = CANWorker(ch_id, config, db)
        # QueuedConnection 명시 — 스레드 실행 위치 보장
        worker.parsed_message_received.connect(
            self._dispatcher.on_message, Qt.ConnectionType.QueuedConnection)
        worker.error_occurred.connect(
            self._dispatcher.on_error, Qt.ConnectionType.QueuedConnection)
        ctx = ChannelContext(ch_id, config, worker, db)
        self._channels[ch_id] = ctx
        return ctx

    def remove_channel(self, ch_id: int) -> None:
        ctx = self._channels.pop(ch_id)
        # [AI STRICT — 종료 순서 준수]
        # SimWorker가 CANWorker.send()를 호출 중일 수 있으므로
        # SimWorker를 반드시 먼저 완전히 종료한 후 CANWorker를 종료한다.
        # CANWorker.stop() 먼저 호출 시 _bus=None 상태에서 send() 호출 → NoneType crash.
        if ctx.sim_worker:
            ctx.sim_worker.stop()
            ctx.sim_worker.wait()
        ctx.worker.stop()
        ctx.worker.wait()

    def get(self, ch_id: int) -> "ChannelContext | None":
        return self._channels.get(ch_id)

    def all(self) -> "list[ChannelContext]":
        return list(self._channels.values())
```

```
[CONFIG VALIDATION — add_channel() 호출 전 검증 필수]

공통:
  channel >= 0
  bus_type ∈ {"can", "lin"}

CAN:
  bitrate > 0

CAN FD (fd_mode=True):
  data_bitrate >= bitrate

LIN (bus_type="lin"):
  bitrate ∈ {9600, 19200}
  lin_mode ∈ {"master", "slave", "listen_only"}

검증 실패 시: ValueError raise (assert 사용 금지 — 배포 빌드에서 제거됨)
```

### 5.4 DbParser

```python
# core/db_parser.py
import cantools
import ldfparser
from typing import Any

_MISS = object()   # "조회했으나 없음" sentinel. None과 구분.

class DbParser:
    """
    THREAD  : 인스턴스별 독립 소유. 채널 간 공유 시 Lock 필수.
    INPUT   : arb_id: int, data: bytes
    OUTPUT  : (signals: dict|None, msg_name: str|None)
    DO NOT  : exception raise, Qt import
    """
    def __init__(self, path: str | None = None) -> None:
        self._db   = None
        self._type = None   # "dbc" | "ldf" | None
        self._msg_def_cache: dict[int, Any] = {}
        if path:
            self.load(path)

    def load(self, path: str) -> bool:
        try:
            if path.lower().endswith(".dbc"):
                self._db, self._type = cantools.database.load_file(path), "dbc"
            elif path.lower().endswith(".ldf"):
                self._db, self._type = ldfparser.parse_ldf(path), "ldf"
            else:
                return False
            self.clear_cache()
            return True
        except Exception:
            self._db = self._type = None
            return False

    def clear_cache(self) -> None:
        self._msg_def_cache.clear()

    def decode(self, arb_id: int, data: bytes) -> dict | None:
        signals, _ = self.decode_with_name(arb_id, data)
        return signals

    def decode_with_name(self, arb_id: int, data: bytes) -> "tuple[dict|None, str|None]":
        """
        cantools는 없는 arb_id에 None이 아닌 KeyError를 던진다.
        _MISS sentinel으로 캐시하여 매 프레임 재탐색 방지.
        """
        if self._db is None:
            return None, None
        try:
            if self._type == "dbc":
                if arb_id not in self._msg_def_cache:
                    try:
                        self._msg_def_cache[arb_id] = self._db.get_message_by_frame_id(arb_id)
                    except KeyError:
                        self._msg_def_cache[arb_id] = _MISS
                msg_def = self._msg_def_cache[arb_id]
                if msg_def is _MISS:
                    return None, None
                return self._db.decode_message(arb_id, data), msg_def.name

            elif self._type == "ldf":
                frame_id = arb_id & 0x3F
                if frame_id not in self._msg_def_cache:
                    try:
                        self._msg_def_cache[frame_id] = self._db.get_frame(frame_id)
                    except Exception:
                        self._msg_def_cache[frame_id] = _MISS
                frame = self._msg_def_cache[frame_id]
                if frame is _MISS:
                    return None, None
                return frame.parse(bytes(data)), frame.name

            return None, None
        except Exception:
            return None, None

    @property
    def is_loaded(self) -> bool:
        return self._db is not None

    @property
    def db_type(self) -> "str | None":
        return self._type


# core/async_db_loader.py
import threading
from PySide6.QtCore import QObject, Signal

class AsyncDbLoader(QObject):
    """
    THREAD  : _run()=daemon Thread, Signal 수신=Main Thread
    DO NOT  : Signal emit 전 self 참조 없애지 말 것 (GC → Segfault)

    올바른 사용:
        self._db_loader = AsyncDbLoader(parser, path)  # self에 저장 필수
        self._db_loader.db_loaded.connect(self._on_db_loaded)
        self._db_loader.start_loading()

    연속 로드 시 이전 로더 Signal disconnect — MainWindow._on_load_db_clicked() 핸들러에서 처리:
        if self._db_loader:
            try: self._db_loader.db_loaded.disconnect(self._on_db_loaded)
            except RuntimeError: pass
    ★ disconnect 위치: MainWindow._on_load_db_clicked() 내부. start_loading() 전에 실행.
    ★ _on_db_loaded() 또는 AsyncDbLoader.__init__() 내부에서 처리 금지.
    """
    db_loaded = Signal(bool, object)   # (success, DbParser)

    def __init__(self, parser: "DbParser", path: str) -> None:
        super().__init__()
        self._parser, self._path = parser, path

    def start_loading(self) -> None:
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        ok = self._parser.load(self._path)
        self.db_loaded.emit(ok, self._parser)
```

### 5.5 SimWorker

```python
# core/sim_worker.py
import time
import uuid
from dataclasses import dataclass, field
from threading import Lock
from PySide6.QtCore import QThread, Signal

@dataclass
class SimMessage:
    arb_id:       int
    data:         bytes
    interval_ms:  float
    msg_id:       str   = field(default_factory=lambda: uuid.uuid4().hex[:8])
    next_send_at: float = field(default_factory=time.perf_counter)
    start_time:   float = field(default_factory=time.perf_counter)
    waveforms:    "dict[str, WaveformGenerator] | None" = None
    encode_fn:    "Callable[[dict], bytes] | None" = None

    def is_due(self, now: float) -> bool:
        return now >= self.next_send_at

    def update_next(self, now: float) -> None:
        self.next_send_at += self.interval_ms / 1000.0
        # 크게 밀렸으면 리셋 (폭주 방지)
        if now - self.next_send_at > self.interval_ms / 1000.0:
            self.next_send_at = now + self.interval_ms / 1000.0

    def to_can_message(self, data: bytes | None = None):
        import can
        payload = self.data if data is None else data
        return can.Message(arbitration_id=self.arb_id, data=payload,
                           is_extended_id=False)

class SimWorker(QThread):
    """
    THREAD  : Worker Thread
    INPUT   : SimMessage (add_message, Main Thread에서 호출)
    OUTPUT  : CANWorker.send() 직접 호출 + tx_echo Signal
    DO NOT  : UI 접근, _messages 무Lock 접근
    """
    tx_echo = Signal(object)   # is_tx=True ParsedMessage → Dispatcher 에코

    def __init__(self, ch_id: int, bus_sender: "CANWorker") -> None:
        super().__init__()
        self._ch_id         = ch_id
        self._bus_sender    = bus_sender
        self._stop          = False
        self._messages:     list[SimMessage] = []
        self._messages_lock = Lock()   # add/remove(Main) + _send(Worker) 보호

    def run(self) -> None:
        while not self._stop:
            with self._messages_lock:
                # [AI STRICT — SimWorker 복사 규칙]
                # 반드시 list() 생성자 사용. 얕은 복사 의도적.
                # SimMessage 객체는 원본 공유 — next_send_at 갱신이 원본에 반영되는 것이 의도.
                # deepcopy 교체 금지(타이밍 드리프트 보정 무력화), = 할당 금지(RuntimeError).
                msgs_snapshot = list(self._messages)

            if not msgs_snapshot:
                time.sleep(0.1)
                continue

            now = time.perf_counter()
            self._send_due_messages(now, msgs_snapshot)

            next_wakeup = min(m.next_send_at for m in msgs_snapshot)
            sleep_sec   = next_wakeup - time.perf_counter()
            if sleep_sec > 0.002:
                time.sleep(sleep_sec - 0.001)
            while time.perf_counter() < next_wakeup:
                pass   # busy-wait 마지막 1ms (CANoe 동일 방식)

    def _send_due_messages(self, now: float, msgs: list) -> None:
        from models.parsed_message import ParsedMessage
        from models.channel_stats import ChannelStats
        for sm in msgs:
            if sm.is_due(now):
                # [AI STRICT] waveforms.get_value()는 Worker Thread에서 read-only 호출.
                # Main Thread에서 points 리스트를 편집할 경우 반드시 SimWorker 정지 후 수행하거나
                # WaveformGenerator 내부 _points_lock으로 보호한다.
                if sm.waveforms and sm.encode_fn:
                    elapsed_ms = (now - sm.start_time) * 1000.0
                    sig_vals = {
                        name: wg.get_value(elapsed_ms)
                        for name, wg in sm.waveforms.items()
                    }
                    data = sm.encode_fn(sig_vals)
                else:
                    data = sm.data
                self._bus_sender.send(sm.to_can_message(data=data))
                frame_bits = ChannelStats.calc_frame_bits(len(data), is_fd=False)
                self._bus_sender.increment_tx(frame_bits)
                sm.update_next(now)
                # Trace 컬러링용 Tx 에코
                echo = ParsedMessage(
                    ch_id=self._ch_id, timestamp=time.time(),
                    arb_id=sm.arb_id, dlc=len(data), data=data, is_tx=True)
                self.tx_echo.emit(echo)

    def add_message(self, msg: SimMessage) -> None:
        """Main Thread에서 호출."""
        with self._messages_lock:
            self._messages.append(msg)

    def remove_message(self, msg_id: str) -> None:
        """Main Thread에서 호출. msg_id 기반으로 정확히 1개 메시지만 제거."""
        with self._messages_lock:
            self._messages = [m for m in self._messages if m.msg_id != msg_id]

    def stop(self) -> None:
        """종료 플래그만 설정. wait()는 호출자가 수행(closeEvent/remove_channel)."""
        self._stop = True
```

### 5.6 LogWorker

```python
# models/log_queue.py
import queue
from threading import Lock
from models.parsed_message import ParsedMessage

class LogQueue:
    """THREAD: put()=Worker, get_queue()=LogWorker"""
    MAX_SIZE = 50_000

    def __init__(self) -> None:
        self._q         = queue.Queue(maxsize=self.MAX_SIZE)
        self._drop_lock = Lock()   # drop_count 원자성 보장 (복수 Worker 동시 put 가능)
        self.drop_count = 0

    def put(self, msg: ParsedMessage) -> None:
        try:
            self._q.put_nowait(msg)
        except queue.Full:
            with self._drop_lock:
                self.drop_count += 1   # blocking 절대 금지

    def get_queue(self) -> queue.Queue:
        return self._q


# core/log_worker.py
import os, queue
from PySide6.QtCore import QThread, Signal

MAX_FILE_BYTES = 100 * 1024 * 1024   # 100MB Log Rotation 상한

class LogWorker(QThread):
    """
    THREAD  : Worker Thread
    INPUT   : LogQueue
    DO NOT  : UI 접근, 종료 시 잔여 배치 손실 (else 블록에서 반드시 flush)
    """
    log_dropped = Signal(int)
    log_rotated = Signal(str)

    def __init__(self, log_queue: "LogQueue", path: str, fmt: str = "asc") -> None:
        super().__init__()
        self._q         = log_queue.get_queue()
        self._lq        = log_queue
        self._base_path = path
        self._fmt       = fmt
        self._running   = False

    def _make_path(self, index: int) -> str:
        base, ext = os.path.splitext(self._base_path)
        return f"{base}_{index:03d}{ext}"

    def run(self) -> None:
        # [LogWorker 종료 시퀀스 — AI 재현 필수]
        # 1. stop() → self._running = False
        # 2. 내부 while self._running 루프 탈출 (정상 종료 경로)
        # 3. while-else의 else 블록 실행 → 잔여 배치 flush → End TriggerBlock 기록
        # ★ break로 탈출(Log Rotation)하면 else 블록 미실행 — 의도적
        # ★ else 블록을 루프 밖으로 이동 금지 — 정상/Rotation 경로 구분 무력화
        self._running = True
        CHUNK = 5_000
        file_index, last_drop = 1, 0

        while self._running:
            current_path = self._make_path(file_index)
            with open(current_path, "w", encoding="utf-8") as f:
                if self._fmt == "asc":
                    from datetime import datetime
                    f.write(f"date {datetime.now().strftime('%a %b %d %I:%M:%S %p %Y')}\n")
                    f.write("base hex  timestamps absolute\ninternal events logged\n")
                    f.write("// version 8.5.0\nBegin Triggerblock\n")

                batch: list = []
                while self._running:
                    try:
                        msg = self._q.get(timeout=0.1)
                        batch.append(msg)
                        if len(batch) >= CHUNK:
                            self._write_batch(f, batch)
                            batch.clear()
                    except queue.Empty:
                        if batch:
                            self._write_batch(f, batch)
                            batch.clear()
                        f.flush()

                    if self._lq.drop_count != last_drop:
                        last_drop = self._lq.drop_count
                        self.log_dropped.emit(last_drop)

                    if f.tell() >= MAX_FILE_BYTES:
                        if self._fmt == "asc":
                            f.write("End TriggerBlock\n")
                        break   # Log Rotation
                else:
                    # 종료 시 잔여 배치 반드시 기록 (누락 방지)
                    if batch:
                        self._write_batch(f, batch)
                    if self._fmt == "asc":
                        f.write("End TriggerBlock\n")
                    break

            file_index += 1
            self.log_rotated.emit(self._make_path(file_index))

    @staticmethod
    def _write_batch(f, batch: list) -> None:
        for msg in batch:
            direction = "Tx" if msg.is_tx else "Rx"
            data_hex  = msg.data.hex(" ").upper()
            f.write(f"{msg.timestamp:.6f} {msg.ch_id + 1}  "
                    f"{msg.arb_id:X}  {direction}  d  {msg.dlc}  {data_hex}\n")

    def stop(self) -> None:
        """종료 플래그만 설정. wait()는 호출자가 수행(closeEvent/remove_channel)."""
        self._running = False
```

---

## 6. 데이터 레이어 (models/)

### 6.1 MessageStore

```python
# models/message_store.py
from collections import deque
from threading import Lock
from models.parsed_message import ParsedMessage

class MessageStore:
    """
    THREAD  : append()=Worker Thread, flush()=Main Thread ONLY
    DO NOT  : flush()를 Worker에서 호출
    """
    MAX_ROWS = 100_000   # ~10MB

    def __init__(self) -> None:
        self._buffer:  deque[ParsedMessage] = deque(maxlen=self.MAX_ROWS)
        self._pending: list[ParsedMessage]  = []
        self._lock     = Lock()
        self.drop_count = 0

    def append(self, msg: ParsedMessage) -> None:
        with self._lock:
            self._pending.append(msg)

    def flush(self, limit: int | None = None) -> list[ParsedMessage]:
        """
        QTimer(50ms) 슬롯 전용.
        limit 지정 시 최대 limit개만 반환하고 초과분은 _pending 앞쪽에 잔류시킨다.
        """
        with self._lock:
            if limit is not None and len(self._pending) > limit:
                batch = self._pending[:limit]
                self._pending = self._pending[limit:]
            else:
                batch, self._pending = self._pending, []
        overflow = max(0, len(self._buffer) + len(batch) - self.MAX_ROWS)
        if overflow > 0:
            self.drop_count += overflow
        self._buffer.extend(batch)
        return batch
```

### 6.2 NumpySignalBuffer

```
[SignalBuffer 활성화 트리거]
AsyncDbLoader.db_loaded Signal
  → MainWindow._on_db_loaded()
  → signal_registry.enable_all() 호출
DBC 로드 전 : enabled=False → append() 무시 (메모리 낭비 없음)
★ get_or_create() 내부에서 자동 enable 금지 — DBC 없는 상태에서 메모리 낭비
★ CANWorker/Dispatcher에서 enable() 직접 호출 금지 — Main Thread 전용
```

```python
# models/numpy_signal_buffer.py
import numpy as np
from threading import Lock

class NumpySignalBuffer:
    """
    THREAD  : append()=Worker Thread, get_view()=Main Thread
    DO NOT  : list로 교체 (GC 부하 급증). copy() 생략 (UI 렌더링 중 오염).
    NOTE    : 링 버퍼 꽉 찬 경우 np.concatenate()로 2회 메모리 할당 발생.
              TODO(v1.1): double-buffering으로 할당 1회로 감소 검토.
    """
    def __init__(self, max_points: int = 5_000) -> None:
        self._cap        = max_points
        self._timestamps = np.zeros(max_points, dtype=np.float64)
        self._values     = np.zeros(max_points, dtype=np.float64)
        self._index      = 0
        self._size       = 0
        self.enabled     = False
        self._lock       = Lock()

    def enable(self) -> None:  self.enabled = True
    def disable(self) -> None: self.enabled = False

    def append(self, timestamp: float, value: float) -> None:
        if not self.enabled:
            return
        with self._lock:
            self._timestamps[self._index] = timestamp
            self._values[self._index]     = value
            self._index = (self._index + 1) % self._cap
            if self._size < self._cap:
                self._size += 1

    def get_view(self) -> "tuple[np.ndarray, np.ndarray] | None":
        with self._lock:
            if self._size == 0:
                return None
            if self._size < self._cap:
                return (self._timestamps[:self._size].copy(),
                        self._values[:self._size].copy())
            i = self._index
            ts  = np.concatenate((self._timestamps[i:], self._timestamps[:i]))
            val = np.concatenate((self._values[i:],     self._values[:i]))
            return ts.copy(), val.copy()


class SignalBufferRegistry:
    """THREAD: append()=Worker(Dispatcher), get_or_create()/enable_all()=Main"""
    def __init__(self) -> None:
        self._bufs: dict[tuple[int, str], NumpySignalBuffer] = {}
        self._lock  = Lock()   # get_or_create() 동시 접근 방어 (복수 CANWorker)

    def get_or_create(self, ch_id: int, sig_name: str,
                      max_points: int = 5_000) -> NumpySignalBuffer:
        key = (ch_id, sig_name)
        with self._lock:
            if key not in self._bufs:
                self._bufs[key] = NumpySignalBuffer(max_points)
            return self._bufs[key]

    def append(self, ch_id: int, sig_name: str,
               timestamp: float, value: float) -> None:
        self.get_or_create(ch_id, sig_name).append(timestamp, value)

    def enable_all(self) -> None:
        with self._lock:
            for buf in self._bufs.values(): buf.enable()

    def disable_all(self) -> None:
        with self._lock:
            for buf in self._bufs.values(): buf.disable()
```

### 6.3 SimStateStore

```python
# models/sim_state_store.py

class SimStateStore:
    """
    THREAD  : update() = Main Thread (Dispatcher 경유)
              get()    = Main Thread (Sim Dock)
    DO NOT  : Worker Thread 직접 접근 — Main Thread 전용 모델
    """

    def __init__(self) -> None:
        self._state: dict[int, dict[str, float]] = {}   # {ch_id: {sig_name: value}}

    def update(self, ch_id: int, signals: dict) -> None:
        """Dispatcher.on_message()에서 호출. signals dict의 값을 ch_id 키로 병합."""
        self._state.setdefault(ch_id, {}).update(signals)

    def get(self, ch_id: int) -> dict:
        """Sim Dock에서 호출. 없는 채널은 빈 dict 반환."""
        return self._state.get(ch_id, {})

    def clear(self, ch_id: int) -> None:
        """채널 제거 시 호출."""
        self._state.pop(ch_id, None)
```

---

## 7. 진입점 및 UI

### 7.1 main.py (Windows 타이머 해상도)

```python
# src/main.py
import ctypes, os, sys
from PySide6.QtWidgets import QApplication
from app.main_window import MainWindow

def _set_timer_resolution() -> None:
    if os.name == 'nt':
        ctypes.windll.winmm.timeBeginPeriod(1)   # 15.6ms → 1ms

def _restore_timer_resolution() -> None:
    if os.name == 'nt':
        ctypes.windll.winmm.timeEndPeriod(1)

if __name__ == "__main__":
    _set_timer_resolution()
    try:
        app = QApplication(sys.argv)
        window = MainWindow()
        window.show()
        exit_code = app.exec()
    finally:
        _restore_timer_resolution()
    sys.exit(exit_code)
```

### 7.2 MainWindow QTimer 구조

```python
# app/main_window.py (QTimer 핵심 부분)
class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._auto_scroll = True
        self._db_loader: "AsyncDbLoader | None" = None   # GC 방지 — 반드시 self에 저장

        QTimer(self, timeout=self._flush_trace, interval=50).start()
        QTimer(self, timeout=self._flush_graph, interval=100).start()
        QTimer(self, timeout=self._flush_stats, interval=1000).start()

    def _flush_trace(self) -> None:
        batch = self._message_store.flush(limit=2000)
        if batch:
            self._trace_model.append_batch(batch)   # INPUT: list[ParsedMessage]
            if self._auto_scroll:
                self._trace_view.scrollToBottom()
        if self._message_store.drop_count > 0:
            self._show_buffer_warning(self._message_store.drop_count)

    def _flush_graph(self) -> None:
        for (ch_id, sig), item in self._plot_items.items():
            result = self._signal_registry.get_or_create(ch_id, sig).get_view()
            if result:
                item.setData(x=result[0], y=result[1])

    def _flush_stats(self) -> None:
        for ctx in self._channel_manager.all():
            stats = ctx.worker.get_stats()
            self._statusbar.update_channel_stats(ctx.ch_id, stats)
```

### 7.3 TraceModel 컬러링

```python
# models/trace_model.py (ForegroundRole 핵심)
from PySide6.QtGui import QColor
from PySide6.QtCore import Qt

COLOR_TX    = QColor("#2196F3")   # 파랑 — Tx
COLOR_ERROR = QColor("#F44336")   # 빨강 — Error
COLOR_LIN   = QColor("#7a4a00")   # 갈색 — LIN
COLOR_RX    = None                # 테마 기본색
TRACE_VISIBLE_LIMIT = 100_000     # UI 표시 상한. MessageStore.MAX_ROWS와 동일값 유지.

class TraceModel:   # QAbstractItemModel 상속
    """
    THREAD  : Main Thread 전용
    LIN 컬러링 전략:
      생성 시 ch_bus_type: dict[int, str] 주입.
      MainWindow가 ChannelManager.all()에서 ch_id별 bus_type을 추출해 전달.
      add_channel() / remove_channel() 시 MainWindow가 갱신.
      TraceModel은 ChannelManager를 직접 참조하지 않는다. (MVVM 결합 보호)
    """
    def __init__(self, ch_bus_type: dict[int, str] | None = None) -> None:
        self._rows: list[ParsedMessage] = []
        self._ch_bus_type: dict[int, str] = ch_bus_type or {}

    def set_ch_bus_type(self, ch_id: int, bus_type: str) -> None:
        """MainWindow가 채널 추가/제거 후 호출."""
        self._ch_bus_type[ch_id] = bus_type

    def data(self, index, role=Qt.DisplayRole):
        msg = self._rows[index.row()]
        if role == Qt.ForegroundRole:
            if msg.is_error: return COLOR_ERROR
            if msg.is_tx:    return COLOR_TX
            if self._ch_bus_type.get(msg.ch_id) == "lin": return COLOR_LIN
            return COLOR_RX
        # ... DisplayRole 처리

    def append_batch(self, batch: "list[ParsedMessage]") -> None:
        """INPUT: list[ParsedMessage]. QTimer(50ms) 슬롯에서만 호출."""
        total = len(self._rows) + len(batch)
        if total > TRACE_VISIBLE_LIMIT:
            overflow = total - TRACE_VISIBLE_LIMIT
            self.beginRemoveRows(..., 0, overflow - 1)
            del self._rows[:overflow]
            self.endRemoveRows()
        first = len(self._rows)
        self.beginInsertRows(..., first, first + len(batch) - 1)
        self._rows.extend(batch)
        self.endInsertRows()
```

> `beginRemoveRows()`와 `beginInsertRows()`는 중첩 호출 금지. 항상 `endRemoveRows()` 완료 후 다음 `beginInsertRows()`를 호출한다.

### 7.4 QSettings 저장 항목

| 키 | 타입 | 설명 |
|:---|:---|:---|
| `settings_version` | int | 마이그레이션용 스키마 버전 |
| `window/geometry` | bytes | `saveGeometry()` |
| `window/state` | bytes | `saveState()` Dock 레이아웃. Trace/Graphics/Simulation·IG Dock의 visibility, dock area, tab/stack 상태, floating geometry 포함 |
| `channel/{n}/interface` | str | vector, kvaser 등 |
| `channel/{n}/channel` | int | 채널 번호 |
| `channel/{n}/bitrate` | int | Baudrate |
| `channel/{n}/app_name` | str | Vector 인터페이스 앱 이름 (기본값 `"PyCANoe"`) |
| `channel/{n}/bus_type` | str | can / lin ← M8 신규 |
| `channel/{n}/lin_mode` | str | master / slave / listen_only ← M8 신규 |
| `channel/{n}/fd_mode` | bool | CAN FD 여부 |
| `channel/{n}/data_bitrate` | int | CAN FD Data Baudrate |
| `channel/{n}/db_path` | str | 마지막 DBC/LDF 경로 |
| `log/last_path` | str | 마지막 로그 경로 |
| `trace/filter_id` | str | 필터 ID (hex) |
| `trace/filter_mask` | str | 필터 Mask |
| `trace/auto_scroll` | bool | Auto-Scroll 상태 |
| `trace/filter_show_can` | bool | CAN 타입 표시 여부 ← Rev 12 신규 |
| `trace/filter_show_lin` | bool | LIN 타입 표시 여부 ← Rev 12 신규 |
| `trace/filter_show_error` | bool | Error 타입 표시 여부 ← Rev 12 신규 |
| `graph/rolling_window_sec` | int | 5/10/30/0(전체) |
| `graph/view_mode` | str | separate / alternating / all_y ← Rev 12 신규 |
| `ig/messages` | str | **v1.1 예정.** encode_fn Callable 직렬화 방식 결정 후 구현. 현재 v1.0에서는 저장/복원 미구현 |
| `statusbar/show_memory` | bool | Memory 항목 표시 여부 ← Rev 12 신규 |

---

## 8. UI/UX 명세

> **참조:** `PyCANoe_GUI_mockup.html` — 본 섹션의 모든 레이아웃·컬럼·버튼 구성은 해당 Mockup을 정규 레퍼런스로 사용한다.

### 8.1 메인 레이아웃

```
╔══════════════════════════════════════════════════════════════════════════╗
║  PyCANoe - Measurement Setup                              ─  □  ×        ║
╠══════════════════════════════════════════════════════════════════════════╣
║  File  Edit  View  Connection  Database  Simulation  Graphics  Tools  Help ║
╠══════════════════════════════════════════════════════════════════════════╣
║ [▶ Start] [■ Stop] [● Log] │ [CH1] [+ Channel] [Load DBC/LDF]           ║
║ [Trace] [Graphics] [Simulation/IG] [Virtual Node] │ [Config] [Layout]    ║
╠══════════════════════════════╦═══════════════════════════════════════════╣
║  Trace Monitor               ║  Graphics                                  ║
║  ─────────────────────────── ║  ┌─────────────┬─────────────────────────┐║
║  CH[All▾] ID/PID[0x___]      ║  │ signal list │ graph toolbar           │║
║  Mask[0x7FF] [Apply][Reset]  ║  │ ☑ ■ Name    │ ─────────────────────── │║
║  [☑CAN][☑LIN][☑Error]        ║  │ ☑ ■ ...     │  plot area (separate)  │║
║  ┌───┬──────────┬────┬───────┤ ║  └─────────────┴─────────────────────────┘║
║  │Ch │Timestamp │Type│ID/PID │ ║                                            ║
║  │Dir│DLC │ Data (HEX)       │ ║  (DBC 로드 전: 비활성 / 로드 후: 자동 활성) ║
║  ├───┼──────────┼────┼───────┤ ╠═══════════════════════════════════════════╣
║  │ 1 │62.021751 │CAN │0x1A0  │ ║  (Graphics가 우측 전체 높이 span)          ║
║  │Rx │ 8  │01 02 03 04...    │ ║                                            ║
║  ├───┼──────────┼────┼───────┤ ║                                            ║
║  │ 1 │62.021900 │CAN │0x1A0  │ ║                                            ║
║  │Tx │ 8  │01 03 03 04...    │ ║  ← Tx: 파랑                               ║
║  ├───┼──────────┼────┼───────┤ ║                                            ║
║  │ 3 │62.022180 │LIN │PID12  │ ║  ← LIN: 갈색                              ║
║  ├───┼──────────┼────┼───────┤ ║                                            ║
║  │ 2 │62.023001 │ERR │---    │ ║  ← Error: 빨강+굵게                        ║
║  └───┴──────────┴────┴───────┘ ║                                            ║
╠══════════════════════════════╣ ║                                            ║
║  Simulation / IG              ║                                            ║
║  [New][Clone][SpecialFrame▾]  ║                                            ║
║  [Delete][Cut][Copy][Paste]   ║                                            ║
║  ┌IG 메시지 목록 그리드──────┐  ║                                            ║
║  │▶│ Name  │ ID │ CH │ DLC  │  ║                                            ║
║  └────────────────────────────┘  ║                                            ║
║  [Standard][CAN][LIN] 탭       ║                                            ║
║  ┌ 신호 목록 ──────────────────┐  ║                                            ║
║  │SB│Signal│Raw│Phys│Unit│Wave│  ║                                            ║
║  └────────────────────────────┘  ║                                            ║
╠══════════════════════════════╩═══════════════════════════════════════════╣
║ ● CH1 CAN 500k  ● CH2 CAN FD 500k/2M  ● CH3 LIN Slave 19.2k            ║
║ Rx 8,891/s  Tx 1,204/s  Load 34.2%  Drop 0  Trace 82k rows  Memory 168MB ║
║                         [우측] ● REC 00:02:14  DBC: car.dbc  LDF: body.ldf║
╚══════════════════════════════════════════════════════════════════════════╝
```

**레이아웃 구조 (QMainWindow + QDockWidget 기반):**
- **고정 영역:** 상단 메뉴바(`QMenuBar`)와 하단 상태바(`QStatusBar`)는 Dock 대상이 아니며 항상 고정 표시한다.
- **Trace Monitor Dock:** 기본 위치는 좌측 상단. 툴바 `[Trace]` 및 View 메뉴에서 on/off 가능. Dock 위치 이동 가능. Floating은 기본 비활성 권장.
- **Simulation / IG Dock:** 기본 위치는 좌측 하단. 툴바 `[Simulation/IG]` 및 View 메뉴에서 on/off 가능. Dock 위치 이동 및 floating 가능.
- **Graphics Dock:** 기본 위치는 우측 전체 높이. 툴바 `[Graphics]` 및 View 메뉴에서 on/off 가능. Dock 위치 이동 및 floating 가능.
- 초기 배치: 좌측 영역 70%(Trace 상단 + Simulation/IG 하단) / 우측 Graphics 30%.
- Dock 허용 영역: Trace Monitor, Graphics, Simulation/IG 모두 Left/Right/Top/Bottom DockArea 이동 허용.
- Dock 상태 저장: `saveState()` / `restoreState()`로 표시 여부, 위치, floating 상태, geometry를 복원한다.
- Dock 토글: 각 Dock의 `toggleViewAction()`을 툴바 버튼과 View 메뉴에 동일하게 연결한다.

### 8.2 툴바 버튼 구성 (Mockup 기준 — 이 순서 준수)

```
[▶ Start]  [■ Stop]  [● Log]
  │ 구분선
[CH1] ... [CHn]        ← 채널 추가 시 동적 생성. 클릭 → Channel Configurator 팝업
[+ Channel]            ← 클릭 → Channel Configurator 팝업 (신규)
[Load DBC/LDF]         ← AsyncDbLoader 트리거
[Trace]                ← Trace Monitor Dock on/off 토글
[Graphics]             ← Graphics Dock on/off 토글 (floating 허용)
[Simulation / IG]      ← Simulation/IG Dock on/off 토글 (floating 허용)
[Virtual Node]         ← Virtual Node 관리 팝업
  │ 구분선
[Config]               ← QSettings 편집 팝업
[Layout]               ← Dock 레이아웃 저장/복원
  │ 우측 정렬
  "Default input mode: CAN · Rev 13"
```

**버튼 상태 규칙:**
- `[▶ Start]`: 채널이 1개 이상 정의될 때만 활성. 실행 중 비활성.
- `[■ Stop]`: 실행 중일 때만 활성.
- `[● Log]`: 토글 버튼. 활성 시 빨강 강조, "REC" 상태바 표시.
- `[CH1..CHn]`: 채널 정의 시 동적 추가. 정의 없으면 표시 안 함.

### 8.2a Dock Window 동작 규칙

| Window | 기본 위치 | On/Off | 위치 이동 | Floating | 고정 여부 |
|:---|:---|:---:|:---:|:---:|:---:|
| Trace Monitor | Left Dock Area 상단 | ✅ | ✅ | 기본 비활성 권장 | ❌ |
| Graphics | Right Dock Area 전체 높이 | ✅ | ✅ | ✅ | ❌ |
| Simulation / IG | Left Dock Area 하단 | ✅ | ✅ | ✅ | ❌ |
| 상단 메뉴바 | Top 고정 영역 | ❌ | ❌ | ❌ | ✅ |
| 하단 상태바 | Bottom 고정 영역 | ❌ | ❌ | ❌ | ✅ |

**구현 규칙:**
- `Trace Monitor`, `Graphics`, `Simulation / IG`는 반드시 `QDockWidget`으로 구현한다.
- `QDockWidget.setAllowedAreas(Qt.AllDockWidgetAreas)`로 Dock 위치 이동을 허용한다.
- `Graphics`와 `Simulation / IG`는 `DockWidgetMovable | DockWidgetFloatable | DockWidgetClosable` feature를 활성화한다.
- `Trace Monitor`는 `DockWidgetMovable | DockWidgetClosable` feature를 기본값으로 하고, floating은 필요 시 설정 옵션으로만 허용한다.
- 상단 메뉴바와 하단 상태바는 `QDockWidget`으로 감싸지 않는다.
- 레이아웃 초기화 시 `splitDockWidget(trace_dock, ig_dock, Qt.Vertical)` 및 `addDockWidget(Qt.RightDockWidgetArea, graphics_dock)`을 기준으로 배치한다.

### 8.3 Trace Dock 상세

**컬럼 구성 (Mockup 기준):**

| 컬럼 | 너비 | 내용 |
|:---|:---|:---|
| Ch | 42px | 채널 번호 (1~4) |
| Timestamp | 92px | 절대 시간(초, 소수점 6자리) |
| Type | 60px | CAN / LIN / ERR / CAN FD |
| ID/PID | 76px | CAN: `0x1A0` / LIN: `PID 0x12` |
| Dir | 44px | Rx / Tx |
| DLC | 42px | 0~64 |
| Data | 가변 | HEX 스페이스 구분 |
| Signal / Message | 220px | `MsgName.SigName = value` / DBC 없으면 "Raw" |

> **Rev11 대비 변경:** `Dir(Rx/Tx)` 컬럼 추가, `ID` → `ID/PID`로 변경

**컬러링:**

| 행 유형 | 색상 |
|:---|:---|
| Rx (기본) | 테마 기본색 |
| Tx (is_tx=True) | `#0040b0` (파랑) |
| LIN (`ch_id`의 `bus_type="lin"` 주입값) | `#7a4a00` (갈색) |
| Error (is_error=True) | `#a00000` (빨강) + 굵게 |

**필터 바:**
- Channel 콤보: All / CH1 CAN / CH2 CAN FD / CH3 LIN ...
- ID/PID 입력 + Mask 입력 → [Apply] [Reset]
- 타입 체크박스: ☑CAN ☑LIN ☑Error

**성능 설정 (코드 필수):**
```python
view.setUniformRowHeights(True)   # 렌더링 성능 100배+ 향상
view.setAnimated(False)           # 애니메이션 연산 제거
# flush limit: 2,000 row/50ms
```

**우클릭 컨텍스트 메뉴:**
- "이 ID 필터링" — arb_id를 필터 바에 자동 입력
- "클립보드로 복사" — HEX 데이터 복사
- "Send to Graph" — DBC 로드 상태일 때만 활성
- "Send to Simulation" — arb_id, data, dlc 자동 등록

### 8.4 Simulation / IG Dock 상세

**IG Toolbar (Mockup 기준 — 이 순서):**

```
[New] [Clone] [SpecialFrame ▾: Error Frame / Remote Frame] [Delete]
[Cut] [Copy] [Paste]                                       [Layout →]
```

**기능 명세:**

| 버튼 | 동작 |
|:---|:---|
| New | 빈 SimMessage 생성 → IG 그리드에 추가 |
| Clone | 선택된 SimMessage 복제 (arb_id, data, interval 동일) |
| SpecialFrame | Error Frame 또는 Remote Frame 즉시 1회 전송 |
| Delete | 선택된 SimMessage 제거 (`SimWorker.remove_message(sm.msg_id)`) |
| Cut / Copy / Paste | 클립보드 기반 IG 메시지 편집 |

**IG 메시지 그리드 컬럼:**

| 컬럼 | 내용 |
|:---|:---|
| ▶ (active) | 전송 활성 토글 |
| Message Name | DBC 있으면 메시지 이름, 없으면 편집 가능 텍스트 |
| Identifier | Hex ID (예: 0x27) |
| Channel | CAN 1 / LIN 1 등 |
| Frame | Data / Response / Error / Remote |
| DLC | 0~64 |
| BRS | CAN FD BRS 플래그 체크박스 |
| Send | update (주기) / now (1회) |
| Key | 키보드 단축키 |
| Cycle Time [ms] | 주기 (편집 가능) |
| Burst | 연속 전송 횟수 |
| HighLoad | off / on |
| Data Field (Byte 0~7) | HEX 값 직접 편집 |

**신호 탭 (Standard / CAN / LIN):**
- 선택된 IG 메시지의 신호 목록 표시
- Signal Name / Raw Value (▲▼ 스피너) / Phys Value / Unit / Phys Step / Waveform Generation

**신호 탭 컬럼:**

| 컬럼 | 내용 |
|:---|:---|
| SB (Send Bit) | 해당 신호 전송 활성 체크박스. 체크 해제 시 encode_fn 호출 입력에서 제외 |
| Signal Name | DBC 정의 신호명 (read-only) |
| Raw Value | HEX 원시값 직접 입력 |
| Phys Value | Physical 값 (스피너 편집) |
| Unit | DBC 정의 단위 (read-only) |
| Dec (-) | Phys Value를 Phys Step 단위로 감소 |
| Phys Step | 증감 스텝 크기 (편집 가능) |
| Inc (+) | Phys Value를 Phys Step 단위로 증가 |
| Waveform Generation | `None` / `Toggle switch` / `User defined` 표시. 클릭 시 WaveformDialog |

**Waveform Generation:**
- 각 신호마다 `[Define...]` 버튼 → WaveformGenerator 팝업 열기
- 현재 설정 표시: `None` / `Toggle switch` / `User defined` 등

### 8.4a WaveformGenerator 클래스 명세

```python
# core/waveform_generator.py
from enum import Enum
from dataclasses import dataclass, field

class WaveformType(Enum):
    NONE        = "None"
    TOGGLE      = "Toggle switch"
    RANGE       = "Range of values"
    RAMP_PULSE  = "Ramps and pulses"
    RANDOM      = "Random"
    SINE        = "Sine"
    USER_DEFINED = "User defined"

@dataclass
class WaveformPoint:
    time_ms: float
    value:   float

@dataclass
class WaveformGenerator:
    """
    THREAD  :
      Write (편집) : Main Thread 전용 — UI에서 설정 변경
      Read  (실행) : SimWorker Worker Thread — get_value() 호출
    INPUT   : SimMessage에 주입. SimWorker._send_due_messages()에서 호출.
    OUTPUT  : get_value(elapsed_ms) → float (신호 물리값)
    SAFETY  :
      active / level1 / level2 / default_value 등 단순 스칼라 필드는
      CPython GIL 보호로 단순 읽기/쓰기는 안전.
      points(list) 수정 시에는 반드시 SimWorker 일시 정지 후 편집하거나
      self._points_lock(threading.Lock)을 추가해 보호한다.
    DO NOT  : Qt import, blocking call
    """
    waveform_type:   WaveformType = WaveformType.NONE
    sample_time_ms:  float = 10.0
    default_value:   float = 0.0
    db_min:          float = 0.0
    db_max:          float = 0.0
    active:          bool  = True
    repetitive:      bool  = True
    time_bound:      bool  = False

    # Toggle 전용
    level1:  float = 0.0
    level2:  float = 1.0

    # User defined (time_bound=True 시 사용)
    points:  list[WaveformPoint] = field(default_factory=list)

    def get_value(self, elapsed_ms: float) -> float:
        """SimWorker에서 매 전송 직전 호출. elapsed_ms는 마지막 리셋 이후 경과 시간."""
        if not self.active or self.waveform_type == WaveformType.NONE:
            return self.default_value
        if self.waveform_type == WaveformType.TOGGLE:
            return self.level1 if (int(elapsed_ms / self.sample_time_ms) % 2 == 0) else self.level2
        if self.waveform_type == WaveformType.USER_DEFINED and self.time_bound and self.points:
            return self._interpolate(elapsed_ms)
        return self.default_value

    def _interpolate(self, elapsed_ms: float) -> float:
        """time/value 포인트 사이 선형 보간. 반복 모드 시 elapsed_ms를 총 주기로 mod."""
        if not self.points:
            return self.default_value
        total_ms = self.points[-1].time_ms
        if self.repetitive and total_ms > 0:
            elapsed_ms = elapsed_ms % total_ms
        for i in range(len(self.points) - 1):
            p0, p1 = self.points[i], self.points[i + 1]
            if p0.time_ms <= elapsed_ms <= p1.time_ms:
                t = (elapsed_ms - p0.time_ms) / (p1.time_ms - p0.time_ms)
                return p0.value + t * (p1.value - p0.value)
        return self.points[-1].value
```

**SimMessage 확장 (Waveform 연동):**
```python
# models/sim_message.py (WaveformGenerator 필드 추가)
@dataclass
class SimMessage:
    arb_id:       int
    data:         bytes
    interval_ms:  float
    msg_id:       str   = field(default_factory=lambda: uuid.uuid4().hex[:8])
    next_send_at: float = field(default_factory=time.perf_counter)
    start_time:   float = field(default_factory=time.perf_counter)  # Waveform 기준 시간
    # 신호별 WaveformGenerator. key=sig_name, value=WaveformGenerator
    # None이면 data bytes 그대로 전송 (기존 동작 유지)
    waveforms:    "dict[str, WaveformGenerator] | None" = None
    # DBC 기반 신호→bytes 변환 함수. None이면 data 그대로 사용.
    encode_fn:    "Callable[[dict], bytes] | None" = None
```

`SimWorker._send_due_messages()` 수정 방향:
1. `sm.waveforms`가 None이면 → 기존 `sm.data` 그대로 전송 (하위 호환)
2. `sm.waveforms`가 있으면 → `elapsed_ms` 계산 → `waveform.get_value()` 호출 → `encode_fn({sig: val, ...})` → bytes 생성 후 전송

**encode_fn 바인딩 경로:**
- 조건: DBC 로드 상태 + IG Dock에서 신호 값 편집 가능
- Sim Dock에서 아래 형태로 `SimMessage.encode_fn` 바인딩

```python
sm.encode_fn = lambda sigs: db_parser.encode_message(sm.arb_id, sigs)
```

- DBC 없음(`db_parser.is_loaded=False`): `encode_fn = None` → `sm.data` bytes 그대로 전송
- 바인딩 시점: IG 그리드에서 신호 값을 편집하거나 DBC 핫스왑 완료(`_on_db_loaded`) 후
- 해제 시점: DBC 제거 또는 채널 제거 시 `encode_fn = None`

### 8.5 Graphics Dock 상세

**레이아웃 (Mockup 기준):**
```
┌──────────────────────────────────────────────────────────────────────────┐
│ Graphics  [Separate views ●] [Alternating y-axis] [All y-axes]           │
│ ┌──────────────────┬────────────────────────────────────────────────────┐ │
│ │ Signal List      │ Graph Toolbar                                      │ │
│ │                  │ [▦][↔][↕][🔍][＋][－] │ [Y][Y↔][Y≡] │ [◀][▶][■]  │ │
│ │ ☑ ■ sig1 [A]     │ ──────────────────────────────────────────────────│ │
│ │ ☑ ■ sig2 [V]     │                                                   │ │
│ │ ☑ ■ sig3 [RPM]   │        Plot Area (pyqtgraph)                      │ │
│ │ ☐ ■ sig4         │                                                   │ │
│ │ [+ 신호 추가]     │   Begin: 0s · End: 62.021s · Div: 2s             │ │
│ └──────────────────┴────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────┘
```

**신호 목록 컬럼:**

| 컬럼 | 내용 |
|:---|:---|
| ☑ / ☐ | 표시/숨김 토글 |
| ■ (색상) | 신호별 고유 색상. 등록 순서대로 pyqtgraph 기본 팔레트 순환 |
| Name | `SigName [Unit]` 형식 |
| Hex | 현재 Raw 값 |
| y | 현재 Physical 값 |

**Graph 색상 정책 (Rev 13 확정):**

```python
_SIGNAL_COLORS = [
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728",
    "#9467bd", "#8c564b", "#e377c2", "#7f7f7f",
    "#bcbd22", "#17becf",
]

def _get_signal_color(self, sig_index: int) -> str:
    return _SIGNAL_COLORS[sig_index % len(_SIGNAL_COLORS)]
```

> 채널별 색상은 신호가 20개 이상일 때 구분력이 부족하므로 사용하지 않는다. Graph는 신호별 색상, Trace는 Tx/Error/LIN 상태 색상을 우선한다.

**그래프 툴바 기능:**

| 버튼 | 기능 |
|:---|:---|
| ▦ | 전체 보기 (Fit to window) |
| ↔ / ↕ | X축 / Y축 줌 |
| 🔍 + / − | 확대 / 축소 |
| Y | All y-axes 모드 (하나의 Y축 공유) |
| Y↔ | Alternating y-axis 모드 (좌/우 번갈아) |
| Y≡ | Separate views 모드 (신호별 독립 플롯) |
| ◀ / ▶ | 시간 이동 (Rolling Window 기준) |
| ■ | 재생 정지 (현재 시점 고정) |

**보기 모드 (QSettings 저장):**
- `Separate views`: 신호마다 독립 플롯 영역 (수직 분할)
- `Alternating y-axis`: 좌/우 Y축 번갈아 사용
- `All y-axes`: 단일 Y축에 모든 신호 표시

**신호 추가 경로:**
- A: Trace 우클릭 → "Send to Graph"
- B: 신호 목록 `[+ 신호 추가]` → DBC/LDF 트리 팝업

**DBC 없을 때 상태:** Dock 전체 비활성 + 안내 문구 "Load DBC/LDF to enable Graphics"

### 8.6 Channel Configurator 팝업 (Mockup 기준)

**호출 경로:**
- `[+ Channel]` 클릭 → 신규 채널 추가 모드
- `[CH1]` 등 기존 채널 버튼 클릭 → 해당 채널 편집 모드

**팝업 구성:**

```
Channel Configurator — CH1 (편집) / New Channel (신규)
┌────────────────────────────────────────┐
│ Bus type  ○ CAN FD  ○ High-Speed CAN  ○ LIN │
│ Interface  [Vector ▾]                        │
│ Channel    [0        ]                        │
│ Bitrate    [500000 ▾]                         │
│ Data bitrate [2000000]  ← CAN FD 선택 시만 활성 │
│ LIN mode   [Slave ▾]   ← LIN 선택 시만 활성   │
│ Database   [Load DBC/LDF...]                  │
│                                               │
│ ── 편집 모드 전용 ──────────────────────── │
│ [Delete Channel]                              │
│                                               │
│            [OK]  [Cancel]  [Apply]  [Help]   │
└────────────────────────────────────────┘
```

**bus_type 연동 비활성화 규칙:**
- `CAN FD` 선택: Data bitrate 활성, LIN mode 비활성
- `High-Speed CAN` 선택: Data bitrate 비활성, LIN mode 비활성
- `LIN` 선택: Data bitrate 비활성, LIN mode 활성, Bitrate 선택지 9600/19200만 표시

**OK 동작:** `ChannelConfig.validate()` 실행 → 실패 시 인라인 에러 표시 → 성공 시 `ChannelManager.add_channel()` 또는 설정 업데이트

### 8.7 상태바 구성 (Mockup 기준)

```
[좌측]
● CH1 CAN 500k    ● CH2 CAN FD 500k/2M    ● CH3 LIN Slave 19.2k
Rx 8,891/s    Tx 1,204/s    Load 34.2%    Drop 0    Trace 82k rows    Memory 168MB

[우측]
● REC 00:02:14    DBC: car.dbc    LDF: body.ldf
```

**상태 인디케이터:**
- `●` 초록: 연결됨
- `○` 회색: 미연결
- `⚠` 주황: 연결 오류 / Drop > 0

**Memory 표시:** `tracemalloc` 또는 `psutil.Process().memory_info().rss` 기반, 1초 주기 갱신

> **Rev11 대비 추가:** Memory 표시, LDF 표시, Trace row 수 표시

---

## 9. 프로젝트 구조

```
PyCANoe/
├── .gitignore
├── requirements.txt / requirements-dev.txt
├── build.spec
├── tests/
│   ├── fixtures/sample.dbc, sample.ldf
│   ├── conftest.py
│   ├── test_parsed_message.py
│   ├── test_db_parser.py
│   ├── test_async_db_loader.py
│   ├── test_message_store.py
│   ├── test_numpy_signal_buffer.py
│   ├── test_log_queue.py
│   ├── test_log_worker.py
│   ├── test_channel_stats.py
│   ├── test_can_worker.py
│   ├── test_sim_worker.py
│   ├── test_waveform_generator.py   ← Rev 12 신규
│   └── test_virtual_pipeline.py
└── src/
    ├── main.py
    ├── app/
    │   ├── main_window.py
    │   ├── config_manager.py        # QSettings + SETTINGS_VERSION 마이그레이션
    │   └── dialogs/channel_dialog.py, error_dialog.py
    ├── core/
    │   ├── channel_manager.py
    │   ├── can_worker.py
    │   ├── dispatcher.py
    │   ├── sim_worker.py
    │   ├── log_worker.py
    │   ├── db_parser.py
    │   ├── async_db_loader.py
    │   └── waveform_generator.py   ← Rev 12 신규
    ├── models/
    │   ├── parsed_message.py        # P0 동결
    │   ├── channel_stats.py
    │   ├── message_store.py
    │   ├── numpy_signal_buffer.py
    │   ├── log_queue.py
    │   ├── sim_state_store.py
    │   ├── sim_message.py           ← Rev 12 분리 (sim_worker.py에서 이동)
    │   └── trace_model.py
    └── widgets/
        ├── trace_dock.py
        ├── graph_dock.py
        ├── sim_dock.py
        └── waveform_dialog.py       ← Rev 12 신규
```

---

## 10. 메모리 예산 (4채널 풀 가동)

| 구성요소 | 설정 | 예상 |
|:---|:---|:---|
| MessageStore | deque(100,000) | ~10~60 MB (signals/msg_name 포함 여부에 따라 변동) |
| NumpySignalBuffer | 5,000pts × 50신호 (보수 기준) | ~4 MB |
| NumpySignalBuffer | 5,000pts × 200신호 (4채널 대형 DBC 기준) | ~16 MB |
| pyqtgraph 플롯 오버헤드 | copy + setData 포함 | +8~12 MB |
| LogQueue | Queue(50,000) | ~5 MB |
| SimStateStore | 신호 수백 개 | < 1 MB |
| **순수 데이터** | | **~24~90 MB** |
| Python 런타임 + PySide6 | | ~100~150 MB |
| **전체 상한** | | **< 200 MB** |

> 200신호를 동시에 표시하면 프로세스 전체 메모리가 ~220MB 범위까지 올라갈 수 있다. 이 경우 `max_points=2,500` 또는 표시 신호 수 상한을 적용한다. 상태바의 `Trace 82k rows` 값은 `len(trace_model._rows)` 기준으로 산출한다.

---

## 11. 테스트 명세

### 11.1 컴포넌트별 테스트 기준

| 대상 | 검증 내용 |
|:---|:---|
| `ParsedMessage` | frozen 불변성, CAN FD DLC 매핑, LIN arb_id & 0x3F, is_tx/is_brs 필드 존재 |
| `DbParser` | DB 없음→None, LIN 분기, decode 실패→None, _MISS sentinel 캐싱 (Mock으로 1회 탐색 확인), 핫스왑 후 clear_cache() |
| `AsyncDbLoader` | Signal이 Main Thread에서 수신 (pytest-qt), self 참조 없을 때 GC 방어 |
| `MessageStore` | 2스레드 동시 append/flush 안전성, drop_count 정확성 |
| `NumpySignalBuffer` | 2스레드 동시 접근 (Lock), copy() 독립성, tracemalloc 고정 메모리 |
| `LogQueue` | maxsize 초과 시 drop_count 증가, 통신 루프 blocking 없음 |
| `LogWorker` | stop() 직전 잔여 배치 기록 확인, 100MB 초과 시 파일 분할 |
| `ChannelStats` | calc_frame_bits(), Rx+Tx 합산, 100% 클램프, bitrate=0 예외 |
| `CANWorker` | exponential backoff, parser_lock 레이스 (update_db + decode 동시), get_stats() 레이스 |
| `SimWorker` | _messages_lock (add + send 동시), 독립 타이밍, starvation 없음, 유휴 sleep |
| `virtual pipeline` | virtual 2채널 E2E 송수신, ParsedMessage 내용 검증 |
| `LogQueue` | drop_count race 없음 (복수 Worker 동시 put, _drop_lock 보호 확인) |
| `SignalBufferRegistry` | get_or_create + append 동시 접근 (_lock 보호 확인) |
| `SimStateStore` | update/get 정상 동작, clear() 후 get() 빈 dict 반환 |
| `Virtual Node` | Thread Ownership 준수 (on_message/on_timer가 Worker Thread에서 실행) |
| `LIN Config` | bus_type="lin" + lin_mode QSettings 저장/복원, bitrate 유효성 검증 |
| `WaveformGenerator` | NONE → default_value 반환, TOGGLE 레벨 전환, USER_DEFINED 보간 정확성, repetitive mod 동작 ← Rev 12 신규 |
| `ChannelStats` | elapsed_sec 기반 bus_load_pct 계산, elapsed=0 예외 처리, 타이머 주기 변경 시 수치 정확성 ← Rev 12 신규 |
| `remove_channel()` | SimWorker wait 완료 후 CANWorker stop() 호출 순서 검증 ← Rev 12 신규 |

### 11.2 스트레스 테스트 기준

```
[STRESS TEST]
Input  : 5,000 msgs/sec × 60초, 4채널 동시
Pass   : crash 없음, UI 드래그 응답 유지, 메모리 < 200MB

[TIMING TEST — SimWorker]
Input  : 100ms 주기 메시지 (timeBeginPeriod(1) 적용)
Pass   : 실제 전송 간격 95~105ms 범위 이내
```

### 11.3 마일스톤 공통 인수 기준

- `pytest tests/` 전체 통과 (커버리지 80% 이상)
- `virtual` 인터페이스로 H/W 없이 테스트 통과
- `tracemalloc` 메모리 상한 초과 없음
- Qt Warning 없음 (백그라운드→UI 직접 접근 없음)

### 11.4 conftest.py 필수 fixture

> AI가 각 테스트 파일을 독립 작성 시 fixture 중복 생성 방지. 아래 fixture는 반드시 `tests/conftest.py`에 집중 정의.

```python
# tests/conftest.py
import pytest
from typing import Callable
from core.can_worker import CANWorker
from core.channel_manager import ChannelConfig
from models.parsed_message import ParsedMessage

@pytest.fixture
def sample_dbc_path() -> str:
    """tests/fixtures/sample.dbc 경로 반환."""
    return "tests/fixtures/sample.dbc"

@pytest.fixture
def sample_ldf_path() -> str:
    """tests/fixtures/sample.ldf 경로 반환."""
    return "tests/fixtures/sample.ldf"

@pytest.fixture
def virtual_can_worker() -> CANWorker:
    """virtual 인터페이스 CANWorker. H/W 없이 단위 테스트 전용."""
    from core.db_parser import DbParser
    cfg = ChannelConfig(interface="virtual", channel=0, bitrate=500_000)
    worker = CANWorker(ch_id=0, config=cfg, db=DbParser())
    yield worker
    if worker.isRunning():
        worker.stop()
        worker.wait()

@pytest.fixture
def parsed_msg_factory() -> Callable[..., ParsedMessage]:
    """테스트용 ParsedMessage 생성 헬퍼. 미지정 필드는 기본값 사용."""
    def _factory(
        ch_id: int = 0,
        timestamp: float = 0.0,
        arb_id: int = 0x1A0,
        dlc: int = 8,
        data: bytes = b'\x00' * 8,
        **kwargs,
    ) -> ParsedMessage:
        return ParsedMessage(ch_id=ch_id, timestamp=timestamp,
                             arb_id=arb_id, dlc=dlc, data=data, **kwargs)
    return _factory
```

---

## 12. 마일스톤 계획

### M1 — 아키텍처 POC + 핵심 데이터 모델

**Task:** git/venv 초기화 → ParsedMessage P0 확정 → ChannelStats → MessageStore → AsyncDbLoader → NumpySignalBuffer → virtual 파이프라인 POC (QTimer → StatusBar 수신 건수 표시)

**AC:**
- UI 드래그 멈춤 없음 (2채널 가상 수신 중)
- DBC 없이 signals=None 메시지 오류 없이 수신
- 2스레드 단위 테스트 전체 통과
- ParsedMessage P0 동결 선언

---

### M2 — 로깅 (ASC) + Log Rotation + Windows 타이머

**Task:** `timeBeginPeriod(1)` 추가 → LogQueue + LogWorker → ASC 포맷 (CANalyzer 호환 헤더/푸터) → Log Rotation (100MB) → 잔여 배치 손실 방지 → 채널별/통합 저장 옵션 → StatusBar 드롭 경고

**AC:** 4채널 1분 풀 부하 후 ASC 정상 생성. 100MB 분할 확인. stop() 직전 손실 없음.

---

### M3 — Trace Dock + 컬러링 + PyInstaller 조기 검증

**Task:** TraceModel (beginInsertRows 배치) → setUniformRowHeights/setAnimated → Auto-Scroll → Tx/Error 컬러링 → SW/HW 필터 → CANWorker exponential backoff + ErrorDialog → PyInstaller 최소 빌드 (Vector DLL + lark hiddenimport)

**AC:** 500kbps 풀 부하 중 UI 응답 유지. 컬러링 동작. H/W 없는 PC에서 .exe 실행.

---

### M4 — Graph Dock

**Task:** SignalBufferRegistry + NumpySignalBuffer 연동 → AsyncDbLoader + db_loaded Signal → Graph 활성화 → 신호별 고유 색상, Rolling Window

**AC:** 신호 50개 동시 그래프 끊기지 않음. DBC 로드 중 UI 응답 유지.

---

### M5 — Simulation (IG)

**Task:** SimMessage(models/sim_message.py 분리) + SimWorker (_messages_lock + drift 보정 + busy-wait) → Tx 에코 (tx_echo Signal → Dispatcher) → Sim Dock 구현:
- IG Toolbar: New / Clone / SpecialFrame(Error/Remote) / Delete / Cut / Copy / Paste
- IG 메시지 그리드 (§8.4 컬럼 전체)
- 신호 탭: Standard / CAN / LIN
- WaveformGenerator: NONE / TOGGLE / USER_DEFINED (SINE/RANDOM/RAMP은 v1.1)
- Waveform Dialog (waveform_dialog.py): time/value 포인트 편집 + 그래프 미리보기
- increment_tx() 연동

**AC:**
- 100ms 주기 메시지 95~105ms 이내. Starvation 없음. 유휴 CPU 없음.
- Trace 파랑 표시 (is_tx=True, Dir="Tx" 컬럼 표시).
- Toggle waveform: 지정 sample_time_ms 주기로 Level1/Level2 전환 확인.
- User defined waveform: time/value 포인트 보간값이 ±1% 오차 이내.
- DBC 로드 후 신호 PhysValue 편집 시 `encode_fn`이 dict를 bytes로 정상 변환.
- DBC 없는 상태의 IG 메시지는 `encode_fn=None` 경로로 `data` bytes 그대로 전송.

---

### M6 — 통합, 안정화, 최종 배포

**Task:** Bus Statistics Dock → QSettings 저장/복원 (SETTINGS_VERSION + _migrate()) → BLF/CSV 포맷 추가 → pytest 80% 커버리지 → tracemalloc 30분 누수 없음 → 최종 통합 테스트 → PyInstaller 최종 빌드

```python
# build.spec 핵심
a = Analysis(
    ['src/main.py'],
    binaries=[('C:/Program Files/Vector XL Driver Library/bin/vxlapi64.dll', '.')],
    hiddenimports=['can.interfaces.vector', 'can.interfaces.virtual',
                   'lark', 'lark.grammars'],
    datas=[('venv/Lib/site-packages/cantools/database/can/formats/dbc.lark',
            'cantools/database/can/formats')],
)
```

**AC:** 전체 기능 통합 정상 동작. Python 없는 PC에서 dist/PyCANoe.exe 실행.

---

### M7 — Virtual Node Engine ✅ 완료 (11차)

사용자 Python 스크립트로 독립 시뮬레이션 노드 구성. (CANoe CAPL 대체)

- `importlib` 기반 `.py` 스크립트 동적 로드
- `on_message(msg: ParsedMessage)` 콜백
- `on_timer(interval_ms)` 주기 콜백
- `bus.send(arb_id, data)` API
- is_tx=True 메시지 차단 (무한 루프 방지)
- 예외 격리: 노드 오류가 전체 시스템에 전파되지 않음

**AC:** 630/630 통과, 커버리지 95%

---

### M8 — LIN H/W 버스 지원 🔲 계획 (13차~)

**목표:** LIN DB 지원(LDF 파싱)은 M6에서 완료. M8에서 실제 LIN H/W 버스 연결 추가.

**Task:**

1. `ChannelConfig.bus_type` / `lin_mode` 필드 — §5.3에 반영 완료 (Rev 11.0)
2. `build_bus_kwargs()`에 LIN 분기 추가 (`python-can LinBus` 파라미터)
3. `CANWorker._connect_and_listen()`에서 bus_type 분기 처리
4. `ChannelDialog`에 LIN 탭 추가 (인터페이스·baud rate·lin_mode 선택)
5. `ChannelConfig` QSettings 저장/복원에 `bus_type`, `lin_mode` 포함 — §7.4에 반영 완료 (Rev 11.0)
6. 단위 테스트 추가 (목표: 680개+)

**v1.0 지원 범위:**

```
✅ LIN Trace (Rx/Tx)
✅ LDF Parsing (ldfparser)
✅ LIN Hardware Interface (python-can LinBus)
✅ Master Mode (수동 Header 송신 API 수준, Schedule Table Editor 없음)
✅ Slave Mode
✅ Listen Only Mode
✅ Classic / Enhanced Checksum (Driver 기본 동작 사용)
✅ Diagnostic Frame (0x3C / 0x3D) — Trace 표시 가능
```

**v1.0 미지원 (Future Scope):**

```
❌ Schedule Table Editor
❌ Diagnostic Service 전용 UI
❌ Auto Checksum Override
```

**AC:**
- [ ] LIN 채널 추가 → python-can LinBus 연결 성공
- [ ] LDF 로드 → LIN 메시지 Trace에 표시
- [ ] 단위 테스트 680개+ 통과, 커버리지 95% 유지
- [ ] CAN 기존 기능 회귀 없음

---

### Rev 11.0 비반영 항목 (의도적 제외)

> 아래 항목들은 검토 의견에 포함되었으나 현재 아키텍처 안정성을 해칠 가능성이 크고 이득이 크지 않아 Rev 11.0에서 의도적으로 제외.

| 항목 | 제외 이유 |
|:---|:---|
| `ParsedMessage`에 `is_lin` 필드 추가 | P0 동결 정책 위반. 전 계층 파급. |
| `ParsedMessage`에 `bus_type` 필드 추가 | P0 동결 정책 위반. LIN은 arb_id 마스킹으로 구분 가능. |
| `CANWorker` 아키텍처 변경 | decode 위치 등 핵심 설계는 불변 (§0.1 Rule 1~2). |
| `MessageDispatcher` 구조 변경 | fan-out 단순 구조 유지. 복잡도 증가 대비 이득 없음. |
| EventBus 도입 | 현재 Dispatcher로 충분. 개인 프로젝트 디버깅 복잡도 과다 증가. |
| `SimWorker` 복사 정책 변경 | list() 얕은 복사는 타이밍 드리프트 보정에 필수. 변경 금지. |

### Rev 12.0 비반영 항목 (의도적 제외)

> 아래 항목들은 GUI Mockup 검토 시 논의되었으나 현재 마일스톤 범위 초과 또는 아키텍처 영향 과다로 제외.

| 항목 | 제외 이유 |
|:---|:---|
| `ParsedMessage`에 `is_lin` 필드 추가 | P0 동결 정책 변경 불가. LIN 채널 식별은 `ch_id` + `ChannelConfig.bus_type`으로 UI에서 처리. |
| `ChannelStats.bus_load_pct`에 LIN 프레임 비트 분기 | TODO(v1.1)로 유지. LIN 프레임 비트 계산(~34bit)은 calc_frame_bits()에 버스 타입 인자 추가 필요 — 인터페이스 변경 범위 큼. |
| Waveform Generator UI의 Sine / Random / Ramp 완전 구현 | M5 범위 초과. WaveformGenerator 클래스 구조만 명세하고, NONE/TOGGLE/USER_DEFINED 우선 구현. 나머지는 v1.1. |
| Graph Dock `[Alternating y-axis]` / `[All y-axes]` 모드 | M4 범위 초과. Separate views 우선 구현, 나머지 모드는 v1.1. |

### Rev 13.0 비반영 항목 (의도적 제외)

| 항목 | 제외 이유 |
|:---|:---|
| Virtual Node Manager UI 상세 버튼 명세 | M7 기능 범위는 완료. UI 세부 명세 추가는 v1.1 리팩토링 시점에 처리. |
| Force Signal 고정값 전송 기능 | M5 범위 초과. 일부 사용성은 `WaveformType.RANGE`로 대체 가능하며 정식 기능은 v1.1. |
| WaveformGenerator `enabled` / `active` 필드 분리 | v1.0은 `active` bool 하나로 기능 범위를 커버. CANoe 완전 호환 목적의 필드 분리는 v1.1. |

---

## 13. 핵심 설계 결정 요약

| 결정 항목 | 선택 | 핵심 이유 |
|:---|:---|:---|
| decode 위치 | CANWorker 내부 | Dispatcher는 Main Thread → decode 시 UI 응답 차단 |
| NumpySignalBuffer | 고정 배열 + Lock + copy() | 동적 배열 → GC 폭발. copy() 없으면 렌더링 중 오염. |
| AsyncDbLoader | QObject + daemon Thread | ThreadPoolExecutor 누수. 백그라운드 콜백 → Segfault. Signal만 안전. |
| MessageStore 드롭 | flush() 시 overflow 계산 | append()에서 판단 시 _pending 무제한 성장 |
| CANWorker 종료 | 명시적 break | 암묵적 루프 탈출은 정상/비정상 종료 구분 불가 |
| CANWorker stop() | 0.1초 폴링 루프 | msleep(wait*1000)은 최대 16초 블로킹 |
| SimWorker 타이밍 | perf_counter + busy-wait 1ms | Windows sleep 해상도 한계. CANoe 동일 방식. |
| SimWorker 유휴 | sleep(0.1) | 메시지 없어도 루프 → CPU 100% |
| SimMessage 타이밍 | 독립 next_send_at + drift 보정 | 단일 루프 주기 → 짧은 주기가 긴 주기 starvation 유발 |
| LogWorker 청크 | 5,000건 | 100건 → SSD I/O 50배 과다 |
| 재연결 backoff | [1,2,4,8,16]초 MAX_RETRY=5 | 즉시 재시도 → H/W 복구 중 에러 루프 |
| DB 핫스왑 | `clear_cache()` → `parser_lock` → parser swap (Rev 13.0) | swap 후 clear 방식은 Worker Thread decode와 cache clear race 가능 |
| _MISS sentinel | cantools KeyError 정확히 반영 | None 반환이 아님 → 매 프레임 재탐색 버그 |
| QueuedConnection 명시 | channel_manager.add_channel()에서 명시 | auto-detect 전제 붕괴 방어 |
| Windows 타이머 | timeBeginPeriod(1) | 기본 15.6ms → SimWorker 10ms 주기 오차 ±15ms |
| Log Rotation | 100MB 분할 | 500kbps 1시간 → 1~2GB → 디스크 풀 |
| ASC 헤더/푸터 | Begin/End TriggerBlock | CANalyzer 인식 필수 조건 |
| self._db_loader | self에 반드시 저장 | 로컬 변수 → GC → Signal emit 전 Segfault |
| ParsedMessage P0 동결 | M1에서 확정 후 변경 금지 | 변경 시 전 계층(CANWorker·DbParser·Dispatcher·UI) 파급 |
| PyInstaller 조기 검증 | M3 완료 시점 최소 빌드 | M6까지 미루면 DLL/hiddenimport 최종 발견 |
| Event Bus 전환 | 유보 (M7 시점) | 현재 Dispatcher로 충분. 개인 프로젝트 디버깅 복잡도 증가. |
| LogQueue drop_count Lock | _drop_lock 추가 (Rev 11.0) | 복수 CANWorker 동시 put() 시 race condition 방어 |
| SignalBufferRegistry Lock | _lock 추가 (Rev 11.0) | get_or_create() 동시 호출 시 dict 충돌 방어 |
| increment_tx frame_bits | 인자 추가 (Rev 11.0) | tx_bits 누적 없이 Tx Bus Load가 항상 0% 표시되던 버그 수정 |
| ChannelManager assert 제거 | ValueError 교체 (Rev 11.0) | assert는 python -O 빌드에서 제거 → 배포본 무음 실패 방지 |
| UI Throttling | 2,000 row/flush 상한 (Rev 11.0) | 5,000fps 부하 시 QTimer 슬롯 starvation 방지 |
| AsyncDbLoader Shutdown | disconnect → stop() 순서 명시 (Rev 11.0) | loader Signal 미해제 시 종료 후 emit → Segfault 방지 |
| remove_channel() 종료 순서 | SimWorker → CANWorker 순 (Rev 12.0) | SimWorker가 CANWorker.send() 호출 중 _bus=None 접근 방지 |
| ChannelStats elapsed_sec | perf_counter 기반 실측값 (Rev 12.0) | QTimer 주기 가정(1s) 하드코딩 제거 → 주기 변경 시에도 bus_load_pct 정확 |
| WaveformGenerator | 독립 클래스 (Rev 12.0) | SimMessage.data 고정 bytes만으로는 신호 기반 파형 생성 불가 |
| SimMessage 파일 분리 | models/sim_message.py (Rev 12.0) | sim_worker.py가 WaveformGenerator 의존 시 순환 import 방지 |
| GUI 레이아웃 2컬럼 | 좌(Trace+IG) / 우(Graph) QSplitter (Rev 12.0) | Mockup 기준 정규화. 기존 상하 분할은 Graph를 너무 좁게 만들어 실용성 저하. |
| Dock 레이아웃 정책 | QMainWindow + QDockWidget (Rev 13.0) | Trace Monitor / Graphics / Simulation·IG는 on/off 및 위치 이동 가능. Graphics와 Simulation·IG는 floating 허용. 상단 메뉴바와 하단 상태바는 고정. |
| Trace Dir 컬럼 추가 | Rx / Tx 명시 (Rev 12.0) | is_tx=True 에코와 실제 Rx 구분이 Data 컬럼 색상만으로는 불명확. |
| TraceModel LIN 컬러링 | `ch_id → bus_type` 주입 (Rev 13.0) | ParsedMessage P0 동결을 유지하면서 LIN 색상 표시. TraceModel이 ChannelManager를 직접 참조하지 않음. |
| TraceModel 표시 상한 | `TRACE_VISIBLE_LIMIT=100_000` (Rev 13.0) | MessageStore는 상한이 있으나 UI rows가 무제한 증가하던 문제 방지. |
| SimMessage 삭제 식별자 | `msg_id` 기반 삭제 (Rev 13.0) | 동일 arb_id를 다른 주기로 여러 개 등록하는 일반 사용 패턴 보호. |
| Graph 신호 색상 | Signal별 고유 색상 (Rev 13.0) | 채널 색상 방식은 신호 수가 많을 때 구분력이 부족. |
