# tests/test_parsed_message.py
"""
ParsedMessage 단위 테스트.
STEP 1 완료 기준: pm.ch_id = 1 시도 → FrozenInstanceError 발생.
"""
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from models.parsed_message import ParsedMessage


class TestParsedMessageFrozen:
    """불변성 검증."""

    def test_frozen_ch_id(self) -> None:
        """STEP 1 완료 기준: ch_id 대입 시 FrozenInstanceError."""
        pm = ParsedMessage(
            ch_id=0, timestamp=0.0, arb_id=0x1A0, dlc=8, data=b"\x00" * 8
        )
        with pytest.raises(Exception):   # FrozenInstanceError (dataclasses 내부 예외)
            pm.ch_id = 1  # type: ignore[misc]

    def test_frozen_data(self) -> None:
        """data 필드 수정 시 FrozenInstanceError."""
        pm = ParsedMessage(
            ch_id=0, timestamp=0.0, arb_id=0x100, dlc=4, data=b"\xAA\xBB\xCC\xDD"
        )
        with pytest.raises(Exception):
            pm.data = b"\x00" * 4  # type: ignore[misc]

    def test_frozen_signals(self) -> None:
        """signals 필드 수정 시 FrozenInstanceError."""
        pm = ParsedMessage(
            ch_id=0, timestamp=1.0, arb_id=0x200, dlc=8,
            data=b"\x00" * 8, signals={"Speed": 100.0}
        )
        with pytest.raises(Exception):
            pm.signals = None  # type: ignore[misc]


class TestParsedMessageFields:
    """필드 존재 및 기본값 검증."""

    def test_default_flags(self) -> None:
        """is_fd, is_remote, is_error, is_tx, is_brs 기본값은 모두 False."""
        pm = ParsedMessage(
            ch_id=0, timestamp=0.0, arb_id=0x1A0, dlc=8, data=b"\x00" * 8
        )
        assert pm.is_fd     is False
        assert pm.is_remote is False
        assert pm.is_error  is False
        assert pm.is_tx     is False
        assert pm.is_brs    is False

    def test_is_tx_field_exists(self) -> None:
        """is_tx 필드가 존재하고 설정 가능해야 한다."""
        pm = ParsedMessage(
            ch_id=1, timestamp=0.5, arb_id=0x300, dlc=8,
            data=b"\x01" * 8, is_tx=True
        )
        assert pm.is_tx is True

    def test_is_brs_field_exists(self) -> None:
        """is_brs 필드가 존재하고 설정 가능해야 한다."""
        pm = ParsedMessage(
            ch_id=0, timestamp=0.0, arb_id=0x1A0, dlc=8,
            data=b"\x00" * 8, is_fd=True, is_brs=True
        )
        assert pm.is_brs is True

    def test_signals_none_by_default(self) -> None:
        """DBC 없을 때 signals, msg_name은 None."""
        pm = ParsedMessage(
            ch_id=0, timestamp=0.0, arb_id=0x1A0, dlc=8, data=b"\x00" * 8
        )
        assert pm.signals  is None
        assert pm.msg_name is None

    def test_signals_with_values(self) -> None:
        """signals 딕셔너리 정상 저장."""
        sigs = {"EngSpeed": 1200.0, "EngTemp": 90.0}
        pm = ParsedMessage(
            ch_id=0, timestamp=0.0, arb_id=0x1A0, dlc=8,
            data=b"\x00" * 8, signals=sigs, msg_name="EngineData"
        )
        assert pm.signals  == sigs
        assert pm.msg_name == "EngineData"


class TestParsedMessageCANFD:
    """CAN FD DLC 범위 검증 (매핑은 상위 레이어에서 처리)."""

    @pytest.mark.parametrize("dlc", [9, 10, 11, 12, 13, 14, 15])
    def test_can_fd_dlc_stored(self, dlc: int) -> None:
        """CAN FD DLC(9~15) 값이 그대로 저장되어야 한다."""
        pm = ParsedMessage(
            ch_id=0, timestamp=0.0, arb_id=0x1A0,
            dlc=dlc, data=b"\x00" * 8, is_fd=True
        )
        assert pm.dlc == dlc


class TestParsedMessageLIN:
    """LIN Frame ID 추출 규칙 검증."""

    def test_lin_arb_id_mask(self) -> None:
        """LIN arb_id & 0x3F 로 Frame ID 추출 가능해야 한다."""
        protected_id = 0xC5   # Frame ID=5, 패리티 비트 포함
        pm = ParsedMessage(
            ch_id=2, timestamp=0.0, arb_id=protected_id, dlc=4,
            data=b"\x01\x02\x03\x04"
        )
        assert (pm.arb_id & 0x3F) == 0x05


class TestParsedMessageRepr:
    """repr 문자열 형식 확인."""

    def test_repr_contains_arb_id(self) -> None:
        pm = ParsedMessage(
            ch_id=0, timestamp=100.1234, arb_id=0x1A0, dlc=8,
            data=b"\x01\x02\x03\x04\x05\x06\x07\x08"
        )
        r = repr(pm)
        assert "1A0" in r
        assert "100.1234" in r

    def test_repr_tx_flag(self) -> None:
        pm = ParsedMessage(
            ch_id=0, timestamp=0.0, arb_id=0x100, dlc=2,
            data=b"\xAA\xBB", is_tx=True
        )
        assert "TX" in repr(pm)
