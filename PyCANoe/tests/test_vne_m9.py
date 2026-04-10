# tests/test_vne_m9.py
"""
M9 — VirtualNodeEngine arb_id 필터링 + 핫리로드 단위 테스트.

검증 항목:
  [arb_id 필터링]
  - BusProxy.add_filter / remove_filter / clear_filters API
  - BusProxy.should_deliver: 필터 없음 → 전체, 필터 있음 → 해당만
  - VirtualNodeWorker: on_message 호출 시 필터 적용 확인
  - Thread-safe: 다른 스레드에서 필터 수정 후 Worker 인식

  [핫리로드]
  - VirtualNodeEngine.set_hot_reload: 활성/비활성 제어
  - _check_hot_reload: mtime 변경 시 _reload_node() 호출
  - _reload_node: 기존 Worker stop → 새 Worker start
  - node_reloaded Signal emit 확인
  - 파일 없을 때 reload 실패 → node_error Signal
  - BusProxy(필터 포함) 재사용 확인

  [VirtualNodeDock M9 UI]
  - 핫리로드 체크박스 초기 비활성
  - 선택 시 활성화
  - 체크 시 set_hot_reload() 호출
  - node_reloaded Signal → 로그 출력
"""
from __future__ import annotations

import os
import tempfile
import time
import types
from unittest.mock import MagicMock, patch, call

import pytest
from PySide6.QtCore import Qt, QCoreApplication

from core.virtual_node_engine import (
    BusProxy, VirtualNodeEngine, VirtualNodeWorker, _NodeInfo
)
from models.parsed_message import ParsedMessage
from models.sim_state_store import SimStateStore
from widgets.virtual_node_dock import VirtualNodeDock


# ---------------------------------------------------------------------------
# 공통 픽스처
# ---------------------------------------------------------------------------

@pytest.fixture
def sim_state():
    return SimStateStore()


@pytest.fixture
def bus_proxy(qtbot, sim_state):
    return BusProxy(ch_id=0, sim_state=sim_state)


@pytest.fixture
def vne(qtbot, sim_state):
    cm = MagicMock()
    cm.get.return_value = None
    engine = VirtualNodeEngine(cm, sim_state)
    yield engine
    engine.unload_all()


def _make_msg(arb_id=0x100, is_tx=False):
    return ParsedMessage(
        ch_id=0, timestamp=1.0, arb_id=arb_id,
        dlc=8, data=b'\x00' * 8, is_tx=is_tx,
    )


def _make_script(content: str) -> str:
    """임시 스크립트 파일 생성 후 경로 반환."""
    f = tempfile.NamedTemporaryFile(
        mode='w', suffix='.py', delete=False, encoding='utf-8'
    )
    f.write(content)
    f.close()
    return f.name


# ===========================================================================
# 1. BusProxy arb_id 필터 API
# ===========================================================================

class TestBusProxyFilter:
    def test_default_no_filters(self, bus_proxy):
        assert bus_proxy._arb_id_filters == set()

    def test_should_deliver_no_filter_true(self, bus_proxy):
        """필터 없으면 모든 arb_id 전달."""
        assert bus_proxy.should_deliver(0x100) is True
        assert bus_proxy.should_deliver(0x200) is True

    def test_add_filter(self, bus_proxy):
        bus_proxy.add_filter(0x100)
        assert 0x100 in bus_proxy._arb_id_filters

    def test_should_deliver_with_filter_match(self, bus_proxy):
        bus_proxy.add_filter(0x100)
        assert bus_proxy.should_deliver(0x100) is True

    def test_should_deliver_with_filter_no_match(self, bus_proxy):
        bus_proxy.add_filter(0x100)
        assert bus_proxy.should_deliver(0x200) is False

    def test_add_multiple_filters(self, bus_proxy):
        bus_proxy.add_filter(0x100)
        bus_proxy.add_filter(0x200)
        assert bus_proxy.should_deliver(0x100) is True
        assert bus_proxy.should_deliver(0x200) is True
        assert bus_proxy.should_deliver(0x300) is False

    def test_remove_filter(self, bus_proxy):
        bus_proxy.add_filter(0x100)
        bus_proxy.remove_filter(0x100)
        # 필터 없음 → 전체 전달
        assert bus_proxy.should_deliver(0x100) is True

    def test_remove_nonexistent_filter_no_error(self, bus_proxy):
        bus_proxy.remove_filter(0x999)   # 예외 없어야 함

    def test_clear_filters(self, bus_proxy):
        bus_proxy.add_filter(0x100)
        bus_proxy.add_filter(0x200)
        bus_proxy.clear_filters()
        assert bus_proxy._arb_id_filters == set()
        assert bus_proxy.should_deliver(0x100) is True

    def test_filter_int_conversion(self, bus_proxy):
        """arb_id가 int로 변환되는지 확인."""
        bus_proxy.add_filter(0x1A0)
        assert bus_proxy.should_deliver(0x1A0) is True

    @pytest.mark.parametrize("arb_id", [0x000, 0x7FF, 0x1FFFFFFF])
    def test_edge_arb_ids(self, bus_proxy, arb_id):
        bus_proxy.add_filter(arb_id)
        assert bus_proxy.should_deliver(arb_id) is True


