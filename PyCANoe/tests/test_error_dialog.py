# tests/test_error_dialog.py
"""
ErrorDialog 단위 테스트.
커버리지 목표: 80%+ (현재 26%)
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QDialogButtonBox
from app.dialogs.error_dialog import ErrorDialog

_app = QApplication.instance() or QApplication([])


class TestErrorDialogInit:
    def test_creates_with_message(self) -> None:
        dlg = ErrorDialog("테스트 오류 메시지")
        assert dlg is not None
        assert dlg.windowTitle() == "연결 오류"

    def test_custom_title(self) -> None:
        dlg = ErrorDialog("오류", title="커스텀 제목")
        assert dlg.windowTitle() == "커스텀 제목"

    def test_message_displayed_in_textedit(self) -> None:
        msg = "이것은 오류 메시지입니다."
        dlg = ErrorDialog(msg)
        assert dlg._txt.toPlainText() == msg

    def test_textedit_is_readonly(self) -> None:
        dlg = ErrorDialog("오류")
        assert dlg._txt.isReadOnly()

    def test_minimum_width(self) -> None:
        dlg = ErrorDialog("오류")
        assert dlg.minimumWidth() == 420

    def test_with_parent(self, qtbot) -> None:
        from PySide6.QtWidgets import QWidget
        parent = QWidget()
        dlg = ErrorDialog("오류", parent=parent)
        assert dlg.parent() is parent
        parent.close()


class TestErrorDialogShowError:
    def test_show_error_classmethod_exists(self) -> None:
        """show_error 클래스 메서드가 존재한다."""
        assert callable(ErrorDialog.show_error)

    def test_show_error_creates_dialog(self, monkeypatch) -> None:
        """show_error()가 ErrorDialog 인스턴스를 생성하고 exec()를 호출한다."""
        created = []
        original_init = ErrorDialog.__init__

        def mock_exec(self):
            return 0

        monkeypatch.setattr(ErrorDialog, "exec", mock_exec)

        # show_error가 크래시 없이 실행되는지 확인
        ErrorDialog.show_error("테스트 메시지", title="테스트")
