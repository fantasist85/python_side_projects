# PyCANoe 개발 현황 기록

> **기준 브랜치:** `PyCANoe`  
> **명세서 버전:** Rev 9.0  
> **기록 작성일:** 2026-04-06  
> **다음 작업:** STEP 10 - TraceDock 기능 보완 + M2(LogWorker) 검증 시작  

---

## 1. 구현 완료 현황 (STEP 기준)

| STEP | 대상 | 파일 | 상태 | 비고 |
|:---:|:---|:---|:---:|:---|
| 1 | `ParsedMessage` | `models/parsed_message.py` | ✅ 완료 | frozen+slots, P0 동결 선언 완료 |
| 2 | `ChannelStats` | `models/channel_stats.py` | ✅ 완료 | calc_frame_bits, bus_load_pct 구현 |
| 3 | `MessageStore` | `models/message_store.py` | ✅ 완료 | deque(100k)+Lock, flush() 구현 |
| 4 | `DbParser` | `core/db_parser.py` | ✅ 완료 | _MISS sentinel, DBC/LDF 분기, 캐싱 |
| 4 | `AsyncDbLoader` | `core/async_db_loader.py` | ✅ 완료 | daemon Thread + self 바인딩 패턴 |
| 5 | `CANWorker` | `core/can_worker.py` | ✅ 완료 | exponential backoff, _parser_lock |
| 6 | `MessageDispatcher` | `core/dispatcher.py` | ✅ 완료 | QueuedConnection fan-out |
| 7 | `NumpySignalBuffer` + `SignalBufferRegistry` | `models/numpy_signal_buffer.py` | ✅ 완료 | 링버퍼, enable/disable 분리 |
| 8 | `LogQueue` + `LogWorker` | `models/log_queue.py`, `core/log_worker.py` | ✅ 완료 | while-else 잔여배치, 100MB Rotation |
| 9 | `SimMessage` + `SimWorker` | `core/sim_worker.py` | ✅ 완료 | drift보정, busy-wait, list() 복사 |
| 10 | **UI 통합** | `app/`, `widgets/`, `models/trace_model.py` | ⚠️ **부분 완료** | 아래 상세 참조 |
| 11 | 4채널 + DB 핫스왑 + Bus Statistics | - | ❌ 미착수 | M6 범위 |

---

## 2. STEP 10 상세 현황 (UI 통합)

### 2.1 완료된 UI 파일

| 파일 | 내용 | 상태 |
|:---|:---|:---:|
| `models/trace_model.py` | TraceModel, beginInsertRows 배치, SW 필터, 컬러링 | ✅ 완료 |
| `widgets/trace_dock.py` | TraceDock(QTreeView), UniformRowHeights, scrollToBottom | ⚠️ **기능 미흡** |
| `widgets/graph_dock.py` | GraphDock, pyqtgraph PlotWidget, rolling window | ✅ 완료 |
| `widgets/sim_dock.py` | SimDock, QSplitter, Physical/Raw Hex 전환, SimWorker 연동 | ✅ 완료 |
| `app/main_window.py` | MainWindow, QTimer 3개, closeEvent Shutdown 시퀀스 | ✅ 완료 |
| `app/config_manager.py` | QSettings, SETTINGS_VERSION, _migrate() | ✅ 완료 |
| `app/dialogs/channel_dialog.py` | 채널 설정 다이얼로그 | ✅ 완료 |
| `app/dialogs/error_dialog.py` | 오류 표시 다이얼로그 | ✅ 완료 |
| `src/main.py` | 진입점, timeBeginPeriod(1) Windows 타이머 | ✅ 완료 |
| `core/channel_manager.py` | ChannelConfig, ChannelContext, ChannelManager | ✅ 완료 |

### 2.2 TraceDock 미구현 기능 (명세서 대비 gap)

명세서 Section 8.2 기준으로 현재 `TraceDock`에 **누락된 기능**:

```
[ ] SW 필터 UI (필터 입력 LineEdit + 적용 버튼)
    - TraceModel.set_filter() / clear_filter() 메서드는 구현되어 있음
    - TraceDock에서 UI 입력 → 모델 연결 코드가 없음
    - MainWindow.closeEvent()에서 self._trace_dock.get_filter() 호출하나 메서드 미구현

[ ] 우클릭 컨텍스트 메뉴
    - "Send to Graph" → MainWindow._on_send_to_graph()
    - "Send to Simulation" → MainWindow._on_send_to_sim()
    - MainWindow 연결 코드는 있으나 TraceDock에서 Signal 미구현
      (send_to_graph, send_to_sim Signal이 없음)

[ ] get_filter() 메서드 미구현
    - MainWindow.closeEvent()에서 self._trace_dock.get_filter() 호출 → AttributeError 발생
```

> **⚠️ 주의:** `MainWindow`에서 `TraceDock.send_to_graph`, `TraceDock.send_to_sim` Signal을 connect하고 있으나, `TraceDock` 클래스에 해당 Signal이 선언되어 있지 않아 **앱 실행 시 AttributeError 발생**함.

