# tests/test_log_worker_csv.py
"""
LogWorker CSV 포맷 — 단위 테스트.

검증 항목:
  - _format_csv() : 출력 필드 순서 및 구분자 정확성
  - _format_csv() : timestamp 소수 6자리 포맷
  - _format_csv() : arb_id 대문자 HEX 표기
  - _format_csv() : is_tx 0/1 정수 표기
  - _format_csv() : data hex (공백 없는 연속 HEX)
  - _write_header() : CSV 헤더 1행 정확성
  - _format_asc() : 기존 ASC 포맷 회귀 방지
  - fmt 파라미터 대소문자 무관 ("CSV", "Csv" 등)
"""
import pytest
from unittest.mock import MagicMock, patch, mock_open
from core.log_worker import LogWorker
from models.parsed_message import ParsedMessage


# ── 헬퍼 ──────────────────────────────────────────────────────────────────

def make_msg(
    ch_id: int = 0,
    timestamp: float = 1.234567,
    arb_id: int = 0x1A0,
    dlc: int = 8,
    data: bytes = b'\x01\x02\x03\x04\x05\x06\x07\x08',
    is_tx: bool = False,
) -> ParsedMessage:
    return ParsedMessage(
        ch_id=ch_id, timestamp=timestamp, arb_id=arb_id,
        dlc=dlc, data=data, is_tx=is_tx,
    )


@pytest.fixture
def mock_queue():
    q = MagicMock()
    q.get_batch.return_value = []
    return q


# ── _format_csv() ─────────────────────────────────────────────────────────

class TestLogWorkerFormatCsv:
    def test_csv_field_count(self, mock_queue):
        """CSV 한 줄에 필드가 정확히 6개여야 한다."""
        worker = LogWorker(mock_queue, "/tmp/test.csv", fmt="csv")
        line = worker._format_csv(make_msg())
        fields = line.strip().split(",")
        assert len(fields) == 6

    def test_csv_timestamp_precision(self, mock_queue):
        """timestamp는 소수점 6자리 형식이어야 한다."""
        worker = LogWorker(mock_queue, "/tmp/test.csv", fmt="csv")
        msg = make_msg(timestamp=1.234567)
        line = worker._format_csv(msg)
        ts_field = line.split(",")[0]
        assert ts_field == "1.234567"

    def test_csv_ch_id_one_based(self, mock_queue):
        """ch_id는 1-based로 출력되어야 한다 (ch_id=0 → '1')."""
        worker = LogWorker(mock_queue, "/tmp/test.csv", fmt="csv")
        line = worker._format_csv(make_msg(ch_id=0))
        ch_field = line.split(",")[1]
        assert ch_field == "1"

    def test_csv_ch_id_3_is_4(self, mock_queue):
        worker = LogWorker(mock_queue, "/tmp/test.csv", fmt="csv")
        line = worker._format_csv(make_msg(ch_id=3))
        ch_field = line.split(",")[1]
        assert ch_field == "4"

    def test_csv_arb_id_uppercase_hex(self, mock_queue):
        """arb_id는 대문자 HEX 표기여야 한다 (공백·0x 접두사 없음)."""
        worker = LogWorker(mock_queue, "/tmp/test.csv", fmt="csv")
        line = worker._format_csv(make_msg(arb_id=0x1A0))
        arb_field = line.split(",")[2]
        assert arb_field == "1A0"

    def test_csv_dlc_field(self, mock_queue):
        """dlc 필드가 정확해야 한다."""
        worker = LogWorker(mock_queue, "/tmp/test.csv", fmt="csv")
        line = worker._format_csv(make_msg(dlc=4, data=b'\x00' * 4))
        dlc_field = line.split(",")[3]
        assert dlc_field == "4"

    def test_csv_data_hex_no_spaces(self, mock_queue):
        """data는 공백 없는 연속 소문자 HEX 문자열이어야 한다."""
        worker = LogWorker(mock_queue, "/tmp/test.csv", fmt="csv")
        line = worker._format_csv(make_msg(data=b'\xAB\xCD\xEF'))
        data_field = line.split(",")[4]
        assert data_field == "abcdef"
        assert " " not in data_field

    def test_csv_is_tx_false_is_zero(self, mock_queue):
        """is_tx=False → 마지막 필드 '0'."""
        worker = LogWorker(mock_queue, "/tmp/test.csv", fmt="csv")
        line = worker._format_csv(make_msg(is_tx=False))
        is_tx_field = line.strip().split(",")[5]
        assert is_tx_field == "0"

    def test_csv_is_tx_true_is_one(self, mock_queue):
        """is_tx=True → 마지막 필드 '1'."""
        worker = LogWorker(mock_queue, "/tmp/test.csv", fmt="csv")
        line = worker._format_csv(make_msg(is_tx=True))
        is_tx_field = line.strip().split(",")[5]
        assert is_tx_field == "1"

    def test_csv_ends_with_newline(self, mock_queue):
        """CSV 한 줄은 반드시 '\\n' 으로 끝나야 한다."""
        worker = LogWorker(mock_queue, "/tmp/test.csv", fmt="csv")
        line = worker._format_csv(make_msg())
        assert line.endswith("\n")


