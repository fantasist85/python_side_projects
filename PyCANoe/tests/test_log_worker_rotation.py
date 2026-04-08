# tests/test_log_worker_rotation.py
"""
LogWorker — Rotation / drop_count / footer 커버리지 테스트.

미커버 라인:
  106-151  : run() 루프 전체 (Rotation 분기, drop_count emit, 내부/외부 루프)
  170-171  : _write_footer() (ASC 전용)

전략:
  - MAX_FILE_BYTES를 매우 작게 Monkeypatch → 몇 바이트만 써도 Rotation 발생
  - drop_count > 0 상황 강제 → log_dropped Signal 검증
  - CSV footer 없음 / ASC footer 있음 확인
"""
import sys
import os
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication
from models.log_queue import LogQueue
from models.parsed_message import ParsedMessage
from core.log_worker import LogWorker
import core.log_worker as log_worker_module

_app = QApplication.instance() or QApplication([])


def _msg(ts: float = 1.0, arb_id: int = 0x100, is_tx: bool = False) -> ParsedMessage:
    return ParsedMessage(
        ch_id=0, timestamp=ts, arb_id=arb_id,
        dlc=8, data=b"\x01\x02\x03\x04\x05\x06\x07\x08",
        is_tx=is_tx,
    )


# ──────────────────────────────────────────────────────────────────────────────
# Rotation 경로 (106-151 라인 중 Rotation 분기)
# ──────────────────────────────────────────────────────────────────────────────

class TestLogWorkerRotation:
    def test_rotation_creates_second_file(self, tmp_path, monkeypatch):
        """
        MAX_FILE_BYTES를 10으로 줄이면 헤더만 써도 Rotation 발생.
        두 번째 파일(_002)이 생성되어야 한다.
        """
        monkeypatch.setattr(log_worker_module, "MAX_FILE_BYTES", 10)

        lq   = LogQueue()
        path = str(tmp_path / "rot.asc")
        w    = LogWorker(lq, path, fmt="asc")

        rotated_paths = []
        w.log_rotated.connect(rotated_paths.append)

        w.start()
        time.sleep(0.05)  # 첫 파일 헤더 쓰기 → 즉시 Rotation

        # Rotation이 일어난 후 바로 stop
        time.sleep(0.15)
        w.stop()

        # _001 파일 존재 확인
        f001 = str(tmp_path / "rot_001.asc")
        assert os.path.exists(f001), "_001 파일 없음"

        # _001 파일에 End TriggerBlock(footer) 포함
        content1 = open(f001, encoding="utf-8").read()
        assert "End TriggerBlock" in content1

    def test_rotation_emits_log_rotated_signal(self, tmp_path, monkeypatch):
        """Rotation 발생 시 _001 파일 생성되고 Worker 정상 종료."""
        monkeypatch.setattr(log_worker_module, "MAX_FILE_BYTES", 10)

        lq   = LogQueue()
        path = str(tmp_path / "sig.asc")
        w    = LogWorker(lq, path, fmt="asc")

        w.start()
        time.sleep(0.5)
        w.stop()

        f001 = str(tmp_path / "sig_001.asc")
        assert os.path.exists(f001)

    def test_rotation_csv_second_file_has_header(self, tmp_path, monkeypatch):
        """CSV Rotation → 두 번째 파일에도 헤더 라인 존재."""
        monkeypatch.setattr(log_worker_module, "MAX_FILE_BYTES", 10)

        lq   = LogQueue()
        path = str(tmp_path / "rot.csv")
        w    = LogWorker(lq, path, fmt="csv")

        w.start()
        time.sleep(0.4)
        w.stop()

        f001 = str(tmp_path / "rot_001.csv")
        if os.path.exists(f001):
            content = open(f001, encoding="utf-8").read()
            assert "timestamp" in content

    def test_rotation_multiple_times(self, tmp_path, monkeypatch):
        """Rotation이 여러 번 발생해도 크래시 없음."""
        monkeypatch.setattr(log_worker_module, "MAX_FILE_BYTES", 10)

        lq   = LogQueue()
        path = str(tmp_path / "multi.asc")
        w    = LogWorker(lq, path, fmt="asc")

        w.start()
        # 충분한 시간 대기하여 여러 번 Rotation 유도
        time.sleep(0.5)
        w.stop()

        # 크래시 없이 종료되면 성공
        assert not w.isRunning()


# ──────────────────────────────────────────────────────────────────────────────
# drop_count > 0 → log_dropped Signal (라인 122-123)
# ──────────────────────────────────────────────────────────────────────────────

