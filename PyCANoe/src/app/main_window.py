# app/main_window.py
"""
MainWindow — Presentation 레이어 (완전 통합판).

THREAD  : Main Thread 전용. UI 위젯 접근 + QTimer 배치 갱신만.
          decode·파일 I/O 절대 금지.

SHUTDOWN SEQUENCE (closeEvent):
  1. 모든 QTimer 정지
  2. CANWorker.stop()
  3. SimWorker.stop()
  4. LogWorker.stop()
  ★ terminate() 절대 금지
  ★ QTimer 정지 전 Worker stop() 호출 금지
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QToolBar,
)

from app.config_manager import ConfigManager
from app.dialogs.channel_dialog import ChannelDialog
from app.dialogs.error_dialog import ErrorDialog
from core.async_db_loader import AsyncDbLoader
from core.channel_manager import ChannelConfig, ChannelManager
from core.dispatcher import MessageDispatcher
from core.log_worker import LogWorker
from models.log_queue import LogQueue
from models.message_store import MessageStore
from models.numpy_signal_buffer import SignalBufferRegistry
from models.sim_state_store import SimStateStore
from models.trace_model import TraceModel

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """
    THREAD  : Main Thread 전용
    DO NOT  : Worker Thread에서 UI 위젯 접근.
              QTimer 정지 전 Worker stop() 호출.
    """

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PyCANoe v1.0")
        self.resize(1280, 800)

        # ── 데이터 레이어 ──────────────────────────────────────────────
        self._message_store   = MessageStore()
        self._signal_registry = SignalBufferRegistry()
        self._log_queue       = LogQueue()
        self._sim_state       = SimStateStore()

        # ── 서비스 레이어 ─────────────────────────────────────────────
        self._dispatcher = MessageDispatcher(
            store     = self._message_store,
            registry  = self._signal_registry,
            log_queue = self._log_queue,
            sim_store = self._sim_state,
        )
        self._channel_manager = ChannelManager(self._dispatcher)

        # GC 방어 — AsyncDbLoader 반드시 self에 저장
        self._db_loader: AsyncDbLoader | None = None
        self._log_worker: LogWorker | None = None
        self._config = ConfigManager()

        # ── UI ────────────────────────────────────────────────────────
        self._auto_scroll = True
        self._trace_model = TraceModel(self)
        self._setup_ui()
        self._setup_timers()

        # 상태바
        self._status_label = QLabel("준비")
        self.statusBar().addWidget(self._status_label)
        self._drop_label = QLabel("")
        self._drop_label.setStyleSheet("color: #B71C1C;")
        self.statusBar().addPermanentWidget(self._drop_label)

        # 설정 복원
        self._config.restore_window(self)

    # ------------------------------------------------------------------
    # UI 초기화
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        from widgets.trace_dock import TraceDock
        self._trace_dock = TraceDock(self._trace_model, self)
        self._trace_dock.send_to_graph.connect(self._on_send_to_graph)
        self._trace_dock.send_to_sim.connect(self._on_send_to_sim)
        self.setCentralWidget(self._trace_dock)

        from widgets.graph_dock import GraphDock
        self._graph_dock = GraphDock(self._signal_registry, self)
        graph_dw = QDockWidget("Graph", self)
        graph_dw.setObjectName("GraphDock")
        graph_dw.setWidget(self._graph_dock)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, graph_dw)
        graph_dw.hide()
        self._graph_dw = graph_dw

        from widgets.sim_dock import SimDock
        self._sim_dock = SimDock(self._channel_manager, self._sim_state, self)
        sim_dw = QDockWidget("Simulation (IG)", self)
        sim_dw.setObjectName("SimDock")
        sim_dw.setWidget(self._sim_dock)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, sim_dw)
        self._sim_dw = sim_dw

        self._setup_toolbar()

    def _setup_toolbar(self) -> None:
        tb = QToolBar("메인 툴바", self)
        tb.setObjectName("MainToolBar")
        tb.setMovable(False)
        self.addToolBar(tb)

        tb.addAction("+ CH 추가",     self._on_add_channel_clicked)
        tb.addAction("DBC/LDF 로드",  self._on_load_db_clicked)
        tb.addSeparator()
        tb.addAction("▶ Start",       self._on_start_clicked)
        tb.addAction("■ Stop",        self._on_stop_clicked)
        tb.addSeparator()
        tb.addAction("● Log 시작",    self._on_log_start_clicked)
        tb.addAction("■ Log 중지",    self._on_log_stop_clicked)
        tb.addSeparator()

        act_scroll = tb.addAction("↓ Auto-Scroll")
        act_scroll.setCheckable(True)
        act_scroll.setChecked(True)
        act_scroll.toggled.connect(self._on_auto_scroll_toggled)

    # ------------------------------------------------------------------
    # QTimer 배치 갱신
    # ------------------------------------------------------------------

    def _setup_timers(self) -> None:
        self._timer_trace = QTimer(self)
        self._timer_trace.setInterval(50)
        self._timer_trace.timeout.connect(self._flush_trace)

        self._timer_graph = QTimer(self)
        self._timer_graph.setInterval(100)
        self._timer_graph.timeout.connect(self._flush_graph)

        self._timer_stats = QTimer(self)
        self._timer_stats.setInterval(1000)
        self._timer_stats.timeout.connect(self._flush_stats)

        self._timer_trace.start()
        self._timer_graph.start()
        self._timer_stats.start()

    def _flush_trace(self) -> None:
        batch = self._message_store.flush()
        if batch:
            self._trace_model.append_batch(batch)
            if self._auto_scroll:
                self._trace_dock.scroll_to_bottom()
        if self._message_store.drop_count > 0:
            self._show_drop_warning(f"MessageStore 드롭: {self._message_store.drop_count}건")

    def _flush_graph(self) -> None:
        self._graph_dock.update_plots()

    def _flush_stats(self) -> None:
        parts = []
        for ctx in self._channel_manager.all():
            stats = ctx.worker.get_stats()
            parts.append(
                f"CH{ctx.ch_id + 1}: "
                f"Load {stats.bus_load_pct:.1f}% | "
                f"Rx:{stats.rx_count}/s | "
                f"Tx:{stats.tx_count}/s | "
                f"Err:{stats.error_count}"
            )
        if parts:
            self._status_label.setText("  ".join(parts))

    # ------------------------------------------------------------------
    # 툴바 슬롯
    # ------------------------------------------------------------------

    def _on_add_channel_clicked(self) -> None:
        ch_id = len(self._channel_manager.all())
        if ch_id >= ChannelManager.MAX_CHANNELS:
            QMessageBox.warning(self, "경고", "최대 4채널까지 지원합니다.")
            return
        dlg = ChannelDialog(ch_id=ch_id, parent=self)
        if dlg.exec() != ChannelDialog.DialogCode.Accepted:
            return
        config = dlg.get_config()
        try:
            ctx = self._channel_manager.add_channel(ch_id, config)
            ctx.worker.error_occurred.connect(
                self._on_worker_error, Qt.ConnectionType.QueuedConnection)
            ctx.worker.connection_state_changed.connect(
                self._on_connection_state_changed, Qt.ConnectionType.QueuedConnection)
            self._status_label.setText(
                f"CH{ch_id + 1} 추가됨 ({config.interface} / {config.bitrate // 1000}kbps)"
            )
            self._sim_dock.refresh_channels()
        except Exception as exc:
            ErrorDialog.show_error(str(exc), parent=self)

    def _on_load_db_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "DBC/LDF 파일 선택", "", "DB Files (*.dbc *.ldf)")
        if not path:
            return
        ctxs = self._channel_manager.all()
        if not ctxs:
            QMessageBox.information(self, "안내", "먼저 채널을 추가하세요.")
            return
        if self._db_loader is not None:
            try:
                self._db_loader.db_loaded.disconnect(self._on_db_loaded)
            except RuntimeError:
                pass
        parser = ctxs[0].db_parser
        self._db_loader = AsyncDbLoader(parser, path)
        self._db_loader.db_loaded.connect(self._on_db_loaded)
        self._db_loader.start_loading()
        self._status_label.setText(f"DB 로딩 중: {path}")

    def _on_db_loaded(self, success: bool, parser) -> None:
        if success:
            self._signal_registry.enable_all()
            self._graph_dock.enable()
            self._graph_dw.show()
            self._status_label.setText(f"DB 로드 완료 [{parser.db_type.upper()}]")
        else:
            self._status_label.setText("DB 로드 실패")
            ErrorDialog.show_error("DBC/LDF 파일 로드에 실패했습니다.", parent=self)

    def _on_start_clicked(self) -> None:
        ctxs = self._channel_manager.all()
        if not ctxs:
            QMessageBox.information(self, "안내", "채널을 먼저 추가하세요.")
            return
        for ctx in ctxs:
            if not ctx.worker.isRunning():
                ctx.worker.start()
        self._status_label.setText("수신 중...")

    def _on_stop_clicked(self) -> None:
        for ctx in self._channel_manager.all():
            if ctx.worker.isRunning():
                ctx.worker.stop()
        self._status_label.setText("정지")

    def _on_log_start_clicked(self) -> None:
        default = self._config.restore_log_path() or "log.asc"
        path, _ = QFileDialog.getSaveFileName(
            self, "로그 파일 저장", default, "ASC Files (*.asc)")
        if not path:
            return
        if self._log_worker and self._log_worker.isRunning():
            self._log_worker.stop()
        self._log_worker = LogWorker(self._log_queue, path, fmt="asc")
        self._log_worker.log_dropped.connect(self._on_log_dropped)
        self._log_worker.log_rotated.connect(self._on_log_rotated)
        self._log_worker.start()
        self._config.save_log_path(path)
        self._status_label.setText(f"● REC — {path}")

    def _on_log_stop_clicked(self) -> None:
        if self._log_worker and self._log_worker.isRunning():
            self._log_worker.stop()
        self._status_label.setText("로그 중지")

    def _on_auto_scroll_toggled(self, checked: bool) -> None:
        self._auto_scroll = checked

    # ------------------------------------------------------------------
    # TraceDock → Graph / Sim 연결
    # ------------------------------------------------------------------

    def _on_send_to_graph(self, ch_id: int, sig_name: str) -> None:
        self._graph_dock.add_signal(ch_id, sig_name)
        self._graph_dw.show()

    def _on_send_to_sim(self, ch_id: int, arb_id: int, dlc: int, data: bytes) -> None:
        self._sim_dock.add_from_trace(ch_id, arb_id, dlc, data)
        self._sim_dw.show()

    # ------------------------------------------------------------------
    # Worker 이벤트 슬롯
    # ------------------------------------------------------------------

    def _on_worker_error(self, msg: str) -> None:
        logger.warning("Worker 오류: %s", msg)
        self._status_label.setText(f"⚠ {msg}")
        ErrorDialog.show_error(msg, parent=self)

    def _on_connection_state_changed(self, ch_id: int, is_connected: bool) -> None:
        state = "연결됨" if is_connected else "끊김"
        self._status_label.setText(f"CH{ch_id + 1} {state}")

    def _on_log_dropped(self, count: int) -> None:
        self._show_drop_warning(f"Log 드롭: {count}건")

    def _on_log_rotated(self, new_path: str) -> None:
        self._status_label.setText(f"● REC (Rotated) — {new_path}")

    def _show_drop_warning(self, msg: str) -> None:
        self._drop_label.setText(f"⚠ {msg}")
        self.statusBar().showMessage(msg, 3000)

    # ------------------------------------------------------------------
    # 종료 시퀀스
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        # 1. QTimer 전부 정지
        self._timer_trace.stop()
        self._timer_graph.stop()
        self._timer_stats.stop()

        # 설정 저장
        self._config.save_window(self)
        channel_pairs = [(ctx.ch_id, ctx.config) for ctx in self._channel_manager.all()]
        self._config.save_channels(channel_pairs)
        filter_id, filter_mask = self._trace_dock.get_filter()
        self._config.save_trace_filter(filter_id, filter_mask, self._auto_scroll)
        self._config.save_graph_window(self._graph_dock.rolling_sec())

        # 2+3. CANWorker / SimWorker stop
        for ctx in self._channel_manager.all():
            ctx.worker.stop()
            if ctx.sim_worker and ctx.sim_worker.isRunning():
                ctx.sim_worker.stop()

        # 4. LogWorker stop
        if self._log_worker and self._log_worker.isRunning():
            self._log_worker.stop()

        super().closeEvent(event)
