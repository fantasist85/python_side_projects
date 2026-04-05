# core/async_db_loader.py
import threading
from PySide6.QtCore import QObject, Signal

from core.db_parser import DbParser


class AsyncDbLoader(QObject):
    """
    THREAD  : _run()=daemon Thread, db_loaded Signal 수신=Main Thread
    INPUT   : DbParser 인스턴스, 로드할 파일 경로
    OUTPUT  : db_loaded Signal(bool, DbParser)
    DO NOT  : Signal emit 전 self 참조 없애지 말 것 (GC → Segfault).
              함수 내 로컬 변수로 생성 금지 — 반드시 self._db_loader 형태로 바인딩.
              _on_db_loaded() 또는 __init__() 내부에서 이전 Signal disconnect 처리 금지.

    올바른 사용 패턴 (MainWindow):
        # 연속 로드 시 이전 Signal 해제
        if self._db_loader is not None:
            try:
                self._db_loader.db_loaded.disconnect(self._on_db_loaded)
            except RuntimeError:
                pass
        self._db_loader = AsyncDbLoader(parser, path)   # self에 저장 필수
        self._db_loader.db_loaded.connect(self._on_db_loaded)
        self._db_loader.start_loading()
    """

    db_loaded = Signal(bool, object)   # (success: bool, parser: DbParser)

    def __init__(self, parser: DbParser, path: str) -> None:
        super().__init__()
        self._parser = parser
        self._path   = path

    def start_loading(self) -> None:
        """daemon Thread 시작. 완료 시 db_loaded Signal emit."""
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        ok = self._parser.load(self._path)
        self.db_loaded.emit(ok, self._parser)