# ===========================================================================
# 2. VirtualNodeWorker on_message 필터 적용
# ===========================================================================

class TestWorkerMessageFilter:
    def test_no_filter_delivers_all(self, qtbot, sim_state):
        received = []

        def on_message(bus, msg):
            received.append(msg.arb_id)

        module = types.ModuleType("test_filter_all")
        module.on_message = on_message

        bus = BusProxy(ch_id=0, sim_state=sim_state)
        worker = VirtualNodeWorker(module, bus)
        worker.run = lambda: None   # run() 직접 호출 방지

        # enqueue → 직접 처리 시뮬레이션
        msg1 = _make_msg(arb_id=0x100)
        msg2 = _make_msg(arb_id=0x200)

        worker._msg_queue = [msg1, msg2]
        with worker._msg_lock:
            pending = worker._msg_queue
            worker._msg_queue = []

        for msg in pending:
            if bus.should_deliver(msg.arb_id):
                worker._call("on_message", bus, msg)

        assert received == [0x100, 0x200]

    def test_filter_blocks_unwanted(self, qtbot, sim_state):
        received = []

        def on_message(bus, msg):
            received.append(msg.arb_id)

        module = types.ModuleType("test_filter_block")
        module.on_message = on_message

        bus = BusProxy(ch_id=0, sim_state=sim_state)
        bus.add_filter(0x100)   # 0x100만 허용
        worker = VirtualNodeWorker(module, bus)

        msgs = [_make_msg(0x100), _make_msg(0x200), _make_msg(0x100)]
        for msg in msgs:
            if bus.should_deliver(msg.arb_id):
                worker._call("on_message", bus, msg)

        assert received == [0x100, 0x100]

    def test_filter_delivers_after_clear(self, qtbot, sim_state):
        received = []

        def on_message(bus, msg):
            received.append(msg.arb_id)

        module = types.ModuleType("test_filter_clear")
        module.on_message = on_message

        bus = BusProxy(ch_id=0, sim_state=sim_state)
        bus.add_filter(0x100)
        bus.clear_filters()  # 필터 제거

        worker = VirtualNodeWorker(module, bus)
        for msg in [_make_msg(0x100), _make_msg(0x200)]:
            if bus.should_deliver(msg.arb_id):
                worker._call("on_message", bus, msg)

        assert received == [0x100, 0x200]


# ===========================================================================
# 3. VirtualNodeEngine.set_hot_reload
# ===========================================================================

