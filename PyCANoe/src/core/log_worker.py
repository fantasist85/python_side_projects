# core/log_worker.py
"""
LogWorker — 비동기 로그 파일 기록 워커.

THREAD  : Worker Thread (QThread)
INPUT   : LogQueue (thread-safe queue, get_batch() 사용)
OUTPUT  : .asc / .csv 파일 기록

지원 포맷 (fmt 인자):
  "asc" — Vector ASC 형식 (기본)
  "csv" — CSV 형식 (timestamp, ch_id, arb_id, dlc, data, is_tx)

파일명 패턴 (Rev 6.0):
  첫 번째 파일:  <base>_001<ext>   (예: log_001.asc)
  Rotation 후 :  <base>_002<ext>, <base>_003<ext>, ...

Rotation:
  파일 크기가 MAX_FILE_BYTES(100MB) 초과 시 자동 분할.

Shutdown 순서 (while-else 구조):
  while-else의 else 블록이 정상 종료 flush 담당.
  stop() → _stop_req=True → while 루프 탈출 → else 블록에서 잔여 항목 flush.

STRICT RULES:
  - while-else 구조 유지 필수 (else 블록 = 정상종료 flush)
  - terminate() 절대 금지
  - ASC: Begin Triggerblock / End TriggerBlock 반드시 포함
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QThread, Signal

if TYPE_CHECKING:
    from models.log_queue import LogQueue
    from models.parsed_message import ParsedMessage

logger = logging.getLogger(__name__)

MAX_FILE_BYTES = 100 * 1024 * 1024   # 100 MB


class LogWorker(QThread):
    """
    THREAD  : Worker Thread
    DO NOT  : UI 위젯 접근, terminate() 호출

    Signals:
      log_dropped(int)    — 큐 드롭 발생 건수
      log_rotated(str)    — Rotation 후 새 파일 경로
    """

    log_dropped = Signal(int)
    log_rotated = Signal(str)

    def __init__(
        self,
        log_queue: "LogQueue",
        path: str,
        fmt: str = "asc",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._queue     = log_queue
        self._base_path = path          # 사용자가 지정한 원본 경로
        self._fmt       = fmt.lower()
        self._stop_req  = False

    # ------------------------------------------------------------------
    # 외부 API
    # ------------------------------------------------------------------

    def stop(self) -> None:
        """정상 종료 요청. while-else 구조로 잔여 항목 flush 후 종료."""
        self._stop_req = True
        self.wait()

    # ------------------------------------------------------------------
    # 파일 경로 헬퍼
    # ------------------------------------------------------------------

    def _make_path(self, index: int) -> str:
        """
        Rev 6.0: 분할 파일 경로 생성.
          log.asc    -> log_001.asc (index=1)
          log.asc    -> log_002.asc (index=2)
        """
        p   = Path(self._base_path)
        return str(p.parent / f"{p.stem}_{index:03d}{p.suffix}")

    # ------------------------------------------------------------------
    # QThread 진입점
    # ------------------------------------------------------------------

    def run(self) -> None:
        """
        외부 루프: Rotation마다 새 파일 open.
        내부 루프: get_batch()로 메시지 소비.
        while-else: else 블록이 정상종료 시 잔여 flush 담당.
        """
        file_index = 1

        while True:
            current_path = self._make_path(file_index)
            try:
                with open(current_path, "w", encoding="utf-8") as f:
                    self._write_header(f)

                    while not self._stop_req:
                        msgs = self._queue.get_batch(timeout=0.05)
                        if msgs:
                            self._write_batch(f, msgs)
                            f.flush()

                        # drop_count 갱신 알림
                        dc = self._queue.drop_count
                        if dc > 0:
                            self.log_dropped.emit(dc)

                        # Rotation 체크
                        try:
                            if os.path.getsize(current_path) >= MAX_FILE_BYTES:
                                self._write_footer(f)
                                break   # 내부 루프 탈출 -> Rotation
                        except OSError:
                            pass

                    else:
                        # ── 정상 종료 경로 (stop() 호출) ──────────────────
                        # 잔여 항목 flush (STRICT RULE §10)
                        remaining = self._queue.get_batch(timeout=0.0)
                        if remaining:
                            self._write_batch(f, remaining)
                            f.flush()
                        self._write_footer(f)
                        break   # 외부 루프 탈출

            except Exception as exc:
                logger.error("LogWorker 오류: %s", exc)
                break

            # Rotation 후 다음 파일로
            file_index += 1
            next_path = self._make_path(file_index)
            self.log_rotated.emit(next_path)
            logger.info("LogWorker rotation -> %s", next_path)

    # ------------------------------------------------------------------
    # 헤더 / 푸터
    # ------------------------------------------------------------------

    def _write_header(self, f) -> None:
        if self._fmt == "csv":
            f.write("timestamp,ch_id,arb_id,dlc,data,is_tx\n")
        else:
            # ASC 헤더 — CANalyzer 호환 (Rev 5.0)
            t = time.strftime("%a %b %d %I:%M:%S %p %Y")
            f.write(f"date {t}\n")
            f.write("base hex  timestamps absolute\n")
            f.write("no internal events logged\n")
            f.write("// version 9.0.0\n")
            f.write("Begin Triggerblock\n")

    def _write_footer(self, f) -> None:
        if self._fmt != "csv":
            f.write("End TriggerBlock\n")

    # ------------------------------------------------------------------
    # 배치 기록
    # ------------------------------------------------------------------

    def _write_batch(self, f, msgs: list) -> None:
        for msg in msgs:
            try:
                f.write(self._format(msg))
            except Exception as exc:
                logger.warning("LogWorker 포맷 오류 (arb_id=0x%X): %s",
                               getattr(msg, "arb_id", 0), exc)

    def _format(self, msg) -> str:
        if self._fmt == "csv":
            return self._format_csv(msg)
        return self._format_asc(msg)

    @staticmethod
    def _format_asc(msg) -> str:
        direction = "Tx" if msg.is_tx else "Rx"
        data_hex  = " ".join(f"{b:02X}" for b in msg.data)
        return (
            f"   {msg.timestamp:.4f}  {msg.ch_id + 1}  "
            f"{msg.arb_id:X}  {direction}  d  {msg.dlc}  {data_hex}\n"
        )

    @staticmethod
    def _format_csv(msg) -> str:
        """STRICT RULE §17: ch_id 1-based, arb_id 대문자HEX, data 연속소문자HEX, is_tx 0/1"""
        return (
            f"{msg.timestamp:.6f},"
            f"{msg.ch_id + 1},"
            f"{msg.arb_id:X},"
            f"{msg.dlc},"
            f"{msg.data.hex()},"
            f"{int(msg.is_tx)}\n"
        )
