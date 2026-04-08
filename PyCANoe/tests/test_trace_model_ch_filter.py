# tests/test_trace_model_ch_filter.py
"""
TraceModel 채널 필터 단위 테스트.

검증 항목:
  - set_ch_filter() / clear_ch_filter() 상태 설정
  - append_batch()에서 ch_filter 적용 — 지정 채널 메시지만 표시
  - ID 필터 + 채널 필터 동시 적용 (AND 조건)
  - clear_ch_filter() 후 전체 표시 복원
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from models.parsed_message import ParsedMessage
from models.trace_model import TraceModel


def _msg(ch_id: int = 0, arb_id: int = 0x100) -> ParsedMessage:
    return ParsedMessage(
        ch_id=ch_id, timestamp=0.0, arb_id=arb_id, dlc=8, data=b"\x00" * 8
    )


@pytest.fixture
def model():
    return TraceModel()


# ── 초기 상태 ─────────────────────────────────────────────────────────────

class TestChFilterInit:
    def test_ch_filter_none_by_default(self, model):
        assert model._ch_filter is None

    def test_no_filter_passes_all(self, model):
        model.append_batch([_msg(0), _msg(1), _msg(2)])
        assert model.rowCount() == 3


# ── set_ch_filter / clear_ch_filter ──────────────────────────────────────

class TestSetChFilter:
    def test_set_ch_filter_stores_value(self, model):
        model.set_ch_filter(2)
        assert model._ch_filter == 2

    def test_clear_ch_filter_sets_none(self, model):
        model.set_ch_filter(1)
        model.clear_ch_filter()
        assert model._ch_filter is None

    def test_ch_filter_zero_is_valid(self, model):
        model.set_ch_filter(0)
        assert model._ch_filter == 0

    def test_set_ch_filter_none_equivalent_to_all(self, model):
        model.set_ch_filter(None)
        assert model._ch_filter is None


# ── append_batch 채널 필터 적용 ───────────────────────────────────────────

class TestChFilterAppendBatch:
    def test_filter_ch0_only_ch0_shown(self, model):
        model.set_ch_filter(0)
        model.append_batch([_msg(0), _msg(1), _msg(2)])
        assert model.rowCount() == 1
        assert model.get_row(0).ch_id == 0

    def test_filter_ch1_only_ch1_shown(self, model):
        model.set_ch_filter(1)
        model.append_batch([_msg(0), _msg(1), _msg(2)])
        assert model.rowCount() == 1
        assert model.get_row(0).ch_id == 1

    def test_filter_ch3_no_match_zero_rows(self, model):
        model.set_ch_filter(3)
        model.append_batch([_msg(0), _msg(1)])
        assert model.rowCount() == 0

    def test_clear_ch_filter_shows_all(self, model):
        model.set_ch_filter(0)
        model.append_batch([_msg(0)])
        model.clear_ch_filter()
        model.append_batch([_msg(1), _msg(2)])
        # 채널 필터 없으면 새 배치 전부 통과
        assert model.rowCount() == 3

    def test_multiple_msgs_same_channel(self, model):
        model.set_ch_filter(0)
        model.append_batch([_msg(0, 0x100), _msg(0, 0x200), _msg(1, 0x300)])
        assert model.rowCount() == 2

    def test_none_filter_passes_all_channels(self, model):
        model.set_ch_filter(None)
        model.append_batch([_msg(0), _msg(1), _msg(2), _msg(3)])
        assert model.rowCount() == 4


# ── ID 필터 + 채널 필터 동시 적용 ────────────────────────────────────────

class TestChFilterWithIdFilter:
    def test_id_and_ch_filter_both_applied(self, model):
        """ID 필터(0x100) AND 채널 필터(ch=0) — 둘 다 만족하는 메시지만 통과."""
        model.set_filter(0x100, 0x7FF)
        model.set_ch_filter(0)
        model.append_batch([
            _msg(ch_id=0, arb_id=0x100),   # 통과 (ch=0, id=0x100)
            _msg(ch_id=0, arb_id=0x200),   # 차단 (ch=0, id≠0x100)
            _msg(ch_id=1, arb_id=0x100),   # 차단 (ch≠0, id=0x100)
            _msg(ch_id=1, arb_id=0x200),   # 차단
        ])
        assert model.rowCount() == 1
        assert model.get_row(0).ch_id == 0
        assert model.get_row(0).arb_id == 0x100
