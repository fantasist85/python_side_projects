# PyCANoe 개발 현황 기록

> **기준 브랜치:** `PyCANoe`
> **명세서 버전:** Rev 9.0
> **기록 갱신일:** 2026-04-10 (12차 세션 — Phase 0 git 정리 & 문서 최신화)
> **현재 상태:** M1~M7 전체 완료. 테스트 630개 / 커버리지 95%

---

## 1. 마일스톤 진행 상태

| M# | 이름 | 상태 | 비고 |
|:---:|:---|:---:|:---|
| M1 | 아키텍처 POC + 핵심 데이터 모델 | ✅ **완료** | ParsedMessage P0 동결 포함 |
| M2 | 로깅 (ASC) + Log Rotation + Windows 타이머 | ✅ **완료** | while-else, 100MB Rotation, timeBeginPeriod(1) |
| M3 | Trace Dock + 컬러링 + PyInstaller 조기 검증 | ✅ **완료** | build.spec 완성, 바이너리 기동 확인 |
| M4 | Graph Dock | ✅ **완료** | 신호 추가 팝업 구현 완료 (7차) |
| M5 | Simulation (IG) | ✅ **완료** | tx_echo, _messages_lock, drift 보정 |
| M6 | 통합, 안정화, 최종 배포 | ✅ **완료** | 373/373 통과, 커버리지 82% |
| M7 | Virtual Node Engine | ✅ **완료** | 630/630 통과, 커버리지 95% (11차) |
| **M8** | **LIN H/W 버스 지원** | 🔲 **계획** | **python-can LinBus + ChannelDialog LIN 탭** |

---

## 2. 이번 세션(12차) 작업 내역 — Phase 0 git 정리

### 2-1. 작업 내용

| 항목 | 내용 |
|:---|:---|
| 테스트 검증 | 630/630 패스 확인 (커버리지 95% 유지) |
| 문서 최신화 | PyCANoe_DevStatus.md Rev 12차 갱신 |
| 문서 최신화 | PyCANoe.md M8 마일스톤 스코프 추가 |
| git 커밋 | M1~M7 전체 코드 커밋 & 푸시 완료 |

### 2-2. 환경 메모

- **테스트 실행 환경:** Ubuntu Linux, PySide6 시스템 패키지, `libegl1` 필요
- **pytest 실행:** `QT_QPA_PLATFORM=offscreen PYTHONPATH=src /usr/local/bin/python -m pytest tests/ -q`
- **uv 환경 주의:** `/root/.local/bin/pytest` 는 PySide6 없음 → 시스템 Python 사용

---

## 3. 다음 작업 우선순위 — M8 LIN H/W 지원

### [우선 1] CANWorker LIN 모드 추가

```python
# src/core/can_worker.py
# build_bus_kwargs()에 LIN 분기 추가
# python-can LinBus 인터페이스 연동
```

구현 체크리스트:
- [ ] `ChannelConfig`에 `bus_type: Literal["can", "lin"] = "can"` 필드 추가
- [ ] `build_bus_kwargs()`에 LIN 인터페이스 분기 (`lin` 타입 처리)
- [ ] `CANWorker`에서 LIN 메시지 수신 시 `arb_id & 0x3F` 처리 확인

### [우선 2] ChannelDialog LIN 탭

```
ChannelDialog
├── 탭: CAN (기존)
└── 탭: LIN (신규)
    ├── 인터페이스 선택 (Vector LIN / PLIN)
    ├── Baud rate 선택 (9600 / 19200 / 38400)
    └── LDF 파일 경로 입력
```

### [우선 3] 단위 테스트

- [ ] `tests/test_lin_worker.py` — LinBus mock, 수신 루프
- [ ] `tests/test_channel_dialog_lin.py` — LIN 탭 UI
- 목표: 테스트 680개+, 커버리지 95% 유지

### [우선 4] PyInstaller 최종 빌드 (Windows 환경 필요)

```bash
python -m PyInstaller build.spec --distpath dist --workpath build --noconfirm
```

검증 체크리스트:
- [ ] Python 없는 PC에서 `dist/PyCANoe.exe` 실행 확인
- [ ] View > Virtual Node Dock → `examples/virtual_node_heartbeat.py` 로드 → Trace 확인
- [ ] 스크립트 예외 시 로그 콘솔에 에러 출력 확인 (노드 계속 동작)
- [ ] [전체 정지] + 앱 종료 → 스레드 정상 종료 확인 (hang 없음)

