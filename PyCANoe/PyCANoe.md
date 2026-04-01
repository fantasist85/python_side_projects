# PyCANoe 통합 프로젝트 계획 및 설계서

> **Rev. 6.0** — AI 3종 교차 검토 반영 (버그 수정 4종 + 설계 개선 4종 + 마일스톤 재조정)
>
> | 버전 | 주요 변경 |
> |---|---|
> | Rev 1.0 | 최초 작성. 단일 채널, DBC 필수, 기본 아키텍처 |
> | Rev 2.0 | 4채널 지원 / DBC 선택적 운용 / 데이터 파이프라인 / 메모리 예산 |
> | Rev 3.0 | 디코딩 스레드 재배치 / NumpySignalBuffer / ParsedMessage 데이터모델 / 재연결 전략 / 필터링 엔진 / Bus Statistics / SimWorker 정밀도 / 마일스톤 재조정 / 테스트 전략 |
> | Rev 4.0 | 버그 3종 수정 (MessageStore 드롭 로직 / DbParser Executor 누수+UI 크래시 / CANWorker 종료 흐름) / NumpySignalBuffer Lock+copy() 추가 / Bus Load 계산 공식 완성 / ChannelStats 통합 / LIN decode 분기 명시 / SimWorker 유휴 CPU 방어 / Trace Auto-Scroll / 배포 파이프라인(PyInstaller) / .gitignore DBC/LDF 보완 |
> | Rev 5.0 | [버그①] CANWorker.get_stats() 레이스 컨디션 → stats_lock 추가 / [버그②] SimWorker SimMessage 독립 타이밍 설계 / [버그③] AsyncDbLoader 수명 관리 누락 명시 / [버그④] LogWorker ASC 파일 헤더 추가(CANalyzer 호환) / [설계⑤] ParsedMessage.msg_name 필드 추가 / [설계⑥] Bus Load Tx 비트 반영 / [설계⑦] CAN FD Bus Load calc_frame_bits() 명시 / [설계⑧] MessageDispatcher 코드 명세 추가 / [품질⑨] DbParser.decode() 데드코드 제거 / [배포⑩] QSettings 마이그레이션 전략 / [배포⑪] PyInstaller Vector DLL + lark hiddenimport / [테스트⑫] CANWorker.get_stats() 레이스 테스트 추가 |
> | **Rev 6.0** | **[버그①] CANWorker DB 핫스왑 중 parser_lock 누락 수정 / [버그②] SimWorker._messages Lock 누락 수정 / [버그③] LogWorker 종료 시 잔여 배치 손실 수정 / [버그④] Windows 타이머 해상도(15.6ms) 대응 — timeBeginPeriod(1) 추가 / [설계⑤] DbParser 메시지 정의 캐싱 (_msg_def_cache) / [설계⑥] Trace Tx/Rx/Error 컬러링 (is_tx, is_brs 필드) / [설계⑦] ParsedMessage is_tx + is_brs 필드 동결 반영 / [설계⑧] Log Rotation (100MB 파일 분할) / [마일스톤] PyInstaller 검증 M3으로 앞당김 + 각 마일스톤 개선사항 통합** |

---

## 1. 프로젝트 개요

### 1.1. 프로젝트 명

PyCANoe (Python CAN/LIN Analyzer)

### 1.2. 프로젝트 목표

- LGPL 라이선스를 준수하는 PySide6 기반으로, 경량화되고 고성능인 CAN/LIN 네트워크 분석 및 시뮬레이션 도구를 개발한다.
- UI 멈춤 현상이 없는(Non-Blocking) 반응형 인터페이스를 제공한다. CANoe와 동일하게 초당 5,000 프레임 이상 수신 시에도 UI가 응답 가능한 상태를 유지한다.
- 최대 4채널 동시 운용을 지원하는 확장 가능한 채널 관리 구조를 갖춘다.
- DBC/LDF 없이도 RAW 통신이 가능하며, DB 로드 시 신호 해석·Graph 기능이 자동 활성화된다.
- 목적별로 분리된 데이터 모델과 비동기 파이프라인으로 전체 프로세스 메모리 200MB 이하를 유지한다.
- 메모리 누수·크래시·UI 프리징이 없는 프로덕션 레벨 품질을 달성한다.
- 파이썬 환경 없이도 실행 가능한 단일 실행 파일(.exe)로 배포한다.
- 향후 기능 확장이 용이한 모듈식 계층형 아키텍처를 구축한다.

### 1.3. 핵심 기능 범위 (Scope)

| In-Scope (v1.0 구현 대상) | Future Scope (향후 확장) |
| :---- | :---- |
| **1. 모니터링 (Trace):** CAN/LIN 실시간 추적, 최대 4채널, HW/SW 이중 필터링, Auto-Scroll 토글, **Tx/Rx/Error 컬러링 (Rev 6.0)** | 1. **진단 (UDS)** |
| **2. 시각화 (Graph):** DBC/LDF 기반 신호 그래프, 채널별 색상 구분 (DB 없으면 비활성) | 2. **H/W 확장:** PCAN, 기타 python-can 지원 H/W |
| **3. 시뮬레이션 (Sim):** CANoe IG 스타일 메시지/신호 전송, Physical/Raw Hex 입력 전환 | 3. **Replay:** ASC/BLF 파일 재생 |
| **4. 데이터베이스:** DBC (CAN), LDF (LIN) 비동기 로딩, None-safe Graceful Degradation, **메시지 정의 캐싱 (Rev 6.0)** | 4. **Virtual Node Engine:** Python 스크립트 로드, on_message 이벤트 콜백 |
| **5. 로깅:** ASC 우선 구현, BLF/CSV 순차 추가, 비동기 저장, 드롭 경고, **Log Rotation 100MB (Rev 6.0)** | 5. **BLF 고급 포맷** 완성 (M6 이후) |
| **6. H/W (v1.0):** Vector (VN16xx, VT 등), Kvaser, virtual 인터페이스 (CI/테스트용) | |
| **7. 4채널 독립 운용:** 채널별 독립 Worker·DB·SimWorker·통계 | |
| **8. Bus Statistics:** 채널별 Bus Load %, Tx/Rx/Error 카운터 실시간 표시 | |
| **9. 배포:** PyInstaller 단일 실행 파일(.exe) 빌드, **M3 조기 검증 (Rev 6.0)** | |

---

## 2. 기술 스택 및 개발 환경

### 2.1. 핵심 기술 스택

| 구분 | 기술 | 라이선스 | 선정 사유 |
| :---- | :---- | :---- | :---- |
| **UI** | PySide6 | LGPL | GPL 회피, 상업적/사내 사용 자유. QDockWidget, Model/View, QThread, QObject Signal 전문 기능 제공. |
| **그래프** | PyQtGraph | MIT | matplotlib 대비 압도적인 실시간 성능. `setData()` numpy 직접 전달. PySide6 완벽 호환. |
| **통신** | python-can | LGPL | Vector, Kvaser(현재), PCAN(향후) 다양한 H/W 백엔드를 동일 API로 지원. virtual 인터페이스로 H/W 없이 테스트 가능. |
| **DB 파싱** | cantools (DBC) | MIT | CAN DBC 파싱의 사실상 표준. 경량화. None-safe 래핑으로 선택적 사용. |
| **DB 파싱** | ldfparser (LDF) | MIT | LDF 파싱 경량화 라이브러리. None-safe 래핑. LIN Protected ID(6비트) 기반 분기 처리. |
| **데이터 구조** | collections.deque | 표준 | maxlen 기반 자동 메모리 상한 관리 (Trace/Log 링 버퍼). |
| **비동기 큐** | queue.Queue | 표준 | LogWorker 간 Thread-safe 메시지 전달. put_nowait 드롭 정책. |
| **수치 연산** | numpy | BSD | NumpySignalBuffer 고정 배열 재사용. GC 부하 원천 차단. |
| **동시성** | threading.Lock / threading.Thread | 표준 | MessageStore·NumpySignalBuffer·SimWorker._messages 스레드 안전성. AsyncDbLoader Executor 누수 없는 비동기 로딩. |
| **배포** | PyInstaller | MIT | Python 환경 없이 실행 가능한 단일 .exe 생성. |
| **테스트** | pytest / pytest-qt / pytest-mock / pytest-cov | MIT | 단위 테스트, PySide6 위젯 테스트, 커버리지 측정. |

### 2.2. 개발 환경 구축

**1. 가상환경 생성 (필수)**

```bash
# 프로젝트 루트 폴더에서 실행
python -m venv venv
# Windows
.\venv\Scripts\activate
# macOS/Linux
source venv/bin/activate
```

**2. 런타임 의존성 (requirements.txt)**

```
# ---------------------------------
# PyCANoe Runtime Dependencies
# ---------------------------------

# Core Framework (LGPL)
PySide6

# High-Speed Plotting (MIT)
pyqtgraph

# Hardware Communication (LGPL)
python-can

# Database Parsing (MIT) — Optional at runtime
cantools
ldfparser

# Numeric — NumpySignalBuffer fixed-array ring buffer (BSD)
numpy
```

**3. 개발/테스트/배포 전용 의존성 (requirements-dev.txt)**

```
# ---------------------------------
# PyCANoe Dev / Test / Build Dependencies
# ---------------------------------
pytest
pytest-qt        # PySide6 위젯 단위 테스트
pytest-mock      # Worker 스레드 Mock
pytest-cov       # 커버리지 측정

# Packaging — M3 조기 검증 + M6 최종 빌드
pyinstaller      # 단일 실행 파일(.exe) 빌드
```

**설치:**

```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

**4. Git 무시 파일 (.gitignore)**

```
# Python
venv/
__pycache__/
*.pyc
*.egg-info/

# IDE
.vscode/
.idea/

# Build artifacts
dist/
build/
*.spec

# Logs / test output
*.asc
*.blf
*.csv
test_data/

