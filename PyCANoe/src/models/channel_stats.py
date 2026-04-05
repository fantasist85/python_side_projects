# models/channel_stats.py
from dataclasses import dataclass


@dataclass
class ChannelStats:
    """
    THREAD  : 생성=Main Thread (CANWorker.get_stats() 반환값). 불변 스냅샷.
    INPUT   : rx_count, tx_count, error_count, rx_bits, tx_bits, bitrate
    OUTPUT  : bus_load_pct (property)
    DO NOT  : Worker Thread에서 직접 생성 또는 수정
    """
    rx_count:    int = 0
    tx_count:    int = 0
    error_count: int = 0
    rx_bits:     int = 0
    tx_bits:     int = 0
    bitrate:     int = 500_000

    @staticmethod
    def calc_frame_bits(dlc: int, is_fd: bool) -> int:
        """
        프레임 비트 수 계산 (bit stuffing 미포함).
        CAN 2.0B : 47 + dlc*8 bits
        CAN FD   : 67 + dlc*8 bits (Arbitration Phase 보수적 근사)
        TODO(v1.1): data_bitrate 분리 계산
        """
        return (67 if is_fd else 47) + dlc * 8

    @property
    def bus_load_pct(self) -> float:
        """버스 부하율 (%). bitrate <= 0 이면 0.0 반환. 최대 100.0 클램프."""
        if self.bitrate <= 0:
            return 0.0
        return min(100.0, (self.rx_bits + self.tx_bits) / self.bitrate * 100.0)
