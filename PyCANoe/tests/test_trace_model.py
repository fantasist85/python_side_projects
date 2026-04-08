# tests/test_trace_model.py
"""
TraceModel — QAbstractTableModel 단위 테스트.

검증 항목:
  - append_batch() 배치 삽입 및 rowCount 정확성
  - ForegroundRole 컬러링 (is_tx → 파랑, is_error → 빨강, Rx → None)
  - SW ID 필터 (set_filter / clear_filter)
  - MAX_ROWS 초과 시 오래된 행 자동 제거
  - get_row() 경계값
  - DisplayRole 각 컬럼 표시값
"""
import pytest
from PySide6.QtCore import Qt
from models.trace_model import TraceModel, COLOR_TX, COLOR_ERROR, _COLUMNS
from models.parsed_message import ParsedMessage


# ── 헬퍼 ──────────────────────────────────────────────────────────────────
def make_msg(
    ch_id=0, timestamp=1.0, arb_id=0x1A0, dlc=8,
    data=b'\x01\x02\x03\x04\x05\x06\x07\x08',
    is_tx=False, is_error=False, is_fd=False,
    signals=None, msg_name=None,
) -> ParsedMessage:
    return ParsedMessage(
        ch_id=ch_id, timestamp=timestamp, arb_id=arb_id,
        dlc=dlc, data=data, is_tx=is_tx, is_error=is_error, is_fd=is_fd,
        signals=signals, msg_name=msg_name,
    )


@pytest.fixture
def model(qapp):
    return TraceModel()


# ── 기본 동작 ──────────────────────────────────────────────────────────────
class TestTraceModelBasic:
    def test_initial_empty(self, model):
        assert model.rowCount() == 0

    def test_column_count(self, model):
        assert model.columnCount() == len(_COLUMNS)

    def test_append_batch_increases_row_count(self, model):
        model.append_batch([make_msg(), make_msg(arb_id=0x200)])
        assert model.rowCount() == 2

    def test_append_empty_batch_noop(self, model):
        model.append_batch([])
        assert model.rowCount() == 0

    def test_clear_resets(self, model):
        model.append_batch([make_msg()] * 5)
        model.clear()
        assert model.rowCount() == 0

    def test_get_row_valid(self, model):
        msg = make_msg(arb_id=0x100)
        model.append_batch([msg])
        assert model.get_row(0) is msg

    def test_get_row_out_of_range_returns_none(self, model):
        assert model.get_row(0) is None
        model.append_batch([make_msg()])
        assert model.get_row(99) is None


# ── DisplayRole 컬럼 표시값 ────────────────────────────────────────────────
class TestTraceModelDisplay:
    def _data(self, model, row, col_name):
        col = _COLUMNS.index(col_name)
        return model.data(model.index(row, col), Qt.DisplayRole)

    def test_ch_column(self, model):
        model.append_batch([make_msg(ch_id=2)])
        assert self._data(model, 0, "Ch") == "3"   # 0-based → 1-based

    def test_timestamp_column(self, model):
        model.append_batch([make_msg(timestamp=12.3456)])
        assert self._data(model, 0, "Timestamp") == "12.3456"

    def test_type_can(self, model):
        model.append_batch([make_msg()])
        assert self._data(model, 0, "Type") == "CAN"

    def test_type_fd(self, model):
        model.append_batch([make_msg(is_fd=True)])
        assert self._data(model, 0, "Type") == "FD"

    def test_type_err(self, model):
        model.append_batch([make_msg(is_error=True)])
        assert self._data(model, 0, "Type") == "ERR"

    def test_id_column(self, model):
        model.append_batch([make_msg(arb_id=0x1A0)])
        assert self._data(model, 0, "ID") == "1A0"

    def test_dlc_column(self, model):
        model.append_batch([make_msg(dlc=4, data=b'\x00'*4)])
        assert self._data(model, 0, "DLC") == "4"

    def test_data_hex_column(self, model):
        model.append_batch([make_msg(data=b'\xAB\xCD')])
        assert self._data(model, 0, "Data (HEX)") == "AB CD"

    def test_signal_column_with_dbc(self, model):
        model.append_batch([make_msg(
            signals={"EngSpeed": 1200.0},
            msg_name="EngineData",
        )])
        result = self._data(model, 0, "Signal (DBC)")
        assert "EngineData" in result
        assert "EngSpeed" in result

    def test_signal_column_no_dbc(self, model):
        model.append_batch([make_msg(signals=None)])
        assert self._data(model, 0, "Signal (DBC)") == ""

    def test_invalid_index_returns_none(self, model):
        assert model.data(model.index(-1, 0), Qt.DisplayRole) is None


