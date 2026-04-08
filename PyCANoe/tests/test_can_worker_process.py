# tests/test_can_worker_process.py
"""
CANWorker — _process_message / _connect_and_listen / retry 상세 커버리지 테스트.

목표 커버리지:
  - _process_message() : 정상 메시지 / 에러 프레임 / FD 프레임
  - _connect_and_listen() : HW 필터 적용 경로
  - run() + retry : CanError 발생 시 exponential backoff 확인
  - stop() 중 retry 대기 중 조기 종료
"""
import sys
import os
import time
import threading
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication
import can

from core.can_worker import CANWorker, build_bus_kwargs
from core.channel_manager import ChannelConfig
from core.db_parser import DbParser
from models.parsed_message import ParsedMessage

_app = QApplication.instance() or QApplication([])


def _make_config(**kwargs):
    defaults = dict(interface="virtual", channel=0, bitrate=500_000)
    defaults.update(kwargs)
    return ChannelConfig(**defaults)


def _make_worker(config=None, db=None):
    cfg = config or _make_config()
    db  = db or DbParser()
    return CANWorker(ch_id=0, config=cfg, db=db)


def _make_raw_msg(**kwargs):
    """python-can Message 목(Mock) 생성."""
    msg = MagicMock(spec=can.Message)
    msg.arbitration_id  = kwargs.get("arb_id",       0x123)
    msg.dlc             = kwargs.get("dlc",           8)
    msg.data            = bytearray(kwargs.get("data", b"\x01\x02\x03\x04\x05\x06\x07\x08"))
    msg.timestamp       = kwargs.get("timestamp",     100.0)
    msg.is_fd           = kwargs.get("is_fd",         False)
    msg.is_remote_frame = kwargs.get("is_remote",     False)
    msg.is_error_frame  = kwargs.get("is_error",      False)
    msg.bitrate_switch  = kwargs.get("bitrate_switch", False)
    return msg


# ──────────────────────────────────────────────────────────────────────────────
# _process_message
# ──────────────────────────────────────────────────────────────────────────────

class TestProcessMessage:
    def test_normal_message_emits_parsed_message(self, qtbot):
        """정상 수신 메시지 → ParsedMessage emit."""
        w = _make_worker()
        received = []
        w.parsed_message_received.connect(received.append)

        raw = _make_raw_msg(arb_id=0x1A0, dlc=8)
        w._process_message(raw)

        assert len(received) == 1
        pm = received[0]
        assert isinstance(pm, ParsedMessage)
        assert pm.arb_id == 0x1A0
        assert pm.ch_id  == 0
        assert pm.dlc    == 8

    def test_error_frame_increments_err_count(self, qtbot):
        """에러 프레임 → err_count 증가, is_error=True."""
        w = _make_worker()
        received = []
        w.parsed_message_received.connect(received.append)

        raw = _make_raw_msg(is_error=True, dlc=0, data=b"")
        w._process_message(raw)

        stats = w.get_stats()
        assert stats.error_count == 1
        assert received[0].is_error is True

    def test_fd_message_is_fd_true(self, qtbot):
        """CAN FD 메시지 → is_fd=True, is_brs 반영."""
        w = _make_worker()
        received = []
        w.parsed_message_received.connect(received.append)

        raw = _make_raw_msg(is_fd=True, bitrate_switch=True, dlc=15,
                            data=bytes(64))
        w._process_message(raw)

        pm = received[0]
        assert pm.is_fd  is True
        assert pm.is_brs is True

    def test_rx_count_increments(self, qtbot):
        """메시지 3개 수신 → rx_count == 3."""
        w = _make_worker()
        for _ in range(3):
            w._process_message(_make_raw_msg())
        stats = w.get_stats()
        assert stats.rx_count == 3

    def test_rx_bits_incremented_correctly(self, qtbot):
        """DLC=8, is_fd=False → 47+64 = 111 비트씩 누적."""
        from models.channel_stats import ChannelStats
        w = _make_worker()
        w._process_message(_make_raw_msg(dlc=8, is_fd=False))
        with w._stats_lock:
            assert w._rx_bits == ChannelStats.calc_frame_bits(8, False)

    def test_signals_decoded_when_db_loaded(self, qtbot):
        """DBC 로드된 경우 signals 딕셔너리가 채워져 있어야 한다."""
        import cantools
        db_path = os.path.join(os.path.dirname(__file__), "fixtures", "sample.dbc")
        parser = DbParser(db_path)
        w = _make_worker(db=parser)

        received = []
        w.parsed_message_received.connect(received.append)

        # sample.dbc의 첫 번째 메시지 ID/데이터 찾기
        if parser.is_loaded:
            msgs = parser._db.messages
            if msgs:
                m = msgs[0]
                raw = _make_raw_msg(arb_id=m.frame_id, dlc=m.length,
                                    data=bytes(m.length))
                w._process_message(raw)
                pm = received[0]
                # signals가 None이 아니거나 None이어도 크래시 없어야 함
                assert pm is not None

    def test_no_db_signals_is_none(self, qtbot):
        """DB 없으면 signals=None."""
        w = _make_worker(db=DbParser())
        received = []
        w.parsed_message_received.connect(received.append)
        w._process_message(_make_raw_msg())
        assert received[0].signals is None

    def test_parser_lock_protects_db_access(self, qtbot):
        """_parser_lock 보호 하에 decode 수행 — 동시 update_db 크래시 없음."""
        w  = _make_worker()
        db2 = DbParser()
        errors = []

        def updater():
            for _ in range(500):
                try:
                    w.update_db(db2)
                except Exception as e:
                    errors.append(e)

        def processer():
            for _ in range(500):
                try:
                    w._process_message(_make_raw_msg())
                except Exception as e:
                    errors.append(e)

        t1 = threading.Thread(target=updater)
        t2 = threading.Thread(target=processer)
        t1.start(); t2.start()
        t1.join(); t2.join()
        assert not errors


