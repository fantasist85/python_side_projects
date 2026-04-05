# tests/test_channel_stats.py
import sys, os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from models.channel_stats import ChannelStats


class TestCalcFrameBits:
    def test_can_20b(self) -> None:
        """CAN 2.0B: 47 + dlc*8."""
        assert ChannelStats.calc_frame_bits(dlc=8, is_fd=False) == 47 + 64

    def test_can_fd(self) -> None:
        """CAN FD: 67 + dlc*8."""
        assert ChannelStats.calc_frame_bits(dlc=8, is_fd=True) == 67 + 64

    def test_dlc_zero(self) -> None:
        assert ChannelStats.calc_frame_bits(dlc=0, is_fd=False) == 47
        assert ChannelStats.calc_frame_bits(dlc=0, is_fd=True)  == 67


class TestBusLoadPct:
    def test_normal_load(self) -> None:
        """rx_bits + tx_bits / bitrate * 100 클램프 없음."""
        s = ChannelStats(rx_bits=50_000, tx_bits=0, bitrate=500_000)
        assert abs(s.bus_load_pct - 10.0) < 0.01

    def test_clamp_100_pct(self) -> None:
        """100% 초과 시 100.0으로 클램프."""
        s = ChannelStats(rx_bits=600_000, tx_bits=0, bitrate=500_000)
        assert s.bus_load_pct == 100.0

    def test_bitrate_zero_returns_zero(self) -> None:
        """bitrate <= 0 이면 0.0 반환, ZeroDivisionError 없음."""
        s = ChannelStats(rx_bits=1000, bitrate=0)
        assert s.bus_load_pct == 0.0

    def test_rx_tx_combined(self) -> None:
        """rx_bits + tx_bits 합산."""
        s = ChannelStats(rx_bits=100_000, tx_bits=150_000, bitrate=500_000)
        assert abs(s.bus_load_pct - 50.0) < 0.01