# ── _write_header() ───────────────────────────────────────────────────────

class TestLogWorkerCsvHeader:
    def test_csv_header_first_line(self, mock_queue):
        """CSV 헤더는 'timestamp,ch_id,arb_id,dlc,data,is_tx\\n' 이어야 한다."""
        worker = LogWorker(mock_queue, "/tmp/test.csv", fmt="csv")
        f = MagicMock()
        written = []
        f.write = written.append
        worker._write_header(f)
        assert written[0] == "timestamp,ch_id,arb_id,dlc,data,is_tx\n"

    def test_asc_header_contains_date(self, mock_queue):
        """ASC 헤더는 'date'로 시작하는 줄을 포함해야 한다."""
        worker = LogWorker(mock_queue, "/tmp/test.asc", fmt="asc")
        f = MagicMock()
        written = []
        f.write = written.append
        worker._write_header(f)
        assert any(line.startswith("date ") for line in written)


# ── fmt 대소문자 무관 ─────────────────────────────────────────────────────

class TestLogWorkerFmtCaseInsensitive:
    @pytest.mark.parametrize("fmt", ["csv", "CSV", "Csv"])
    def test_fmt_normalized_to_lowercase(self, mock_queue, fmt):
        """fmt 파라미터는 대소문자 무관하게 동작해야 한다."""
        worker = LogWorker(mock_queue, "/tmp/test.csv", fmt=fmt)
        assert worker._fmt == "csv"

    @pytest.mark.parametrize("fmt", ["asc", "ASC", "Asc"])
    def test_fmt_asc_normalized(self, mock_queue, fmt):
        worker = LogWorker(mock_queue, "/tmp/test.asc", fmt=fmt)
        assert worker._fmt == "asc"


# ── _format_asc() 회귀 방지 ───────────────────────────────────────────────

class TestLogWorkerFormatAscRegression:
    def test_asc_contains_arb_id_hex(self, mock_queue):
        """ASC 포맷에 arb_id HEX가 포함되어야 한다."""
        worker = LogWorker(mock_queue, "/tmp/test.asc", fmt="asc")
        line = worker._format_asc(make_msg(arb_id=0x1A0))
        assert "1A0" in line

    def test_asc_tx_direction(self, mock_queue):
        """is_tx=True → 'Tx' 포함."""
        worker = LogWorker(mock_queue, "/tmp/test.asc", fmt="asc")
        line = worker._format_asc(make_msg(is_tx=True))
        assert "Tx" in line

    def test_asc_rx_direction(self, mock_queue):
        """is_tx=False → 'Rx' 포함."""
        worker = LogWorker(mock_queue, "/tmp/test.asc", fmt="asc")
        line = worker._format_asc(make_msg(is_tx=False))
        assert "Rx" in line

    def test_asc_data_bytes_space_separated(self, mock_queue):
        """ASC 데이터 바이트는 공백으로 구분된 대문자 HEX여야 한다."""
        worker = LogWorker(mock_queue, "/tmp/test.asc", fmt="asc")
        line = worker._format_asc(make_msg(data=b'\xAB\xCD'))
        assert "AB CD" in line


# ── _format() 디스패치 ────────────────────────────────────────────────────

class TestLogWorkerFormatDispatch:
    def test_format_dispatches_to_csv(self, mock_queue):
        """fmt='csv' 일 때 _format()이 CSV 결과를 반환해야 한다."""
        worker = LogWorker(mock_queue, "/tmp/test.csv", fmt="csv")
        msg = make_msg()
        result = worker._format(msg)
        fields = result.strip().split(",")
        assert len(fields) == 6

    def test_format_dispatches_to_asc(self, mock_queue):
        """fmt='asc' 일 때 _format()이 ASC 결과를 반환해야 한다."""
        worker = LogWorker(mock_queue, "/tmp/test.asc", fmt="asc")
        msg = make_msg()
        result = worker._format(msg)
        assert "Rx" in result or "Tx" in result
