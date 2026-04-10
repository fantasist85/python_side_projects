# tests/test_channel_dialog_lin.py
"""
M8 — ChannelDialog LIN 탭 단위 테스트.

규칙:
  - headless Qt: QT_QPA_PLATFORM=offscreen
  - QMenu.exec() / show() 호출 금지
  - isHidden() 사용 권장 (isVisible() headless 신뢰 불가)
"""
import pytest
from PySide6.QtWidgets import QApplication
from app.dialogs.channel_dialog import ChannelDialog
from core.channel_manager import ChannelConfig


# ------------------------------------------------------------------
# 1. 초기 상태 — CAN 패널 표시, LIN 패널 숨김
# ------------------------------------------------------------------

class TestChannelDialogInitialState:
    def test_default_bus_type_is_can(self, qtbot):
        dlg = ChannelDialog(ch_id=0)
        assert dlg._cb_bus_type.currentText() == "CAN"

    def test_lin_panel_hidden_on_start(self, qtbot):
        dlg = ChannelDialog(ch_id=0)
        assert dlg._lin_panel.isHidden()

    def test_can_panel_visible_on_start(self, qtbot):
        dlg = ChannelDialog(ch_id=0)
        assert not dlg._can_panel.isHidden()

    def test_fd_box_visible_on_can(self, qtbot):
        dlg = ChannelDialog(ch_id=0)
        assert not dlg._fd_box.isHidden()

    def test_filt_box_visible_on_can(self, qtbot):
        dlg = ChannelDialog(ch_id=0)
        assert not dlg._filt_box.isHidden()


# ------------------------------------------------------------------
# 2. 버스 유형 전환 — LIN 선택
# ------------------------------------------------------------------

class TestBusTypeSwitch:
    def test_switch_to_lin_hides_can_panel(self, qtbot):
        dlg = ChannelDialog(ch_id=0)
        dlg._cb_bus_type.setCurrentText("LIN")
        assert dlg._can_panel.isHidden()

    def test_switch_to_lin_shows_lin_panel(self, qtbot):
        dlg = ChannelDialog(ch_id=0)
        dlg._cb_bus_type.setCurrentText("LIN")
        assert not dlg._lin_panel.isHidden()

    def test_switch_to_lin_hides_fd_box(self, qtbot):
        dlg = ChannelDialog(ch_id=0)
        dlg._cb_bus_type.setCurrentText("LIN")
        assert dlg._fd_box.isHidden()

    def test_switch_to_lin_hides_filt_box(self, qtbot):
        dlg = ChannelDialog(ch_id=0)
        dlg._cb_bus_type.setCurrentText("LIN")
        assert dlg._filt_box.isHidden()

    def test_switch_back_to_can_shows_can_panel(self, qtbot):
        dlg = ChannelDialog(ch_id=0)
        dlg._cb_bus_type.setCurrentText("LIN")
        dlg._cb_bus_type.setCurrentText("CAN")
        assert not dlg._can_panel.isHidden()

    def test_switch_back_to_can_hides_lin_panel(self, qtbot):
        dlg = ChannelDialog(ch_id=0)
        dlg._cb_bus_type.setCurrentText("LIN")
        dlg._cb_bus_type.setCurrentText("CAN")
        assert dlg._lin_panel.isHidden()

    def test_lin_disables_fd_checked(self, qtbot):
        dlg = ChannelDialog(ch_id=0)
        dlg._fd_box.setChecked(True)
        dlg._cb_bus_type.setCurrentText("LIN")
        assert not dlg._fd_box.isChecked()

    def test_lin_disables_filt_checked(self, qtbot):
        dlg = ChannelDialog(ch_id=0)
        dlg._filt_box.setChecked(True)
        dlg._cb_bus_type.setCurrentText("LIN")
        assert not dlg._filt_box.isChecked()


# ------------------------------------------------------------------
# 3. get_config() — LIN 설정 추출
# ------------------------------------------------------------------

