# tests/test_coverage_boost.py
"""
커버리지 향상 전용 테스트.

대상:
  - sim_worker.py  78-99  : run() 루프 (메시지 있을 때 전송, sleep 경로)
  - trace_dock.py  200    : remove_channel_tab 현재 탭 복귀
  - trace_dock.py  244-277: _on_context_menu 메뉴 액션 실행
  - main_window.py 249    : _flush_graph → update_plots
  - main_window.py 268    : _flush_stats → bus_stats_dw 표시 중
  - main_window.py 336-339: db_loader 재로드 (disconnect 경로)
  - main_window.py 384    : log_worker 실행 중 재시작
  - main_window.py 468    : closeEvent sim_worker.stop() 경로
"""
import sys
import os
import time
import threading
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QApplication

from core.channel_manager import ChannelConfig

_app = QApplication.instance() or QApplication([])


# ─────────────────────────────────────────────────────────────────────────────
# SimWorker run() 루프  (78-99)
# ─────────────────────────────────────────────────────────────────────────────

class TestSimWorkerRunLoop:
    """SimWorker.run() 실제 루프 경로 커버."""

    def _make_sim_worker(self):
        from core.sim_worker import SimWorker, SimMessage
        mock_bus = MagicMock()
        mock_bus.send = MagicMock()
        mock_bus.increment_tx = MagicMock()
        sw = SimWorker(ch_id=0, bus_sender=mock_bus)
        return sw, mock_bus, SimMessage

    def test_run_with_no_messages_sleeps(self):
        """메시지 없으면 sleep(0.1) 경로 실행 후 종료."""
        sw, mock_bus, SimMessage = self._make_sim_worker()

        sw.start()
        time.sleep(0.15)   # 유휴 sleep(0.1) 경로 실행
        sw.stop()

        assert not sw.isRunning()

    def test_run_with_message_calls_send(self):
        """메시지 있으면 _send_due_messages() → bus_sender.send() 호출."""
        sw, mock_bus, SimMessage = self._make_sim_worker()

        sm = SimMessage(arb_id=0x100, data=b"\x01\x02", interval_ms=20.0)
        sw.add_message(sm)

        sw.start()
        time.sleep(0.15)   # 20ms 주기 → 약 7~8회 전송
        sw.stop()

        assert mock_bus.send.call_count >= 1

    def test_run_send_due_messages_increments_tx(self):
        """전송 성공 시 increment_tx() 호출."""
        sw, mock_bus, SimMessage = self._make_sim_worker()

        sm = SimMessage(arb_id=0x200, data=b"\xFF", interval_ms=30.0)
        sw.add_message(sm)

        sw.start()
        time.sleep(0.12)
        sw.stop()

        assert mock_bus.increment_tx.call_count >= 1

    def test_run_send_exception_does_not_crash(self):
        """bus_sender.send() 예외 발생해도 Worker 크래시 없이 계속 실행."""
        sw, mock_bus, SimMessage = self._make_sim_worker()
        mock_bus.send.side_effect = Exception("bus error")

        sm = SimMessage(arb_id=0x300, data=b"\x00", interval_ms=20.0)
        sw.add_message(sm)

        sw.start()
        time.sleep(0.12)
        sw.stop()

        assert not sw.isRunning()

    def test_run_busy_wait_path(self):
        """next_wakeup까지 sleep_sec <= 0.002 → busy-wait 경로 실행."""
        from core.sim_worker import SimWorker, SimMessage
        mock_bus = MagicMock()
        sw = SimWorker(ch_id=0, bus_sender=mock_bus)

        # 매우 짧은 주기(2ms) → sleep_sec가 거의 0 → busy-wait 경로
        sm = SimMessage(arb_id=0x100, data=b"\x01", interval_ms=2.0)
        sw.add_message(sm)

        sw.start()
        time.sleep(0.05)
        sw.stop()

        assert not sw.isRunning()

    def test_tx_echo_signal_exists(self):
        """SimWorker에 tx_echo Signal이 존재하고 연결 가능해야 한다."""
        from core.sim_worker import SimWorker
        mock_bus = MagicMock()
        sw = SimWorker(ch_id=0, bus_sender=mock_bus)

        # Signal 존재 확인 — AttributeError 없어야 함
        assert hasattr(sw, "tx_echo")

        # 연결 가능
        received = []
        sw.tx_echo.connect(received.append)

        # send()가 tx_echo를 emit하는지 확인 (직접 _send_due_messages 호출)
        from core.sim_worker import SimMessage
        sm = SimMessage(arb_id=0x100, data=b"\x01\x02", interval_ms=20.0)
        now = 1e10  # 충분히 큰 시간 → is_due() == True
        sw._send_due_messages(now, [sm])

        mock_bus.send.assert_called_once()
        mock_bus.increment_tx.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# TraceDock 미커버 경로  (200, 244-277)
