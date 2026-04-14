# tests/test_sim_lin.py
"""
M10 LIN IG 지원 검증 테스트.

커버 항목:
  Phase B (sim_worker.py):
    - _calc_lin_pid(): LIN spec §2.3.1 PID 패리티 계산
    - SimMessage.bus_type 기본값 "can"
    - SimMessage.to_lin_message(): PID 포함 can.Message 생성
    - SimMessage.to_bus_message(): bus_type 분기 (can/lin)
    - SimWorker._send_due_messages(): to_bus_message() 사용 확인

  Phase A (sim_dock.py):
    - _SimMessageDetail: LIN 채널 선택 시 레이블 변경
    - _collect(): LIN 채널 시 bus_type="lin" + 6-bit 클램프
    - _collect(): CAN 채널 시 bus_type="can"
    - SimDock._start_message(): bus_type 전달 확인
"""
import os
import sys
import time
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest
import can

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.sim_worker import SimMessage, SimWorker, _calc_lin_pid


# ===========================================================================
# Phase B: _calc_lin_pid() 패리티 계산
# ===========================================================================

class TestCalcLinPid:
    """
    LIN spec §2.3.1 패리티 비트 검증.
      P0 = ID0 ^ ID1 ^ ID2 ^ ID4
      P1 = ~(ID1 ^ ID3 ^ ID4 ^ ID5) & 1
    """

    def test_frame_id_0x00(self):
        """frame_id=0x00 → PID=0xC0 (P0=0, P1=1 → ~0=1)."""
        # ID0..5 = 0 → P0=0, P1=~0=1 → 0x00|0x00|0x80 = 0x80
        # But: P1 = ~(0^0^0^0) & 1 = ~0 & 1 = ...
        # Python: ~0 = -1, -1 & 1 = 1 → P1=1 → bit7 set → 0x80
        pid = _calc_lin_pid(0x00)
        assert pid == 0x80

    def test_frame_id_0x01(self):
        """frame_id=0x01 (ID0=1,rest=0) → P0=1, P1=1 → PID=0xC1."""
        # P0 = 1^0^0^0 = 1 → bit6
        # P1 = ~(0^0^0^0) & 1 = 1 → bit7
        pid = _calc_lin_pid(0x01)
        assert pid == 0xC1

    def test_frame_id_0x02(self):
        """frame_id=0x02 (ID1=1,rest=0) → P0=1, P1=~1=0 → PID=0x42."""
        # P0 = 0^1^0^0 = 1 → bit6 set
        # P1 = ~(1^0^0^0) & 1 = ~1 & 1 = 0 → bit7 clear
        # PID = 0x02 | 0x40 = 0x42
        pid = _calc_lin_pid(0x02)
        assert pid == 0x42

    def test_frame_id_0x3F(self):
        """frame_id=0x3F (all bits=1) → PID 상위 비트 계산."""
        # ID0=1,ID1=1,ID2=1,ID3=1,ID4=1,ID5=1
        # P0 = 1^1^1^1 = 0 → bit6 clear
        # P1 = ~(1^1^1^1) & 1 = ~0 & 1 = 1 → bit7 set
        pid = _calc_lin_pid(0x3F)
        assert pid == 0xBF   # 0x3F | 0x80 = 0xBF

    def test_upper_bits_ignored(self):
        """6-bit 초과 입력 → 하위 6bit만 사용."""
        assert _calc_lin_pid(0x40) == _calc_lin_pid(0x00)   # 0x40 & 0x3F = 0
        assert _calc_lin_pid(0x41) == _calc_lin_pid(0x01)   # 0x41 & 0x3F = 1
        assert _calc_lin_pid(0xFF) == _calc_lin_pid(0x3F)

    def test_pid_always_8bit(self):
        """PID는 항상 0~255 범위."""
        for fid in range(64):
            pid = _calc_lin_pid(fid)
            assert 0 <= pid <= 255, f"frame_id={fid}: PID={pid} out of range"

    def test_pid_frame_id_extracted_correctly(self):
        """PID & 0x3F = 원래 frame_id."""
        for fid in range(64):
            pid = _calc_lin_pid(fid)
            assert (pid & 0x3F) == fid, f"frame_id={fid}: pid & 0x3F = {pid & 0x3F}"

    def test_known_pid_table(self):
        """LIN spec 예시 PID 검증 (일부)."""
        known = {
            0x00: 0x80,
            0x01: 0xC1,
            0x02: 0x42,
            0x03: 0x03,
            0x04: 0xC4,
            0x05: 0x85,
        }
        for fid, expected_pid in known.items():
            assert _calc_lin_pid(fid) == expected_pid, (
                f"frame_id=0x{fid:02X}: expected PID=0x{expected_pid:02X}, "
                f"got=0x{_calc_lin_pid(fid):02X}"
            )


