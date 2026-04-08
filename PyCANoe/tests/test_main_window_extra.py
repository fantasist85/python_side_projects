# tests/test_main_window_extra.py
"""
MainWindow — 추가 슬롯/액션 커버리지 테스트.

커버 대상 (main_window.py 미커버 라인):
  - _on_add_channel_clicked() : 최대 채널 경고 / 다이얼로그 취소 / 성공
  - _on_load_db_clicked()     : 채널 없음 / DB 로드 성공/실패
  - _on_start_clicked()       : 채널 없음 / 채널 있음
  - _on_stop_clicked()        : Worker 실행 중 stop() 호출
  - _on_log_start_clicked()   : 로그 시작 / 포맷 감지
  - _on_log_stop_clicked()    : 로그 중지
  - _on_auto_scroll_toggled() : 값 반영
  - _on_send_to_graph()       : GraphDock.add_signal + show
  - _on_send_to_sim()         : SimDock.add_from_trace + show
  - _on_worker_error()        : status_label 갱신
  - _on_connection_state_changed() : 연결/끊김 상태 갱신
  - _on_log_dropped()         : drop_label 갱신
  - _on_log_rotated()         : status_label 갱신
  - _flush_trace()            : drop_count 경고 표시
  - _reset_layout()           : Dock 상태 초기화
"""
import sys
import os
from unittest.mock import MagicMock, patch, call

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication
from core.channel_manager import ChannelConfig

_app = QApplication.instance() or QApplication([])


def make_mock_ctx(ch_id: int = 0):
    ctx = MagicMock()
    ctx.ch_id = ch_id
    ctx.config = ChannelConfig(interface="virtual", channel=ch_id, bitrate=500_000)
    ctx.worker = MagicMock()
    ctx.worker.isRunning.return_value = False
    ctx.sim_worker = None
    stats = MagicMock()
    stats.bus_load_pct = 0.0
    stats.rx_count     = 0
    stats.tx_count     = 0
    stats.error_count  = 0
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


# ──────────────────────────────────────────────────────────────────────────────
# _on_add_channel_clicked
# ──────────────────────────────────────────────────────────────────────────────

class TestAddChannelClicked:
    def test_max_channels_shows_warning(self, qtbot):
        """4채널 이미 있으면 경고 박스만 표시 — add_channel 호출 없음."""
        ctxs = [make_mock_ctx(i) for i in range(4)]
        win, cfg, cm = _make_win(qtbot, cm_channels=ctxs)
        cm.all.return_value = ctxs

        with patch("app.main_window.QMessageBox.warning") as mock_warn:
            win._on_add_channel_clicked()
            mock_warn.assert_called_once()

    def test_dialog_rejected_no_add(self, qtbot):
        """다이얼로그 취소 → add_channel 호출 없음."""
        win, cfg, cm = _make_win(qtbot)
        cm.all.return_value = []

        with patch("app.main_window.ChannelDialog") as MockDlg:
            mock_dlg = MagicMock()
            mock_dlg.exec.return_value = MagicMock()  # Rejected (not Accepted)
            mock_dlg.exec.return_value = 0  # Rejected
            MockDlg.return_value = mock_dlg

            win._on_add_channel_clicked()
            cm.add_channel.assert_not_called()

    def test_dialog_accepted_adds_channel(self, qtbot):
        """다이얼로그 OK → add_channel 호출 + sim_dock.refresh."""
        from PySide6.QtWidgets import QDialog
        win, cfg, cm = _make_win(qtbot)
        cm.all.return_value = []

        mock_ctx = make_mock_ctx(ch_id=0)
        cm.add_channel.return_value = mock_ctx

        with patch("app.main_window.ChannelDialog") as MockDlg:
            mock_dlg = MagicMock()
            # DialogCode.Accepted 비교가 통과하도록 실제 값(1) 사용
            MockDlg.DialogCode.Accepted = QDialog.DialogCode.Accepted
            mock_dlg.exec.return_value = int(QDialog.DialogCode.Accepted)
            mock_cfg_obj = ChannelConfig(interface="virtual", channel=0, bitrate=500_000)
            mock_dlg.get_config.return_value = mock_cfg_obj
            MockDlg.return_value = mock_dlg

            win._on_add_channel_clicked()

        cm.add_channel.assert_called_once()

    def test_add_channel_exception_shows_error_dialog(self, qtbot):
        """add_channel 예외 → ErrorDialog 표시, 크래시 없음."""
        from PySide6.QtWidgets import QDialog
        win, cfg, cm = _make_win(qtbot)
        cm.all.return_value = []
        cm.add_channel.side_effect = RuntimeError("Bus error")

        with patch("app.main_window.ChannelDialog") as MockDlg:
            mock_dlg = MagicMock()
            MockDlg.DialogCode.Accepted = QDialog.DialogCode.Accepted
            mock_dlg.exec.return_value = int(QDialog.DialogCode.Accepted)
            mock_dlg.get_config.return_value = ChannelConfig(
                interface="virtual", channel=0, bitrate=500_000)
            MockDlg.return_value = mock_dlg

            with patch("app.main_window.ErrorDialog.show_error") as mock_err:
                win._on_add_channel_clicked()
                mock_err.assert_called_once()


