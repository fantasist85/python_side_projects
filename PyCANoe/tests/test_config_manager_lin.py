# tests/test_config_manager_lin.py
"""
M8 — ConfigManager bus_type / lin_baud 저장·복원 단위 테스트.

SETTINGS_VERSION = 2 (M8 변경)
마이그레이션: v0→2 (초기화), v1→2 (bus_type/lin_baud 기본값 적용)
"""
import pytest
from unittest.mock import MagicMock, patch
from app.config_manager import ConfigManager, SETTINGS_VERSION
from core.channel_manager import ChannelConfig


# ------------------------------------------------------------------
# 헬퍼
# ------------------------------------------------------------------

def make_manager(stored_version=SETTINGS_VERSION):
    """QSettings를 Mock으로 대체한 ConfigManager."""
    mgr = ConfigManager.__new__(ConfigManager)
    qs = MagicMock()
    qs.value.side_effect = lambda key, default=None, **kw: default
    qs.value("settings_version", 0)
    # settings_version 은 _migrate()에서 별도 처리
    mgr._qs = qs
    return mgr, qs


# ------------------------------------------------------------------
# 1. SETTINGS_VERSION 값 확인
# ------------------------------------------------------------------

def test_settings_version_is_2():
    assert SETTINGS_VERSION == 2


# ------------------------------------------------------------------
# 2. save_channels() — bus_type / lin_baud 저장
# ------------------------------------------------------------------

class TestSaveChannelsLin:
    def test_saves_bus_type_can(self):
        mgr, qs = make_manager()
        cfg = ChannelConfig(interface="virtual", channel=0, bitrate=500_000,
                            bus_type="can")
        mgr.save_channels([(0, cfg)])
        calls = {c.args[0]: c.args[1] for c in qs.setValue.call_args_list}
        assert calls.get("channel/0/bus_type") == "can"

    def test_saves_bus_type_lin(self):
        mgr, qs = make_manager()
        cfg = ChannelConfig(interface="vector_lin", channel=1, bitrate=19200,
                            bus_type="lin", lin_baud=19200)
        mgr.save_channels([(1, cfg)])
        calls = {c.args[0]: c.args[1] for c in qs.setValue.call_args_list}
        assert calls.get("channel/1/bus_type") == "lin"

    def test_saves_lin_baud(self):
        mgr, qs = make_manager()
        cfg = ChannelConfig(interface="vector_lin", channel=0, bitrate=9600,
                            bus_type="lin", lin_baud=9600)
        mgr.save_channels([(0, cfg)])
        calls = {c.args[0]: c.args[1] for c in qs.setValue.call_args_list}
        assert calls.get("channel/0/lin_baud") == 9600

    def test_saves_lin_baud_38400(self):
        mgr, qs = make_manager()
        cfg = ChannelConfig(interface="virtual_lin", channel=0, bitrate=38400,
                            bus_type="lin", lin_baud=38400)
        mgr.save_channels([(0, cfg)])
        calls = {c.args[0]: c.args[1] for c in qs.setValue.call_args_list}
        assert calls.get("channel/0/lin_baud") == 38400


# ------------------------------------------------------------------
# 3. restore_channels() — bus_type / lin_baud 복원
# ------------------------------------------------------------------

class TestRestoreChannelsLin:
    def _make_mgr_with_data(self, ch_data: dict):
        """저장된 채널 데이터를 시뮬레이션하는 ConfigManager."""
        mgr = ConfigManager.__new__(ConfigManager)
        qs = MagicMock()

        def value_side_effect(key, default=None, **kw):
            if key == "settings_version":
                return SETTINGS_VERSION
            if key == "channel/count":
                return 1
            return ch_data.get(key, default)

        qs.value.side_effect = value_side_effect
        qs.contains.return_value = True
        mgr._qs = qs
        return mgr

    def test_restores_bus_type_lin(self):
        mgr = self._make_mgr_with_data({
            "channel/0/interface": "virtual_lin",
            "channel/0/channel": 0,
            "channel/0/bitrate": 19200,
            "channel/0/bus_type": "lin",
            "channel/0/lin_baud": 19200,
        })
        result = mgr.restore_channels()
        assert len(result) == 1
        ch_id, cfg = result[0]
        assert cfg.bus_type == "lin"

    def test_restores_lin_baud(self):
        mgr = self._make_mgr_with_data({
            "channel/0/interface": "vector_lin",
            "channel/0/channel": 1,
            "channel/0/bitrate": 9600,
            "channel/0/bus_type": "lin",
            "channel/0/lin_baud": 9600,
        })
        result = mgr.restore_channels()
        ch_id, cfg = result[0]
        assert cfg.lin_baud == 9600

    def test_restores_bus_type_default_can(self):
        """bus_type 저장값 없을 때 기본값 "can" 복원."""
        mgr = self._make_mgr_with_data({
            "channel/0/interface": "virtual",
            "channel/0/channel": 0,
            "channel/0/bitrate": 500_000,
            # bus_type 없음 → 기본값
        })
        result = mgr.restore_channels()
        ch_id, cfg = result[0]
        assert cfg.bus_type == "can"

    def test_restores_lin_baud_default(self):
        """lin_baud 저장값 없을 때 기본값 19200 복원."""
        mgr = self._make_mgr_with_data({
            "channel/0/interface": "virtual",
            "channel/0/channel": 0,
            "channel/0/bitrate": 500_000,
        })
        result = mgr.restore_channels()
        ch_id, cfg = result[0]
        assert cfg.lin_baud == 19200


# ------------------------------------------------------------------
# 4. 마이그레이션 — v1 → v2
# ------------------------------------------------------------------

class TestMigrationV1ToV2:
    def test_v1_migrates_to_v2(self):
        mgr = ConfigManager.__new__(ConfigManager)
        qs = MagicMock()
        qs.value.side_effect = lambda key, default=None, **kw: \
            1 if key == "settings_version" else default
        mgr._qs = qs
        mgr._migrate()
        # v1→v2: settings_version 업데이트, clear() 미호출
        qs.clear.assert_not_called()
        set_calls = {c.args[0]: c.args[1] for c in qs.setValue.call_args_list}
        assert set_calls.get("settings_version") == SETTINGS_VERSION

    def test_v0_migrates_clears_settings(self):
        mgr = ConfigManager.__new__(ConfigManager)
        qs = MagicMock()
        qs.value.side_effect = lambda key, default=None, **kw: \
            0 if key == "settings_version" else default
        mgr._qs = qs
        mgr._migrate()
        qs.clear.assert_called_once()

    def test_already_v2_no_migration(self):
        mgr = ConfigManager.__new__(ConfigManager)
        qs = MagicMock()
        qs.value.side_effect = lambda key, default=None, **kw: \
            SETTINGS_VERSION if key == "settings_version" else default
        mgr._qs = qs
        mgr._migrate()
        qs.clear.assert_not_called()
        qs.setValue.assert_not_called()
