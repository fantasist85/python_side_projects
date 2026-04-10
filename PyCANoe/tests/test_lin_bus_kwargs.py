# tests/test_lin_bus_kwargs.py
"""
M8 — build_bus_kwargs() LIN 분기 단위 테스트.

규칙:
  - build_bus_kwargs()는 CANWorker 외부 순수 함수 — H/W 없이 단독 테스트 가능
  - LIN 인터페이스: virtual_lin (가상), vector_lin (Vector H/W)
  - LIN은 fd 키 절대 포함 금지
"""
import pytest
from core.can_worker import build_bus_kwargs, _build_lin_bus_kwargs
from core.channel_manager import ChannelConfig


# ------------------------------------------------------------------
# 헬퍼
# ------------------------------------------------------------------

def lin_cfg(**kw) -> ChannelConfig:
    """LIN ChannelConfig 생성 헬퍼."""
    defaults = dict(interface="virtual_lin", channel=0, bitrate=19200,
                    bus_type="lin", lin_baud=19200)
    defaults.update(kw)
    return ChannelConfig(**defaults)


def can_cfg(**kw) -> ChannelConfig:
    """CAN ChannelConfig 생성 헬퍼."""
    defaults = dict(interface="virtual", channel=0, bitrate=500_000, bus_type="can")
    defaults.update(kw)
    return ChannelConfig(**defaults)


# ------------------------------------------------------------------
# 1. build_bus_kwargs() — bus_type 분기
# ------------------------------------------------------------------

class TestBuildBusKwargsDispatch:
    def test_can_type_routes_to_can(self):
        cfg = can_cfg(interface="virtual", channel=3)
        kw = build_bus_kwargs(cfg)
        assert kw["interface"] == "virtual"
        assert kw["channel"] == "3"

    def test_lin_type_routes_to_lin(self):
        cfg = lin_cfg(interface="virtual_lin", channel=0, lin_baud=19200)
        kw = build_bus_kwargs(cfg)
        # virtual_lin → python-can virtual 내부 사용
        assert kw["interface"] == "virtual"

    def test_default_bus_type_is_can(self):
        cfg = ChannelConfig(interface="virtual", channel=0, bitrate=500_000)
        assert cfg.bus_type == "can"

    def test_default_lin_baud_is_19200(self):
        cfg = ChannelConfig(interface="virtual_lin", channel=0, bitrate=19200,
                            bus_type="lin")
        assert cfg.lin_baud == 19200


# ------------------------------------------------------------------
# 2. _build_lin_bus_kwargs() — virtual_lin
# ------------------------------------------------------------------

class TestLinBusKwargsVirtual:
    def test_interface_becomes_virtual(self):
        cfg = lin_cfg(interface="virtual_lin", channel=2)
        kw = _build_lin_bus_kwargs(cfg)
        assert kw["interface"] == "virtual"

    def test_channel_is_string(self):
        cfg = lin_cfg(interface="virtual_lin", channel=5)
        kw = _build_lin_bus_kwargs(cfg)
        assert kw["channel"] == "5"

    def test_no_fd_key(self):
        cfg = lin_cfg(interface="virtual_lin")
        kw = _build_lin_bus_kwargs(cfg)
        assert "fd" not in kw

    def test_no_bitrate_key(self):
        """virtual_lin은 bitrate 불필요."""
        cfg = lin_cfg(interface="virtual_lin")
        kw = _build_lin_bus_kwargs(cfg)
        assert "bitrate" not in kw


# ------------------------------------------------------------------
# 3. _build_lin_bus_kwargs() — vector_lin
# ------------------------------------------------------------------

class TestLinBusKwargsVector:
    def test_interface_is_vector(self):
        cfg = lin_cfg(interface="vector_lin", channel=1, lin_baud=9600,
                      app_name="TestApp")
        kw = _build_lin_bus_kwargs(cfg)
        assert kw["interface"] == "vector"

    def test_channel_passed(self):
        cfg = lin_cfg(interface="vector_lin", channel=3)
        kw = _build_lin_bus_kwargs(cfg)
        assert kw["channel"] == 3

    def test_bitrate_uses_lin_baud(self):
        cfg = lin_cfg(interface="vector_lin", lin_baud=38400)
        kw = _build_lin_bus_kwargs(cfg)
        assert kw["bitrate"] == 38400

    def test_app_name_included(self):
        cfg = lin_cfg(interface="vector_lin", app_name="MyApp")
        kw = _build_lin_bus_kwargs(cfg)
        assert kw["app_name"] == "MyApp"

    def test_no_fd_key(self):
        cfg = lin_cfg(interface="vector_lin")
        kw = _build_lin_bus_kwargs(cfg)
        assert "fd" not in kw

    def test_no_data_bitrate_key(self):
        cfg = lin_cfg(interface="vector_lin")
        kw = _build_lin_bus_kwargs(cfg)
        assert "data_bitrate" not in kw


