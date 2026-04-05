# models/sim_state_store.py
from threading import Lock


class SimStateStore:
    """
    THREAD  : update()=Main Thread (Dispatcher via QueuedConnection),
              get()=Main Thread (SimDock UI)
    DO NOT  : Worker Thread에서 직접 접근
    """

    def __init__(self) -> None:
        self._store: dict[int, dict[str, float]] = {}
        self._lock  = Lock()

    def update(self, ch_id: int, signals: dict) -> None:
        """Dispatcher에서 호출. 채널별 최신 신호 값 갱신."""
        with self._lock:
            if ch_id not in self._store:
                self._store[ch_id] = {}
            self._store[ch_id].update(signals)

    def get(self, ch_id: int, sig_name: str) -> float | None:
        with self._lock:
            return self._store.get(ch_id, {}).get(sig_name)

    def get_channel(self, ch_id: int) -> dict[str, float]:
        with self._lock:
            return dict(self._store.get(ch_id, {}))