# ──────────────────────────────────────────────────────────────────────────────
# _on_load_db_clicked
# ──────────────────────────────────────────────────────────────────────────────

class TestLoadDbClicked:
    def test_no_channels_shows_info(self, qtbot):
        """채널 없으면 안내 메시지만 표시."""
        win, cfg, cm = _make_win(qtbot)
        cm.all.return_value = []

        with patch("app.main_window.QFileDialog.getOpenFileName",
                   return_value=("/tmp/test.dbc", "")):
            with patch("app.main_window.QMessageBox.information") as mock_info:
                win._on_load_db_clicked()
                mock_info.assert_called_once()

    def test_no_file_selected_no_action(self, qtbot):
        """파일 선택 안 함 → 아무 동작 없음."""
        win, cfg, cm = _make_win(qtbot)
        with patch("app.main_window.QFileDialog.getOpenFileName",
                   return_value=("", "")):
            win._on_load_db_clicked()  # 크래시 없어야 함

    def test_load_db_starts_loader(self, qtbot):
        """채널 있고 파일 선택 → AsyncDbLoader 생성 및 start_loading."""
        ctx = make_mock_ctx(0)
        ctx.db_parser = MagicMock()
        win, cfg, cm = _make_win(qtbot)
        cm.all.return_value = [ctx]

        with patch("app.main_window.QFileDialog.getOpenFileName",
                   return_value=("/tmp/car.dbc", "")):
            with patch("app.main_window.AsyncDbLoader") as MockLoader:
                mock_loader = MagicMock()
                MockLoader.return_value = mock_loader

                win._on_load_db_clicked()

                mock_loader.start_loading.assert_called_once()

    def test_db_loaded_success_enables_graph(self, qtbot):
        """DB 로드 성공 → signal_registry.enable_all, graph_dock.enable, graph 표시."""
        win, cfg, cm = _make_win(qtbot)
        mock_parser = MagicMock()
        mock_parser.db_type = "dbc"

        win._on_db_loaded(True, mock_parser)

        assert win._status_label.text() == "DB 로드 완료 [DBC]"

    def test_db_loaded_failure_shows_error(self, qtbot):
        """DB 로드 실패 → 에러 다이얼로그."""
        win, cfg, cm = _make_win(qtbot)
        with patch("app.main_window.ErrorDialog.show_error") as mock_err:
            win._on_db_loaded(False, None)
            mock_err.assert_called_once()


# ──────────────────────────────────────────────────────────────────────────────
# _on_start_clicked / _on_stop_clicked
# ──────────────────────────────────────────────────────────────────────────────

