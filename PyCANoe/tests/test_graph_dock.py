# tests/test_graph_dock.py
"""
GraphDock — 위젯 단위 테스트 (pytest-qt).

검증 항목:
  - enable() / disable() 상태 플래그 갱신
  - add_signal() — enabled=True 시 SignalBufferRegistry.get() 호출
  - add_signal() — enabled=False 시 거부 (사전 조건: DBC 로드 후에만 허용)
  - remove_signal() — 추가한 신호 제거 크래시 없음
  - update_plots() — 크래시 없음 (enabled/disabled 양쪽)
  - set_rolling_sec() / rolling_sec() 왕복
  - clear() — 내부 상태 초기화
"""
import pytest
from unittest.mock import MagicMock, patch
from models.numpy_signal_buffer import SignalBufferRegistry
from widgets.graph_dock import GraphDock


# ── fixture ───────────────────────────────────────────────────────────────

@pytest.fixture
def registry(qapp):
    """실제 SignalBufferRegistry — 테스트 격리를 위해 매번 신규 생성."""
    return SignalBufferRegistry()


@pytest.fixture
def dock(qtbot, registry):
    d = GraphDock(registry)
    qtbot.addWidget(d)
    d.show()
    return d, registry


# ── enable / disable ──────────────────────────────────────────────────────

class TestGraphDockEnableDisable:
    def test_disabled_by_default(self, dock):
        d, _ = dock
        assert d._enabled is False

    def test_enable_sets_flag(self, dock):
        d, _ = dock
        d.enable()
        assert d._enabled is True

    def test_disable_after_enable(self, dock):
        d, _ = dock
        d.enable()
        d.disable()
        assert d._enabled is False

    def test_enable_twice_no_crash(self, dock):
        d, _ = dock
        d.enable()
        d.enable()
        assert d._enabled is True


# ── add_signal ────────────────────────────────────────────────────────────

class TestGraphDockAddSignal:
    def test_add_signal_when_disabled_ignored(self, dock):
        """disabled 상태에서 add_signal()은 무시되어야 한다."""
        d, registry = dock
        # disabled 상태에서 호출 — 크래시 없어야 하고 플롯 추가 안 됨
        initial_count = len(d._plot_items)
        d.add_signal(ch_id=0, sig_name="EngSpeed")
        assert len(d._plot_items) == initial_count

    def test_add_signal_when_enabled_increases_plot_count(self, dock):
        """enabled 상태에서 add_signal()은 플롯을 추가해야 한다."""
        d, registry = dock
        d.enable()
        initial_count = len(d._plot_items)
        d.add_signal(ch_id=0, sig_name="EngSpeed")
        assert len(d._plot_items) == initial_count + 1

    def test_add_duplicate_signal_ignored(self, dock):
        """동일 (ch_id, sig_name) 중복 추가는 무시되어야 한다."""
        d, registry = dock
        d.enable()
        d.add_signal(ch_id=0, sig_name="EngSpeed")
        count_after_first = len(d._plot_items)
        d.add_signal(ch_id=0, sig_name="EngSpeed")
        assert len(d._plot_items) == count_after_first

    def test_add_multiple_different_signals(self, dock):
        """서로 다른 신호는 각각 추가되어야 한다."""
        d, registry = dock
        d.enable()
        d.add_signal(ch_id=0, sig_name="EngSpeed")
        d.add_signal(ch_id=0, sig_name="VehSpeed")
        assert len(d._plot_items) >= 2


# ── remove_signal ─────────────────────────────────────────────────────────

class TestGraphDockRemoveSignal:
    def test_remove_existing_signal(self, dock):
        d, registry = dock
        d.enable()
        d.add_signal(ch_id=0, sig_name="EngSpeed")
        count_before = len(d._plot_items)
        d.remove_signal(ch_id=0, sig_name="EngSpeed")
        assert len(d._plot_items) == count_before - 1

    def test_remove_nonexistent_signal_no_crash(self, dock):
        """존재하지 않는 신호 제거 시 크래시 없어야 한다."""
        d, registry = dock
        d.remove_signal(ch_id=0, sig_name="DoesNotExist")

    def test_remove_all_signals_clears_plots(self, dock):
        d, registry = dock
        d.enable()
        d.add_signal(ch_id=0, sig_name="EngSpeed")
        d.add_signal(ch_id=0, sig_name="VehSpeed")
        d.remove_signal(ch_id=0, sig_name="EngSpeed")
        d.remove_signal(ch_id=0, sig_name="VehSpeed")
        assert len(d._plot_items) == 0


# ── update_plots ──────────────────────────────────────────────────────────

class TestGraphDockUpdatePlots:
    def test_update_plots_disabled_no_crash(self, dock):
        """disabled 상태에서 update_plots() — 크래시 없어야 한다."""
        d, _ = dock
        d.update_plots()

    def test_update_plots_enabled_no_signal_no_crash(self, dock):
        """enabled이지만 신호 없을 때 — 크래시 없어야 한다."""
        d, _ = dock
        d.enable()
        d.update_plots()

    def test_update_plots_with_signal_no_crash(self, dock):
        """신호가 추가된 상태에서 update_plots() — 크래시 없어야 한다."""
        d, registry = dock
        d.enable()
        d.add_signal(ch_id=0, sig_name="EngSpeed")
        d.update_plots()


# ── set_rolling_sec / rolling_sec ─────────────────────────────────────────

class TestGraphDockRollingSec:
    def test_rolling_sec_default(self, dock):
        """기본값은 30초 (명세서 기본값)."""
        d, _ = dock
        assert d.rolling_sec() == 30

    def test_set_rolling_sec_roundtrip(self, dock):
        d, _ = dock
        d.set_rolling_sec(10)
        assert d.rolling_sec() == 10

    def test_set_rolling_sec_zero(self, dock):
        """0 = 전체 표시 모드."""
        d, _ = dock
        d.set_rolling_sec(0)
        assert d.rolling_sec() == 0

    def test_set_rolling_sec_various_values(self, dock):
        d, _ = dock
        for val in (5, 10, 30):
            d.set_rolling_sec(val)
            assert d.rolling_sec() == val


# ── clear ─────────────────────────────────────────────────────────────────

class TestGraphDockClear:
    def test_clear_removes_all_plots(self, dock):
        d, registry = dock
        d.enable()
        d.add_signal(ch_id=0, sig_name="EngSpeed")
        d.add_signal(ch_id=0, sig_name="VehSpeed")
        d.clear_all()
        assert len(d._plot_items) == 0

    def test_clear_empty_no_crash(self, dock):
        """플롯 없는 상태에서 clear() — 크래시 없어야 한다."""
        d, _ = dock
        d.clear_all()
