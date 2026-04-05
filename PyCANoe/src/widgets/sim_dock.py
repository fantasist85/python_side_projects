# widgets/sim_dock.py
"""
SimDock — Simulation (IG) Dock.

CANoe IG 스타일 주기 전송 UI.

THREAD  : Main Thread 전용
INPUT   : ChannelManager (SimWorker 접근), SimStateStore (현재 신호 값)
OUTPUT  : SimWorker.add_message() / remove_message() 호출
DO NOT  : SimWorker 직접 접근 (ChannelManager 통해 접근),
          Worker Thread에서 UI 위젯 접근

UI 구조 (명세서 8.1):
  QSplitter(Horizontal)
    ├── 좌: 메시지 목록 (QTreeWidget) + [추가] [제거] [시작] [정지]
    └── 우: 선택된 메시지 상세 설정 (Physical/Raw Hex 전환)
        ├── 채널 선택 QComboBox
        ├── Arbitration ID (hex)
        ├── 주기 ms
        ├── 데이터 입력 모드: Physical / Raw Hex
        └── 신호 슬라이더 (Physical 모드, DBC 있을 때)
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QMessageBox,
    QSlider,
    QScrollArea,
)

if TYPE_CHECKING:
    from core.channel_manager import ChannelManager
    from core.sim_worker import SimMessage
    from models.sim_state_store import SimStateStore

logger = logging.getLogger(__name__)


class SimDock(QWidget):
    """
    Simulation (IG) Dock — 주기 CAN 메시지 전송 관리.

    사용 예 (MainWindow):
        self._sim_dock = SimDock(self._channel_manager, self._sim_state, self)
    """

    # MainWindow가 tx_echo를 Dispatcher에 연결할 수 있도록 위임 Signal
    sim_worker_created = Signal(object)   # SimWorker 인스턴스

    def __init__(
        self,
        channel_manager: ChannelManager,
        sim_state: SimStateStore,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._cm        = channel_manager
        self._sim_state = sim_state
        self._build_ui()

    # ------------------------------------------------------------------
    # UI 구성
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── 좌: 메시지 목록 ──────────────────────────────────────────
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(4, 4, 4, 4)

        # 버튼 바
        btn_bar = QHBoxLayout()
        self._btn_add    = QPushButton("+ 추가")
        self._btn_remove = QPushButton("제거")
        self._btn_start  = QPushButton("▶ 시작")
        self._btn_stop   = QPushButton("■ 정지")
        self._btn_start.setStyleSheet("color: #1565C0; font-weight: bold;")
        self._btn_stop.setStyleSheet("color: #B71C1C; font-weight: bold;")

        self._btn_add.clicked.connect(self._on_add_clicked)
        self._btn_remove.clicked.connect(self._on_remove_clicked)
        self._btn_start.clicked.connect(self._on_start_clicked)
        self._btn_stop.clicked.connect(self._on_stop_clicked)

        btn_bar.addWidget(self._btn_add)
        btn_bar.addWidget(self._btn_remove)
        btn_bar.addStretch()
        btn_bar.addWidget(self._btn_start)
        btn_bar.addWidget(self._btn_stop)
        left_layout.addLayout(btn_bar)

        # 메시지 목록 트리
        self._msg_tree = QTreeWidget()
        self._msg_tree.setHeaderLabels(["CH", "ID (hex)", "주기(ms)", "상태"])
        self._msg_tree.setColumnWidth(0, 40)
        self._msg_tree.setColumnWidth(1, 80)
        self._msg_tree.setColumnWidth(2, 70)
        self._msg_tree.itemSelectionChanged.connect(self._on_selection_changed)
        left_layout.addWidget(self._msg_tree)

        left.setMinimumWidth(260)
        splitter.addWidget(left)

        # ── 우: 상세 설정 ─────────────────────────────────────────────
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        self._detail = _SimMessageDetail(self)
        self._detail.value_changed.connect(self._on_detail_changed)
        right_scroll.setWidget(self._detail)
        splitter.addWidget(right_scroll)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        layout.addWidget(splitter)

        # 초기 상태: 상세 비활성
        self._detail.setEnabled(False)

    # ------------------------------------------------------------------
    # 슬롯
    # ------------------------------------------------------------------

    def _on_add_clicked(self) -> None:
        """새 메시지 행 추가 (기본값으로)."""
        item = QTreeWidgetItem(["1", "100", "100", "정지"])
        item.setData(0, Qt.ItemDataRole.UserRole, {
            "ch_id":       0,
            "arb_id":      0x100,
            "interval_ms": 100.0,
            "data":        b"\x00" * 8,
            "running":     False,
        })
        self._msg_tree.addTopLevelItem(item)
        self._msg_tree.setCurrentItem(item)

    def _on_remove_clicked(self) -> None:
        item = self._msg_tree.currentItem()
        if item is None:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data.get("running"):
            self._stop_message(item)
        idx = self._msg_tree.indexOfTopLevelItem(item)
        self._msg_tree.takeTopLevelItem(idx)

    def _on_start_clicked(self) -> None:
        item = self._msg_tree.currentItem()
        if item is None:
            # 전체 시작
            for i in range(self._msg_tree.topLevelItemCount()):
                self._start_message(self._msg_tree.topLevelItem(i))
        else:
            self._start_message(item)

    def _on_stop_clicked(self) -> None:
        item = self._msg_tree.currentItem()
        if item is None:
            # 전체 정지
            for i in range(self._msg_tree.topLevelItemCount()):
                self._stop_message(self._msg_tree.topLevelItem(i))
        else:
            self._stop_message(item)

    def _on_selection_changed(self) -> None:
        item = self._msg_tree.currentItem()
        if item is None:
            self._detail.setEnabled(False)
            return
        self._detail.setEnabled(True)
        data = item.data(0, Qt.ItemDataRole.UserRole) or {}
        self._detail.load(data)

    def _on_detail_changed(self, data: dict) -> None:
        """상세 설정 변경 시 트리 항목 갱신."""
        item = self._msg_tree.currentItem()
        if item is None:
            return
        item.setData(0, Qt.ItemDataRole.UserRole, data)
        item.setText(0, str(data.get("ch_id", 0) + 1))
        item.setText(1, f"{data.get('arb_id', 0):X}")
        item.setText(2, str(int(data.get("interval_ms", 100))))

    # ------------------------------------------------------------------
    # 메시지 시작 / 정지
    # ------------------------------------------------------------------

    def _start_message(self, item: QTreeWidgetItem) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole) or {}
        ch_id = data.get("ch_id", 0)
        ctx   = self._cm.get(ch_id)
        if ctx is None:
            QMessageBox.warning(self, "경고", f"CH{ch_id + 1} 채널이 없습니다.")
            return

        from core.sim_worker import SimMessage, SimWorker

        # SimWorker 없으면 생성. tx_echo → Dispatcher 연결은 MainWindow에 위임.
        if ctx.sim_worker is None:
            sw = SimWorker(ch_id, ctx.worker)
            ctx.sim_worker = sw
            sw.start()
            # sim_worker_created Signal → MainWindow._on_sim_worker_created()
            # MainWindow에서 tx_echo를 Dispatcher.on_message에 QueuedConnection 연결
            self.sim_worker_created.emit(sw)

        sim_msg = SimMessage(
            arb_id      = data.get("arb_id", 0x100),
            data        = data.get("data", b"\x00" * 8),
            interval_ms = data.get("interval_ms", 100.0),
        )
        ctx.sim_worker.add_message(sim_msg)

        data["running"] = True
        item.setData(0, Qt.ItemDataRole.UserRole, data)
        item.setText(3, "▶ 실행")

    def _stop_message(self, item: QTreeWidgetItem) -> None:
        data  = item.data(0, Qt.ItemDataRole.UserRole) or {}
        ch_id = data.get("ch_id", 0)
        ctx   = self._cm.get(ch_id)

        if ctx and ctx.sim_worker:
            ctx.sim_worker.remove_message(data.get("arb_id", 0))

        data["running"] = False
        item.setData(0, Qt.ItemDataRole.UserRole, data)
        item.setText(3, "정지")

    # ------------------------------------------------------------------
    # 외부 인터페이스
    # ------------------------------------------------------------------

    def add_from_trace(self, ch_id: int, arb_id: int, dlc: int, data: bytes) -> None:
        """
        TraceDock 우클릭 "Send to Simulation"에서 호출.
        arb_id, data, dlc를 기본값으로 메시지 행 추가.
        """
        item = QTreeWidgetItem([
            str(ch_id + 1),
            f"{arb_id:X}",
            "100",
            "정지",
        ])
        item.setData(0, Qt.ItemDataRole.UserRole, {
            "ch_id":       ch_id,
            "arb_id":      arb_id,
            "interval_ms": 100.0,
            "data":        data[:dlc],
            "running":     False,
        })
        self._msg_tree.addTopLevelItem(item)
        self._msg_tree.setCurrentItem(item)

    def refresh_channels(self) -> None:
        """채널 추가/제거 후 상세 UI의 채널 목록 갱신."""
        self._detail.refresh_channels(self._cm)


# ---------------------------------------------------------------------------
# 상세 설정 위젯 (내부)
# ---------------------------------------------------------------------------

class _SimMessageDetail(QWidget):
    """
    선택된 SimMessage의 상세 설정 폼.
    Physical / Raw Hex 전환 지원.
    """
    from PySide6.QtCore import Signal as _Signal
    value_changed = _Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # ── 기본 설정 ─────────────────────────────────────────────────
        basic = QGroupBox("메시지 설정")
        form  = QFormLayout(basic)

        self._cb_ch = QComboBox()
        self._cb_ch.addItems([f"CH{i+1}" for i in range(4)])
        form.addRow("채널:", self._cb_ch)

        self._le_arb_id = QLineEdit("100")
        self._le_arb_id.setPlaceholderText("hex, 예: 1A0")
        form.addRow("Arbitration ID:", self._le_arb_id)

        self._spin_interval = QDoubleSpinBox()
        self._spin_interval.setRange(1.0, 60_000.0)
        self._spin_interval.setValue(100.0)
        self._spin_interval.setSuffix(" ms")
        form.addRow("주기:", self._spin_interval)

        layout.addWidget(basic)

        # ── 데이터 입력 모드 ──────────────────────────────────────────
        mode_box = QGroupBox("데이터 입력")
        mode_layout = QVBoxLayout(mode_box)

        mode_bar = QHBoxLayout()
        self._rb_raw = QRadioButton("Raw Hex")
        self._rb_raw.setChecked(True)
        self._rb_phys = QRadioButton("Physical (DBC)")
        mode_bar.addWidget(self._rb_raw)
        mode_bar.addWidget(self._rb_phys)
        mode_bar.addStretch()
        mode_layout.addLayout(mode_bar)

        # Raw Hex 입력
        self._le_raw = QLineEdit("00 00 00 00 00 00 00 00")
        self._le_raw.setPlaceholderText("예: 01 02 03 04 05 06 07 08")
        mode_layout.addWidget(self._le_raw)

        # Physical 입력 (슬라이더 영역 — DBC 로드 후 채워짐)
        self._phys_area = QWidget()
        self._phys_layout = QVBoxLayout(self._phys_area)
        self._phys_layout.addWidget(
            QLabel("DBC 로드 후 신호가 표시됩니다.")
        )
        self._phys_area.hide()
        mode_layout.addWidget(self._phys_area)

        self._rb_raw.toggled.connect(self._on_mode_toggled)
        layout.addWidget(mode_box)

        # 적용 버튼
        btn_apply = QPushButton("적용")
        btn_apply.clicked.connect(self._on_apply)
        layout.addWidget(btn_apply)

        layout.addStretch()

    # ------------------------------------------------------------------

    def _on_mode_toggled(self, raw_checked: bool) -> None:
        self._le_raw.setVisible(raw_checked)
        self._phys_area.setVisible(not raw_checked)

    def _on_apply(self) -> None:
        self.value_changed.emit(self._collect())

    def _collect(self) -> dict:
        try:
            arb_id = int(self._le_arb_id.text().strip(), 16)
        except ValueError:
            arb_id = 0x100

        raw_hex = self._le_raw.text().replace(" ", "")
        try:
            data = bytes.fromhex(raw_hex)
        except ValueError:
            data = b"\x00" * 8

        return {
            "ch_id":       self._cb_ch.currentIndex(),
            "arb_id":      arb_id,
            "interval_ms": self._spin_interval.value(),
            "data":        data,
            "running":     False,
        }

    def load(self, data: dict) -> None:
        ch_id = data.get("ch_id", 0)
        if 0 <= ch_id < self._cb_ch.count():
            self._cb_ch.setCurrentIndex(ch_id)
        self._le_arb_id.setText(f"{data.get('arb_id', 0x100):X}")
        self._spin_interval.setValue(data.get("interval_ms", 100.0))
        raw = data.get("data", b"\x00" * 8)
        self._le_raw.setText(raw.hex(" ").upper())

    def refresh_channels(self, cm) -> None:
        """채널 추가 후 콤보박스 갱신."""
        count = len(cm.all())
        self._cb_ch.clear()
        for i in range(max(count, 1)):
            self._cb_ch.addItem(f"CH{i+1}")