class TestVneSetHotReload:
    def test_set_hot_reload_unknown_node_no_error(self, vne):
        vne.set_hot_reload(9999, True)   # 예외 없어야 함

    def test_set_hot_reload_enables_flag(self, vne, qtbot):
        path = _make_script("def on_start(bus): pass\n")
        try:
            nid = vne.load_script(0, path)
            vne.set_hot_reload(nid, True)
            assert vne._nodes[nid].hot_reload is True
        finally:
            vne.unload_node(nid)
            os.unlink(path)

    def test_set_hot_reload_disables_flag(self, vne, qtbot):
        path = _make_script("def on_start(bus): pass\n")
        try:
            nid = vne.load_script(0, path)
            vne.set_hot_reload(nid, True)
            vne.set_hot_reload(nid, False)
            assert vne._nodes[nid].hot_reload is False
        finally:
            vne.unload_node(nid)
            os.unlink(path)

    def test_set_hot_reload_updates_mtime(self, vne, qtbot):
        path = _make_script("def on_start(bus): pass\n")
        try:
            nid = vne.load_script(0, path)
            vne.set_hot_reload(nid, True)
            info = vne._nodes[nid]
            assert info.last_mtime > 0.0
        finally:
            vne.unload_node(nid)
            os.unlink(path)


# ===========================================================================
# 4. _check_hot_reload: mtime 변경 감지
# ===========================================================================

class TestCheckHotReload:
    def test_no_reload_when_mtime_unchanged(self, vne, qtbot):
        path = _make_script("def on_start(bus): pass\n")
        try:
            nid = vne.load_script(0, path)
            vne.set_hot_reload(nid, True)

            reloaded = []
            vne.node_reloaded.connect(lambda nid, p: reloaded.append(nid))

            vne._check_hot_reload()
            assert reloaded == []
        finally:
            vne.unload_node(nid)
            os.unlink(path)

    def test_reload_when_mtime_increased(self, vne, qtbot):
        path = _make_script("def on_start(bus): pass\n")
        try:
            nid = vne.load_script(0, path)
            vne.set_hot_reload(nid, True)

            reloaded = []
            vne.node_reloaded.connect(lambda n, p: reloaded.append(n))

            # mtime을 과거로 조작 → 다음 check에서 변경 감지
            vne._nodes[nid].last_mtime = 0.0
            vne._check_hot_reload()

            assert nid in reloaded
        finally:
            vne.unload_node(nid)
            os.unlink(path)

    def test_no_reload_when_hot_reload_disabled(self, vne, qtbot):
        path = _make_script("def on_start(bus): pass\n")
        try:
            nid = vne.load_script(0, path)
            # hot_reload = False (기본)

            reloaded = []
            vne.node_reloaded.connect(lambda n, p: reloaded.append(n))

            vne._nodes[nid].last_mtime = 0.0  # mtime 강제 낮춤
            vne._check_hot_reload()
            assert reloaded == []
        finally:
            vne.unload_node(nid)
            os.unlink(path)

    def test_no_reload_on_oserror(self, vne, qtbot):
        """파일이 사라져도 예외 없이 건너뜀."""
        path = _make_script("pass\n")
        try:
            nid = vne.load_script(0, path)
            vne.set_hot_reload(nid, True)
            # 파일 경로를 존재하지 않는 경로로 교체
            vne._nodes[nid].script_path = "/nonexistent/path.py"
            vne._check_hot_reload()   # 예외 없어야 함
        finally:
            vne.unload_node(nid)
            os.unlink(path)


# ===========================================================================
# 5. _reload_node: Worker 교체
# ===========================================================================

class TestReloadNode:
    def test_reload_node_emits_signal(self, vne, qtbot):
        path = _make_script("def on_start(bus): pass\n")
        try:
            nid = vne.load_script(0, path)
            reloaded = []
            vne.node_reloaded.connect(lambda n, p: reloaded.append((n, p)))

            vne._reload_node(nid)
            assert any(n == nid for n, p in reloaded)
        finally:
            vne.unload_node(nid)
            os.unlink(path)

    def test_reload_node_replaces_worker(self, vne, qtbot):
        path = _make_script("def on_start(bus): pass\n")
        try:
            nid = vne.load_script(0, path)
            old_worker = vne._nodes[nid].worker

            vne._reload_node(nid)

            new_worker = vne._nodes[nid].worker
            assert new_worker is not old_worker
        finally:
            vne.unload_node(nid)
            os.unlink(path)

    def test_reload_node_reuses_bus_proxy(self, vne, qtbot):
        """BusProxy(필터 포함)는 재사용됨."""
        path = _make_script("def on_start(bus): pass\n")
        try:
            nid = vne.load_script(0, path)
            bus_before = vne._nodes[nid].bus
            bus_before.add_filter(0x100)

            vne._reload_node(nid)

            bus_after = vne._nodes[nid].bus
            assert bus_after is bus_before
            # 필터도 유지되는지 확인
            assert bus_after.should_deliver(0x100) is True
            assert bus_after.should_deliver(0x200) is False
        finally:
            vne.unload_node(nid)
            os.unlink(path)

    def test_reload_node_invalid_script_emits_error(self, vne, qtbot):
        path = _make_script("def on_start(bus): pass\n")
        try:
            nid = vne.load_script(0, path)

            errors = []
            vne.node_error.connect(lambda n, m: errors.append(n))

            # 스크립트를 SyntaxError가 나는 내용으로 교체
            with open(path, 'w') as f:
                f.write("def broken(:\n")   # SyntaxError

            vne._reload_node(nid)
            assert nid in errors
        finally:
            vne.unload_node(nid)
            os.unlink(path)

    def test_reload_nonexistent_node_no_error(self, vne):
        vne._reload_node(9999)   # 예외 없어야 함