# ── ForegroundRole 컬러링 ─────────────────────────────────────────────────
class TestTraceModelColoring:
    def _fg(self, model, row=0):
        return model.data(model.index(row, 0), Qt.ForegroundRole)

    def test_rx_foreground_none(self, model):
        model.append_batch([make_msg(is_tx=False, is_error=False)])
        assert self._fg(model) is None

    def test_tx_foreground_blue(self, model):
        model.append_batch([make_msg(is_tx=True)])
        assert self._fg(model) == COLOR_TX

    def test_error_foreground_red(self, model):
        model.append_batch([make_msg(is_error=True)])
        assert self._fg(model) == COLOR_ERROR

    def test_error_takes_priority_over_tx(self, model):
        # is_error가 is_tx보다 우선 (data()에서 is_error 먼저 체크)
        model.append_batch([make_msg(is_tx=True, is_error=True)])
        assert self._fg(model) == COLOR_ERROR


# ── SW ID 필터 ────────────────────────────────────────────────────────────
class TestTraceModelFilter:
    def test_filter_passes_matching_id(self, model):
        model.set_filter(0x1A0, 0x7FF)
        model.append_batch([make_msg(arb_id=0x1A0)])
        assert model.rowCount() == 1

    def test_filter_blocks_non_matching_id(self, model):
        model.set_filter(0x1A0, 0x7FF)
        model.append_batch([make_msg(arb_id=0x200)])
        assert model.rowCount() == 0

    def test_filter_with_mask(self, model):
        # mask=0x700 → 0x1A0 & 0x700 == 0x100, 0x1B0 & 0x700 == 0x100
        model.set_filter(0x100, 0x700)
        model.append_batch([make_msg(arb_id=0x1A0), make_msg(arb_id=0x1B0)])
        assert model.rowCount() == 2

    def test_clear_filter(self, model):
        model.set_filter(0x1A0, 0x7FF)
        model.clear_filter()
        model.append_batch([make_msg(arb_id=0x200)])
        assert model.rowCount() == 1

    def test_filter_applies_only_to_new_batch(self, model):
        # 필터 설정 전에 추가된 행은 유지
        model.append_batch([make_msg(arb_id=0x200)])
        model.set_filter(0x1A0, 0x7FF)
        model.append_batch([make_msg(arb_id=0x200)])   # 필터로 차단
        assert model.rowCount() == 1   # 기존 1개만 남음


# ── MAX_ROWS 제한 ─────────────────────────────────────────────────────────
class TestTraceModelMaxRows:
    def test_overflow_removes_old_rows(self, model):
        # MAX_ROWS = 100_000이므로 직접 override하여 테스트
        # 1건씩 순차 삽입 → 오래된 행이 밀려나는지 확인
        model.MAX_ROWS = 5
        for i in range(7):
            model.append_batch([make_msg(arb_id=i)])
        assert model.rowCount() == 5

    def test_overflow_keeps_newest(self, model):
        # MAX_ROWS=3, 5개를 한 번에 → 최신 3개(arb_id 2,3,4)만 유지
        model.MAX_ROWS = 3
        msgs = [make_msg(arb_id=i) for i in range(5)]
        model.append_batch(msgs)
        assert model.rowCount() == 3
        # 배치 내부 잘라내기: 뒤에서 MAX_ROWS개 유지
        assert model.get_row(0).arb_id == 2
        assert model.get_row(2).arb_id == 4

    def test_overflow_sequential_keeps_newest(self, model):
        # 1건씩 넣어도 최신 MAX_ROWS개만 유지
        model.MAX_ROWS = 3
        for i in range(6):
            model.append_batch([make_msg(arb_id=i)])
        assert model.rowCount() == 3
        assert model.get_row(0).arb_id == 3
        assert model.get_row(2).arb_id == 5
