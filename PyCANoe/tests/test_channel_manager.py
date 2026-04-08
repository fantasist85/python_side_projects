# tests/test_channel_manager.py
"""
ChannelManager 단위 테스트.
커버리지 목표: 미커버 라인 (38-39, 46-85) 처리.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

pytest.importorskip("PySide6")

from unittest.mock import MagicMock, patch
from PySide6.QtWidgets import QApplication
from core.channel_manager import ChannelManager, ChannelConfig, ChannelContext

_app = QApplication.instance() or QApplication([])


@pytest.fixture
def dispatcher():
    d = MagicMock()
    d.on_message = MagicMock()
    d.on_error = MagicMock()
    return d


@pytest.fixture
def manager(dispatcher):
    return ChannelManager(dispatcher)


def _cfg(ch: int = 0) -> ChannelConfig:
    return ChannelConfig(interface="virtual", channel=ch, bitrate=500_000)


class TestChannelManagerAddChannel:
    def test_add_channel_returns_context(self, manager):
        """add_channel() → ChannelContext 반환."""
        ctx = manager.add_channel(0, _cfg(0))
        assert isinstance(ctx, ChannelContext)
        assert ctx.ch_id == 0

    def test_add_channel_stores_in_dict(self, manager):
        """추가된 채널이 내부 dict에 저장된다."""
        manager.add_channel(0, _cfg(0))
        assert manager.get(0) is not None

    def test_add_multiple_channels(self, manager):
        """최대 4채널까지 추가 가능."""
        for i in range(4):
            manager.add_channel(i, _cfg(i))
        assert len(manager.all()) == 4

    def test_add_channel_exceeds_max_raises(self, manager):
        """5채널 추가 시 AssertionError 발생."""
        for i in range(4):
            manager.add_channel(i, _cfg(i))
        with pytest.raises(AssertionError):
            manager.add_channel(4, _cfg(4))

    def test_add_duplicate_channel_raises(self, manager):
        """같은 ch_id 중복 추가 시 AssertionError 발생."""
        manager.add_channel(0, _cfg(0))
        with pytest.raises(AssertionError):
            manager.add_channel(0, _cfg(0))

    def test_add_channel_worker_created(self, manager):
        """add_channel() 시 CANWorker가 생성된다."""
        ctx = manager.add_channel(0, _cfg(0))
        assert ctx.worker is not None

    def test_add_channel_db_parser_created(self, manager):
        """add_channel() 시 DbParser가 생성된다."""
        ctx = manager.add_channel(0, _cfg(0))
        assert ctx.db_parser is not None


class TestChannelManagerRemoveChannel:
    def test_remove_channel_stops_worker(self, manager):
        """remove_channel() 시 worker.stop()이 호출된다."""
        ctx = manager.add_channel(0, _cfg(0))
        # worker를 mock으로 교체
        ctx.worker.stop = MagicMock()
        manager.remove_channel(0)
        ctx.worker.stop.assert_called_once()

    def test_remove_channel_removes_from_dict(self, manager):
        """remove_channel() 후 get()은 None 반환."""
        manager.add_channel(0, _cfg(0))
        manager.remove_channel(0)
        assert manager.get(0) is None

    def test_remove_nonexistent_channel_no_crash(self, manager):
        """존재하지 않는 채널 remove → 크래시 없어야 함."""
        manager.remove_channel(99)  # 크래시 없어야 함

    def test_remove_channel_with_sim_worker_stops_sim(self, manager):
        """sim_worker가 있으면 함께 stop()된다."""
        ctx = manager.add_channel(0, _cfg(0))
        sim_mock = MagicMock()
        ctx.sim_worker = sim_mock
        ctx.worker.stop = MagicMock()
        manager.remove_channel(0)
        sim_mock.stop.assert_called_once()


class TestChannelManagerGetAll:
    def test_get_returns_none_for_missing(self, manager):
        assert manager.get(99) is None

    def test_all_returns_empty_initially(self, manager):
        assert manager.all() == []

    def test_all_returns_list_of_contexts(self, manager):
        manager.add_channel(0, _cfg(0))
        manager.add_channel(1, _cfg(1))
        ctxs = manager.all()
        assert len(ctxs) == 2
        assert all(isinstance(c, ChannelContext) for c in ctxs)
