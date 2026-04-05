# core/db_parser.py
import logging
from typing import Any

logger = logging.getLogger(__name__)

_MISS = object()   # "조회했으나 없음" sentinel. None과 구분.
                   # cantools는 없는 arb_id에 None이 아닌 KeyError를 던진다.


class DbParser:
    """
    THREAD  : 인스턴스별 독립 소유. 채널 간 공유 시 호출자가 Lock 보유 필수.
    INPUT   : arb_id: int, data: bytes
    OUTPUT  : (signals: dict|None, msg_name: str|None)
    DO NOT  : exception raise, Qt import
              _MISS sentinel을 None으로 대체 금지 (매 프레임 재탐색 버그 발생)
    """

    def __init__(self, path: str | None = None) -> None:
        self._db:   Any = None
        self._type: str | None = None   # "dbc" | "ldf" | None
        self._msg_def_cache: dict[int, Any] = {}
        if path:
            self.load(path)

    # ------------------------------------------------------------------
    # 공개 인터페이스
    # ------------------------------------------------------------------

    def load(self, path: str) -> bool:
        """
        DBC/LDF 파일 로드. 성공 시 True, 실패 시 False (self._db = None 유지).
        Graceful Degradation: 실패해도 시스템 계속 동작.
        """
        try:
            if path.lower().endswith(".dbc"):
                import cantools
                self._db   = cantools.database.load_file(path)
                self._type = "dbc"
            elif path.lower().endswith(".ldf"):
                import ldfparser
                self._db   = ldfparser.parse_ldf(path)
                self._type = "ldf"
            else:
                return False
            self.clear_cache()
            return True
        except Exception as exc:
            logger.warning("DbParser.load() failed: %s — %s", path, exc)
            self._db   = None
            self._type = None
            return False

    def clear_cache(self) -> None:
        """DB 핫스왑 시 호출. _MISS sentinel 포함 전체 삭제."""
        self._msg_def_cache.clear()

    def decode(self, arb_id: int, data: bytes) -> dict | None:
        """signals 딕셔너리만 반환. decode_with_name() 래퍼."""
        signals, _ = self.decode_with_name(arb_id, data)
        return signals

    def decode_with_name(
        self, arb_id: int, data: bytes
    ) -> tuple[dict | None, str | None]:
        """
        _MISS sentinel 캐싱으로 KeyError 반복 탐색 방지.
        실패 시 (None, None) 반환 — exception raise 절대 금지.
        """
        if self._db is None:
            return None, None

        try:
            if self._type == "dbc":
                return self._decode_dbc(arb_id, data)
            elif self._type == "ldf":
                return self._decode_ldf(arb_id, data)
            return None, None
        except Exception as exc:
            logger.debug("decode_with_name() unexpected: arb_id=0x%X — %s", arb_id, exc)
            return None, None

    # ------------------------------------------------------------------
    # 프로퍼티
    # ------------------------------------------------------------------

    @property
    def is_loaded(self) -> bool:
        return self._db is not None

    @property
    def db_type(self) -> str | None:
        return self._type

    # ------------------------------------------------------------------
    # 내부 구현
    # ------------------------------------------------------------------

    def _decode_dbc(
        self, arb_id: int, data: bytes
    ) -> tuple[dict | None, str | None]:
        if arb_id not in self._msg_def_cache:
            try:
                self._msg_def_cache[arb_id] = self._db.get_message_by_frame_id(arb_id)
            except KeyError:
                self._msg_def_cache[arb_id] = _MISS

        msg_def = self._msg_def_cache[arb_id]
        if msg_def is _MISS:
            return None, None

        try:
            signals = self._db.decode_message(arb_id, data)
            return signals, msg_def.name
        except Exception:
            return None, None

    def _decode_ldf(
        self, arb_id: int, data: bytes
    ) -> tuple[dict | None, str | None]:
        frame_id = arb_id & 0x3F
        if frame_id not in self._msg_def_cache:
            try:
                self._msg_def_cache[frame_id] = self._db.get_frame(frame_id)
            except Exception:
                self._msg_def_cache[frame_id] = _MISS

        frame = self._msg_def_cache[frame_id]
        if frame is _MISS:
            return None, None

        try:
            return frame.parse(bytes(data)), frame.name
        except Exception:
            return None, None