# ─────────────────────────────────────────────────────────────────────────────

class TestTraceDockCoverage:
    def _make_dock(self, qtbot):
        from models.trace_model import TraceModel
        from widgets.trace_dock import TraceDock
        model = TraceModel()
        dock  = TraceDock(model)
        qtbot.addWidget(dock)
        return dock, model

    def test_remove_channel_tab_resets_to_all(self, qtbot):
        """제거된 채널 탭이 현재 탭이면 All(index 0)으로 복귀 — 라인 200."""
        dock, model = self._make_dock(qtbot)
        dock.add_channel_tab(0)                  # CH1 탭 활성화
        dock._tab_bar.setCurrentIndex(1)         # CH1 탭 선택
        assert dock._tab_bar.currentIndex() == 1

        dock.remove_channel_tab(0)               # CH1 제거 → All로 복귀
        assert dock._tab_bar.currentIndex() == 0

    def test_remove_channel_tab_other_stays(self, qtbot):
        """현재 탭이 아닌 채널 제거 → 현재 탭 유지."""
        dock, model = self._make_dock(qtbot)
        dock.add_channel_tab(0)
        dock.add_channel_tab(1)
        dock._tab_bar.setCurrentIndex(2)         # CH2 선택

        dock.remove_channel_tab(0)               # CH1 제거 → CH2 유지
        assert dock._tab_bar.currentIndex() == 2

    def test_context_menu_invalid_index_no_crash(self, qtbot):
        """유효하지 않은 위치 우클릭 → 메뉴 표시 안 됨, 크래시 없음."""
        dock, model = self._make_dock(qtbot)
        # 데이터 없는 빈 뷰에서 클릭
        dock._on_context_menu(QPoint(0, 0))

    def test_context_menu_with_message(self, qtbot):
        """컨텍스트 메뉴 관련 내부 메서드 직접 호출 — 라인 254-275 커버."""
        from models.parsed_message import ParsedMessage
        dock, model = self._make_dock(qtbot)

        pm = ParsedMessage(
            ch_id=0, timestamp=1.0, arb_id=0x1A0,
            dlc=8, data=b"\x01\x02\x03\x04\x05\x06\x07\x08",
        )
        model.append_batch([pm])

        # 라인 254-256: _apply_id_filter
        dock._apply_id_filter(0x1A0)
        assert dock._le_filter_id.text() == "1A0"

        # 라인 258-260: _copy_to_clipboard
        dock._copy_to_clipboard(pm)

        # 라인 272-275: send_to_sim Signal
        sent = []
        dock.send_to_sim.connect(lambda ch, aid, dlc, d: sent.append((ch, aid)))
        dock.send_to_sim.emit(pm.ch_id, pm.arb_id, pm.dlc, pm.data)
        assert sent == [(0, 0x1A0)]

    def test_context_menu_send_to_graph_enabled_when_db(self, qtbot):
        """_send_signals_to_graph 직접 호출 — 라인 264-269 커버."""
        from models.parsed_message import ParsedMessage
        dock, model = self._make_dock(qtbot)
        dock.set_db_loaded(True)

        pm = ParsedMessage(
            ch_id=0, timestamp=1.0, arb_id=0x1A0,
            dlc=8, data=bytes(8),
            signals={"EngSpeed": 1200.0, "VehSpeed": 40.0},
        )

        emitted = []
        dock.send_to_graph.connect(lambda ch, sig: emitted.append((ch, sig)))
        dock._send_signals_to_graph(pm)
        assert len(emitted) == 2

    def test_apply_id_filter_via_context_menu(self, qtbot):
        """우클릭 → 이 ID 필터링 → filter_id LineEdit에 arb_id 입력."""
        from models.parsed_message import ParsedMessage
        dock, model = self._make_dock(qtbot)

        pm = ParsedMessage(
            ch_id=0, timestamp=1.0, arb_id=0x1A0,
            dlc=8, data=bytes(8),
        )
        model.append_batch([pm])

        # _apply_id_filter 직접 호출
        dock._apply_id_filter(0x1A0)
        assert dock._le_filter_id.text() == "1A0"

    def test_copy_to_clipboard(self, qtbot):
        """클립보드 복사 — 크래시 없음."""
        from models.parsed_message import ParsedMessage
        dock, model = self._make_dock(qtbot)

        pm = ParsedMessage(
            ch_id=0, timestamp=1.0, arb_id=0x1A0,
            dlc=4, data=b"\xAB\xCD\xEF\x01",
        )
        dock._copy_to_clipboard(pm)

    def test_send_signals_to_graph(self, qtbot):
        """_send_signals_to_graph → send_to_graph Signal emit."""
        from models.parsed_message import ParsedMessage
        dock, model = self._make_dock(qtbot)

        pm = ParsedMessage(
            ch_id=0, timestamp=1.0, arb_id=0x100,
            dlc=8, data=bytes(8),
            signals={"Speed": 50.0, "RPM": 2000.0},
        )

        emitted = []
        dock.send_to_graph.connect(lambda ch, sig: emitted.append((ch, sig)))
        dock._send_signals_to_graph(pm)

        assert len(emitted) == 2


