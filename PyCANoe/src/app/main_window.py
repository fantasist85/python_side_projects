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
    QMenu,
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
from core.virtual_node_engine import VirtualNodeEngine  # M7
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

        # M7 — Virtual Node Engine
        self._vne = VirtualNodeEngine(self._channel_manager, self._sim_state, self)

        # GC 방어 — AsyncDbLoader 반드시 self에 저장
        self._db_loader: AsyncDbLoader | None = None
        self._log_worker: LogWorker | None = None
        self._config = ConfigManager()

        # ── UI ────────────────────────────────────────────────────────
        self._auto_scroll = True
        self._trace_model = TraceModel(self)
        self._setup_ui()
        self._setup_menu()
        self._setup_timers()

        # 상태바
        self._status_label = QLabel("준비")
        self.statusBar().addWidget(self._status_label)
        self._drop_label = QLabel("")
        self._drop_label.setStyleSheet("color: #B71C1C;")
        self.statusBar().addPermanentWidget(self._drop_label)

        # 설정 복원
        self._config.restore_window(self)
        filter_id, filter_mask, auto_scroll = self._config.restore_trace_filter()
        self._trace_dock.restore_filter(filter_id, filter_mask)
        self._auto_scroll = auto_scroll
        rolling_sec = self._config.restore_graph_window()
        self._graph_dock.set_rolling_sec(rolling_sec)

        # 채널 설정 복원 — 이전 세션에서 저장된 채널을 자동 재등록
        self._restore_channels()

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
        self._sim_dock.sim_worker_created.connect(self._on_sim_worker_created)
        sim_dw = QDockWidget("Simulation (IG)", self)
        sim_dw.setObjectName("SimDock")
        sim_dw.setWidget(self._sim_dock)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, sim_dw)
        self._sim_dw = sim_dw

        # Bus Statistics Dock (M6 선택 항목)
        from widgets.bus_stats_dock import BusStatsDock
        self._bus_stats_dock = BusStatsDock(self)
        bus_stats_dw = QDockWidget("Bus Statistics", self)
        bus_stats_dw.setObjectName("BusStatsDock")
        bus_stats_dw.setWidget(self._bus_stats_dock)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, bus_stats_dw)
        bus_stats_dw.hide()
        self._bus_stats_dw = bus_stats_dw

        # M7 — Virtual Node Dock
        from widgets.virtual_node_dock import VirtualNodeDock
        self._vn_dock = VirtualNodeDock(self._vne, self._channel_manager, self)
        vn_dw = QDockWidget("Virtual Node", self)
        vn_dw.setObjectName("VirtualNodeDock")
        vn_dw.setWidget(self._vn_dock)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, vn_dw)
        vn_dw.hide()
        self._vn_dw = vn_dw

        self._setup_toolbar()

    def _setup_menu(self) -> None:
        """메뉴바 — View 메뉴 (Reset Layout 포함)."""
        menu_bar = self.menuBar()

        view_menu = menu_bar.addMenu("View")

        act_reset = view_menu.addAction("↺ 레이아웃 초기화 (Default)")
        act_reset.triggered.connect(self._reset_layout)

        view_menu.addSeparator()

        act_bus_stats = view_menu.addAction("Bus Statistics")
        act_bus_stats.setCheckable(True)
        act_bus_stats.setChecked(False)
        act_bus_stats.toggled.connect(self._bus_stats_dw.setVisible)
        self._bus_stats_dw.visibilityChanged.connect(act_bus_stats.setChecked)

        act_graph = view_menu.addAction("Graph")
        act_graph.setCheckable(True)
        act_graph.setChecked(False)
        act_graph.toggled.connect(self._graph_dw.setVisible)
        self._graph_dw.visibilityChanged.connect(act_graph.setChecked)

        act_sim = view_menu.addAction("Simulation (IG)")
        act_sim.setCheckable(True)
        act_sim.setChecked(True)
        act_sim.toggled.connect(self._sim_dw.setVisible)
        self._sim_dw.visibilityChanged.connect(act_sim.setChecked)

        act_vn = view_menu.addAction("Virtual Node")   # M7
        act_vn.setCheckable(True)
        act_vn.setChecked(False)
        act_vn.toggled.connect(self._vn_dw.setVisible)
        self._vn_dw.visibilityChanged.connect(act_vn.setChecked)

    # ------------------------------------------------------------------
    # View > Reset Layout
    # ------------------------------------------------------------------

    def _reset_layout(self) -> None:
        """
        모든 Dock을 초기 레이아웃으로 복원.
        - GraphDock    : 숨김 (DBC 로드 후 자동 표시)
        - SimDock      : BottomDockWidgetArea 표시
        - BusStatsDock : 숨김
        """
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._graph_dw)
        self._graph_dw.hide()

        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._sim_dw)
        self._sim_dw.show()

        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._bus_stats_dw)
        self._bus_stats_dw.hide()

        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._vn_dw)   # M7
        self._vn_dw.hide()

        self._status_label.setText("레이아웃이 기본값으로 초기화되었습니다.")
        logger.info("레이아웃 초기화")

    def _setup_toolbar(self) -> None:
        tb = QToolBar("메인 툴바", self)
        tb.setObjectName("MainToolBar")
        tb.setMovable(False)
        self.addToolBar(tb)

        tb.addAction("+ CH 추가",     self._on_add_channel_clicked)
        tb.addAction("- CH 제거",     self._on_remove_channel_clicked)   # A-1
        tb.addAction("✎ CH 편집",     self._on_edit_channel_clicked)     # A-1
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
        # C-3: 컴팩트 채널별 상태바 (버스 타입 포함)
        parts = []
        stats_list = []
        for ctx in self._channel_manager.all():
            stats    = ctx.worker.get_stats()
            bus_type = getattr(ctx.config, "bus_type", "can").upper()
            parts.append(
                f"[CH{ctx.ch_id + 1}/{bus_type}] "
                f"Load:{stats.bus_load_pct:.0f}% "
                f"Rx:{stats.rx_count} "
                f"Tx:{stats.tx_count} "
                f"Err:{stats.error_count}"
            )
            stats_list.append((ctx.ch_id, stats))
        if parts:
            self._status_label.setText("  |  ".join(parts))
        # Bus Statistics Dock 갱신 (표시 중인 경우에만)
        if self._bus_stats_dw.isVisible() and stats_list:
            self._bus_stats_dock.update_stats(stats_list)

    # ------------------------------------------------------------------
    # 툴바 슬롯
    # ------------------------------------------------------------------

    def _restore_channels(self) -> None:
        """
        ConfigManager.restore_channels() 값으로 이전 세션 채널을 자동 재등록.
        MainWindow.__init__() 마지막에 호출.
        Worker는 start()하지 않음 — 사용자가 ▶ Start 버튼을 눌러야 수신 시작.
        """
        restored = self._config.restore_channels()
        if not restored:
            return
        for ch_id, cfg in restored:
            try:
                ctx = self._channel_manager.add_channel(ch_id, cfg)
                ctx.worker.error_occurred.connect(
                    self._on_worker_error, Qt.ConnectionType.QueuedConnection)
                ctx.worker.connection_state_changed.connect(
                    self._on_connection_state_changed, Qt.ConnectionType.QueuedConnection)
                # M7: Worker → VNE 메시지 라우팅
                ctx.worker.parsed_message_received.connect(
                    self._vne.on_all_messages, Qt.ConnectionType.QueuedConnection)
                self._trace_dock.add_channel_tab(ch_id)          # 채널 탭 활성화
                self._trace_model.set_ch_type(ch_id, cfg.bus_type)  # B-1
                logger.info("CH%d 설정 복원 (%s / %dkbps)", ch_id + 1,
                            cfg.interface, cfg.bitrate // 1000)
            except Exception as exc:
                logger.warning("CH%d 채널 복원 실패: %s", ch_id, exc)
        if restored:
            self._sim_dock.refresh_channels()
            self._status_label.setText(
                f"{len(restored)}개 채널 설정 복원됨 (▶ Start로 수신 시작)"
            )

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
            # M7: Worker → VNE 메시지 라우팅
            ctx.worker.parsed_message_received.connect(
                self._vne.on_all_messages, Qt.ConnectionType.QueuedConnection)
            self._status_label.setText(
                f"CH{ch_id + 1} 추가됨 ({config.interface} / {config.bitrate // 1000}kbps)"
            )
            self._sim_dock.refresh_channels()
            self._trace_dock.add_channel_tab(ch_id)   # 채널 탭 활성화
            self._trace_model.set_ch_type(ch_id, config.bus_type)   # B-1
        except Exception as exc:
            ErrorDialog.show_error(str(exc), parent=self)

    def _on_remove_channel_clicked(self) -> None:
        """A-1: 현재 선택된 채널 탭의 채널 제거."""
        ch_id = self._trace_dock.get_current_ch_id()
        if ch_id is None:
            QMessageBox.information(self, "안내", "제거할 채널을 탭에서 선택하세요.")
            return
        ctx = self._channel_manager.get(ch_id)
        if ctx is None:
            return
        self._channel_manager.remove_channel(ch_id)
        self._trace_dock.remove_channel_tab(ch_id)
        self._trace_model.remove_ch_type(ch_id)   # B-1 연동
        self._sim_dock.refresh_channels()
        self._status_label.setText(f"CH{ch_id + 1} 제거됨")

    def _on_edit_channel_clicked(self) -> None:
        """A-1: 현재 선택된 채널 탭의 채널 설정 편집."""
        ch_id = self._trace_dock.get_current_ch_id()
        if ch_id is None:
            QMessageBox.information(self, "안내", "편집할 채널을 탭에서 선택하세요.")
            return
        ctx = self._channel_manager.get(ch_id)
        if ctx is None:
            return
        dlg = ChannelDialog(ch_id=ch_id, config=ctx.config, parent=self)
        if dlg.exec() != ChannelDialog.DialogCode.Accepted:
            return
        new_config = dlg.get_config()
        ctx.config = new_config
        self._trace_model.set_ch_type(ch_id, new_config.bus_type)   # B-1 갱신
        self._status_label.setText(f"CH{ch_id + 1} 설정 편집됨")

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
        self._last_db_path = path   # BUG-3: 에러 메시지용 경로 보관
        parser = ctxs[0].db_parser
        self._db_loader = AsyncDbLoader(parser, path)
        self._db_loader.db_loaded.connect(self._on_db_loaded)
        self._db_loader.start_loading()
        self._status_label.setText(f"DB 로딩 중: {path}")

    def _on_db_loaded(self, success: bool, parser) -> None:
        if success:
            # BUG-2: 모든 채널 파서에 로드된 DB 동기화
            for ctx in self._channel_manager.all():
                if ctx.db_parser is not parser:
                    ctx.db_parser._db          = parser._db
                    ctx.db_parser._type        = parser._type
                    ctx.db_parser._ldf_enc_map = parser._ldf_enc_map  # A-2
                    ctx.db_parser.clear_cache()
                ctx.worker.update_db(ctx.db_parser)

            self._signal_registry.enable_all()
            self._graph_dock.enable()
            self._graph_dw.show()
            self._trace_dock.set_db_loaded(True)   # 우클릭 "Send to Graph" 활성화
            self._sim_dock.set_db(parser)          # B-2: LDF 프레임 목록 갱신
            self._status_label.setText(f"DB 로드 완료 [{parser.db_type.upper()}]")
        else:
            self._trace_dock.set_db_loaded(False)
            self._status_label.setText("DB 로드 실패")
            # BUG-3: 파일 경로 및 원인 안내 포함
            path_info = getattr(self, "_last_db_path", "")
            detail = f"\n\n파일: {path_info}" if path_info else ""
            ErrorDialog.show_error(
                f"DBC/LDF 파일 로드에 실패했습니다.{detail}"
                "\n\n파일 형식/내용을 확인하거나 로그를 참조하세요.",
                parent=self,
            )

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
            self, "로그 파일 저장", default,
            "ASC Files (*.asc);;CSV Files (*.csv);;All Files (*)")
        if not path:
            return
        # 확장자 기반으로 포맷 자동 결정 — fmt 하드코딩 제거
        fmt = "csv" if path.lower().endswith(".csv") else "asc"
        if self._log_worker and self._log_worker.isRunning():
            self._log_worker.stop()
        self._log_worker = LogWorker(self._log_queue, path, fmt=fmt)
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

    def _on_sim_worker_created(self, sim_worker) -> None:
        """
        SimDock.sim_worker_created Signal 수신.
        tx_echo(ParsedMessage) → Dispatcher.on_message QueuedConnection 연결.
        Trace 파랑 컬러링(is_tx=True)이 동작하려면 이 연결 필수.
        """
        sim_worker.tx_echo.connect(
            self._dispatcher.on_message,
            Qt.ConnectionType.QueuedConnection,
        )

    def _on_worker_error(self, msg: str) -> None:
        logger.warning("Worker 오류: %s", msg)
        self._status_label.setText(f"⚠ {msg}")
        ErrorDialog.show_error(msg, parent=self)

    def _on_connection_state_changed(self, ch_id: int, is_connected: bool) -> None:
        state = "연결됨" if is_connected else "끊김"
        self._status_label.setText(f"CH{ch_id + 1} {state}")
        self._trace_dock.update_channel_tab_state(ch_id, is_connected)  # C-1

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

        # M7: Virtual Node Engine 전체 정지
        self._vne.unload_all()

        # 4. LogWorker stop
        if self._log_worker and self._log_worker.isRunning():
            self._log_worker.stop()

        super().closeEvent(event)