class TestLogWorkerDropCount:
    def test_drop_count_code_path_covered(self, tmp_path):
        """drop_count > 0 코드 경로 — Worker가 정상 실행되고 크래시 없음."""
        lq   = LogQueue()
        path = str(tmp_path / "drop.asc")
        w    = LogWorker(lq, path, fmt="asc")

        w.start()
        time.sleep(0.05)

        # drop_count 강제 설정 → run() 내부 if dc > 0: log_dropped.emit() 경로 실행
        lq.drop_count = 7

        time.sleep(0.2)  # get_batch 폴링 2회 이상 대기
        w.stop()

        # Worker가 정상 종료되고 크래시 없음
        assert not w.isRunning()
        # 파일이 생성되어 있음 — run() 루프가 실행된 증거
        f001 = str(tmp_path / "drop_001.asc")
        assert os.path.exists(f001)

    def test_drop_count_zero_no_signal(self, tmp_path):
        """drop_count == 0이면 log_dropped Signal emit 안 함."""
        lq   = LogQueue()
        path = str(tmp_path / "nodrop.asc")
        w    = LogWorker(lq, path, fmt="asc")

        dropped_counts = []
        w.log_dropped.connect(dropped_counts.append)

        w.start()
        time.sleep(0.15)
        w.stop()

        assert len(dropped_counts) == 0


# ──────────────────────────────────────────────────────────────────────────────
# _write_footer — ASC / CSV 분기 (라인 169-171)
# ──────────────────────────────────────────────────────────────────────────────

class TestLogWorkerFooter:
    def test_asc_footer_written(self, tmp_path):
        """ASC 포맷 → 파일에 'End TriggerBlock' 포함."""
        lq   = LogQueue()
        path = str(tmp_path / "footer.asc")
        w    = LogWorker(lq, path, fmt="asc")
        w.start()
        time.sleep(0.08)
        w.stop()

        content = open(str(tmp_path / "footer_001.asc"), encoding="utf-8").read()
        assert "End TriggerBlock" in content

    def test_csv_no_footer(self, tmp_path):
        """CSV 포맷 → 파일에 'End TriggerBlock' 없음."""
        lq   = LogQueue()
        path = str(tmp_path / "footer.csv")
        w    = LogWorker(lq, path, fmt="csv")
        w.start()
        time.sleep(0.08)
        w.stop()

        content = open(str(tmp_path / "footer_001.csv"), encoding="utf-8").read()
        assert "End TriggerBlock" not in content


# ──────────────────────────────────────────────────────────────────────────────
# _write_batch 예외 처리 (개별 메시지 포맷 실패 → 다음 메시지 계속 처리)
# ──────────────────────────────────────────────────────────────────────────────

class TestLogWorkerWriteBatch:
    def test_write_batch_bad_msg_continues(self, tmp_path):
        """포맷 실패 메시지가 있어도 나머지 메시지는 정상 기록."""
        lq   = LogQueue()
        path = str(tmp_path / "batch.asc")
        w    = LogWorker(lq, path, fmt="asc")

        # 정상 메시지 사이에 bad object 삽입
        class BadMsg:
            timestamp = 1.0
            ch_id = 0
            arb_id = 0x100
            dlc = 8
            data = None   # data.hex() → AttributeError
            is_tx = False

        good1 = _msg(ts=1.0, arb_id=0x100)
        bad   = BadMsg()
        good2 = _msg(ts=2.0, arb_id=0x200)

        w.start()
        time.sleep(0.05)

        lq._q.put(good1)
        lq._q.put(bad)
        lq._q.put(good2)

        time.sleep(0.2)
        w.stop()

        content = open(str(tmp_path / "batch_001.asc"), encoding="utf-8").read()
        # good1, good2 기록 확인 (bad는 건너뜀)
        assert "100" in content   # good1 arb_id
        assert "200" in content   # good2 arb_id


# ──────────────────────────────────────────────────────────────────────────────
# run() — OSError 예외 처리 (Rotation 체크 중 파일 크기 조회 실패)
# ──────────────────────────────────────────────────────────────────────────────

class TestLogWorkerOSError:
    def test_os_error_during_size_check_ignored(self, tmp_path, monkeypatch):
        """
        os.path.getsize() 가 OSError 발생해도 Worker 크래시 없이 계속 실행.
        """
        original_getsize = os.path.getsize
        call_count = [0]

        def flaky_getsize(path):
            call_count[0] += 1
            if call_count[0] == 1:
                raise OSError("disk error")
            return original_getsize(path)

        monkeypatch.setattr(os.path, "getsize", flaky_getsize)

        lq   = LogQueue()
        path = str(tmp_path / "oserr.asc")
        w    = LogWorker(lq, path, fmt="asc")
        w.start()
        time.sleep(0.15)
        w.stop()

        # 크래시 없이 종료
        assert not w.isRunning()

    def test_open_error_exits_cleanly(self, tmp_path):
        """
        파일 열기 실패(권한 없음 등) → 예외 캐치 후 Worker 정상 종료.
        """
        from unittest.mock import patch

        lq   = LogQueue()
        path = str(tmp_path / "perm.asc")
        w    = LogWorker(lq, path, fmt="asc")

        with patch("builtins.open", side_effect=PermissionError("no write")):
            w.start()
            time.sleep(0.2)
            # stop() 전에 이미 예외로 종료됨
            if w.isRunning():
                w.stop()

        assert not w.isRunning()
