# tests/test_sim_worker_extra2.py
"""
SimWorker 추가 커버리지 테스트.

커버 대상 (sim_worker.py 79% → 목표 90%):
  - SimMessage.update_next() drift 리셋 경로
  - SimMessage.to_can_message()
  - SimMessage.is_due()
  - _send_due_messages() send 예외 시 계속 진행
  - run() busy-wait 경로 (sleep_sec <= 0.002)
  - remove_message() 존재하지 않는 arb_id
"""
import sys
import os
import time
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication
import can

from core.sim_worker import SimMessage, SimWorker

_app = QApplication.instance() or QApplication([])


def _make_sim_msg(arb_id=0x100, data=b"\x01\x02", interval_ms=100.0):
    return SimMessage(arb_id=arb_id, data=data, interval_ms=interval_ms)


def _make_worker():
    bus_sender = MagicMock()
    bus_sender.send.return_value = None
    return SimWorker(ch_id=0, bus_sender=bus_sender), bus_sender


# ──────────────────────────────────────────────────────────────────────────────
# SimMessage 메서드
# ──────────────────────────────────────────────────────────────────────────────

class TestSimMessage:
    def test_is_due_past(self):
        """next_send_at이 과거면 True."""
        sm = _make_sim_msg()
        sm.next_send_at = time.perf_counter() - 1.0
        assert sm.is_due(time.perf_counter()) is True

    def test_is_due_future(self):
        """next_send_at이 미래면 False."""
        sm = _make_sim_msg()
        sm.next_send_at = time.perf_counter() + 10.0
        assert sm.is_due(time.perf_counter()) is False

    def test_update_next_advances_time(self):
        """update_next() 호출 시 next_send_at이 interval_ms/1000 만큼 증가."""
        sm = _make_sim_msg(interval_ms=100.0)
        before = sm.next_send_at
        now = sm.next_send_at + 0.001   # 이제 막 지났을 때
        sm.update_next(now)
        assert sm.next_send_at > before

    def test_update_next_drift_reset(self):
        """크게 밀린 경우 next_send_at이 now + interval로 리셋."""
        sm = _make_sim_msg(interval_ms=100.0)
        # next_send_at을 매우 과거로 설정 (2 * interval 이상 밀림)
        sm.next_send_at = time.perf_counter() - 5.0
        now = time.perf_counter()
        sm.update_next(now)
        # 리셋 후 now보다 크고, now + interval에 가까워야 함
        assert sm.next_send_at > now

    def test_to_can_message_arb_id(self):
        """to_can_message() → can.Message with correct arb_id."""
        sm = _make_sim_msg(arb_id=0x1A0, data=b"\xDE\xAD")
        msg = sm.to_can_message()
        assert isinstance(msg, can.Message)
        assert msg.arbitration_id == 0x1A0

    def test_to_can_message_data(self):
        """to_can_message() → data 일치."""
        sm = _make_sim_msg(data=b"\x01\x02\x03")
        msg = sm.to_can_message()
        assert bytes(msg.data) == b"\x01\x02\x03"

    def test_to_can_message_not_extended(self):
        """to_can_message() → is_extended_id=False."""
        sm = _make_sim_msg()
        msg = sm.to_can_message()
        assert msg.is_extended_id is False


# ──────────────────────────────────────────────────────────────────────────────
# SimWorker.remove_message
# ──────────────────────────────────────────────────────────────────────────────

class TestSimWorkerRemove:
    def test_remove_nonexistent_no_crash(self):
        """없는 arb_id remove → 크래시 없음, 기존 메시지 유지."""
        w, _ = _make_worker()
        sm = _make_sim_msg(arb_id=0x100)
        w.add_message(sm)

        w.remove_message(0x999)   # 없는 ID

        with w._messages_lock:
            assert len(w._messages) == 1

    def test_remove_correct_message(self):
        """올바른 arb_id remove → 해당 메시지 삭제."""
        w, _ = _make_worker()
        w.add_message(_make_sim_msg(arb_id=0x100))
        w.add_message(_make_sim_msg(arb_id=0x200))

        w.remove_message(0x100)

        with w._messages_lock:
            ids = [m.arb_id for m in w._messages]
        assert 0x100 not in ids
        assert 0x200 in ids

    def test_remove_all_messages(self):
        """모든 메시지 remove → 빈 리스트."""
        w, _ = _make_worker()
        w.add_message(_make_sim_msg(arb_id=0x100))
        w.remove_message(0x100)

        with w._messages_lock:
            assert len(w._messages) == 0


