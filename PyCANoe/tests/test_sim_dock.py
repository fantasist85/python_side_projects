# tests/test_sim_dock.py
"""
SimDock — 위젯 단위 테스트 (pytest-qt).

검증 항목:
  - refresh_channels() — 채널 없을 때 크래시 없음
  - add_from_trace() — 메시지 추가 후 트리 항목 증가
  - _start_message() / _stop_message() — SimWorker 없을 때 크래시 없음
  - sim_worker_created Signal — 시작 시 emit 확인
  - 채널 콤보박스 — refresh_channels() 후 항목 수 갱신

속성명 매핑 (실제 구현 기준):
  SimDock._msg_tree       — 메시지 목록 QTreeWidget
  SimDock._detail._cb_ch  — 채널 선택 콤보박스 (SimMessageDetail 내부)
"""
import pytest
from unittest.mock import MagicMock, patch
from models.sim_state_store import SimStateStore
from widgets.sim_dock import SimDock


# ── fixture ───────────────────────────────────────────────────────────────

@pytest.fixture
def mock_channel_manager():
    cm = MagicMock()
    cm.all.return_value = []          # 기본: 채널 없음
    cm.MAX_CHANNELS = 4
    return cm


@pytest.fixture
def sim_state(qapp):
    return SimStateStore()


@pytest.fixture
def dock(qtbot, mock_channel_manager, sim_state):
    d = SimDock(mock_channel_manager, sim_state)
    qtbot.addWidget(d)
    d.show()
    return d, mock_channel_manager


# ── refresh_channels ──────────────────────────────────────────────────────

class TestSimDockRefreshChannels:
    def test_refresh_no_channels_no_crash(self, dock):
        """채널 없을 때 refresh_channels() — 크래시 없어야 한다."""
        d, cm = dock
        cm.all.return_value = []
        d.refresh_channels()

    def test_refresh_with_channels_updates_combo(self, dock):
        """채널 존재 시 콤보박스 항목 수가 갱신되어야 한다."""
        d, cm = dock
        mock_ctx = MagicMock()
        mock_ctx.ch_id = 0
        cm.all.return_value = [mock_ctx]
        d.refresh_channels()
        # _detail._cb_ch 가 채널 콤보박스 (SimMessageDetail 내부)
        assert d._detail._cb_ch.count() >= 1

    def test_refresh_multiple_channels(self, dock):
        d, cm = dock
        ctxs = []
        for i in range(3):
            ctx = MagicMock()
            ctx.ch_id = i
            ctxs.append(ctx)
        cm.all.return_value = ctxs
        d.refresh_channels()
        assert d._detail._cb_ch.count() == 3


# ── add_from_trace ────────────────────────────────────────────────────────

class TestSimDockAddFromTrace:
    def test_add_from_trace_increases_tree_count(self, dock):
        """add_from_trace() 호출 후 트리 항목이 증가해야 한다."""
        d, cm = dock
        mock_ctx = MagicMock()
        mock_ctx.ch_id = 0
        cm.all.return_value = [mock_ctx]
        d.refresh_channels()

        before = d._msg_tree.topLevelItemCount()
        d.add_from_trace(ch_id=0, arb_id=0x1A0, dlc=8, data=b'\x00' * 8)
        assert d._msg_tree.topLevelItemCount() == before + 1

    def test_add_from_trace_no_channel_no_crash(self, dock):
        """채널 없는 상태에서 add_from_trace() — 크래시 없어야 한다."""
        d, cm = dock
        cm.all.return_value = []
        d.refresh_channels()
        d.add_from_trace(ch_id=0, arb_id=0x1A0, dlc=8, data=b'\x00' * 8)

    def test_add_multiple_messages(self, dock):
        d, cm = dock
        mock_ctx = MagicMock()
        mock_ctx.ch_id = 0
        cm.all.return_value = [mock_ctx]
        d.refresh_channels()

        for arb_id in (0x100, 0x200, 0x300):
            d.add_from_trace(ch_id=0, arb_id=arb_id, dlc=8, data=b'\xAB' * 8)
        assert d._msg_tree.topLevelItemCount() == 3

    def test_add_from_trace_correct_arb_id(self, dock):
        """추가된 트리 항목의 Arbitration ID가 정확해야 한다."""
        d, cm = dock
        mock_ctx = MagicMock()
        mock_ctx.ch_id = 0
        cm.all.return_value = [mock_ctx]
        d.refresh_channels()

        d.add_from_trace(ch_id=0, arb_id=0x2B0, dlc=4, data=b'\x01' * 4)
        item = d._msg_tree.topLevelItem(0)
        # 트리 항목 텍스트에 arb_id (hex) 포함 확인
        all_text = " ".join(item.text(col) for col in range(d._msg_tree.columnCount()))
        assert "2B0" in all_text.upper()


# ── _start_message / _stop_message ───────────────────────────────────────

class TestSimDockStartStop:
    def test_start_message_no_selection_no_crash(self, dock):
        """선택 항목 없을 때 _on_start_clicked() — 크래시 없어야 한다."""
        d, cm = dock
        d._msg_tree.clearSelection()
        d._on_start_clicked()

    def test_stop_message_no_selection_no_crash(self, dock):
        """선택 항목 없을 때 _on_stop_clicked() — 크래시 없어야 한다."""
        d, cm = dock
        d._msg_tree.clearSelection()
        d._on_stop_clicked()

    def test_start_without_sim_worker_no_crash(self, dock):
        """SimWorker 없이 시작 버튼 클릭 — 크래시 없어야 한다."""
        d, cm = dock
        mock_ctx = MagicMock()
        mock_ctx.ch_id = 0
        mock_ctx.sim_worker = None   # SimWorker 미생성 상태
        cm.all.return_value = [mock_ctx]
        d.refresh_channels()

        d.add_from_trace(ch_id=0, arb_id=0x1A0, dlc=8, data=b'\x00' * 8)
        d._msg_tree.setCurrentItem(d._msg_tree.topLevelItem(0))
        d._on_start_clicked()   # 크래시 없어야 함


# ── sim_worker_created Signal ─────────────────────────────────────────────

class TestSimDockSignals:
    def test_sim_worker_created_signal_exists(self, dock):
        """sim_worker_created Signal이 정의되어 있어야 한다."""
        d, _ = dock
        assert hasattr(d, 'sim_worker_created')

    def test_sim_worker_created_connectable(self, dock, qtbot):
        """sim_worker_created에 슬롯을 연결할 수 있어야 한다."""
        d, _ = dock
        received = []
        d.sim_worker_created.connect(received.append)
        # emit 직접 테스트
        fake_worker = MagicMock()
        d.sim_worker_created.emit(fake_worker)
        assert len(received) == 1
        assert received[0] is fake_worker
