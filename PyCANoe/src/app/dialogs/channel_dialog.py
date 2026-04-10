# app/dialogs/channel_dialog.py
"""
ChannelDialog — 채널 추가/편집 다이얼로그.

THREAD  : Main Thread 전용
INPUT   : 편집 시 기존 ChannelConfig (optional)
OUTPUT  : exec() → QDialog.Accepted 시 get_config() 로 ChannelConfig 반환
DO NOT  : Worker Thread에서 호출, blocking I/O

변경 이력:
  Rev 9.0  — 인터페이스별 전용 옵션 패널 추가
             (Vector / Kvaser / SocketCAN / PCAN / virtual)
  Rev 10.0 — M8: 버스 유형 선택 추가 (CAN / LIN).
             LIN 선택 시 전용 패널 (인터페이스·baud rate) 표시.
             FD / HW 필터 패널은 LIN 시 자동 숨김.
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
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from core.channel_manager import ChannelConfig

_INTERFACES = ["virtual", "vector", "kvaser", "socketcan", "pcan"]
_BITRATES   = [125_000, 250_000, 500_000, 1_000_000]
_DATA_RATES = [1_000_000, 2_000_000, 4_000_000, 8_000_000]

# LIN 지원 인터페이스 / baud rate
_LIN_INTERFACES = ["virtual_lin", "vector_lin"]
_LIN_BAUDS      = [9600, 19200, 38400]

# PCAN 표준 채널 목록 (PEAK 공식 채널 ID)
_PCAN_CHANNELS = [
    "PCAN_USBBUS1", "PCAN_USBBUS2", "PCAN_USBBUS3", "PCAN_USBBUS4",
    "PCAN_USBBUS5", "PCAN_USBBUS6", "PCAN_USBBUS7", "PCAN_USBBUS8",
    "PCAN_ISABUS1", "PCAN_ISABUS2",
    "PCAN_LANBUS1", "PCAN_LANBUS2",
]

# CAN 인터페이스 인덱스 → 스택 페이지 인덱스 매핑
_IFACE_PAGE: dict[str, int] = {
    "virtual":   0,
    "vector":    1,
    "kvaser":    2,
    "socketcan": 3,
    "pcan":      4,
}


class ChannelDialog(QDialog):
    """
    채널 연결 설정 다이얼로그.

    버스 유형 선택 (CAN / LIN):
      CAN → 기존 인터페이스 패널 (virtual / vector / kvaser / socketcan / pcan)
      LIN → LIN 전용 패널 (virtual_lin / vector_lin + baud rate)

    인터페이스 선택에 따라 전용 옵션 패널이 동적 전환된다.

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
        self.setMinimumWidth(420)
        self._build_ui()
        if config is not None:
            self._load_config(config)
        # 초기 버스 유형 / 인터페이스에 맞게 패널 갱신
        self._on_bus_type_changed(self._cb_bus_type.currentText())

    # ------------------------------------------------------------------
    # UI 구성
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # ── 버스 유형 (CAN / LIN) ─────────────────────────────────────
        bus_type_box = QGroupBox("버스 유형")
        bt_form = QFormLayout(bus_type_box)

        self._cb_bus_type = QComboBox()
        self._cb_bus_type.addItems(["CAN", "LIN"])
        self._cb_bus_type.currentTextChanged.connect(self._on_bus_type_changed)
        bt_form.addRow("버스 유형:", self._cb_bus_type)

        layout.addWidget(bus_type_box)

        # ── CAN 설정 패널 ─────────────────────────────────────────────
        self._can_panel = self._make_can_panel()
        layout.addWidget(self._can_panel)

        # ── LIN 설정 패널 (M8 신규) ────────────────────────────────────
        self._lin_panel = self._make_lin_panel()
        layout.addWidget(self._lin_panel)

        # ── CAN FD (vector / kvaser 에서만 활성) ───────────────────────
        fd_box = QGroupBox("CAN FD")
        fd_box.setCheckable(True)
        fd_box.setChecked(False)
        self._fd_box = fd_box
        fd_form = QFormLayout(fd_box)

        self._cb_data_rate = QComboBox()
        for dr in _DATA_RATES:
            self._cb_data_rate.addItem(f"{dr // 1_000_000} Mbps", dr)
        self._cb_data_rate.setCurrentIndex(1)   # 2Mbps 기본
        fd_form.addRow("Data Bitrate:", self._cb_data_rate)

        layout.addWidget(fd_box)

        # ── HW 필터 (CAN 전용) ─────────────────────────────────────────
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

        # ── 버튼 ──────────────────────────────────────────────────────
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    # ── CAN 패널 ──────────────────────────────────────────────────────

    def _make_can_panel(self) -> QWidget:
        panel = QWidget()
        vl = QVBoxLayout(panel)
        vl.setContentsMargins(0, 0, 0, 0)

        # 기본 설정 (인터페이스 + bitrate)
        basic_box = QGroupBox("CAN 기본 설정")
        form = QFormLayout(basic_box)

        self._cb_interface = QComboBox()
        self._cb_interface.addItems(_INTERFACES)
        self._cb_interface.currentTextChanged.connect(self._on_interface_changed)
        form.addRow("인터페이스:", self._cb_interface)

        self._cb_bitrate = QComboBox()
        for br in _BITRATES:
            self._cb_bitrate.addItem(f"{br // 1000} kbps", br)
        self._cb_bitrate.setCurrentIndex(2)   # 500k 기본
        form.addRow("Bitrate:", self._cb_bitrate)

        vl.addWidget(basic_box)

        # 인터페이스별 전용 옵션 (QStackedWidget)
        self._stack = QStackedWidget()
        self._stack.addWidget(self._make_page_virtual())    # 0: virtual
        self._stack.addWidget(self._make_page_vector())     # 1: vector
        self._stack.addWidget(self._make_page_kvaser())     # 2: kvaser
        self._stack.addWidget(self._make_page_socketcan())  # 3: socketcan
        self._stack.addWidget(self._make_page_pcan())       # 4: pcan
        vl.addWidget(self._stack)

        return panel

    # ── LIN 패널 (M8) ─────────────────────────────────────────────────

    def _make_lin_panel(self) -> QWidget:
        panel = QWidget()
        vl = QVBoxLayout(panel)
        vl.setContentsMargins(0, 0, 0, 0)

        lin_box = QGroupBox("LIN 설정")
        form = QFormLayout(lin_box)

        self._cb_lin_interface = QComboBox()
        self._cb_lin_interface.addItems(_LIN_INTERFACES)
        self._cb_lin_interface.setToolTip(
            "virtual_lin: CI/테스트용 가상 LIN 버스\n"
            "vector_lin:  Vector VN16xx 등 LIN H/W 채널"
        )
        form.addRow("인터페이스:", self._cb_lin_interface)

        self._cb_lin_baud = QComboBox()
        for baud in _LIN_BAUDS:
            self._cb_lin_baud.addItem(f"{baud} bps", baud)
        self._cb_lin_baud.setCurrentIndex(1)   # 19200 기본
        form.addRow("Baud Rate:", self._cb_lin_baud)

        self._spin_lin_channel = QSpinBox()
        self._spin_lin_channel.setRange(0, 15)
        self._spin_lin_channel.setToolTip("Vector LIN 채널 번호 (vector_lin 전용)")
        form.addRow("채널 번호:", self._spin_lin_channel)

        lbl = QLabel(
            "<small>⚠ LIN H/W: Vector VN16xx 등 LIN 채널 지원 장치 필요.<br>"
            "virtual_lin은 테스트·CI 환경에서 사용하세요.</small>"
        )
        lbl.setWordWrap(True)
        lbl.setTextFormat(Qt.TextFormat.RichText)
        form.addRow(lbl)

        vl.addWidget(lin_box)
        return panel

    # ── CAN 인터페이스별 페이지 빌더 ──────────────────────────────────

    def _make_page_virtual(self) -> QWidget:
        """virtual: 채널 번호만 (fd/app_name 미지원)."""
        page = QWidget()
        box  = QGroupBox("Virtual 옵션")
        form = QFormLayout(box)

        self._spin_virtual_channel = QSpinBox()
        self._spin_virtual_channel.setRange(0, 15)
        self._spin_virtual_channel.setToolTip("python-can virtual bus 채널 번호")
        form.addRow("채널 번호:", self._spin_virtual_channel)

        vl = QVBoxLayout(page)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.addWidget(box)
        return page

    def _make_page_vector(self) -> QWidget:
        """vector: App Name + 채널 번호."""
        page = QWidget()
        box  = QGroupBox("Vector 옵션")
        form = QFormLayout(box)

        self._spin_vector_channel = QSpinBox()
        self._spin_vector_channel.setRange(0, 15)
        self._spin_vector_channel.setToolTip("Vector XL 채널 인덱스 (VN16xx 등)")
        form.addRow("채널 번호:", self._spin_vector_channel)

        self._le_app_name = QLineEdit("PyCANoe")
        self._le_app_name.setToolTip("Vector CANalyzer 호환 앱 이름")
        form.addRow("App Name:", self._le_app_name)

        vl = QVBoxLayout(page)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.addWidget(box)
        return page

    def _make_page_kvaser(self) -> QWidget:
        """kvaser: 채널 번호."""
        page = QWidget()
        box  = QGroupBox("Kvaser 옵션")
        form = QFormLayout(box)

        self._spin_kvaser_channel = QSpinBox()
        self._spin_kvaser_channel.setRange(0, 15)
        self._spin_kvaser_channel.setToolTip("Kvaser 장치 채널 번호 (0-based)")
        form.addRow("채널 번호:", self._spin_kvaser_channel)

        lbl = QLabel(
            "<small>CAN FD 지원: 아래 CAN FD 옵션 체크 시 자동 활성화</small>"
        )
        lbl.setWordWrap(True)
        form.addRow(lbl)

        vl = QVBoxLayout(page)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.addWidget(box)
        return page

    def _make_page_socketcan(self) -> QWidget:
        """socketcan: 인터페이스명 (vcan0, can0 등)."""
        page = QWidget()
        box  = QGroupBox("SocketCAN 옵션")
        form = QFormLayout(box)

        self._le_socketcan_ifname = QLineEdit("vcan0")
        self._le_socketcan_ifname.setToolTip(
            "Linux 네트워크 인터페이스명\n"
            "예: vcan0 (가상), can0 (물리)\n"
            "확인: ip link show | grep can"
        )
        form.addRow("인터페이스명:", self._le_socketcan_ifname)

        lbl = QLabel(
            "<small>⚠ Linux 전용. Windows에서는 동작하지 않습니다.<br>"
            "가상 버스 생성: <code>sudo modprobe vcan &amp;&amp; "
            "sudo ip link add dev vcan0 type vcan &amp;&amp; "
            "sudo ip link set vcan0 up</code></small>"
        )
        lbl.setWordWrap(True)
        lbl.setTextFormat(Qt.TextFormat.RichText)
        form.addRow(lbl)

        vl = QVBoxLayout(page)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.addWidget(box)
        return page

    def _make_page_pcan(self) -> QWidget:
        """pcan: PEAK PCAN 채널 ID 선택."""
        page = QWidget()
        box  = QGroupBox("PCAN 옵션")
        form = QFormLayout(box)

        self._cb_pcan_channel = QComboBox()
        self._cb_pcan_channel.addItems(_PCAN_CHANNELS)
        self._cb_pcan_channel.setToolTip(
            "PEAK PCAN 채널 ID\n"
            "USB: PCAN_USBBUSn  |  LAN: PCAN_LANBUSn"
        )
        form.addRow("PCAN 채널:", self._cb_pcan_channel)

        lbl = QLabel(
            "<small>PEAK PCAN-USB / PCAN-LAN 장치 필요.<br>"
            "드라이버: <a href='https://www.peak-system.com/'>peak-system.com</a><br>"
            "pip 패키지: <code>python-can[pcan]</code></small>"
        )
        lbl.setWordWrap(True)
        lbl.setTextFormat(Qt.TextFormat.RichText)
        lbl.setOpenExternalLinks(True)
        form.addRow(lbl)

        vl = QVBoxLayout(page)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.addWidget(box)
        return page

    # ------------------------------------------------------------------
    # 버스 유형 / 인터페이스 전환 슬롯
    # ------------------------------------------------------------------

    def _on_bus_type_changed(self, bus_type: str) -> None:
        """버스 유형 선택 시 패널 전환 + FD/필터 가시성 제어."""
        is_lin = (bus_type == "LIN")
        self._can_panel.setVisible(not is_lin)
        self._lin_panel.setVisible(is_lin)
        # FD / HW 필터: LIN 미지원 → 숨김
        self._fd_box.setVisible(not is_lin)
        self._filt_box.setVisible(not is_lin)
        if is_lin:
            self._fd_box.setChecked(False)
            self._filt_box.setChecked(False)
        else:
            # CAN 복귀 시 인터페이스 기반 FD 활성 여부 재적용
            self._on_interface_changed(self._cb_interface.currentText())

    def _on_interface_changed(self, iface: str) -> None:
        """CAN 인터페이스 선택 시 스택 페이지 전환 + FD 옵션 가시성 제어."""
        page_idx = _IFACE_PAGE.get(iface, 0)
        self._stack.setCurrentIndex(page_idx)

        # FD 옵션: Vector / Kvaser 에서만 유효
        fd_supported = iface in ("vector", "kvaser")
        self._fd_box.setEnabled(fd_supported)
        if not fd_supported:
            self._fd_box.setChecked(False)

        # Bitrate: SocketCAN은 커널 설정으로 관리 → 비활성
        self._cb_bitrate.setEnabled(iface != "socketcan")

    # ------------------------------------------------------------------
    # 데이터 로드 / 추출
    # ------------------------------------------------------------------

    def _load_config(self, cfg: ChannelConfig) -> None:
        """기존 ChannelConfig로 폼 초기화."""
        # 버스 유형
        bt_idx = self._cb_bus_type.findText(cfg.bus_type.upper())
        if bt_idx >= 0:
            self._cb_bus_type.setCurrentIndex(bt_idx)

        if cfg.bus_type == "lin":
            # LIN 전용 필드
            lin_iface_idx = self._cb_lin_interface.findText(cfg.interface)
            if lin_iface_idx >= 0:
                self._cb_lin_interface.setCurrentIndex(lin_iface_idx)
            baud_idx = self._cb_lin_baud.findData(cfg.lin_baud)
            if baud_idx >= 0:
                self._cb_lin_baud.setCurrentIndex(baud_idx)
            self._spin_lin_channel.setValue(cfg.channel)
        else:
            # CAN 필드
            idx = self._cb_interface.findText(cfg.interface)
            if idx >= 0:
                self._cb_interface.setCurrentIndex(idx)

            br_idx = self._cb_bitrate.findData(cfg.bitrate)
            if br_idx >= 0:
                self._cb_bitrate.setCurrentIndex(br_idx)

            self._spin_virtual_channel.setValue(cfg.channel)
            self._spin_vector_channel.setValue(cfg.channel)
            self._spin_kvaser_channel.setValue(cfg.channel)
            self._le_app_name.setText(cfg.app_name)
            self._le_socketcan_ifname.setText(cfg.socketcan_ifname)

            pcan_idx = self._cb_pcan_channel.findText(cfg.pcan_channel)
            if pcan_idx >= 0:
                self._cb_pcan_channel.setCurrentIndex(pcan_idx)

            self._fd_box.setChecked(cfg.fd_mode)
            dr_idx = self._cb_data_rate.findData(cfg.data_bitrate)
            if dr_idx >= 0:
                self._cb_data_rate.setCurrentIndex(dr_idx)

            if cfg.hw_id_filter is not None:
                self._filt_box.setChecked(True)
                self._le_filter_id.setText(f"0x{cfg.hw_id_filter:03X}")
                if cfg.hw_id_mask is not None:
                    self._le_filter_mask.setText(f"0x{cfg.hw_id_mask:03X}")

    def get_config(self) -> ChannelConfig:
        """Accept 시 현재 입력값으로 ChannelConfig 반환."""
        bus_type = self._cb_bus_type.currentText().lower()  # "can" | "lin"

        if bus_type == "lin":
            return ChannelConfig(
                interface = self._cb_lin_interface.currentText(),
                channel   = self._spin_lin_channel.value(),
                bitrate   = self._cb_lin_baud.currentData(),  # lin_baud와 동일
                bus_type  = "lin",
                lin_baud  = self._cb_lin_baud.currentData(),
            )

        # CAN
        iface = self._cb_interface.currentText()

        if iface == "virtual":
            channel = self._spin_virtual_channel.value()
        elif iface == "vector":
            channel = self._spin_vector_channel.value()
        elif iface == "kvaser":
            channel = self._spin_kvaser_channel.value()
        else:
            channel = 0   # socketcan / pcan 은 channel int 미사용

        hw_id_filter = None
        hw_id_mask   = None
        if self._filt_box.isChecked():
            try:
                hw_id_filter = int(self._le_filter_id.text(), 16)
                hw_id_mask   = int(self._le_filter_mask.text(), 16)
            except ValueError:
                pass

        return ChannelConfig(
            interface        = iface,
            channel          = channel,
            bitrate          = self._cb_bitrate.currentData(),
            bus_type         = "can",
            fd_mode          = self._fd_box.isChecked() and self._fd_box.isEnabled(),
            data_bitrate     = self._cb_data_rate.currentData(),
            app_name         = self._le_app_name.text() or "PyCANoe",
            hw_id_filter     = hw_id_filter,
            hw_id_mask       = hw_id_mask,
            socketcan_ifname = self._le_socketcan_ifname.text() or "vcan0",
            pcan_channel     = self._cb_pcan_channel.currentText(),
        )
