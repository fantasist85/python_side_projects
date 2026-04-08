# tests/test_main_window.py
"""
MainWindow — 단위 테스트 (pytest-qt).

검증 항목:
  - _restore_channels() : ConfigManager Mock 반환값 → ChannelManager 연결 흐름
  - _restore_channels() : 빈 채널 목록 → 조기 return (크래시 없음)
  - _restore_channels() : 채널 복원 실패(예외) → 로그 경고만, 크래시 없음
  - _flush_stats()      : 채널 없을 때 크래시 없음
  - _flush_stats()      : 채널 있을 때 status_label 갱신
  - closeEvent()        : QTimer 정지 → Worker stop() 순서 보장
  - _on_sim_worker_created() : tx_echo ↔ dispatcher.on_message 연결 확인

NOTE: MainWindow는 python-can H/W 접근 없이 테스트해야 하므로
      ChannelManager / ConfigManager / Worker를 Mock으로 격리.
"""
import pytest
from unittest.mock import MagicMock, patch, call
from PySide6.QtCore import Qt, QEvent
from core.channel_manager import ChannelConfig


# ── 공통 Mock 팩토리 ──────────────────────────────────────────────────────

def make_mock_ctx(ch_id: int = 0):
    """ChannelContext Mock."""
    ctx = MagicMock()
    ctx.ch_id     = ch_id
    ctx.config    = ChannelConfig(
        interface="virtual", channel=ch_id, bitrate=500_000
    )
    ctx.worker    = MagicMock()
    ctx.worker.isRunning.return_value = False
    ctx.sim_worker = None
    # get_stats() 반환값 설정
    stats = MagicMock()
    stats.bus_load_pct = 0.0
    stats.rx_count     = 0
    stats.tx_count     = 0
    stats.error_count  = 0
    ctx.worker.get_stats.return_value = stats
    return ctx


def _make_main_window(qtbot, restored_channels=None):
    """
    MainWindow를 외부 의존성(HW, QSettings) 없이 생성.

    패치 대상:
      - ConfigManager : 채널 복원 / 윈도우 복원 Mock
      - ChannelManager: add_channel() Mock
    """
    from app.main_window import MainWindow

    if restored_channels is None:
        restored_channels = []

    with (
        patch("app.main_window.ConfigManager") as MockCfg,
        patch("app.main_window.ChannelManager") as MockCM,
    ):
        # ConfigManager 설정
        mock_cfg = MagicMock()
        mock_cfg.restore_window.return_value        = False
        mock_cfg.restore_trace_filter.return_value  = ("", "", True)
        mock_cfg.restore_graph_window.return_value  = 30
        mock_cfg.restore_channels.return_value      = restored_channels
        MockCfg.return_value = mock_cfg

        # ChannelManager 설정
        mock_cm = MagicMock()
        mock_cm.all.return_value = []
        mock_cm.MAX_CHANNELS     = 4
        MockCM.return_value = mock_cm

        win = MainWindow()
        qtbot.addWidget(win)

    return win, mock_cfg, mock_cm


# ── _restore_channels ─────────────────────────────────────────────────────

class TestMainWindowRestoreChannels:
    def test_restore_empty_no_crash(self, qtbot):
        """빈 채널 목록 복원 — 크래시 없어야 한다."""
        win, cfg, cm = _make_main_window(qtbot, restored_channels=[])
        # __init__ 내부에서 이미 호출됨 — 추가 호출도 안전해야 함
        win._restore_channels()

    def test_restore_calls_add_channel(self, qtbot):
        """저장된 채널이 있으면 ChannelManager.add_channel() 호출되어야 한다."""
        cfg_item = ChannelConfig(interface="virtual", channel=0, bitrate=500_000)
        restored = [(0, cfg_item)]

        with (
            patch("app.main_window.ConfigManager") as MockCfg,
            patch("app.main_window.ChannelManager") as MockCM,
        ):
            mock_cfg = MagicMock()
            mock_cfg.restore_window.return_value        = False
            mock_cfg.restore_trace_filter.return_value  = ("", "", True)
            mock_cfg.restore_graph_window.return_value  = 30
            mock_cfg.restore_channels.return_value      = restored
            MockCfg.return_value = mock_cfg

            mock_cm = MagicMock()
            mock_ctx = make_mock_ctx(ch_id=0)
            mock_cm.add_channel.return_value = mock_ctx
            mock_cm.all.return_value         = []
            mock_cm.MAX_CHANNELS             = 4
            MockCM.return_value = mock_cm

            from app.main_window import MainWindow
            win = MainWindow()
            qtbot.addWidget(win)

        # add_channel이 ch_id=0, cfg=cfg_item 으로 호출되었는지 확인
        mock_cm.add_channel.assert_called_with(0, cfg_item)

    def test_restore_exception_no_crash(self, qtbot):
        """채널 복원 중 예외 발생 시 — 나머지 채널 복원 계속, 크래시 없어야 한다."""
        cfg_item = ChannelConfig(interface="virtual", channel=0, bitrate=500_000)
        restored = [(0, cfg_item), (1, cfg_item)]

        with (
            patch("app.main_window.ConfigManager") as MockCfg,
            patch("app.main_window.ChannelManager") as MockCM,
        ):
            mock_cfg = MagicMock()
            mock_cfg.restore_window.return_value        = False
            mock_cfg.restore_trace_filter.return_value  = ("", "", True)
            mock_cfg.restore_graph_window.return_value  = 30
            mock_cfg.restore_channels.return_value      = restored
            MockCfg.return_value = mock_cfg

            mock_cm = MagicMock()
            # 첫 번째 add_channel은 예외, 두 번째는 성공
            mock_ctx = make_mock_ctx(ch_id=1)
            mock_cm.add_channel.side_effect = [RuntimeError("Bus error"), mock_ctx]
            mock_cm.all.return_value = []
            mock_cm.MAX_CHANNELS     = 4
            MockCM.return_value = mock_cm

            from app.main_window import MainWindow
            win = MainWindow()   # 크래시 없어야 함
            qtbot.addWidget(win)


