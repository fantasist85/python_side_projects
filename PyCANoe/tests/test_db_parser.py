# tests/test_db_parser.py
"""
DbParser 단위 테스트.
STEP 4 완료 기준: pytest tests/test_db_parser.py -v 전체 통과.
"""
import sys
import os
from unittest.mock import MagicMock, patch, call

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.db_parser import DbParser, _MISS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_DBC = os.path.join(os.path.dirname(__file__), "fixtures", "sample.dbc")


@pytest.fixture
def db_no_file() -> DbParser:
    """DB 파일 없이 생성한 빈 DbParser."""
    return DbParser()


@pytest.fixture
def db_with_dbc() -> DbParser:
    """sample.dbc가 로드된 DbParser."""
    parser = DbParser()
    ok = parser.load(SAMPLE_DBC)
    assert ok, "sample.dbc 로드 실패"
    return parser


# ---------------------------------------------------------------------------
# DB 없음 → None 반환
# ---------------------------------------------------------------------------

class TestDbParserNoDb:
    def test_decode_returns_none_when_no_db(self, db_no_file: DbParser) -> None:
        """DB 없이 decode 시 (None, None) 반환. exception raise 금지."""
        result = db_no_file.decode_with_name(0x1A0, b"\x00" * 8)
        assert result == (None, None)

    def test_is_loaded_false(self, db_no_file: DbParser) -> None:
        assert db_no_file.is_loaded is False

    def test_db_type_none(self, db_no_file: DbParser) -> None:
        assert db_no_file.db_type is None


# ---------------------------------------------------------------------------
# DBC 로드 및 정상 decode
# ---------------------------------------------------------------------------

class TestDbParserDBC:
    def test_load_valid_dbc(self) -> None:
        parser = DbParser()
        ok = parser.load(SAMPLE_DBC)
        assert ok is True
        assert parser.is_loaded is True
        assert parser.db_type == "dbc"

    def test_load_invalid_path(self) -> None:
        """존재하지 않는 파일 → False 반환, is_loaded=False."""
        parser = DbParser()
        ok = parser.load("/nonexistent/path/to.dbc")
        assert ok is False
        assert parser.is_loaded is False

    def test_load_unsupported_ext(self) -> None:
        """미지원 확장자 → False 반환."""
        parser = DbParser()
        ok = parser.load("/some/file.txt")
        assert ok is False

    def test_decode_known_arb_id(self, db_with_dbc: DbParser) -> None:
        """0x1A0(416) EngineData 디코딩 성공."""
        # EngSpeed=4800rpm (4800/0.25=19200=0x4B00, little-endian 2바이트)
        data = bytes([0x00, 0x4B, 0x5A, 0x40, 0x00, 0x00, 0x00, 0x00])
        signals, msg_name = db_with_dbc.decode_with_name(0x1A0, data)
        assert msg_name == "EngineData"
        assert signals is not None
        assert "EngSpeed" in signals

    def test_decode_unknown_arb_id_returns_none(self, db_with_dbc: DbParser) -> None:
        """DB에 없는 arb_id → (None, None), exception 아님."""
        result = db_with_dbc.decode_with_name(0xDEAD, b"\x00" * 8)
        assert result == (None, None)

    def test_decode_shortcut(self, db_with_dbc: DbParser) -> None:
        """decode() = decode_with_name()[0] 래퍼."""
        data = b"\x00" * 8
        signals_full, _ = db_with_dbc.decode_with_name(0x1A0, data)
        signals_short    = db_with_dbc.decode(0x1A0, data)
        assert signals_full == signals_short


# ---------------------------------------------------------------------------
# _MISS sentinel 캐싱 — Mock으로 1회만 탐색 확인
# ---------------------------------------------------------------------------