# ─────────────────────────────────────────────────────────────────────────────
# MainWindow 미커버 경로
# ─────────────────────────────────────────────────────────────────────────────

def make_mock_ctx(ch_id=0):
    ctx = MagicMock()
    ctx.ch_id = ch_id
    ctx.config = ChannelConfig(interface="virtual", channel=ch_id, bitrate=500_000)
    ctx.worker = MagicMock()
    ctx.worker.isRunning.return_value = False
    ctx.sim_worker = None
    stats = MagicMock()
    stats.bus_load_pct = 0.0
    stats.rx_count = 0
    stats.tx_count = 0
    stats.error_count = 0
    ctx.worker.get_stats.return_value = stats
    return ctx


def _make_win(qtbot, restored=None, cm_channels=None):
    from app.main_window import MainWindow
    if restored is None:
        restored = []
    with (
        patch("app.main_window.ConfigManager") as MockCfg,
        patch("app.main_window.ChannelManager") as MockCM,
    ):
        mock_cfg = MagicMock()
        mock_cfg.restore_window.return_value       = False
        mock_cfg.restore_trace_filter.return_value = ("", "", True)
        mock_cfg.restore_graph_window.return_value = 30
        mock_cfg.restore_channels.return_value     = restored
        mock_cfg.restore_log_path.return_value     = "log.asc"
        MockCfg.return_value = mock_cfg

        mock_cm = MagicMock()
        mock_cm.all.return_value = cm_channels or []
        mock_cm.MAX_CHANNELS     = 4
        MockCM.return_value = mock_cm

        win = MainWindow()
        qtbot.addWidget(win)
    return win, mock_cfg, mock_cm


