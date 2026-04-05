# tests/test_log_queue.py
import sys, os
import threading
import time
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from models.log_queue import LogQueue
from models.parsed_message import ParsedMessage


def _msg(arb_id: int = 0x100) -> ParsedMessage:
    return ParsedMessage(ch_id=0, timestamp=0.0, arb_id=arb_id, dlc=8, data=b"\x00" * 8)


class TestLogQueueBasic:
    def test_put_and_get(self) -> None:
        lq = LogQueue()
        lq.put(_msg())
        q = lq.get_queue()
        msg = q.get_nowait()
        assert msg.arb_id == 0x100

    def test_drop_on_full(self) -> None:
        """Queue Full 시 drop_count 증가, blocking 없어야 함."""
        lq = LogQueue()
        # MAX_SIZE 채우기
        q = lq.get_queue()
        for _ in range(LogQueue.MAX_SIZE):
            q.put_nowait(_msg())

        start = time.monotonic()
        lq.put(_msg(0x200))   # 초과 → drop
        elapsed = time.monotonic() - start

        assert lq.drop_count == 1
        assert elapsed < 0.01, f"put()이 {elapsed:.3f}s 블로킹됨 — 절대 금지"

    def test_no_blocking_in_communication_loop(self) -> None:
        """통신 루프 속도로 put() 1000회 — 1초 이내."""
        lq = LogQueue()
        start = time.monotonic()
        for i in range(1000):
            lq.put(_msg(i))
        elapsed = time.monotonic() - start
        assert elapsed < 1.0