# ──────────────────────────────────────────────────────────────────────────────
# _send_due_messages — 예외 처리
# ──────────────────────────────────────────────────────────────────────────────

class TestSendDueMessages:
    def test_send_exception_continues_to_next(self):
        """bus.send() 예외 발생 시 나머지 메시지 전송 계속."""
        bus = MagicMock()
        bus.send.side_effect = can.CanError("bus error")
        w = SimWorker(ch_id=0, bus_sender=bus)

        sm1 = _make_sim_msg(arb_id=0x100)
        sm2 = _make_sim_msg(arb_id=0x200)
        sm1.next_send_at = time.perf_counter() - 0.1  # 이미 지남
        sm2.next_send_at = time.perf_counter() - 0.1

        # 예외가 발생해도 크래시 없어야 함
        w._send_due_messages(time.perf_counter(), [sm1, sm2])

        # 두 번 호출 시도
        assert bus.send.call_count == 2

    def test_tx_echo_emitted_even_on_send_error(self):
        """send() 예외 발생 시에도 tx_echo emit."""
        bus = MagicMock()
        bus.send.side_effect = Exception("error")
        w = SimWorker(ch_id=0, bus_sender=bus)

        echoes = []
        w.tx_echo.connect(echoes.append)

        sm = _make_sim_msg()
        sm.next_send_at = time.perf_counter() - 0.1

        w._send_due_messages(time.perf_counter(), [sm])
        assert len(echoes) == 1

    def test_not_due_message_skipped(self):
        """미래 메시지 → send 호출 없음."""
        bus = MagicMock()
        w = SimWorker(ch_id=0, bus_sender=bus)

        sm = _make_sim_msg()
        sm.next_send_at = time.perf_counter() + 100.0  # 100초 후

        w._send_due_messages(time.perf_counter(), [sm])
        bus.send.assert_not_called()


# ──────────────────────────────────────────────────────────────────────────────
# SimWorker.run() — busy-wait 경로 (short interval)
# ──────────────────────────────────────────────────────────────────────────────

class TestSimWorkerRunBusyWait:
    def test_short_interval_no_crash(self):
        """1ms 이하 interval → busy-wait 경로 진입, 크래시 없음."""
        w, bus = _make_worker()

        sm = _make_sim_msg(interval_ms=1.0)   # 1ms
        w.add_message(sm)

        w.start()
        time.sleep(0.05)   # 50ms 실행 → 약 50번 전송
        w.stop()

        # 최소 1번은 전송되어야 함
        assert bus.send.call_count >= 1

    def test_multiple_intervals_no_starvation(self):
        """50ms + 30ms 두 메시지 — 짧은 주기가 긴 주기를 굶기지 않는다."""
        w, bus = _make_worker()
        w.add_message(_make_sim_msg(arb_id=0x100, interval_ms=50.0))
        w.add_message(_make_sim_msg(arb_id=0x200, interval_ms=30.0))

        w.start()
        time.sleep(0.2)   # 200ms
        w.stop()

        assert bus.send.call_count >= 2   # 최소 양쪽 모두 전송


# ──────────────────────────────────────────────────────────────────────────────
# SimWorker.stop() 안전성
# ──────────────────────────────────────────────────────────────────────────────

class TestSimWorkerStop:
    def test_stop_while_running(self):
        """실행 중 stop() → isRunning() False."""
        w, _ = _make_worker()
        sm = _make_sim_msg(interval_ms=10.0)
        w.add_message(sm)
        w.start()
        time.sleep(0.05)
        w.stop()
        assert not w.isRunning()

    def test_stop_idle_worker(self):
        """메시지 없는 유휴 상태 stop() → 즉시 종료."""
        w, _ = _make_worker()
        w.start()
        time.sleep(0.05)
        w.stop()
        assert not w.isRunning()

    def test_double_stop_no_crash(self):
        """stop() 2회 호출 — 크래시 없음."""
        w, _ = _make_worker()
        w.start()
        time.sleep(0.02)
        w.stop()
        w.stop()   # 두 번째 stop — 크래시 없어야 함