---

## 3. 테스트 파일 현황

| 파일 | STEP | 상태 |
|:---|:---:|:---:|
| `test_parsed_message.py` | 1 | ✅ 작성 완료 |
| `test_channel_stats.py` | 2 | ✅ 작성 완료 |
| `test_message_store.py` | 3 | ✅ 작성 완료 |
| `test_db_parser.py` | 4 | ✅ 작성 완료 |
| `test_async_db_loader.py` | 4 | ✅ 작성 완료 |
| `test_can_worker.py` | 5 | ✅ 작성 완료 |
| `test_log_queue.py` | 8 | ✅ 작성 완료 |
| `test_log_worker.py` | 8 | ✅ 작성 완료 |
| `test_numpy_signal_buffer.py` | 7 | ✅ 작성 완료 |
| `test_sim_worker.py` | 9 | ✅ 작성 완료 |
| `test_virtual_pipeline.py` | E2E | ✅ 작성 완료 |
| `conftest.py` | 공통 | ✅ 작성 완료 (명세서 11.4 준수) |
| `fixtures/sample.dbc` | - | ✅ 있음 |
| `fixtures/sample.ldf` | - | ❌ **없음** (sample.ldf 파일 미생성) |

> **⚠️ 주의:** `sample.ldf` 파일이 없어 LDF 관련 테스트는 skip 또는 실패할 수 있음.

---

## 4. 마일스톤 진행 상태

| M# | 이름 | 상태 | 비고 |
|:---:|:---|:---:|:---|
| M1 | 아키텍처 POC + 핵심 데이터 모델 | ⚠️ **95%** | TraceDock Signal/메서드 미완성으로 UI 크래시 있음 |
| M2 | 로깅 (ASC) + Log Rotation | ⚠️ **90%** | LogWorker 코드 완성, **테스트 실행 검증 미완** |
| M3 | Trace Dock + 컬러링 + PyInstaller | ⚠️ **60%** | 컬러링(TraceModel) 완성, SW 필터 UI / 우클릭 메뉴 미완성 |
| M4 | Graph Dock | ⚠️ **85%** | GraphDock 완성, + 신호 추가 DBC 팝업 TODO 남음 |
| M5 | Simulation (IG) | ⚠️ **90%** | SimDock + SimWorker 완성, tx_echo → Dispatcher 연결 누락 확인 필요 |
| M6 | 통합, 안정화, 최종 배포 | ❌ 미착수 | |
| M7 | Virtual Node Engine | ❌ 미착수 | Future scope |

---

## 5. 다음 작업 우선순위 (권장 순서)

### [우선 1] TraceDock 누락 기능 구현 — `widgets/trace_dock.py`

현재 `MainWindow`가 connect하려는 Signal/메서드가 `TraceDock`에 없어 **앱이 정상 실행되지 않는 버그**.
이 항목 해결 없이는 통합 테스트 불가.

구현 필요 항목:
```python
# widgets/trace_dock.py 에 추가 필요

# 1) Signal 선언
from PySide6.QtCore import Signal
send_to_graph = Signal(int, str)   # (ch_id, sig_name)
send_to_sim   = Signal(int, int, int, bytes)  # (ch_id, arb_id, dlc, data)

# 2) 우클릭 컨텍스트 메뉴 구현
#    QTreeView.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
#    QTreeView.customContextMenuRequested.connect(_on_context_menu)

# 3) SW 필터 UI 구현
#    QLineEdit (ID 입력) + QPushButton (적용/초기화) → TraceModel.set_filter()

# 4) get_filter() 메서드 구현
def get_filter(self) -> tuple[str, str]:
    ...
```

### [우선 2] `sample.ldf` fixture 파일 생성

LDF 파싱 테스트를 위한 최소한의 LDF fixture 파일 필요.
간단한 LIN 2.x 형식으로 생성.

### [우선 3] pytest 전체 실행하여 실제 통과 현황 확인

```bash
cd PyCANoe
pip install -r requirements.txt -r requirements-dev.txt
pytest tests/ -v --tb=short 2>&1 | tee test_results.txt
```

### [우선 4] SimWorker tx_echo → Dispatcher 연결 확인

`SimWorker.tx_echo` Signal이 `MessageDispatcher.on_message()`에 연결되어야 Trace 파랑 컬러링이 동작함.
현재 `ChannelManager.add_channel()` 또는 `SimDock._start_message()`에서 이 연결이 누락된 것으로 보임.

확인 코드:
```python
# core/channel_manager.py 또는 widgets/sim_dock.py 에 필요
sim_worker.tx_echo.connect(
    dispatcher.on_message,
    Qt.ConnectionType.QueuedConnection
)
```

### [우선 5] M2 검증 — LogWorker 테스트 실행

명세서 STEP 8 완료 기준:
> stop() 직전 큐에 남은 메시지가 ASC 파일 End TriggerBlock 앞에 기록됨 확인.

