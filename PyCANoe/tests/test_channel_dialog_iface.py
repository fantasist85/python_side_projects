# tests/test_channel_dialog_iface.py
"""
ChannelDialog 인터페이스별 옵션 패널 테스트 (Rev 9.0).

검증 항목:
  - 인터페이스 선택 시 스택 페이지 전환 확인
  - virtual  : fd_box 비활성, bitrate 비활성 아님
  - socketcan: bitrate 콤보 비활성, fd_box 비활성
  - pcan     : pcan_channel 반영, fd_box 비활성
  - kvaser   : fd_box 활성 가능
  - vector   : app_name 반영, fd_box 활성 가능
  - _load_config → get_config() 왕복 검증 (interface별)
  - get_config() fd_mode: 미지원 인터페이스는 False 강제
"""
import pytest
from PySide6.QtWidgets import QStackedWidget
from app.dialogs.channel_dialog import ChannelDialog, _IFACE_PAGE
from core.channel_manager import ChannelConfig


# ── fixture ───────────────────────────────────────────────────────────────

@pytest.fixture
def dlg(qtbot):
    d = ChannelDialog(ch_id=0)
    qtbot.addWidget(d)
    return d


def _select_iface(dlg: ChannelDialog, iface: str) -> None:
    idx = dlg._cb_interface.findText(iface)
    assert idx >= 0, f"인터페이스 '{iface}'가 콤보박스에 없음"
    dlg._cb_interface.setCurrentIndex(idx)


# ── 스택 페이지 전환 ──────────────────────────────────────────────────────

class TestStackPageSwitch:
    @pytest.mark.parametrize("iface,expected_page", list(_IFACE_PAGE.items()))
    def test_page_index(self, dlg, iface, expected_page):
        """인터페이스 선택 시 스택이 올바른 페이지로 전환되어야 한다."""
        _select_iface(dlg, iface)
        assert dlg._stack.currentIndex() == expected_page


# ── FD 옵션 가시성 ────────────────────────────────────────────────────────

class TestFdVisibility:
    @pytest.mark.parametrize("iface", ["vector", "kvaser"])
    def test_fd_enabled_for_fd_interfaces(self, dlg, iface):
        _select_iface(dlg, iface)
        assert dlg._fd_box.isEnabled()

    @pytest.mark.parametrize("iface", ["virtual", "socketcan", "pcan"])
    def test_fd_disabled_for_non_fd_interfaces(self, dlg, iface):
        _select_iface(dlg, iface)
        assert not dlg._fd_box.isEnabled()

    @pytest.mark.parametrize("iface", ["virtual", "socketcan", "pcan"])
    def test_fd_unchecked_when_disabled(self, dlg, iface):
        """FD 미지원 인터페이스로 전환 시 체크 해제되어야 한다."""
        # 먼저 FD 지원 인터페이스에서 FD 활성화
        _select_iface(dlg, "vector")
        dlg._fd_box.setChecked(True)
        # 미지원으로 전환
        _select_iface(dlg, iface)
        assert not dlg._fd_box.isChecked()


# ── Bitrate 비활성 (SocketCAN) ────────────────────────────────────────────

class TestBitrateVisibility:
    def test_bitrate_disabled_for_socketcan(self, dlg):
        _select_iface(dlg, "socketcan")
        assert not dlg._cb_bitrate.isEnabled()

    @pytest.mark.parametrize("iface", ["virtual", "vector", "kvaser", "pcan"])
    def test_bitrate_enabled_for_others(self, dlg, iface):
        _select_iface(dlg, iface)
        assert dlg._cb_bitrate.isEnabled()


# ── get_config() fd_mode 강제 False ──────────────────────────────────────

class TestGetConfigFdMode:
    @pytest.mark.parametrize("iface", ["virtual", "socketcan", "pcan"])
    def test_fd_mode_false_for_non_fd_iface(self, dlg, iface):
        """FD 미지원 인터페이스는 get_config()에서 fd_mode=False 반환."""
        _select_iface(dlg, iface)
        cfg = dlg.get_config()
        assert cfg.fd_mode is False

    def test_fd_mode_true_for_vector(self, dlg):
        _select_iface(dlg, "vector")
        dlg._fd_box.setChecked(True)
        cfg = dlg.get_config()
        assert cfg.fd_mode is True

    def test_fd_mode_true_for_kvaser(self, dlg):
        _select_iface(dlg, "kvaser")
        dlg._fd_box.setChecked(True)
        cfg = dlg.get_config()
        assert cfg.fd_mode is True


# ── SocketCAN ifname 반영 ─────────────────────────────────────────────────