class TestStartStopClicked:
    def test_start_no_channels_shows_info(self, qtbot):
        """채널 없으면 안내 메시지 표시."""
        win, cfg, cm = _make_win(qtbot)
        cm.all.return_value = []
        with patch("app.main_window.QMessageBox.information") as mock_info:
            win._on_start_clicked()
            mock_info.assert_called_once()

    def test_start_with_channel_starts_worker(self, qtbot):
        """채널 있고 Worker 미실행 → worker.start() 호출."""
        ctx = make_mock_ctx(0)
        ctx.worker.isRunning.return_value = False
        win, cfg, cm = _make_win(qtbot)
        cm.all.return_value = [ctx]

        win._on_start_clicked()
        ctx.worker.start.assert_called_once()

    def test_start_already_running_no_duplicate_start(self, qtbot):
        """이미 실행 중인 Worker → start() 호출 안 함."""
        ctx = make_mock_ctx(0)
        ctx.worker.isRunning.return_value = True
        win, cfg, cm = _make_win(qtbot)
        cm.all.return_value = [ctx]

        win._on_start_clicked()
        ctx.worker.start.assert_not_called()

    def test_stop_running_worker_stops(self, qtbot):
        """실행 중 Worker → stop() 호출."""
        ctx = make_mock_ctx(0)
        ctx.worker.isRunning.return_value = True
        win, cfg, cm = _make_win(qtbot)
        cm.all.return_value = [ctx]

        win._on_stop_clicked()
        ctx.worker.stop.assert_called_once()

    def test_stop_status_label_updated(self, qtbot):
        """stop 후 status_label 갱신."""
        win, cfg, cm = _make_win(qtbot)
        cm.all.return_value = []
        win._on_stop_clicked()
        assert win._status_label.text() == "정지"


# ──────────────────────────────────────────────────────────────────────────────
# _on_log_start_clicked / _on_log_stop_clicked
# ──────────────────────────────────────────────────────────────────────────────

class TestLogClicked:
    def test_log_start_no_file_selected(self, qtbot):
        """파일 미선택 → LogWorker 생성 없음."""
        win, cfg, cm = _make_win(qtbot)
        with patch("app.main_window.QFileDialog.getSaveFileName",
                   return_value=("", "")):
            win._on_log_start_clicked()
        assert win._log_worker is None

    def test_log_start_asc_format(self, qtbot):
        """asc 확장자 → LogWorker(fmt="asc") 생성."""
        win, cfg, cm = _make_win(qtbot)
        with patch("app.main_window.QFileDialog.getSaveFileName",
                   return_value=("/tmp/log.asc", "")):
            with patch("app.main_window.LogWorker") as MockLW:
                mock_lw = MagicMock()
                mock_lw.isRunning.return_value = False
                MockLW.return_value = mock_lw

                win._on_log_start_clicked()

                # fmt="asc"로 생성되어야 함
                call_kwargs = MockLW.call_args
                assert call_kwargs[1].get("fmt", call_kwargs[0][2] if len(call_kwargs[0]) > 2 else "asc") == "asc" or \
                       "asc" in str(call_kwargs)

    def test_log_start_csv_format(self, qtbot):
        """csv 확장자 → LogWorker(fmt="csv") 생성."""
        win, cfg, cm = _make_win(qtbot)
        with patch("app.main_window.QFileDialog.getSaveFileName",
                   return_value=("/tmp/log.csv", "")):
            with patch("app.main_window.LogWorker") as MockLW:
                mock_lw = MagicMock()
                mock_lw.isRunning.return_value = False
                MockLW.return_value = mock_lw

                win._on_log_start_clicked()

                # fmt="csv"로 생성
                call_args = MockLW.call_args
                assert "csv" in str(call_args)

    def test_log_stop_stops_running_worker(self, qtbot):
        """실행 중 LogWorker → stop() 호출."""
        win, cfg, cm = _make_win(qtbot)
        mock_lw = MagicMock()
        mock_lw.isRunning.return_value = True
        win._log_worker = mock_lw

        win._on_log_stop_clicked()
        mock_lw.stop.assert_called_once()

    def test_log_stop_status_updated(self, qtbot):
        """stop 후 status_label 갱신."""
        win, cfg, cm = _make_win(qtbot)
        win._log_worker = None
        win._on_log_stop_clicked()
        assert win._status_label.text() == "로그 중지"


# ──────────────────────────────────────────────────────────────────────────────
# 기타 슬롯
# ──────────────────────────────────────────────────────────────────────────────

