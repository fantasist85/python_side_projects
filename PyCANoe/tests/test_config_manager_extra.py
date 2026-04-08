# tests/test_config_manager_extra.py
"""
ConfigManager 추가 단위 테스트.
커버리지 목표: 미커버 라인 (47-49, 87-94, 109) 처리.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMainWindow
from PySide6.QtCore import QSettings
from app.config_manager import ConfigManager

_app = QApplication.instance() or QApplication([])


@pytest.fixture
def cfg(tmp_path):
    """임시 INI 파일을 사용하는 ConfigManager 인스턴스."""
    ini = str(tmp_path / "test_settings.ini")
    qs  = QSettings(ini, QSettings.Format.IniFormat)
    mgr = ConfigManager.__new__(ConfigManager)
    mgr._qs = qs
    return mgr


@pytest.fixture
def main_window(qtbot):
    w = QMainWindow()
    qtbot.addWidget(w)
    w.show()
    return w


class TestConfigManagerSaveWindow:
    def test_save_window_stores_version(self, cfg, main_window):
        """save_window() 호출 시 settings_version이 저장된다."""
        from app.config_manager import SETTINGS_VERSION
        cfg.save_window(main_window)
        assert int(cfg._qs.value("settings_version", 0)) == SETTINGS_VERSION

    def test_save_window_stores_geometry(self, cfg, main_window):
        """save_window() 호출 시 window/geometry가 저장된다."""
        cfg.save_window(main_window)
        assert cfg._qs.value("window/geometry") is not None

    def test_save_window_stores_state(self, cfg, main_window):
        """save_window() 호출 시 window/state가 저장된다."""
        cfg.save_window(main_window)
        assert cfg._qs.value("window/state") is not None


class TestConfigManagerRestoreWindow:
    def test_restore_window_returns_false_when_nothing_saved(self, cfg, main_window):
        """저장된 데이터 없으면 False 반환."""
        result = cfg.restore_window(main_window)
        assert result is False

    def test_restore_window_returns_true_after_save(self, cfg, main_window):
        """save 후 restore → True 반환."""
        cfg.save_window(main_window)
        result = cfg.restore_window(main_window)
        assert result is True

    def test_restore_window_no_crash_with_invalid_state(self, cfg, main_window):
        """잘못된 state가 있어도 크래시 없어야 함."""
        cfg._qs.setValue("window/geometry", b"invalid_data")
        cfg.restore_window(main_window)  # 크래시 없어야 함


class TestConfigManagerSaveTraceFilter:
    def test_save_restore_trace_filter_roundtrip(self, cfg):
        """save_trace_filter() 후 restore_trace_filter() → 동일한 값."""
        cfg.save_trace_filter("1A0", "7FF", False)
        fid, fmask, auto = cfg.restore_trace_filter()
        assert fid   == "1A0"
        assert fmask == "7FF"
        assert auto  is False

    def test_save_restore_auto_scroll_true(self, cfg):
        cfg.save_trace_filter("", "", True)
        _, _, auto = cfg.restore_trace_filter()
        assert auto is True


class TestConfigManagerSaveGraphWindow:
    def test_save_restore_graph_window(self, cfg):
        cfg.save_graph_window(10)
        assert cfg.restore_graph_window() == 10

    def test_restore_graph_window_default(self, cfg):
        assert cfg.restore_graph_window() == 30


class TestConfigManagerSaveLogPath:
    def test_save_restore_log_path(self, cfg):
        cfg.save_log_path("/tmp/my_log.asc")
        assert cfg.restore_log_path() == "/tmp/my_log.asc"

    def test_restore_log_path_default_empty(self, cfg):
        assert cfg.restore_log_path() == ""
