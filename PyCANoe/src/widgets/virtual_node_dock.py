# widgets/virtual_node_dock.py
"""
VirtualNodeDock — M7 Virtual Node Engine UI.

[UI 구조]
  QSplitter(Vertical)
  ├── 상단: 노드 관리 패널
  │     ├── [스크립트 로드] [채널 선택] [노드 시작] [노드 정지] [전체 정지]
  │     └── 노드 목록 QTreeWidget (NodeID / Script / CH / 상태)
  └── 하단: 로그 콘솔
        ├── 로그 출력 QTextEdit (read-only, 타임스탬프 + 노드ID)
        └── [로그 지우기]

[THREAD 규칙]
  - 이 위젯은 Main Thread 전용.
  - VirtualNodeEngine Signal → Slot으로만 수신.
"""
from __future__ import annotations

import datetime
import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtGui import QColor, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSplitter,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from core.virtual_node_engine import VirtualNodeEngine
    from core.channel_manager import ChannelManager

logger = logging.getLogger(__name__)


class VirtualNodeDock(QWidget):
    """
    THREAD  : Main Thread 전용
    INPUT   : VirtualNodeEngine Signal (log_emitted, node_started, node_stopped, node_error)
    OUTPUT  : VirtualNodeEngine.load_script() / unload_node() / unload_all() 호출
    """

    def __init__(
        self,
        vne: "VirtualNodeEngine",
        channel_manager: "ChannelManager",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._vne             = vne
        self._channel_manager = channel_manager
        # node_id → QTreeWidgetItem
        self._items: dict[int, QTreeWidgetItem] = {}

        self._setup_ui()
        self._connect_signals()

    # ------------------------------------------------------------------
    # UI 초기화
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(4, 4, 4, 4)

        splitter = QSplitter(Qt.Orientation.Vertical)
        root_layout.addWidget(splitter)

        # ── 상단: 노드 관리 ───────────────────────────────────────────
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)

        ctrl_layout = QHBoxLayout()
        top_layout.addLayout(ctrl_layout)

        ctrl_layout.addWidget(QLabel("CH:"))
        self._cb_channel = QComboBox()
        self._cb_channel.setFixedWidth(70)
        self._cb_channel.addItems(["CH1", "CH2", "CH3", "CH4"])
        ctrl_layout.addWidget(self._cb_channel)

        self._btn_load = QPushButton("📂 스크립트 로드")
        self._btn_load.setToolTip("Python 스크립트 파일(.py)을 선택하여 Virtual Node로 실행합니다.")
        ctrl_layout.addWidget(self._btn_load)

        self._btn_stop_selected = QPushButton("■ 선택 정지")
        self._btn_stop_selected.setEnabled(False)
        ctrl_layout.addWidget(self._btn_stop_selected)

        self._btn_stop_all = QPushButton("■ 전체 정지")
        ctrl_layout.addWidget(self._btn_stop_all)

        ctrl_layout.addStretch()

        # 노드 목록
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Node ID", "Script", "CH", "상태"])
        self._tree.setColumnWidth(0, 70)
        self._tree.setColumnWidth(1, 200)
        self._tree.setColumnWidth(2, 50)
        self._tree.setColumnWidth(3, 80)
        self._tree.setRootIsDecorated(False)
        self._tree.itemSelectionChanged.connect(self._on_selection_changed)
        top_layout.addWidget(self._tree)

        splitter.addWidget(top_widget)

        # ── 하단: 로그 콘솔 ───────────────────────────────────────────
        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)

        log_ctrl = QHBoxLayout()
        log_ctrl.addWidget(QLabel("📋 Virtual Node 로그"))
        log_ctrl.addStretch()
        self._btn_clear_log = QPushButton("지우기")
        self._btn_clear_log.setFixedWidth(60)
        log_ctrl.addWidget(self._btn_clear_log)
        bottom_layout.addLayout(log_ctrl)

        self._log_edit = QTextEdit()
        self._log_edit.setReadOnly(True)
        self._log_edit.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self._log_edit.setStyleSheet(
            "QTextEdit { font-family: Consolas, 'Courier New', monospace; font-size: 11px; }"
        )
        bottom_layout.addWidget(self._log_edit)

        splitter.addWidget(bottom_widget)
        splitter.setSizes([300, 200])

        # 버튼 연결
        self._btn_load.clicked.connect(self._on_load_clicked)
        self._btn_stop_selected.clicked.connect(self._on_stop_selected_clicked)
        self._btn_stop_all.clicked.connect(self._on_stop_all_clicked)
        self._btn_clear_log.clicked.connect(self._log_edit.clear)

    def _connect_signals(self) -> None:
        self._vne.log_emitted.connect(self._on_log_emitted)
        self._vne.node_error.connect(self._on_node_error)
        self._vne.node_started.connect(self._on_node_started)
        self._vne.node_stopped.connect(self._on_node_stopped)

    # ------------------------------------------------------------------
    # UI 이벤트
    # ------------------------------------------------------------------

    def _on_load_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Virtual Node 스크립트 선택", "",
            "Python Scripts (*.py);;All Files (*)"
        )
        if not path:
            return
        ch_id = self._cb_channel.currentIndex()   # 0-based
        try:
            self._vne.load_script(ch_id, path)
        except ValueError as exc:
            self._append_log(-1, f"[ERROR] {exc}", error=True)

    def _on_stop_selected_clicked(self) -> None:
        selected = self._tree.selectedItems()
        for item in selected:
            node_id = item.data(0, Qt.ItemDataRole.UserRole)
            if node_id is not None:
                self._vne.unload_node(node_id)

    def _on_stop_all_clicked(self) -> None:
        self._vne.unload_all()

    def _on_selection_changed(self) -> None:
        self._btn_stop_selected.setEnabled(bool(self._tree.selectedItems()))

    # ------------------------------------------------------------------
    # VirtualNodeEngine Signal 슬롯
    # ------------------------------------------------------------------

    @Slot(int, str)
    def _on_log_emitted(self, node_id: int, text: str) -> None:
        self._append_log(node_id, text, error=False)

    @Slot(int, str)
    def _on_node_error(self, node_id: int, msg: str) -> None:
        self._append_log(node_id, msg, error=True)
        # 노드 상태 업데이트
        item = self._items.get(node_id)
        if item:
            item.setText(3, "⚠ 오류")
            item.setForeground(3, QColor("#F44336"))

    @Slot(int, str)
    def _on_node_started(self, node_id: int, script_path: str) -> None:
        import os
        item = QTreeWidgetItem([
            str(node_id),
            os.path.basename(script_path),
            f"CH{self._cb_channel.currentIndex() + 1}",
            "▶ 실행 중",
        ])
        item.setData(0, Qt.ItemDataRole.UserRole, node_id)
        item.setToolTip(1, script_path)
        item.setForeground(3, QColor("#4CAF50"))
        self._tree.addTopLevelItem(item)
        self._items[node_id] = item
        self._append_log(node_id, f"[시작] {script_path}")

    @Slot(int)
    def _on_node_stopped(self, node_id: int) -> None:
        item = self._items.pop(node_id, None)
        if item:
            idx = self._tree.indexOfTopLevelItem(item)
            if idx >= 0:
                self._tree.takeTopLevelItem(idx)
        self._append_log(node_id, "[정지]")

    # ------------------------------------------------------------------
    # 로그 출력 (색상 구분)
    # ------------------------------------------------------------------

    def _append_log(self, node_id: int, text: str, error: bool = False) -> None:
        ts  = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
        nid = f"Node{node_id}" if node_id >= 0 else "Loader"
        line = f"[{ts}][{nid}] {text}"

        cursor = self._log_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        fmt = QTextCharFormat()
        if error:
            fmt.setForeground(QColor("#F44336"))
        else:
            fmt.setForeground(QColor("#B0BEC5"))

        cursor.setCharFormat(fmt)
        cursor.insertText(line + "\n")
        self._log_edit.setTextCursor(cursor)
        self._log_edit.ensureCursorVisible()
