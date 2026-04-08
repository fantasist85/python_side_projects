# tests/test_sim_state_store.py
"""
SimStateStore 단위 테스트.
커버리지 목표: 100% (현재 50%)
"""
import sys
import os
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from models.sim_state_store import SimStateStore


class TestSimStateStoreBasic:
    def test_update_and_get(self) -> None:
        store = SimStateStore()
        store.update(0, {"EngSpeed": 1200.0, "VehSpeed": 40.0})
        assert store.get(0, "EngSpeed") == 1200.0
        assert store.get(0, "VehSpeed") == 40.0

    def test_get_missing_channel_returns_none(self) -> None:
        store = SimStateStore()
        assert store.get(99, "SomeSignal") is None

    def test_get_missing_signal_returns_none(self) -> None:
        store = SimStateStore()
        store.update(0, {"EngSpeed": 100.0})
        assert store.get(0, "MissingSignal") is None

    def test_update_overwrites_existing(self) -> None:
        store = SimStateStore()
        store.update(0, {"EngSpeed": 1000.0})
        store.update(0, {"EngSpeed": 2000.0})
        assert store.get(0, "EngSpeed") == 2000.0

    def test_update_multiple_channels(self) -> None:
        store = SimStateStore()
        store.update(0, {"SigA": 1.0})
        store.update(1, {"SigB": 2.0})
        assert store.get(0, "SigA") == 1.0
        assert store.get(1, "SigB") == 2.0
        # 채널 간 간섭 없음
        assert store.get(0, "SigB") is None
        assert store.get(1, "SigA") is None

    def test_get_channel_returns_copy(self) -> None:
        store = SimStateStore()
        store.update(0, {"X": 5.0, "Y": 10.0})
        ch_data = store.get_channel(0)
        assert ch_data == {"X": 5.0, "Y": 10.0}
        # 반환된 dict 수정해도 내부 상태 변경 없음
        ch_data["X"] = 999.0
        assert store.get(0, "X") == 5.0

    def test_get_channel_missing_returns_empty(self) -> None:
        store = SimStateStore()
        result = store.get_channel(99)
        assert result == {}

    def test_update_merges_signals(self) -> None:
        """update()는 기존 신호를 유지하고 새 신호만 추가/갱신한다."""
        store = SimStateStore()
        store.update(0, {"A": 1.0})
        store.update(0, {"B": 2.0})
        # A도 남아있어야 함
        assert store.get(0, "A") == 1.0
        assert store.get(0, "B") == 2.0


class TestSimStateStoreConcurrency:
    def test_concurrent_update_get(self) -> None:
        """update()/get() 동시 접근 — RuntimeError 없어야 함."""
        store = SimStateStore()
        errors: list = []

        def writer():
            try:
                for i in range(500):
                    store.update(0, {"Sig": float(i)})
            except Exception as e:
                errors.append(e)

        def reader():
            try:
                for _ in range(500):
                    store.get(0, "Sig")
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=writer)
        t2 = threading.Thread(target=reader)
        t1.start(); t2.start()
        t1.join(); t2.join()
        assert not errors
