# app/main_window.py
"""
MainWindow — Presentation 레이어.
Main Thread 전용. UI 위젯 접근 + QTimer 배치 갱신만.
decode·파일 I/O 절대 금지.
"""
import logging

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QMainWindow,
    QStatusBar,
    QToolBar,
    QWidget,
    QVBoxLayout,
    QMessageBox,
)

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
              QTimer 정지 전 Worker stop() 호출 (타이머 슬롯이 종료된 Worker 접근 가능).
    """

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("PyCANoe v1.0")
        self.resize(1200, 800)

        # ── 데이터 레이어 ──────────────────────────────────────────────
        self._message_store    = MessageStore()
        self._signal_registry  = SignalBufferRegistry()
        self._log_queue        = LogQueue()
        self._sim_state        = SimStateStore()

        # ── 서비스 레이어 ─────────────────────────────────────────────
        self._dispatcher = MessageDispatcher(
            store     = self._message_store,
            registry  = self._signal_registry,
            log_queue = self._log_queue,
            sim_store = self._sim_state,
        )
        self._channel_manager = ChannelManager(self._dispatcher)

        # LogWorker (기본 경로 — 실제 경로는 Log 시작 시 설정)
        self._log_worker: LogWorker | None = None

        # GC 방지 — AsyncDbLoader는 반드시 self에 저장
        self._db_loader: AsyncDbLoader | None = None

        # ── UI ────────────────────────────────────────────────────────
        self._auto_scroll = True
        self._trace_model = TraceModel(self)
        self._setup_ui()
        self._setup_timers()

        # 상태바 라벨
        self._status_label = QLabel("준비")
        self.statusBar().addWidget(self._status_label)

    # ------------------------------------------------------------------
    # UI 초기화
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        from widgets.trace_dock import TraceDock
        self._trace_dock = TraceDock(self._trace_model, self)
        self.setCentralWidget(self._trace_dock)
        self._setup_toolbar()

    def _setup_toolbar(self) -> None:
        tb = QToolBar("메인 툴바", self)
        self.addToolBar(tb)

        tb.addAction("+ CH 추가", self._on_add_channel_clicked)
        tb.addAction("DBC/LDF 로드", self._on_load_db_clicked)
        tb.addSeparator()
        tb.addAction("▶ Start", self._on_start_clicked)
        tb.addAction("■ Stop",  self._on_stop_clicked)
        tb.addSeparator()
        tb.addAction("● Log 시작", self._on_log_start_clicked)
        tb.addAction("■ Log 중지", self._on_log_stop_clicked)

    # ------------------------------------------------------------------
    # QTimer 배치 갱신 (Main Thread 전용)
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
            self._show_buffer_warning(self._message_store.drop_count)

    def _flush_graph(self) -> None:
        # Graph Dock 연동 — M4에서 구현
        pass

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
        """채널 추가 — 임시: virtual CH0."""
        ch_id = len(self._channel_manager.all())
        if ch_id >= ChannelManager.MAX_CHANNELS:
            QMessageBox.warning(self, "경고", "최대 4채널까지 지원합니다.")
            return
        config = ChannelConfig(interface="virtual", channel=ch_id, bitrate=500_000)
        self._channel_manager.add_channel(ch_id, config)
        self._status_label.setText(f"CH{ch_id + 1} 추가됨 (virtual)")

    def _on_load_db_clicked(self) -> None:
        """DBC/LDF 비동기 로드. self._db_loader에 저장 필수 (GC 방지)."""
        path, _ = QFileDialog.getOpenFileName(
            self, "DBC/LDF 파일 선택", "", "DB Files (*.dbc *.ldf)"
        )
        if not path:
            return

        ctxs = self._channel_manager.all()
        if not ctxs:
            QMessageBox.information(self, "안내", "먼저 채널을 추가하세요.")
            return

        # 연속 로드 시 이전 Signal disconnect
        if self._db_loader is not None:
            try:
                self._db_loader.db_loaded.disconnect(self._on_db_loaded)
            except RuntimeError:
                pass

        # 첫 번째 채널의 DbParser로 비동기 로드
        parser = ctxs[0].db_parser
        self._db_loader = AsyncDbLoader(parser, path)   # 반드시 self에 저장
        self._db_loader.db_loaded.connect(self._on_db_loaded)
        self._db_loader.start_loading()
        self._status_label.setText(f"DB 로딩 중: {path}")

    def _on_db_loaded(self, success: bool, parser) -> None:
        """AsyncDbLoader.db_loaded Signal 수신 — Main Thread."""
        if success:
            self._signal_registry.enable_all()   # SignalBuffer 활성화
            self._status_label.setText(
                f"DB 로드 완료 [{parser.db_type.upper()}]"
            )
        else:
            self._status_label.setText("DB 로드 실패")

    def _on_start_clicked(self) -> None:
        for ctx in self._channel_manager.all():
            if not ctx.worker.isRunning():
                ctx.worker.start()
        self._status_label.setText("수신 중...")

    def _on_stop_clicked(self) -> None:
        for ctx in self._channel_manager.all():
            if ctx.worker.isRunning():
                ctx.worker.stop()
        self._status_label.setText("정지")

    def _on_log_start_clicked(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "로그 파일 저장", "log.asc", "ASC Files (*.asc)"
        )
        if not path:
            return
        if self._log_worker and self._log_worker.isRunning():
            self._log_worker.stop()
        self._log_worker = LogWorker(self._log_queue, path, fmt="asc")
        self._log_worker.log_dropped.connect(self._on_log_dropped)
        self._log_worker.log_rotated.connect(self._on_log_rotated)
        self._log_worker.start()
        self._status_label.setText(f"● REC — {path}")

    def _on_log_stop_clicked(self) -> None:
        if self._log_worker and self._log_worker.isRunning():
            self._log_worker.stop()
        self._status_label.setText("로그 중지")

    def _on_log_dropped(self, count: int) -> None:
        self._show_buffer_warning(count)

    def _on_log_rotated(self, new_path: str) -> None:
        self._status_label.setText(f"● REC (Rotated) — {new_path}")

    # ------------------------------------------------------------------
    # 경고 표시
    # ------------------------------------------------------------------

    def _show_buffer_warning(self, drop_count: int) -> None:
        self.statusBar().showMessage(
            f"⚠ 버퍼 드롭 {drop_count}건", 3000
        )

    # ------------------------------------------------------------------
    # 종료 시퀀스 — CRITICAL SHUTDOWN SEQUENCE 100% 준수
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        """
        [CRITICAL SHUTDOWN SEQUENCE]
        1. 모든 QTimer 정지 (UI 갱신 중단)
        2. CANWorker.stop() 호출
        3. SimWorker.stop() 호출
        4. LogWorker.stop() 호출
        5. 모든 Worker .wait() — QThread.stop()에 포함되어 있음

        ★ terminate() 절대 금지 — H/W 포트 미해제 → BSoD/Segfault
        ★ QTimer 정지 전 stop() 호출 금지
        """
        # 1. QTimer 전부 정지
        self._timer_trace.stop()
        self._timer_graph.stop()
        self._timer_stats.stop()

        # 2 + 3. CANWorker / SimWorker stop (내부에서 .wait() 포함)
        for ctx in self._channel_manager.all():
            ctx.worker.stop()
            if ctx.sim_worker and ctx.sim_worker.isRunning():
                ctx.sim_worker.stop()

        # 4. LogWorker stop
        if self._log_worker and self._log_worker.isRunning():
            self._log_worker.stop()

        super().closeEvent(event)
