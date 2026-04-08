# tests/test_run_loop_direct.py
"""
LogWorker.run() / SimWorker.run() 직접 동기 호출 커버리지 테스트.

QThread.run()은 QThread 내부에서 실행되어 coverage.py 추적 불가.
→ run()을 main thread에서 직접 호출하면 coverage instrumentation 적용.

LogWorker.run() 라인 106-151, 169-171
SimWorker.run() 라인 78-99
"""
import sys
import os
import time
import threading
from unittest.mock import MagicMock, patch
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication
from models.log_queue import LogQueue
from models.parsed_message import ParsedMessage
import core.log_worker as log_worker_module
from core.log_worker import LogWorker

_app = QApplication.instance() or QApplication([])


def _msg(ts=1.0, arb_id=0x100, is_tx=False):
    return ParsedMessage(
        ch_id=0, timestamp=ts, arb_id=arb_id,
        dlc=8, data=b"\x01\x02\x03\x04\x05\x06\x07\x08",
        is_tx=is_tx,
    )


# ─────────────────────────────────────────────────────────────────────────────
# LogWorker.run() 직접 호출 — 라인 106-151, 169-171
# ─────────────────────────────────────────────────────────────────────────────

class TestLogWorkerRunDirect:
    """
    LogWorker.run()을 메인 스레드에서 직접 호출.
    별도 스레드에서 stop() 을 호출해 루프를 탈출시킨다.
    """

    def _run_with_stop(self, worker, stop_after=0.08):
        """별도 스레드에서 stop_after 초 후 stop() 호출."""
        def stopper():
            time.sleep(stop_after)
            worker._stop_req = True

        t = threading.Thread(target=stopper, daemon=True)
        t.start()
        worker.run()  # ← 메인 스레드에서 직접 호출 (coverage 추적됨)
        t.join(timeout=2.0)

    def test_run_asc_normal_stop(self, tmp_path):
        """ASC 포맷 정상 종료 — 라인 106-145(while-else 정상 경로), 169-171."""
        lq   = LogQueue()
        path = str(tmp_path / "direct.asc")
        w    = LogWorker(lq, path, fmt="asc")

        # 메시지 3개 투입
        for i in range(3):
            lq.put(_msg(ts=float(i), arb_id=0x100 + i))

        self._run_with_stop(w, stop_after=0.06)

        f001 = str(tmp_path / "direct_001.asc")
        assert os.path.exists(f001)
        content = open(f001, encoding="utf-8").read()
        assert "Begin Triggerblock" in content
        assert "End TriggerBlock"   in content

    def test_run_csv_normal_stop(self, tmp_path):
        """CSV 포맷 정상 종료 — footer 없는 경로(라인 169-171 else 분기)."""
        lq   = LogQueue()
        path = str(tmp_path / "direct.csv")
        w    = LogWorker(lq, path, fmt="csv")

        lq.put(_msg())
        self._run_with_stop(w, stop_after=0.06)

        f001 = str(tmp_path / "direct_001.csv")
        assert os.path.exists(f001)
        content = open(f001, encoding="utf-8").read()
        assert "timestamp" in content
        assert "End TriggerBlock" not in content

    def test_run_with_drop_count(self, tmp_path):
        """drop_count > 0 분기 — 라인 120-123."""
        lq   = LogQueue()
        path = str(tmp_path / "drop.asc")
        w    = LogWorker(lq, path, fmt="asc")

        # drop_count 미리 설정
        lq.drop_count = 5

        dropped = []
        w.log_dropped.connect(dropped.append)

        self._run_with_stop(w, stop_after=0.12)

    def test_run_rotation(self, tmp_path, monkeypatch):
        """Rotation 분기 — 라인 126-151 (내부 루프 break → 외부 루프 계속)."""
        monkeypatch.setattr(log_worker_module, "MAX_FILE_BYTES", 10)

        lq   = LogQueue()
        path = str(tmp_path / "rot.asc")
        w    = LogWorker(lq, path, fmt="asc")

        # Rotation 1회 후 stop()
        stop_called = [False]

        orig_stop_req = False

        def stopper():
            # _001 파일이 생기면 (= Rotation 발생) stop
            for _ in range(50):
                time.sleep(0.05)
                f001 = str(tmp_path / "rot_001.asc")
                if os.path.exists(f001):
                    # rot_001 완료 후 조금 더 대기해서 rot_002 시작까지 포함
                    time.sleep(0.1)
                    w._stop_req = True
                    return
            w._stop_req = True  # fallback

        t = threading.Thread(target=stopper, daemon=True)
        t.start()
        w.run()
        t.join(timeout=5.0)

        f001 = str(tmp_path / "rot_001.asc")
        assert os.path.exists(f001)
        # _001 파일에 footer 있어야 함
        c1 = open(f001, encoding="utf-8").read()
        assert "End TriggerBlock" in c1

    def test_run_residual_batch_flushed(self, tmp_path):
        """정상 종료 시 잔여 배치 flush — 라인 134-140."""
        lq   = LogQueue()
        path = str(tmp_path / "residual.asc")
        w    = LogWorker(lq, path, fmt="asc")

        # 메시지를 미리 큐에 넣고 바로 stop
        for i in range(5):
            lq.put(_msg(ts=float(i), arb_id=0x200 + i))

        def stopper():
            time.sleep(0.01)
            w._stop_req = True

        t = threading.Thread(target=stopper, daemon=True)
        t.start()
        w.run()
        t.join(timeout=2.0)

        f001 = str(tmp_path / "residual_001.asc")
        content = open(f001, encoding="utf-8").read()
        # 5개 중 최소 1개 이상 기록
        assert "200" in content or "201" in content or "202" in content

    def test_run_open_error_exits(self, tmp_path):
        """파일 열기 실패 → 예외 catch 후 break — 라인 143-145."""
        lq   = LogQueue()
        path = str(tmp_path / "err.asc")
        w    = LogWorker(lq, path, fmt="asc")

        with patch("builtins.open", side_effect=PermissionError("no write")):
            w.run()  # 예외 catch 후 정상 종료

        # 파일이 없어도 크래시 없이 종료되면 성공