---

## 4. 알려진 TODO / 미구현 사항

| 항목 | 우선도 |
|:---|:---:|
| LIN H/W 버스 지원 (M8) — CANWorker LinBus + ChannelDialog LIN 탭 | 🔴 높음 |
| PyInstaller 최종 빌드 (Windows 검증) | 🔴 높음 |
| VirtualNodeWorker on_message arb_id 필터링 | ⚪ 낮음 (M8 묶음) |
| Virtual Node 스크립트 핫리로드 | ⚪ 낮음 (M8 묶음) |

---

## 5. 아키텍처 핵심 규칙 (세션 간 인수인계 — 절대 불변)

```
[STRICT RULES — AI 코드 작성 시 반드시 준수]

 1. ParsedMessage : frozen=True, slots=True — 필드 추가/변경 절대 금지 (P0 동결)
 2. decode 위치   : CANWorker._process_message() 내부만. Dispatcher/UI decode 금지
 3. UI 접근       : Main Thread 전용. Worker에서 UI 위젯 직접 접근 금지
 4. Qt Signal     : 스레드 간 통신은 Signal(QueuedConnection)만 허용
 5. SimWorker 복사: list(self._messages) 생성자만 사용
 6. AsyncDbLoader : 반드시 self._db_loader 바인딩 필수
 7. terminate()   : 절대 금지 — H/W 포트 미해제 → BSoD/Segfault
 8. Shutdown 순서 : QTimer → CANWorker.stop() → SimWorker.stop() → VNE.unload_all() → LogWorker.stop()
 9. SignalBuffer  : enabled=False 기본 — DBC 로드 후 enable_all()로만 활성화
10. LogWorker     : while-else 구조 유지 — else 블록이 정상종료 flush 담당
11. tx_echo 연결  : sim_worker_created → MainWindow._on_sim_worker_created()에서 연결
12. parser_lock   : clear_cache()는 lock 밖에서 호출 (데드락 위험)
13. Signal import : widgets/에서 Signal은 파일 최상위에서만 import (PyInstaller 필수)
14. save_channels : settings_version도 함께 저장 필수
15. append_batch  : 배치 len > MAX_ROWS 시 batch[-MAX_ROWS:]로 먼저 잘라낸 후 삽입
16. LogWorker fmt : 확장자 기반 자동 감지 — main_window에서 fmt 하드코딩 금지
17. CSV 포맷      : ch_id는 1-based, arb_id 대문자HEX, data 연속소문자HEX, is_tx 0/1
18. LogWorker 파일명: _make_path(index) → <stem>_001<ext> 패턴 (원본경로 직접 open 금지)
19. closeEvent 테스트: MagicMock() 대신 QCloseEvent() 사용 (PySide6 타입 검사)
20. SimDock 콤보박스: _detail._cb_ch (SimMessageDetail 내부, SimDock에서 직접 접근 금지)
21. TraceDock 채널 탭: add_channel_tab() 반드시 호출 (add_channel + restore_channels 양쪽)
22. _ch_filter   : TraceModel.set_ch_filter(None) = clear_ch_filter() (All 탭과 동일)
23. pyqtgraph headless: GraphDock show() → Segfault. GraphDock 버튼 테스트는 Windows 전용
24. isVisible() headless: setVisible() 후에도 False 반환. isHidden() 사용 권장
25. build_bus_kwargs: CANWorker 외부 순수 함수 — H/W 없이 단독 단위 테스트 가능
26. ChannelConfig 신규 필드: socketcan_ifname(str), pcan_channel(str) — 기본값 있음
27. SocketCAN bitrate: 커널 관리 — python-can에 bitrate 전달 금지 (build_bus_kwargs 참조)
28. FD 미지원 인터페이스: virtual/socketcan/pcan — build_bus_kwargs에서 fd 키 제외
29. QThread.run() 커버리지: QThread 내부 실행은 coverage 추적 불가 → run()을 메인 스레드에서 직접 호출
30. QMenu.exec() 블로킹: headless에서 menu.exec() 절대 호출 금지 → 내부 메서드 직접 테스트
31. isVisible() Mock: headless에서 show() 후 isVisible()=False → MagicMock(return_value=True)로 강제
32. VNE is_tx 차단: on_all_messages()에서 msg.is_tx=True 메시지 전달 금지 (Tx 에코 무한 루프 방지)
33. VNE BusProxy  : bus.send()는 Signal emit → Main Thread에서 CANWorker.send() 호출. Worker에서 직접 호출 금지
34. VNE 스크립트  : importlib.util.spec_from_file_location 동적 로드. hiddenimport 불필요
35. VNE shutdown  : closeEvent에서 반드시 vne.unload_all() 호출 (CANWorker.stop() 이후, LogWorker.stop() 이전)
36. VNE 예외 격리 : on_message/on_timer 예외 → node_error Signal emit, 노드 중단 없음
37. LIN bus_type  : ChannelConfig.bus_type = "lin" 시 build_bus_kwargs() LIN 분기 실행 (M8 추가 예정)
38. pytest 환경   : uv 환경 pytest 사용 금지 → /usr/local/bin/python -m pytest 사용 (Linux CI)
```

