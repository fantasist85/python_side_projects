# tests/test_trace_dock_extra.py
"""
TraceDock 추가 단위 테스트.
커버리지 목표: 미커버 라인 (200, 244-298) 처리.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from models.trace_model import TraceModel
from models.parsed_message import ParsedMessage

_app = QApplication.instance() or QApplication([])


def _msg(ch_id: int = 0, arb_id: int = 0x1A0, signals: dict | None = None) -> ParsedMessage:
    return ParsedMessage(
        ch_id=ch_id, timestamp=1.0, arb_id=arb_id,
        dlc=8, data=b"\x01\x02\x03\x04\x05\x06\x07\x08",
        signals=signals,
    )


@pytest.fixture
def dock(qtbot):
    from widgets.trace_dock import TraceDock
    model = TraceModel()
    d = TraceDock(model)
    qtbot.addWidget(d)
    d.show()
    return d, model


class TestTraceDockFilterApply:
    def test_filter_apply_valid_updates_model(self, dock):
        """유효한 Hex 입력 → TraceModel.set_filter() 호출."""
        d, model = dock
        d._le_filter_id.setText("1A0")
        d._le_filter_mask.setText("7FF")
        d._on_filter_apply()
        assert model._filter_id   == 0x1A0
        assert model._filter_mask == 0x7FF

    def test_filter_apply_invalid_hex_does_nothing(self, dock):
        """잘못된 Hex 입력 → 모델 상태 변경 없음."""
        d, model = dock
        d._le_filter_id.setText("XYZ")
        d._on_filter_apply()
        # 기본값 유지 확인 (크래시 없음)
        assert model._filter_id is None

    def test_filter_clear_resets_model(self, dock):
        """필터 초기화 → 모델 필터 해제."""
        d, model = dock
        model.set_filter(0x100, 0x7FF)
        d._on_filter_clear()
        assert model._filter_id is None

    def test_filter_clear_resets_ui_text(self, dock):
        """필터 초기화 → ID 입력 필드 비워지고 Mask는 7FF로 복원."""
        d, model = dock
        d._le_filter_id.setText("100")
        d._on_filter_clear()
        assert d._le_filter_id.text() == ""
        assert d._le_filter_mask.text() == "7FF"


class TestTraceDockApplyIdFilter:
    def test_apply_id_filter_sets_le_text(self, dock):
        """_apply_id_filter() 호출 시 ID 필드에 자동 입력 및 필터 적용."""
        d, model = dock
        d._apply_id_filter(0x2B0)
        assert d._le_filter_id.text() == "2B0"
        assert model._filter_id == 0x2B0


class TestTraceDockCopyToClipboard:
    def test_copy_to_clipboard_sets_text(self, dock):
        """_copy_to_clipboard() 호출 시 클립보드에 메시지 정보 복사."""
        d, model = dock
        msg = _msg(ch_id=0, arb_id=0x1A0)
        d._copy_to_clipboard(msg)
        from PySide6.QtWidgets import QApplication
        clip_text = QApplication.clipboard().text()
        assert "CH1" in clip_text
        assert "1A0" in clip_text


class TestTraceDockSendSignalsToGraph:
    def test_send_signals_to_graph_emits_for_each_signal(self, dock, qtbot):
        """신호 있는 메시지 → send_to_graph Signal을 신호 수만큼 emit."""
        d, model = dock
        d.set_db_loaded(True)
        msg = _msg(ch_id=0, arb_id=0x1A0, signals={"EngSpeed": 1200.0, "VehSpeed": 40.0})

        received = []
        d.send_to_graph.connect(lambda ch, sig: received.append((ch, sig)))
        d._send_signals_to_graph(msg)
        assert len(received) == 2

    def test_send_signals_to_graph_no_signals_does_nothing(self, dock):
        """signals=None → send_to_graph emit 없음."""
        d, model = dock
        msg = _msg(signals=None)
        received = []
        d.send_to_graph.connect(lambda ch, sig: received.append((ch, sig)))
        d._send_signals_to_graph(msg)
        assert received == []


class TestTraceDockAutoScroll:
    def test_scroll_to_bottom_no_crash(self, dock):
        """scroll_to_bottom() 호출 — 크래시 없어야 함."""
        d, model = dock
        model.append_batch([_msg()] * 5)
        d.scroll_to_bottom()


class TestTraceDockDbLoaded:
    def test_set_db_loaded_true(self, dock):
        d, model = dock
        d.set_db_loaded(True)
        assert d._db_loaded is True

    def test_set_db_loaded_false(self, dock):
        d, model = dock
        d.set_db_loaded(False)
        assert d._db_loaded is False


class TestTraceDockRefreshChannelTabsExtra:
    def test_refresh_with_mixed_channels(self, dock):
        """refresh_channel_tabs([0, 2]) → CH1, CH3 활성, CH2, CH4 비활성."""
        d, model = dock
        d.refresh_channel_tabs([0, 2])
        # CH1(index 1), CH3(index 3) 활성
        assert d._tab_bar.isTabEnabled(1) is True
        assert d._tab_bar.isTabEnabled(3) is True
        # CH2(index 2), CH4(index 4) 비활성
        assert d._tab_bar.isTabEnabled(2) is False
        assert d._tab_bar.isTabEnabled(4) is False