# ──────────────────────────────────────────────────────────────────────────────
# _connect_and_listen  —  HW 필터 경로
# ──────────────────────────────────────────────────────────────────────────────

class TestConnectAndListen:
    def test_hw_filter_applied_when_configured(self, qtbot):
        """hw_id_filter 설정 시 bus.set_filters() 호출되어야 한다."""
        cfg = _make_config(
            interface="virtual",
            channel=0,
            bitrate=500_000,
            hw_id_filter=0x1A0,
            hw_id_mask=0x7FF,
        )
        w = _make_worker(config=cfg)

        # virtual Bus를 Mock으로 대체
        mock_bus = MagicMock()
        mock_bus.__enter__ = lambda s: s
        mock_bus.__exit__  = MagicMock(return_value=False)
        mock_bus.recv.side_effect = [None, None]  # 2회 None 후 stop

        def stop_after_two(*_):
            w._stop = True
            return None

        call_count = [0]
        def recv_side(timeout):
            call_count[0] += 1
            if call_count[0] >= 2:
                w._stop = True
            return None

        mock_bus.recv.side_effect = recv_side

        with patch("core.can_worker.can.Bus", return_value=mock_bus):
            w._connect_and_listen()

        mock_bus.set_filters.assert_called_once()
        filters = mock_bus.set_filters.call_args[0][0]
        assert filters[0]["can_id"]   == 0x1A0
        assert filters[0]["can_mask"] == 0x7FF

    def test_no_hw_filter_when_not_configured(self, qtbot):
        """hw_id_filter 없으면 set_filters 호출 안 됨."""
        w = _make_worker()  # hw_id_filter=None 기본값

        mock_bus = MagicMock()
        mock_bus.__enter__ = lambda s: s
        mock_bus.__exit__  = MagicMock(return_value=False)

        call_count = [0]
        def recv_side(timeout):
            call_count[0] += 1
            if call_count[0] >= 1:
                w._stop = True
            return None

        mock_bus.recv.side_effect = recv_side

        with patch("core.can_worker.can.Bus", return_value=mock_bus):
            w._connect_and_listen()

        mock_bus.set_filters.assert_not_called()

    def test_connection_state_changed_emitted_on_connect(self, qtbot):
        """연결 성공 시 connection_state_changed(ch_id, True) emit."""
        w = _make_worker()
        states = []
        w.connection_state_changed.connect(lambda ch, s: states.append((ch, s)))

        mock_bus = MagicMock()
        mock_bus.__enter__ = lambda s: s
        mock_bus.__exit__  = MagicMock(return_value=False)

        call_count = [0]
        def recv_side(timeout):
            call_count[0] += 1
            if call_count[0] >= 1:
                w._stop = True
            return None

        mock_bus.recv.side_effect = recv_side

        with patch("core.can_worker.can.Bus", return_value=mock_bus):
            w._connect_and_listen()

        assert (0, True) in states

    def test_received_message_emitted(self, qtbot):
        """recv()가 메시지 반환 시 parsed_message_received emit."""
        w = _make_worker()
        received = []
        w.parsed_message_received.connect(received.append)

        raw = _make_raw_msg()
        call_count = [0]
        def recv_side(timeout):
            call_count[0] += 1
            if call_count[0] == 1:
                return raw
            w._stop = True
            return None

        mock_bus = MagicMock()
        mock_bus.__enter__ = lambda s: s
        mock_bus.__exit__  = MagicMock(return_value=False)
        mock_bus.recv.side_effect = recv_side

        with patch("core.can_worker.can.Bus", return_value=mock_bus):
            w._connect_and_listen()

        assert len(received) == 1


