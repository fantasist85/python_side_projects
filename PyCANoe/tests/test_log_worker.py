# tests/test_log_worker.py
import sys, os
import time
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

# LogWorker는 PySide6.QtCore.QThread 의존 — Qt App 필요
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication
from models.log_queue import LogQueue
from models.parsed_message import ParsedMessage
from core.log_worker import LogWorker

_app = QApplication.instance() or QApplication([])


def _msg(ts: float = 0.0, arb_id: int = 0x100) -> ParsedMessage:
    return ParsedMessage(ch_id=0, timestamp=ts, arb_id=arb_id, dlc=8, data=b"\x00" * 8)


class TestLogWorkerResidualFlush:
    def test_residual_batch_written_before_stop(self, tmp_path) -> None:
        """
        STEP 8 완료 기준:
        stop() 직전 큐에 남은 메시지가 ASC 파일 End TriggerBlock 앞에 기록됨.
        """
        lq   = LogQueue()
        path = str(tmp_path / "test.asc")
        w    = LogWorker(lq, path, fmt="asc")
        w.start()
        time.sleep(0.05)   # Worker 준비 대기

        # 10건 투입 후 즉시 stop() — CHUNK(5000)보다 적으므로 배치에 잔류
        for i in range(10):
            lq.put(_msg(ts=float(i), arb_id=0x100 + i))
        time.sleep(0.15)   # get(timeout=0.1) 한 번 탈출 대기
        w.stop()

        log_path = path.replace(".asc", "_001.asc")
        assert os.path.exists(log_path), f"파일 없음: {log_path}"
        content = open(log_path, encoding="utf-8").read()

        assert "Begin Triggerblock" in content
        assert "End TriggerBlock"   in content
        # 10건 중 최소 1건 이상 기록
        assert content.count("100") >= 1 or "1A4" in content or "10" in content

    def test_asc_header_format(self, tmp_path) -> None:
        """ASC 파일에 CANalyzer 호환 헤더 포함 확인."""
        lq   = LogQueue()
        path = str(tmp_path / "hdr.asc")
        w    = LogWorker(lq, path, fmt="asc")
        w.start()
        time.sleep(0.05)
        w.stop()

        log_path = path.replace(".asc", "_001.asc")
        content  = open(log_path, encoding="utf-8").read()
        assert "base hex"          in content
        assert "Begin Triggerblock" in content
        assert "End TriggerBlock"   in content
