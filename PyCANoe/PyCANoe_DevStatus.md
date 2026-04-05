# PyCANoe 개발 현황 기록

> **기준 브랜치:** `PyCANoe`  
> **명세서 버전:** Rev 9.0  
> **기록 갱신일:** 2026-04-06 (2차 세션)  
> **다음 작업:** M3 마무리 (PyInstaller 조기 검증) → M6 Bus Statistics Dock

---

## 1. STEP별 구현 완료 현황

| STEP | 대상 | 파일 | 상태 | 비고 |
|:---:|:---|:---|:---:|:---|
| 1 | `ParsedMessage` | `models/parsed_message.py` | ✅ 완료 | P0 동결 |
| 2 | `ChannelStats` | `models/channel_stats.py` | ✅ 완료 | |
| 3 | `MessageStore` | `models/message_store.py` | ✅ 완료 | |
| 4 | `DbParser` + `AsyncDbLoader` | `core/db_parser.py`, `core/async_db_loader.py` | ✅ 완료 | |
| 5 | `CANWorker` | `core/can_worker.py` | ✅ 완료 | |
| 6 | `MessageDispatcher` | `core/dispatcher.py` | ✅ 완료 | |
| 7 | `NumpySignalBuffer` + Registry | `models/numpy_signal_buffer.py` | ✅ 완료 | |
| 8 | `LogQueue` + `LogWorker` | `models/log_queue.py`, `core/log_worker.py` | ✅ 완료 | |
| 9 | `SimMessage` + `SimWorker` | `core/sim_worker.py` | ✅ 완료 | |
| 10 | **UI 통합** | `app/`, `widgets/`, `models/trace_model.py` | ✅ **완료** | 이번 세션 완성 |
| 11 | 4채널 + DB 핫스왑 + Bus Statistics | - | ❌ 미착수 | M6 범위 |

---

## 2. 이번 세션(2차) 작업 내역

### 2-1. `widgets/trace_dock.py` — 완전 재작성 ✅

**이전 문제:** `send_to_graph`, `send_to_sim` Signal 미선언 → MainWindow 초기화 시 AttributeError 발생으로 앱 실행 불가.

**구현 완료 항목:**
- `send_to_graph = Signal(int, str)` 선언
- `send_to_sim = Signal(int, int, int, object)` 선언
- SW 필터 바 UI (ID LineEdit + Mask LineEdit + 적용/초기화 버튼)
- 우클릭 컨텍스트 메뉴 (이 ID 필터링 / 클립보드 복사 / Send to Graph / Send to Simulation)
- `get_filter() -> tuple[str, str]` 메서드
- `set_db_loaded(bool)` 메서드 — DBC 로드 후 Send to Graph 활성화
- `restore_filter(str, str)` 메서드 — QSettings 복원

### 2-2. `app/main_window.py` — 3곳 수정 ✅

| 수정 위치 | 내용 |
|:---|:---|
| `_setup_ui()` | `sim_dock.sim_worker_created` → `_on_sim_worker_created` 연결 추가 |
| `_on_db_loaded()` | `trace_dock.set_db_loaded(True/False)` 호출 추가 |
| `__init__()` | `restore_filter()`, `set_rolling_sec()` 설정 복원 호출 추가 |
| `_on_sim_worker_created()` | 신규 슬롯 — `tx_echo → dispatcher.on_message QueuedConnection` 연결 |

### 2-3. `widgets/sim_dock.py` — SimWorker 생성 시 Signal emit 추가 ✅

- `sim_worker_created = Signal(object)` 선언
- `_start_message()` 내 SimWorker 신규 생성 시 `self.sim_worker_created.emit(sw)` 호출
- → MainWindow에서 `tx_echo → Dispatcher` 연결 수행 (Trace 파랑 컬러링 동작)

### 2-4. `tests/fixtures/sample.ldf` — 신규 생성 ✅

- LIN 2.1 형식, `MotorStatus(0x01)` / `MotorCmd(0x02)` / `SlaveStatus(0x03)` 3개 프레임
- LDF 관련 테스트 정상 동작

### 2-5. pytest 결과 ✅

```
78 passed in 4.77s   (0 failed, 0 error)
```

| 모듈 | 커버리지 |
|:---|:---:|
| `models/parsed_message.py` | 100% |
| `models/channel_stats.py` | 100% |
| `models/log_queue.py` | 100% |
| `core/async_db_loader.py` | 100% |
| `core/db_parser.py` | 88% |
| `models/numpy_signal_buffer.py` | 92% |
| `models/message_store.py` | 96% |
| UI 레이어 (`app/`, `widgets/`) | 0% (headless pytest에서 별도 테스트 필요) |
| **전체** | **22%** (UI 제외 core/models만 보면 ~85%) |

---

## 3. 마일스톤 진행 상태 (갱신)

| M# | 이름 | 상태 | 비고 |
|:---:|:---|:---:|:---|
| M1 | 아키텍처 POC + 핵심 데이터 모델 | ✅ **완료** | TraceDock Signal 버그 해결 |
| M2 | 로깅 (ASC) + Log Rotation | ✅ **완료** | 78/78 테스트 통과 |
| M3 | Trace Dock + 컬러링 + PyInstaller | ⚠️ **80%** | UI 완성, **PyInstaller 조기 빌드 미완** |
| M4 | Graph Dock | ✅ **완료** | GraphDock 완성. DBC 팝업 TODO만 남음 |
| M5 | Simulation (IG) | ✅ **완료** | tx_echo → Dispatcher 연결 완성 |
| M6 | 통합, 안정화, 최종 배포 | ❌ 미착수 | |
| M7 | Virtual Node Engine | ❌ 미착수 | Future scope |

