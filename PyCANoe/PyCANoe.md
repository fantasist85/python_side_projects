# PyCANoe 프로젝트 설계 명세서

> **Rev. 10.0** — M8 LIN H/W 지원 스코프 추가. pytest 환경 규칙 추가.
>
> | 버전 | 주요 변경 |
> |---|---|
> | Rev 1.0~6.0 | 아키텍처 확립, 버그 수정 6종, 설계 개선 다수 |
> | Rev 7.0 | sentinel 패턴, stop() 폴링, QueuedConnection 명시, AsyncDbLoader 연속 로드 수정 |
> | Rev 8.0 | AI 구현 명세서로 전면 리팩토링. AI Rules / Thread Ownership / Error Policy / Implementation Order / 누락 인터페이스 명세 추가. 버전 히스토리 상세 제거. 토큰 최적화. |
> | Rev 9.0 | AI 구현 안전성 강화: SimWorker 복사 규칙, Shutdown 시퀀스, LogWorker while-else 설명, SignalBuffer 활성화 트리거, update_db() lock 주석, STEP 완료 기준, AsyncDbLoader disconnect 위치, conftest.py fixture 목록 추가. |
> | **Rev 10.0** | **M8 LIN H/W 지원 스코프 추가 (ChannelConfig.bus_type, build_bus_kwargs LIN 분기). pytest 환경 규칙 추가 (uv 환경 금지, 시스템 Python 사용).** |

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

[QTimer  50ms] → MessageStore.flush() → TraceModel.append_batch()
[QTimer 100ms] → SignalBufferRegistry.get_view() → pyqtgraph setData()
[QTimer   1s ] → CANWorker.get_stats() → Bus Statistics UI
[LogWorker]    → LogQueue.get() → 파일 write (청크 5,000건)
```

```
[CRITICAL SHUTDOWN SEQUENCE — closeEvent() 구현 시 이 순서 100% 준수]

1. 모든 QTimer 정지 (UI 갱신 중단)
2. ChannelManager.all() 순회 → ctx.worker.stop() 호출
3. ctx.sim_worker가 있다면 stop() 호출
4. self._log_worker.stop() 호출
5. 모든 Worker에 대해 .wait() 호출 — 스레드 완전 종료 보장

★ terminate() 사용 절대 금지 — 하드웨어 포트 미해제 → BSoD/Segfault
★ stop() 없이 .wait() 단독 호출 금지 — 데드락
★ QTimer 정지 전 stop() 호출 금지 — 타이머 슬롯이 종료된 Worker 접근 가능
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

    @staticmethod
    def calc_frame_bits(dlc: int, is_fd: bool) -> int:
        # CAN 2.0B: 47 + dlc*8 bits (bit stuffing 미포함)
        # CAN FD  : 67 + dlc*8 bits (Arbitration Phase 보수적 근사)
        # TODO(v1.1): data_bitrate 분리 계산
        return (67 if is_fd else 47) + dlc * 8

    @property
    def bus_load_pct(self) -> float:
        if self.bitrate <= 0:
            return 0.0
        return min(100.0, (self.rx_bits + self.tx_bits) / self.bitrate * 100.0)
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
        self._rx_count = self._rx_bits = self._err_count = self._tx_count = 0

    def update_db(self, db: "DbParser") -> None:
        """Main Thread에서 호출. parser_lock + clear_cache() 포함."""
        with self._parser_lock:
            self._db = db
        db.clear_cache()

    def send(self, msg: "can.Message") -> None:
        """SimWorker에서 호출. bus 참조는 _connect_and_listen 범위 내에서만 유효."""
        if self._bus is not None:
            self._bus.send(msg)

    def increment_tx(self) -> None:
        """SimWorker가 전송 시 호출."""
        with self._stats_lock:
            self._tx_count += 1

    def get_stats(self) -> ChannelStats:
        """QTimer(1s) 슬롯에서 호출. read + clear 원자적 수행."""
        with self._stats_lock:
            s = ChannelStats(
                rx_count=self._rx_count, tx_count=self._tx_count,
                error_count=self._err_count, rx_bits=self._rx_bits,
                bitrate=self._config.bitrate,
            )
            self._rx_count = self._tx_count = self._err_count = self._rx_bits = 0
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
        self._state = WorkerState.STOPPING
        self._stop  = True
        self.wait()
        self._state = WorkerState.STOPPED
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
    fd_mode:      bool = False
    data_bitrate: int  = 2_000_000
    app_name:     str  = "PyCANoe"
    db_path:      str | None = None
    hw_id_filter: int | None = None
    hw_id_mask:   int | None = None

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
        assert len(self._channels) < self.MAX_CHANNELS
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
        ctx.worker.stop()
        if ctx.sim_worker:
            ctx.sim_worker.stop()

    def get(self, ch_id: int) -> "ChannelContext | None":
        return self._channels.get(ch_id)

    def all(self) -> "list[ChannelContext]":
        return list(self._channels.values())
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

    def update_db(self, db: "DbParser") -> None:
        """CANWorker.update_db()에서 호출. _parser_lock은 호출자가 보유."""
        # lock 밖에서 clear_cache() 호출 — 의도적.
        # clear_cache()는 독립 인스턴스 조작이므로 lock 범위 밖이 안전하며,
        # lock 안으로 이동 시 lock 보유 중 추가 메서드 호출로 데드락 위험 있음.
        self._db = db._db
        self._type = db._type
        self.clear_cache()

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
from dataclasses import dataclass, field
from threading import Lock
from PySide6.QtCore import QThread, Signal

