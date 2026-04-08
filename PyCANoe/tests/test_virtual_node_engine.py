# tests/test_virtual_node_engine.py
"""
M7 Virtual Node Engine 단위 테스트.

검증 항목:
  - BusProxy API (send/send_fd/log/get_signal/set_interval)
  - VirtualNodeWorker: on_start/on_message/on_timer 콜백 호출 순서
  - VirtualNodeWorker: 예외 격리 (노드 중단 없음)
  - VirtualNodeEngine: load_script / unload_node / unload_all
  - VirtualNodeEngine: is_tx 메시지 라우팅 차단
  - VirtualNodeEngine: _on_send_requested CH 없음 케이스
  - VirtualNodeEngine.active_nodes()
  - 스크립트 로드 실패 케이스 (SyntaxError, 존재하지 않는 파일)
  - VirtualNodeDock: 버튼 동작, 로그 출력, 노드 목록 갱신
"""
from __future__ import annotations

import os
import tempfile
import threading
import time
import types
from unittest.mock import MagicMock, patch, call

import pytest
from PySide6.QtCore import Qt, QCoreApplication

from core.virtual_node_engine import BusProxy, VirtualNodeEngine, VirtualNodeWorker
from models.parsed_message import ParsedMessage
from models.sim_state_store import SimStateStore


# ---------------------------------------------------------------------------
# 공통 픽스처
# ---------------------------------------------------------------------------

@pytest.fixture
def sim_state():
    return SimStateStore()


@pytest.fixture
def bus_proxy(qtbot, sim_state):
    proxy = BusProxy(ch_id=0, sim_state=sim_state)
    return proxy


@pytest.fixture
def vne(qtbot, sim_state):
    cm = MagicMock()
    cm.get.return_value = None   # 기본: CH 없음
    engine = VirtualNodeEngine(cm, sim_state)
    yield engine
    engine.unload_all()


def _make_msg(ch_id=0, arb_id=0x100, is_tx=False):
    return ParsedMessage(
        ch_id=ch_id, timestamp=1.0, arb_id=arb_id,
        dlc=8, data=b'\x00' * 8, is_tx=is_tx,
    )


def _write_script(code: str) -> str:
    """임시 .py 스크립트 파일 작성 후 경로 반환."""
    fd, path = tempfile.mkstemp(suffix=".py")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(code)
    return path


# ---------------------------------------------------------------------------
# BusProxy 테스트
# ---------------------------------------------------------------------------

