# app/dialogs/error_dialog.py
"""
ErrorDialog — CANWorker 연결 오류 표시 다이얼로그.

THREAD  : Main Thread 전용
INPUT   : 오류 메시지 문자열
OUTPUT  : 사용자에게 오류 내용 표시. 재시도/닫기 선택.
DO NOT  : Worker Thread에서 직접 생성·표시
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class ErrorDialog(QDialog):
    """
    연결 오류 / 시스템 오류 표시 다이얼로그.

    사용 예 (MainWindow 슬롯):
        def _on_error(self, msg: str) -> None:
            dlg = ErrorDialog(msg, parent=self)
            dlg.exec()
    """

    def __init__(
        self,
        message: str,
        title: str = "연결 오류",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(420)
        self._build_ui(message)

    # ------------------------------------------------------------------
    # UI 구성
    # ------------------------------------------------------------------

    def _build_ui(self, message: str) -> None:
        layout = QVBoxLayout(self)

        # 아이콘 + 제목
        header = QHBoxLayout()
        icon_lbl = QLabel("⚠")
        icon_lbl.setStyleSheet("font-size: 28px;")
        header.addWidget(icon_lbl)

        title_lbl = QLabel("오류가 발생했습니다.")
        title_lbl.setStyleSheet("font-weight: bold; font-size: 14px;")
        header.addWidget(title_lbl, 1)
        layout.addLayout(header)

        # 오류 메시지 (읽기 전용 텍스트)
        self._txt = QTextEdit()
        self._txt.setReadOnly(True)
        self._txt.setPlainText(message)
        self._txt.setMaximumHeight(120)
        layout.addWidget(self._txt)

        # 버튼
        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    # ------------------------------------------------------------------
    # 클래스 메서드: 빠른 표시용
    # ------------------------------------------------------------------

    @classmethod
    def show_error(
        cls,
        message: str,
        title: str = "연결 오류",
        parent: QWidget | None = None,
    ) -> None:
        """한 줄로 오류 다이얼로그 표시."""
        dlg = cls(message, title=title, parent=parent)
        dlg.exec()
