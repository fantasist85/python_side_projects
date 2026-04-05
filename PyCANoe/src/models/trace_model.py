# models/trace_model.py
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
from PySide6.QtGui import QColor

from models.parsed_message import ParsedMessage

# Trace 컬러링 규칙
COLOR_TX    = QColor("#2196F3")   # 파랑 — Tx (SimWorker 에코)
COLOR_ERROR = QColor("#F44336")   # 빨강 — Error Frame
COLOR_RX    = None                # 테마 기본색

_COLUMNS = ["Ch", "Timestamp", "Type", "ID", "DLC", "Data (HEX)", "Signal (DBC)"]
_COL_IDX = {name: i for i, name in enumerate(_COLUMNS)}


class TraceModel(QAbstractTableModel):
    """
    THREAD  : Main Thread 전용 (QAbstractTableModel)
    INPUT   : append_batch(list[ParsedMessage]) — QTimer(50ms) 슬롯에서만 호출
    DO NOT  : Worker Thread에서 직접 접근. decode 수행. append() 단건 호출 (배치 필수).
    """
    MAX_ROWS = 100_000

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[ParsedMessage] = []
        self._filter_id:   int | None = None
        self._filter_mask: int        = 0x7FF

    # ------------------------------------------------------------------
    # QAbstractTableModel 필수 구현
    # ------------------------------------------------------------------

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(self._rows)

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:
        return len(_COLUMNS)

    def headerData(self, section: int, orientation: Qt.Orientation,
                   role: int = Qt.DisplayRole):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return _COLUMNS[section]
        return None

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid() or index.row() >= len(self._rows):
            return None

        msg = self._rows[index.row()]
        col = index.column()

        if role == Qt.ForegroundRole:
            if msg.is_error: return COLOR_ERROR
            if msg.is_tx:    return COLOR_TX
            return COLOR_RX

        if role == Qt.DisplayRole:
            return self._display(msg, col)

        return None

    # ------------------------------------------------------------------
    # 배치 추가
    # ------------------------------------------------------------------

    def append_batch(self, batch: list[ParsedMessage]) -> None:
        """
        INPUT: list[ParsedMessage]. QTimer(50ms) 슬롯에서만 호출.
        beginInsertRows/endInsertRows 배치 처리 — 단건 emit보다 100배+ 빠름.
        MAX_ROWS 초과 시 오래된 행 제거 후 삽입.
        SW ID 필터 적용.
        """
        if not batch:
            return

        # SW 필터 적용
        if self._filter_id is not None:
            batch = [
                m for m in batch
                if (m.arb_id & self._filter_mask) == (self._filter_id & self._filter_mask)
            ]
        if not batch:
            return

        # 초과분 앞에서 제거
        total = len(self._rows) + len(batch)
        if total > self.MAX_ROWS:
            remove_count = total - self.MAX_ROWS
            self.beginRemoveRows(QModelIndex(), 0, remove_count - 1)
            del self._rows[:remove_count]
            self.endRemoveRows()

        first = len(self._rows)
        last  = first + len(batch) - 1
        self.beginInsertRows(QModelIndex(), first, last)
        self._rows.extend(batch)
        self.endInsertRows()

    def clear(self) -> None:
        self.beginResetModel()
        self._rows.clear()
        self.endResetModel()

    def get_row(self, row: int) -> ParsedMessage | None:
        """우클릭 컨텍스트 메뉴에서 행 데이터 조회."""
        if 0 <= row < len(self._rows):
            return self._rows[row]
        return None

    def set_filter(self, filter_id: int, filter_mask: int) -> None:
        """SW ID 필터 설정. 이후 append_batch()에서 적용."""
        self._filter_id   = filter_id
        self._filter_mask = filter_mask

    def clear_filter(self) -> None:
        """필터 초기화."""
        self._filter_id = None

    # ------------------------------------------------------------------
    # 내부 표시 헬퍼
    # ------------------------------------------------------------------

    def _display(self, msg: ParsedMessage, col: int) -> str:
        if col == _COL_IDX["Ch"]:
            return str(msg.ch_id + 1)
        if col == _COL_IDX["Timestamp"]:
            return f"{msg.timestamp:.4f}"
        if col == _COL_IDX["Type"]:
            if msg.is_error:  return "ERR"
            if msg.is_fd:     return "FD"
            return "CAN"
        if col == _COL_IDX["ID"]:
            return f"{msg.arb_id:X}"
        if col == _COL_IDX["DLC"]:
            return str(msg.dlc)
        if col == _COL_IDX["Data (HEX)"]:
            return msg.data.hex(" ").upper()
        if col == _COL_IDX["Signal (DBC)"]:
            if msg.msg_name and msg.signals:
                first_sig = next(iter(msg.signals.items()))
                return f"[{msg.msg_name}] {first_sig[0]}={first_sig[1]}"
            return ""
        return ""