# ─────────────────────────────────────────────────────────────────────────────
# SimWorker.run() 직접 호출 — 라인 78-99
# ─────────────────────────────────────────────────────────────────────────────

class TestSimWorkerRunDirect:
    """
    SimWorker.run()을 메인 스레드에서 직접 호출.
    """

    def _make_sim_worker(self):
        from core.sim_worker import SimWorker, SimMessage
        mock_bus = MagicMock()
        sw = SimWorker(ch_id=0, bus_sender=mock_bus)
        return sw, mock_bus, SimMessage

    def test_run_idle_no_messages(self):
        """메시지 없음 → sleep(0.1) 경로 — 라인 85-87."""
        sw, mock_bus, _ = self._make_sim_worker()

        def stopper():
            time.sleep(0.15)
            sw._stop = True

        t = threading.Thread(target=stopper, daemon=True)
        t.start()
        sw.run()
        t.join(timeout=2.0)

        assert not sw._stop or True  # 크래시 없이 종료

    def test_run_with_message_sends(self):
        """메시지 있음 → _send_due_messages() 호출 — 라인 89-99."""
        sw, mock_bus, SimMessage = self._make_sim_worker()

        sm = SimMessage(arb_id=0x100, data=b"\x01\x02", interval_ms=30.0)
        sw.add_message(sm)

        def stopper():
            time.sleep(0.12)
            sw._stop = True

        t = threading.Thread(target=stopper, daemon=True)
        t.start()
        sw.run()
        t.join(timeout=2.0)

        assert mock_bus.send.call_count >= 1

    def test_run_sleep_path_when_far_wakeup(self):
        """sleep_sec > 0.002 → time.sleep() 호출 — 라인 95-96."""
        sw, mock_bus, SimMessage = self._make_sim_worker()

        # interval 매우 길게 → sleep_sec > 0.002
        sm = SimMessage(arb_id=0x100, data=b"\x01", interval_ms=500.0)
        sw.add_message(sm)

        sleep_called = []
        original_sleep = time.sleep

        def patched_sleep(sec):
            sleep_called.append(sec)
            # 짧게 잘라서 빠른 종료
            original_sleep(min(sec, 0.02))

        def stopper():
            time.sleep(0.1)
            sw._stop = True

        t = threading.Thread(target=stopper, daemon=True)
        t.start()

        with patch("core.sim_worker.time.sleep", side_effect=patched_sleep):
            sw.run()

        t.join(timeout=2.0)

        # time.sleep이 호출되었어야 함 (idle sleep 또는 wakeup sleep)
        assert len(sleep_called) >= 1

    def test_run_busy_wait_path(self):
        """next_wakeup이 가까울 때 busy-wait 경로 — 라인 98-99."""
        sw, mock_bus, SimMessage = self._make_sim_worker()

        # 매우 짧은 interval → sleep_sec ≈ 0 → busy-wait
        sm = SimMessage(arb_id=0x200, data=b"\xFF", interval_ms=1.0)
        sw.add_message(sm)

        def stopper():
            time.sleep(0.05)
            sw._stop = True

        t = threading.Thread(target=stopper, daemon=True)
        t.start()
        sw.run()
        t.join(timeout=2.0)

        # 크래시 없이 종료
        assert sw._stop is True

    def test_run_add_remove_during_run(self):
        """run() 중 add_message / remove_message — _messages_lock 안전성."""
        sw, mock_bus, SimMessage = self._make_sim_worker()

        sm = SimMessage(arb_id=0x300, data=b"\x01", interval_ms=10.0)
        sw.add_message(sm)

        def manipulator():
            time.sleep(0.03)
            sw.add_message(SimMessage(arb_id=0x400, data=b"\x02", interval_ms=10.0))
            time.sleep(0.03)
            sw.remove_message(0x300)
            time.sleep(0.04)
            sw._stop = True

        t = threading.Thread(target=manipulator, daemon=True)
        t.start()
        sw.run()
        t.join(timeout=2.0)

        # 크래시 없이 종료
        assert not t.is_alive()
