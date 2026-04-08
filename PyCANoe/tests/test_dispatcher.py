# tests/test_dispatcher.py
"""
MessageDispatcher — fan-out 단위 테스트.

검증 항목:
  - on_message() → MessageStore, LogQueue, SignalBufferRegistry, SimStateStore 분배
  - signals=None 일 때 Registry/SimStore 미업데이트
  - on_error() 호출 시 크래시 없음
"""
import pytest
from unittest.mock import MagicMock, patch
from models.parsed_message import ParsedMessage
from core.dispatcher import MessageDispatcher


# ── 헬퍼 ──────────────────────────────────────────────────────────────────
def make_msg(signals=None, msg_name=None, is_tx=False):
    return ParsedMessage(
        ch_id=0, timestamp=1.0, arb_id=0x1A0,
        dlc=8, data=b'\x00' * 8,
        signals=signals, msg_name=msg_name, is_tx=is_tx,
    )


@pytest.fixture
def mocks():
    store    = MagicMock()
    registry = MagicMock()
    log_q    = MagicMock()
    sim      = MagicMock()
    return store, registry, log_q, sim


@pytest.fixture
def dispatcher(qapp, mocks):
    store, registry, log_q, sim = mocks
    return MessageDispatcher(
        store=store, registry=registry, log_queue=log_q, sim_store=sim
    )


# ── fan-out 기본 동작 ─────────────────────────────────────────────────────
class TestDispatcherFanOut:
    def test_store_append_called(self, dispatcher, mocks):
        store, registry, log_q, sim = mocks
        msg = make_msg()
        dispatcher.on_message(msg)
        store.append.assert_called_once_with(msg)

    def test_log_queue_put_called(self, dispatcher, mocks):
        store, registry, log_q, sim = mocks
        msg = make_msg()
        dispatcher.on_message(msg)
        log_q.put.assert_called_once_with(msg)

    def test_registry_not_called_when_no_signals(self, dispatcher, mocks):
        store, registry, log_q, sim = mocks
        dispatcher.on_message(make_msg(signals=None))
        registry.append.assert_not_called()

    def test_sim_not_updated_when_no_signals(self, dispatcher, mocks):
        store, registry, log_q, sim = mocks
        dispatcher.on_message(make_msg(signals=None))
        sim.update.assert_not_called()

    def test_registry_called_for_each_signal(self, dispatcher, mocks):
        store, registry, log_q, sim = mocks
        msg = make_msg(signals={"EngSpeed": 1200.0, "VehSpeed": 40.0})
        dispatcher.on_message(msg)
        assert registry.append.call_count == 2

    def test_registry_called_with_correct_args(self, dispatcher, mocks):
        store, registry, log_q, sim = mocks
        msg = make_msg(signals={"EngSpeed": 1200.0})
        dispatcher.on_message(msg)
        registry.append.assert_called_once_with(0, "EngSpeed", 1.0, 1200.0)

    def test_sim_update_called_with_signals(self, dispatcher, mocks):
        store, registry, log_q, sim = mocks
        sigs = {"EngSpeed": 1200.0}
        msg = make_msg(signals=sigs)
        dispatcher.on_message(msg)
        sim.update.assert_called_once_with(0, sigs)

    def test_on_error_no_crash(self, dispatcher):
        dispatcher.on_error("CH1: 연결 오류")   # 크래시 없어야 함

    def test_multiple_messages_all_dispatched(self, dispatcher, mocks):
        store, registry, log_q, sim = mocks
        for i in range(10):
            dispatcher.on_message(make_msg())
        assert store.append.call_count == 10
        assert log_q.put.call_count == 10