# Vehicle DB files — 사내 기밀 보호 (Rev 4.0 추가)
*.dbc
*.ldf
!tests/fixtures/*.dbc    # 테스트용 샘플은 예외 허용
!tests/fixtures/*.ldf
```

---

## 3. 시스템 아키텍처 및 설계

### 3.1. 아키텍처 목표

1. **디코딩 병목 제거:** `DbParser.decode()`는 반드시 `CANWorker` 스레드 내부에서 실행한다. UI 스레드는 렌더링만 담당하며 decode 연산을 절대 수행하지 않는다.
2. **UI 크래시 원천 차단:** 백그라운드 스레드에서 UI 위젯에 직접 접근하지 않는다. 모든 스레드 간 통신은 Qt Signal(QueuedConnection)을 통해서만 수행한다.
3. **UI 멈춤 방지:** QThread 멀티스레딩으로 H/W I/O 및 모든 무거운 작업을 메인 UI 스레드와 완벽히 분리한다. QTimer 배치 갱신으로 dataChanged 호출을 최소화한다.
4. **4채널 독립 운용:** `ChannelManager`가 최대 4개의 `ChannelContext`를 관리하며, 각 채널은 독립적인 Worker·DbParser·SimWorker·통계를 가진다.
5. **데이터 팬아웃 구조:** `MessageDispatcher`가 수신·디코딩 완료된 `ParsedMessage`를 목적에 맞는 독립 데이터 모델로 분배(fan-out)한다.
6. **메모리 상한 보장:** 모든 버퍼는 `deque(maxlen=N)` 또는 고정 크기 numpy 배열 기반으로 자동 상한을 관리하여 장시간 운용 시에도 메모리 누수가 없다.
7. **GC 부하 원천 차단:** Graph용 SignalBuffer는 매 갱신마다 numpy 배열을 새로 생성하지 않는 `NumpySignalBuffer`(고정 배열 + Lock + copy())를 사용한다.
8. **DBC 선택적 운용:** DB 없이도 전 기능(Trace·Sim·Logging)이 동작하며, DB 로드 시 신호 해석·Graph 기능이 자동 활성화된다.
9. **확장성 및 유지보수:** 계층 분리(Layered Architecture)로 UI, 로직, 데이터, 인프라를 명확히 분리한다.

### 3.2. 계층 분리 (Layered Architecture)

```
┌──────────────────────────────────────────────────────────────┐
│  Presentation Layer — app/, widgets/                         │
│  Main Thread 전용. UI 렌더링 + QTimer 배치 갱신만 담당.          │
│  백그라운드 스레드에서의 직접 접근 절대 금지.                      │
├──────────────────────────────────────────────────────────────┤
│  Service Layer — core/                                       │
│  ChannelManager, CANWorker×4 (decode 포함),                  │
│  SimWorker×4, LogWorker, MessageDispatcher, AsyncDbLoader    │
├──────────────────────────────────────────────────────────────┤
│  Data Layer — models/                                        │
│  ParsedMessage, ChannelStats, MessageStore,                  │
│  NumpySignalBuffer, LogQueue, SimStateStore, TraceModel      │
├──────────────────────────────────────────────────────────────┤
│  Infrastructure Layer — python-can                           │
│  H/W Bus 추상화. Vector / Kvaser / PCAN / virtual            │
└──────────────────────────────────────────────────────────────┘
```

### 3.3. 스레드 구성

| 스레드 | 역할 | 비고 |
| :---- | :---- | :---- |
| **Main Thread (UI)** | UI 위젯 관리, 사용자 입력, QTimer 배치 갱신 | PySide6 Main Thread 전용. decode·파일 I/O 절대 금지. |
| **CANWorker×N (QThread)** | H/W recv() → DbParser.decode() → ParsedMessage emit | 채널 수만큼 생성 (최대 4). decode가 이 스레드에서 실행됨. |
| **LogWorker (QThread)** | LogQueue 소비, ASC/BLF/CSV 비동기 파일 쓰기, 1초 flush, **Log Rotation (Rev 6.0)** | 채널 통합 또는 채널별 분리 선택. |
| **SimWorker×N (QThread)** | perf_counter 절대시간 기반 drift 보정 루프, 주기 전송 | 채널별 독립. busy-wait 1ms 정밀도. 메시지 없으면 sleep(0.1). |
| **DB 로딩 (threading.Thread)** | DbParser 비동기 파싱, 완료 시 Qt Signal emit | AsyncDbLoader가 관리. Executor 누수 없음. |

### 3.4. 핵심 데이터 모델 — ParsedMessage (P0 확정 필수)

`ParsedMessage`는 파이프라인 전체를 흐르는 기본 단위다. M1 착수 전에 반드시 확정해야 하며, 나중에 변경하면 모든 계층에 파급된다.

> **Rev 5.0 변경 [설계⑤]:** `msg_name` 필드 추가. Trace UI의 Signal 컬럼에 `"[EngineData] EngSpeed: 1200"` 형태로 메시지 이름을 표시하려면 이 필드가 필요하다.
>
> **Rev 6.0 변경 [설계⑦]:** `is_tx` 및 `is_brs` 필드 추가. `is_tx`는 Trace 컬러링 및 Tx/Rx 구분에 필수이며, `is_brs`는 CAN FD BRS 플래그로 python-can의 `Message.bitrate_switch`에서 가져온다. **ParsedMessage가 P0 동결 예정이므로 이 시점에 반드시 포함한다. 추후 추가 시 CANWorker·DbParser·Dispatcher·UI 전 계층 파급.**

```python
# models/parsed_message.py
from dataclasses import dataclass

@dataclass(frozen=True, slots=True)
class ParsedMessage:
    # --- H/W 원시 필드 ---
    ch_id:     int          # 0~3, 채널 식별자
    timestamp: float        # python-can 타임스탬프 (초)
    arb_id:    int          # CAN Arbitration ID (LIN: Protected ID 8비트)
    dlc:       int          # 전송 DLC (0~15). CAN FD는 9~15 = 실제 12~64바이트
    data:      bytes        # 실제 페이로드 (최대 64바이트, CAN FD 대응)
    is_fd:     bool = False
    is_remote: bool = False
    is_error:  bool = False
    is_tx:     bool = False  # Rev 6.0: SimWorker 송신 메시지 (Trace 컬러링용)
    is_brs:    bool = False  # Rev 6.0: CAN FD BRS 플래그 (python-can Message.bitrate_switch)

    # --- 디코딩 결과 (CANWorker 내부에서 채움) ---
    signals:   dict | None = None
    # DBC/LDF 있으면: {"EngSpeed": 1200.0, "VehSpeed": 40.0}
    # DB 없거나 decode 실패 시: None (Graceful Degradation)
    msg_name:  str | None = None   # Rev 5.0: DBC/LDF 메시지 이름 (예: "EngineData")
    # Trace UI Signal 컬럼에 "[EngineData] EngSpeed: 1200" 형태로 표시할 때 사용.
    # DB 없거나 매핑 실패 시 None.
```

> **CAN FD DLC 매핑:** DLC 9→12B, 10→16B, 11→20B, 12→24B, 13→32B, 14→48B, 15→64B.
> Trace UI의 Data 컬럼은 `len(data)` 기준으로 실제 바이트 수를 표시한다.
>
> **LIN arb_id:** LIN Protected ID는 6비트 Frame ID + 2비트 Parity = 8비트.
> decode 시 `arb_id & 0x3F`로 Frame ID 추출 후 ldfparser API에 전달한다.
>
> **is_tx 사용법:** `SimWorker`가 메시지를 전송할 때 `is_tx=True`로 설정한 `ParsedMessage`를 에코 형태로 Dispatcher에 전달하면, Trace가 Tx 메시지를 컬러로 구분하여 표시한다.

### 3.5. 메시지 파이프라인 (데이터 흐름)

decode는 CANWorker 내부에서 완료된 후 `ParsedMessage`로 emit된다. `MessageDispatcher`는 fan-out만 수행한다.

```
[H/W Bus CH1~4]
     │  python-can Bus.recv()  (blocking, timeout=0.1s)
     ▼
[CANWorker-N  ←── DbParser 주입 (채널 생성 시) + parser_lock (Rev 6.0 핫스왑 보호)]
     │  1) recv() → python-can Message
     │  2) DbParser.decode_with_name(arb_id, data) → signals dict | None  (캐싱 Rev 6.0)
     │  3) ParsedMessage 생성 (is_fd, is_error, is_brs, CAN FD 최대 64B 포함)
     │  4) _rx_bits 누적 (Bus Load 계산용)
     │  Qt Signal: parsed_message_received(ParsedMessage)
     ▼
[MessageDispatcher]          ← fan-out만 담당. decode 없음.
     │
     ├──► [MessageStore]          deque(100k) + Lock + 정확한 드롭 카운터
     ├──► [SignalBufferRegistry]   NumpySignalBuffer(고정 배열 + Lock + copy()) — Graph
     ├──► [LogQueue]              Queue(50k) + 드롭 카운터 — LogWorker 공급
     └──► [SimStateStore]         dict{ch_id:{sig:val}} — Sim 에코 감지용

[QTimer  50ms] ── MessageStore.flush() → TraceModel.append_batch()
                   → Auto-Scroll 판단 → 컬러링 적용 → QTreeView 갱신
[QTimer 100ms] ── SignalBufferRegistry.get_view() → PlotDataItem.setData()
[QTimer   1s ] ── CANWorker.get_stats() → ChannelStats.bus_load_pct → Bus Statistics UI
[LogWorker]    ── LogQueue.get(timeout=0.1) → 파일 write(청크 5,000건) → flush 1초
                   → 100MB 초과 시 파일 분할 (Log Rotation, Rev 6.0)
```

### 3.6. MessageDispatcher — fan-out 명세

> **Rev 5.0 [설계⑧]:** 계획서 전체에서 "fan-out만 수행"으로만 언급되고 코드 명세가 없었다. 실행 스레드(메인), decode 수행 여부, 각 데이터 모델로의 push 흐름을 명시한다.

```python
# core/dispatcher.py
from PySide6.QtCore import QObject, Slot

class MessageDispatcher(QObject):
    """
    CANWorker.parsed_message_received Signal의 수신 슬롯.
    QueuedConnection이므로 메인 스레드에서 실행됨.
    decode 없이 fan-out만 수행 — UI 스레드 보호.
    """
    def __init__(self, store: "MessageStore", registry: "SignalBufferRegistry",
                 log_queue: "LogQueue", sim_store: "SimStateStore") -> None:
        super().__init__()
        self._store    = store
        self._registry = registry
        self._log_q    = log_queue
        self._sim      = sim_store

    @Slot(object)
    def on_message(self, msg: "ParsedMessage") -> None:
        """모든 수신 메시지를 목적별 데이터 모델에 분배한다."""
        self._store.append(msg)            # Trace 링 버퍼
        self._log_q.put(msg)               # 로그 큐 (비동기 파일 I/O)
        if msg.signals:
            for sig_name, value in msg.signals.items():
                self._registry.append(msg.ch_id, sig_name, msg.timestamp, float(value))
            self._sim.update(msg.ch_id, msg.signals)

    @Slot(str)
    def on_error(self, error_msg: str) -> None:
        """CANWorker 오류 이벤트. StatusBar/ErrorDialog 연동은 MainWindow에서 처리."""
        pass  # MainWindow에서 별도 연결 가능
```

> **스레드 실행 위치 확인:** `ChannelManager.add_channel()`에서 `worker.parsed_message_received.connect(self._dispatcher.on_message)`로 연결한다. CANWorker(QThread)와 MessageDispatcher(메인 스레드 QObject) 간 크로스 스레드 Signal이므로 Qt가 자동으로 QueuedConnection을 선택 → `on_message`는 메인 스레드 이벤트 루프에서 실행된다.

### 3.7. ChannelManager 설계

```python
# core/channel_manager.py
from dataclasses import dataclass

@dataclass
class ChannelConfig:
    interface:    str         # "vector", "kvaser", "pcan", "virtual"
    channel:      int         # 0-based channel index
    bitrate:      int         # 예: 500_000
    fd_mode:      bool = False
    data_bitrate: int  = 2_000_000  # CAN-FD Data Phase
    app_name:     str  = "PyCANoe"  # Vector App Name
    db_path:      str | None = None # DBC/LDF 경로 (없으면 None)
    hw_id_filter: int | None = None # python-can HW 필터 ID (None=전체 수신)
    hw_id_mask:   int | None = None # python-can HW 필터 마스크

@dataclass
class ChannelContext:
    ch_id:      int
    config:     ChannelConfig
    worker:     "CANWorker"
    db_parser:  "DbParser"           # DB 없어도 None-safe 객체
    sim_worker: "SimWorker | None" = None

class ChannelManager:
    MAX_CHANNELS = 4

    def __init__(self, dispatcher: "MessageDispatcher") -> None:
        self._channels: dict[int, ChannelContext] = {}
        self._dispatcher = dispatcher

    def add_channel(self, ch_id: int, config: ChannelConfig) -> ChannelContext:
        assert len(self._channels) < self.MAX_CHANNELS, "최대 4채널"
        db     = DbParser(config.db_path)
        worker = CANWorker(ch_id, config, db)   # decode는 Worker 내부
        worker.parsed_message_received.connect(self._dispatcher.on_message)
        worker.error_occurred.connect(self._dispatcher.on_error)
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

### 3.8. CANWorker — DB 핫스왑 parser_lock 추가 (Rev 6.0 버그 수정)

**Rev 5.0까지의 설계:** `stats_lock`으로 통계 카운터 레이스 컨디션을 방어하고, `break`로 정상 종료 의도를 명확화.

**Rev 6.0 버그 수정 [버그①] — DB 핫스왑 중 parser_lock 누락:**
`AsyncDbLoader`가 완료 신호를 보내서 메인 스레드가 `CANWorker`에 새 DbParser를 주입하는 시점에, Worker 스레드는 이전 DbParser로 `decode_with_name()`을 실행 중일 수 있다. `update_db()` 메서드와 `_parser_lock`을 추가하여 주입 시점의 레이스 컨디션을 방어한다.

```python
# core/can_worker.py
import can
from threading import Lock
from PySide6.QtCore import QThread, Signal
from .models.parsed_message import ParsedMessage
from .models.channel_stats import ChannelStats

MAX_RETRY = 5
RETRY_BACKOFF_SEC = [1, 2, 4, 8, 16]
_CAN_OVERHEAD_BITS = 47   # SOF+ID+RTR+IDE+r0+DLC+CRC+DEL+ACK+DEL+EOF+IFS

class CANWorker(QThread):
    parsed_message_received  = Signal(object)      # ParsedMessage
    error_occurred           = Signal(str)
    connection_state_changed = Signal(int, bool)   # ch_id, is_connected

    def __init__(self, ch_id: int, config: "ChannelConfig", db: "DbParser") -> None:
        super().__init__()
        self._ch_id        = ch_id
        self._config       = config
        self._db           = db
        self._stop         = False
        self._stats_lock   = Lock()   # Rev 5.0: 통계 카운터 레이스 컨디션 방어
        self._parser_lock  = Lock()   # Rev 6.0: DB 핫스왑 레이스 컨디션 방어
        self._rx_count     = 0
        self._rx_bits      = 0
        self._err_count    = 0
        self._tx_count     = 0

    def update_db(self, db: "DbParser") -> None:
        """
        Rev 6.0: DB 핫스왑 진입점.
        메인 스레드(AsyncDbLoader 완료 슬롯)에서 호출.
        parser_lock으로 Worker 스레드의 decode 완료를 기다린 후 교체.
        교체 후 캐시 초기화(DbParser._msg_def_cache.clear())도 함께 수행.
        """
        with self._parser_lock:
            self._db = db
        # DbParser 교체 시 캐시 무효화 (Rev 6.0 설계⑤ 연동)
        db.clear_cache()

    def run(self) -> None:
        retry_count = 0
        while not self._stop:
            try:
                self._connect_and_listen()
                break   # 명시적 break — 정상 종료(stop() 호출) 의도 명확화
            except can.CanError as e:
                retry_count += 1
                self.connection_state_changed.emit(self._ch_id, False)
                if retry_count > MAX_RETRY:
                    self.error_occurred.emit(
                        f"CH{self._ch_id}: 재연결 한계 초과 ({MAX_RETRY}회). 수동 재연결 필요.")
                    break
                wait = RETRY_BACKOFF_SEC[min(retry_count - 1, len(RETRY_BACKOFF_SEC) - 1)]
                self.error_occurred.emit(
                    f"CH{self._ch_id}: 연결 오류 — {wait}초 후 재시도 ({retry_count}/{MAX_RETRY})")
                self.msleep(int(wait * 1000))

    def _connect_and_listen(self) -> None:
        with can.Bus(interface=self._config.interface,
                     channel=self._config.channel,
                     bitrate=self._config.bitrate,
                     fd=self._config.fd_mode) as bus:
            if self._config.hw_id_filter is not None:
                bus.set_filters([{
                    "can_id":   self._config.hw_id_filter,
                    "can_mask": self._config.hw_id_mask or 0x7FF,
                    "extended": False
                }])
            self.connection_state_changed.emit(self._ch_id, True)
            while not self._stop:
                raw = bus.recv(timeout=0.1)
                if raw is None:
                    continue
                # Rev 6.0: parser_lock으로 decode 구간 보호
                with self._parser_lock:
                    signals, msg_name = self._db.decode_with_name(raw.arbitration_id, raw.data)
                msg = ParsedMessage(
                    ch_id=self._ch_id,
                    timestamp=raw.timestamp,
                    arb_id=raw.arbitration_id,
                    dlc=raw.dlc,
                    data=bytes(raw.data),
                    is_fd=raw.is_fd,
                    is_remote=raw.is_remote_frame,
                    is_error=raw.is_error_frame,
                    is_brs=getattr(raw, 'bitrate_switch', False),  # Rev 6.0: CAN FD BRS 플래그
                    signals=signals,
                    msg_name=msg_name,
                )
                frame_bits = ChannelStats.calc_frame_bits(len(raw.data), raw.is_fd)
                with self._stats_lock:
                    self._rx_count += 1
                    self._rx_bits  += frame_bits
                    if raw.is_error_frame:
                        self._err_count += 1
                self.parsed_message_received.emit(msg)

    def increment_tx(self) -> None:
        """SimWorker가 메시지 전송 시 호출하여 Tx 카운터를 증가시킨다."""
        with self._stats_lock:
            self._tx_count += 1

    def get_stats(self) -> "ChannelStats":
        """
        1초 주기 QTimer 슬롯에서 호출. 카운터를 반환 후 초기화.
        Rev 5.0: stats_lock으로 read+clear 원자성 보장.
        """
        with self._stats_lock:
            stats = ChannelStats(
                rx_count=self._rx_count,
                tx_count=self._tx_count,
                error_count=self._err_count,
                rx_bits=self._rx_bits,
                bitrate=self._config.bitrate,
            )
            self._rx_count = self._tx_count = self._err_count = self._rx_bits = 0
        return stats

    def stop(self) -> None:
        self._stop = True
        self.wait()
```

### 3.9. ChannelStats — Tx/Rx/Error/Bus Load 통합 통계

> **Rev 5.0 [설계⑥]:** Bus Load 계산에 Tx 비트(`tx_bits`) 반영. SimWorker가 활발히 전송 중이면 Rx만 계산할 경우 실제보다 낮게 표시된다. CANoe의 Bus Load는 Rx+Tx 합산 기준이다.
>
> **Rev 5.0 [설계⑦]:** CAN FD 프레임은 Arbitration Phase(nominal bitrate)와 Data Phase(data bitrate)가 혼재하므로 단순 overhead 공식이 부정확하다. `calc_frame_bits()` 정적 메서드를 도입하여 `is_fd` 플래그 기반으로 분기 처리한다.

```python
# models/channel_stats.py
from dataclasses import dataclass

@dataclass
class ChannelStats:
    rx_count:    int   = 0
    tx_count:    int   = 0
    error_count: int   = 0
    rx_bits:     int   = 0      # 1초간 수신된 총 비트 수
    tx_bits:     int   = 0      # Rev 5.0: 1초간 송신된 총 비트 수 (Bus Load에 합산)
    bitrate:     int   = 500_000

    @staticmethod
    def calc_frame_bits(dlc: int, is_fd: bool) -> int:
        """
        Rev 5.0: 프레임 종류별 비트 수 계산.

        CAN 2.0B (is_fd=False):
          47 + dlc × 8 비트 (bit stuffing 제외 최솟값)
          예: DLC=8 → 47+64 = 111비트

        CAN FD (is_fd=True):
          Arbitration Phase(~67비트) + Data Phase(dlc × 8).
          v1.0에서는 nominal bitrate 기준 보수적 계산.
          예: DLC=64 → 67+512 = 579비트
        """
        if is_fd:
            return 67 + dlc * 8   # Arbitration Phase 보수적 추정
        return 47 + dlc * 8

    @property
    def bus_load_pct(self) -> float:
        """
        Bus Load % 계산 (Rev 5.0 Tx 비트 반영).

        공식: ((rx_bits + tx_bits) / bitrate) × 100
        Rx+Tx 합산으로 CANoe Bus Load 기준에 부합.
        CAN FD는 nominal bitrate 기준 보수적 계산.
        """
        if self.bitrate <= 0:
            return 0.0
        total_bits = self.rx_bits + self.tx_bits
        return min(100.0, total_bits / self.bitrate * 100.0)
```

### 3.10. DbParser — None-safe + LIN 분기 + 메시지 정의 캐싱 (Rev 6.0 설계 추가)

**Rev 4.0 수정:** `DbParser`는 Qt 의존성 없는 순수 Python 클래스로 유지한다.

**Rev 5.0 변경:** `decode_with_name()` 메서드 추가. `decode()` 내 데드코드 제거.

**Rev 6.0 설계 추가 [설계⑤] — 메시지 정의 캐싱:**
`cantools`의 `get_message_by_frame_id()`는 매번 내부 dict 탐색을 수행한다. 5,000fps에서 초당 5,000번 호출되므로, `_msg_def_cache`를 도입하여 최초 1회만 조회하고 이후에는 캐시에서 반환한다. DBC 교체(핫스왑) 시 `clear_cache()`를 반드시 호출해야 한다.

```python
# core/db_parser.py
import cantools
import ldfparser
from typing import Any

class DbParser:
    """
    순수 Python 클래스. Qt 의존성 없음 — 단위 테스트 용이.
    비동기 로딩은 AsyncDbLoader가 담당한다.
    """
    def __init__(self, path: str | None = None) -> None:
        self._db             = None
        self._type           = None   # "dbc" | "ldf" | None
        self._msg_def_cache: dict[int, Any] = {}   # Rev 6.0: 메시지 정의 캐시
        if path:
            self.load(path)

    def load(self, path: str) -> bool:
        """동기 로드. CANWorker 주입 시 또는 AsyncDbLoader 내부에서 호출."""
        try:
            if path.lower().endswith(".dbc"):
                self._db   = cantools.database.load_file(path)
                self._type = "dbc"
            elif path.lower().endswith(".ldf"):
                self._db   = ldfparser.parse_ldf(path)
                self._type = "ldf"
            else:
                return False
            self.clear_cache()   # 새 DB 로드 시 캐시 초기화
            return True
        except Exception:
            self._db   = None
            self._type = None
            return False

    def clear_cache(self) -> None:
        """
        Rev 6.0: 메시지 정의 캐시 초기화.
        DBC 핫스왑(update_db) 또는 새 DB 로드 시 반드시 호출.
        """
        self._msg_def_cache.clear()

    def decode(self, arb_id: int, data: bytes) -> dict | None:
        """
        DB 없거나 decode 실패 시 None 반환 (Graceful Degradation).
        """
        signals, _ = self.decode_with_name(arb_id, data)
        return signals

    def decode_with_name(self, arb_id: int, data: bytes) -> "tuple[dict | None, str | None]":
        """
        Rev 5.0: signals dict와 msg_name을 함께 반환.
        Rev 6.0: _msg_def_cache로 get_message_by_frame_id() 중복 조회 제거.
        DB 없거나 decode 실패 시 (None, None) 반환.
        """
        if self._db is None:
            return None, None
        try:
            if self._type == "dbc":
                # Rev 6.0: 캐시에서 먼저 조회 — 5,000fps에서 초당 조회 비용 대폭 감소
                if arb_id not in self._msg_def_cache:
                    self._msg_def_cache[arb_id] = self._db.get_message_by_frame_id(arb_id)
                msg_def = self._msg_def_cache[arb_id]
                if msg_def is None:
                    return None, None
                return self._db.decode_message(arb_id, data), msg_def.name
            elif self._type == "ldf":
                frame_id = arb_id & 0x3F   # 하위 6비트 = LIN Frame ID
                if frame_id not in self._msg_def_cache:
                    self._msg_def_cache[frame_id] = self._db.get_frame(frame_id)
                frame = self._msg_def_cache[frame_id]
                if frame is None:
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
        return self._type   # "dbc" | "ldf" | None


# core/async_db_loader.py
import threading
from PySide6.QtCore import QObject, Signal

class AsyncDbLoader(QObject):
    """
    DbParser를 백그라운드 스레드에서 로드하고,
    완료 시 Qt Signal(QueuedConnection)로 메인 스레드에 안전하게 전달한다.

    Rev 5.0 주의 [버그③]: MainWindow에서 반드시 self에 참조를 유지해야 한다.
    참조가 없으면 GC가 loader 객체를 수거하고 Signal emit 전에 파괴되어 Segfault가 발생한다.
    올바른 사용 예:
        self._db_loader = AsyncDbLoader(parser, path)   # self에 저장 필수
        self._db_loader.db_loaded.connect(self._on_db_loaded)
        self._db_loader.start_loading()

    완료 슬롯(_on_db_loaded)에서 반드시 CANWorker.update_db(parser)를 호출한다.
    update_db()는 parser_lock 획득 + clear_cache()를 함께 수행한다.
    """
    db_loaded = Signal(bool, object)   # success: bool, parser: DbParser

    def __init__(self, parser: "DbParser", path: str) -> None:
        super().__init__()
        self._parser = parser
        self._path   = path

    def start_loading(self) -> None:
        t = threading.Thread(target=self._run, daemon=True)
        t.start()

    def _run(self) -> None:
        ok = self._parser.load(self._path)
        self.db_loaded.emit(ok, self._parser)
```

**비동기 로딩 흐름 (DB 핫스왑 Rev 6.0 업데이트):**

```
1. 사용자가 DBC 경로 지정 → Channel Add Dialog [적용] 클릭
2. MainWindow: AsyncDbLoader(parser, path) 생성
3. self._db_loader = loader   # GC 방지 필수 (Rev 5.0)
4. loader.db_loaded.connect(self._on_db_loaded)
5. loader.start_loading()
6. StatusBar: ⏳ "DBC 파싱 중..." 스피너 표시
7. [백그라운드] DbParser.load() → clear_cache() 내부 호출
8. [백그라운드] db_loaded.emit(ok, parser)
9. [메인 스레드] _on_db_loaded(ok, parser) 슬롯
10. → CANWorker.update_db(parser)   # parser_lock 획득 + clear_cache() (Rev 6.0)
11. → SignalBufferRegistry.enable_all() → Graph 버튼 활성화
```

### 3.11. 메모리 버퍼 전략

#### 3.11.1. MessageStore — Trace용 링 버퍼

```python
# models/message_store.py
from collections import deque
from threading import Lock
from .parsed_message import ParsedMessage

class MessageStore:
    MAX_ROWS = 100_000      # ~10 MB (ParsedMessage 1건 ≈ 100 bytes)

    def __init__(self) -> None:
        self._buffer:  deque[ParsedMessage] = deque(maxlen=self.MAX_ROWS)
        self._pending: list[ParsedMessage]  = []
        self._lock     = Lock()
        self.drop_count = 0

    def append(self, msg: ParsedMessage) -> None:
        """Worker 스레드에서 호출. Lock으로 _pending 보호."""
        with self._lock:
            self._pending.append(msg)

    def flush(self) -> list[ParsedMessage]:
        """
        QTimer(50ms) 슬롯 — 메인 스레드에서만 호출.
        스냅샷 후 클리어. 버퍼 용량 초과분을 드롭 카운터에 정확히 반영.
        """
        with self._lock:
            batch         = self._pending
            self._pending = []
        overflow = max(0, len(self._buffer) + len(batch) - self.MAX_ROWS)
        if overflow > 0:
            self.drop_count += overflow
        self._buffer.extend(batch)
        return batch

    def filter_by_channel(self, ch_id: int) -> list[ParsedMessage]:
        return [m for m in self._buffer if m.ch_id == ch_id]

    def get_all(self) -> list[ParsedMessage]:
        return list(self._buffer)
```

#### 3.11.2. NumpySignalBuffer — Graph용 고정 배열 링 버퍼

```python
# models/numpy_signal_buffer.py
import numpy as np
from threading import Lock

class NumpySignalBuffer:
    """
    메모리 재할당 없이 고정 크기 numpy 배열을 재사용하는 링 버퍼.
    threading.Lock으로 append(Worker 스레드)와 get_view(UI 스레드) 간
    Race Condition을 방지. get_view()는 .copy()로 스냅샷 반환.
    """
    def __init__(self, max_points: int = 5_000) -> None:
        self._cap        = max_points
        self._timestamps = np.zeros(max_points, dtype=np.float64)
        self._values     = np.zeros(max_points, dtype=np.float64)
        self._index      = 0
        self._size       = 0
        self.enabled     = False
        self._lock       = Lock()

    def enable(self) -> None:
        self.enabled = True

    def disable(self) -> None:
        self.enabled = False

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
        """
        pyqtgraph PlotDataItem.setData()에 전달할 numpy 배열 반환.
        .copy()로 스냅샷 — UI 렌더링 중 Worker 스레드가 원본을 덮어써도 안전.
        """
        with self._lock:
            if self._size == 0:
                return None
            if self._size < self._cap:
                return (self._timestamps[:self._size].copy(),
                        self._values[:self._size].copy())
            i   = self._index
            ts  = np.concatenate((self._timestamps[i:], self._timestamps[:i]))
            val = np.concatenate((self._values[i:],     self._values[:i]))
            return ts, val


class SignalBufferRegistry:
    """채널별, 신호별 NumpySignalBuffer를 중앙 관리한다."""
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
        for buf in self._bufs.values():
            buf.enable()

    def disable_all(self) -> None:
        for buf in self._bufs.values():
            buf.disable()
```

#### 3.11.3. LogQueue + LogWorker — 비동기 파일 I/O + Log Rotation (Rev 6.0)

**Rev 6.0 설계 추가 [설계⑧] — Log Rotation:**
500kbps 풀 부하 1시간이면 ASC 파일이 1~2GB에 달한다. 100MB 초과 시 파일을 자동 분할하여 디스크 풀 크래시를 방지한다. 파일명은 `log_001.asc`, `log_002.asc` 형태로 순번을 부여한다.

**Rev 6.0 버그 수정 [버그③] — 종료 시 잔여 배치 손실:**
Rev 5.0까지는 `_running = False` → 루프 탈출 → `batch`에 남은 메시지가 파일에 기록되지 않았다. 루프 탈출 직후 잔여 배치 처리 코드를 추가한다.

```python
# models/log_queue.py
import queue
from .parsed_message import ParsedMessage

class LogQueue:
    MAX_SIZE = 50_000

    def __init__(self) -> None:
        self._q         = queue.Queue(maxsize=self.MAX_SIZE)
        self.drop_count = 0

    def put(self, msg: ParsedMessage) -> None:
        try:
            self._q.put_nowait(msg)
        except queue.Full:
            self.drop_count += 1   # 통신 루프를 절대 블로킹하지 않는다.

    def get_queue(self) -> queue.Queue:
        return self._q


# core/log_worker.py
import os
import queue
from PySide6.QtCore import QThread, Signal

MAX_FILE_BYTES = 100 * 1024 * 1024   # Rev 6.0: 100MB Log Rotation 상한

class LogWorker(QThread):
    log_dropped    = Signal(int)    # 누적 드롭 카운트 → StatusBar 표시
    log_rotated    = Signal(str)    # Rev 6.0: 새 파일 경로 → StatusBar 갱신

    def __init__(self, log_queue: "LogQueue", path: str, fmt: str = "asc") -> None:
        super().__init__()
        self._q        = log_queue.get_queue()
        self._lq       = log_queue
        self._base_path = path
        self._fmt      = fmt
        self._running  = False

    def _make_path(self, index: int) -> str:
        """Rev 6.0: 분할 파일 경로 생성. log.asc → log_001.asc, log_002.asc ..."""
        base, ext = os.path.splitext(self._base_path)
        return f"{base}_{index:03d}{ext}"

    def run(self) -> None:
        self._running = True
        CHUNK      = 5_000
        file_index = 1
        last_drop  = 0

        while self._running:
            current_path = self._make_path(file_index)
            with open(current_path, "w", encoding="utf-8") as f:
                if self._fmt == "asc":
                    from datetime import datetime
                    f.write("date " + datetime.now().strftime("%a %b %d %I:%M:%S %p %Y") + "\n")
                    f.write("base hex  timestamps absolute\n")
                    f.write("internal events logged\n")
                    f.write("// version 8.5.0\n")
                    f.write("Begin Triggerblock\n")

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
                        f.flush()   # 최대 ~1초 이내 flush 보장

                    if self._lq.drop_count != last_drop:
                        last_drop = self._lq.drop_count
                        self.log_dropped.emit(last_drop)

                    # Rev 6.0: Log Rotation — 100MB 초과 시 파일 분할
                    if f.tell() >= MAX_FILE_BYTES:
                        # 현재 파일 정리 후 새 파일로 교체
                        if self._fmt == "asc":
                            f.write("End TriggerBlock\n")
                        break   # 내부 루프 탈출 → 외부 루프에서 새 파일 생성

                else:
                    # Rev 6.0 버그③ 수정: _running=False로 종료 시 잔여 배치 기록 보장
                    if batch:
                        self._write_batch(f, batch)
                    if self._fmt == "asc":
                        f.write("End TriggerBlock\n")
                    break   # 외부 루프 탈출

            file_index += 1
            self.log_rotated.emit(self._make_path(file_index))

    @staticmethod
    def _write_batch(f, batch: list) -> None:
        for msg in batch:
            f.write(LogWorker._format_asc(msg))

    @staticmethod
    def _format_asc(msg) -> str:
        data_hex = msg.data.hex(" ").upper()
        direction = "Tx" if msg.is_tx else "Rx"   # Rev 6.0: is_tx 필드 활용
        return (f"{msg.timestamp:.6f} {msg.ch_id + 1}  "
                f"{msg.arb_id:X}  {direction}  d  {msg.dlc}  {data_hex}\n")

    def stop(self) -> None:
        self._running = False
        self.wait()
```

### 3.12. SimWorker — _messages Lock 추가 (Rev 6.0 버그 수정)

**Rev 5.0까지의 설계:** SimMessage 독립 타이밍(`next_send_at`), drift 보정, 유휴 CPU 방어(sleep(0.1)).

**Rev 6.0 버그 수정 [버그②] — _messages Lock 누락:**
`add_message()` / `remove_message()`는 메인 스레드(UI 사용자 조작)에서 호출되고, `_send_due_messages()`는 SimWorker 스레드에서 동시에 `_messages` 리스트를 순회한다. `CANWorker`에 `_stats_lock`을 달았던 것처럼, `_messages_lock`을 추가하여 동시 접근을 방어한다.

```python
# core/sim_worker.py
import time
from dataclasses import dataclass, field
from threading import Lock
from PySide6.QtCore import QThread

@dataclass
class SimMessage:
    arb_id:       int
    data:         bytes
    interval_ms:  float
    next_send_at: float = field(default_factory=time.perf_counter)

    def is_due(self, now: float) -> bool:
        return now >= self.next_send_at

    def update_next(self, now: float) -> None:
        """
        Rev 5.0: drift 보정 — 예정 시각 기준으로 다음 주기 계산.
        크게 밀렸을 경우 리셋하여 메시지 폭주 방지.
        """
        self.next_send_at += self.interval_ms / 1000.0
        if now - self.next_send_at > self.interval_ms / 1000.0:
            self.next_send_at = now + self.interval_ms / 1000.0

    def to_can_message(self):
        import can
        return can.Message(arbitration_id=self.arb_id, data=self.data, is_extended_id=False)


class SimWorker(QThread):
    def __init__(self, ch_id: int, bus_sender: "CANWorker") -> None:
        super().__init__()
        self._ch_id         = ch_id
        self._bus_sender    = bus_sender
        self._stop          = False
        self._messages:     list[SimMessage] = []
        self._messages_lock = Lock()   # Rev 6.0: add/remove(메인 스레드) + _send(Worker 스레드) 동시 접근 방어

    def run(self) -> None:
        while not self._stop:
            with self._messages_lock:
                msgs_snapshot = list(self._messages)   # 스냅샷으로 순회 안전성 보장

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
                pass   # busy-wait 마지막 1ms (정밀도 확보, CANoe 동일 방식)

    def _send_due_messages(self, now: float, msgs: list) -> None:
        for sm in msgs:
            if sm.is_due(now):
                self._bus_sender.send(sm.to_can_message())
                self._bus_sender.increment_tx()
                sm.update_next(now)

    def add_message(self, msg: SimMessage) -> None:
        """메인 스레드에서 호출."""
        with self._messages_lock:
            self._messages.append(msg)

    def remove_message(self, arb_id: int) -> None:
        """메인 스레드에서 호출."""
        with self._messages_lock:
            self._messages = [m for m in self._messages if m.arb_id != arb_id]

    def stop(self) -> None:
        self._stop = True
        self.wait()
```

> **SimWorker 타이밍 트레이드오프:**
> - `busy-wait` 구간(마지막 1ms)은 CPU 코어 1개를 100% 점유한다.
> - 이는 Vector CANoe가 내부적으로 동일하게 사용하는 방식이며, ms 단위 CAN 전송 정밀도를 위한 필연적인 트레이드오프다.
> - 메시지가 없는 유휴 상태에서는 sleep(0.1)만 실행되므로 CPU 점유가 없다.
> - **Rev 6.0:** Windows 타이머 해상도를 1ms로 설정하면(`timeBeginPeriod(1)`) sleep 정밀도가 대폭 향상된다. 아래 3.16절 참조.

### 3.13. Windows 타이머 해상도 설정 (Rev 6.0 신규)

> **Rev 6.0 버그 수정 [버그④] — Windows 타이머 해상도:**
> Windows 기본 타이머 해상도는 **15.6ms**다. `time.sleep(0.001)` 호출이 실제로는 최대 15ms씩 대기할 수 있어, 10ms 주기 메시지 전송 정확도에 직접적인 영향을 준다. 앱 시작 시 `timeBeginPeriod(1)`로 1ms 해상도로 올리고, 종료 시 `timeEndPeriod(1)`로 복원한다.

```python
# src/main.py
import ctypes
import os
import sys
from PySide6.QtWidgets import QApplication
from app.main_window import MainWindow

def _set_timer_resolution() -> None:
    """Windows 타이머 해상도를 1ms로 설정 (기본값 15.6ms → 1ms)."""
    if os.name == 'nt':
        ctypes.windll.winmm.timeBeginPeriod(1)

def _restore_timer_resolution() -> None:
    """앱 종료 시 타이머 해상도 복원."""
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

> **효과:** SimWorker의 `time.sleep(sleep_sec - 0.001)` 구간의 정밀도가 ~15ms에서 ~1ms로 향상된다. 10ms 주기 메시지 전송 정확도가 ±15ms에서 ±1ms 수준으로 개선된다. 구현 비용 대비 효과가 가장 큰 수정이다.

### 3.14. Trace 컬러링 — Tx/Rx/Error 색상 구분 (Rev 6.0 신규)

> **Rev 6.0 설계 추가 [설계⑥]:** `TraceModel.data()`에 `Qt.ForegroundRole` 처리를 추가하여 메시지 종류별 색상을 적용한다. `ParsedMessage.is_tx` 필드(`is_tx: bool = False`)를 선행 조건으로 한다. `SimWorker`가 전송한 메시지는 `is_tx=True`로 에코 피드백하여 CANoe와 유사한 경험을 제공한다.

```python
# models/trace_model.py (ForegroundRole 추가 부분)
from PySide6.QtGui import QColor
from PySide6.QtCore import Qt

# 컬러 상수
COLOR_TX    = QColor("#2196F3")   # 파랑 — Tx (SimWorker 전송)
COLOR_ERROR = QColor("#F44336")   # 빨강 — Error Frame
COLOR_RX    = None                # 기본 (흰색/검정, 테마 의존)

class TraceModel:   # QAbstractItemModel 상속
    ...
    def data(self, index, role=Qt.DisplayRole):
        msg = self._rows[index.row()]
        if role == Qt.ForegroundRole:
            if msg.is_error:
                return COLOR_ERROR
            if msg.is_tx:
                return COLOR_TX
            return COLOR_RX   # 기본값
        # ... DisplayRole 처리
```

> **SimWorker Tx 에코 피드백:**
> `SimWorker._send_due_messages()`에서 메시지 전송 후 `is_tx=True`로 설정한 `ParsedMessage`를 별도 Signal로 emit하여 Dispatcher에 피드백한다. 이 메시지는 Trace에만 표시되며 LogWorker에서 방향이 `Tx`로 기록된다.

### 3.15. 필터링 엔진 — HW / SW 이중 레이어

#### HW 필터 (python-can 백엔드 레벨)

`ChannelConfig`의 `hw_id_filter` / `hw_id_mask`를 python-can에 전달. CANWorker `_connect_and_listen()` 내부에서 적용. 불필요한 메시지를 H/W 수준에서 차단하므로 파이프라인 전체 부하가 감소한다.

#### SW 필터 (Trace Dock 레벨)

`MessageStore`의 데이터는 유지하되 화면 표시만 필터링한다.

```
Trace Dock 상단 필터 바:
  [ID: 0x1A0] [Mask: 0x7FF] [적용] [초기화]  [☑ CAN] [☑ LIN] [☑ Error] [Ch: All ▼]
```

### 3.16. Bus Statistics

`CANWorker.get_stats()`가 `ChannelStats`를 반환하고 `QTimer(1s)`로 UI에 전달한다. Tx는 `SimWorker`가 전송 시 `CANWorker.increment_tx()`를 호출하여 수집한다.

```
StatusBar 하단:
  CH1: Load 34.2% | Rx: 8,891/s | Tx: 1,204/s | Err: 0
  CH2: Load 12.1% | Rx: 2,341/s | Tx:   201/s | Err: 2
```

### 3.17. UI 배치 갱신 전략 + Auto-Scroll

```python
# app/main_window.py
class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self._auto_scroll = True

        self._trace_timer = QTimer(self)
        self._trace_timer.timeout.connect(self._flush_trace)
        self._trace_timer.start(50)

        self._graph_timer = QTimer(self)
        self._graph_timer.timeout.connect(self._flush_graph)
        self._graph_timer.start(100)

        self._stats_timer = QTimer(self)
        self._stats_timer.timeout.connect(self._flush_stats)
        self._stats_timer.start(1000)

    def _flush_trace(self) -> None:
        batch = self._message_store.flush()
        if batch:
            self._trace_model.append_batch(batch)
            if self._auto_scroll:
                self._trace_view.scrollToBottom()
        if self._message_store.drop_count > 0:
            self._show_buffer_warning(self._message_store.drop_count)

    def _toggle_auto_scroll(self, enabled: bool) -> None:
        self._auto_scroll = enabled

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

---

## 4. 상세 UI/UX 설계

### 4.1. UI/UX 목표

- QDockWidget을 활용하여 Trace, Simulation Dock은 기본 고정 레이아웃으로 표시한다.
- Graph Dock은 기본 숨김 상태이며, DBC 미로드 시 Graph 버튼이 비활성(gray)으로 표시된다.
- Trace Dock 상단에 채널 탭, 필터 바, Auto-Scroll 토글 버튼을 제공한다.
- **Trace Dock에서 Tx(파랑) / Error(빨강) 컬러링으로 메시지 종류를 즉시 식별한다. (Rev 6.0)**
- Simulation Dock의 신호 제어판은 Physical / Raw Hex 입력 전환을 지원한다.
- QSettings로 마지막 창 레이아웃·채널 설정·DB 경로를 저장/복원한다.
- View 메뉴에 "Reset Layout (Default)" 액션을 제공하여 초기 레이아웃으로 즉시 복구한다.
- 에러(연결 실패, DBC 오류, Bus-Off, 드롭 등)는 StatusBar 아이콘으로 표시하고, 클릭 시 ErrorDialog 팝업을 띄운다.

### 4.2. UI (TXT GUI) 시각화

#### 기본 레이아웃 (Graph Dock 숨김)

```
+-------------------------------------------------------------------------------------------+
| PyCANoe v1.0 (LGPL)                                                                       |
+-------------------------------------------------------------------------------------------+
| File  Edit  View  Connection  Tools  Help                                                 |
+-------------------------------------------------------------------------------------------+
| [+CH] [DBC] [Graph(비활성)] [Start ▶] [Stop ■] [Log ●]                                    |
+===========================================================================================+
| [Dock] Trace Monitor                                                                      |
| [All] [CH1: CAN 500k] [CH2: CAN 250k] [CH3: LIN] [CH4: ---]                              |
| [ID:0x___][Mask:0x7FF][적용][초기화] [☑ CAN][☑ LIN][☑ Err][Ch:All▼] [⬇ Auto Scroll ON]  |
|-------------------------------------------------------------------------------------------|
| Ch | Timestamp  | Type | ID   | DLC | Data (HEX)          | Signal (DBC)                 |
|  1 | 100.1234   | CAN  | 1A0  |  8  | 01 02 03 04 FF 00.. | EngSpeed: 1200.0 rpm  [Rx]    |
|  1 | 100.1245   | CAN  | 1A0  |  8  | 01 03 03 04 FF 00.. | EngSpeed: 1210.0 rpm  [Tx 🔵] |  ← is_tx 파랑
|  2 | 100.1240   | CAN  | 2B0  |  4  | FF 00 FF 00         |                      [Rx]    |
|  1 | 100.1278   | LIN  | 3C   |  8  | 00 00 00 00 00 00.. | L_Signal_A: 0.0       [Rx]    |
|  3 | 100.1290   | ERR  | ---  |  0  | ---                 |                      [🔴 ERR]| ← Error 빨강
+===========================================================================================+
| [Dock] Simulation (IG)   [CH1 ▼] [CH2 ▼]                                                 |
|-------------------------------------------------------------------------------------------|
| + [Tree] 메시지/신호         | + [Controls] 신호 제어판                                   |
| | ▾ CAN_Msg_A (100ms)[CH1] | | [Signal: EngSpeed]  [CH1]                              |
| |     [S] EngSpeed (1200)  | | 입력 단위: (●) Physical  ( ) Raw Hex                   |
| |     [S] VehSpeed (40)    | | 값 (rpm):  [ 1200.0   ]                                |
| |   ▸ LIN_Msg_C (500)[CH3] | | 슬라이더:  [    |=======o    ] (0 ~ 8000)              |
| |                          | | Waveform:  [None ▼] [Ramp ▼] [Sine ▼]                  |
| +--------------------------+ +--------------------------------------------------------|
+-------------------------------------------------------------------------------------------+
| [●CH1:500k VN1610][●CH2:250k][○CH3:---][DBC:car.dbc][Log:● REC 00:02:34]                 |
| CH1: Load 34.2% Rx:8891 Tx:1204 Err:0  | CH2: Load 12.1% Rx:2341 Tx:201 Err:0            |
+-------------------------------------------------------------------------------------------+
```

### 4.3. 컴포넌트별 상세 명세

#### MainWindow (QMainWindow)
- `QTimer(50ms)` — MessageStore flush → TraceModel 배치 갱신 → Auto-Scroll 판단.
- `QTimer(100ms)` — SignalBufferRegistry → pyqtgraph setData 갱신.
- `QTimer(1000ms)` — CANWorker.get_stats() → ChannelStats → Bus Statistics UI 갱신.
- View 메뉴: "Reset Layout (Default)" — 초기 레이아웃 바이트 하드코딩 + `restoreState()` 복구.
- StatusBar: 채널별 연결 상태 + DBC 로드 상태 + 로그 녹화 + Bus Stats + 드롭 경고 + **Log Rotation 알림 (Rev 6.0)**.

#### Channel Add Dialog (QDialog)
- 채널 ID 선택 (0~3, 미사용 슬롯만 표시), Interface, Channel, Baudrate 드롭다운.
- CAN-FD 모드 토글 + Data Baudrate. Vector App Name 입력.
- HW Filter: ID + Mask 입력 (선택 사항).
- DBC/LDF Path: `[...]` + "로드 없이 시작" 체크박스.
- DBC 선택 시 AsyncDbLoader 비동기 로딩: ⏳ "파싱 중..." 스피너.

#### Trace Dock (QDockWidget)
- 채널 탭 `[All][CH1][CH2][CH3][CH4]` — 채널 필터 적용.
- 필터 바: ID/Mask, 타입 체크박스, 채널 드롭다운.
- `[⬇ Auto Scroll]` 토글 버튼. 기본 ON.
- **`setUniformRowHeights(True)` 필수** — 렌더링 성능 100배+ 향상.
- **`setAnimated(False)` 필수** — 애니메이션 연산 제거.
- 컬럼: Ch, Timestamp, Type, ID, DLC, Data (HEX), Signal (DBC 없으면 공백).
- `beginInsertRows` / `endInsertRows` 배치 처리.
- **Tx(파랑) / Error(빨강) 컬러링. ForegroundRole 적용. (Rev 6.0)**
- 우클릭 메뉴: Send to Graph (DBC 있을 때만 활성), Send to Simulation.

#### Graph Dock (QDockWidget)
- 기본 숨김. DBC 미로드 시 툴바 버튼 비활성.
- pyqtgraph PlotWidget. 채널별 색상 (CH1=파랑, CH2=초록, CH3=주황, CH4=빨강).
- Rolling Window 드롭다운: 5s / 10s / 30s / 전체.
- `NumpySignalBuffer.get_view()` → `PlotDataItem.setData(x, y)`.

#### Simulation Dock (QDockWidget)
- QSplitter 기반 IG 스타일.
- 좌측 (Tree): 채널 탭, 메시지/신호 계층, DBC 없으면 RAW 수동 입력.
- 우측 (Controls): `(●) Physical` / `( ) Raw Hex` 라디오 버튼. Waveform 드롭다운.
- SimWorker 유휴 상태(메시지 없음)에서 CPU 점유 없음.

---

## 5. 프로젝트 스캐폴딩

```
PyCANoe/
├── .gitignore
├── README.md
├── requirements.txt
├── requirements-dev.txt
├── build.spec                        # PyInstaller 빌드 스펙 (M3 조기 검증, M6 최종)
├── venv/
├── tests/
│   ├── fixtures/
│   │   ├── sample.dbc
│   │   └── sample.ldf
│   ├── test_parsed_message.py        # frozen 불변성, is_tx/is_brs 필드 존재 확인 (Rev 6.0)
│   ├── test_db_parser.py             # decode() None-safe, 캐싱 정확성, 핫스왑 캐시 초기화 (Rev 6.0)
│   ├── test_async_db_loader.py       # Signal emit 스레드 안전성, self 참조 수명
│   ├── test_message_store.py         # flush() 2스레드 안전성, 드롭 카운터
│   ├── test_numpy_signal_buffer.py   # 2스레드 + Lock, copy() 독립성
│   ├── test_log_queue.py             # maxsize 드롭, 블로킹 없음
│   ├── test_log_worker.py            # 잔여 배치 손실 없음 (Rev 6.0), Log Rotation 분할 (Rev 6.0)
│   ├── test_channel_stats.py         # Bus Load % 공식, calc_frame_bits, Rx+Tx 합산
│   ├── test_can_worker.py            # exponential backoff, get_stats() 레이스, parser_lock (Rev 6.0)
│   ├── test_sim_worker.py            # 독립 타이밍, starvation 없음, _messages_lock (Rev 6.0)
│   ├── test_virtual_pipeline.py      # virtual 인터페이스 2채널 E2E
│   └── conftest.py
└── src/
    ├── main.py                       # timeBeginPeriod(1) 포함 (Rev 6.0)
    ├── resources/
    ├── app/
    │   ├── main_window.py
    │   ├── config_manager.py         # QSettings + SETTINGS_VERSION 마이그레이션
    │   └── dialogs/
    │       ├── channel_dialog.py
    │       └── error_dialog.py
    ├── core/
    │   ├── channel_manager.py
    │   ├── can_worker.py             # parser_lock + update_db() 추가 (Rev 6.0)
    │   ├── dispatcher.py
    │   ├── sim_worker.py             # _messages_lock 추가 (Rev 6.0)
    │   ├── log_worker.py             # Log Rotation + 잔여 배치 수정 (Rev 6.0)
    │   ├── db_parser.py              # _msg_def_cache + clear_cache() 추가 (Rev 6.0)
    │   └── async_db_loader.py
    ├── models/
    │   ├── parsed_message.py         # is_tx, is_brs 필드 추가 (Rev 6.0)
    │   ├── channel_stats.py
    │   ├── message_store.py
    │   ├── numpy_signal_buffer.py
    │   ├── log_queue.py
    │   ├── sim_state_store.py
    │   └── trace_model.py            # ForegroundRole 컬러링 추가 (Rev 6.0)
    └── widgets/
        ├── trace_dock.py
        ├── graph_dock.py
        └── sim_dock.py
```

---

## 6. 메모리 예산 (4채널 풀 가동 기준)

| 구성요소 | 설정값 | 예상 메모리 |
| :---- | :---- | :---- |
| MessageStore | deque(100,000) × 1 | ~10 MB |
| NumpySignalBuffer | 고정 배열 5,000pts × 신호 50개 (copy() 포함) | ~4 MB |
| LogQueue | Queue(50,000) × 1 | ~5 MB |
| SimStateStore | dict (신호 수백 개) | < 1 MB |
| pyqtgraph 플롯 뷰 | 채널 4 × 신호 수 | ~4 MB |
| **순수 데이터 합계** | | **~24 MB** |
| Python 런타임 + PySide6 + pyqtgraph | | ~100~150 MB |
| **전체 프로세스 상한** | | **< 200 MB** |

> **Log Rotation (Rev 6.0):** 단일 ASC 파일 상한이 100MB로 제한되므로, 500kbps 풀 부하 장시간 운용 시 디스크 풀 크래시가 방지된다. 프로세스 메모리 예산에는 영향 없음.

---

## 7. 테스트 전략

### 7.1. 단위 테스트 필수 대상

| 테스트 대상 | 검증 내용 |
| :---- | :---- |
| `ParsedMessage` | frozen 불변성, CAN FD DLC 매핑, LIN `arb_id & 0x3F`, `msg_name` / `is_tx` / `is_brs` 필드 존재 확인 (Rev 6.0) |
| `DbParser.decode()` | DBC 없음→None, LIN 분기, decode 실패→None, 핫로드, `decode_with_name()` msg_name 반환 |
| `DbParser._msg_def_cache` | **Rev 6.0: 동일 arb_id 반복 호출 시 `get_message_by_frame_id()` 1회만 실행되는지 Mock으로 검증. 핫스왑 후 `clear_cache()` 호출 여부 확인.** |
| `AsyncDbLoader` | Signal이 메인 스레드에서 수신되는지 (pytest-qt), self 참조 없을 때 GC 수거 방어 확인 |
| `MessageStore.flush()` | 2스레드 동시 append/flush 안전성, 드롭 카운터 정확성 |
| `NumpySignalBuffer` | 2스레드 동시 접근 안전성(Lock), copy() 독립성 |
| `LogQueue` | maxsize 초과 시 드롭 + drop_count 증가, 통신 루프 블로킹 없음 |
| `LogWorker` | **Rev 6.0 [버그③]: stop() 직전 배치에 남은 메시지가 파일에 기록되는지 확인.** **Rev 6.0 [설계⑧]: 100MB 초과 시 파일 분할 및 새 파일 헤더 생성 확인.** |
| `ChannelStats.bus_load_pct` | calc_frame_bits(), Rx+Tx 합산, 100% 클램프, 0 bitrate 예외 처리 |
| `SimWorker` | **Rev 6.0 [버그②]: add_message(메인 스레드) + _send_due_messages(Worker 스레드) 동시 실행 후 크래시/데이터 손상 없음.** 독립 타이밍, starvation 없음, 유휴 sleep |
| `CANWorker` | exponential backoff, 정상 종료 break, get_stats() 레이스 (Rev 5.0), **parser_lock: update_db(메인) + decode(Worker) 동시 실행 후 crach 없음 (Rev 6.0)** |
| virtual 파이프라인 | python-can virtual 2채널 E2E 송수신 + ParsedMessage 내용 검증 |

### 7.2. 인수 기준 (각 마일스톤 공통)

모든 마일스톤에서 아래 조건을 만족해야 다음 단계로 진행한다.

- `pytest tests/` 전체 통과 (커버리지 80% 이상 목표)
- H/W 없는 환경 (`virtual` 인터페이스)에서도 테스트 통과
- 메모리 프로파일 (`tracemalloc` 기준) 상한 초과 없음
- 백그라운드 스레드에서 UI 위젯 직접 접근 없음 (Qt Warning 로그 없음)

---

## 8. 마일스톤 계획 (Rev 6.0 재조정)

> **M2/M3 순서 유지 이유:** H/W 실기기 테스트(M3 Trace) 중 버그 발생 시 ASC 로그 파일이 없으면 재현이 불가능하다. 로깅(ASC 우선)을 M2로 앞당겨 H/W 디버깅 도구를 먼저 확보한다.
>
> **Rev 6.0 마일스톤 변경 요점:**
> - `ParsedMessage` P0 동결 항목에 `is_tx`, `is_brs` 추가 (M1)
> - Log Rotation을 M2에서 함께 구현 (별도 마일스톤 불필요)
> - Windows 타이머 해상도 설정을 M2 시작 시점에 적용 (이후 모든 타이밍 테스트에 영향)
> - Trace 컬러링을 M3에서 구현 (is_tx 필드 M1 확정 후)
> - **PyInstaller 최소 빌드 검증을 M3 완료 시점으로 앞당김** — M6까지 미루면 DLL/hiddenimport 문제를 늦게 발견할 위험이 있다.

### M1 — 아키텍처 POC + 핵심 데이터 모델 확정

**목표:** Rev 6.0에서 발견된 버그들이 모두 반영된 구현으로 시작한다.

**Task:**

1. `[Setup]` git init, venv, `.gitignore`, `requirements.txt`, `requirements-dev.txt` 작성 및 설치.
2. `[Setup]` 스캐폴딩 생성. `tests/fixtures/sample.dbc`, `sample.ldf` 준비.
3. `[P0-Design]` `ParsedMessage` dataclass 확정. **Rev 6.0: `is_tx: bool = False`, `is_brs: bool = False` 포함.** `msg_name` 포함. 팀 리뷰 후 동결.
4. `[P0-Design]` `ChannelStats` + `bus_load_pct` + `calc_frame_bits()` 구현 및 단위 테스트.
5. `[Spike]` `test_hw.py` — python-can + Vector H/W CLI 수신 검증.
6. `[Spike]` `test_dbc.py` — cantools DBC decode() + DBC 없이 None 반환 경로 검증.
7. `[Spike]` `test_virtual.py` — virtual 인터페이스 2채널 송수신 검증.
8. `[Impl]` `NumpySignalBuffer` (Lock + copy()) 구현 + 단위 테스트 (2스레드 + tracemalloc).
9. `[Impl]` `MessageStore` (드롭 로직) 구현 + 단위 테스트 (2스레드 + overflow 카운터).
10. `[Impl]` `AsyncDbLoader` 구현 + pytest-qt 테스트. **self 참조 보유 패턴 검증 포함.**
11. `[Arch-POC]` 6개 핵심 파일 POC: `ParsedMessage` emit, `MessageStore` flush, `QTimer(50ms)` → StatusBar 수신 건수 표시.

**인수 기준 (M1 AC):**

- AC1: 'Add Channel' 2개 + 가상 메시지 수신 상태에서 UI 드래그 시 절대 멈추지 않는다.
- AC2: DBC 없이 채널 추가 시 `signals=None`인 `ParsedMessage`가 오류 없이 수신된다.
- AC3: `test_virtual.py` H/W 없이 통과.
- AC4: `NumpySignalBuffer` 2스레드 + tracemalloc 테스트 통과.
- AC5: `MessageStore` 2스레드 + 드롭 카운터 정확성 테스트 통과.
- AC6: `AsyncDbLoader` pytest-qt Signal 수신 테스트 통과 (메인 스레드 수신 확인).
- **AC7 (Rev 6.0 신규):** `ParsedMessage`에 `is_tx`, `is_brs` 필드가 존재하고 frozen 동결 상태. 추가 필드 없이 P0 동결 선언.

---

### M2 — 로깅 (ASC) + Log Rotation + Windows 타이머 해상도

**목표:** H/W 실기기 테스트에 앞서 ASC 로그 파일 생성 기능을 완성한다. Rev 6.0 타이머 해상도 설정을 이 시점에 적용하여 이후 모든 타이밍 테스트의 정확도를 보장한다.

**Task:**

1. **`[Rev 6.0 버그④]` `main.py`에 `timeBeginPeriod(1)` / `timeEndPeriod(1)` 추가.** `os.name == 'nt'` 분기로 Windows 전용 적용. 이후 SimWorker sleep 정밀도 향상.
2. `LogQueue` + `LogWorker` 구현. 청크 5,000건, `log_dropped` Signal.
3. ASC 포맷 구현 및 검증. CANalyzer 호환 헤더(`Begin Triggerblock`) 및 푸터(`End TriggerBlock`) 포함. 실제 CANalyzer에서 파일이 열리는지 검증.
4. **`[Rev 6.0 버그③]` 종료 시 잔여 배치 손실 방지 코드 추가 및 단위 테스트.**
5. **`[Rev 6.0 설계⑧]` Log Rotation: 100MB 초과 시 `log_001.asc`, `log_002.asc` 파일 분할. `log_rotated` Signal → StatusBar 갱신. 단위 테스트 포함.**
6. 채널별 분리 저장 / 통합 저장 옵션.
7. StatusBar "Log Dropped: N건" 경고 아이콘 연동.
8. 로그 녹화 시작/종료 UI 버튼 + 녹화 경과 시간 표시.

**인수 기준:** 1분간 4채널 풀 부하 수신 후 ASC 파일 정상 생성. 100MB 초과 시 자동 파일 분할 확인. 드롭 발생 시 StatusBar에 표시. stop() 직전 배치 손실 없음.

---

### M3 — Trace Dock 고성능 구현 + Tx/Rx 컬러링 + PyInstaller 조기 검증

**목표:** 초당 5,000+ 메시지 수신 시에도 Trace UI가 응답 가능한 상태를 유지한다. Tx/Rx/Error 컬러링을 구현하여 CANoe 수준의 가시성을 확보한다. **PyInstaller 최소 빌드를 이 시점에 검증하여 DLL/hiddenimport 문제를 조기 발견한다.**

**Task:**

1. `TraceModel` 구현. `beginInsertRows` / `endInsertRows` 배치 처리.
2. **`setUniformRowHeights(True)` 및 `setAnimated(False)` 필수 설정.**
3. **Auto-Scroll 토글 버튼** 구현. 스마트 스크롤 감지 연동.
4. **`[Rev 6.0 설계⑥]` Trace 컬러링: `ForegroundRole` 처리 추가. `is_tx=True` → 파랑, `is_error=True` → 빨강. SimWorker Tx 에코 피드백 연동.**
5. 채널 탭 `[All][CH1][CH2][CH3][CH4]`, SW 필터 바, HW 필터 연동.
6. `CANWorker.update_db()` + `parser_lock` 구현 및 통합 테스트. (DB 핫스왑 Rev 6.0)
7. `DbParser._msg_def_cache` + `clear_cache()` 구현 및 단위 테스트. (캐싱 Rev 6.0)
8. CANWorker exponential backoff 재연결 + ErrorDialog 연동.
9. View > "Reset Layout (Default)" 구현.
10. **`[Rev 6.0 마일스톤]` PyInstaller 최소 빌드 검증:**
    - 현재까지 구현된 기능(Trace + Log)으로 `.exe` 생성.
    - `build.spec`에 Vector DLL + lark hiddenimport 포함 확인.
    - Python 없는 PC에서 실행 검증.
    - 문제 발견 시 M3 내에서 즉시 수정.

**인수 기준:** 500kbps 풀 부하 수신 중 UI 드래그 멈춤 없음. Auto-Scroll ON/OFF 정상 동작. Tx 메시지 파랑 컬러 확인. Error 메시지 빨강 컬러 확인. 최소 `.exe` 빌드 성공 및 Vector H/W 없는 PC에서 실행 확인.

---

### M4 — Graph Dock 구현

**Task:**

1. `SignalBufferRegistry` + `NumpySignalBuffer` 연동. `get_view()` → `setData()`.
2. `AsyncDbLoader` 연동. StatusBar 스피너 + `db_loaded` Signal → `enable_all()`.
3. Graph Dock 기본 숨김. DBC 로드 완료 시 Graph 버튼 활성화.
4. 채널별 색상 구분. Rolling Window 드롭다운.

**인수 기준:** 신호 50개 동시 모니터링 시 Graph 갱신 끊기지 않음. DBC 로드 중 UI 응답 유지.

---

### M5 — Simulation (IG) 구현

**Task:**

1. `SimMessage` dataclass 구현. `next_send_at` 필드 + `is_due()` + `update_next()` drift 보정 포함.
2. **`[Rev 6.0 버그②]` `SimWorker._messages_lock` 구현 및 단위 테스트. add_message/remove_message Lock 포함.**
3. `SimWorker` drift 보정 + busy-wait + 유휴 sleep(0.1) 구현. 메시지별 독립 타이밍 적용.
4. **Tx 에코 피드백: 전송 메시지를 `is_tx=True`로 설정하여 Dispatcher로 emit → Trace 컬러링 연동.**
5. Simulation Dock: QSplitter + QTreeWidget + QStackedWidget.
6. Physical / Raw Hex 라디오 버튼. Waveform. DBC 없는 경우 RAW 수동 입력.
7. `SimWorker.increment_tx()` → `CANWorker.get_stats()` Tx 카운터 연동.

**인수 기준:** 100ms 주기 메시지가 95~105ms 범위 내 전송 (Windows 타이머 1ms 해상도 기준). 주기 다른 메시지 혼재 시 starvation 없음. 메시지 없을 때 CPU 점유 없음. Tx 메시지 Trace에서 파랑으로 표시.

---

### M6 — 통합, 안정화 및 최종 배포

**목표:** 모든 기능을 통합하고 현장 배포 가능한 단일 실행 파일을 생성한다.

**Task:**

1. Bus Statistics Dock/StatusBar 구현 (`ChannelStats.bus_load_pct` 포함).
2. QSettings: 채널 설정·DB 경로·레이아웃 저장/복원. SETTINGS_VERSION 키 + `_migrate()` 마이그레이션 전략:

   ```python
   # app/config_manager.py
   SETTINGS_VERSION = 1

   class ConfigManager:
       def load(self) -> dict:
           ver = self._s.value("settings_version", 0, type=int)
           if ver < SETTINGS_VERSION:
               self._migrate(ver)
           ...

       def _migrate(self, from_ver: int) -> None:
           if from_ver < 1:
               pass   # v0 → v1: 키 이름 변경 등
           self._s.setValue("settings_version", SETTINGS_VERSION)
   ```
3. BLF / CSV 로깅 포맷 추가 (LogWorker 확장).
4. pytest 전체 커버리지 80% 이상 달성.
5. `tracemalloc` 메모리 프로파일링: 30분 풀 가동 후 누수 없음 확인.
6. 최종 통합 테스트: 4채널 동시 운용, DBC 핫로드, Bus-Off 재연결, 로그 드롭 경고, Auto-Scroll, Log Rotation.
7. **PyInstaller 최종 빌드** (M3에서 조기 검증 완료, M6에서 전체 기능 포함 최종 빌드):

   ```python
   # build.spec
   a = Analysis(
       ['src/main.py'],
       binaries=[
           ('C:/Program Files/Vector XL Driver Library/bin/vxlapi64.dll', '.'),
       ],
       hiddenimports=[
           'can.interfaces.vector',
           'can.interfaces.virtual',
           'lark',
           'lark.grammars',
       ],
       datas=[
           ('venv/Lib/site-packages/cantools/database/can/formats/dbc.lark',
            'cantools/database/can/formats'),
       ],
       ...
   )
   ```

   ```bash
   pyinstaller build.spec
   # 결과물: dist/PyCANoe.exe
   ```
8. Python 환경 없는 PC에서 `dist/PyCANoe.exe` 실행 검증.

---

### M7 (Future) — Virtual Node Engine

**목표:** 사용자 Python 스크립트로 독립적인 시뮬레이션 노드를 구성한다. (CANoe CAPL 대체)

1. 사용자 `.py` 스크립트 동적 로드 (`importlib`).
2. `on_message(msg: ParsedMessage)` 콜백 인터페이스.
3. `QTimer` 연동 주기 콜백 `on_timer(interval_ms)`.
4. 스크립트 내 메시지 전송 API: `bus.send(arb_id, data)`.

> **M7 리팩토링 시점:** Virtual Node Engine 구현 시 MessageDispatcher가 복잡해질 경우 Event Bus 패턴으로 전환을 검토한다. 현재 단계에서는 추상화 레이어 추가가 디버깅을 어렵게 하므로 유보.

---

## 9. 종합 설계 결정 사항 (Design Decision Log)

| 결정 항목 | 선택 | 이유 / 트레이드오프 |
| :---- | :---- | :---- |
| decode 위치 | CANWorker 내부 | Qt QueuedConnection 특성상 Dispatcher가 UI 스레드에서 실행될 수 있음. Worker 내부 실행으로 UI 스레드 완전 보호. |
| SignalBuffer 자료구조 | 고정 numpy 배열 + Lock + copy() | GC 대상 배열 초당 수천 개 생멸 → 프레임 드랍. Lock으로 Race Condition 방지. copy()로 UI 렌더링 중 배열 오염 방지. |
| DbParser 비동기 로딩 | AsyncDbLoader(QObject) + threading.Thread(daemon) | ThreadPoolExecutor 누수 제거. 백그라운드 콜백 직접 호출 시 UI 크래시(Segfault). Qt Signal(QueuedConnection)만이 메인 스레드 안전 전달 보장. |
| MessageStore 드롭 카운터 | flush() 시 overflow 계산 | append()에서 판단 시 _pending 무제한 성장 가능. flush() 시 합산으로 정확한 overflow 계산. |
| CANWorker 정상 종료 | 명시적 break | 정상 종료 후 retry_count=0 실행이 의도적으로 보이지 않아 구현 혼란 유발. |
| SimWorker 유휴 상태 | sleep(0.1) | 메시지 없을 때도 루프가 계속 돌면 CPU 점유. sleep(0.1)로 유휴 상태 완전 해소. |
| SimWorker 타이밍 정밀도 | perf_counter + busy-wait 1ms | Windows msleep/sleep 해상도 한계. busy-wait으로 1ms 이하 정밀도 확보. CANoe 동일 방식. |
| LogWorker 청크 크기 | 5,000건 | 100건은 SSD I/O 호출 빈도 과다. 5,000건으로 I/O 호출 50분의 1 감소. |
| 재연결 전략 | exponential backoff [1,2,4,8,16]초, MAX_RETRY=5 | 즉시 재시도는 H/W 오류 복구 중 과도한 에러 루프 유발. 최대 약 31초 내 포기. |
| CANWorker 통계 Lock (Rev 5.0) | threading.Lock on increment + get_stats | GIL이 있어도 read→clear 원자성 미보장. Lock으로 원자적 수집+초기화 보장. |
| SimMessage 독립 타이밍 (Rev 5.0) | 메시지별 next_send_at + update_next() drift 보정 | min_interval 기준 단일 루프 주기: 짧은 주기가 긴 주기 메시지 스케줄을 지배 → starvation. 메시지별 독립 next_send_at으로 해소. |
| AsyncDbLoader self 참조 (Rev 5.0) | MainWindow에서 반드시 self._db_loader로 저장 | 로컬 변수로만 보유 시 GC 수거 → Segfault. 명시적 경고 문서화. |
| ASC 파일 헤더 (Rev 5.0) | CANalyzer 호환 헤더/푸터 필수 | 헤더 없으면 CANalyzer/CANoe가 파일 인식 불가. |
| ParsedMessage.msg_name (Rev 5.0) | P0에서 확정 | Trace UI 표시에 필요. 추후 추가 시 전 계층 파급. P0 확정으로 비용 최소화. |
| QSettings 마이그레이션 (Rev 5.0) | SETTINGS_VERSION 키 + _migrate() | 배포 후 스키마 변경 시 구버전 설정 로드 실패 방지. |
| **DB 핫스왑 parser_lock (Rev 6.0)** | **CANWorker에 _parser_lock 추가. update_db() + decode() 구간 Lock 보호** | **AsyncDbLoader 완료(메인 스레드)와 CANWorker decode(Worker 스레드) 동시 실행 시 이전 DbParser 참조로 decode 가능. parser_lock으로 교체 원자성 보장.** |
| **SimWorker._messages_lock (Rev 6.0)** | **threading.Lock on add/remove/send** | **add_message(메인 스레드) + _send_due_messages(Worker 스레드) 동시 접근으로 리스트 변형 크래시 가능. Lock + 스냅샷 순회로 방어.** |
| **LogWorker 잔여 배치 (Rev 6.0)** | **루프 탈출 후 잔여 배치 처리 추가** | **_running=False → 루프 탈출 시 batch에 남은 메시지가 기록되지 않는 버그. 종료 경로에서 반드시 flush.** |
| **Windows 타이머 해상도 (Rev 6.0)** | **timeBeginPeriod(1) + timeEndPeriod(1)** | **기본 15.6ms 해상도에서 sleep(0.001)이 실제로 15ms씩 대기. 1ms 해상도 설정으로 SimWorker 10ms 주기 정확도 확보. 구현 비용 최소, 효과 최대.** |
| **DbParser 메시지 정의 캐싱 (Rev 6.0)** | **_msg_def_cache dict + clear_cache()** | **5,000fps에서 초당 5,000번 get_message_by_frame_id() 호출. 캐싱으로 최초 1회 탐색 후 O(1) 접근. DB 핫스왑 시 clear_cache() 필수.** |
| **ParsedMessage is_tx + is_brs (Rev 6.0)** | **P0 동결 시점에 함께 추가** | **is_tx는 Trace 컬러링 필수. is_brs는 CAN FD BRS 플래그. P0 동결 후 추가 시 전 계층 파급. 이 시점에 확정.** |
| **Trace 컬러링 (Rev 6.0)** | **ForegroundRole. is_tx→파랑, is_error→빨강** | **구현 비용 낮음(data() 메서드 추가). 실사용 가치 높음. is_tx 필드 선행 조건. M3에서 함께 구현.** |
| **Log Rotation (Rev 6.0)** | **100MB 상한, log_001.asc 분할** | **500kbps 풀 부하 1시간 → 1~2GB. 단일 파일 무제한 성장 시 디스크 풀 크래시. M2에서 함께 구현.** |
| **PyInstaller 조기 검증 (Rev 6.0)** | **M3 완료 시점 최소 빌드** | **M6까지 미루면 Vector DLL/lark hiddenimport 문제를 최종 단계에서 발견. M3에서 조기 검증으로 리스크 제거.** |
| Event Bus 전환 | 유보 (M7 시점 재검토) | 현재 MessageDispatcher로 충분. 추상화 레이어 추가 시 개인 프로젝트 디버깅 난이도 상승. Virtual Node Engine 구현 시 재검토. |
| multiprocessing GIL 우회 | 유보 (프로파일링 후 결정) | cantools 내부가 C 확장이라 순수 Python보다 훨씬 빠름. perf_counter 기반 프로파일링으로 병목 확인 후 필요 시 도입. |