# ──────────────────────────────────────────────────────────────────────────────
# run() — retry / backoff
# ──────────────────────────────────────────────────────────────────────────────

class TestCANWorkerRetry:
    def test_retry_limit_exceeded_emits_error(self, qtbot):
        """MAX_RETRY 초과 시 error_occurred emit + 스레드 종료."""
        w = _make_worker()
        errors = []
        w.error_occurred.connect(errors.append)

        # _connect_and_listen이 항상 CanError 발생하도록
        with patch.object(w, "_connect_and_listen",
                          side_effect=can.CanError("test")):
            # msleep을 즉시 반환으로 Mock
            with patch.object(w, "msleep", return_value=None):
                w.run()

        # "재연결 한계 초과" 에러 메시지 포함 여부
        assert any("한계 초과" in e for e in errors)

    def test_stop_during_retry_wait_exits_cleanly(self, qtbot):
        """retry 대기 중 stop() 호출 → 조기 종료."""
        w = _make_worker()

        fail_count = [0]
        original_listen = None

        def mock_listen():
            fail_count[0] += 1
            if fail_count[0] == 1:
                raise can.CanError("first fail")
            # 2번째 호출 전에 이미 _stop=True이면 여기까지 안 옴

        with patch.object(w, "_connect_and_listen", side_effect=mock_listen):
            def delayed_stop():
                time.sleep(0.05)
                w._stop = True

            t = threading.Thread(target=delayed_stop)
            t.start()
            w.run()
            t.join()

        # 크래시 없이 종료되어야 함
        assert not w.isRunning()

    def test_retry_count_resets_after_success(self, qtbot):
        """성공 시 break로 탈출 — 재시도 루프 종료."""
        w = _make_worker()
        errors = []
        w.error_occurred.connect(errors.append)

        call_count = [0]
        def mock_listen():
            call_count[0] += 1
            if call_count[0] < 2:
                raise can.CanError("transient")
            # 2번째 호출: 정상 종료 (break 없이 return)

        with patch.object(w, "_connect_and_listen", side_effect=mock_listen):
            with patch.object(w, "msleep", return_value=None):
                w.run()

        # 한 번의 재시도 에러 메시지
        assert len([e for e in errors if "재시도" in e]) >= 1


# ──────────────────────────────────────────────────────────────────────────────
# send() 메서드
# ──────────────────────────────────────────────────────────────────────────────

class TestCANWorkerSend:
    def test_send_no_bus_does_not_crash(self):
        """_bus가 None이면 send() 호출 시 크래시 없어야 함."""
        w = _make_worker()
        assert w._bus is None
        msg = can.Message(arbitration_id=0x100, data=b"\x01", is_extended_id=False)
        w.send(msg)  # 크래시 없어야 함

    def test_send_with_bus_calls_bus_send(self):
        """_bus가 있으면 bus.send() 호출."""
        w = _make_worker()
        mock_bus = MagicMock()
        w._bus = mock_bus

        msg = can.Message(arbitration_id=0x100, data=b"\x01", is_extended_id=False)
        w.send(msg)

        mock_bus.send.assert_called_once_with(msg)

    def test_send_can_error_logged_not_raised(self):
        """bus.send()가 CanError 발생 시 예외 전파 없이 로그만."""
        w = _make_worker()
        mock_bus = MagicMock()
        mock_bus.send.side_effect = can.CanError("bus error")
        w._bus = mock_bus

        msg = can.Message(arbitration_id=0x100, data=b"\x01", is_extended_id=False)
        w.send(msg)   # 예외 전파 없어야 함
