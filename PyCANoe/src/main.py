# src/main.py
"""
PyCANoe 진입점.
Windows: timeBeginPeriod(1) 적용 — 기본 15.6ms → 1ms (SimWorker 타이밍 필수).
"""
import ctypes
import os
import sys

# src/ 디렉터리를 Python 경로에 추가 (패키지 임포트용)
sys.path.insert(0, os.path.dirname(__file__))

from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow


def _set_timer_resolution() -> None:
    """Windows 멀티미디어 타이머 해상도를 1ms로 설정."""
    if os.name == "nt":
        ctypes.windll.winmm.timeBeginPeriod(1)


def _restore_timer_resolution() -> None:
    """프로세스 종료 시 타이머 해상도 복원."""
    if os.name == "nt":
        ctypes.windll.winmm.timeEndPeriod(1)


if __name__ == "__main__":
    _set_timer_resolution()
    try:
        app = QApplication(sys.argv)
        app.setApplicationName("PyCANoe")
        app.setOrganizationName("PyCANoe")

        window = MainWindow()
        window.show()

        exit_code = app.exec()
    finally:
        _restore_timer_resolution()

    sys.exit(exit_code)
