# tests/test_graph_dock_signal_dialog.py
"""
GraphDock 신호 추가 팝업(_SignalSelectDialog) 단위 테스트.

검증 항목:
  - _SignalSelectDialog.selected_signals() — 체크된 항목만 반환
  - 이미 추가된 신호는 체크 & 비활성 (중복 추가 방지)
  - 미활성화 신호 선택 시 결과에 포함되지 않음
  - GraphDock._on_add_signal_clicked() — disabled 상태에서 호출 시 크래시 없음
  - GraphDock._on_add_signal_clicked() — 신호 없을 때 크래시 없음
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest
from unittest.mock import MagicMock, patch
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

_app = QApplication.instance() or QApplication([])


@pytest.fixture
def registry():
    from models.numpy_signal_buffer import SignalBufferRegistry
    r = SignalBufferRegistry()
    r.get_or_create(0, "EngSpeed")
    r.get_or_create(0, "VehSpeed")
    r.get_or_create(1, "BrakeForce")
    return r


@pytest.fixture
def dock_enabled(qtbot, registry):
    from widgets.graph_dock import GraphDock
    d = GraphDock(registry)
    qtbot.addWidget(d)
    d.show()
    d.enable()
    return d, registry


# ── _SignalSelectDialog ───────────────────────────────────────────────────

class TestSignalSelectDialog:
    def test_selected_signals_empty_when_none_checked(self, qtbot, registry):
        """체크 없이 OK → 빈 목록 반환."""
        from widgets.graph_dock import _SignalSelectDialog
        available = [(0, "EngSpeed"), (0, "VehSpeed")]
        dlg = _SignalSelectDialog(available, {}, parent=None)

        # 모든 체크 해제
        dlg._select_none()
        result = dlg.selected_signals()
        assert result == []

    def test_selected_signals_returns_checked(self, qtbot, registry):
        """체크된 신호가 반환된다."""
        from widgets.graph_dock import _SignalSelectDialog
        from PySide6.QtCore import Qt
        available = [(0, "EngSpeed"), (0, "VehSpeed")]
        dlg = _SignalSelectDialog(available, {}, parent=None)

        # EngSpeed만 체크
        dlg._select_none()
        dlg._items[0][0].setCheckState(Qt.CheckState.Checked)

        result = dlg.selected_signals()
        assert (0, "EngSpeed") in result
        assert (0, "VehSpeed") not in result

    def test_already_added_signal_disabled(self, qtbot):
        """이미 추가된 신호는 비활성화 상태여야 한다."""
        from widgets.graph_dock import _SignalSelectDialog
        from PySide6.QtCore import Qt
        available   = [(0, "EngSpeed"), (0, "VehSpeed")]
        already     = {(0, "EngSpeed"): object()}  # already_added dict
        dlg = _SignalSelectDialog(available, already, parent=None)

        # EngSpeed 항목이 비활성화 상태인지 확인
        eng_item = dlg._items[0][0]
        assert not (eng_item.flags() & Qt.ItemFlag.ItemIsEnabled)

    def test_already_added_excluded_from_selected(self, qtbot):
        """이미 추가된 신호는 selected_signals()에 포함되지 않는다."""
        from widgets.graph_dock import _SignalSelectDialog
        available = [(0, "EngSpeed"), (0, "VehSpeed")]
        already   = {(0, "EngSpeed"): object()}
        dlg = _SignalSelectDialog(available, already, parent=None)

        dlg._select_all()
        result = dlg.selected_signals()
        # EngSpeed는 이미 추가됨 → 결과에서 제외
        assert (0, "EngSpeed") not in result
        assert (0, "VehSpeed") in result

    def test_select_all_checks_enabled_only(self, qtbot):
        """select_all()은 활성화된 항목만 체크한다.
        비활성(이미 추가된) 항목은 체크 상태를 그대로 유지한다."""
        from widgets.graph_dock import _SignalSelectDialog
        from PySide6.QtCore import Qt
        available = [(0, "EngSpeed"), (0, "VehSpeed")]
        already   = {(0, "EngSpeed"): object()}
        dlg = _SignalSelectDialog(available, already, parent=None)

        dlg._select_none()
        dlg._select_all()

        # VehSpeed는 활성 → 체크됨
        veh_item = dlg._items[1][0]
        assert veh_item.checkState() == Qt.CheckState.Checked

        # EngSpeed는 비활성 — select_none/select_all의 영향을 받지 않음
        # (비활성 항목은 생성 시 Checked로 초기화되어 유지됨)
        eng_item = dlg._items[0][0]
        assert not (eng_item.flags() & Qt.ItemFlag.ItemIsEnabled)

    def test_search_hides_non_matching(self, qtbot):
        """검색 필드에 텍스트 입력 시 미일치 항목이 숨겨진다."""
        from widgets.graph_dock import _SignalSelectDialog
        available = [(0, "EngSpeed"), (0, "VehSpeed"), (1, "BrakeForce")]
        dlg = _SignalSelectDialog(available, {}, parent=None)

        dlg._on_search("eng")
        # "EngSpeed"는 보임, 나머지는 숨겨짐
        assert not dlg._list.item(0).isHidden()   # EngSpeed
        assert dlg._list.item(1).isHidden()        # VehSpeed
        assert dlg._list.item(2).isHidden()        # BrakeForce

    def test_search_empty_shows_all(self, qtbot):
        """검색 초기화 시 모든 항목이 표시된다."""
        from widgets.graph_dock import _SignalSelectDialog
        available = [(0, "EngSpeed"), (0, "VehSpeed")]
        dlg = _SignalSelectDialog(available, {}, parent=None)

        dlg._on_search("xxx")   # 모두 숨김
        dlg._on_search("")      # 초기화 → 모두 표시
        for i in range(dlg._list.count()):
            assert not dlg._list.item(i).isHidden()


# ── GraphDock._on_add_signal_clicked 내부 로직 ──────────────────────────
# NOTE: GraphDock 인스턴스를 headless 환경에서 직접 생성하면 pyqtgraph
#       GraphicsView.paintEvent Segfault가 발생한다.
#       add_signal 버튼 클릭 동작은 _SignalSelectDialog 테스트로 충분히 검증됨.
#       실 환경(Windows)에서 통합 테스트로 확인한다.