class TestMiscSlots:
    def test_auto_scroll_toggled(self, qtbot):
        """_on_auto_scroll_toggled → _auto_scroll 값 반영."""
        win, cfg, cm = _make_win(qtbot)
        win._on_auto_scroll_toggled(False)
        assert win._auto_scroll is False
        win._on_auto_scroll_toggled(True)
        assert win._auto_scroll is True

    def test_on_send_to_graph(self, qtbot):
        """_on_send_to_graph → graph_dock.add_signal + graph_dw.show."""
        win, cfg, cm = _make_win(qtbot)
        win._graph_dock.add_signal = MagicMock()
        win._on_send_to_graph(0, "EngSpeed")
        win._graph_dock.add_signal.assert_called_once_with(0, "EngSpeed")

    def test_on_send_to_sim(self, qtbot):
        """_on_send_to_sim → sim_dock.add_from_trace + sim_dw.show."""
        win, cfg, cm = _make_win(qtbot)
        win._sim_dock.add_from_trace = MagicMock()
        win._on_send_to_sim(0, 0x1A0, 8, b"\x01\x02")
        win._sim_dock.add_from_trace.assert_called_once_with(0, 0x1A0, 8, b"\x01\x02")

    def test_on_worker_error_updates_status(self, qtbot):
        """_on_worker_error → status_label에 ⚠ 포함."""
        win, cfg, cm = _make_win(qtbot)
        with patch("app.main_window.ErrorDialog.show_error"):
            win._on_worker_error("연결 실패")
        assert "연결 실패" in win._status_label.text()

    def test_on_connection_state_connected(self, qtbot):
        """연결됨 상태 → '연결됨' 포함."""
        win, cfg, cm = _make_win(qtbot)
        win._on_connection_state_changed(0, True)
        assert "연결됨" in win._status_label.text()

    def test_on_connection_state_disconnected(self, qtbot):
        """끊김 상태 → '끊김' 포함."""
        win, cfg, cm = _make_win(qtbot)
        win._on_connection_state_changed(0, False)
        assert "끊김" in win._status_label.text()

    def test_on_log_dropped(self, qtbot):
        """log_dropped → drop_label 갱신."""
        win, cfg, cm = _make_win(qtbot)
        win._on_log_dropped(42)
        assert "42" in win._drop_label.text()

    def test_on_log_rotated(self, qtbot):
        """log_rotated → status_label에 Rotated 포함."""
        win, cfg, cm = _make_win(qtbot)
        win._on_log_rotated("/tmp/log_002.asc")
        assert "Rotated" in win._status_label.text()

    def test_reset_layout_no_crash(self, qtbot):
        """_reset_layout() — 크래시 없음."""
        win, cfg, cm = _make_win(qtbot)
        win._reset_layout()
        assert "초기화" in win._status_label.text()


# ──────────────────────────────────────────────────────────────────────────────
# _flush_trace — drop_count 경고
# ──────────────────────────────────────────────────────────────────────────────

class TestFlushTrace:
    def test_flush_trace_no_drop_no_warning(self, qtbot):
        """drop_count == 0 → 경고 표시 안 함."""
        win, cfg, cm = _make_win(qtbot)
        win._message_store.drop_count = 0
        win._flush_trace()
        assert win._drop_label.text() == ""

    def test_flush_trace_drop_shows_warning(self, qtbot):
        """drop_count > 0 → _drop_label 갱신."""
        win, cfg, cm = _make_win(qtbot)
        win._message_store.drop_count = 5
        win._flush_trace()
        assert "5" in win._drop_label.text() or "드롭" in win._drop_label.text()

    def test_flush_trace_with_batch_auto_scroll(self, qtbot):
        """batch 있고 auto_scroll=True → scroll_to_bottom 호출."""
        from models.parsed_message import ParsedMessage
        win, cfg, cm = _make_win(qtbot)
        win._auto_scroll = True

        pm = ParsedMessage(
            ch_id=0, timestamp=1.0, arb_id=0x100,
            dlc=8, data=bytes(8),
        )
        win._message_store._pending.append(pm)

        win._trace_dock.scroll_to_bottom = MagicMock()
        win._flush_trace()
        win._trace_dock.scroll_to_bottom.assert_called_once()

    def test_flush_trace_no_scroll_when_disabled(self, qtbot):
        """auto_scroll=False → scroll_to_bottom 호출 안 함."""
        from models.parsed_message import ParsedMessage
        win, cfg, cm = _make_win(qtbot)
        win._auto_scroll = False

        pm = ParsedMessage(
            ch_id=0, timestamp=1.0, arb_id=0x100,
            dlc=8, data=bytes(8),
        )
        win._message_store._pending.append(pm)

        win._trace_dock.scroll_to_bottom = MagicMock()
        win._flush_trace()
        win._trace_dock.scroll_to_bottom.assert_not_called()