```bash
pytest tests/test_log_worker.py -v
```

---

## 6. 아키텍처 핵심 규칙 요약 (세션 간 인수인계용)

```
[절대 불변 규칙 — 어떤 상황에서도 변경 금지]

1. ParsedMessage : frozen=True, slots=True — 필드 추가/변경 절대 금지
2. decode 위치   : CANWorker 내부만. Dispatcher/UI에서 decode 금지
3. UI 접근       : Main Thread 전용. Worker Thread에서 UI 직접 접근 금지
4. Qt Signal     : 스레드 간 통신은 Signal(QueuedConnection)만 허용
5. SimWorker 복사: list(self._messages) 생성자만 — deepcopy/= 할당/.copy() 금지
6. AsyncDbLoader : 반드시 self._db_loader로 바인딩 — 로컬 변수 즉시 GC → Segfault
7. terminate()   : 절대 금지 — H/W 포트 미해제 → BSoD/Segfault
8. Shutdown 순서 : QTimer 정지 → CANWorker.stop() → SimWorker.stop() → LogWorker.stop()
9. NumpySignalBuffer: enabled=False 기본값 — DBC 로드 후 enable_all()로만 활성화
10. LogWorker while-else: break 시 else 미실행(Rotation), 정상종료 시 else 실행(flush)
```

---

## 7. 디렉토리 구조 (현재 실제 파일 기준)

```
PyCANoe/
├── PyCANoe.md                        # 설계 명세서 Rev 9.0
├── requirements.txt                  # PySide6 pyqtgraph python-can cantools ldfparser numpy
├── requirements-dev.txt              # pytest pytest-qt pytest-mock pytest-cov pyinstaller
├── src/
│   ├── main.py                       # ✅ 진입점 + timeBeginPeriod(1)
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main_window.py            # ✅ 완성
│   │   ├── config_manager.py         # ✅ 완성
│   │   └── dialogs/
│   │       ├── __init__.py
│   │       ├── channel_dialog.py     # ✅ 완성
│   │       └── error_dialog.py       # ✅ 완성
│   ├── core/
│   │   ├── __init__.py
│   │   ├── can_worker.py             # ✅ 완성
│   │   ├── channel_manager.py        # ✅ 완성
│   │   ├── dispatcher.py             # ✅ 완성
│   │   ├── sim_worker.py             # ✅ 완성
│   │   ├── log_worker.py             # ✅ 완성
│   │   ├── db_parser.py              # ✅ 완성
│   │   └── async_db_loader.py        # ✅ 완성
│   ├── models/
│   │   ├── __init__.py
│   │   ├── parsed_message.py         # ✅ P0 동결
│   │   ├── channel_stats.py          # ✅ 완성
│   │   ├── message_store.py          # ✅ 완성
│   │   ├── numpy_signal_buffer.py    # ✅ 완성
│   │   ├── log_queue.py              # ✅ 완성
│   │   ├── sim_state_store.py        # ✅ 완성
│   │   └── trace_model.py            # ✅ 완성
│   └── widgets/
│       ├── __init__.py
│       ├── trace_dock.py             # ⚠️ Signal/우클릭/필터 UI 미구현
│       ├── graph_dock.py             # ✅ 완성
│       └── sim_dock.py               # ✅ 완성
└── tests/
    ├── __init__.py
    ├── conftest.py                   # ✅ 완성 (명세서 11.4)
    ├── fixtures/
    │   ├── sample.dbc                # ✅ 있음
    │   └── sample.ldf                # ❌ 없음 — 생성 필요
    ├── test_parsed_message.py        # ✅
    ├── test_channel_stats.py         # ✅
    ├── test_message_store.py         # ✅
    ├── test_db_parser.py             # ✅
    ├── test_async_db_loader.py       # ✅
    ├── test_can_worker.py            # ✅
    ├── test_log_queue.py             # ✅
    ├── test_log_worker.py            # ✅
    ├── test_numpy_signal_buffer.py   # ✅
    ├── test_sim_worker.py            # ✅
    └── test_virtual_pipeline.py      # ✅
```

---

## 8. 참고: 테스트 실행 방법

```bash
# 환경 설정 (Windows)
python -m venv venv && venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt

# 전체 테스트
cd PyCANoe
pytest tests/ -v

# 특정 테스트
pytest tests/test_db_parser.py -v        # STEP 4 완료 기준
pytest tests/test_log_worker.py -v       # STEP 8 완료 기준
pytest tests/test_sim_worker.py -v       # STEP 9 완료 기준

# 커버리지 측정
pytest tests/ --cov=src --cov-report=term-missing

# headless 환경 (CI/서버)
QT_QPA_PLATFORM=offscreen pytest tests/ -v
```

---

*이 파일은 세션 간 개발 현황 인수인계용입니다. 작업 완료 시 해당 항목의 상태를 갱신하세요.*
