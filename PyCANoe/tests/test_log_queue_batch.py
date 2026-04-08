# tests/test_log_queue_batch.py
"""
LogQueue.get_batch() 추가 단위 테스트.
커버리지 목표: get_batch() 경로 (lines 37-49) 100%
"""
import sys
import os
import time
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from models.log_queue import LogQueue
from models.parsed_message import ParsedMessage


def _msg(ts: float = 1.0, arb_id: int = 0x100) -> ParsedMessage:
    return ParsedMessage(ch_id=0, timestamp=ts, arb_id=arb_id, dlc=4, data=b"\x01\x02\x03\x04")


class TestLogQueueGetBatch:
    def test_get_batch_empty_returns_empty_list(self) -> None:
        """큐가 비어있으면 빈 리스트 반환."""
        lq = LogQueue()
        result = lq.get_batch(timeout=0.01)
        assert result == []

    def test_get_batch_single_message(self) -> None:
        """메시지 1개 투입 → 1개 반환."""
        lq = LogQueue()
        lq.put(_msg(ts=1.0))
        result = lq.get_batch(timeout=0.1)
        assert len(result) == 1
        assert result[0].arb_id == 0x100

    def test_get_batch_multiple_messages(self) -> None:
        """여러 메시지 투입 → 한 번에 모두 드레인."""
        lq = LogQueue()
        for i in range(10):
            lq.put(_msg(ts=float(i), arb_id=0x100 + i))
        result = lq.get_batch(timeout=0.1)
        assert len(result) == 10

    def test_get_batch_drains_up_to_max(self) -> None:
        """MAX_DRAIN(5000) 한도 내에서 드레인."""
        lq = LogQueue()
        for i in range(100):
            lq.put(_msg(ts=float(i)))
        result = lq.get_batch(timeout=0.1)
        assert len(result) == 100

    def test_get_batch_does_not_block_beyond_timeout(self) -> None:
        """비어있을 때 timeout 이후 즉시 반환."""
        lq = LogQueue()
        start = time.monotonic()
        result = lq.get_batch(timeout=0.05)
        elapsed = time.monotonic() - start
        assert result == []
        assert elapsed < 0.2  # timeout 이내에 반환

    def test_get_batch_concurrent_put(self) -> None:
        """put(Worker) + get_batch(LogWorker) 동시 — RuntimeError 없어야 함."""
        lq = LogQueue()
        errors: list = []

        def producer():
            try:
                for i in range(200):
                    lq.put(_msg(ts=float(i)))
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        t = threading.Thread(target=producer)
        t.start()
        # consumer
        total = 0
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and total < 200:
            batch = lq.get_batch(timeout=0.05)
            total += len(batch)
        t.join()
        assert not errors

    def test_drop_count_increments_on_full(self) -> None:
        """큐 풀 시 drop_count 증가 확인."""
        lq = LogQueue()
        # maxsize까지 채우기
        for _ in range(LogQueue.MAX_SIZE):
            lq.put(_msg())
        assert lq.drop_count == 0
        # 초과 투입
        lq.put(_msg())
        assert lq.drop_count == 1
