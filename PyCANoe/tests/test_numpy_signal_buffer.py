# tests/test_numpy_signal_buffer.py
import sys, os
import threading
import tracemalloc
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from models.numpy_signal_buffer import NumpySignalBuffer, SignalBufferRegistry


class TestNumpySignalBufferBasic:
    def test_disabled_by_default(self) -> None:
        buf = NumpySignalBuffer(max_points=100)
        buf.append(0.0, 1.0)
        assert buf.get_view() is None   # enabled=False → 저장 안 됨

    def test_enable_then_append(self) -> None:
        buf = NumpySignalBuffer(max_points=100)
        buf.enable()
        buf.append(1.0, 42.0)
        result = buf.get_view()
        assert result is not None
        ts, val = result
        assert ts[0] == pytest.approx(1.0)
        assert val[0] == pytest.approx(42.0)

    def test_ring_buffer_wraps(self) -> None:
        """max_points 초과 시 링 버퍼 순환. 최신 데이터 유지."""
        buf = NumpySignalBuffer(max_points=5)
        buf.enable()
        for i in range(8):
            buf.append(float(i), float(i * 10))
        ts, val = buf.get_view()
        assert len(ts) == 5
        # 가장 최신 5개 (3,4,5,6,7)가 들어 있어야 함
        assert float(ts[-1]) == pytest.approx(7.0)

    def test_get_view_returns_copy(self) -> None:
        """get_view() 반환값 수정이 내부 버퍼를 오염시키지 않아야 한다."""
        buf = NumpySignalBuffer(max_points=10)
        buf.enable()
        buf.append(0.0, 99.0)
        ts, val = buf.get_view()
        ts[0]  = -1.0   # 반환된 배열 수정
        val[0] = -1.0
        ts2, val2 = buf.get_view()
        assert ts2[0]  == pytest.approx(0.0)   # 내부 버퍼는 변경되지 않아야 함
        assert val2[0] == pytest.approx(99.0)


class TestNumpySignalBufferConcurrency:
    def test_concurrent_append_get_view(self) -> None:
        """2스레드 동시 접근 — 크래시 없어야 함."""
        buf = NumpySignalBuffer(max_points=1000)
        buf.enable()
        errors: list = []

        def appender():
            try:
                for i in range(500):
                    buf.append(float(i), float(i))
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                import time
                for _ in range(100):
                    buf.get_view()
                    time.sleep(0.001)
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=appender)
        t2 = threading.Thread(target=reader)
        t1.start(); t2.start()
        t1.join(); t2.join()
        assert not errors


class TestNumpySignalBufferMemory:
    def test_fixed_memory_usage(self) -> None:
        """tracemalloc으로 메모리 고정 확인 — append 반복해도 증가 없음."""
        buf = NumpySignalBuffer(max_points=5_000)
        buf.enable()

        tracemalloc.start()
        for i in range(5_000):
            buf.append(float(i), float(i))
        snapshot1 = tracemalloc.take_snapshot()

        # 같은 횟수 추가 반복 (링 버퍼 순환)
        for i in range(5_000):
            buf.append(float(i + 5_000), float(i))
        snapshot2 = tracemalloc.take_snapshot()
        tracemalloc.stop()

        stats1 = sum(s.size for s in snapshot1.statistics("lineno"))
        stats2 = sum(s.size for s in snapshot2.statistics("lineno"))
        # 2번째 5000건 추가 후 메모리가 1번째보다 크게 증가하면 안 됨 (5KB 허용)
        assert stats2 - stats1 < 5 * 1024, (
            f"메모리 증가 초과: {stats2 - stats1} bytes"
        )


class TestSignalBufferRegistry:
    def test_get_or_create(self) -> None:
        reg = SignalBufferRegistry()
        buf1 = reg.get_or_create(0, "Speed")
        buf2 = reg.get_or_create(0, "Speed")
        assert buf1 is buf2   # 동일 인스턴스 반환

    def test_no_auto_enable(self) -> None:
        """get_or_create() 내부에서 자동 enable 금지."""
        reg = SignalBufferRegistry()
        buf = reg.get_or_create(0, "Temp")
        assert buf.enabled is False

    def test_enable_all(self) -> None:
        reg = SignalBufferRegistry()
        reg.get_or_create(0, "Speed")
        reg.get_or_create(1, "Temp")
        reg.enable_all()
        assert reg.get_or_create(0, "Speed").enabled is True
        assert reg.get_or_create(1, "Temp").enabled  is True
