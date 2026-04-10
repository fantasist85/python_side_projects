# core/can_worker.py
import logging
from enum import Enum, auto
from threading import Lock

import can
from PySide6.QtCore import QThread, Signal

from models.parsed_message import ParsedMessage
from models.channel_stats import ChannelStats

logger = logging.getLogger(__name__)

MAX_RETRY = 5
RETRY_BACKOFF_SEC = [1, 2, 4, 8, 16]

# 인터페이스별 추가 kwargs 생성 함수 — CANWorker 외부에서 단독 테스트 가능
_IFACE_NO_FD = frozenset({"virtual", "socketcan", "pcan"})

# LIN 지원 인터페이스 집합
_LIN_IFACES = frozenset({"vector_lin", "virtual_lin"})


def build_bus_kwargs(config: "ChannelConfig") -> dict:
    """
    인터페이스 종류에 따라 python-can Bus() kwargs 딕셔너리 생성.

    THREAD  : Worker Thread (CANWorker.run() 내부) 또는 테스트 코드
    INPUT   : ChannelConfig
    OUTPUT  : dict — can.Bus(**kwargs) 에 직접 전달 가능
    DO NOT  : UI 위젯 접근, 예외 발생

    M8 추가: bus_type == "lin" 인 경우 _build_lin_bus_kwargs() 분기
    """
    if config.bus_type == "lin":
        return _build_lin_bus_kwargs(config)

    iface = config.interface

    if iface == "virtual":
        return {
            "interface": "virtual",
            "channel":   str(config.channel),
        }

    if iface == "socketcan":
        return {
            "interface": "socketcan",
            "channel":   config.socketcan_ifname,
        }

    if iface == "pcan":
        return {
            "interface": "pcan",
            "channel":   config.pcan_channel,
            "bitrate":   config.bitrate,
        }

    if iface == "kvaser":
        kwargs: dict = {
            "interface": "kvaser",
            "channel":   config.channel,
            "bitrate":   config.bitrate,
        }
        if config.fd_mode:
            kwargs["fd"]           = True
            kwargs["data_bitrate"] = config.data_bitrate
        return kwargs

    if iface == "vector":
        kwargs = {
            "interface": "vector",
            "channel":   config.channel,
            "bitrate":   config.bitrate,
            "app_name":  config.app_name,
        }
        if config.fd_mode:
            kwargs["fd"]           = True
            kwargs["data_bitrate"] = config.data_bitrate
        return kwargs

    # 알 수 없는 인터페이스 — 최소 공통 파라미터로 fallback
    logger.warning("알 수 없는 인터페이스 '%s' — 기본 kwargs 사용", iface)
    return {
        "interface": iface,
        "channel":   config.channel,
        "bitrate":   config.bitrate,
    }


def _build_lin_bus_kwargs(config: "ChannelConfig") -> dict:
    """
    LIN 버스 kwargs 생성 (M8).

    지원 인터페이스:
      vector_lin  — Vector VN16xx 등 LIN 채널. python-can vector 인터페이스 사용.
                    bitrate 자리에 lin_baud 전달.
      virtual_lin — 테스트/CI 용 가상 버스. python-can virtual 인터페이스 내부 활용.

    LIN 공통 특성:
      - FD 미지원 (fd 키 제외)
      - 필터 없음 (set_filters() 호출 안 함 — CANWorker._connect_and_listen() 참조)
    """
    iface = config.interface

    if iface == "virtual_lin":
        return {
            "interface": "virtual",
            "channel":   str(config.channel),
        }

    if iface == "vector_lin":
        return {
            "interface": "vector",
            "channel":   config.channel,
            "bitrate":   config.lin_baud,
            "app_name":  config.app_name,
        }

    # 알 수 없는 LIN 인터페이스 — fallback
    logger.warning("알 수 없는 LIN 인터페이스 '%s' — 기본 kwargs 사용", iface)
    return {
        "interface": iface,
        "channel":   config.channel,
        "bitrate":   config.lin_baud,
    }


class WorkerState(Enum):
    INIT     = auto()
    RUNNING  = auto()
    STOPPING = auto()
    STOPPED  = auto()


