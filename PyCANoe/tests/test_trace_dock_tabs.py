# tests/test_trace_dock_tabs.py
"""
TraceDock 채널 탭 기능 단위 테스트.

검증 항목:
  - 초기 상태: All 탭만 활성, CH1~4 탭 비활성
  - add_channel_tab()   : 해당 CH 탭 활성화
  - remove_channel_tab(): 해당 CH 탭 비활성화, 현재 탭이 제거된 채널이면 All로 이동
  - refresh_channel_tabs(): 목록 기반 일괄 갱신
  - _on_tab_changed()   : TraceModel.set_ch_filter / clear_ch_filter 연동
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from unittest.mock import MagicMock, patch
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])


@pytest.fixture
def trace_dock(qtbot):
    from models.trace_model import TraceModel
    from widgets.trace_dock import TraceDock
    model = TraceModel()
    dock  = TraceDock(model)
    qtbot.addWidget(dock)
    dock.show()
    return dock, model


# ── 초기 상태 ─────────────────────────────────────────────────────────────

class TestTraceDockTabsInit:
    def test_all_tab_exists_and_active(self, trace_dock):
        dock, _ = trace_dock
        assert dock._tab_bar.tabText(0) == "All"
        assert dock._tab_bar.isTabEnabled(0)

    def test_ch_tabs_exist(self, trace_dock):
        dock, _ = trace_dock
        for i in range(1, 5):
            assert dock._tab_bar.tabText(i) == f"CH{i}"

    def test_ch_tabs_disabled_initially(self, trace_dock):
        dock, _ = trace_dock
        for i in range(1, 5):
            assert not dock._tab_bar.isTabEnabled(i)

    def test_default_tab_is_all(self, trace_dock):
        dock, _ = trace_dock
        assert dock._tab_bar.currentIndex() == 0


# ── add_channel_tab ───────────────────────────────────────────────────────

class TestAddChannelTab:
    def test_add_ch0_enables_tab1(self, trace_dock):
        dock, _ = trace_dock
        dock.add_channel_tab(0)
        assert dock._tab_bar.isTabEnabled(1)

    def test_add_ch3_enables_tab4(self, trace_dock):
        dock, _ = trace_dock
        dock.add_channel_tab(3)
        assert dock._tab_bar.isTabEnabled(4)

    def test_add_multiple_channels(self, trace_dock):
        dock, _ = trace_dock
        dock.add_channel_tab(0)
        dock.add_channel_tab(1)
        assert dock._tab_bar.isTabEnabled(1)
        assert dock._tab_bar.isTabEnabled(2)
        assert not dock._tab_bar.isTabEnabled(3)

    def test_add_invalid_ch_no_crash(self, trace_dock):
        dock, _ = trace_dock
        dock.add_channel_tab(99)   # 범위 초과 — 크래시 없어야 함


# ── remove_channel_tab ────────────────────────────────────────────────────

class TestRemoveChannelTab:
    def test_remove_disables_tab(self, trace_dock):
        dock, _ = trace_dock
        dock.add_channel_tab(0)
        dock.remove_channel_tab(0)
        assert not dock._tab_bar.isTabEnabled(1)

    def test_remove_active_tab_returns_to_all(self, trace_dock, qtbot):
        dock, _ = trace_dock
        dock.add_channel_tab(0)
        dock._tab_bar.setCurrentIndex(1)   # CH1 탭 선택
        dock.remove_channel_tab(0)
        assert dock._tab_bar.currentIndex() == 0   # All로 복귀

    def test_remove_nonactive_tab_keeps_current(self, trace_dock):
        dock, _ = trace_dock
        dock.add_channel_tab(0)
        dock.add_channel_tab(1)
        dock._tab_bar.setCurrentIndex(1)   # CH1 탭 선택
        dock.remove_channel_tab(1)         # CH2 제거
        assert dock._tab_bar.currentIndex() == 1   # CH1 탭 유지


# ── refresh_channel_tabs ──────────────────────────────────────────────────

class TestRefreshChannelTabs:
    def test_refresh_enables_specified_channels(self, trace_dock):
        dock, _ = trace_dock
        dock.refresh_channel_tabs([0, 2])
        assert dock._tab_bar.isTabEnabled(1)    # CH1
        assert not dock._tab_bar.isTabEnabled(2)  # CH2
        assert dock._tab_bar.isTabEnabled(3)    # CH3
        assert not dock._tab_bar.isTabEnabled(4)  # CH4

    def test_refresh_empty_disables_all(self, trace_dock):
        dock, _ = trace_dock
        dock.add_channel_tab(0)
        dock.add_channel_tab(2)
        dock.refresh_channel_tabs([])
        for i in range(1, 5):
            assert not dock._tab_bar.isTabEnabled(i)


# ── 탭 변경 → TraceModel 채널 필터 ──────────────────────────────────────

class TestTabChangedFilter:
    def test_all_tab_clears_ch_filter(self, trace_dock):
        dock, model = trace_dock
        dock.add_channel_tab(0)
        dock._tab_bar.setCurrentIndex(1)   # CH1
        dock._tab_bar.setCurrentIndex(0)   # All
        assert model._ch_filter is None

    def test_ch_tab_sets_ch_filter(self, trace_dock):
        dock, model = trace_dock
        dock.add_channel_tab(1)
        dock._tab_bar.setCurrentIndex(2)   # CH2 (ch_id=1)
        assert model._ch_filter == 1

    def test_ch1_tab_sets_filter_0(self, trace_dock):
        dock, model = trace_dock
        dock.add_channel_tab(0)
        dock._tab_bar.setCurrentIndex(1)   # CH1 (ch_id=0)
        assert model._ch_filter == 0
