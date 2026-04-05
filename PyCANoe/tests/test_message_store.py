# tests/test_message_store.py
import sys, os
import threading
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from models.message_store import MessageStore
from models.parsed_message import ParsedMessage


def _make_msg(arb_id: int = 0x100) -> ParsedMessage:
    return ParsedMessage(ch_id=0, timestamp=0.0, arb_id=arb_id, dlc=8, data=b"\x00" * 8)


class TestMessageStoreBasic:
    def test_append_and_flush(self) -> None:
        store = MessageStore()
        store.append(_make_msg(0x100))
        store.append(_make_msg(0x200))
        batch = store.flush()
        assert len(batch) == 2
        assert batch[0].arb_id == 0x100

    def test_flush_clears_pending(self) -> None:
        store = MessageStore()
        store.append(_make_msg())
        store.flush()
        assert store.flush() == []

    def test_drop_count_on_overflow(self) -> None:
        """MAX_ROWS 초과 시 drop_count 정확히 산출."""
        store = MessageStore()
        # MAX_ROWS만큼 미리 채우기
        for _ in range(store.MAX_ROWS):
            store._buffer.append(_make_msg())  # 직접 채움 (테스트 전용)
        # 추가 10건 → 10건 드롭
        for _ in range(10):
            store.append(_make_msg())
        store.flush()
        assert store.drop_count == 10


class TestMessageStoreConcurrency:
    def test_concurrent_append_flush(self) -> None:
        """2스레드 동시 append + Main Thread flush — 크래시/데드락 없어야 함."""
        store = MessageStore()
        errors: list = []

        def worker():
            try:
                for i in range(500):
                    store.append(_make_msg(i))
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start(); t2.start()

        total = 0
        import time
        deadline = time.time() + 3.0
        while (t1.is_alive() or t2.is_alive()) and time.time() < deadline:
            total += len(store.flush())
            time.sleep(0.005)
        total += len(store.flush())

        t1.join(); t2.join()
        assert not errors, f"Worker 예외 발생: {errors}"
        assert total == 1000
