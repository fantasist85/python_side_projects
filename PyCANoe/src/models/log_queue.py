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

    def get_batch(self, timeout: float = 0.05) -> list:
        """
        큐에서 가능한 만큼 메시지를 꺼내 리스트로 반환.
        첫 메시지는 timeout 동안 blocking 대기.
        이후에는 non-blocking으로 최대 MAX_DRAIN 건까지 드레인.
        메시지가 없으면 빈 리스트 반환.
        """
        MAX_DRAIN = 5_000
        msgs: list = []
        try:
            msgs.append(self._q.get(timeout=timeout))
        except queue.Empty:
            return msgs
        # 추가 non-blocking 드레인
        for _ in range(MAX_DRAIN - 1):
            try:
                msgs.append(self._q.get_nowait())
            except queue.Empty:
                break
        return msgs