@dataclass
class SimMessage:
    arb_id:       int
    data:         bytes
    interval_ms:  float
    next_send_at: float = field(default_factory=time.perf_counter)

    def is_due(self, now: float) -> bool:
        return now >= self.next_send_at

    def update_next(self, now: float) -> None:
        self.next_send_at += self.interval_ms / 1000.0
        # 크게 밀렸으면 리셋 (폭주 방지)
        if now - self.next_send_at > self.interval_ms / 1000.0:
            self.next_send_at = now + self.interval_ms / 1000.0

    def to_can_message(self):
        import can
        return can.Message(arbitration_id=self.arb_id, data=self.data,
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
        for sm in msgs:
            if sm.is_due(now):
                self._bus_sender.send(sm.to_can_message())
                self._bus_sender.increment_tx()
                sm.update_next(now)
                # Trace 컬러링용 Tx 에코
                echo = ParsedMessage(
                    ch_id=self._ch_id, timestamp=time.time(),
                    arb_id=sm.arb_id, dlc=len(sm.data), data=sm.data, is_tx=True)
                self.tx_echo.emit(echo)

    def add_message(self, msg: SimMessage) -> None:
        """Main Thread에서 호출."""
        with self._messages_lock:
            self._messages.append(msg)

    def remove_message(self, arb_id: int) -> None:
        """Main Thread에서 호출."""
        with self._messages_lock:
            self._messages = [m for m in self._messages if m.arb_id != arb_id]

    def stop(self) -> None:
        self._stop = True
        self.wait()
```

### 5.6 LogWorker

```python
# models/log_queue.py
import queue
from models.parsed_message import ParsedMessage

class LogQueue:
    """THREAD: put()=Worker, get_queue()=LogWorker"""
    MAX_SIZE = 50_000

    def __init__(self) -> None:
        self._q         = queue.Queue(maxsize=self.MAX_SIZE)
        self.drop_count = 0

    def put(self, msg: ParsedMessage) -> None:
        try:
            self._q.put_nowait(msg)
        except queue.Full:
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
        self._running = False
        self.wait()
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

    def flush(self) -> list[ParsedMessage]:
        """QTimer(50ms) 슬롯 전용. 스냅샷 후 클리어."""
        with self._lock:
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

    def get_or_create(self, ch_id: int, sig_name: str,
                      max_points: int = 5_000) -> NumpySignalBuffer:
        key = (ch_id, sig_name)
        if key not in self._bufs:
            self._bufs[key] = NumpySignalBuffer(max_points)
        return self._bufs[key]

    def append(self, ch_id: int, sig_name: str,
               timestamp: float, value: float) -> None:
        self.get_or_create(ch_id, sig_name).append(timestamp, value)

    def enable_all(self) -> None:
        for buf in self._bufs.values(): buf.enable()

    def disable_all(self) -> None:
        for buf in self._bufs.values(): buf.disable()
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
        batch = self._message_store.flush()
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
COLOR_RX    = None                # 테마 기본색

class TraceModel:   # QAbstractItemModel 상속
    def data(self, index, role=Qt.DisplayRole):
        msg = self._rows[index.row()]
        if role == Qt.ForegroundRole:
            if msg.is_error: return COLOR_ERROR
            if msg.is_tx:    return COLOR_TX
            return COLOR_RX
        # ... DisplayRole 처리

    def append_batch(self, batch: "list[ParsedMessage]") -> None:
        """INPUT: list[ParsedMessage]. QTimer(50ms) 슬롯에서만 호출."""
        first = len(self._rows)
        self.beginInsertRows(..., first, first + len(batch) - 1)
        self._rows.extend(batch)
        self.endInsertRows()
```

### 7.4 QSettings 저장 항목

| 키 | 타입 | 설명 |
|:---|:---|:---|
| `settings_version` | int | 마이그레이션용 스키마 버전 |
| `window/geometry` | bytes | `saveGeometry()` |
| `window/state` | bytes | `saveState()` Dock 레이아웃 |
| `channel/{n}/interface` | str | vector, kvaser 등 |
| `channel/{n}/channel` | int | 채널 번호 |
| `channel/{n}/bitrate` | int | Baudrate |
| `channel/{n}/fd_mode` | bool | CAN FD 여부 |
| `channel/{n}/data_bitrate` | int | CAN FD Data Baudrate |
| `channel/{n}/db_path` | str | 마지막 DBC/LDF 경로 |
| `log/last_path` | str | 마지막 로그 경로 |
| `trace/filter_id` | str | 필터 ID (hex) |
| `trace/filter_mask` | str | 필터 Mask |
| `trace/auto_scroll` | bool | Auto-Scroll 상태 |
| `graph/rolling_window_sec` | int | 5/10/30/0(전체) |

---

## 8. UI/UX 명세

### 8.1 메인 레이아웃

```
╔══════════════════════════════════════════════════════════════════════════╗
║  PyCANoe v1.0                                                            ║
╠══════════════════════════════════════════════════════════════════════════╣
║  File  Edit  View  Connection  Tools  Help                               ║
╠══════════════════════════════════════════════════════════════════════════╣
║  [+ CH]  [DBC]  [Graph ▒]  │  [▶ Start]  [■ Stop]  │  [● Log]           ║
╠══════════════════════════════════════════════════════════════════════════╣
║ ┌─ Trace Monitor ──────────────────────────── [↓ Auto-Scroll ON] ───────┐║
║ │ [All*] [CH1: CAN 500k] [CH2: CAN 250k] [CH3: LIN] [CH4: ---]        │║
║ │ ID[0x___] Mask[0x7FF] [적용] [초기화] │ [☑CAN][☑LIN][☑Error] [All▼] │║
║ ├────┬────────────┬──────┬──────┬─────┬──────────────┬──────────────────┤║
║ │ Ch │ Timestamp  │ Type │  ID  │ DLC │ Data (HEX)   │ Signal (DBC)     │║
║ ├────┼────────────┼──────┼──────┼─────┼──────────────┼──────────────────┤║
║ │  1 │ 100.1234   │ CAN  │ 1A0  │  8  │ 01 02 03 04  │[EngineData]1200  │║ ← Rx 기본색
║ │  1 │ 100.1245   │ CAN  │ 1A0  │  8  │ 01 03 03 04  │[EngineData]1210  │║ ← Tx 파랑
║ │  3 │ 100.1290   │ ERR  │ ---  │  0  │ ---          │[Error Frame]     │║ ← Error 빨강
║ └────┴────────────┴──────┴──────┴─────┴──────────────┴──────────────────┘║
║ ┌─ Simulation (IG) ─────────────────────────────────────────────────────┐║
║ │ [CH1 ▾] CAN_Msg_A 100ms │ Signal: EngSpeed  Physical(rpm)            │║
║ │   ● EngSpeed (1200)     │ 값: [1200.0]  범위: [──●──] 0~8000          │║
║ └───────────────────────────────────────────────────────────────────────┘║
╠══════════════════════════════════════════════════════════════════════════╣
║ ● CH1:500k VN1610  ● CH2:250k  ○ CH3:---  │ DBC:car.dbc │ ● REC 00:02  ║
║ CH1: Load 34.2% | Rx:8,891/s | Tx:1,204/s | Err:0                       ║
╚══════════════════════════════════════════════════════════════════════════╝
```

### 8.2 컴포넌트 상세

**Trace Dock 필수 설정:**
- `setUniformRowHeights(True)` — 렌더링 성능 100배+ 향상
- `setAnimated(False)` — 애니메이션 연산 제거
- `beginInsertRows` / `endInsertRows` 배치 처리

**Trace Dock 우클릭 메뉴:**
- "이 ID 필터링" — arb_id를 필터 바에 자동 입력
- "클립보드로 복사" — HEX 데이터 복사
- "Send to Graph" — DBC 있을 때만 활성
- "Send to Simulation" — arb_id, data, dlc 자동 등록

**Graph Dock:**
- 기본 숨김. DBC `db_loaded` Signal 수신 시 자동 활성.
- 채널 색상: CH1=파랑, CH2=초록, CH3=주황, CH4=빨강
- Rolling Window: 5s / 10s / 30s / 전체

**Graph 신호 추가 경로:**
- A: Trace 우클릭 → "Send to Graph"
- B: Graph Dock `[+ 신호 추가]` → DBC 트리 팝업

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
    │   └── async_db_loader.py
    ├── models/
    │   ├── parsed_message.py        # P0 동결
    │   ├── channel_stats.py
    │   ├── message_store.py
    │   ├── numpy_signal_buffer.py
    │   ├── log_queue.py
    │   ├── sim_state_store.py
    │   └── trace_model.py
    └── widgets/
        ├── trace_dock.py
        ├── graph_dock.py
        └── sim_dock.py
```

---

## 10. 메모리 예산 (4채널 풀 가동)

| 구성요소 | 설정 | 예상 |
|:---|:---|:---|
| MessageStore | deque(100,000) | ~10 MB |
| NumpySignalBuffer | 5,000pts × 50신호 | ~4 MB |
| LogQueue | Queue(50,000) | ~5 MB |
| SimStateStore | 신호 수백 개 | < 1 MB |
| pyqtgraph 플롯 | 채널 4 × 신호 수 | ~4 MB |
| **순수 데이터** | | **~24 MB** |
| Python 런타임 + PySide6 | | ~100~150 MB |
| **전체 상한** | | **< 200 MB** |

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
    worker.stop()

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

**Task:** SignalBufferRegistry + NumpySignalBuffer 연동 → AsyncDbLoader + db_loaded Signal → Graph 활성화 → 채널 색상, Rolling Window

**AC:** 신호 50개 동시 그래프 끊기지 않음. DBC 로드 중 UI 응답 유지.

---

### M5 — Simulation (IG)

**Task:** SimMessage + SimWorker (_messages_lock + drift 보정 + busy-wait) → Tx 에코 (tx_echo Signal → Dispatcher) → Sim Dock (QSplitter + Physical/Raw Hex 전환) → increment_tx() 연동

**AC:** 100ms 주기 메시지 95~105ms 이내. Starvation 없음. 유휴 CPU 없음. Trace 파랑 표시.

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

1. `ChannelConfig`에 `bus_type: Literal["can", "lin"] = "can"` 필드 추가
2. `build_bus_kwargs()`에 LIN 분기 추가 (`python-can LinBus` 파라미터)
3. `CANWorker._connect_and_listen()`에서 bus_type 분기 처리
4. `ChannelDialog`에 LIN 탭 추가 (인터페이스·baud rate 선택)
5. `ChannelConfig` QSettings 저장/복원에 `bus_type` 포함
6. 단위 테스트 추가 (목표: 680개+)

```python
# M8 ChannelConfig 변경 예정
@dataclass
class ChannelConfig:
    interface:    str
    channel:      int
    bitrate:      int
    bus_type:     str  = "can"   # ← M8 신규. "can" | "lin"
    fd_mode:      bool = False
    data_bitrate: int  = 2_000_000
    app_name:     str  = "PyCANoe"
    db_path:      str | None = None
    hw_id_filter: int | None = None
    hw_id_mask:   int | None = None
    socketcan_ifname: str = "vcan0"
    pcan_channel:     str = "PCAN_USBBUS1"
```

**AC:**
- [ ] LIN 채널 추가 → python-can LinBus 연결 성공
- [ ] LDF 로드 → LIN 메시지 Trace에 표시
- [ ] 단위 테스트 680개+ 통과, 커버리지 95% 유지
- [ ] CAN 기존 기능 회귀 없음

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
| DB 핫스왑 | parser_lock + clear_cache() | 교체 중 decode Race Condition 방지 |
| _MISS sentinel | cantools KeyError 정확히 반영 | None 반환이 아님 → 매 프레임 재탐색 버그 |
| QueuedConnection 명시 | channel_manager.add_channel()에서 명시 | auto-detect 전제 붕괴 방어 |
| Windows 타이머 | timeBeginPeriod(1) | 기본 15.6ms → SimWorker 10ms 주기 오차 ±15ms |
| Log Rotation | 100MB 분할 | 500kbps 1시간 → 1~2GB → 디스크 풀 |
| ASC 헤더/푸터 | Begin/End TriggerBlock | CANalyzer 인식 필수 조건 |
| self._db_loader | self에 반드시 저장 | 로컬 변수 → GC → Signal emit 전 Segfault |
| ParsedMessage P0 동결 | M1에서 확정 후 변경 금지 | 변경 시 전 계층(CANWorker·DbParser·Dispatcher·UI) 파급 |
| PyInstaller 조기 검증 | M3 완료 시점 최소 빌드 | M6까지 미루면 DLL/hiddenimport 최종 발견 |
| Event Bus 전환 | 유보 (M7 시점) | 현재 Dispatcher로 충분. 개인 프로젝트 디버깅 복잡도 증가. |
