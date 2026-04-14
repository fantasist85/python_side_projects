# core/sim_worker.py
import time
import logging
from dataclasses import dataclass, field
from threading import Lock

import can
from PySide6.QtCore import QThread, Signal

from models.parsed_message import ParsedMessage

logger = logging.getLogger(__name__)


def _calc_lin_pid(frame_id: int) -> int:
    """
    LIN Protected ID (PID) 계산. (LIN 2.x spec §2.3.1)

    frame_id : 0~63 (6-bit). 상위 비트는 무시.
    반환값   : 8-bit PID = frame_id | (P0 << 6) | (P1 << 7)

    패리티 비트:
      P0 = ID0 ^ ID1 ^ ID2 ^ ID4
      P1 = ~(ID1 ^ ID3 ^ ID4 ^ ID5)
    """
    fid = frame_id & 0x3F
    p0 = ((fid >> 0) ^ (fid >> 1) ^ (fid >> 2) ^ (fid >> 4)) & 1
    p1 = (~((fid >> 1) ^ (fid >> 3) ^ (fid >> 4) ^ (fid >> 5))) & 1
    return fid | (p0 << 6) | (p1 << 7)


@dataclass
class SimMessage:
    """
    THREAD  : 생성/수정=Main Thread, next_send_at 갱신=SimWorker Thread
    NOTE    : next_send_at 갱신이 원본 객체에 반영되어야 drift 보정이 동작한다.
              SimWorker.run()에서 list() 얕은 복사를 사용하는 이유.
    """
    arb_id:       int
    data:         bytes
    interval_ms:  float
    bus_type:     str   = "can"   # "can" | "lin"  ← M10 신규
    next_send_at: float = field(default_factory=time.perf_counter)

    def is_due(self, now: float) -> bool:
        return now >= self.next_send_at

    def update_next(self, now: float) -> None:
        """drift 보정: 누적 오차 없이 다음 전송 시각 갱신."""
        self.next_send_at += self.interval_ms / 1000.0
        # 크게 밀렸으면 리셋 (폭주 방지)
        if now - self.next_send_at > self.interval_ms / 1000.0:
            self.next_send_at = now + self.interval_ms / 1000.0

    def to_can_message(self) -> can.Message:
        return can.Message(
            arbitration_id=self.arb_id,
            data=self.data,
            is_extended_id=False,
        )

    def to_lin_message(self) -> can.Message:
        """
        LIN 프레임 메시지 생성.
        arb_id(6-bit frame_id) → PID(8-bit) 계산 후 arbitration_id로 전달.
        virtual_lin / vector_lin 모두 동일 API 사용.
        """
        pid = _calc_lin_pid(self.arb_id & 0x3F)
        return can.Message(
            arbitration_id=pid,
            data=self.data,
            is_extended_id=False,
        )

    def to_bus_message(self) -> can.Message:
        """bus_type에 따라 적합한 can.Message 반환."""
        if self.bus_type == "lin":
            return self.to_lin_message()
        return self.to_can_message()


class SimWorker(QThread):
    """
    THREAD  : Worker Thread
    INPUT   : SimMessage (add_message/remove_message — Main Thread에서 호출)
    OUTPUT  : tx_echo Signal(ParsedMessage) → Dispatcher 에코
    DO NOT  : UI 접근, _messages 무Lock 접근.
              deepcopy 사용 금지 (타이밍 드리프트 보정 무력화).
              = 단순 할당 금지 (순회 중 RuntimeError 유발).
              .copy() 메서드 금지 (list() 통일).

    [SimWorker 복사 규칙 — AI STRICT]
    - list(self._messages) : 반드시 list() 생성자 사용. 얕은 복사 의도적.
    - SimMessage 객체는 원본 공유 — next_send_at 갱신이 원본에 반영되는 것이 의도.
    - deepcopy 교체 금지 : 타이밍 드리프트 보정 무력화됨.
    - = 단순 할당 금지 : 순회 중 RuntimeError 유발.
    - .copy() 메서드 금지 : list()와 동일하나 의도 불명확 — list() 통일.
    """

    tx_echo = Signal(object)   # is_tx=True ParsedMessage → Dispatcher

    def __init__(self, ch_id: int, bus_sender: "CANWorker") -> None:
        super().__init__()
        self._ch_id         = ch_id
        self._bus_sender    = bus_sender
        self._stop          = False
        self._messages:     list[SimMessage] = []
        self._messages_lock = Lock()   # add/remove(Main) + _send(Worker) 보호

    # ------------------------------------------------------------------
    # QThread 실행 루프
    # ------------------------------------------------------------------

    def run(self) -> None:
        while not self._stop:
            with self._messages_lock:
                # [AI STRICT — SimWorker 복사 규칙]
                # 반드시 list() 생성자 사용. 얕은 복사 의도적.
                # SimMessage 객체는 원본 공유 — next_send_at 갱신이 원본에 반영.
                msgs_snapshot = list(self._messages)

            if not msgs_snapshot:
                time.sleep(0.1)   # 유휴 시 CPU 100% 방지
                continue

            now = time.perf_counter()
            self._send_due_messages(now, msgs_snapshot)

            # 다음 전송까지 대기
            next_wakeup = min(m.next_send_at for m in msgs_snapshot)
            sleep_sec   = next_wakeup - time.perf_counter()
            if sleep_sec > 0.002:
                time.sleep(sleep_sec - 0.001)
            # busy-wait 마지막 1ms (CANoe 동일 방식, Windows sleep 해상도 한계 대응)
            while time.perf_counter() < next_wakeup:
                pass

    def _send_due_messages(self, now: float, msgs: list[SimMessage]) -> None:
        for sm in msgs:
            if sm.is_due(now):
                try:
                    self._bus_sender.send(sm.to_bus_message())   # M10: bus_type 분기
                    self._bus_sender.increment_tx()
                except Exception as exc:
                    logger.warning(
                        "SimWorker CH%d send failed: arb_id=0x%X — %s",
                        self._ch_id, sm.arb_id, exc,
                    )
                sm.update_next(now)

                # Trace 컬러링용 Tx 에코 (is_tx=True)
                echo = ParsedMessage(
                    ch_id     = self._ch_id,
                    timestamp = time.time(),
                    arb_id    = sm.arb_id,
                    dlc       = len(sm.data),
                    data      = sm.data,
                    is_tx     = True,
                )
                self.tx_echo.emit(echo)

    # ------------------------------------------------------------------
    # Main Thread에서 호출하는 thread-safe 메서드
    # ------------------------------------------------------------------

    def add_message(self, msg: SimMessage) -> None:
        """Main Thread에서 호출. _messages_lock 보호."""
        with self._messages_lock:
            self._messages.append(msg)

    def remove_message(self, arb_id: int) -> None:
        """Main Thread에서 호출. _messages_lock 보호."""
        with self._messages_lock:
            self._messages = [m for m in self._messages if m.arb_id != arb_id]

    # ------------------------------------------------------------------
    # 종료
    # ------------------------------------------------------------------

    def stop(self) -> None:
        self._stop = True
        self.wait()
