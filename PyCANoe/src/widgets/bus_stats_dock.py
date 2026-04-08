# widgets/bus_stats_dock.py
"""
BusStatsDock — Bus Statistics QDockWidget.

각 CAN 채널의 실시간 버스 통계를 표 형태로 표시.
StatusBar 한 줄 표시의 확장판 — 채널이 많아도 가독성 유지.

THREAD  : Main Thread 전용.
UPDATE  : MainWindow._flush_stats() 에서 1초 주기로 update_stats() 호출.

표시 항목 (명세서 M6):
  채널 | 버스 부하율 (%) | Rx (msg/s) | Tx (msg/s) | 오류 | 상태
"""
from __future__ import annotations

from typing import List, Tuple, Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

# ── 컬럼 인덱스 상수 ───────────────────────────────────────────────────────
_COL_CH       = 0
_COL_LOAD     = 1
_COL_RX       = 2
_COL_TX       = 3
_COL_ERR      = 4
_COL_STATUS   = 5
_NUM_COLS     = 6

_HEADERS = ["채널", "버스 부하 (%)", "Rx (msg/s)", "Tx (msg/s)", "오류", "상태"]

# 버스 부하율 색상 임계값
_LOAD_WARN  = 50.0   # 노란색
_LOAD_CRIT  = 80.0   # 빨간색


class BusStatsDock(QWidget):
    """
    Bus Statistics를 QTableWidget으로 표시하는 Dock 콘텐츠 위젯.

    MainWindow가 QDockWidget으로 감싸서 사용.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_ui()

    # ------------------------------------------------------------------
    # UI 초기화
    # ------------------------------------------------------------------

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # 헤더 행
        header_row = QHBoxLayout()
        title = QLabel("Bus Statistics")
        title.setStyleSheet("font-weight: bold; font-size: 13px;")
        header_row.addWidget(title)
        header_row.addStretch()

        btn_clear = QPushButton("오류 초기화")
        btn_clear.setFixedWidth(90)
        btn_clear.clicked.connect(self._on_clear_errors)
        header_row.addWidget(btn_clear)
        layout.addLayout(header_row)

        # 통계 테이블
        self._table = QTableWidget(0, _NUM_COLS, self)
        self._table.setHorizontalHeaderLabels(_HEADERS)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)

        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(_COL_CH,     QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(_COL_STATUS, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(_COL_CH,     70)
        self._table.setColumnWidth(_COL_STATUS, 80)

        layout.addWidget(self._table)

        # 누적 오류 카운터 (채널별, clear 전까지 유지)
        self._cumulative_errors: dict[int, int] = {}

    # ------------------------------------------------------------------
    # 외부 인터페이스
    # ------------------------------------------------------------------

    def update_stats(self, stats_list: list[tuple[int, Any]]) -> None:
        """
        채널 통계를 테이블에 반영.

        Parameters
        ----------
        stats_list : list of (ch_id, ChannelStats)
            ChannelStats 는 .bus_load_pct / .rx_count / .tx_count / .error_count 속성 보유.
        """
        # 행 수 조정
        needed = len(stats_list)
        current = self._table.rowCount()
        if current < needed:
            for _ in range(needed - current):
                self._table.insertRow(self._table.rowCount())
        elif current > needed:
            for _ in range(current - needed):
                self._table.removeRow(self._table.rowCount() - 1)

        for row, (ch_id, stats) in enumerate(stats_list):
            load    = stats.bus_load_pct
            rx      = stats.rx_count
            tx      = stats.tx_count
            err     = stats.error_count

            # 누적 오류
            prev = self._cumulative_errors.get(ch_id, 0)
            self._cumulative_errors[ch_id] = prev + err

            status = "정상" if err == 0 else "오류"

            self._set_cell(row, _COL_CH,     f"CH{ch_id + 1}")
            self._set_cell(row, _COL_LOAD,   f"{load:.1f}")
            self._set_cell(row, _COL_RX,     str(rx))
            self._set_cell(row, _COL_TX,     str(tx))
            self._set_cell(row, _COL_ERR,    str(self._cumulative_errors[ch_id]))
            self._set_cell(row, _COL_STATUS, status)

            # 버스 부하 색상
            load_item = self._table.item(row, _COL_LOAD)
            if load_item:
                if load >= _LOAD_CRIT:
                    load_item.setForeground(QColor("#B71C1C"))  # 진한 빨강
                elif load >= _LOAD_WARN:
                    load_item.setForeground(QColor("#F57F17"))  # 주황
                else:
                    load_item.setForeground(QColor("#1B5E20"))  # 초록

            # 상태 색상
            status_item = self._table.item(row, _COL_STATUS)
            if status_item:
                if err > 0:
                    status_item.setForeground(QColor("#B71C1C"))
                else:
                    status_item.setForeground(QColor("#1B5E20"))

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    def _set_cell(self, row: int, col: int, text: str) -> None:
        item = self._table.item(row, col)
        if item is None:
            item = QTableWidgetItem(text)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(row, col, item)
        else:
            item.setText(text)

    def _on_clear_errors(self) -> None:
        """누적 오류 카운터 초기화."""
        self._cumulative_errors.clear()
        for row in range(self._table.rowCount()):
            err_item = self._table.item(row, _COL_ERR)
            if err_item:
                err_item.setText("0")
            status_item = self._table.item(row, _COL_STATUS)
            if status_item:
                status_item.setText("정상")
                status_item.setForeground(QColor("#1B5E20"))