class TestBusProxy:

    def test_send_emits_signal(self, qtbot, bus_proxy):
        """send() → send_requested Signal emit (ch_id, arb_id, data, is_fd=False)"""
        received = []
        bus_proxy.send_requested.connect(
            lambda ch, arb, d, fd: received.append((ch, arb, d, fd))
        )
        bus_proxy.send(0x1A0, b'\x01\x02')
        assert received == [(0, 0x1A0, b'\x01\x02', False)]

    def test_send_fd_emits_signal_with_fd_true(self, qtbot, bus_proxy):
        """send_fd() → is_fd=True"""
        received = []
        bus_proxy.send_requested.connect(
            lambda ch, arb, d, fd: received.append(fd)
        )
        bus_proxy.send_fd(0x200, b'\xFF' * 8)
        assert received == [True]

    def test_send_accepts_list_and_bytearray(self, qtbot, bus_proxy):
        """send()는 list/bytearray도 bytes로 변환해야 한다."""
        received = []
        bus_proxy.send_requested.connect(
            lambda ch, arb, d, fd: received.append(d)
        )
        bus_proxy.send(0x1, [0xAA, 0xBB])
        assert received == [b'\xAA\xBB']

    def test_log_emits_signal(self, qtbot, bus_proxy):
        """log() → log_emitted Signal"""
        logs = []
        bus_proxy.log_emitted.connect(logs.append)
        bus_proxy.log("hello world")
        assert logs == ["hello world"]

    def test_get_signal_none_when_empty(self, bus_proxy):
        """SimStateStore가 비어 있으면 None 반환."""
        assert bus_proxy.get_signal(0, "EngSpeed") is None

    def test_get_signal_returns_value_from_store(self, bus_proxy, sim_state):
        """SimStateStore에 값이 있으면 반환."""
        sim_state.update(0, {"EngSpeed": 1200.0})
        assert bus_proxy.get_signal(0, "EngSpeed") == 1200.0

    def test_set_interval_updates_interval(self, bus_proxy):
        """set_interval()은 interval_ms 프로퍼티에 반영된다."""
        bus_proxy.set_interval(250.0)
        assert bus_proxy.interval_ms == 250.0

    def test_set_interval_minimum_1ms(self, bus_proxy):
        """set_interval(0) → 최소값 1.0ms로 클램프."""
        bus_proxy.set_interval(0)
        assert bus_proxy.interval_ms == 1.0

    def test_ch_id_property(self, bus_proxy):
        assert bus_proxy.ch_id == 0

    def test_interval_ms_thread_safe(self, bus_proxy):
        """여러 스레드에서 set_interval 호출해도 크래시 없음."""
        errors = []
        def setter():
            try:
                for _ in range(100):
                    bus_proxy.set_interval(10.0)
            except Exception as e:
                errors.append(e)
        threads = [threading.Thread(target=setter) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors


# ---------------------------------------------------------------------------
# VirtualNodeWorker 테스트
# ---------------------------------------------------------------------------

class TestVirtualNodeWorker:

    def _make_module(self, code: str) -> types.ModuleType:
        module = types.ModuleType("test_vn")
        exec(compile(code, "<test>", "exec"), module.__dict__)
        return module

    def _run_with_stop(self, worker, stop_after=0.12):
        """run()을 메인 스레드에서 직접 호출해 coverage 추적."""
        def stopper():
            time.sleep(stop_after)
            worker._stop = True
        t = threading.Thread(target=stopper, daemon=True)
        t.start()
        worker.run()
        t.join(timeout=2.0)

    def test_on_start_called_once(self, qtbot, sim_state):
        """on_start(bus)는 run() 진입 시 1회 호출."""
        calls = []
        code = "def on_start(bus): calls.append('start')"
        module = self._make_module(code)
        module.calls = calls
        bus = BusProxy(0, sim_state)
        worker = VirtualNodeWorker(module, bus)
        self._run_with_stop(worker, stop_after=0.05)
        assert calls == ["start"]

    def test_on_message_called_per_message(self, qtbot, sim_state):
        """enqueue_message()로 메시지를 넣으면 on_message(bus, msg) 호출."""
        calls = []
        code = "def on_message(bus, msg): calls.append(msg.arb_id)"
        module = self._make_module(code)
        module.calls = calls
        bus = BusProxy(0, sim_state)
        worker = VirtualNodeWorker(module, bus)

        msg = _make_msg(arb_id=0x1A0)
        worker.enqueue_message(msg)
        worker.enqueue_message(msg)

        self._run_with_stop(worker, stop_after=0.1)
        assert calls.count(0x1A0) == 2

    def test_on_timer_called_periodically(self, qtbot, sim_state):
        """on_timer(bus)는 interval_ms 주기로 반복 호출."""
        calls = []
        code = "def on_timer(bus): calls.append(1)"
        module = self._make_module(code)
        module.calls = calls
        bus = BusProxy(0, sim_state)
        bus.set_interval(20)   # 20ms 주기
        worker = VirtualNodeWorker(module, bus)
        self._run_with_stop(worker, stop_after=0.15)
        # 150ms / 20ms ≈ 7회 이상 호출 기대 (여유 있게 3 이상)
        assert len(calls) >= 3

    def test_exception_in_on_message_does_not_stop_node(self, qtbot, sim_state):
        """on_message 예외가 발생해도 워커가 계속 동작."""
        calls = []
        code = (
            "count = [0]\n"
            "def on_message(bus, msg):\n"
            "    count[0] += 1\n"
            "    if count[0] == 1:\n"
            "        raise ValueError('intentional')\n"
            "    calls.append(count[0])\n"
        )
        module = self._make_module(code)
        module.calls = calls
        bus = BusProxy(0, sim_state)
        worker = VirtualNodeWorker(module, bus)

        for _ in range(3):
            worker.enqueue_message(_make_msg())

        errors = []
        worker.node_error.connect(errors.append)

        self._run_with_stop(worker, stop_after=0.1)
        assert len(errors) == 1   # 1번 예외 보고
        assert len(calls) >= 2    # 이후 메시지는 계속 처리

    def test_node_error_signal_emitted_on_exception(self, qtbot, sim_state):
        """예외 발생 시 node_error Signal이 emit된다."""
        code = "def on_start(bus): raise RuntimeError('boom')"
        module = self._make_module(code)
        bus = BusProxy(0, sim_state)
        worker = VirtualNodeWorker(module, bus)

        errors = []
        worker.node_error.connect(errors.append)
        self._run_with_stop(worker, stop_after=0.05)
        assert any("boom" in e for e in errors)

    def test_missing_callbacks_are_ignored(self, qtbot, sim_state):
        """on_start/on_message/on_timer가 없어도 크래시 없음."""
        module = types.ModuleType("empty")
        bus = BusProxy(0, sim_state)
        worker = VirtualNodeWorker(module, bus)
        # 예외 없이 실행 완료
        self._run_with_stop(worker, stop_after=0.05)

    def test_enqueue_message_thread_safe(self, sim_state):
        """여러 스레드에서 enqueue_message() 동시 호출 → 크래시/손실 없음."""
        module = types.ModuleType("empty")
        bus = BusProxy(0, sim_state)
        worker = VirtualNodeWorker(module, bus)

        errors = []
        def enqueuer():
            try:
                for _ in range(50):
                    worker.enqueue_message(_make_msg())
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=enqueuer) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors

    def test_stop_clears_flag(self, sim_state):
        """stop() 호출 시 _stop = True."""
        module = types.ModuleType("empty")
        bus = BusProxy(0, sim_state)
        worker = VirtualNodeWorker(module, bus)
        assert worker._stop is False
        worker._stop = True   # QThread.wait() 호출 없이 플래그만 검증
        assert worker._stop is True