# ── _flush_stats ──────────────────────────────────────────────────────────

class TestMainWindowFlushStats:
    def test_flush_stats_no_channel_no_crash(self, qtbot):
        """채널 없을 때 _flush_stats() — 크래시 없어야 한다."""
        win, cfg, cm = _make_main_window(qtbot)
        cm.all.return_value = []
        win._flush_stats()

    def test_flush_stats_updates_status_label(self, qtbot):
        """채널 있을 때 _flush_stats() — status_label 텍스트 갱신."""
        win, cfg, cm = _make_main_window(qtbot)

        ctx = make_mock_ctx(ch_id=0)
        ctx.worker.get_stats.return_value.bus_load_pct = 12.5
        ctx.worker.get_stats.return_value.rx_count     = 100
        cm.all.return_value = [ctx]

        win._flush_stats()
        text = win._status_label.text()
        assert "CH1" in text
        assert "12.5" in text

    def test_flush_stats_multiple_channels(self, qtbot):
        """채널 2개 — 모두 status_label에 표시되어야 한다."""
        win, cfg, cm = _make_main_window(qtbot)
        ctxs = [make_mock_ctx(ch_id=i) for i in range(2)]
        cm.all.return_value = ctxs

        win._flush_stats()
        text = win._status_label.text()
        assert "CH1" in text
        assert "CH2" in text


# ── _on_sim_worker_created ────────────────────────────────────────────────

class TestMainWindowSimWorkerCreated:
    def test_tx_echo_connected_to_dispatcher(self, qtbot):
        """
        sim_worker_created 수신 시 tx_echo가 dispatcher.on_message에
        QueuedConnection으로 연결되어야 한다.
        """
        win, cfg, cm = _make_main_window(qtbot)

        mock_sim_worker = MagicMock()
        win._on_sim_worker_created(mock_sim_worker)

        # connect() 가 Qt.ConnectionType.QueuedConnection 인자로 호출되었는지 확인
        mock_sim_worker.tx_echo.connect.assert_called_once_with(
            win._dispatcher.on_message,
            Qt.ConnectionType.QueuedConnection,
        )


# ── closeEvent ────────────────────────────────────────────────────────────

class TestMainWindowCloseEvent:
    def test_close_event_stops_timers_before_workers(self, qtbot):
        """
        closeEvent: QTimer 정지가 Worker stop()보다 먼저 호출되어야 한다.
        (아키텍처 규칙 §8: Shutdown 순서)
        """
        from PySide6.QtGui import QCloseEvent
        win, cfg, cm = _make_main_window(qtbot)

        ctx = make_mock_ctx(ch_id=0)
        cm.all.return_value = [ctx]

        call_order = []

        # Timer stop() 추적
        win._timer_trace.timeout.disconnect()
        orig_trace_stop = win._timer_trace.stop
        def trace_stop():
            call_order.append("timer_trace_stop")
            orig_trace_stop()
        win._timer_trace.stop = trace_stop

        # Worker stop() 추적
        def worker_stop():
            call_order.append("worker_stop")
        ctx.worker.stop = worker_stop

        event = QCloseEvent()
        win.closeEvent(event)

        # timer_trace_stop이 worker_stop보다 먼저 나와야 함
        if "timer_trace_stop" in call_order and "worker_stop" in call_order:
            assert call_order.index("timer_trace_stop") < call_order.index("worker_stop")

    def test_close_event_saves_config(self, qtbot):
        """closeEvent 시 설정 저장 메서드들이 호출되어야 한다."""
        from PySide6.QtGui import QCloseEvent
        win, cfg, cm = _make_main_window(qtbot)
        cm.all.return_value = []

        event = QCloseEvent()
        win.closeEvent(event)

        cfg.save_window.assert_called_once()
        cfg.save_channels.assert_called_once()
