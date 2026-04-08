# tests/test_sim_dock_extra.py
"""
SimDock / _SimMessageDetail 추가 단위 테스트.
커버리지 목표: 미커버 라인 lines 149-228, 361-379 처리.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

pytest.importorskip("PySide6")

from unittest.mock import MagicMock
from PySide6.QtWidgets import QApplication, QTreeWidgetItem
from PySide6.QtCore import Qt

_app = QApplication.instance() or QApplication([])


def _make_cm(num_channels: int = 1):
    cm = MagicMock()
    ctxs = []
    for i in range(num_channels):
        ctx = MagicMock()
        ctx.ch_id = i
        ctx.sim_worker = None
        ctxs.append(ctx)
    cm.all.return_value = ctxs
    cm.get.side_effect = lambda ch_id: next(
        (c for c in ctxs if c.ch_id == ch_id), None
    )
    cm.MAX_CHANNELS = 4
    return cm


@pytest.fixture
def dock(qtbot):
    from widgets.sim_dock import SimDock
    from models.sim_state_store import SimStateStore
    cm = _make_cm(1)
    state = SimStateStore()
    d = SimDock(cm, state)
    qtbot.addWidget(d)
    d.show()
    return d, cm


@pytest.fixture
def dock_with_worker(qtbot):
    from widgets.sim_dock import SimDock
    from models.sim_state_store import SimStateStore
    cm = _make_cm(1)
    ctx = cm.get(0)
    ctx.sim_worker = MagicMock()
    state = SimStateStore()
    d = SimDock(cm, state)
    qtbot.addWidget(d)
    d.show()
    return d, cm, ctx


class TestSimDockOnRemove:
    def test_remove_running_message_stops_first(self, dock_with_worker):
        d, cm, ctx = dock_with_worker
        item = QTreeWidgetItem(["1", "100", "100", "▶ 실행"])
        item.setData(0, Qt.ItemDataRole.UserRole, {
            "ch_id": 0, "arb_id": 0x100, "interval_ms": 100.0,
            "data": b"\x00" * 8, "running": True,
        })
        d._msg_tree.addTopLevelItem(item)
        d._msg_tree.setCurrentItem(item)
        d._on_remove_clicked()
        assert d._msg_tree.topLevelItemCount() == 0

    def test_remove_no_selection_no_crash(self, dock):
        d, cm = dock
        d._msg_tree.setCurrentItem(None)
        d._on_remove_clicked()


class TestSimDockStartStop:
    def test_start_all_when_no_selection(self, dock_with_worker):
        d, cm, ctx = dock_with_worker
        for arb_id in [0x100, 0x200]:
            item = QTreeWidgetItem(["1", f"{arb_id:X}", "100", "정지"])
            item.setData(0, Qt.ItemDataRole.UserRole, {
                "ch_id": 0, "arb_id": arb_id, "interval_ms": 100.0,
                "data": b"\x00" * 8, "running": False,
            })
            d._msg_tree.addTopLevelItem(item)
        d._msg_tree.setCurrentItem(None)
        d._on_start_clicked()

    def test_stop_all_when_no_selection(self, dock_with_worker):
        d, cm, ctx = dock_with_worker
        item = QTreeWidgetItem(["1", "100", "100", "▶ 실행"])
        item.setData(0, Qt.ItemDataRole.UserRole, {
            "ch_id": 0, "arb_id": 0x100, "interval_ms": 100.0,
            "data": b"\x00" * 8, "running": True,
        })
        d._msg_tree.addTopLevelItem(item)
        d._msg_tree.setCurrentItem(None)
        d._on_stop_clicked()

    def test_start_with_selection_sets_running(self, dock_with_worker):
        d, cm, ctx = dock_with_worker
        item = QTreeWidgetItem(["1", "100", "100", "정지"])
        item.setData(0, Qt.ItemDataRole.UserRole, {
            "ch_id": 0, "arb_id": 0x100, "interval_ms": 100.0,
            "data": b"\x00" * 8, "running": False,
        })
        d._msg_tree.addTopLevelItem(item)
        d._msg_tree.setCurrentItem(item)
        d._on_start_clicked()
        updated = item.data(0, Qt.ItemDataRole.UserRole)
        assert updated["running"] is True

    def test_stop_with_selection_sets_not_running(self, dock_with_worker):
        d, cm, ctx = dock_with_worker
        item = QTreeWidgetItem(["1", "100", "100", "▶ 실행"])
        item.setData(0, Qt.ItemDataRole.UserRole, {
            "ch_id": 0, "arb_id": 0x100, "interval_ms": 100.0,
            "data": b"\x00" * 8, "running": True,
        })
        d._msg_tree.addTopLevelItem(item)
        d._msg_tree.setCurrentItem(item)
        d._on_stop_clicked()
        updated = item.data(0, Qt.ItemDataRole.UserRole)
        assert updated["running"] is False

    def test_stop_without_sim_worker_no_crash(self, dock):
        d, cm = dock
        item = QTreeWidgetItem(["1", "100", "100", "▶ 실행"])
        item.setData(0, Qt.ItemDataRole.UserRole, {
            "ch_id": 0, "arb_id": 0x100, "interval_ms": 100.0,
            "data": b"\x00" * 8, "running": True,
        })
        d._msg_tree.addTopLevelItem(item)
        d._msg_tree.setCurrentItem(item)
        d._on_stop_clicked()


class TestSimDockDetailChanged:
    def test_detail_changed_updates_tree_text(self, dock):
        d, cm = dock
        item = QTreeWidgetItem(["1", "100", "100", "정지"])
        item.setData(0, Qt.ItemDataRole.UserRole, {
            "ch_id": 0, "arb_id": 0x100, "interval_ms": 100.0,
            "data": b"\x00" * 8, "running": False,
        })
        d._msg_tree.addTopLevelItem(item)
        d._msg_tree.setCurrentItem(item)
        new_data = {
            "ch_id": 0, "arb_id": 0x2B0,
            "interval_ms": 50.0, "data": b"\xFF" * 4, "running": False,
        }
        d._on_detail_changed(new_data)
        assert item.text(1) == "2B0"
        assert item.text(2) == "50"

    def test_detail_changed_no_selection_no_crash(self, dock):
        d, cm = dock
        d._msg_tree.setCurrentItem(None)
        d._on_detail_changed({"ch_id": 0, "arb_id": 0x100})


class TestSimDockSelectionChanged:
    def test_selection_enables_detail(self, dock):
        d, cm = dock
        item = QTreeWidgetItem(["1", "100", "100", "정지"])
        item.setData(0, Qt.ItemDataRole.UserRole, {
            "ch_id": 0, "arb_id": 0x100, "interval_ms": 100.0,
            "data": b"\x00" * 8, "running": False,
        })
        d._msg_tree.addTopLevelItem(item)
        d._msg_tree.setCurrentItem(item)
        d._on_selection_changed()
        assert d._detail.isEnabled()

    def test_no_selection_disables_detail(self, dock):
        d, cm = dock
        d._msg_tree.setCurrentItem(None)
        d._on_selection_changed()
        assert not d._detail.isEnabled()


class TestSimMessageDetail:
    @pytest.fixture
    def detail(self, qtbot):
        from widgets.sim_dock import _SimMessageDetail
        d = _SimMessageDetail()
        qtbot.addWidget(d)
        return d

    def test_mode_toggle_raw_shows_raw(self, detail):
        detail._on_mode_toggled(True)
        assert not detail._le_raw.isHidden()
        assert detail._phys_area.isHidden()

    def test_mode_toggle_phys_shows_phys(self, detail):
        detail._on_mode_toggled(False)
        assert detail._le_raw.isHidden()
        assert not detail._phys_area.isHidden()

    def test_collect_valid_arb_id(self, detail):
        detail._le_arb_id.setText("1A0")
        result = detail._collect()
        assert result["arb_id"] == 0x1A0

    def test_collect_invalid_arb_id_defaults(self, detail):
        detail._le_arb_id.setText("ZZZZ")
        result = detail._collect()
        assert result["arb_id"] == 0x100

    def test_collect_invalid_hex_data_defaults(self, detail):
        detail._le_raw.setText("XXYYZZ")
        result = detail._collect()
        assert result["data"] == b"\x00" * 8

    def test_load_sets_arb_id(self, detail):
        detail.load({"ch_id": 0, "arb_id": 0x2B0, "interval_ms": 200.0,
                     "data": b"\x01\x02", "running": False})
        assert detail._le_arb_id.text() == "2B0"

    def test_on_apply_emits_value_changed(self, detail, qtbot):
        received = []
        detail.value_changed.connect(lambda d: received.append(d))
        detail._on_apply()
        assert len(received) == 1
        assert "arb_id" in received[0]

    def test_refresh_channels_updates_combo(self, detail):
        cm = _make_cm(2)
        detail.refresh_channels(cm)
        assert detail._cb_ch.count() == 2
