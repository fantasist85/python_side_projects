# core/virtual_node_engine.py
"""
M7 Virtual Node Engine — CAPL 대체 Python 스크립트 실행 엔진.
M9 업데이트: arb_id 필터링 + 스크립트 핫리로드 지원.

[아키텍처 위치]
  Service Layer — Main Thread가 로드/언로드 제어,
  스크립트 콜백(on_message, on_timer)은 VirtualNodeWorker(QThread)에서 실행.

[스크립트 API — 사용자 작성 .py]
  def on_start(bus):          # 선택. 노드 시작 시 1회 호출.
      ...

  def on_message(bus, msg):   # 선택. ParsedMessage 수신 시마다 호출.
      ...                     # 필터 설정 시 해당 arb_id 메시지만 전달됨.

  def on_timer(bus):          # 선택. interval_ms 주기로 반복 호출.
      ...

[bus API — 스크립트에서 사용 가능]
  bus.send(arb_id, data)              → CAN 메시지 전송
  bus.send_fd(arb_id, data)           → CAN FD 메시지 전송 (is_fd=True)
  bus.log(text)                       → VirtualNodeEngine.log_emitted Signal
  bus.get_signal(ch_id, sig_name)     → float | None (SimStateStore 조회)
  bus.set_interval(interval_ms)       → on_timer 주기 변경 (런타임 가능)

  [M9 신규 — arb_id 필터]
  bus.add_filter(arb_id)              → 특정 arb_id만 on_message()에 전달
  bus.remove_filter(arb_id)           → 필터 제거
  bus.clear_filters()                 → 전체 필터 제거 (모든 메시지 수신)

[핫리로드 — M9 신규]
  VirtualNodeEngine.set_hot_reload(node_id, True) 호출 시
  500ms 폴링으로 스크립트 파일 수정 시간 감지 → 변경 시 자동 재로드.
  재로드 시 node_id 유지, on_start()부터 재실행.

[스레드 안전 규칙]
  STRICT RULES:
  - on_message / on_timer 는 VirtualNodeWorker 스레드에서 실행됨.
  - bus.send()는 내부에서 Qt Signal(QueuedConnection)을 emit → Main Thread에서 CANWorker.send() 호출.
  - UI 위젯 직접 접근 절대 금지 (bus.log()도 Signal emit).
  - 스크립트 예외는 catch → log_emitted Signal로 보고, 노드 중단하지 않음.
  - 핫리로드 타이머: QTimer(Main Thread), 500ms 폴링.
"""
from __future__ import annotations

import importlib.util
import logging
import os
import time
import types
from dataclasses import dataclass, field
from threading import Lock
from typing import TYPE_CHECKING

import can
from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

from models.parsed_message import ParsedMessage

if TYPE_CHECKING:
    from core.can_worker import CANWorker
    from models.sim_state_store import SimStateStore

logger = logging.getLogger(__name__)

_HOT_RELOAD_INTERVAL_MS = 500   # 핫리로드 폴링 주기 (ms)


def _calc_lin_pid(frame_id: int) -> int:
    """
    B-3: LIN Spec §2.3.1 Protected ID 계산.
    P0 = ID0 ^ ID1 ^ ID2 ^ ID4
    P1 = ~(ID1 ^ ID3 ^ ID4 ^ ID5) & 1
    PID = frame_id | (P0 << 6) | (P1 << 7)
    """
    fid = frame_id & 0x3F
    p0  = (fid ^ (fid >> 1) ^ (fid >> 2) ^ (fid >> 4)) & 1
    p1  = (~((fid >> 1) ^ (fid >> 3) ^ (fid >> 4) ^ (fid >> 5))) & 1
    return fid | (p0 << 6) | (p1 << 7)


# ---------------------------------------------------------------------------
# _NodeInfo — 노드별 메타데이터
# ---------------------------------------------------------------------------