---

## 6. 파일 구조

```
PyCANoe/
├── .coveragerc
├── build.spec                              ✅ PyInstaller
├── requirements.txt
├── requirements-dev.txt
├── examples/                               ✅ M7 신규
│   ├── virtual_node_heartbeat.py           ✅ 예제: 100ms Heartbeat 전송
│   └── virtual_node_responder.py           ✅ 예제: DBC 신호 조건부 응답
├── tests/  (630/630 통과, 95% 커버리지)
│   ├── ... (기존 580개)
│   └── test_virtual_node_engine.py         ✅ (50) ← 11차 신규
└── src/
    ├── main.py
    ├── app/
    │   ├── main_window.py                  ✅ (100%) — M7 VNE 통합
    │   ├── config_manager.py               ✅
    │   └── dialogs/
    │       ├── channel_dialog.py           ✅
    │       └── error_dialog.py             ✅
    ├── core/
    │   ├── can_worker.py                   ✅ (100%)
    │   ├── channel_manager.py              ✅
    │   ├── log_worker.py                   ✅
    │   ├── sim_worker.py                   ✅ (100%)
    │   ├── db_parser.py                    ✅
    │   ├── async_db_loader.py              ✅
    │   └── virtual_node_engine.py          ✅ (99%) ← M7 신규
    ├── models/
    │   ├── parsed_message.py               ✅
    │   ├── channel_stats.py                ✅
    │   ├── message_store.py                ✅
    │   ├── numpy_signal_buffer.py          ✅
    │   ├── log_queue.py                    ✅
    │   ├── sim_state_store.py              ✅
    │   └── trace_model.py                  ✅
    └── widgets/
        ├── trace_dock.py                   ✅
        ├── graph_dock.py                   ✅
        ├── sim_dock.py                     ✅
        ├── bus_stats_dock.py               ✅
        └── virtual_node_dock.py            ✅ (95%) ← M7 신규
```

---

## 7. 테스트 실행 방법

```bash
cd PyCANoe

# 전체 테스트 (Linux — 시스템 Python 사용)
QT_QPA_PLATFORM=offscreen PYTHONPATH=src /usr/local/bin/python -m pytest tests/ -v

# 커버리지
QT_QPA_PLATFORM=offscreen PYTHONPATH=src /usr/local/bin/python -m pytest tests/ --cov=src --cov-report=term-missing

# M7만
QT_QPA_PLATFORM=offscreen PYTHONPATH=src /usr/local/bin/python -m pytest tests/test_virtual_node_engine.py -v

# 앱 직접 실행
python src/main.py
```

---

## 8. 세션별 변경 요약

| 세션 | 주요 작업 | 테스트 수 | 커버리지 |
|:---:|:---|:---:|:---:|
| 1차~5차 | M1~M6 구현 | - | - |
| 6차 | BLF/CSV, QSettings | 245 | 74% |
| 7차 | Trace 채널 탭 + Graph 팝업 | 281 | 75% |
| 8차 | 커버리지 향상 | 373 | 82% |
| 9차 | 다중 인터페이스 지원 | 443 | 84% |
| 10차 | 커버리지 84%→95%, 테스트 137개 추가 | 580 | 95% |
| 11차 | M7 Virtual Node Engine 완료 | 630 | 95% |
| **12차** | **Phase 0: git 정리 & 문서 최신화, M8 계획 수립** | **630** | **95%** |
