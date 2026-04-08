# tests/test_config_manager.py
"""
ConfigManager — QSettings 저장/복원 단위 테스트.

검증 항목:
  - save_channels / restore_channels 왕복 정확성
  - restore_channels 저장 없으면 빈 리스트 반환
  - save_trace_filter / restore_trace_filter 왕복
  - save_graph_window / restore_graph_window 왕복
  - save_log_path / restore_log_path 왕복
  - SETTINGS_VERSION 마이그레이션 (v0 → v1 초기화)
"""
import pytest
from PySide6.QtCore import QSettings
from app.config_manager import ConfigManager, SETTINGS_VERSION
from core.channel_manager import ChannelConfig


@pytest.fixture(autouse=True)
def clean_settings(qapp, tmp_path):
    """각 테스트마다 격리된 QSettings 사용."""
    # QSettings를 임시 INI 파일로 격리
    orig_format = QSettings.defaultFormat()
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    ini = str(tmp_path / "test_settings.ini")

    # ConfigManager 내부 QSettings 경로를 임시 파일로 패치
    import unittest.mock as mock
    with mock.patch(
        'app.config_manager.QSettings',
        lambda *a, **kw: QSettings(ini, QSettings.Format.IniFormat)
    ):
        yield

    QSettings.setDefaultFormat(orig_format)


@pytest.fixture
def cfg(clean_settings):
    return ConfigManager()


# ── channels 저장/복원 ────────────────────────────────────────────────────
class TestConfigManagerChannels:
    def test_restore_channels_empty_when_nothing_saved(self, cfg):
        result = cfg.restore_channels()
        assert result == []

    def test_save_restore_single_channel(self, cfg):
        config = ChannelConfig(
            interface="virtual", channel=0, bitrate=500_000,
            fd_mode=False, data_bitrate=2_000_000, app_name="PyCANoe",
        )
        cfg.save_channels([(0, config)])
        restored = cfg.restore_channels()
        assert len(restored) == 1
        ch_id, rcfg = restored[0]
        assert ch_id == 0
        assert rcfg.interface == "virtual"
        assert rcfg.bitrate == 500_000
        assert rcfg.fd_mode is False
        assert rcfg.app_name == "PyCANoe"

    def test_save_restore_multiple_channels(self, cfg):
        configs = [
            (0, ChannelConfig("virtual", 0, 500_000)),
            (1, ChannelConfig("vector",  1, 250_000)),
        ]
        cfg.save_channels(configs)
        restored = cfg.restore_channels()
        assert len(restored) == 2
        ids = [ch_id for ch_id, _ in restored]
        assert 0 in ids and 1 in ids

    def test_save_restore_fd_mode(self, cfg):
        config = ChannelConfig(
            interface="vector", channel=0, bitrate=500_000,
            fd_mode=True, data_bitrate=4_000_000,
        )
        cfg.save_channels([(0, config)])
        _, rcfg = cfg.restore_channels()[0]
        assert rcfg.fd_mode is True
        assert rcfg.data_bitrate == 4_000_000

    def test_save_restore_db_path(self, cfg):
        config = ChannelConfig(
            interface="virtual", channel=0, bitrate=500_000,
            db_path="/path/to/car.dbc",
        )
        cfg.save_channels([(0, config)])
        _, rcfg = cfg.restore_channels()[0]
        assert rcfg.db_path == "/path/to/car.dbc"


# ── trace filter 저장/복원 ────────────────────────────────────────────────
class TestConfigManagerTraceFilter:
    def test_restore_defaults(self, cfg):
        fid, fmask, auto = cfg.restore_trace_filter()
        assert fid == ""
        assert fmask == ""
        assert auto is True

    def test_save_restore_filter(self, cfg):
        cfg.save_trace_filter("1A0", "7FF", False)
        fid, fmask, auto = cfg.restore_trace_filter()
        assert fid == "1A0"
        assert fmask == "7FF"
        assert auto is False

    def test_auto_scroll_true(self, cfg):
        cfg.save_trace_filter("", "", True)
        _, _, auto = cfg.restore_trace_filter()
        assert auto is True


# ── graph window 저장/복원 ────────────────────────────────────────────────
class TestConfigManagerGraph:
    def test_restore_default_rolling_sec(self, cfg):
        assert cfg.restore_graph_window() == 30

    def test_save_restore_rolling_sec(self, cfg):
        cfg.save_graph_window(10)
        assert cfg.restore_graph_window() == 10

    def test_save_restore_rolling_sec_zero(self, cfg):
        cfg.save_graph_window(0)
        assert cfg.restore_graph_window() == 0


# ── log path 저장/복원 ────────────────────────────────────────────────────
class TestConfigManagerLogPath:
    def test_restore_empty_default(self, cfg):
        assert cfg.restore_log_path() == ""

    def test_save_restore_log_path(self, cfg):
        cfg.save_log_path("/tmp/test.asc")
        assert cfg.restore_log_path() == "/tmp/test.asc"


# ── 마이그레이션 ──────────────────────────────────────────────────────────
class TestConfigManagerMigration:
    def test_migration_v0_clears_settings(self, cfg):
        # v0 데이터를 심어두고 _migrate() 호출 시 초기화되는지 확인
        cfg._qs.setValue("settings_version", 0)
        cfg._qs.setValue("some_old_key", "old_value")
        cfg._migrate()
        # 마이그레이션 후 old_key 사라지고 version이 갱신되어야 함
        assert int(cfg._qs.value("settings_version", 0)) == SETTINGS_VERSION
        assert cfg._qs.value("some_old_key") is None

    def test_no_migration_needed_when_current_version(self, cfg):
        cfg._qs.setValue("settings_version", SETTINGS_VERSION)
        cfg._qs.setValue("keep_key", "keep_value")
        cfg._migrate()
        assert cfg._qs.value("keep_key") == "keep_value"