@dataclass
class _NodeInfo:
    """노드 한 개의 런타임 상태. Main Thread 전용."""
    worker:      "VirtualNodeWorker"
    bus:         "BusProxy"
    ch_id:       int
    script_path: str
    last_mtime:  float = 0.0        # 핫리로드용 파일 수정 시간 캐시
    hot_reload:  bool  = False      # 핫리로드 활성 여부


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
        bus_type: str = "can",   # B-3: LIN 채널 PID 자동 계산
    ) -> None:
        super().__init__(parent)
        self._ch_id     = ch_id
        self._sim_state = sim_state
        self._bus_type  = bus_type   # B-3: "can" | "lin"
        self._interval_ms: float = 100.0
        self._interval_lock = Lock()

        # M9: arb_id 필터. 빈 set = 필터 없음 (전체 전달)
        self._arb_id_filters: set[int] = set()
        self._filter_lock = Lock()

    # ------------------------------------------------------------------
    # 스크립트 공개 API
    # ------------------------------------------------------------------

    def send(self, arb_id: int, data: bytes | list | bytearray) -> None:
        """CAN/LIN 메시지 전송 요청. B-3: LIN이면 PID 자동 계산. Signal emit → Main Thread."""
        if self._bus_type == "lin":
            arb_id = _calc_lin_pid(arb_id & 0x3F)
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

    # ── M9: arb_id 필터 API ───────────────────────────────────────────

    def add_filter(self, arb_id: int) -> None:
        """
        특정 arb_id만 on_message()에 전달받도록 필터 추가.
        필터가 1개라도 있으면 등록된 arb_id 메시지만 전달됨.
        Thread-safe.
        """
        with self._filter_lock:
            self._arb_id_filters.add(int(arb_id))

    def remove_filter(self, arb_id: int) -> None:
        """arb_id 필터 제거. Thread-safe."""
        with self._filter_lock:
            self._arb_id_filters.discard(int(arb_id))

    def clear_filters(self) -> None:
        """모든 필터 제거 → 이후 전체 메시지 수신. Thread-safe."""
        with self._filter_lock:
            self._arb_id_filters.clear()

    # ------------------------------------------------------------------
    # 내부 접근자 (VirtualNodeWorker에서 사용)
    # ------------------------------------------------------------------

    def should_deliver(self, arb_id: int) -> bool:
        """
        필터 체크. 필터 없으면 True(전체 전달).
        필터 있으면 arb_id가 등록된 경우만 True.
        Thread-safe.
        """
        with self._filter_lock:
            if not self._arb_id_filters:
                return True
            return arb_id in self._arb_id_filters

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
                # M9: arb_id 필터 적용
                if self._bus.should_deliver(msg.arb_id):
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
    THREAD  : Main Thread 전용. 로드/언로드/라우팅/핫리로드.
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

    log_emitted    = Signal(int, str)    # (node_id, text) → VirtualNodeDock
    node_error     = Signal(int, str)    # (node_id, error_msg)
    node_started   = Signal(int, str)    # (node_id, script_path)
    node_stopped   = Signal(int)         # node_id
    node_reloaded  = Signal(int, str)    # (node_id, script_path) ← M9 신규

    def __init__(
        self,
        channel_manager: "ChannelManager",
        sim_state: "SimStateStore",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._channel_manager = channel_manager
        self._sim_state       = sim_state
        self._nodes: dict[int, _NodeInfo] = {}
        self._next_id = 0

        # M9: 핫리로드 폴링 타이머
        self._hot_reload_timer = QTimer(self)
        self._hot_reload_timer.setInterval(_HOT_RELOAD_INTERVAL_MS)
        self._hot_reload_timer.timeout.connect(self._check_hot_reload)
        self._hot_reload_timer.start()

    # ------------------------------------------------------------------
    # 노드 로드 / 언로드
    # ------------------------------------------------------------------

    def load_script(self, ch_id: int, script_path: str) -> int:
        """
        스크립트 파일을 로드하여 새 Virtual Node를 시작한다.
        반환값: node_id (언로드/핫리로드 시 사용)
        Main Thread 전용.
        """
        module = self._load_module(script_path)
        if module is None:
            raise ValueError(f"스크립트 로드 실패: {script_path}")

        node_id = self._next_id
        self._next_id += 1

        # B-3: 채널 버스 타입 확인 → BusProxy에 전달
        ctx      = self._channel_manager.get(ch_id)
        bus_type = getattr(ctx.config, "bus_type", "can") if ctx else "can"
        bus = BusProxy(ch_id, self._sim_state, bus_type=bus_type)
        bus.send_requested.connect(self._on_send_requested)
        bus.log_emitted.connect(
            lambda text, nid=node_id: self.log_emitted.emit(nid, text)
        )

        worker = VirtualNodeWorker(module, bus)
        worker.node_error.connect(
            lambda msg, nid=node_id: self.node_error.emit(nid, msg)
        )
        worker.start()

        try:
            mtime = os.path.getmtime(script_path)
        except OSError:
            mtime = 0.0

        self._nodes[node_id] = _NodeInfo(
            worker=worker,
            bus=bus,
            ch_id=ch_id,
            script_path=script_path,
            last_mtime=mtime,
        )
        self.node_started.emit(node_id, script_path)
        logger.info("VirtualNode %d 시작: CH%d — %s", node_id, ch_id, script_path)
        return node_id

    def unload_node(self, node_id: int) -> None:
        """
        실행 중인 Virtual Node를 정지하고 제거한다.
        Main Thread 전용.
        """
        info = self._nodes.pop(node_id, None)
        if info is None:
            return
        info.worker.stop()
        self.node_stopped.emit(node_id)
        logger.info("VirtualNode %d 정지", node_id)

    def unload_all(self) -> None:
        """모든 노드 정지. closeEvent에서 호출."""
        for node_id in list(self._nodes.keys()):
            self.unload_node(node_id)

    def active_nodes(self) -> list[tuple[int, int]]:
        """[(node_id, ch_id), ...] 목록 반환."""
        return [
            (nid, info.ch_id)
            for nid, info in self._nodes.items()
        ]

    # ------------------------------------------------------------------
    # M9: 핫리로드 제어
    # ------------------------------------------------------------------

    def set_hot_reload(self, node_id: int, enabled: bool) -> None:
        """
        특정 노드의 핫리로드 활성화/비활성화.
        활성화 시 500ms 폴링으로 파일 수정 시간 감지 → 자동 재로드.
        Main Thread 전용.
        """
        info = self._nodes.get(node_id)
        if info is None:
            return
        info.hot_reload = enabled
        if enabled:
            # 기준 mtime 갱신 (즉각 reload 방지)
            try:
                info.last_mtime = os.path.getmtime(info.script_path)
            except OSError:
                pass
        logger.info("VirtualNode %d 핫리로드: %s", node_id, "ON" if enabled else "OFF")

    @Slot()
    def _check_hot_reload(self) -> None:
        """
        QTimer(500ms) 슬롯 — Main Thread에서 실행.
        핫리로드 활성 노드의 파일 수정 시간을 확인하여 변경 시 재로드.
        """
        for node_id, info in list(self._nodes.items()):
            if not info.hot_reload:
                continue
            try:
                mtime = os.path.getmtime(info.script_path)
            except OSError:
                continue
            if mtime > info.last_mtime:
                info.last_mtime = mtime
                self._reload_node(node_id)

    def _reload_node(self, node_id: int) -> None:
        """
        노드를 재로드한다 (node_id 유지).
        기존 Worker stop → 새 모듈 로드 → 새 Worker start.
        Main Thread 전용.
        """
        info = self._nodes.get(node_id)
        if info is None:
            return

        logger.info("VirtualNode %d 핫리로드: %s", node_id, info.script_path)

        # 기존 Worker 정지
        info.worker.stop()

        # 새 모듈 로드
        module = self._load_module(info.script_path)
        if module is None:
            self.node_error.emit(node_id, f"[핫리로드 실패] {info.script_path}")
            return

        # BusProxy 재사용 (ch_id, sim_state, filters 유지)
        new_worker = VirtualNodeWorker(module, info.bus)
        new_worker.node_error.connect(
            lambda msg, nid=node_id: self.node_error.emit(nid, msg)
        )
        new_worker.start()

        info.worker = new_worker
        self.node_reloaded.emit(node_id, info.script_path)
        logger.info("VirtualNode %d 재로드 완료", node_id)

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
        for info in self._nodes.values():
            info.worker.enqueue_message(msg)

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
