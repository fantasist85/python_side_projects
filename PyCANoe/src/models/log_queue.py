# models/log_queue.py
import queue

from models.parsed_message import ParsedMessage


class LogQueue:
    """
    THREAD  : put()=Worker Thread (Dispatcher via QueuedConnection),
              get_queue()=LogWorker Thread
    DO NOT  : put() 내부에서 blocking 대기 — 통신 루프 차단 절대 금지.
    """

    MAX_SIZE = 50_000

    def __init__(self) -> None:
        self._q         = queue.Queue(maxsize=self.MAX_SIZE)
        self.drop_count = 0

    def put(self, msg: ParsedMessage) -> None:
        """Queue Full 시 drop_count 증가. blocking 절대 금지."""
        try:
            self._q.put_nowait(msg)
        except queue.Full:
            self.drop_count += 1

    def get_queue(self) -> queue.Queue:
        return self._q
