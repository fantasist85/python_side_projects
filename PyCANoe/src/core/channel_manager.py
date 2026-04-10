# core/channel_manager.py
from dataclasses import dataclass, field
from PySide6.QtCore import Qt


@dataclass
class ChannelConfig:
    """채널 연결 설정. Main Thread에서 생성·참조."""
    interface:    str
    channel:      int
    bitrate:      int
    bus_type:     str       = "can"     # "can" | "lin"  ← M8 신규
    fd_mode:      bool      = False
    data_bitrate: int       = 2_000_000
    app_name:     str       = "PyCANoe"
    db_path:      str | None = None
    hw_id_filter: int | None = None
    hw_id_mask:   int | None = None

    # ── Vector 전용 ────────────────────────────────────────────────────
    # app_name은 위에서 공용으로 사용 (Vector app_name 동일)

    # ── SocketCAN 전용 ─────────────────────────────────────────────────
    # channel 필드가 인터페이스명으로 사용됨 (예: "vcan0", "can0")
    # → channel은 str이 아니라 int 유지하고 socketcan_ifname 별도 관리
    socketcan_ifname: str   = "vcan0"   # SocketCAN 인터페이스명

    # ── PCAN 전용 ──────────────────────────────────────────────────────
    pcan_channel: str       = "PCAN_USBBUS1"  # PEAK PCAN 채널 ID

    # ── Kvaser 전용 ────────────────────────────────────────────────────
    # Kvaser는 channel(int) 그대로 사용 — 추가 파라미터 없음

    # ── LIN 전용 (M8) ──────────────────────────────────────────────────
    lin_baud:     int       = 19200     # LIN baud rate: 9600 | 19200 | 38400


@dataclass
class ChannelContext:
    """채널 한 개의 런타임 상태 묶음. Main Thread 전용."""
    ch_id:      int
    config:     ChannelConfig
    worker:     "CANWorker"
    db_parser:  "DbParser"
    sim_worker: "SimWorker | None" = None


class ChannelManager:
    """
    THREAD  : Main Thread 전용
    DO NOT  : Worker Thread에서 add_channel / remove_channel 호출
    """
    MAX_CHANNELS = 4

    def __init__(self, dispatcher: "MessageDispatcher") -> None:
        self._channels: dict[int, ChannelContext] = {}
        self._dispatcher = dispatcher

    def add_channel(self, ch_id: int, config: ChannelConfig) -> ChannelContext:
        """
        CANWorker 생성 + QueuedConnection 명시 연결.
        QueuedConnection 명시: 스레드 실행 위치 보장 (auto-detect 전제 붕괴 방어).
        """
        assert len(self._channels) < self.MAX_CHANNELS, "최대 4채널 초과"
        assert ch_id not in self._channels, f"CH{ch_id} 이미 존재"

        # 지연 임포트 — 순환 참조 방지
        from core.db_parser import DbParser
        from core.can_worker import CANWorker

        db     = DbParser(config.db_path)
        worker = CANWorker(ch_id, config, db)

        # QueuedConnection 명시 — 반드시 명시적으로 지정
        worker.parsed_message_received.connect(
            self._dispatcher.on_message,
            Qt.ConnectionType.QueuedConnection,
        )
        worker.error_occurred.connect(
            self._dispatcher.on_error,
            Qt.ConnectionType.QueuedConnection,
        )

        ctx = ChannelContext(
            ch_id=ch_id, config=config, worker=worker, db_parser=db
        )
        self._channels[ch_id] = ctx
        return ctx

    def remove_channel(self, ch_id: int) -> None:
        """채널 제거. Worker stop() 포함. Main Thread 전용."""
        ctx = self._channels.pop(ch_id, None)
        if ctx is None:
            return
        ctx.worker.stop()
        if ctx.sim_worker:
            ctx.sim_worker.stop()

    def get(self, ch_id: int) -> ChannelContext | None:
        return self._channels.get(ch_id)

    def all(self) -> list[ChannelContext]:
        return list(self._channels.values())
