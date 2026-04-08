# tests/test_build_bus_kwargs.py
"""
build_bus_kwargs() 단위 테스트.

검증 항목:
  - virtual  : interface=virtual, channel=str
  - socketcan: interface=socketcan, channel=ifname
  - pcan     : interface=pcan, channel=pcan_channel, bitrate 포함
  - kvaser   : interface=kvaser, channel=int, bitrate 포함
  - kvaser FD: fd=True, data_bitrate 포함
  - vector   : interface=vector, app_name 포함
  - vector FD: fd=True, data_bitrate 포함
  - unknown  : fallback — interface/channel/bitrate 포함
  - fd_mode 미지원 인터페이스(virtual/socketcan/pcan)에 fd 키 없음
"""
import pytest
from core.channel_manager import ChannelConfig
from core.can_worker import build_bus_kwargs


def _cfg(**kwargs) -> ChannelConfig:
    """테스트용 ChannelConfig 생성 헬퍼."""
    defaults = dict(
        interface="virtual",
        channel=0,
        bitrate=500_000,
    )
    defaults.update(kwargs)
    return ChannelConfig(**defaults)


# ── virtual ───────────────────────────────────────────────────────────────

class TestVirtual:
    def test_interface_key(self):
        kw = build_bus_kwargs(_cfg(interface="virtual", channel=0))
        assert kw["interface"] == "virtual"

    def test_channel_is_string(self):
        """python-can virtual bus는 channel을 문자열로 받는다."""
        kw = build_bus_kwargs(_cfg(interface="virtual", channel=2))
        assert kw["channel"] == "2"

    def test_no_fd_key(self):
        """virtual은 FD 파라미터를 지원하지 않는다."""
        kw = build_bus_kwargs(_cfg(interface="virtual", fd_mode=True))
        assert "fd" not in kw

    def test_no_app_name_key(self):
        kw = build_bus_kwargs(_cfg(interface="virtual"))
        assert "app_name" not in kw

    def test_no_bitrate_key(self):
        """virtual은 bitrate 파라미터를 받지 않는다."""
        kw = build_bus_kwargs(_cfg(interface="virtual"))
        assert "bitrate" not in kw


# ── socketcan ─────────────────────────────────────────────────────────────

class TestSocketCAN:
    def test_interface_key(self):
        kw = build_bus_kwargs(_cfg(interface="socketcan", socketcan_ifname="vcan0"))
        assert kw["interface"] == "socketcan"

    def test_channel_is_ifname(self):
        kw = build_bus_kwargs(_cfg(interface="socketcan", socketcan_ifname="can1"))
        assert kw["channel"] == "can1"

    def test_no_fd_key(self):
        kw = build_bus_kwargs(_cfg(interface="socketcan", fd_mode=True))
        assert "fd" not in kw

    def test_no_bitrate_key(self):
        """socketcan bitrate는 커널이 관리 — python-can에 전달하지 않는다."""
        kw = build_bus_kwargs(_cfg(interface="socketcan"))
        assert "bitrate" not in kw

    def test_default_ifname_vcan0(self):
        kw = build_bus_kwargs(_cfg(interface="socketcan"))
        assert kw["channel"] == "vcan0"


# ── pcan ──────────────────────────────────────────────────────────────────

class TestPCAN:
    def test_interface_key(self):
        kw = build_bus_kwargs(_cfg(interface="pcan"))
        assert kw["interface"] == "pcan"

    def test_channel_is_pcan_channel(self):
        kw = build_bus_kwargs(_cfg(interface="pcan", pcan_channel="PCAN_USBBUS2"))
        assert kw["channel"] == "PCAN_USBBUS2"

    def test_bitrate_included(self):
        kw = build_bus_kwargs(_cfg(interface="pcan", bitrate=250_000))
        assert kw["bitrate"] == 250_000

    def test_no_fd_key(self):
        """PCAN python-can 백엔드는 fd 파라미터를 별도 처리하지 않는다."""
        kw = build_bus_kwargs(_cfg(interface="pcan", fd_mode=True))
        assert "fd" not in kw

    def test_default_pcan_channel(self):
        kw = build_bus_kwargs(_cfg(interface="pcan"))
        assert kw["channel"] == "PCAN_USBBUS1"


# ── kvaser ────────────────────────────────────────────────────────────────

class TestKvaser:
    def test_interface_key(self):
        kw = build_bus_kwargs(_cfg(interface="kvaser"))
        assert kw["interface"] == "kvaser"

    def test_channel_is_int(self):
        kw = build_bus_kwargs(_cfg(interface="kvaser", channel=1))
        assert kw["channel"] == 1

    def test_bitrate_included(self):
        kw = build_bus_kwargs(_cfg(interface="kvaser", bitrate=1_000_000))
        assert kw["bitrate"] == 1_000_000

    def test_no_fd_when_fd_false(self):
        kw = build_bus_kwargs(_cfg(interface="kvaser", fd_mode=False))
        assert "fd" not in kw

    def test_fd_true_includes_fd_key(self):
        kw = build_bus_kwargs(_cfg(interface="kvaser", fd_mode=True))
        assert kw.get("fd") is True

    def test_fd_true_includes_data_bitrate(self):
        kw = build_bus_kwargs(_cfg(
            interface="kvaser", fd_mode=True, data_bitrate=4_000_000
        ))
        assert kw["data_bitrate"] == 4_000_000

    def test_no_app_name_key(self):
        kw = build_bus_kwargs(_cfg(interface="kvaser"))
        assert "app_name" not in kw


# ── vector ────────────────────────────────────────────────────────────────

class TestVector:
    def test_interface_key(self):
        kw = build_bus_kwargs(_cfg(interface="vector"))
        assert kw["interface"] == "vector"

    def test_channel_is_int(self):
        kw = build_bus_kwargs(_cfg(interface="vector", channel=3))
        assert kw["channel"] == 3

    def test_bitrate_included(self):
        kw = build_bus_kwargs(_cfg(interface="vector", bitrate=500_000))
        assert kw["bitrate"] == 500_000

    def test_app_name_included(self):
        kw = build_bus_kwargs(_cfg(interface="vector", app_name="TestApp"))
        assert kw["app_name"] == "TestApp"

    def test_no_fd_when_fd_false(self):
        kw = build_bus_kwargs(_cfg(interface="vector", fd_mode=False))
        assert "fd" not in kw

    def test_fd_true_includes_fd_key(self):
        kw = build_bus_kwargs(_cfg(interface="vector", fd_mode=True))
        assert kw.get("fd") is True

    def test_fd_true_includes_data_bitrate(self):
        kw = build_bus_kwargs(_cfg(
            interface="vector", fd_mode=True, data_bitrate=8_000_000
        ))
        assert kw["data_bitrate"] == 8_000_000


# ── unknown fallback ──────────────────────────────────────────────────────

class TestUnknownInterface:
    def test_interface_passthrough(self):
        kw = build_bus_kwargs(_cfg(interface="ixxat", channel=0, bitrate=500_000))
        assert kw["interface"] == "ixxat"

    def test_channel_passthrough(self):
        kw = build_bus_kwargs(_cfg(interface="ixxat", channel=2))
        assert kw["channel"] == 2

    def test_bitrate_passthrough(self):
        kw = build_bus_kwargs(_cfg(interface="ixxat", bitrate=250_000))
        assert kw["bitrate"] == 250_000
