# core/virtual_node_engine.py
"""
M7 Virtual Node Engine — CAPL 대체 Python 스크립트 실행 엔진.

[아키텍처 위치]
  Service Layer — Main Thread가 로드/언로드 제어,
  스크립트 콜백(on_message, on_timer)은 VirtualNodeWorker(QThread)에서 실행.

[스크립트 API — 사용자 작성 .py]
  def on_start(bus):          # 선택. 노드 시작 시 1회 호출.
      ...

  def on_message(bus, msg):   # 선택. ParsedMessage 수신 시마다 호출.
      ...

  def on_timer(bus):          # 선택. interval_ms 주기로 반복 호출.
      ...

[bus API — 스크립트에서 사용 가능]
  bus.send(arb_id, data)              → CAN 메시지 전송
  bus.send_fd(arb_id, data)           → CAN FD 메시지 전송 (is_fd=True)
  bus.log(text)                       → VirtualNodeEngine.log_emitted Signal
  bus.get_signal(ch_id, sig_name)     → float | None (SimStateStore 조회)
  bus.set_interval(interval_ms)       → on_timer 주기 변경 (런타임 가능)

[스레드 안전 규칙]
  STRICT RULES:
  - on_message / on_timer 는 VirtualNodeWorker 스레드에서 실행됨.
  - bus.send()는 내부에서 Qt Signal(QueuedConnection)을 emit → Main Thread에서 CANWorker.send() 호출.
  - UI 위젯 직접 접근 절대 금지 (bus.log()도 Signal emit).
  - 스크립트 예외는 catch → log_emitted Signal로 보고, 노드 중단하지 않음.
"""
from __future__ import annotations

import importlib.util
import logging
import time
import types
from threading import Lock
from typing import TYPE_CHECKING

import can
from PySide6.QtCore import QObject, QThread, Signal, Slot

from models.parsed_message import ParsedMessage

if TYPE_CHECKING:
    from core.can_worker import CANWorker
    from models.sim_state_store import SimStateStore

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# BusProxy — 스크립트에 노출되는 bus 객체
# ---------------------------------------------------------------------------