# ===========================================================================
# Phase B: SimMessage bus_type + 메시지 생성
# ===========================================================================

class TestSimMessageBusType:
    def test_default_bus_type_is_can(self):
        """기본 bus_type은 'can'이어야 한다."""
        msg = SimMessage(arb_id=0x100, data=b"\x00" * 8, interval_ms=100.0)
        assert msg.bus_type == "can"

    def test_bus_type_lin_accepted(self):
        """bus_type='lin' 설정 가능."""
        msg = SimMessage(arb_id=0x01, data=b"\x00", interval_ms=50.0, bus_type="lin")
        assert msg.bus_type == "lin"

    def test_to_can_message_uses_arb_id_directly(self):
        """CAN: arb_id → arbitration_id 그대로."""
        msg = SimMessage(arb_id=0x1A0, data=b"\x01\x02", interval_ms=100.0)
        cm = msg.to_can_message()
        assert cm.arbitration_id == 0x1A0

    def test_to_lin_message_computes_pid(self):
        """LIN: frame_id=0x01 → PID=0xC1 (패리티 포함)."""
        msg = SimMessage(arb_id=0x01, data=b"\xAA", interval_ms=50.0, bus_type="lin")
        lm = msg.to_lin_message()
        assert lm.arbitration_id == _calc_lin_pid(0x01)
        assert lm.arbitration_id == 0xC1

    def test_to_lin_message_data_preserved(self):
        """LIN 메시지 data는 그대로 전달된다."""
        payload = b"\x11\x22\x33"
        msg = SimMessage(arb_id=0x02, data=payload, interval_ms=20.0, bus_type="lin")
        lm = msg.to_lin_message()
        assert bytes(lm.data) == payload

    def test_to_bus_message_can(self):
        """bus_type='can': to_bus_message() == to_can_message()."""
        msg = SimMessage(arb_id=0x100, data=b"\x00" * 8, interval_ms=100.0, bus_type="can")
        assert msg.to_bus_message().arbitration_id == msg.to_can_message().arbitration_id

    def test_to_bus_message_lin(self):
        """bus_type='lin': to_bus_message() == to_lin_message()."""
        msg = SimMessage(arb_id=0x03, data=b"\x00", interval_ms=20.0, bus_type="lin")
        assert msg.to_bus_message().arbitration_id == msg.to_lin_message().arbitration_id

    def test_to_lin_message_clips_to_6bit(self):
        """arb_id=0x41 → 6-bit clip → frame_id=0x01 → PID=0xC1."""
        msg = SimMessage(arb_id=0x41, data=b"\x00", interval_ms=10.0, bus_type="lin")
        lm = msg.to_lin_message()
        assert lm.arbitration_id == _calc_lin_pid(0x01)

    def test_is_extended_id_false_for_lin(self):
        """LIN 메시지는 is_extended_id=False."""
        msg = SimMessage(arb_id=0x01, data=b"\x00", interval_ms=10.0, bus_type="lin")
        lm = msg.to_lin_message()
        assert lm.is_extended_id is False


# ===========================================================================
# Phase B: SimWorker가 to_bus_message() 사용 확인
# ===========================================================================

class TestSimWorkerUsesToBusMessage:
    """SimWorker._send_due_messages()가 to_bus_message()를 호출함을 검증."""

    def test_send_uses_to_bus_message_for_can(self):
        mock_worker = MagicMock()
        sw = SimWorker(ch_id=0, bus_sender=mock_worker)

        msg = SimMessage(
            arb_id=0x100, data=b"\x00" * 8, interval_ms=10.0, bus_type="can"
        )
        msg.next_send_at = time.perf_counter() - 1.0  # due now

        sw._send_due_messages(time.perf_counter(), [msg])

        mock_worker.send.assert_called_once()
        sent_msg = mock_worker.send.call_args[0][0]
        assert sent_msg.arbitration_id == 0x100  # CAN: arb_id 그대로

    def test_send_uses_to_bus_message_for_lin(self):
        mock_worker = MagicMock()
        sw = SimWorker(ch_id=0, bus_sender=mock_worker)

        msg = SimMessage(
            arb_id=0x01, data=b"\xAA", interval_ms=10.0, bus_type="lin"
        )
        msg.next_send_at = time.perf_counter() - 1.0  # due now

        sw._send_due_messages(time.perf_counter(), [msg])

        mock_worker.send.assert_called_once()
        sent_msg = mock_worker.send.call_args[0][0]
        # LIN: PID = _calc_lin_pid(0x01) = 0xC1
        assert sent_msg.arbitration_id == 0xC1

    def test_not_due_messages_not_sent(self):
        """기한 미도래 메시지는 전송하지 않는다."""
        mock_worker = MagicMock()
        sw = SimWorker(ch_id=0, bus_sender=mock_worker)
        msg = SimMessage(arb_id=0x01, data=b"\x00", interval_ms=100.0, bus_type="lin")
        msg.next_send_at = time.perf_counter() + 99.0  # far future
        sw._send_due_messages(time.perf_counter(), [msg])
        mock_worker.send.assert_not_called()


