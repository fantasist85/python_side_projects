# tests/test_sim_worker_echo.py
"""
SimWorker tx_echo Signal 테스트.

검증 항목:
  - _send_due_messages() 실행 시 tx_echo Signal emit
  - echo ParsedMessage의 is_tx=True, ch_id, arb_id, data 정확성
  - 전송 실패 시에도 크래시 없음 (CANWorker.send() 예외 처리)
"""
import time
import pytest
from unittest.mock import MagicMock, patch
from core.sim_worker import SimMessage, SimWorker
from models.parsed_message import ParsedMessage


@pytest.fixture
def mock_bus_sender():
    sender = MagicMock()
    sender.send = MagicMock()
    sender.increment_tx = MagicMock()
    return sender


@pytest.fixture
def worker(qapp, mock_bus_sender):
    sw = SimWorker(ch_id=0, bus_sender=mock_bus_sender)
    return sw


# ── tx_echo 발생 ──────────────────────────────────────────────────────────
class TestSimWorkerEcho:
    def test_tx_echo_emitted(self, worker, mock_bus_sender, qtbot):
        sm = SimMessage(arb_id=0x1A0, data=b'\x01\x02', interval_ms=100.0)
        sm.next_send_at = time.perf_counter() - 1.0   # 즉시 전송 조건

        received: list[ParsedMessage] = []
        worker.tx_echo.connect(received.append)

        with qtbot.waitSignal(worker.tx_echo, timeout=500):
            now = time.perf_counter()
            worker._send_due_messages(now, [sm])

        assert len(received) == 1

    def test_echo_is_tx_true(self, worker, mock_bus_sender, qtbot):
        sm = SimMessage(arb_id=0x1A0, data=b'\xFF', interval_ms=100.0)
        sm.next_send_at = time.perf_counter() - 1.0

        received: list[ParsedMessage] = []
        worker.tx_echo.connect(received.append)

        with qtbot.waitSignal(worker.tx_echo, timeout=500):
            worker._send_due_messages(time.perf_counter(), [sm])

        assert received[0].is_tx is True

    def test_echo_correct_arb_id(self, worker, mock_bus_sender, qtbot):
        sm = SimMessage(arb_id=0x2B0, data=b'\x00', interval_ms=100.0)
        sm.next_send_at = time.perf_counter() - 1.0

        received: list[ParsedMessage] = []
        worker.tx_echo.connect(received.append)

        with qtbot.waitSignal(worker.tx_echo, timeout=500):
            worker._send_due_messages(time.perf_counter(), [sm])

        assert received[0].arb_id == 0x2B0

    def test_echo_correct_data(self, worker, mock_bus_sender, qtbot):
        payload = b'\xDE\xAD\xBE\xEF'
        sm = SimMessage(arb_id=0x100, data=payload, interval_ms=100.0)
        sm.next_send_at = time.perf_counter() - 1.0

        received: list[ParsedMessage] = []
        worker.tx_echo.connect(received.append)

        with qtbot.waitSignal(worker.tx_echo, timeout=500):
            worker._send_due_messages(time.perf_counter(), [sm])

        assert received[0].data == payload

    def test_echo_ch_id(self, qapp, mock_bus_sender, qtbot):
        worker = SimWorker(ch_id=2, bus_sender=mock_bus_sender)
        sm = SimMessage(arb_id=0x100, data=b'\x00', interval_ms=100.0)
        sm.next_send_at = time.perf_counter() - 1.0

        received: list[ParsedMessage] = []
        worker.tx_echo.connect(received.append)

        with qtbot.waitSignal(worker.tx_echo, timeout=500):
            worker._send_due_messages(time.perf_counter(), [sm])

        assert received[0].ch_id == 2

    def test_send_failure_no_crash(self, worker, mock_bus_sender, qtbot):
        """CANWorker.send()가 예외를 던져도 SimWorker가 크래시 없이 계속 동작."""
        mock_bus_sender.send.side_effect = Exception("Bus error")
        sm = SimMessage(arb_id=0x100, data=b'\x00', interval_ms=100.0)
        sm.next_send_at = time.perf_counter() - 1.0

        # 크래시 없이 실행 완료되어야 함
        worker._send_due_messages(time.perf_counter(), [sm])

    def test_not_due_message_not_sent(self, worker, mock_bus_sender):
        """아직 전송 시각이 아닌 메시지는 전송하지 않음."""
        sm = SimMessage(arb_id=0x100, data=b'\x00', interval_ms=100.0)
        sm.next_send_at = time.perf_counter() + 100.0   # 100초 후 전송

        worker._send_due_messages(time.perf_counter(), [sm])
        mock_bus_sender.send.assert_not_called()
        mock_bus_sender.increment_tx.assert_not_called()
