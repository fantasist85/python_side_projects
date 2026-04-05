# tests/test_virtual_pipeline.py
"""
virtual 2채널 E2E 송수신 + ParsedMessage 내용 검증.
H/W 없이 python-can virtual 인터페이스 사용.
"""
import sys, os
import time
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

pytest.importorskip("PySide6")

import can
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

from core.can_worker import CANWorker
from core.channel_manager import ChannelConfig
from core.db_parser import DbParser
from models.parsed_message import ParsedMessage

_app = QApplication.instance() or QApplication([])


class TestVirtualPipeline:
    def test_receive_parsed_message(self) -> None:
        """
        virtual 인터페이스:
        1. CANWorker(CH0) start
        2. 별도 Bus.send()로 메시지 전송
        3. parsed_message_received Signal에서 ParsedMessage 수신 확인
        """
        received: list[ParsedMessage] = []

        cfg    = ChannelConfig(interface="virtual", channel=0, bitrate=500_000)
        worker = CANWorker(ch_id=0, config=cfg, db=DbParser())
        worker.parsed_message_received.connect(
            lambda msg: received.append(msg),
            Qt.ConnectionType.DirectConnection,  # 테스트용 DirectConnection
        )
        worker.start()
        time.sleep(0.1)   # 연결 대기

        # 전송 측 Bus
        with can.Bus(interface="virtual", channel=0) as tx_bus:
            tx_bus.send(can.Message(
                arbitration_id=0x1A0,
                data=b"\x01\x02\x03\x04\x05\x06\x07\x08",
                is_extended_id=False,
            ))

        time.sleep(0.2)   # 수신 대기
        worker.stop()

        assert len(received) >= 1, "메시지 수신 없음"
        msg = received[0]
        assert msg.arb_id  == 0x1A0
        assert msg.ch_id   == 0
        assert msg.dlc     == 8
        assert msg.data    == b"\x01\x02\x03\x04\x05\x06\x07\x08"
        assert msg.signals is None   # DB 없으므로 None
        assert msg.is_tx   is False

    def test_parsed_message_is_frozen(self) -> None:
        """수신된 ParsedMessage는 frozen이어야 함."""
        received: list[ParsedMessage] = []

        cfg    = ChannelConfig(interface="virtual", channel=0, bitrate=500_000)
        worker = CANWorker(ch_id=0, config=cfg, db=DbParser())
        worker.parsed_message_received.connect(
            lambda msg: received.append(msg),
            Qt.ConnectionType.DirectConnection,
        )
        worker.start()
        time.sleep(0.1)

        with can.Bus(interface="virtual", channel=0) as tx_bus:
            tx_bus.send(can.Message(
                arbitration_id=0x300,
                data=b"\xAA" * 4,
                is_extended_id=False,
            ))

        time.sleep(0.2)
        worker.stop()

        assert received, "메시지 수신 없음"
        msg = received[0]
        with pytest.raises(Exception):
            msg.ch_id = 99  # type: ignore[misc]  # FrozenInstanceError
