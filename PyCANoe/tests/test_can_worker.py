# tests/test_can_worker.py
import sys, os
import time
import threading
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication
from core.can_worker import CANWorker, MAX_RETRY, RETRY_BACKOFF_SEC
from core.channel_manager import ChannelConfig
from core.db_parser import DbParser
from models.channel_stats import ChannelStats

_app = QApplication.instance() or QApplication([])


def _make_worker(ch_id: int = 0) -> CANWorker:
    cfg = ChannelConfig(interface="virtual", channel=ch_id, bitrate=500_000)
    return CANWorker(ch_id=ch_id, config=cfg, db=DbParser())


class TestCANWorkerStats:
    def test_get_stats_returns_channel_stats(self) -> None:
        w = _make_worker()
        s = w.get_stats()
        assert isinstance(s, ChannelStats)

    def test_get_stats_resets_counters(self) -> None:
        w = _make_worker()
        # 내부 카운터 직접 조작
        with w._stats_lock:
            w._rx_count = 100
            w._rx_bits  = 5000
        s = w.get_stats()
        assert s.rx_count == 100
        # 리셋 확인
        s2 = w.get_stats()
        assert s2.rx_count == 0

    def test_increment_tx(self) -> None:
        w = _make_worker()
        w.increment_tx()
        w.increment_tx()
        s = w.get_stats()
        assert s.tx_count == 2


class TestCANWorkerParserLock:
    def test_update_db_concurrent_with_stats(self) -> None:
        """update_db() + get_stats() 동시 호출 — 데드락/크래시 없어야 함."""
        w   = _make_worker()
        db2 = DbParser()
        errors: list = []

        def updater():
            try:
                for _ in range(200):
                    w.update_db(db2)
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(200):
                    w.get_stats()
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=updater)
        t2 = threading.Thread(target=reader)
        t1.start(); t2.start()
        t1.join(); t2.join()
        assert not errors


class TestCANWorkerVirtualRun:
    def test_start_stop_virtual(self) -> None:
        """virtual 인터페이스로 start() → stop() — 크래시 없어야 함."""
        w = _make_worker()
        w.start()
        time.sleep(0.2)
        w.stop()
        assert not w.isRunning()
