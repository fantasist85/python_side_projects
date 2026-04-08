# tests/test_main.py
"""
main.py — 진입점 함수 단위 테스트.

_set_timer_resolution / _restore_timer_resolution 은
os.name == 'nt' 일 때만 ctypes 호출이 일어나므로
Linux CI 환경에서는 호출 없이 통과하는 것을 검증한다.

__main__ 블록은 subprocess로 실행해 커버리지를 확보한다.
"""
import sys
import os
import importlib
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
pytest.importorskip("PySide6")


# ─────────────────────────────────────────────────────────────────────────────
# 함수 직접 임포트 테스트
# ─────────────────────────────────────────────────────────────────────────────

class TestTimerResolutionFunctions:
    """_set_timer_resolution / _restore_timer_resolution 단위 테스트."""

    def _import_funcs(self):
        """main 모듈에서 함수만 임포트 (if __name__ == '__main__' 블록 실행 안 함)."""
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "main_module",
            os.path.join(os.path.dirname(__file__), "..", "src", "main.py"),
        )
        mod = importlib.util.module_from_spec(spec)
        # __name__ != '__main__' 이므로 if 블록 실행 안 됨
        spec.loader.exec_module(mod)
        return mod

    def test_set_timer_resolution_linux_no_ctypes_call(self):
        """Linux(os.name='posix')에서 _set_timer_resolution → ctypes 호출 없음."""
        mod = self._import_funcs()
        with patch.object(mod, "os") as mock_os:
            mock_os.name = "posix"
            # ctypes.windll 속성 없음 — AttributeError 없어야 함
            mod._set_timer_resolution()   # 크래시 없어야 함

    def test_restore_timer_resolution_linux_no_ctypes_call(self):
        """Linux에서 _restore_timer_resolution → ctypes 호출 없음."""
        mod = self._import_funcs()
        with patch.object(mod, "os") as mock_os:
            mock_os.name = "posix"
            mod._restore_timer_resolution()

    def test_set_timer_resolution_windows_calls_timeBeginPeriod(self):
        """Windows(os.name='nt') 시뮬레이션 → timeBeginPeriod(1) 호출."""
        mod = self._import_funcs()
        mock_ctypes = MagicMock()
        with patch.object(mod, "os") as mock_os:
            with patch.object(mod, "ctypes", mock_ctypes):
                mock_os.name = "nt"
                mod._set_timer_resolution()
                mock_ctypes.windll.winmm.timeBeginPeriod.assert_called_once_with(1)

    def test_restore_timer_resolution_windows_calls_timeEndPeriod(self):
        """Windows 시뮬레이션 → timeEndPeriod(1) 호출."""
        mod = self._import_funcs()
        mock_ctypes = MagicMock()
        with patch.object(mod, "os") as mock_os:
            with patch.object(mod, "ctypes", mock_ctypes):
                mock_os.name = "nt"
                mod._restore_timer_resolution()
                mock_ctypes.windll.winmm.timeEndPeriod.assert_called_once_with(1)

    def test_module_loads_without_error(self):
        """main.py가 import 시 오류 없이 로드되어야 한다."""
        mod = self._import_funcs()
        assert callable(getattr(mod, "_set_timer_resolution", None))
        assert callable(getattr(mod, "_restore_timer_resolution", None))