class TestMissSentinel:
    def test_miss_sentinel_caches_on_first_miss(self, db_with_dbc: DbParser) -> None:
        """
        DB에 없는 arb_id는 첫 번째 조회 후 _MISS로 캐싱된다.
        이후 동일 arb_id 조회 시 get_message_by_frame_id()가 재호출되지 않아야 한다.
        """
        unknown_id = 0xBEEF
        mock_db = MagicMock()
        mock_db.get_message_by_frame_id.side_effect = KeyError(unknown_id)
        db_with_dbc._db = mock_db

        # 첫 번째 조회
        r1 = db_with_dbc.decode_with_name(unknown_id, b"\x00" * 8)
        assert r1 == (None, None)

        # 두 번째 조회 — 캐시 적중, DB 재탐색 없음
        r2 = db_with_dbc.decode_with_name(unknown_id, b"\x00" * 8)
        assert r2 == (None, None)

        # get_message_by_frame_id 는 딱 1번만 호출돼야 한다
        assert mock_db.get_message_by_frame_id.call_count == 1

    def test_miss_sentinel_is_not_none(self) -> None:
        """_MISS sentinel은 None이 아니어야 한다. None 대체 금지."""
        assert _MISS is not None


# ---------------------------------------------------------------------------
# DB 핫스왑 — clear_cache() 검증
# ---------------------------------------------------------------------------

class TestHotSwap:
    def test_clear_cache_after_load(self) -> None:
        """load() 호출 시 캐시가 초기화된다."""
        parser = DbParser()
        parser.load(SAMPLE_DBC)

        # 캐시에 _MISS 항목 강제 삽입
        parser._msg_def_cache[0xDEAD] = _MISS
        assert 0xDEAD in parser._msg_def_cache

        # 재로드 → clear_cache() 포함
        parser.load(SAMPLE_DBC)
        assert 0xDEAD not in parser._msg_def_cache

    def test_clear_cache_explicit(self, db_with_dbc: DbParser) -> None:
        """명시적 clear_cache() 호출 시 전체 삭제."""
        # 캐시 채우기
        db_with_dbc.decode_with_name(0x1A0, b"\x00" * 8)
        assert len(db_with_dbc._msg_def_cache) > 0

        db_with_dbc.clear_cache()
        assert len(db_with_dbc._msg_def_cache) == 0


# ---------------------------------------------------------------------------
# LIN 분기
# ---------------------------------------------------------------------------

class TestDbParserLIN:
    def test_ldf_branch_miss(self, db_no_file: DbParser) -> None:
        """LIN DB mock으로 unknown frame_id → (None, None)."""
        mock_ldf = MagicMock()
        mock_ldf.get_frame.side_effect = Exception("Frame not found")
        db_no_file._db   = mock_ldf
        db_no_file._type = "ldf"

        result = db_no_file.decode_with_name(0xC5, b"\x01\x02\x03\x04")
        assert result == (None, None)

    def test_ldf_frame_id_extraction(self, db_no_file: DbParser) -> None:
        """LIN Protected ID 0xC5 → frame_id = 0x05 (& 0x3F) で get_frame 호출."""
        mock_frame = MagicMock()
        mock_frame.name = "SomeFrame"
        mock_frame.parse.return_value = {"Signal1": 42.0}

        mock_ldf = MagicMock()
        mock_ldf.get_frame.return_value = mock_frame
        db_no_file._db   = mock_ldf
        db_no_file._type = "ldf"

        signals, name = db_no_file.decode_with_name(0xC5, b"\x01\x02\x03\x04")
        assert name == "SomeFrame"
        assert signals == {"Signal1": 42.0}
        # frame_id = 0xC5 & 0x3F = 0x05
        mock_ldf.get_frame.assert_called_once_with(0x05)


# ---------------------------------------------------------------------------
# decode 실패 → None (exception raise 금지)
# ---------------------------------------------------------------------------

class TestDecodeFailure:
    def test_decode_exception_returns_none(self, db_with_dbc: DbParser) -> None:
        """decode_message 내부에서 예외 발생 시 (None, None) 반환."""
        mock_db = MagicMock()
        mock_msg = MagicMock()
        mock_msg.name = "FakeMsg"
        mock_db.get_message_by_frame_id.return_value = mock_msg
        mock_db.decode_message.side_effect = ValueError("bad data")
        db_with_dbc._db = mock_db
        db_with_dbc.clear_cache()

        result = db_with_dbc.decode_with_name(0x100, b"\xFF" * 8)
        assert result == (None, None)
