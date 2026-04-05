# tests/conftest.py
"""
명세서 Section 11.4 필수 fixture 집중 정의.
각 테스트 파일에서 중복 생성 금지 — 이 파일에서만 정의.
"""
import os
import sys
from typing import Callable

import pytest

# src/ 경로를 Python path에 추가
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.channel_manager import ChannelConfig
from core.db_parser import DbParser
from models.parsed_message import ParsedMessage


@pytest.fixture
def sample_dbc_path() -> str:
    """tests/fixtures/sample.dbc 경로 반환."""
    return os.path.join(os.path.dirname(__file__), "fixtures", "sample.dbc")


@pytest.fixture
def sample_ldf_path() -> str:
    """tests/fixtures/sample.ldf 경로 반환."""
    return os.path.join(os.path.dirname(__file__), "fixtures", "sample.ldf")


@pytest.fixture
def virtual_can_worker():
    """
    virtual 인터페이스 CANWorker. H/W 없이 단위 테스트 전용.
    yield 후 stop() 호출로 스레드 정리 보장.
    """
    from core.can_worker import CANWorker

    cfg    = ChannelConfig(interface="virtual", channel=0, bitrate=500_000)
    worker = CANWorker(ch_id=0, config=cfg, db=DbParser())
    yield worker
    if worker.isRunning():
        worker.stop()


@pytest.fixture
def parsed_msg_factory() -> Callable[..., ParsedMessage]:
    """
    테스트용 ParsedMessage 생성 헬퍼.
    미지정 필드는 기본값 사용.
    """
    def _factory(
        ch_id:     int   = 0,
        timestamp: float = 0.0,
        arb_id:    int   = 0x1A0,
        dlc:       int   = 8,
        data:      bytes = b"\x00" * 8,
        **kwargs,
    ) -> ParsedMessage:
        return ParsedMessage(
            ch_id=ch_id, timestamp=timestamp,
            arb_id=arb_id, dlc=dlc, data=data,
            **kwargs,
        )
    return _factory
