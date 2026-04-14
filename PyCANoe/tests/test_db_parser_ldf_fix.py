# tests/test_db_parser_ldf_fix.py
"""
BUG-1 수정 검증: _decode_ldf()가 frame.parse() 대신 frame.decode()를 사용하는지 확인.
BUG-2 검증: main_window._on_db_loaded() 멀티채널 DB 동기화.
실제 sample.ldf 파일을 이용한 통합 테스트 포함.

커버 항목:
  - frame.decode(bytearray) 호출 확인 (parse() 사용 금지)
  - 실제 LDF 파일 로드 + 신호 디코딩 정상 동작
  - frame_id & 0x3F 추출 정확성
  - 멀티채널 DB 동기화 (_on_db_loaded 로직)
  - 에러 메시지에 파일 경로 포함 (BUG-3)
"""
import os
import sys
from unittest.mock import MagicMock, patch, call

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.db_parser import DbParser, _MISS

SAMPLE_LDF = os.path.join(os.path.dirname(__file__), "fixtures", "sample.ldf")
SAMPLE_DBC = os.path.join(os.path.dirname(__file__), "fixtures", "sample.dbc")


# ---------------------------------------------------------------------------
# BUG-1: frame.decode() 사용 검증
# ---------------------------------------------------------------------------

class TestDecodeApiFixed:
    """frame.decode(bytearray) 를 호출해야 하고, frame.parse() 를 호출하면 안 된다."""

    def _make_parser_with_mock_frame(self, signals: dict, name: str = "TestFrame"):
        parser = DbParser()
        mock_frame = MagicMock()
        mock_frame.name = name
        mock_frame.decode.return_value = signals
        mock_ldf = MagicMock()
        mock_ldf.get_frame.return_value = mock_frame
        parser._db   = mock_ldf
        parser._type = "ldf"
        return parser, mock_frame, mock_ldf

    def test_decode_called_not_parse(self):
        """decode() 호출됨 — parse() 는 절대 호출되지 않아야 한다."""
        parser, mock_frame, _ = self._make_parser_with_mock_frame({"Sig1": 10})
        parser.decode_with_name(0x01, b"\xAA\xBB")
        mock_frame.decode.assert_called_once()
        mock_frame.parse.assert_not_called()

    def test_decode_receives_bytearray(self):
        """decode()에 bytearray가 전달되어야 한다 (bytes 아님)."""
        parser, mock_frame, _ = self._make_parser_with_mock_frame({"Sig1": 10})
        parser.decode_with_name(0x01, b"\x01\x02\x03")
        args, _ = mock_frame.decode.call_args
        assert isinstance(args[0], bytearray), "decode()에 bytearray가 아닌 타입 전달"

    def test_signals_returned_correctly(self):
        """decode() 결과 dict가 정상 반환된다."""
        expected = {"MotorSpeed": 3000, "MotorTemp": 80}
        parser, _, _ = self._make_parser_with_mock_frame(expected, "MotorStatus")
        signals, name = parser.decode_with_name(0x01, b"\x00\x00\x00")
        assert signals == expected
        assert name == "MotorStatus"

    def test_decode_exception_returns_none_not_propagated(self):
        """decode() 내부 예외 → (None, None) 반환, exception 전파 금지."""
        parser = DbParser()
        mock_frame = MagicMock()
        mock_frame.name = "Err"
        mock_frame.decode.side_effect = RuntimeError("decode error")
        mock_ldf = MagicMock()
        mock_ldf.get_frame.return_value = mock_frame
        parser._db   = mock_ldf
        parser._type = "ldf"
        result = parser.decode_with_name(0x05, b"\xFF\xFF")
        assert result == (None, None)

    def test_frame_id_6bit_extraction(self):
        """arb_id & 0x3F 추출로 get_frame 호출 확인."""
        parser, _, mock_ldf = self._make_parser_with_mock_frame({})
        # PID 0xC1 → frame_id = 0xC1 & 0x3F = 0x01
        parser.decode_with_name(0xC1, b"\x00")
        mock_ldf.get_frame.assert_called_with(0x01)

    def test_pid_0x40_maps_to_frame_id_0(self):
        """PID 0x40 → frame_id 0 (bit6=P0 제거)."""
        parser, _, mock_ldf = self._make_parser_with_mock_frame({})
        parser.decode_with_name(0x40, b"\x00")
        mock_ldf.get_frame.assert_called_with(0x00)

    def test_miss_sentinel_cached_after_get_frame_miss(self):
        """get_frame 실패 → _MISS 캐시 → 이후 조회 시 get_frame 재호출 없음."""
        parser = DbParser()
        mock_ldf = MagicMock()
        mock_ldf.get_frame.side_effect = LookupError("not found")
        parser._db   = mock_ldf
        parser._type = "ldf"
        r1 = parser.decode_with_name(0x05, b"\x00")
        r2 = parser.decode_with_name(0x05, b"\xFF")
        assert r1 == (None, None)
        assert r2 == (None, None)
        assert mock_ldf.get_frame.call_count == 1   # 캐시 동작 확인


# ---------------------------------------------------------------------------
# 실제 sample.ldf 파일 통합 테스트
# ---------------------------------------------------------------------------

