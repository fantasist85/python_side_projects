# models/numpy_signal_buffer.py
from threading import Lock

import numpy as np


class NumpySignalBuffer:
    """
    THREAD  : append()=Worker Thread (Dispatcher via QueuedConnection),
              get_view()=Main Thread (QTimer 100ms 슬롯)
    INPUT   : timestamp: float, value: float
    OUTPUT  : get_view() → (np.ndarray, np.ndarray) | None (copy 보장)
    DO NOT  : list로 교체 (GC 부하 급증).
              copy() 생략 (UI 렌더링 중 데이터 오염).
              get_or_create() 내부에서 자동 enable 금지 (DBC 없는 상태에서 메모리 낭비).
              CANWorker/Dispatcher에서 enable() 직접 호출 금지 — Main Thread 전용.
    NOTE    : 링 버퍼 꽉 찬 경우 np.concatenate()로 2회 메모리 할당 발생.
              TODO(v1.1): double-buffering으로 할당 1회로 감소 검토.
    """

    def __init__(self, max_points: int = 5_000) -> None:
        self._cap        = max_points
        self._timestamps = np.zeros(max_points, dtype=np.float64)
        self._values     = np.zeros(max_points, dtype=np.float64)
        self._index      = 0     # 다음 쓰기 위치
        self._size       = 0     # 현재 저장된 데이터 수
        self.enabled     = False
        self._lock       = Lock()

    def enable(self) -> None:
        """Main Thread 전용. AsyncDbLoader.db_loaded → _on_db_loaded에서 호출."""
        self.enabled = True

    def disable(self) -> None:
        """Main Thread 전용."""
        self.enabled = False

    def append(self, timestamp: float, value: float) -> None:
        """enabled=False이면 즉시 반환 (DBC 없을 때 메모리 낭비 방지)."""
        if not self.enabled:
            return
        with self._lock:
            self._timestamps[self._index] = timestamp
            self._values[self._index]     = value
            self._index = (self._index + 1) % self._cap
            if self._size < self._cap:
                self._size += 1

    def get_view(self) -> tuple[np.ndarray, np.ndarray] | None:
        """
        UI 렌더링용 독립 복사본 반환.
        copy() 반드시 유지 — 생략 시 pyqtgraph setData() 중 버퍼 오염.
        """
        with self._lock:
            if self._size == 0:
                return None
            if self._size < self._cap:
                return (
                    self._timestamps[: self._size].copy(),
                    self._values[: self._size].copy(),
                )
            # 링 버퍼 순서 복원 (오래된 → 최신)
            i   = self._index
            ts  = np.concatenate((self._timestamps[i:], self._timestamps[:i]))
            val = np.concatenate((self._values[i:],     self._values[:i]))
            return ts.copy(), val.copy()


class SignalBufferRegistry:
    """
    THREAD  : append()=Worker Thread (Dispatcher),
              get_or_create()/enable_all()/disable_all()=Main Thread
    DO NOT  : get_or_create() 내부에서 enable() 호출 (DBC 없을 때 메모리 낭비).
    """

    def __init__(self) -> None:
        self._bufs: dict[tuple[int, str], NumpySignalBuffer] = {}

    def get_or_create(
        self, ch_id: int, sig_name: str, max_points: int = 5_000
    ) -> NumpySignalBuffer:
        key = (ch_id, sig_name)
        if key not in self._bufs:
            self._bufs[key] = NumpySignalBuffer(max_points)
        return self._bufs[key]

    def append(
        self, ch_id: int, sig_name: str, timestamp: float, value: float
    ) -> None:
        """Dispatcher에서 호출. 버퍼가 없으면 생성 후 append (enabled=False이므로 무시됨)."""
        self.get_or_create(ch_id, sig_name).append(timestamp, value)

    def enable_all(self) -> None:
        """
        Main Thread 전용.
        AsyncDbLoader.db_loaded → MainWindow._on_db_loaded() → 여기 호출.
        [SignalBuffer 활성화 트리거]
        """
        for buf in self._bufs.values():
            buf.enable()

    def disable_all(self) -> None:
        """Main Thread 전용. DB 언로드 또는 채널 해제 시."""
        for buf in self._bufs.values():
            buf.disable()
