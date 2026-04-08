# widgets/graph_dock.py
"""
GraphDock — DBC/LDF 기반 신호 실시간 그래프 Dock.

THREAD  : Main Thread 전용 (QTimer 100ms 슬롯에서 setData 호출)
INPUT   : SignalBufferRegistry (NumpySignalBuffer 뷰),
          db_loaded Signal 수신 후 활성화
OUTPUT  : 신호 그래프 표시 (pyqtgraph PlotWidget)
DO NOT  : Worker Thread에서 UI 위젯 접근.
          DBC 없을 때 Graph 활성화 (enable_all() 전 데이터 무시).
          setData()를 QTimer 밖에서 호출 (렌더링 스레드 경합).

채널 색상 (명세서 8.2):
  CH1=파랑(#1565C0), CH2=초록(#2E7D32), CH3=주황(#E65100), CH4=빨강(#B71C1C)
Rolling Window: 5s / 10s / 30s / 0(전체)
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from models.numpy_signal_buffer import SignalBufferRegistry

logger = logging.getLogger(__name__)

# 채널 색상 (명세서 8.2)
CH_COLORS = {
    0: "#1565C0",   # CH1 파랑
    1: "#2E7D32",   # CH2 초록
    2: "#E65100",   # CH3 주황
    3: "#B71C1C",   # CH4 빨강
}

_ROLLING_OPTIONS = [
    ("5초",   5),
    ("10초",  10),
    ("30초",  30),
    ("전체",  0),
]


class GraphDock(QWidget):
    """
    신호 그래프 Dock.

    DBC 로드 전: 비활성 상태 (그래프 업데이트 없음).
    DBC 로드 후: enable() 호출 → 신호 표시 시작.

    사용 예 (MainWindow):
        self._graph_dock = GraphDock(self._signal_registry, self)
        self._graph_dock.setEnabled(False)  # DBC 로드 전 비활성
        # DBC 로드 완료 시:
        self._graph_dock.enable(db_signals)
        # QTimer(100ms) 슬롯:
        self._graph_dock.update_plots()
    """

    signal_added   = Signal(int, str)   # (ch_id, sig_name) — 신호 추가됨
    signal_removed = Signal(int, str)   # (ch_id, sig_name) — 신호 제거됨

    def __init__(
        self,
        registry: SignalBufferRegistry,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._registry      = registry
        self._plot_items: dict[tuple[int, str], object] = {}  # pyqtgraph PlotDataItem
        self._rolling_sec   = 30
        self._enabled       = False
        self._pg_available  = self._try_import_pyqtgraph()
        self._build_ui()

    # ------------------------------------------------------------------
    # pyqtgraph 가용성 확인
    # ------------------------------------------------------------------

    def _try_import_pyqtgraph(self) -> bool:
        try:
            import pyqtgraph  # noqa: F401
            return True
        except ImportError:
            logger.warning("pyqtgraph 미설치 — Graph 기능 비활성. pip install pyqtgraph")
            return False

    # ------------------------------------------------------------------
    # UI 구성
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 툴바
        toolbar = QToolBar()
        toolbar.setMovable(False)

        toolbar.addWidget(QLabel("Rolling:"))
        self._cb_window = QComboBox()
        for label, sec in _ROLLING_OPTIONS:
            self._cb_window.addItem(label, sec)
        self._cb_window.setCurrentIndex(2)   # 30초 기본
        self._cb_window.currentIndexChanged.connect(self._on_window_changed)
        toolbar.addWidget(self._cb_window)

        toolbar.addSeparator()
        btn_add = QPushButton("+ 신호 추가")
        btn_add.clicked.connect(self._on_add_signal_clicked)
        toolbar.addWidget(btn_add)

        btn_clear = QPushButton("전체 제거")
        btn_clear.clicked.connect(self.clear_all)
        toolbar.addWidget(btn_clear)

        layout.addWidget(toolbar)

        # 메인 영역: 신호 목록(좌) + 그래프(우)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 신호 목록 트리
        self._signal_tree = QTreeWidget()
        self._signal_tree.setHeaderLabels(["채널", "신호명"])
        self._signal_tree.setMaximumWidth(200)
        self._signal_tree.itemDoubleClicked.connect(self._on_signal_tree_remove)
        splitter.addWidget(self._signal_tree)

        # 그래프 영역
        if self._pg_available:
            self._plot_widget = self._create_plot_widget()
        else:
            self._plot_widget = self._create_placeholder()
        splitter.addWidget(self._plot_widget)
        splitter.setStretchFactor(1, 4)

        layout.addWidget(splitter)

        # 비활성 오버레이 라벨
        self._inactive_lbl = QLabel(
            "DBC/LDF 파일을 로드하면 신호 그래프가 활성화됩니다."
        )
        self._inactive_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._inactive_lbl.setStyleSheet("color: gray; font-size: 13px; padding: 20px;")
        layout.addWidget(self._inactive_lbl)

    def _create_plot_widget(self):
        import pyqtgraph as pg
        pg.setConfigOptions(antialias=True, background="w", foreground="k")
        pw = pg.PlotWidget()
        pw.setLabel("bottom", "시간", "s")
        pw.addLegend()
        pw.showGrid(x=True, y=True, alpha=0.3)
        return pw

    def _create_placeholder(self) -> QLabel:
        lbl = QLabel("pyqtgraph 미설치\npip install pyqtgraph")
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("color: gray; font-size: 13px;")
        return lbl

    # ------------------------------------------------------------------
    # 활성화 / 비활성화
    # ------------------------------------------------------------------

    def enable(self, db_signals: dict[int, list[str]] | None = None) -> None:
        """
        DBC 로드 완료 후 MainWindow._on_db_loaded()에서 호출.
        db_signals = {ch_id: ["EngSpeed", "EngTemp", ...]}
        """
        self._enabled = True
        self._inactive_lbl.hide()
        if self._pg_available:
            self._plot_widget.show()
        logger.info("GraphDock 활성화")

    def disable(self) -> None:
        """DB 언로드 또는 채널 해제 시 호출."""
        self._enabled = False
        self._inactive_lbl.show()
        self.clear_all()

    # ------------------------------------------------------------------
    # 신호 추가 / 제거
    # ------------------------------------------------------------------

    def add_signal(self, ch_id: int, sig_name: str) -> None:
        """
        그래프에 신호 추가. Main Thread에서만 호출.
        중복 추가 무시.
        """
        if not self._pg_available or not self._enabled:
            return
        key = (ch_id, sig_name)
        if key in self._plot_items:
            return

        import pyqtgraph as pg
        color = CH_COLORS.get(ch_id, "#333333")
        pen   = pg.mkPen(color=color, width=2)
        curve = self._plot_widget.plot(
            [], [],
            name=f"CH{ch_id + 1}:{sig_name}",
            pen=pen,
        )
        self._plot_items[key] = curve

        # 트리에 항목 추가
        item = QTreeWidgetItem([f"CH{ch_id + 1}", sig_name])
        item.setData(0, Qt.ItemDataRole.UserRole, key)
        self._signal_tree.addTopLevelItem(item)

        self.signal_added.emit(ch_id, sig_name)
        logger.debug("GraphDock: 신호 추가 CH%d %s", ch_id, sig_name)

    def remove_signal(self, ch_id: int, sig_name: str) -> None:
        """신호 제거. Main Thread에서만 호출."""
        key = (ch_id, sig_name)
        curve = self._plot_items.pop(key, None)
        if curve is not None and self._pg_available:
            self._plot_widget.removeItem(curve)

        # 트리에서 항목 제거
        for i in range(self._signal_tree.topLevelItemCount()):
            item = self._signal_tree.topLevelItem(i)
            if item and item.data(0, Qt.ItemDataRole.UserRole) == key:
                self._signal_tree.takeTopLevelItem(i)
                break

        self.signal_removed.emit(ch_id, sig_name)

    def clear_all(self) -> None:
        """모든 신호 제거."""
        for key in list(self._plot_items.keys()):
            self.remove_signal(*key)
        self._signal_tree.clear()

    # ------------------------------------------------------------------
    # 업데이트 (QTimer 100ms 슬롯)
    # ------------------------------------------------------------------

    def update_plots(self) -> None:
        """
        MainWindow._flush_graph()에서 QTimer(100ms) 마다 호출.
        SignalBufferRegistry에서 데이터를 읽어 PlotDataItem.setData() 갱신.
        """
        if not self._pg_available or not self._enabled:
            return

        for (ch_id, sig_name), curve in self._plot_items.items():
            result = self._registry.get_or_create(ch_id, sig_name).get_view()
            if result is None:
                continue
            ts, vals = result

            if self._rolling_sec > 0 and len(ts) > 0:
                t_max  = ts[-1]
                t_min  = t_max - self._rolling_sec
                mask   = ts >= t_min
                ts     = ts[mask]
                vals   = vals[mask]

            curve.setData(x=ts, y=vals)

    # ------------------------------------------------------------------
    # 슬롯
    # ------------------------------------------------------------------

    def _on_window_changed(self, idx: int) -> None:
        self._rolling_sec = self._cb_window.itemData(idx)

    def _on_add_signal_clicked(self) -> None:
        """
        [+ 신호 추가] 버튼 — 신호 선택 팝업 다이얼로그 표시.
        등록된 신호가 없으면 안내 메시지 표시.
        """
        if not self._enabled:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                self, "안내",
                "DBC/LDF 파일을 먼저 로드한 후 신호를 추가할 수 있습니다.\n"
                "또는 Trace 뷰에서 우클릭 → 'Send to Graph'를 사용하세요."
            )
            return

        # 현재 SignalBufferRegistry에 등록된 신호 목록 수집
        available: list[tuple[int, str]] = sorted(self._registry._bufs.keys())
        if not available:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(
                self, "안내",
                "표시할 신호가 없습니다.\n"
                "Trace 뷰에서 메시지를 수신한 후 우클릭 → 'Send to Graph'를 사용하거나,\n"
                "CAN 수신 중에 다시 시도하세요."
            )
            return

        dlg = _SignalSelectDialog(available, self._plot_items, self)
        if dlg.exec():
            for ch_id, sig_name in dlg.selected_signals():
                self.add_signal(ch_id, sig_name)

    def _on_signal_tree_remove(self, item: QTreeWidgetItem, col: int) -> None:
        """더블클릭으로 신호 제거."""
        key = item.data(0, Qt.ItemDataRole.UserRole)
        if key:
            self.remove_signal(*key)

    # ------------------------------------------------------------------
    # 설정
    # ------------------------------------------------------------------

    def rolling_sec(self) -> int:
        return self._rolling_sec

    def set_rolling_sec(self, sec: int) -> None:
        self._rolling_sec = sec
        idx = self._cb_window.findData(sec)
        if idx >= 0:
            self._cb_window.setCurrentIndex(idx)


# ---------------------------------------------------------------------------
# 신호 선택 다이얼로그 (GraphDock 전용 내부 클래스)
# ---------------------------------------------------------------------------

class _SignalSelectDialog:
    """
    [+ 신호 추가] 버튼 클릭 시 표시되는 신호 선택 팝업.

    SignalBufferRegistry에 등록된 (ch_id, sig_name) 목록을 체크박스로 표시.
    이미 그래프에 추가된 신호는 체크 및 비활성화.

    사용법:
        dlg = _SignalSelectDialog(available, already_added, parent)
        if dlg.exec():
            for ch_id, sig_name in dlg.selected_signals():
                self.add_signal(ch_id, sig_name)
    """

    def __init__(
        self,
        available: list[tuple[int, str]],
        already_added: dict,
        parent=None,
    ) -> None:
        from PySide6.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QLabel,
            QListWidget, QListWidgetItem, QDialogButtonBox,
            QPushButton, QLineEdit,
        )
        from PySide6.QtCore import Qt

        self._dialog = QDialog(parent)
        self._dialog.setWindowTitle("신호 추가")
        self._dialog.setMinimumSize(380, 420)
        self._dialog.setModal(True)

        layout = QVBoxLayout(self._dialog)
        layout.setSpacing(8)

        # 안내 레이블
        lbl = QLabel(
            "그래프에 추가할 신호를 선택하세요.\n"
            "(이미 추가된 신호는 회색으로 표시)"
        )
        lbl.setStyleSheet("color: gray; font-size: 11px;")
        layout.addWidget(lbl)

        # 검색 필드
        self._search = QLineEdit()
        self._search.setPlaceholderText("신호명 검색...")
        self._search.setClearButtonEnabled(True)
        layout.addWidget(self._search)

        # 신호 목록 (체크박스)
        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        layout.addWidget(self._list)

        # 전체 선택 / 해제 버튼 행
        btn_row = QHBoxLayout()
        btn_all = QPushButton("전체 선택")
        btn_none = QPushButton("전체 해제")
        btn_all.setFixedWidth(80)
        btn_none.setFixedWidth(80)
        btn_all.clicked.connect(self._select_all)
        btn_none.clicked.connect(self._select_none)
        btn_row.addWidget(btn_all)
        btn_row.addWidget(btn_none)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # OK / Cancel
        bbox = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        bbox.accepted.connect(self._dialog.accept)
        bbox.rejected.connect(self._dialog.reject)
        layout.addWidget(bbox)

        # 항목 채우기
        self._items: list[tuple[QListWidgetItem, int, str]] = []
        for ch_id, sig_name in available:
            item = QListWidgetItem(f"CH{ch_id + 1}  {sig_name}")
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            already = (ch_id, sig_name) in already_added
            item.setCheckState(
                Qt.CheckState.Checked if already else Qt.CheckState.Unchecked
            )
            if already:
                item.setForeground(self._dialog.palette().color(
                    self._dialog.palette().ColorRole.Mid
                ))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self._list.addItem(item)
            self._items.append((item, ch_id, sig_name))

        # 검색 연결
        self._search.textChanged.connect(self._on_search)

    def _select_all(self) -> None:
        from PySide6.QtCore import Qt
        for item, ch_id, sig in self._items:
            if item.flags() & Qt.ItemFlag.ItemIsEnabled:
                item.setCheckState(Qt.CheckState.Checked)

    def _select_none(self) -> None:
        from PySide6.QtCore import Qt
        for item, ch_id, sig in self._items:
            if item.flags() & Qt.ItemFlag.ItemIsEnabled:
                item.setCheckState(Qt.CheckState.Unchecked)

    def _on_search(self, text: str) -> None:
        text = text.lower()
        for i in range(self._list.count()):
            item = self._list.item(i)
            item.setHidden(text not in item.text().lower())

    def exec(self) -> bool:
        return self._dialog.exec() == self._dialog.DialogCode.Accepted

    def selected_signals(self) -> list[tuple[int, str]]:
        """OK 클릭 후 체크된 신호 목록 반환."""
        from PySide6.QtCore import Qt
        result = []
        for item, ch_id, sig_name in self._items:
            if (item.checkState() == Qt.CheckState.Checked and
                    item.flags() & Qt.ItemFlag.ItemIsEnabled):
                result.append((ch_id, sig_name))
        return result