class BusProxy(QObject):
    """
    THREAD  : VirtualNodeWorker 스레드에서 스크립트가 호출.
              send_requested / log_emitted Signal → QueuedConnection으로
              Main Thread에서 처리됨.
    DO NOT  : 이 객체에서 직접 CANWorker.send() 호출 금지.
    """

    # Signal: (ch_id, arb_id, data_bytes, is_fd)
    send_requested = Signal(int, int, bytes, bool)
    log_emitted    = Signal(str)   # 스크립트 log() → VirtualNodeDock / StatusBar

    def __init__(
        self,
        ch_id: int,
        sim_state: "SimStateStore",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._ch_id     = ch_id
        self._sim_state = sim_state
        self._interval_ms: float = 100.0
        self._interval_lock = Lock()

    # ------------------------------------------------------------------
    # 스크립트 공개 API
    # ------------------------------------------------------------------

    def send(self, arb_id: int, data: bytes | list | bytearray) -> None:
        """CAN 2.0 메시지 전송 요청. Signal emit → Main Thread."""
        self.send_requested.emit(self._ch_id, int(arb_id), bytes(data), False)

    def send_fd(self, arb_id: int, data: bytes | list | bytearray) -> None:
        """CAN FD 메시지 전송 요청. Signal emit → Main Thread."""
        self.send_requested.emit(self._ch_id, int(arb_id), bytes(data), True)

    def log(self, text: str) -> None:
        """스크립트 로그 출력. Signal emit → Main Thread → VirtualNodeDock."""
        self.log_emitted.emit(str(text))

    def get_signal(self, ch_id: int, sig_name: str) -> float | None:
        """SimStateStore에서 최신 신호 값 조회. Thread-safe (SimStateStore.get)."""
        return self._sim_state.get(ch_id, sig_name)

    def set_interval(self, interval_ms: float) -> None:
        """on_timer 호출 주기 변경 (런타임 가능). Thread-safe."""
        with self._interval_lock:
            self._interval_ms = max(1.0, float(interval_ms))

    # ------------------------------------------------------------------
    # 내부 접근자 (VirtualNodeWorker에서 사용)
    # ------------------------------------------------------------------

    @property
    def interval_ms(self) -> float:
        with self._interval_lock:
            return self._interval_ms

    @property
    def ch_id(self) -> int:
        return self._ch_id


# ---------------------------------------------------------------------------
# VirtualNodeWorker — on_message / on_timer 콜백 실행 스레드
# ---------------------------------------------------------------------------

class VirtualNodeWorker(QThread):
    """
    THREAD  : Worker Thread.
    INPUT   : ParsedMessage (queue), 스크립트 모듈
    OUTPUT  : BusProxy Signal (send_requested, log_emitted)
    DO NOT  : UI 접근, bus.send() 직접 CANWorker 호출.
    """

    node_error = Signal(str)   # 스크립트 예외 보고 → StatusBar

    def __init__(
        self,
        script_module: types.ModuleType,
        bus: BusProxy,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._module     = script_module
        self._bus        = bus
        self._stop       = False
        self._msg_queue: list[ParsedMessage] = []
        self._msg_lock   = Lock()

    # ------------------------------------------------------------------
    # 외부 인터페이스 (Main Thread에서 호출)
    # ------------------------------------------------------------------

    def enqueue_message(self, msg: ParsedMessage) -> None:
        """
        Dispatcher → VirtualNodeEngine.on_all_messages() → 여기.
        Main Thread에서 호출. _msg_lock 보호.
        """
        with self._msg_lock:
            self._msg_queue.append(msg)

    def stop(self) -> None:
        self._stop = True
        self.wait()

    # ------------------------------------------------------------------
    # 실행 루프
    # ------------------------------------------------------------------

    def run(self) -> None:
        # on_start 콜백
        self._call("on_start", self._bus)

        last_timer = time.perf_counter()

        while not self._stop:
            # ── on_message 처리 ──────────────────────────────────────
            with self._msg_lock:
                pending = self._msg_queue
                self._msg_queue = []

            for msg in pending:
                self._call("on_message", self._bus, msg)

            # ── on_timer 처리 ────────────────────────────────────────
            now = time.perf_counter()
            interval_sec = self._bus.interval_ms / 1000.0
            if now - last_timer >= interval_sec:
                self._call("on_timer", self._bus)
                last_timer = now

            # ── 유휴 대기 ────────────────────────────────────────────
            time.sleep(0.001)   # 1ms busy 방지

    # ------------------------------------------------------------------
    # 콜백 호출 헬퍼
    # ------------------------------------------------------------------

    def _call(self, fn_name: str, *args) -> None:
        """스크립트 함수 호출. 존재하지 않으면 무시. 예외는 Signal 보고."""
        fn = getattr(self._module, fn_name, None)
        if fn is None:
            return
        try:
            fn(*args)
        except Exception as exc:
            msg = f"[VirtualNode] {fn_name}() 예외: {exc}"
            logger.exception(msg)
            self.node_error.emit(msg)


# ---------------------------------------------------------------------------
# VirtualNodeEngine — 노드 생명주기 관리 (Main Thread 전용)
# ---------------------------------------------------------------------------

class VirtualNodeEngine(QObject):
    """
    THREAD  : Main Thread 전용. 로드/언로드/라우팅.
    INPUT   : ParsedMessage (Dispatcher → on_all_messages Slot)
    OUTPUT  : BusProxy.send_requested → CANWorker.send()
              BusProxy.log_emitted    → log_emitted Signal
              worker.node_error       → node_error Signal

    사용 예 (MainWindow):
        self._vne = VirtualNodeEngine(channel_manager, sim_state, self)
        self._vne.log_emitted.connect(self._vn_dock.append_log)
        self._vne.node_error.connect(self._on_vn_error)
        # Dispatcher가 모든 메시지를 VNE에도 전달
        dispatcher.message_routed.connect(self._vne.on_all_messages)
    """

    log_emitted  = Signal(int, str)    # (node_id, text) → VirtualNodeDock
    node_error   = Signal(int, str)    # (node_id, error_msg)
    node_started = Signal(int, str)    # (node_id, script_path)
    node_stopped = Signal(int)         # node_id

    def __init__(
        self,
        channel_manager: "ChannelManager",
        sim_state: "SimStateStore",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._channel_manager = channel_manager
        self._sim_state       = sim_state
        # node_id → (VirtualNodeWorker, BusProxy)
        self._nodes: dict[int, tuple[VirtualNodeWorker, BusProxy]] = {}
        self._next_id = 0

    # ------------------------------------------------------------------
    # 노드 로드 / 언로드
    # ------------------------------------------------------------------

    def load_script(self, ch_id: int, script_path: str) -> int:
        """
        스크립트 파일을 로드하여 새 Virtual Node를 시작한다.
        반환값: node_id (언로드 시 사용)
        Main Thread 전용.
        """
        module = self._load_module(script_path)
        if module is None:
            raise ValueError(f"스크립트 로드 실패: {script_path}")

        node_id = self._next_id
        self._next_id += 1

        bus = BusProxy(ch_id, self._sim_state)
        bus.send_requested.connect(self._on_send_requested)
        bus.log_emitted.connect(
            lambda text, nid=node_id: self.log_emitted.emit(nid, text)
        )

        worker = VirtualNodeWorker(module, bus)
        worker.node_error.connect(
            lambda msg, nid=node_id: self.node_error.emit(nid, msg)
        )
        worker.start()

        self._nodes[node_id] = (worker, bus)
        self.node_started.emit(node_id, script_path)
        logger.info("VirtualNode %d 시작: CH%d — %s", node_id, ch_id, script_path)
        return node_id

    def unload_node(self, node_id: int) -> None:
        """
        실행 중인 Virtual Node를 정지하고 제거한다.
        Main Thread 전용.
        """
        pair = self._nodes.pop(node_id, None)
        if pair is None:
            return
        worker, _ = pair
        worker.stop()
        self.node_stopped.emit(node_id)
        logger.info("VirtualNode %d 정지", node_id)

    def unload_all(self) -> None:
        """모든 노드 정지. closeEvent에서 호출."""
        for node_id in list(self._nodes.keys()):
            self.unload_node(node_id)

    def active_nodes(self) -> list[tuple[int, int]]:
        """[(node_id, ch_id), ...] 목록 반환."""
        return [
            (nid, bus.ch_id)
            for nid, (_, bus) in self._nodes.items()
        ]

    # ------------------------------------------------------------------
    # 메시지 라우팅 슬롯 (Dispatcher에서 연결)
    # ------------------------------------------------------------------

    @Slot(object)
    def on_all_messages(self, msg: ParsedMessage) -> None:
        """
        Main Thread에서 실행 (QueuedConnection).
        수신된 ParsedMessage를 모든 활성 노드 Worker 큐에 전달.
        Tx 에코(is_tx=True)는 전달하지 않음 (무한 루프 방지).
        """
        if msg.is_tx:
            return
        for worker, _ in self._nodes.values():
            worker.enqueue_message(msg)

    # ------------------------------------------------------------------
    # 전송 요청 슬롯 (BusProxy.send_requested → Main Thread)
    # ------------------------------------------------------------------

    @Slot(int, int, bytes, bool)
    def _on_send_requested(self, ch_id: int, arb_id: int, data: bytes, is_fd: bool) -> None:
        """
        Main Thread에서 실행 (QueuedConnection).
        ChannelManager → CANWorker.send() 호출.
        """
        ctx = self._channel_manager.get(ch_id)
        if ctx is None:
            logger.warning("VirtualNode send: CH%d 없음 (arb_id=0x%X)", ch_id, arb_id)
            return
        try:
            raw_msg = can.Message(
                arbitration_id=arb_id,
                data=data,
                is_extended_id=False,
                is_fd=is_fd,
            )
            ctx.worker.send(raw_msg)
            ctx.worker.increment_tx()
        except Exception as exc:
            logger.warning("VirtualNode CH%d send 실패: %s", ch_id, exc)

    # ------------------------------------------------------------------
    # 내부 유틸
    # ------------------------------------------------------------------

    @staticmethod
    def _load_module(script_path: str) -> types.ModuleType | None:
        """
        importlib으로 사용자 스크립트를 동적 로드한다.
        SyntaxError 등 예외 시 None 반환.
        """
        try:
            spec = importlib.util.spec_from_file_location(
                f"virtual_node_{id(script_path)}", script_path
            )
            if spec is None or spec.loader is None:
                return None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)   # type: ignore[union-attr]
            return module
        except Exception as exc:
            logger.error("스크립트 로드 오류: %s — %s", script_path, exc)
            return None
