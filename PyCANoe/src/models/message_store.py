# models/message_store.py
from collections import deque
from threading import Lock
from models.parsed_message import ParsedMessage


class MessageStore:
    """
    THREAD  : append()=Worker Thread (CANWorker Signal → Dispatcher),
              flush()=Main Thread ONLY (QTimer 50ms 슬롯)
    INPUT   : ParsedMessage
    OUTPUT  : flush() → list[ParsedMessage] (배치 스냅샷)
    DO NOT  : flush()를 Worker Thread에서 호출.
              _pending 리스트를 Lock 밖에서 접근.
    """
    MAX_ROWS = 100_000   # ~10 MB

    def __init__(self) -> None:
        self._buffer:  deque[ParsedMessage] = deque(maxlen=self.MAX_ROWS)
        self._pending: list[ParsedMessage]  = []
        self._lock     = Lock()
        self.drop_count: int = 0

    def append(self, msg: ParsedMessage) -> None:
        """Worker Thread에서 호출. Lock 보호."""
        with self._lock:
            self._pending.append(msg)

    def flush(self) -> list[ParsedMessage]:
        """
        QTimer(50ms) 슬롯 전용. 스냅샷 교체 후 overflow 계산.
        drop_count: deque auto-drop 직전 overflow 수를 flush() 시점에 정확히 산출.
        """
        with self._lock:
            batch, self._pending = self._pending, []

        overflow = max(0, len(self._buffer) + len(batch) - self.MAX_ROWS)
        if overflow > 0:
            self.drop_count += overflow

        self._buffer.extend(batch)
        return batch

    @property
    def size(self) -> int:
        """현재 _buffer 보관 건수."""
        return len(self._buffer)
