# app/dialogs/channel_dialog.py
"""
ChannelDialog — 채널 추가/편집 다이얼로그.

THREAD  : Main Thread 전용
INPUT   : 편집 시 기존 ChannelConfig (optional)
OUTPUT  : exec() → QDialog.Accepted 시 get_config() 로 ChannelConfig 반환
DO NOT  : Worker Thread에서 호출, blocking I/O
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QCheckBox,
    QComboBox,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from core.channel_manager import ChannelConfig

_INTERFACES = ["virtual", "vector", "kvaser", "socketcan", "pcan"]
_BITRATES   = [125_000, 250_000, 500_000, 1_000_000]
_DATA_RATES = [1_000_000, 2_000_000, 4_000_000, 8_000_000]


class ChannelDialog(QDialog):
    """
    채널 연결 설정 다이얼로그.

    사용 예:
        dlg = ChannelDialog(parent=self)
        if dlg.exec() == QDialog.Accepted:
            config = dlg.get_config()
    """

    def __init__(
        self,
        ch_id: int,
        config: ChannelConfig | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._ch_id = ch_id
        self.setWindowTitle(f"CH{ch_id + 1} 채널 설정")
        self.setMinimumWidth(380)
        self._build_ui()
        if config is not None:
            self._load_config(config)

    # ------------------------------------------------------------------
    # UI 구성
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # ── 기본 설정 ─────────────────────────────────────────────────
        basic_box = QGroupBox("기본 설정")
        form = QFormLayout(basic_box)

        self._cb_interface = QComboBox()
        self._cb_interface.addItems(_INTERFACES)
        form.addRow("인터페이스:", self._cb_interface)

        self._spin_channel = QSpinBox()
        self._spin_channel.setRange(0, 15)
        form.addRow("채널 번호:", self._spin_channel)

        self._cb_bitrate = QComboBox()
        for br in _BITRATES:
            self._cb_bitrate.addItem(f"{br // 1000} kbps", br)
        self._cb_bitrate.setCurrentIndex(2)  # 500k 기본
        form.addRow("Bitrate:", self._cb_bitrate)

        layout.addWidget(basic_box)

        # ── CAN FD ────────────────────────────────────────────────────
        fd_box = QGroupBox("CAN FD")
        fd_box.setCheckable(True)
        fd_box.setChecked(False)
        self._fd_box = fd_box
        fd_form = QFormLayout(fd_box)

        self._cb_data_rate = QComboBox()
        for dr in _DATA_RATES:
            self._cb_data_rate.addItem(f"{dr // 1_000_000} Mbps", dr)
        self._cb_data_rate.setCurrentIndex(1)  # 2Mbps 기본
        fd_form.addRow("Data Bitrate:", self._cb_data_rate)

        layout.addWidget(fd_box)

        # ── HW 필터 ───────────────────────────────────────────────────
        filt_box = QGroupBox("HW ID 필터 (선택)")
        filt_box.setCheckable(True)
        filt_box.setChecked(False)
        self._filt_box = filt_box
        filt_form = QFormLayout(filt_box)

        self._le_filter_id   = QLineEdit("0x000")
        self._le_filter_mask = QLineEdit("0x7FF")
        filt_form.addRow("Filter ID (hex):", self._le_filter_id)
        filt_form.addRow("Filter Mask (hex):", self._le_filter_mask)

        layout.addWidget(filt_box)

        # ── 앱 이름 ───────────────────────────────────────────────────
        app_box = QGroupBox("Vector 옵션")
        app_form = QFormLayout(app_box)
        self._le_app_name = QLineEdit("PyCANoe")
        app_form.addRow("App Name:", self._le_app_name)
        layout.addWidget(app_box)

        # ── 버튼 ──────────────────────────────────────────────────────
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    # ------------------------------------------------------------------
    # 데이터 로드 / 추출
    # ------------------------------------------------------------------

    def _load_config(self, cfg: ChannelConfig) -> None:
        """기존 ChannelConfig로 폼 초기화."""
        idx = self._cb_interface.findText(cfg.interface)
        if idx >= 0:
            self._cb_interface.setCurrentIndex(idx)
        self._spin_channel.setValue(cfg.channel)

        br_idx = self._cb_bitrate.findData(cfg.bitrate)
        if br_idx >= 0:
            self._cb_bitrate.setCurrentIndex(br_idx)

        self._fd_box.setChecked(cfg.fd_mode)
        dr_idx = self._cb_data_rate.findData(cfg.data_bitrate)
        if dr_idx >= 0:
            self._cb_data_rate.setCurrentIndex(dr_idx)

        if cfg.hw_id_filter is not None:
            self._filt_box.setChecked(True)
            self._le_filter_id.setText(f"0x{cfg.hw_id_filter:03X}")
            if cfg.hw_id_mask is not None:
                self._le_filter_mask.setText(f"0x{cfg.hw_id_mask:03X}")

        self._le_app_name.setText(cfg.app_name)

    def get_config(self) -> ChannelConfig:
        """Accept 시 현재 입력값으로 ChannelConfig 반환."""
        hw_id_filter = None
        hw_id_mask   = None
        if self._filt_box.isChecked():
            try:
                hw_id_filter = int(self._le_filter_id.text(), 16)
                hw_id_mask   = int(self._le_filter_mask.text(), 16)
            except ValueError:
                pass

        return ChannelConfig(
            interface    = self._cb_interface.currentText(),
            channel      = self._spin_channel.value(),
            bitrate      = self._cb_bitrate.currentData(),
            fd_mode      = self._fd_box.isChecked(),
            data_bitrate = self._cb_data_rate.currentData(),
            app_name     = self._le_app_name.text() or "PyCANoe",
            hw_id_filter = hw_id_filter,
            hw_id_mask   = hw_id_mask,
        )
