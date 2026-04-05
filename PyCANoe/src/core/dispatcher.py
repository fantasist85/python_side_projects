# core/dispatcher.py
from PySide6.QtCore import QObject, Slot

from models.parsed_message import ParsedMessage


class MessageDispatcher(QObject):
    """
    THREAD  : Main Thread (QueuedConnection으로 수신)
    INPUT   : ParsedMessage (CANWorker.parsed_message_received Signal)
    OUTPUT  : 각 데이터 모델로 fan-out (MessageStore, SignalBufferRegistry,
              LogQueue, SimStateStore)
    DO NOT  : decode 수행, blocking call. Worker Thread 직접 접근.
    """

    def __init__(
        self,
        store:      "MessageStore",
        registry:   "SignalBufferRegistry",
        log_queue:  "LogQueue",
        sim_store:  "SimStateStore",
    ) -> None:
        super().__init__()
        self._store    = store
        self._registry = registry
        self._log_q    = log_queue
        self._sim      = sim_store

    @Slot(object)
    def on_message(self, msg: ParsedMessage) -> None:
        """
        Main Thread에서 실행. fan-out만 수행. decode 절대 금지.
        QueuedConnection으로 ChannelManager.add_channel()에서 명시적 연결.
        """
        self._store.append(msg)
        self._log_q.put(msg)

        if msg.signals:
            for sig_name, value in msg.signals.items():
                self._registry.append(
                    msg.ch_id, sig_name, msg.timestamp, float(value)
                )
            self._sim.update(msg.ch_id, msg.signals)

    @Slot(str)
    def on_error(self, error_msg: str) -> None:
        """에러 메시지 수신. MainWindow에서 별도 StatusBar 연결."""
        pass   # MainWindow.error_occurred Signal에서 처리
