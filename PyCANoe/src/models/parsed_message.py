# models/parsed_message.py
# P0 동결 — 절대 변경 금지. 변경 시 전 계층(CANWorker, DbParser, Dispatcher, UI) 파급.
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ParsedMessage:
    """
    THREAD  : 생성=CANWorker, 읽기=모든 스레드 (immutable이므로 Lock 불필요)
    INPUT   : H/W 원시 필드 + decode 결과
    OUTPUT  : 불변 스냅샷. 읽기 전용.
    DO NOT  : 필드 추가·변경. frozen이므로 생성 후 수정 불가. (P0 동결)
    """
    # H/W 원시 필드
    ch_id:     int    # 0~3
    timestamp: float  # python-can 타임스탬프 (초)
    arb_id:    int    # CAN Arbitration ID | LIN Protected ID (8비트)
    dlc:       int    # 0~15  (CAN FD: 9→12B … 15→64B)
    data:      bytes  # 최대 64바이트

    is_fd:     bool = False
    is_remote: bool = False
    is_error:  bool = False
    is_tx:     bool = False   # SimWorker 송신 에코 (Trace 파랑 컬러링)
    is_brs:    bool = False   # CAN FD BRS 플래그

    # 디코딩 결과 (CANWorker 내부에서 채움)
    signals:  dict | None = None   # {"EngSpeed": 1200.0} | None
    msg_name: str  | None = None   # "EngineData" | None

    def __repr__(self) -> str:
        sig_str = f", signals={self.signals}" if self.signals else ""
        name_str = f", msg_name={self.msg_name!r}" if self.msg_name else ""
        flags = "".join([
            " FD"     if self.is_fd     else "",
            " BRS"    if self.is_brs    else "",
            " REMOTE" if self.is_remote else "",
            " ERROR"  if self.is_error  else "",
            " TX"     if self.is_tx     else "",
        ])
        return (
            f"ParsedMessage(ch={self.ch_id}, ts={self.timestamp:.4f},"
            f" id=0x{self.arb_id:X}, dlc={self.dlc},"
            f" data={self.data.hex(' ').upper()}{flags}{name_str}{sig_str})"
        )


# ---------------------------------------------------------------------------
# CAN FD DLC 매핑: 9→12, 10→16, 11→20, 12→24, 13→32, 14→48, 15→64
# LIN arb_id decode 시: arb_id & 0x3F 로 Frame ID 추출
# is_tx 사용: SimWorker 전송 시 is_tx=True ParsedMessage를 Dispatcher에 emit
# ---------------------------------------------------------------------------