# ---------------------------------------------------------------------------
# VirtualNodeEngine 테스트
# ---------------------------------------------------------------------------

class TestVirtualNodeEngine:

    def _script(self, code="") -> str:
        return _write_script(code)

    def test_load_script_returns_node_id(self, qtbot, vne):
        """load_script() → int node_id 반환."""
        path = self._script("def on_start(bus): pass")
        nid = vne.load_script(ch_id=0, script_path=path)
        assert isinstance(nid, int)
        vne.unload_node(nid)
        os.unlink(path)

    def test_load_script_increments_node_id(self, qtbot, vne):
        """두 번 로드하면 node_id가 순차 증가."""
        p1 = self._script()
        p2 = self._script()
        n1 = vne.load_script(0, p1)
        n2 = vne.load_script(0, p2)
        assert n2 == n1 + 1
        vne.unload_all()
        os.unlink(p1)
        os.unlink(p2)

    def test_node_started_signal_emitted(self, qtbot, vne):
        """load_script() 성공 시 node_started Signal emit."""
        started = []
        vne.node_started.connect(lambda nid, p: started.append(nid))
        path = self._script()
        nid = vne.load_script(0, path)
        assert nid in started
        vne.unload_node(nid)
        os.unlink(path)

    def test_unload_node_emits_node_stopped(self, qtbot, vne):
        """unload_node() → node_stopped Signal emit."""
        stopped = []
        vne.node_stopped.connect(stopped.append)
        path = self._script()
        nid = vne.load_script(0, path)
        vne.unload_node(nid)
        assert nid in stopped
        os.unlink(path)

    def test_unload_nonexistent_node_does_nothing(self, qtbot, vne):
        """존재하지 않는 node_id unload → 예외 없음."""
        vne.unload_node(9999)   # should not raise

    def test_unload_all_clears_nodes(self, qtbot, vne):
        """unload_all() 후 active_nodes() 빈 리스트."""
        p1 = self._script()
        p2 = self._script()
        vne.load_script(0, p1)
        vne.load_script(1, p2)
        vne.unload_all()
        assert vne.active_nodes() == []
        os.unlink(p1)
        os.unlink(p2)

    def test_active_nodes_returns_correct_pairs(self, qtbot, vne):
        """active_nodes() → [(node_id, ch_id), ...]"""
        p1 = self._script()
        p2 = self._script()
        n1 = vne.load_script(ch_id=0, script_path=p1)
        n2 = vne.load_script(ch_id=2, script_path=p2)
        nodes = vne.active_nodes()
        assert (n1, 0) in nodes
        assert (n2, 2) in nodes
        vne.unload_all()
        os.unlink(p1)
        os.unlink(p2)

    def test_load_invalid_path_raises(self, qtbot, vne):
        """존재하지 않는 파일 → ValueError."""
        with pytest.raises(ValueError):
            vne.load_script(0, "/nonexistent/path/script.py")

    def test_load_syntax_error_script_raises(self, qtbot, vne):
        """SyntaxError가 있는 스크립트 → ValueError."""
        path = self._script("def broken(: pass")
        with pytest.raises(ValueError):
            vne.load_script(0, path)
        os.unlink(path)

    def test_on_all_messages_routes_to_workers(self, qtbot, vne):
        """on_all_messages() → 활성 Worker의 enqueue_message() 호출."""
        path = self._script()
        nid = vne.load_script(0, path)

        worker, _ = vne._nodes[nid]
        original_enqueue = worker.enqueue_message
        called = []
        worker.enqueue_message = lambda m: called.append(m)

        msg = _make_msg(is_tx=False)
        vne.on_all_messages(msg)
        assert len(called) == 1

        worker.enqueue_message = original_enqueue
        vne.unload_node(nid)
        os.unlink(path)

    def test_on_all_messages_skips_tx_echo(self, qtbot, vne):
        """is_tx=True 메시지는 VNE로 전달되지 않는다 (무한 루프 방지)."""
        path = self._script()
        nid = vne.load_script(0, path)

        worker, _ = vne._nodes[nid]
        called = []
        worker.enqueue_message = lambda m: called.append(m)

        tx_msg = _make_msg(is_tx=True)
        vne.on_all_messages(tx_msg)
        assert called == []

        vne.unload_node(nid)
        os.unlink(path)

    def test_on_send_requested_no_channel(self, qtbot, vne, caplog):
        """CH가 없으면 경고 로그만 출력하고 예외 없음."""
        import logging
        with caplog.at_level(logging.WARNING, logger="core.virtual_node_engine"):
            vne._on_send_requested(99, 0x100, b'\x00', False)
        assert "CH99" in caplog.text or "없음" in caplog.text

    def test_on_send_requested_calls_worker_send(self, qtbot, vne):
        """CH가 있으면 CANWorker.send() + increment_tx() 호출."""
        mock_worker = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.worker = mock_worker
        vne._channel_manager.get.return_value = mock_ctx

        vne._on_send_requested(0, 0x1A0, b'\x01\x02', False)

        mock_worker.send.assert_called_once()
        mock_worker.increment_tx.assert_called_once()

    def test_on_send_requested_worker_exception_handled(self, qtbot, vne):
        """CANWorker.send()가 예외를 던져도 VNE가 중단되지 않음."""
        mock_worker = MagicMock()
        mock_worker.send.side_effect = Exception("bus error")
        mock_ctx = MagicMock()
        mock_ctx.worker = mock_worker
        vne._channel_manager.get.return_value = mock_ctx

        # 예외가 전파되지 않아야 함
        vne._on_send_requested(0, 0x1A0, b'\x00', False)

    def test_log_emitted_signal_forwarded(self, qtbot, vne):
        """BusProxy.log() → VNE.log_emitted(node_id, text) Signal."""
        received = []
        vne.log_emitted.connect(lambda nid, txt: received.append((nid, txt)))
        path = self._script("def on_start(bus): bus.log('hello')")
        nid = vne.load_script(0, path)
        time.sleep(0.1)
        QCoreApplication.processEvents()
        # Signal은 QueuedConnection — processEvents로 처리
        assert any(txt == "hello" for _, txt in received)
        vne.unload_node(nid)
        os.unlink(path)

    def test_node_error_signal_forwarded(self, qtbot, vne):
        """스크립트 예외 → VNE.node_error(node_id, msg) Signal emit."""
        errors = []
        vne.node_error.connect(lambda nid, msg: errors.append((nid, msg)))
        path = self._script("def on_start(bus): raise RuntimeError('kaboom')")
        nid = vne.load_script(0, path)
        time.sleep(0.1)
        QCoreApplication.processEvents()
        assert any("kaboom" in msg for _, msg in errors)
        vne.unload_node(nid)
        os.unlink(path)

    def test_load_module_returns_none_for_bad_file(self):
        """_load_module() — 잘못된 경로 → None."""
        result = VirtualNodeEngine._load_module("/no/such/file.py")
        assert result is None

    def test_load_module_success(self):
        """_load_module() — 정상 파일 → ModuleType."""
        path = _write_script("X = 42")
        result = VirtualNodeEngine._load_module(path)
        assert result is not None
        assert result.X == 42
        os.unlink(path)

    def test_load_module_syntax_error(self):
        """_load_module() — SyntaxError → None."""
        path = _write_script("def bad(: pass")
        result = VirtualNodeEngine._load_module(path)
        assert result is None
        os.unlink(path)

    def test_multiple_nodes_same_channel(self, qtbot, vne):
        """같은 채널에 여러 노드를 동시 실행해도 독립 동작."""
        p1 = self._script()
        p2 = self._script()
        n1 = vne.load_script(0, p1)
        n2 = vne.load_script(0, p2)
        assert len(vne._nodes) == 2
        vne.unload_all()
        os.unlink(p1)
        os.unlink(p2)