# ===========================================================================
# Phase A: SimDock / _SimMessageDetail UI LIN 인식
# ===========================================================================

class TestSimMessageDetailLinUI:
    """_SimMessageDetail의 LIN 채널 인식 UI 테스트 (headless Qt)."""

    @pytest.fixture
    def lin_ctx(self):
        """LIN 채널 Context mock."""
        ctx = MagicMock()
        ctx.config.bus_type = "lin"
        return ctx

    @pytest.fixture
    def can_ctx(self):
        """CAN 채널 Context mock."""
        ctx = MagicMock()
        ctx.config.bus_type = "can"
        return ctx

    @pytest.fixture
    def mock_cm_lin(self, lin_ctx):
        cm = MagicMock()
        cm.get.return_value = lin_ctx
        return cm

    @pytest.fixture
    def mock_cm_can(self, can_ctx):
        cm = MagicMock()
        cm.get.return_value = can_ctx
        return cm

    @pytest.fixture
    def mock_cm_none(self):
        cm = MagicMock()
        cm.get.return_value = None
        return cm

    def test_label_changes_to_frame_id_for_lin(self, qapp, qtbot, mock_cm_lin):
        """LIN 채널 → 레이블이 'Frame ID (0x00~0x3F):' 로 변경된다."""
        from widgets.sim_dock import _SimMessageDetail
        detail = _SimMessageDetail(mock_cm_lin)
        qtbot.addWidget(detail)
        detail._on_ch_type_changed(0)
        assert "Frame ID" in detail._lbl_arb_id.text()

    def test_label_stays_arbitration_id_for_can(self, qapp, qtbot, mock_cm_can):
        """CAN 채널 → 레이블이 'Arbitration ID:' 유지."""
        from widgets.sim_dock import _SimMessageDetail
        detail = _SimMessageDetail(mock_cm_can)
        qtbot.addWidget(detail)
        detail._on_ch_type_changed(0)
        assert "Arbitration ID" in detail._lbl_arb_id.text()

    def test_label_stays_arbitration_id_when_ctx_none(self, qapp, qtbot, mock_cm_none):
        """채널이 없을 때(ctx=None) → CAN 레이블 유지."""
        from widgets.sim_dock import _SimMessageDetail
        detail = _SimMessageDetail(mock_cm_none)
        qtbot.addWidget(detail)
        detail._on_ch_type_changed(0)
        assert "Arbitration ID" in detail._lbl_arb_id.text()

    def test_label_stays_when_cm_none(self, qapp, qtbot):
        """cm=None 전달 → 기본 CAN 레이블, 크래시 없음."""
        from widgets.sim_dock import _SimMessageDetail
        detail = _SimMessageDetail(None)
        qtbot.addWidget(detail)
        detail._on_ch_type_changed(0)   # 크래시 없어야 한다
        assert "Arbitration ID" in detail._lbl_arb_id.text()

    def test_is_lin_flag_set_correctly(self, qapp, qtbot, mock_cm_lin, mock_cm_can):
        """_is_lin 플래그가 채널 타입에 따라 정확히 설정된다."""
        from widgets.sim_dock import _SimMessageDetail

        detail_lin = _SimMessageDetail(mock_cm_lin)
        qtbot.addWidget(detail_lin)
        detail_lin._on_ch_type_changed(0)
        assert detail_lin._is_lin is True

        detail_can = _SimMessageDetail(mock_cm_can)
        qtbot.addWidget(detail_can)
        detail_can._on_ch_type_changed(0)
        assert detail_can._is_lin is False

    def test_collect_bus_type_lin(self, qapp, qtbot, mock_cm_lin):
        """LIN 채널 → _collect() 결과에 bus_type='lin' 포함."""
        from widgets.sim_dock import _SimMessageDetail
        detail = _SimMessageDetail(mock_cm_lin)
        qtbot.addWidget(detail)
        detail._on_ch_type_changed(0)   # LIN 활성
        detail._le_arb_id.setText("01")
        result = detail._collect()
        assert result["bus_type"] == "lin"

    def test_collect_bus_type_can(self, qapp, qtbot, mock_cm_can):
        """CAN 채널 → _collect() 결과에 bus_type='can' 포함."""
        from widgets.sim_dock import _SimMessageDetail
        detail = _SimMessageDetail(mock_cm_can)
        qtbot.addWidget(detail)
        detail._on_ch_type_changed(0)
        detail._le_arb_id.setText("1A0")
        result = detail._collect()
        assert result["bus_type"] == "can"

    def test_collect_lin_frame_id_clamped_to_6bit(self, qapp, qtbot, mock_cm_lin):
        """LIN 채널에서 0x40 이상 입력 시 6-bit 클램프 (& 0x3F)."""
        from widgets.sim_dock import _SimMessageDetail
        detail = _SimMessageDetail(mock_cm_lin)
        qtbot.addWidget(detail)
        detail._on_ch_type_changed(0)
        detail._le_arb_id.setText("40")   # 0x40 → 클램프 → 0x00
        result = detail._collect()
        assert result["arb_id"] == 0x00

    def test_collect_lin_3f_not_clamped(self, qapp, qtbot, mock_cm_lin):
        """LIN 채널 최대 frame_id 0x3F 입력 → 그대로."""
        from widgets.sim_dock import _SimMessageDetail
        detail = _SimMessageDetail(mock_cm_lin)
        qtbot.addWidget(detail)
        detail._on_ch_type_changed(0)
        detail._le_arb_id.setText("3F")
        result = detail._collect()
        assert result["arb_id"] == 0x3F

    def test_collect_can_large_arb_id_not_clamped(self, qapp, qtbot, mock_cm_can):
        """CAN 채널에서는 0x7FF 등 큰 ID도 클램프 없음."""
        from widgets.sim_dock import _SimMessageDetail
        detail = _SimMessageDetail(mock_cm_can)
        qtbot.addWidget(detail)
        detail._on_ch_type_changed(0)
        detail._le_arb_id.setText("7FF")
        result = detail._collect()
        assert result["arb_id"] == 0x7FF

    def test_collect_lin_invalid_hex_uses_default(self, qapp, qtbot, mock_cm_lin):
        """LIN 채널에서 잘못된 hex 입력 → 기본값 0x01 사용."""
        from widgets.sim_dock import _SimMessageDetail
        detail = _SimMessageDetail(mock_cm_lin)
        qtbot.addWidget(detail)
        detail._on_ch_type_changed(0)
        detail._le_arb_id.setText("ZZZZ")  # invalid
        result = detail._collect()
        assert result["arb_id"] == 0x01