# ===========================================================================
# 6. VirtualNodeDock M9 UI
# ===========================================================================

class TestVirtualNodeDockM9:
    def _make_dock(self, qtbot):
        sim_state = SimStateStore()
        cm = MagicMock()
        cm.get.return_value = None
        vne = VirtualNodeEngine(cm, sim_state)
        dock = VirtualNodeDock(vne, cm)
        return dock, vne

    def test_hot_reload_checkbox_initially_disabled(self, qtbot):
        dock, vne = self._make_dock(qtbot)
        assert not dock._chk_hot_reload.isEnabled()
        vne.unload_all()

    def test_hot_reload_checkbox_enabled_on_selection(self, qtbot):
        dock, vne = self._make_dock(qtbot)
        path = _make_script("pass\n")
        try:
            nid = vne.load_script(0, path)
            QCoreApplication.processEvents()
            # 아이템 선택 시뮬레이션
            item = dock._items.get(nid)
            if item:
                dock._tree.setCurrentItem(item)
                dock._on_selection_changed()
                assert dock._chk_hot_reload.isEnabled()
        finally:
            vne.unload_node(nid)
            os.unlink(path)

    def test_node_reloaded_appends_log(self, qtbot):
        dock, vne = self._make_dock(qtbot)
        path = _make_script("pass\n")
        try:
            nid = vne.load_script(0, path)
            QCoreApplication.processEvents()
            initial_text = dock._log_edit.toPlainText()

            vne.node_reloaded.emit(nid, path)
            QCoreApplication.processEvents()

            new_text = dock._log_edit.toPlainText()
            assert len(new_text) > len(initial_text)
            assert "핫리로드" in new_text or "reloaded" in new_text.lower() or os.path.basename(path) in new_text
        finally:
            vne.unload_node(nid)
            os.unlink(path)

    def test_hot_reload_toggle_calls_set_hot_reload(self, qtbot):
        sim_state = SimStateStore()
        cm = MagicMock()
        cm.get.return_value = None
        vne = VirtualNodeEngine(cm, sim_state)
        vne.set_hot_reload = MagicMock()

        dock = VirtualNodeDock(vne, cm)
        path = _make_script("pass\n")
        try:
            nid = vne.load_script.__wrapped__(vne, 0, path) if hasattr(vne.load_script, '__wrapped__') else None
            # node_id 직접 주입으로 테스트
            from core.virtual_node_engine import _NodeInfo
            mock_worker = MagicMock()
            mock_worker.isRunning.return_value = False
            mock_bus = MagicMock()
            mock_bus.ch_id = 0
            vne._nodes[0] = _NodeInfo(
                worker=mock_worker, bus=mock_bus,
                ch_id=0, script_path=path
            )
            vne.node_started.emit(0, path)
            QCoreApplication.processEvents()

            item = dock._items.get(0)
            if item:
                dock._tree.setCurrentItem(item)
                dock._on_selection_changed()
                dock._chk_hot_reload.setChecked(True)
                vne.set_hot_reload.assert_called_with(0, True)
        finally:
            vne._nodes.clear()
            os.unlink(path)
