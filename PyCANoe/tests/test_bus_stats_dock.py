# tests/test_bus_stats_dock.py
"""
BusStatsDock 단위 테스트.

실행:
    QT_QPA_PLATFORM=offscreen PYTHONPATH=src pytest tests/test_bus_stats_dock.py -v
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from PySide6.QtWidgets import QApplication
import sys

# QApplication 싱글턴 확보
_app = QApplication.instance() or QApplication(sys.argv)


def _make_stats(bus_load_pct=0.0, rx_count=0, tx_count=0, error_count=0):
    """ChannelStats mock 생성."""
    s = MagicMock()
    s.bus_load_pct = bus_load_pct
    s.rx_count     = rx_count
    s.tx_count     = tx_count
    s.error_count  = error_count
    return s


# ── fixture ──────────────────────────────────────────────────────────────

@pytest.fixture
def dock(qtbot):
    from widgets.bus_stats_dock import BusStatsDock
    w = BusStatsDock()
    qtbot.addWidget(w)
    return w


# ── 초기 상태 ─────────────────────────────────────────────────────────────

class TestBusStatsDockInit:
    def test_table_starts_empty(self, dock):
        assert dock._table.rowCount() == 0

    def test_column_count(self, dock):
        assert dock._table.columnCount() == 6

    def test_headers(self, dock):
        expected = ["채널", "버스 부하 (%)", "Rx (msg/s)", "Tx (msg/s)", "오류", "상태"]
        for col, text in enumerate(expected):
            assert dock._table.horizontalHeaderItem(col).text() == text


# ── update_stats ──────────────────────────────────────────────────────────

class TestUpdateStats:
    def test_single_channel_adds_row(self, dock):
        dock.update_stats([(0, _make_stats(10.0, 100, 5, 0))])
        assert dock._table.rowCount() == 1

    def test_channel_label(self, dock):
        dock.update_stats([(2, _make_stats())])
        assert dock._table.item(0, 0).text() == "CH3"

    def test_bus_load_displayed(self, dock):
        dock.update_stats([(0, _make_stats(bus_load_pct=42.5))])
        assert dock._table.item(0, 1).text() == "42.5"

    def test_rx_tx_displayed(self, dock):
        dock.update_stats([(0, _make_stats(rx_count=200, tx_count=10))])
        assert dock._table.item(0, 2).text() == "200"
        assert dock._table.item(0, 3).text() == "10"

    def test_no_error_status_normal(self, dock):
        dock.update_stats([(0, _make_stats(error_count=0))])
        assert dock._table.item(0, 5).text() == "정상"

    def test_error_status(self, dock):
        dock.update_stats([(0, _make_stats(error_count=3))])
        assert dock._table.item(0, 5).text() == "오류"

    def test_multiple_channels(self, dock):
        stats = [
            (0, _make_stats(5.0, 10, 1, 0)),
            (1, _make_stats(90.0, 500, 0, 2)),
        ]
        dock.update_stats(stats)
        assert dock._table.rowCount() == 2
        assert dock._table.item(0, 0).text() == "CH1"
        assert dock._table.item(1, 0).text() == "CH2"

    def test_row_reduction(self, dock):
        dock.update_stats([(0, _make_stats()), (1, _make_stats())])
        dock.update_stats([(0, _make_stats())])
        assert dock._table.rowCount() == 1

    def test_cumulative_error_accumulates(self, dock):
        dock.update_stats([(0, _make_stats(error_count=2))])
        dock.update_stats([(0, _make_stats(error_count=3))])
        # 2 + 3 = 5 누적
        assert dock._table.item(0, 4).text() == "5"

    def test_cumulative_error_per_channel(self, dock):
        dock.update_stats([(0, _make_stats(error_count=1)), (1, _make_stats(error_count=4))])
        assert dock._table.item(0, 4).text() == "1"
        assert dock._table.item(1, 4).text() == "4"


# ── 오류 초기화 ───────────────────────────────────────────────────────────

class TestClearErrors:
    def test_clear_resets_cumulative(self, dock):
        dock.update_stats([(0, _make_stats(error_count=10))])
        dock._on_clear_errors()
        assert dock._cumulative_errors == {}

    def test_clear_updates_table_cell(self, dock):
        dock.update_stats([(0, _make_stats(error_count=5))])
        dock._on_clear_errors()
        assert dock._table.item(0, 4).text() == "0"

    def test_clear_status_reset_to_normal(self, dock):
        dock.update_stats([(0, _make_stats(error_count=2))])
        dock._on_clear_errors()
        assert dock._table.item(0, 5).text() == "정상"