class TestGetConfigLin:
    def test_bus_type_is_lin(self, qtbot):
        dlg = ChannelDialog(ch_id=0)
        dlg._cb_bus_type.setCurrentText("LIN")
        cfg = dlg.get_config()
        assert cfg.bus_type == "lin"

    def test_default_lin_interface(self, qtbot):
        dlg = ChannelDialog(ch_id=0)
        dlg._cb_bus_type.setCurrentText("LIN")
        cfg = dlg.get_config()
        assert cfg.interface == "virtual_lin"

    def test_default_lin_baud(self, qtbot):
        dlg = ChannelDialog(ch_id=0)
        dlg._cb_bus_type.setCurrentText("LIN")
        cfg = dlg.get_config()
        assert cfg.lin_baud == 19200

    def test_select_vector_lin(self, qtbot):
        dlg = ChannelDialog(ch_id=0)
        dlg._cb_bus_type.setCurrentText("LIN")
        dlg._cb_lin_interface.setCurrentText("vector_lin")
        cfg = dlg.get_config()
        assert cfg.interface == "vector_lin"

    def test_select_baud_9600(self, qtbot):
        dlg = ChannelDialog(ch_id=0)
        dlg._cb_bus_type.setCurrentText("LIN")
        dlg._cb_lin_baud.setCurrentIndex(0)   # 9600
        cfg = dlg.get_config()
        assert cfg.lin_baud == 9600

    def test_select_baud_38400(self, qtbot):
        dlg = ChannelDialog(ch_id=0)
        dlg._cb_bus_type.setCurrentText("LIN")
        dlg._cb_lin_baud.setCurrentIndex(2)   # 38400
        cfg = dlg.get_config()
        assert cfg.lin_baud == 38400

    def test_lin_channel_number(self, qtbot):
        dlg = ChannelDialog(ch_id=0)
        dlg._cb_bus_type.setCurrentText("LIN")
        dlg._spin_lin_channel.setValue(3)
        cfg = dlg.get_config()
        assert cfg.channel == 3

    def test_lin_no_fd_mode(self, qtbot):
        dlg = ChannelDialog(ch_id=0)
        dlg._cb_bus_type.setCurrentText("LIN")
        cfg = dlg.get_config()
        assert not cfg.fd_mode

    def test_lin_no_hw_filter(self, qtbot):
        dlg = ChannelDialog(ch_id=0)
        dlg._cb_bus_type.setCurrentText("LIN")
        cfg = dlg.get_config()
        assert cfg.hw_id_filter is None


# ------------------------------------------------------------------
# 4. get_config() — CAN 설정 (회귀)
# ------------------------------------------------------------------

class TestGetConfigCan:
    def test_bus_type_is_can(self, qtbot):
        dlg = ChannelDialog(ch_id=0)
        cfg = dlg.get_config()
        assert cfg.bus_type == "can"

    def test_default_interface_virtual(self, qtbot):
        dlg = ChannelDialog(ch_id=0)
        cfg = dlg.get_config()
        assert cfg.interface == "virtual"

    def test_default_bitrate_500k(self, qtbot):
        dlg = ChannelDialog(ch_id=0)
        cfg = dlg.get_config()
        assert cfg.bitrate == 500_000


# ------------------------------------------------------------------
# 5. _load_config() — LIN 설정 복원
# ------------------------------------------------------------------

class TestLoadConfigLin:
    def test_load_lin_config_sets_bus_type(self, qtbot):
        existing = ChannelConfig(
            interface="vector_lin", channel=2, bitrate=9600,
            bus_type="lin", lin_baud=9600,
        )
        dlg = ChannelDialog(ch_id=0, config=existing)
        assert dlg._cb_bus_type.currentText() == "LIN"

    def test_load_lin_config_sets_interface(self, qtbot):
        existing = ChannelConfig(
            interface="vector_lin", channel=1, bitrate=38400,
            bus_type="lin", lin_baud=38400,
        )
        dlg = ChannelDialog(ch_id=0, config=existing)
        assert dlg._cb_lin_interface.currentText() == "vector_lin"

    def test_load_lin_config_sets_baud(self, qtbot):
        existing = ChannelConfig(
            interface="virtual_lin", channel=0, bitrate=9600,
            bus_type="lin", lin_baud=9600,
        )
        dlg = ChannelDialog(ch_id=0, config=existing)
        assert dlg._cb_lin_baud.currentData() == 9600

    def test_load_lin_config_sets_channel(self, qtbot):
        existing = ChannelConfig(
            interface="vector_lin", channel=4, bitrate=19200,
            bus_type="lin", lin_baud=19200,
        )
        dlg = ChannelDialog(ch_id=0, config=existing)
        assert dlg._spin_lin_channel.value() == 4

    def test_load_can_config_keeps_can_panel(self, qtbot):
        existing = ChannelConfig(interface="virtual", channel=0, bitrate=500_000)
        dlg = ChannelDialog(ch_id=0, config=existing)
        assert dlg._cb_bus_type.currentText() == "CAN"
        assert not dlg._can_panel.isHidden()


# ------------------------------------------------------------------
# 6. LIN 인터페이스 목록
# ------------------------------------------------------------------

class TestLinInterfaceList:
    def test_virtual_lin_in_list(self, qtbot):
        dlg = ChannelDialog(ch_id=0)
        items = [dlg._cb_lin_interface.itemText(i)
                 for i in range(dlg._cb_lin_interface.count())]
        assert "virtual_lin" in items

    def test_vector_lin_in_list(self, qtbot):
        dlg = ChannelDialog(ch_id=0)
        items = [dlg._cb_lin_interface.itemText(i)
                 for i in range(dlg._cb_lin_interface.count())]
        assert "vector_lin" in items

    def test_lin_baud_options(self, qtbot):
        dlg = ChannelDialog(ch_id=0)
        bauds = [dlg._cb_lin_baud.itemData(i)
                 for i in range(dlg._cb_lin_baud.count())]
        assert set(bauds) == {9600, 19200, 38400}
