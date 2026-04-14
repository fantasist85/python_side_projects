# widgets/trace_dock.py
"""
TraceDock — CAN/LIN 실시간 Trace 뷰 Dock.

THREAD  : Main Thread 전용
INPUT   : TraceModel (QAbstractTableModel)
OUTPUT  : send_to_graph(int, str), send_to_sim(int, int, int, bytes) Signal
DO NOT  : Worker Thread에서 UI 위젯 직접 접근

채널 탭 (Rev 6.0 구현):
  [All][CH1][CH2][CH3][CH4] — 탭 클릭 시 TraceModel.set_ch_filter() 연동.
  채널이 추가된 탭만 활성화. add_channel_tab() / remove_channel_tab() 제공.

SW 필터 UI:
  - ID 입력 LineEdit + Mask 입력 LineEdit + [적용] [초기화] 버튼
  - TraceModel.set_filter() / clear_filter() 연결

우클릭 컨텍스트 메뉴 (명세서 8.2):
  - "이 ID 필터링"    — arb_id를 필터 바에 자동 입력
  - "클립보드로 복사" — HEX 데이터 복사
  - "Send to Graph"   — DBC 있을 때만 활성 (_db_loaded 플래그)
  - "Send to Simulation" — arb_id, data, dlc 자동 등록
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
    QTabBar,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from models.trace_model import TraceModel

logger = logging.getLogger(__name__)

# 채널 탭 레이블 (인덱스 0 = All)
_TAB_ALL = "All"
_MAX_CH  = 4


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
        self._model      = model
        self._db_loaded  = False   # DBC 로드 완료 여부 — "Send to Graph" 활성 조건
        self._active_chs: set[int] = set()   # 활성화된 채널 ch_id 집합

        self._build_ui()

    # ------------------------------------------------------------------
    # UI 구성
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── 채널 탭 바 ────────────────────────────────────────────────
        self._tab_bar = QTabBar(self)
        self._tab_bar.setExpanding(False)
        self._tab_bar.addTab(_TAB_ALL)    # 인덱스 0 = All (항상 존재)
        for i in range(_MAX_CH):
            self._tab_bar.addTab(f"CH{i + 1}")
            self._tab_bar.setTabEnabled(i + 1, False)   # 채널 추가 전 비활성
        self._tab_bar.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self._tab_bar)

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
        self._le_filter_id.setPlaceholderText("예: 1A0 또는 1A0,2B0")   # C-2
        self._le_filter_id.setFixedWidth(110)
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
    # 채널 탭 슬롯
    # ------------------------------------------------------------------

    def _on_tab_changed(self, index: int) -> None:
        """
        탭 변경 시 TraceModel 채널 필터 갱신.
        index 0 = All → clear_ch_filter()
        index 1..4 = CH1..4 → set_ch_filter(ch_id)
        """
        if index == 0:
            self._model.clear_ch_filter()
            logger.debug("TraceDock: 채널 탭 → All")
        else:
            ch_id = index - 1   # 탭 인덱스 1→ch_id 0, 탭 인덱스 2→ch_id 1, ...
            self._model.set_ch_filter(ch_id)
            logger.debug("TraceDock: 채널 탭 → CH%d", ch_id + 1)
        # 필터 변경 후 뷰 갱신
        self._model.layoutChanged.emit()

    # ------------------------------------------------------------------
    # 채널 탭 외부 인터페이스
    # ------------------------------------------------------------------

    def add_channel_tab(self, ch_id: int) -> None:
        """
        채널 추가 시 MainWindow에서 호출.
        해당 CH 탭을 활성화한다. C-1: 초기 아이콘 ■(정지).
        """
        if 0 <= ch_id < _MAX_CH:
            self._active_chs.add(ch_id)
            self._tab_bar.setTabEnabled(ch_id + 1, True)
            self._tab_bar.setTabText(ch_id + 1, f"CH{ch_id + 1} ■")  # C-1
            logger.debug("TraceDock: CH%d 탭 활성화", ch_id + 1)

    def update_channel_tab_state(self, ch_id: int, is_connected: bool) -> None:
        """C-1: 채널 탭 상태 아이콘 갱신. 수신 중=▶, 정지=■."""
        if 0 <= ch_id < _MAX_CH and ch_id in self._active_chs:
            icon = "▶" if is_connected else "■"
            self._tab_bar.setTabText(ch_id + 1, f"CH{ch_id + 1} {icon}")
            logger.debug("TraceDock: CH%d 탭 아이콘 → %s", ch_id + 1, icon)

    def get_current_ch_id(self) -> int | None:
        """현재 선택된 채널 탭의 ch_id 반환. All 탭이면 None."""
        idx = self._tab_bar.currentIndex()
        if idx == 0:
            return None
        return idx - 1

    def remove_channel_tab(self, ch_id: int) -> None:
        """
        채널 제거 시 MainWindow에서 호출.
        해당 CH 탭을 비활성화하고 All 탭으로 이동.
        """
        if 0 <= ch_id < _MAX_CH:
            self._active_chs.discard(ch_id)
            self._tab_bar.setTabEnabled(ch_id + 1, False)
            # 현재 탭이 제거된 채널이면 All로 복귀
            if self._tab_bar.currentIndex() == ch_id + 1:
                self._tab_bar.setCurrentIndex(0)
            logger.debug("TraceDock: CH%d 탭 비활성화", ch_id + 1)

    def refresh_channel_tabs(self, active_ch_ids: list[int]) -> None:
        """
        현재 활성 채널 목록으로 탭 상태를 일괄 갱신.
        ChannelManager.add_channel() / remove_channel() 이후 호출.
        """
        for i in range(_MAX_CH):
            enabled = i in active_ch_ids
            self._tab_bar.setTabEnabled(i + 1, enabled)
            if enabled:
                self._active_chs.add(i)
            else:
                self._active_chs.discard(i)

    # ------------------------------------------------------------------
    # 필터 슬롯
    # ------------------------------------------------------------------

    def _on_filter_apply(self) -> None:
        """C-2: 콤마 구분 멀티 ID 필터 적용. 단일 ID 하위 호환."""
        raw_ids = self._le_filter_id.text().strip()
        if not raw_ids:
            return
        try:
            filter_mask = int(self._le_filter_mask.text().strip(), 16)
        except ValueError:
            filter_mask = 0x7FF

        # C-2: 콤마 구분 파싱 (예: "1A0,2B0,300")
        ids: list[int] = []
        for token in raw_ids.split(","):
            token = token.strip()
            if not token:
                continue
            try:
                ids.append(int(token, 16))
            except ValueError:
                pass

        if not ids:
            logger.debug("TraceDock: 필터 입력값 파싱 실패 — 무시")
            return

        if len(ids) == 1:
            self._model.set_filter(ids[0], filter_mask)
            logger.debug("TraceDock: 필터 적용 id=0x%X mask=0x%X", ids[0], filter_mask)
        else:
            self._model.set_multi_filter(ids, filter_mask)
            logger.debug("TraceDock: 멀티 필터 적용 ids=%s mask=0x%X",
                         [f"0x{i:X}" for i in ids], filter_mask)

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
        self._le_filter_id.setText(f"{arb_id:X}")
        self._on_filter_apply()

    def _copy_to_clipboard(self, msg) -> None:
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
        if not msg.signals:
            return
        for sig_name in msg.signals:
            self.send_to_graph.emit(msg.ch_id, sig_name)

    # ------------------------------------------------------------------
    # 외부 인터페이스
    # ------------------------------------------------------------------

    def scroll_to_bottom(self) -> None:
        self._view.scrollToBottom()

    def set_db_loaded(self, loaded: bool) -> None:
        self._db_loaded = loaded

    def get_filter(self) -> tuple[str, str]:
        return (
            self._le_filter_id.text().strip(),
            self._le_filter_mask.text().strip(),
        )

    def restore_filter(self, filter_id: str, filter_mask: str) -> None:
        if filter_id:
            self._le_filter_id.setText(filter_id)
        if filter_mask:
            self._le_filter_mask.setText(filter_mask)
        if filter_id:
            self._on_filter_apply()
