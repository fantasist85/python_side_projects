# widgets/trace_dock.py
"""
TraceDock — CAN/LIN 실시간 Trace 뷰 Dock.

THREAD  : Main Thread 전용
INPUT   : TraceModel (QAbstractTableModel)
OUTPUT  : send_to_graph(int, str), send_to_sim(int, int, int, bytes) Signal
DO NOT  : Worker Thread에서 UI 위젯 직접 접근

우클릭 컨텍스트 메뉴 (명세서 8.2):
  - "이 ID 필터링"    — arb_id를 필터 바에 자동 입력
  - "클립보드로 복사" — HEX 데이터 복사
  - "Send to Graph"   — DBC 있을 때만 활성 (_db_loaded 플래그)
  - "Send to Simulation" — arb_id, data, dlc 자동 등록

SW 필터 UI:
  - ID 입력 LineEdit + Mask 입력 LineEdit + [적용] [초기화] 버튼
  - TraceModel.set_filter() / clear_filter() 연결
"""
from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from models.trace_model import TraceModel

logger = logging.getLogger(__name__)


class TraceDock(QWidget):
    """
    THREAD  : Main Thread 전용
    INPUT   : TraceModel (QAbstractTableModel)
    OUTPUT  : send_to_graph(ch_id, sig_name),
              send_to_sim(ch_id, arb_id, dlc, data) Signal
    DO NOT  : Worker Thread에서 UI 위젯 직접 접근
    """

    # 우클릭 메뉴 → MainWindow 연결용 Signal
    send_to_graph = Signal(int, str)               # (ch_id, sig_name)
    send_to_sim   = Signal(int, int, int, object)  # (ch_id, arb_id, dlc, data)

    def __init__(self, model: TraceModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._model     = model
        self._db_loaded = False   # DBC 로드 완료 여부 — "Send to Graph" 활성 조건

        self._build_ui()

    # ------------------------------------------------------------------
    # UI 구성
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── 필터 바 ───────────────────────────────────────────────────
        layout.addWidget(self._build_filter_bar())

        # ── Trace 뷰 ──────────────────────────────────────────────────
        self._view = QTreeView(self)
        self._view.setModel(self._model)

        # 고성능 렌더링 필수 설정 (명세서 8.2)
        self._view.setUniformRowHeights(True)   # 렌더링 성능 100배+ 향상
        self._view.setAnimated(False)           # 애니메이션 연산 제거
        self._view.setRootIsDecorated(False)
        self._view.setAlternatingRowColors(True)
        self._view.setSelectionBehavior(QTreeView.SelectionBehavior.SelectRows)

        # 컬럼 너비 초기 설정
        header = self._view.header()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        # 주요 컬럼 초기 너비 (Ch, Timestamp, Type, ID, DLC)
        for col, width in enumerate([40, 100, 55, 70, 45]):
            self._view.setColumnWidth(col, width)

        # 우클릭 컨텍스트 메뉴
        self._view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._view.customContextMenuRequested.connect(self._on_context_menu)

        layout.addWidget(self._view)

    def _build_filter_bar(self) -> QWidget:
        """SW ID 필터 바 위젯 생성."""
        bar = QWidget(self)
        bar.setFixedHeight(36)
        h = QHBoxLayout(bar)
        h.setContentsMargins(6, 4, 6, 4)
        h.setSpacing(6)

        h.addWidget(QLabel("ID:"))

        self._le_filter_id = QLineEdit()
        self._le_filter_id.setPlaceholderText("hex, 예: 1A0")
        self._le_filter_id.setFixedWidth(80)
        self._le_filter_id.returnPressed.connect(self._on_filter_apply)
        h.addWidget(self._le_filter_id)

        h.addWidget(QLabel("Mask:"))

        self._le_filter_mask = QLineEdit("7FF")
        self._le_filter_mask.setFixedWidth(60)
        self._le_filter_mask.returnPressed.connect(self._on_filter_apply)
        h.addWidget(self._le_filter_mask)

        btn_apply = QPushButton("적용")
        btn_apply.setFixedWidth(50)
        btn_apply.clicked.connect(self._on_filter_apply)
        h.addWidget(btn_apply)

        btn_clear = QPushButton("초기화")
        btn_clear.setFixedWidth(55)
        btn_clear.clicked.connect(self._on_filter_clear)
        h.addWidget(btn_clear)

        h.addStretch()

        return bar

    # ------------------------------------------------------------------
    # 필터 슬롯
    # ------------------------------------------------------------------

    def _on_filter_apply(self) -> None:
        """필터 적용. 파싱 실패 시 무시."""
        try:
            filter_id   = int(self._le_filter_id.text().strip(), 16)
            filter_mask = int(self._le_filter_mask.text().strip(), 16)
        except ValueError:
            logger.debug("TraceDock: 필터 입력값 파싱 실패 — 무시")
            return
        self._model.set_filter(filter_id, filter_mask)
        logger.debug("TraceDock: 필터 적용 id=0x%X mask=0x%X", filter_id, filter_mask)

    def _on_filter_clear(self) -> None:
        """필터 초기화."""
        self._le_filter_id.clear()
        self._le_filter_mask.setText("7FF")
        self._model.clear_filter()
        logger.debug("TraceDock: 필터 초기화")

    # ------------------------------------------------------------------
    # 우클릭 컨텍스트 메뉴
    # ------------------------------------------------------------------

    def _on_context_menu(self, pos) -> None:
        """우클릭 컨텍스트 메뉴 (명세서 8.2)."""
        index = self._view.indexAt(pos)
        if not index.isValid():
            return

        msg = self._model.get_row(index.row())
        if msg is None:
            return

        menu = QMenu(self)

        # ── 이 ID 필터링 ──────────────────────────────────────────────
        act_filter = menu.addAction(f"이 ID 필터링  (0x{msg.arb_id:X})")
        act_filter.triggered.connect(lambda: self._apply_id_filter(msg.arb_id))

        # ── 클립보드로 복사 ───────────────────────────────────────────
        act_copy = menu.addAction("클립보드로 복사")
        act_copy.triggered.connect(lambda: self._copy_to_clipboard(msg))

        menu.addSeparator()

        # ── Send to Graph — DBC 로드 후에만 활성 ─────────────────────
        act_graph = menu.addAction("Send to Graph")
        has_signals = self._db_loaded and bool(msg.signals)
        act_graph.setEnabled(has_signals)
        if has_signals:
            act_graph.triggered.connect(lambda: self._send_signals_to_graph(msg))

        # ── Send to Simulation ────────────────────────────────────────
        act_sim = menu.addAction("Send to Simulation")
        act_sim.triggered.connect(
            lambda: self.send_to_sim.emit(msg.ch_id, msg.arb_id, msg.dlc, msg.data)
        )

        menu.exec(self._view.viewport().mapToGlobal(pos))

    def _apply_id_filter(self, arb_id: int) -> None:
        """우클릭 'ID 필터링' — 필터 바에 arb_id 자동 입력 후 적용."""
        self._le_filter_id.setText(f"{arb_id:X}")
        self._on_filter_apply()

    def _copy_to_clipboard(self, msg) -> None:
        """우클릭 '클립보드로 복사' — 행 정보를 텍스트로 복사."""
        text = (
            f"CH{msg.ch_id + 1}  "
            f"ts={msg.timestamp:.4f}  "
            f"id=0x{msg.arb_id:X}  "
            f"dlc={msg.dlc}  "
            f"data={msg.data.hex(' ').upper()}"
        )
        QGuiApplication.clipboard().setText(text)
        logger.debug("TraceDock: 클립보드 복사 완료")

    def _send_signals_to_graph(self, msg) -> None:
        """
        우클릭 'Send to Graph' — signals 딕셔너리의 신호를 순서대로 Graph에 전달.
        """
        if not msg.signals:
            return
        for sig_name in msg.signals:
            self.send_to_graph.emit(msg.ch_id, sig_name)

    # ------------------------------------------------------------------
    # 외부 인터페이스
    # ------------------------------------------------------------------

    def scroll_to_bottom(self) -> None:
        """Auto-Scroll — MainWindow._flush_trace()에서 QTimer(50ms)마다 호출."""
        self._view.scrollToBottom()

    def set_db_loaded(self, loaded: bool) -> None:
        """
        DBC/LDF 로드 완료 시 MainWindow._on_db_loaded()에서 호출.
        True이면 우클릭 'Send to Graph' 활성화.
        """
        self._db_loaded = loaded

    def get_filter(self) -> tuple[str, str]:
        """
        MainWindow.closeEvent()에서 QSettings 저장용 호출.
        반환: (filter_id_hex_str, filter_mask_hex_str)
        """
        return (
            self._le_filter_id.text().strip(),
            self._le_filter_mask.text().strip(),
        )

    def restore_filter(self, filter_id: str, filter_mask: str) -> None:
        """ConfigManager.restore_trace_filter() 값으로 UI 복원."""
        if filter_id:
            self._le_filter_id.setText(filter_id)
        if filter_mask:
            self._le_filter_mask.setText(filter_mask)
        if filter_id:
            self._on_filter_apply()