class CANWorker(QThread):
    """
    THREAD  : Worker Thread (QThread)
    INPUT   : ChannelConfig, DbParser (주입)
    OUTPUT  : parsed_message_received(ParsedMessage), error_occurred(str),
              connection_state_changed(int, bool)
    DO NOT  : UI 접근, decode 외부 위탁, blocking call in stop(),
              terminate() 사용 (H/W 포트 미해제 → BSoD/Segfault)
    """

    parsed_message_received  = Signal(object)          # ParsedMessage
    error_occurred           = Signal(str)
    connection_state_changed = Signal(int, bool)        # (ch_id, is_connected)

    def __init__(
        self,
        ch_id: int,
        config: "ChannelConfig",
        db: "DbParser",
    ) -> None:
        super().__init__()
        self._ch_id       = ch_id
        self._config      = config
        self._db          = db
        self._state       = WorkerState.INIT
        self._stop        = False
        self._bus: can.BusABC | None = None

        self._stats_lock  = Lock()   # get_stats() 원자성 보장
        self._parser_lock = Lock()   # DB 핫스왑 레이스 컨디션 방어

        self._rx_count = 0
        self._rx_bits  = 0
        self._err_count = 0
        self._tx_count = 0

    # ------------------------------------------------------------------
    # Main Thread에서 호출하는 thread-safe 메서드
    # ------------------------------------------------------------------

    def update_db(self, db: "DbParser") -> None:
        """
        Main Thread에서 호출. _parser_lock 보호.
        clear_cache()는 lock 밖에서 호출 — 의도적.
        (lock 안에서 추가 메서드 호출 시 데드락 위험)
        """
        with self._parser_lock:
            self._db = db
        db.clear_cache()

    def send(self, msg: can.Message) -> None:
        """SimWorker에서 호출. bus 참조는 _connect_and_listen 범위 내에서만 유효."""
        if self._bus is not None:
            try:
                self._bus.send(msg)
            except can.CanError as exc:
                logger.warning("CH%d send() failed: %s", self._ch_id, exc)

    def increment_tx(self) -> None:
        """SimWorker가 전송 시 호출. _stats_lock 보호."""
        with self._stats_lock:
            self._tx_count += 1

    def get_stats(self) -> ChannelStats:
        """QTimer(1s) 슬롯에서 호출. read + clear 원자적 수행."""
        with self._stats_lock:
            s = ChannelStats(
                rx_count    = self._rx_count,
                tx_count    = self._tx_count,
                error_count = self._err_count,
                rx_bits     = self._rx_bits,
                bitrate     = self._config.bitrate,
            )
            self._rx_count = self._tx_count = self._err_count = self._rx_bits = 0
        return s

    # ------------------------------------------------------------------
    # QThread 실행 루프
    # ------------------------------------------------------------------

    def run(self) -> None:
        self._state = WorkerState.RUNNING
        self._bus   = None
        retry_count = 0

        while not self._stop:
            try:
                self._connect_and_listen()
                break   # 정상 종료 (stop() 호출)
            except can.CanError as exc:
                retry_count += 1
                self.connection_state_changed.emit(self._ch_id, False)

                if retry_count > MAX_RETRY:
                    self.error_occurred.emit(
                        f"CH{self._ch_id}: 재연결 한계 초과. 수동 재연결 필요."
                    )
                    break

                wait = RETRY_BACKOFF_SEC[
                    min(retry_count - 1, len(RETRY_BACKOFF_SEC) - 1)
                ]
                self.error_occurred.emit(
                    f"CH{self._ch_id}: 연결 오류 — {wait}초 후 재시도 "
                    f"({retry_count}/{MAX_RETRY}): {exc}"
                )
                # 0.1초 폴링으로 _stop 플래그 확인 (최대 16초 블로킹 방지)
                for _ in range(int(wait * 10)):
                    if self._stop:
                        self._state = WorkerState.STOPPED
                        return
                    self.msleep(100)

        self._state = WorkerState.STOPPED

    def _connect_and_listen(self) -> None:
        """Bus 연결 + 수신 루프. stop() 호출 시 정상 탈출."""
        kwargs = build_bus_kwargs(self._config)
        logger.debug("CH%d Bus() kwargs: %s", self._ch_id, kwargs)

        with can.Bus(**kwargs) as bus:
            self._bus = bus

            # HW 필터: CAN 전용. LIN은 set_filters() 미지원 → 건너뜀
            if (
                self._config.bus_type == "can"
                and self._config.hw_id_filter is not None
            ):
                bus.set_filters([{
                    "can_id":   self._config.hw_id_filter,
                    "can_mask": self._config.hw_id_mask or 0x7FF,
                    "extended": False,
                }])

            self.connection_state_changed.emit(self._ch_id, True)

            while not self._stop:
                raw = bus.recv(timeout=0.1)
                if raw is None:
                    continue
                self._process_message(raw)

            self._bus = None

    def _process_message(self, raw: can.Message) -> None:
        """수신 메시지 decode + ParsedMessage emit."""
        with self._parser_lock:
            signals, msg_name = self._db.decode_with_name(
                raw.arbitration_id, raw.data
            )

        msg = ParsedMessage(
            ch_id     = self._ch_id,
            timestamp = raw.timestamp,
            arb_id    = raw.arbitration_id,
            dlc       = raw.dlc,
            data      = bytes(raw.data),
            is_fd     = raw.is_fd,
            is_remote = raw.is_remote_frame,
            is_error  = raw.is_error_frame,
            is_brs    = getattr(raw, "bitrate_switch", False),
            signals   = signals,
            msg_name  = msg_name,
        )

        frame_bits = ChannelStats.calc_frame_bits(len(raw.data), raw.is_fd)
        with self._stats_lock:
            self._rx_count += 1
            self._rx_bits  += frame_bits
            if raw.is_error_frame:
                self._err_count += 1

        self.parsed_message_received.emit(msg)

    # ------------------------------------------------------------------
    # 종료
    # ------------------------------------------------------------------

    def stop(self) -> None:
        """
        SHUTDOWN SEQUENCE 일부.
        terminate() 사용 절대 금지 — H/W 포트 미해제 → BSoD/Segfault.
        """
        self._state = WorkerState.STOPPING
        self._stop  = True
        self.wait()
        self._state = WorkerState.STOPPED