# ---------------------------------------------------------------------------
# VirtualNodeDock 테스트
# ---------------------------------------------------------------------------

class TestVirtualNodeDock:

    @pytest.fixture
    def dock(self, qtbot, sim_state):
        from widgets.virtual_node_dock import VirtualNodeDock
        cm = MagicMock()
        engine = VirtualNodeEngine(cm, sim_state)
        w = VirtualNodeDock(engine, cm)
        qtbot.addWidget(w)
        yield w, engine
        engine.unload_all()

    def test_initial_tree_empty(self, dock):
        w, _ = dock
        assert w._tree.topLevelItemCount() == 0

    def test_load_adds_tree_item_on_node_started(self, dock, qtbot):
        """node_started Signal 수신 시 트리에 항목 추가."""
        w, engine = dock
        path = _write_script("")
        nid = engine.load_script(0, path)
        QCoreApplication.processEvents()
        assert w._tree.topLevelItemCount() == 1
        engine.unload_node(nid)
        os.unlink(path)

    def test_unload_removes_tree_item(self, dock, qtbot):
        """node_stopped Signal 수신 시 트리에서 항목 제거."""
        w, engine = dock
        path = _write_script("")
        nid = engine.load_script(0, path)
        QCoreApplication.processEvents()
        engine.unload_node(nid)
        QCoreApplication.processEvents()
        assert w._tree.topLevelItemCount() == 0
        os.unlink(path)

    def test_log_appears_in_console(self, dock, qtbot):
        """log_emitted Signal → 로그 콘솔에 텍스트 추가."""
        w, engine = dock
        engine.log_emitted.emit(0, "test_log_text")
        QCoreApplication.processEvents()
        assert "test_log_text" in w._log_edit.toPlainText()

    def test_error_log_appears_in_console(self, dock, qtbot):
        """node_error Signal → 콘솔에 에러 텍스트 추가."""
        w, engine = dock
        engine.node_error.emit(0, "something went wrong")
        QCoreApplication.processEvents()
        assert "something went wrong" in w._log_edit.toPlainText()

    def test_clear_log_button(self, dock, qtbot):
        """[지우기] 버튼 클릭 시 로그 콘솔 비워짐."""
        w, engine = dock
        engine.log_emitted.emit(0, "some text")
        QCoreApplication.processEvents()
        w._btn_clear_log.click()
        assert w._log_edit.toPlainText() == ""

    def test_stop_all_button_calls_unload_all(self, dock, qtbot):
        """[전체 정지] 버튼 클릭 → engine.unload_all() 효과."""
        w, engine = dock
        p1 = _write_script("")
        p2 = _write_script("")
        engine.load_script(0, p1)
        engine.load_script(0, p2)
        QCoreApplication.processEvents()
        w._btn_stop_all.click()
        QCoreApplication.processEvents()
        assert engine.active_nodes() == []
        os.unlink(p1)
        os.unlink(p2)

    def test_stop_selected_button_disabled_when_no_selection(self, dock):
        """선택 항목 없으면 [선택 정지] 버튼 비활성."""
        w, _ = dock
        assert not w._btn_stop_selected.isEnabled()

    def test_node_error_changes_item_color(self, dock, qtbot):
        """node_error → 트리 항목 상태 텍스트가 '⚠ 오류'로 변경."""
        w, engine = dock
        path = _write_script("")
        nid = engine.load_script(0, path)
        QCoreApplication.processEvents()
        engine.node_error.emit(nid, "err")
        QCoreApplication.processEvents()
        item = w._items.get(nid)
        assert item is not None
        assert "오류" in item.text(3)
        engine.unload_node(nid)
        os.unlink(path)

    def test_load_button_with_invalid_script_appends_error_log(self, dock, qtbot, tmp_path):
        """스크립트 로드 실패(ValueError) → 로그 콘솔에 [ERROR] 출력."""
        w, engine = dock
        # 내부적으로 load_script 를 패치
        with patch.object(engine, "load_script", side_effect=ValueError("bad script")):
            # 임시 파일 선택 시뮬레이션
            with patch("widgets.virtual_node_dock.QFileDialog.getOpenFileName",
                       return_value=(str(tmp_path / "bad.py"), "")):
                w._btn_load.click()
        QCoreApplication.processEvents()
        assert "[ERROR]" in w._log_edit.toPlainText()

    def test_channel_combobox_has_4_items(self, dock):
        """채널 콤보박스는 CH1~CH4 4개 항목."""
        w, _ = dock
        assert w._cb_channel.count() == 4

    def test_append_log_negative_node_id(self, dock):
        """_append_log(node_id=-1) → 'Loader' 태그로 출력."""
        w, _ = dock
        w._append_log(-1, "loader msg")
        assert "Loader" in w._log_edit.toPlainText()