class TestSocketCANConfig:
    def test_socketcan_ifname_default(self, dlg):
        _select_iface(dlg, "socketcan")
        cfg = dlg.get_config()
        assert cfg.socketcan_ifname == "vcan0"

    def test_socketcan_ifname_custom(self, dlg):
        _select_iface(dlg, "socketcan")
        dlg._le_socketcan_ifname.setText("can1")
        cfg = dlg.get_config()
        assert cfg.socketcan_ifname == "can1"

    def test_socketcan_ifname_empty_fallback(self, dlg):
        """빈 문자열 입력 시 fallback으로 vcan0 반환."""
        _select_iface(dlg, "socketcan")
        dlg._le_socketcan_ifname.setText("")
        cfg = dlg.get_config()
        assert cfg.socketcan_ifname == "vcan0"


# ── PCAN 채널 반영 ────────────────────────────────────────────────────────

class TestPCANConfig:
    def test_pcan_default_channel(self, dlg):
        _select_iface(dlg, "pcan")
        cfg = dlg.get_config()
        assert cfg.pcan_channel == "PCAN_USBBUS1"

    def test_pcan_channel_change(self, dlg):
        _select_iface(dlg, "pcan")
        idx = dlg._cb_pcan_channel.findText("PCAN_USBBUS2")
        dlg._cb_pcan_channel.setCurrentIndex(idx)
        cfg = dlg.get_config()
        assert cfg.pcan_channel == "PCAN_USBBUS2"

    def test_pcan_bitrate_in_config(self, dlg):
        _select_iface(dlg, "pcan")
        cfg = dlg.get_config()
        assert cfg.bitrate == 500_000   # 기본값


# ── Vector app_name 반영 ─────────────────────────────────────────────────

class TestVectorConfig:
    def test_vector_default_app_name(self, dlg):
        _select_iface(dlg, "vector")
        cfg = dlg.get_config()
        assert cfg.app_name == "PyCANoe"

    def test_vector_custom_app_name(self, dlg):
        _select_iface(dlg, "vector")
        dlg._le_app_name.setText("MyApp")
        cfg = dlg.get_config()
        assert cfg.app_name == "MyApp"

    def test_vector_empty_app_name_fallback(self, dlg):
        _select_iface(dlg, "vector")
        dlg._le_app_name.setText("")
        cfg = dlg.get_config()
        assert cfg.app_name == "PyCANoe"

    def test_vector_channel_spin(self, dlg):
        _select_iface(dlg, "vector")
        dlg._spin_vector_channel.setValue(3)
        cfg = dlg.get_config()
        assert cfg.channel == 3


# ── _load_config → get_config() 왕복 검증 ────────────────────────────────

class TestRoundTrip:
    def _make_dlg(self, qtbot, cfg: ChannelConfig) -> ChannelDialog:
        d = ChannelDialog(ch_id=0, config=cfg)
        qtbot.addWidget(d)
        return d

    def test_roundtrip_virtual(self, qtbot):
        cfg = ChannelConfig(interface="virtual", channel=2, bitrate=250_000)
        d   = self._make_dlg(qtbot, cfg)
        out = d.get_config()
        assert out.interface == "virtual"
        assert out.channel   == 2
        assert out.bitrate   == 250_000

    def test_roundtrip_socketcan(self, qtbot):
        cfg = ChannelConfig(
            interface="socketcan", channel=0, bitrate=500_000,
            socketcan_ifname="can0"
        )
        d   = self._make_dlg(qtbot, cfg)
        out = d.get_config()
        assert out.interface        == "socketcan"
        assert out.socketcan_ifname == "can0"

    def test_roundtrip_pcan(self, qtbot):
        cfg = ChannelConfig(
            interface="pcan", channel=0, bitrate=1_000_000,
            pcan_channel="PCAN_USBBUS3"
        )
        d   = self._make_dlg(qtbot, cfg)
        out = d.get_config()
        assert out.interface    == "pcan"
        assert out.pcan_channel == "PCAN_USBBUS3"
        assert out.bitrate      == 1_000_000

    def test_roundtrip_kvaser_fd(self, qtbot):
        cfg = ChannelConfig(
            interface="kvaser", channel=1, bitrate=500_000,
            fd_mode=True, data_bitrate=4_000_000
        )
        d   = self._make_dlg(qtbot, cfg)
        out = d.get_config()
        assert out.interface    == "kvaser"
        assert out.channel      == 1
        assert out.fd_mode      is True
        assert out.data_bitrate == 4_000_000

    def test_roundtrip_vector(self, qtbot):
        cfg = ChannelConfig(
            interface="vector", channel=0, bitrate=500_000,
            app_name="CANoeTest", fd_mode=True, data_bitrate=2_000_000
        )
        d   = self._make_dlg(qtbot, cfg)
        out = d.get_config()
        assert out.interface == "vector"
        assert out.app_name  == "CANoeTest"
        assert out.fd_mode   is True