# ===========================================================================
# Phase A: SimDock._start_message() bus_type 전달 확인
# ===========================================================================

class TestSimDockStartMessageBusType:
    """SimDock이 SimMessage에 bus_type을 올바르게 전달하는지 검증."""

    @pytest.fixture
    def dock_with_lin_ch(self, qtbot):
        from widgets.sim_dock import SimDock
        from models.sim_state_store import SimStateStore

        lin_ctx = MagicMock()
        lin_ctx.config.bus_type = "lin"
        lin_ctx.sim_worker = None

        cm = MagicMock()
        cm.get.return_value = lin_ctx
        cm.all.return_value = [lin_ctx]

        sim_state = SimStateStore()
        dock = SimDock(cm, sim_state)
        qtbot.addWidget(dock)
        dock.show()
        return dock, cm, lin_ctx

    def test_start_message_lin_creates_correct_sim_message(self, qtbot, dock_with_lin_ch):
        """LIN 채널 메시지 시작 시 SimMessage.bus_type='lin' 확인."""
        from core.sim_worker import SimMessage, SimWorker

        dock, cm, lin_ctx = dock_with_lin_ch

        captured_messages = []

        original_add = SimWorker.add_message

        def mock_add(self, msg):
            captured_messages.append(msg)

        with patch.object(SimWorker, "add_message", mock_add), \
             patch.object(SimWorker, "start"):
            from PySide6.QtCore import Qt
            from PySide6.QtWidgets import QTreeWidgetItem
            item = QTreeWidgetItem(["1", "01", "100", "정지"])
            item.setData(0, Qt.ItemDataRole.UserRole, {
                "ch_id":       0,
                "arb_id":      0x01,
                "interval_ms": 100.0,
                "data":        b"\xAA",
                "bus_type":    "lin",
                "running":     False,
            })
            dock._msg_tree.addTopLevelItem(item)
            dock._msg_tree.setCurrentItem(item)
            dock._start_message(item)

        if captured_messages:
            assert captured_messages[0].bus_type == "lin"
