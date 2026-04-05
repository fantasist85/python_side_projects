# core/log_worker.py
import os
import queue
from datetime import datetime

from PySide6.QtCore import QThread, Signal

from models.log_queue import LogQueue

MAX_FILE_BYTES = 100 * 1024 * 1024   # 100 MB — Log Rotation 상한
CHUNK_SIZE     = 5_000               # 청크 단위 (100건→SSD I/O 50배 과다)


class LogWorker(QThread):
    """
    THREAD  : Worker Thread
    INPUT   : LogQueue
    OUTPUT  : log_dropped(int), log_rotated(str) Signal
    DO NOT  : UI 접근.
              stop() 시 잔여 배치 손실 — else 블록에서 반드시 flush.
              else 블록을 루프 밖으로 이동 금지 (정상/Rotation 경로 구분 무력화).

    [LogWorker 종료 시퀀스]
    1. stop() → self._running = False
    2. 내부 while self._running 루프 탈출 (정상 종료 경로)
    3. while-else의 else 블록 실행 → 잔여 배치 flush → End TriggerBlock 기록
    ★ break로 탈출(Log Rotation)하면 else 블록 미실행 — 의도적
    ★ else 블록을 루프 밖으로 이동 금지 — 정상/Rotation 경로 구분 무력화
    """

    log_dropped = Signal(int)   # 누적 drop_count
    log_rotated = Signal(str)   # 새 파일 경로

    def __init__(
        self, log_queue: LogQueue, path: str, fmt: str = "asc"
    ) -> None:
        super().__init__()
        self._q         = log_queue.get_queue()
        self._lq        = log_queue
        self._base_path = path
        self._fmt       = fmt
        self._running   = False

    # ------------------------------------------------------------------
    # 내부 유틸
    # ------------------------------------------------------------------

    def _make_path(self, index: int) -> str:
        base, ext = os.path.splitext(self._base_path)
        return f"{base}_{index:03d}{ext}"

    def _write_asc_header(self, f) -> None:
        f.write(
            f"date {datetime.now().strftime('%a %b %d %I:%M:%S %p %Y')}\n"
            "base hex  timestamps absolute\n"
            "internal events logged\n"
            "// version 8.5.0\n"
            "Begin Triggerblock\n"
        )

    @staticmethod
    def _write_batch(f, batch: list) -> None:
        for msg in batch:
            direction = "Tx" if msg.is_tx else "Rx"
            data_hex  = msg.data.hex(" ").upper()
            f.write(
                f"{msg.timestamp:.6f} {msg.ch_id + 1}  "
                f"{msg.arb_id:X}  {direction}  d  {msg.dlc}  {data_hex}\n"
            )

    # ------------------------------------------------------------------
    # QThread 실행 루프
    # ------------------------------------------------------------------

    def run(self) -> None:
        self._running = True
        file_index    = 1
        last_drop     = 0

        while self._running:
            current_path = self._make_path(file_index)
            with open(current_path, "w", encoding="utf-8") as f:
                if self._fmt == "asc":
                    self._write_asc_header(f)

                batch: list = []

                while self._running:
                    try:
                        msg = self._q.get(timeout=0.1)
                        batch.append(msg)
                        if len(batch) >= CHUNK_SIZE:
                            self._write_batch(f, batch)
                            batch.clear()
                    except queue.Empty:
                        if batch:
                            self._write_batch(f, batch)
                            batch.clear()
                        f.flush()

                    # drop_count 변화 감지 → UI 경고
                    if self._lq.drop_count != last_drop:
                        last_drop = self._lq.drop_count
                        self.log_dropped.emit(last_drop)

                    # Log Rotation 판단
                    if f.tell() >= MAX_FILE_BYTES:
                        if self._fmt == "asc":
                            f.write("End TriggerBlock\n")
                        break   # ← break → else 블록 미실행 (의도적)
                else:
                    # 정상 종료(stop()) 경로 — 잔여 배치 반드시 기록
                    if batch:
                        self._write_batch(f, batch)
                    if self._fmt == "asc":
                        f.write("End TriggerBlock\n")
                    break   # 외부 while self._running 루프 탈출

            # Log Rotation: 다음 파일로
            file_index += 1
            self.log_rotated.emit(self._make_path(file_index))

    # ------------------------------------------------------------------
    # 종료
    # ------------------------------------------------------------------

    def stop(self) -> None:
        self._running = False
        self.wait()