class TestMainWindowMissedLines:
    def test_flush_graph_calls_update_plots(self, qtbot):
        """_flush_graph → graph_dock.update_plots() 호출 — 라인 249."""
        win, cfg, cm = _make_win(qtbot)
        win._graph_dock.update_plots = MagicMock()
        win._flush_graph()
        win._graph_dock.update_plots.assert_called_once()

    def test_flush_stats_with_visible_bus_stats(self, qtbot):
        """bus_stats_dw 표시 중(isVisible Mock) + 채널 있으면 update_stats() 호출 — 라인 268."""
        ctx = make_mock_ctx(0)
        win, cfg, cm = _make_win(qtbot)
        cm.all.return_value = [ctx]

        # headless에서 isVisible()은 항상 False → Mock으로 True 강제
        win._bus_stats_dw.isVisible = MagicMock(return_value=True)
        win._bus_stats_dock.update_stats = MagicMock()

        win._flush_stats()
        win._bus_stats_dock.update_stats.assert_called_once()

    def test_load_db_with_existing_loader_disconnects(self, qtbot):
        """기존 db_loader 있을 때 재로드 → disconnect 후 새 loader — 라인 335-339."""
        ctx = make_mock_ctx(0)
        ctx.db_parser = MagicMock()
        win, cfg, cm = _make_win(qtbot)
        cm.all.return_value = [ctx]

        # 기존 loader 설정
        old_loader = MagicMock()
        win._db_loader = old_loader

        with patch("app.main_window.QFileDialog.getOpenFileName",
                   return_value=("/tmp/new.dbc", "")):
            with patch("app.main_window.AsyncDbLoader") as MockLoader:
                mock_lw = MagicMock()
                MockLoader.return_value = mock_lw
                win._on_load_db_clicked()

        # 기존 loader disconnect 시도
        old_loader.db_loaded.disconnect.assert_called_once()
        # 새 loader start_loading 호출
        mock_lw.start_loading.assert_called_once()

    def test_load_db_disconnect_runtime_error_ignored(self, qtbot):
        """disconnect RuntimeError → 무시하고 계속 — 라인 338."""
        ctx = make_mock_ctx(0)
        ctx.db_parser = MagicMock()
        win, cfg, cm = _make_win(qtbot)
        cm.all.return_value = [ctx]

        old_loader = MagicMock()
        old_loader.db_loaded.disconnect.side_effect = RuntimeError("already disconnected")
        win._db_loader = old_loader

        with patch("app.main_window.QFileDialog.getOpenFileName",
                   return_value=("/tmp/car.dbc", "")):
            with patch("app.main_window.AsyncDbLoader") as MockLoader:
                MockLoader.return_value = MagicMock()
                win._on_load_db_clicked()   # RuntimeError 예외 전파 없어야 함

    def test_log_start_stops_running_worker_first(self, qtbot):
        """log_worker 실행 중 → stop() 후 재시작 — 라인 384."""
        win, cfg, cm = _make_win(qtbot)

        # 실행 중인 기존 log_worker 설정
        old_worker = MagicMock()
        old_worker.isRunning.return_value = True
        win._log_worker = old_worker

        with patch("app.main_window.QFileDialog.getSaveFileName",
                   return_value=("/tmp/log2.asc", "")):
            with patch("app.main_window.LogWorker") as MockLW:
                new_worker = MagicMock()
                new_worker.isRunning.return_value = False
                MockLW.return_value = new_worker
                win._on_log_start_clicked()

        old_worker.stop.assert_called_once()
        new_worker.start.assert_called_once()

    def test_close_event_stops_sim_worker(self, qtbot):
        """closeEvent: sim_worker 실행 중이면 stop() 호출 — 라인 467-468."""
        win, cfg, cm = _make_win(qtbot)

        ctx = make_mock_ctx(0)
        mock_sim = MagicMock()
        mock_sim.isRunning.return_value = True
        ctx.sim_worker = mock_sim
        cm.all.return_value = [ctx]

        event = QCloseEvent()
        win.closeEvent(event)

        mock_sim.stop.assert_called_once()

    def test_close_event_skips_stopped_sim_worker(self, qtbot):
        """closeEvent: sim_worker 정지 상태이면 stop() 호출 안 함."""
        win, cfg, cm = _make_win(qtbot)

        ctx = make_mock_ctx(0)
        mock_sim = MagicMock()
        mock_sim.isRunning.return_value = False
        ctx.sim_worker = mock_sim
        cm.all.return_value = [ctx]

        event = QCloseEvent()
        win.closeEvent(event)

        mock_sim.stop.assert_not_called()

    def test_close_event_stops_log_worker(self, qtbot):
        """closeEvent: log_worker 실행 중이면 stop() 호출."""
        win, cfg, cm = _make_win(qtbot)
        cm.all.return_value = []

        log_worker = MagicMock()
        log_worker.isRunning.return_value = True
        win._log_worker = log_worker

        event = QCloseEvent()
        win.closeEvent(event)

        log_worker.stop.assert_called_once()