---

## 4. 다음 작업 우선순위

### [우선 1] M3 — PyInstaller 조기 빌드 검증

명세서 M3 AC: *H/W 없는 PC에서 .exe 실행.*  
Vector DLL / lark hiddenimport 문제를 M6까지 미루면 최종 발견 위험.

```python
# build.spec 생성 필요 (명세서 Section 12 참조)
a = Analysis(
    ['src/main.py'],
    binaries=[('C:/Program Files/Vector XL Driver Library/bin/vxlapi64.dll', '.')],
    hiddenimports=['can.interfaces.vector', 'can.interfaces.virtual',
                   'lark', 'lark.grammars'],
    datas=[('venv/Lib/site-packages/cantools/database/can/formats/dbc.lark',
            'cantools/database/can/formats')],
)
```

### [우선 2] M6 — Bus Statistics Dock

명세서 8.1 레이아웃 기준 StatusBar에 채널별 통계 표시는 구현됨.  
별도 Bus Statistics Dock(QDockWidget)은 미구현 상태.

구현 내용:
- `widgets/bus_stats_dock.py` 신규 생성
- QTimer(1s) 슬롯 `_flush_stats()`에서 Dock 갱신
- 각 채널: Load%, Rx/s, Tx/s, Error count 테이블 표시

### [우선 3] M6 — pytest UI 레이어 커버리지 확장

현재 UI 레이어(app/, widgets/) 커버리지 0%.  
pytest-qt `qtbot`을 활용한 위젯 테스트 추가:

```python
# tests/test_trace_dock.py 예시
def test_filter_apply(qtbot, parsed_msg_factory):
    model = TraceModel()
    dock = TraceDock(model)
    qtbot.addWidget(dock)
    dock._le_filter_id.setText("1A0")
    dock._on_filter_apply()
    assert model._filter_id == 0x1A0
```

### [우선 4] M6 — QSettings restore_channels() 통합

현재 `MainWindow.__init__()`에서 `ConfigManager.restore_channels()`를 호출하지 않음.  
앱 재시작 시 이전 채널 설정 자동 복원 기능 미완성.

---

## 5. 아키텍처 핵심 규칙 (세션 간 인수인계)

```
[절대 불변 규칙]

1. ParsedMessage : frozen=True, slots=True — 필드 추가/변경 절대 금지
2. decode 위치   : CANWorker 내부만. Dispatcher/UI에서 decode 금지
3. UI 접근       : Main Thread 전용. Worker에서 UI 직접 접근 금지
4. Qt Signal     : 스레드 간 통신은 Signal(QueuedConnection)만 허용
5. SimWorker 복사: list(self._messages) 생성자만 — deepcopy/= 할당/.copy() 금지
6. AsyncDbLoader : 반드시 self._db_loader 바인딩 — 로컬 변수 즉시 GC → Segfault
7. terminate()   : 절대 금지 — H/W 포트 미해제 → BSoD/Segfault
8. Shutdown 순서 : QTimer → CANWorker.stop() → SimWorker.stop() → LogWorker.stop()
9. SignalBuffer  : enabled=False 기본 — DBC 로드 후 enable_all()로만 활성화
10. LogWorker    : while-else 구조 유지 — else 블록이 정상종료 flush 담당
11. tx_echo 연결 : SimWorker 생성 시 MainWindow._on_sim_worker_created()에서 연결
```

---

## 6. 파일 구조 (최종)

```
PyCANoe/
├── requirements.txt
├── requirements-dev.txt
├── src/
│   ├── main.py                       ✅
│   ├── app/
│   │   ├── main_window.py            ✅ (이번 세션 수정)
│   │   ├── config_manager.py         ✅
│   │   └── dialogs/
│   │       ├── channel_dialog.py     ✅
│   │       └── error_dialog.py       ✅
│   ├── core/
│   │   ├── can_worker.py             ✅
│   │   ├── channel_manager.py        ✅
│   │   ├── dispatcher.py             ✅
│   │   ├── sim_worker.py             ✅
│   │   ├── log_worker.py             ✅
│   │   ├── db_parser.py              ✅
│   │   └── async_db_loader.py        ✅
│   ├── models/
│   │   ├── parsed_message.py         ✅ P0 동결
│   │   ├── channel_stats.py          ✅
│   │   ├── message_store.py          ✅
│   │   ├── numpy_signal_buffer.py    ✅
│   │   ├── log_queue.py              ✅
│   │   ├── sim_state_store.py        ✅
│   │   └── trace_model.py            ✅
│   └── widgets/
│       ├── trace_dock.py             ✅ (이번 세션 완성)
│       ├── graph_dock.py             ✅
│       └── sim_dock.py               ✅ (이번 세션 수정)
└── tests/
    ├── conftest.py                   ✅
    ├── fixtures/
    │   ├── sample.dbc                ✅
    │   └── sample.ldf                ✅ (이번 세션 생성)
    └── test_*.py × 11               ✅ (78/78 통과)
```

---

## 7. 테스트 실행 방법

```bash
cd PyCANoe
pip install -r requirements.txt -r requirements-dev.txt

# 전체 테스트 (headless)
QT_QPA_PLATFORM=offscreen pytest tests/ -v

# 커버리지
QT_QPA_PLATFORM=offscreen pytest tests/ --cov=src --cov-report=term-missing
```

*이 파일은 세션 간 개발 현황 인수인계용. 작업 완료 항목은 상태를 갱신할 것.*
