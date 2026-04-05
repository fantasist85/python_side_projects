# widgets/trace_dock.py
from PySide6.QtWidgets import QWidget, QVBoxLayout, QTreeView, QHeaderView
from PySide6.QtCore import Qt

from models.trace_model import TraceModel


class TraceDock(QWidget):
    """
    THREAD  : Main Thread 전용
    INPUT   : TraceModel (QAbstractTableModel)
    DO NOT  : Worker Thread에서 UI 위젯 직접 접근
    """

    def __init__(self, model: TraceModel, parent=None) -> None:
        super().__init__(parent)

        self._view = QTreeView(self)
        self._view.setModel(model)

        # 고성능 렌더링 필수 설정 (명세서 8.2)
        self._view.setUniformRowHeights(True)    # 렌더링 성능 100배+ 향상
        self._view.setAnimated(False)            # 애니메이션 연산 제거
        self._view.setRootIsDecorated(False)
        self._view.setAlternatingRowColors(True)
        self._view.setSelectionBehavior(QTreeView.SelectionBehavior.SelectRows)

        # 컬럼 너비 초기 설정
        header = self._view.header()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._view)
        self.setLayout(layout)

    def scroll_to_bottom(self) -> None:
        self._view.scrollToBottom()
