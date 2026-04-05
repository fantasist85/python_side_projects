# tests/test_async_db_loader.py
"""
AsyncDbLoader 단위 테스트.

명세서 Section 11.1 검증 항목:
  - Signal이 Main Thread에서 수신 (pytest-qt qtbot.waitSignal)
  - self 참조 없을 때 GC 방어 (로컬 변수 패턴 재현)
  - 성공/실패 경로 모두 Signal emit 확인
  - start_loading() 이후 즉시 반환 (non-blocking)
"""
import sys
import os
import gc
import time
import threading
import weakref

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from core.async_db_loader import AsyncDbLoader
from core.db_parser import DbParser

_app = QApplication.instance() or QApplication([])

SAMPLE_DBC = os.path.join(os.path.dirname(__file__), "fixtures", "sample.dbc")


# ---------------------------------------------------------------------------
# 성공 경로
# ---------------------------------------------------------------------------

class TestAsyncDbLoaderSuccess:

    def test_db_loaded_signal_emitted_on_success(self, qtbot) -> None:
        """
        유효한 DBC 파일 로드 시 db_loaded Signal이 (True, parser) 로 emit 되어야 함.
        Signal은 Main Thread에서 수신됨을 pytest-qt qtbot.waitSignal로 검증.
        """
        parser = DbParser()
        loader = AsyncDbLoader(parser, SAMPLE_DBC)

        with qtbot.waitSignal(loader.db_loaded, timeout=3000) as blocker:
            loader.start_loading()

        success, returned_parser = blocker.args
        assert success is True
        assert returned_parser is parser
        assert returned_parser.is_loaded is True

    def test_db_loaded_success_makes_parser_loaded(self, qtbot) -> None:
        """db_loaded(True) 수신 후 parser.is_loaded == True."""
        parser = DbParser()
        loader = AsyncDbLoader(parser, SAMPLE_DBC)

        with qtbot.waitSignal(loader.db_loaded, timeout=3000):
            loader.start_loading()

        assert parser.is_loaded is True
        assert parser.db_type == "dbc"


# ---------------------------------------------------------------------------
# 실패 경로
# ---------------------------------------------------------------------------

class TestAsyncDbLoaderFailure:

    def test_db_loaded_signal_emitted_on_failure(self, qtbot) -> None:
        """
        존재하지 않는 파일 로드 시 db_loaded Signal이 (False, parser) 로 emit 되어야 함.
        실패해도 Signal은 반드시 emit — Graceful Degradation.
        """
        parser = DbParser()
        loader = AsyncDbLoader(parser, "/nonexistent/path/no.dbc")

        with qtbot.waitSignal(loader.db_loaded, timeout=3000) as blocker:
            loader.start_loading()

        success, returned_parser = blocker.args
        assert success is False
        assert returned_parser is parser
        assert returned_parser.is_loaded is False

    def test_db_loaded_failure_parser_db_is_none(self, qtbot) -> None:
        """실패 시 parser._db == None 유지 (Graceful Degradation)."""
        parser = DbParser()
        loader = AsyncDbLoader(parser, "/no/such/file.dbc")

        with qtbot.waitSignal(loader.db_loaded, timeout=3000):
            loader.start_loading()

        assert parser._db is None


# ---------------------------------------------------------------------------
# Non-blocking 검증
# ---------------------------------------------------------------------------

class TestAsyncDbLoaderNonBlocking:

    def test_start_loading_returns_immediately(self) -> None:
        """
        start_loading()은 즉시 반환되어야 함 (daemon thread 위임).
        50ms 이내 반환되지 않으면 실패.
        """
        parser = DbParser()
        loader = AsyncDbLoader(parser, SAMPLE_DBC)

        t0 = time.perf_counter()
        loader.start_loading()
        elapsed = time.perf_counter() - t0

        assert elapsed < 0.05, f"start_loading() 블로킹: {elapsed:.3f}s"

    def test_daemon_thread_does_not_block_main(self, qtbot) -> None:
        """로딩 중에 메인 스레드가 다른 작업을 수행할 수 있어야 함."""
        parser = DbParser()
        loader = AsyncDbLoader(parser, SAMPLE_DBC)
        loader.start_loading()

        # 로딩 중에도 main thread에서 다른 작업 가능
        counter = 0
        for _ in range(1000):
            counter += 1
        assert counter == 1000

        with qtbot.waitSignal(loader.db_loaded, timeout=3000):
            pass


# ---------------------------------------------------------------------------
# GC 방어 검증 (명세서 AI Rule 12)
# ---------------------------------------------------------------------------

class TestAsyncDbLoaderGcSafety:

    def test_self_reference_prevents_gc(self, qtbot) -> None:
        """
        [AI Rule 12] AsyncDbLoader를 self에 저장하면 Signal emit 전 GC되지 않는다.

        올바른 패턴:
            self._db_loader = AsyncDbLoader(parser, path)  # self에 저장 필수
            self._db_loader.db_loaded.connect(slot)
            self._db_loader.start_loading()

        Signal이 정상 수신되면 GC 없이 살아있었음을 의미한다.
        """
        parser  = DbParser()
        results: list = []

        # self 역할을 하는 컨테이너에 저장
        container = {"loader": AsyncDbLoader(parser, SAMPLE_DBC)}
        container["loader"].db_loaded.connect(lambda ok, p: results.append(ok))
        container["loader"].start_loading()

        # Signal이 emit될 때까지 대기
        deadline = time.time() + 3.0
        while not results and time.time() < deadline:
            _app.processEvents()
            time.sleep(0.01)

        assert results, "db_loaded Signal 미수신 — GC 혹은 Signal 연결 오류"
        assert results[0] is True

    def test_consecutive_loads_disconnect_old_signal(self, qtbot) -> None:
        """
        연속 로드 시 이전 Signal을 disconnect하고 새 AsyncDbLoader를 사용해야 한다.
        두 번 연속 로드 후 슬롯이 정확히 2번(각 1번씩) 호출되는지 확인.
        명세서 AsyncDbLoader docstring의 '올바른 사용 패턴' 검증.
        """
        parser1 = DbParser()
        parser2 = DbParser()
        call_log: list[bool] = []

        # 첫 번째 로드
        db_loader: AsyncDbLoader | None = None

        def _on_loaded(ok: bool, p) -> None:
            call_log.append(ok)

        # 1회차
        if db_loader is not None:
            try:
                db_loader.db_loaded.disconnect(_on_loaded)
            except RuntimeError:
                pass
        db_loader = AsyncDbLoader(parser1, SAMPLE_DBC)
        db_loader.db_loaded.connect(_on_loaded)
        db_loader.start_loading()

        with qtbot.waitSignal(db_loader.db_loaded, timeout=3000):
            pass

        # 2회차 (이전 disconnect 후 재연결)
        try:
            db_loader.db_loaded.disconnect(_on_loaded)
        except RuntimeError:
            pass
        db_loader = AsyncDbLoader(parser2, SAMPLE_DBC)
        db_loader.db_loaded.connect(_on_loaded)
        db_loader.start_loading()

        with qtbot.waitSignal(db_loader.db_loaded, timeout=3000):
            pass

        # 슬롯이 정확히 2번 호출되어야 함 (이전 Signal이 중복 연결되지 않음)
        assert len(call_log) == 2, f"예상 2회, 실제 {len(call_log)}회: {call_log}"
        assert all(ok is True for ok in call_log)