# ------------------------------------------------------------------
# 4. _build_lin_bus_kwargs() — 알 수 없는 인터페이스 fallback
# ------------------------------------------------------------------

class TestLinBusKwargsFallback:
    def test_unknown_iface_uses_lin_baud_as_bitrate(self):
        cfg = lin_cfg(interface="unknown_lin", channel=0, lin_baud=9600)
        kw = _build_lin_bus_kwargs(cfg)
        assert kw["bitrate"] == 9600

    def test_unknown_iface_passes_through(self):
        cfg = lin_cfg(interface="unknown_lin", channel=2)
        kw = _build_lin_bus_kwargs(cfg)
        assert kw["interface"] == "unknown_lin"
        assert kw["channel"] == 2


# ------------------------------------------------------------------
# 5. build_bus_kwargs() — CAN 기존 동작 회귀 없음
# ------------------------------------------------------------------

class TestCanBusKwargsRegression:
    def test_virtual_can(self):
        cfg = can_cfg(interface="virtual", channel=1)
        kw = build_bus_kwargs(cfg)
        assert kw == {"interface": "virtual", "channel": "1"}

    def test_socketcan(self):
        cfg = can_cfg(interface="socketcan", socketcan_ifname="can0")
        kw = build_bus_kwargs(cfg)
        assert kw == {"interface": "socketcan", "channel": "can0"}

    def test_pcan(self):
        cfg = can_cfg(interface="pcan", pcan_channel="PCAN_USBBUS2", bitrate=250_000)
        kw = build_bus_kwargs(cfg)
        assert kw["interface"] == "pcan"
        assert kw["channel"] == "PCAN_USBBUS2"
        assert kw["bitrate"] == 250_000

    def test_kvaser_no_fd(self):
        cfg = can_cfg(interface="kvaser", channel=0, bitrate=500_000, fd_mode=False)
        kw = build_bus_kwargs(cfg)
        assert "fd" not in kw

    def test_kvaser_with_fd(self):
        cfg = can_cfg(interface="kvaser", channel=0, bitrate=500_000,
                      fd_mode=True, data_bitrate=2_000_000)
        kw = build_bus_kwargs(cfg)
        assert kw["fd"] is True
        assert kw["data_bitrate"] == 2_000_000

    def test_vector_with_fd(self):
        cfg = can_cfg(interface="vector", channel=2, bitrate=500_000,
                      fd_mode=True, data_bitrate=4_000_000, app_name="Test")
        kw = build_bus_kwargs(cfg)
        assert kw["interface"] == "vector"
        assert kw["fd"] is True
        assert kw["data_bitrate"] == 4_000_000

    def test_unknown_iface_fallback(self):
        cfg = can_cfg(interface="mystery_iface", channel=0, bitrate=125_000)
        kw = build_bus_kwargs(cfg)
        assert kw["interface"] == "mystery_iface"
        assert kw["bitrate"] == 125_000


# ------------------------------------------------------------------
# 6. ChannelConfig LIN 필드 기본값
# ------------------------------------------------------------------

class TestChannelConfigLinDefaults:
    def test_bus_type_default_can(self):
        cfg = ChannelConfig(interface="virtual", channel=0, bitrate=500_000)
        assert cfg.bus_type == "can"

    def test_lin_baud_default(self):
        cfg = ChannelConfig(interface="virtual_lin", channel=0, bitrate=19200,
                            bus_type="lin")
        assert cfg.lin_baud == 19200

    def test_lin_baud_custom(self):
        cfg = ChannelConfig(interface="vector_lin", channel=1, bitrate=9600,
                            bus_type="lin", lin_baud=9600)
        assert cfg.lin_baud == 9600

    @pytest.mark.parametrize("baud", [9600, 19200, 38400])
    def test_valid_lin_bauds(self, baud):
        cfg = lin_cfg(lin_baud=baud)
        assert cfg.lin_baud == baud