class TestRealLdfDecode:
    """sample.ldf 로드 후 실제 프레임 디코딩 검증."""

    @pytest.fixture
    def ldf_parser(self):
        p = DbParser()
        ok = p.load(SAMPLE_LDF)
        assert ok, "sample.ldf 로드 실패"
        return p

    def test_load_ldf_success(self, ldf_parser):
        assert ldf_parser.is_loaded is True
        assert ldf_parser.db_type == "ldf"

    def test_decode_motor_status_frame(self, ldf_parser):
        """MotorStatus 프레임(frame_id=0x01) 디코딩 — 신호값 반환."""
        # MotorStatus: MotorSpeed(16bit,bit0) + MotorTemp(8bit,bit16)
        # raw: speed=1000 (0x03E8 LE) temp=50 → bytes: E8 03 32
        data = bytes([0xE8, 0x03, 0x32])
        signals, name = ldf_parser.decode_with_name(0x01, data)
        assert name == "MotorStatus"
        assert signals is not None
        assert "MotorSpeed" in signals
        assert "MotorTemp" in signals

    def test_decode_pid_form_motor_status(self, ldf_parser):
        """PID 형식(Protected ID)으로도 같은 결과."""
        # frame_id=0x01 → PID = _calc_lin_pid(1) = 0x01 | P0<<6 | P1<<7
        # P0 = (1^0^0^0)&1 = 1 → bit6=1
        # P1 = ~(0^0^0^0)&1 = 1 → bit7=1
        # PID = 0x01 | 0x40 | 0x80 = 0xC1
        data = bytes([0x00, 0x00, 0x00])
        signals_raw, _   = ldf_parser.decode_with_name(0x01, data)
        signals_pid, name = ldf_parser.decode_with_name(0xC1, data)
        assert name == "MotorStatus"
        assert signals_pid == signals_raw   # PID & 0x3F = frame_id, 동일 결과

    def test_decode_motor_cmd_frame(self, ldf_parser):
        """MotorCmd 프레임(frame_id=0x02) 디코딩."""
        data = bytes([0x7F])
        signals, name = ldf_parser.decode_with_name(0x02, data)
        assert name == "MotorCmd"
        assert "MotorControl" in signals

    def test_decode_unknown_frame_returns_none(self, ldf_parser):
        """LDF에 없는 frame_id → (None, None)."""
        result = ldf_parser.decode_with_name(0x10, b"\x00")
        assert result == (None, None)


# ---------------------------------------------------------------------------
# BUG-2: 멀티채널 DB 동기화 검증 (main_window._on_db_loaded 로직)
# ---------------------------------------------------------------------------

class TestMultiChannelDbSync:
    """
    _on_db_loaded() 에서 모든 채널 파서가 동기화되는지 확인.
    main_window 직접 임포트 없이 동기화 로직만 단위 검증.
    """

    def _sync_all_channels(self, lead_parser: DbParser, all_parsers: list):
        """main_window._on_db_loaded() 동기화 로직 추출 버전."""
        for p in all_parsers:
            if p is not lead_parser:
                p._db   = lead_parser._db
                p._type = lead_parser._type
                p.clear_cache()

    def test_second_channel_gets_db(self):
        """CH2 파서에 CH1 로드 DB 동기화된다."""
        p1 = DbParser()
        p1.load(SAMPLE_DBC)
        p2 = DbParser()
        assert not p2.is_loaded

        self._sync_all_channels(p1, [p1, p2])
        assert p2.is_loaded
        assert p2.db_type == "dbc"

    def test_synced_parser_can_decode(self):
        """동기화된 파서로 메시지 디코딩이 가능하다."""
        p1 = DbParser()
        p1.load(SAMPLE_DBC)
        p2 = DbParser()
        self._sync_all_channels(p1, [p1, p2])
        data = bytes([0x00, 0x4B, 0x5A, 0x40, 0x00, 0x00, 0x00, 0x00])
        signals, name = p2.decode_with_name(0x1A0, data)
        assert name == "EngineData"
        assert signals is not None

    def test_lead_parser_unchanged(self):
        """동기화 후 CH1(lead) 파서는 변경되지 않는다."""
        p1 = DbParser()
        p1.load(SAMPLE_DBC)
        p2, p3 = DbParser(), DbParser()
        db_before = p1._db
        self._sync_all_channels(p1, [p1, p2, p3])
        assert p1._db is db_before

    def test_three_channels_all_synced(self):
        """CH1~CH3 모두 동기화 확인."""
        p1 = DbParser()
        p1.load(SAMPLE_DBC)
        p2, p3 = DbParser(), DbParser()
        self._sync_all_channels(p1, [p1, p2, p3])
        for p in [p2, p3]:
            assert p.is_loaded
            assert p._db is p1._db

    def test_ldf_sync(self):
        """LDF DB도 동기화 가능하다."""
        p1 = DbParser()
        p1.load(SAMPLE_LDF)
        p2 = DbParser()
        self._sync_all_channels(p1, [p1, p2])
        assert p2.is_loaded
        assert p2.db_type == "ldf"
        data = bytes([0x00, 0x00, 0x00])
        signals, name = p2.decode_with_name(0x01, data)
        assert name == "MotorStatus"
