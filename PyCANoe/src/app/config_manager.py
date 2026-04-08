# app/config_manager.py
"""
ConfigManager — QSettings 저장/복원 + SETTINGS_VERSION 마이그레이션.

THREAD  : Main Thread 전용
INPUT   : MainWindow, ChannelManager
OUTPUT  : save() / restore() 통해 윈도우 레이아웃·채널 설정 영속화
DO NOT  : Worker Thread에서 호출
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QSettings

if TYPE_CHECKING:
    from PySide6.QtWidgets import QMainWindow
    from core.channel_manager import ChannelConfig

logger = logging.getLogger(__name__)

SETTINGS_VERSION = 1   # 스키마 버전 — 변경 시 _migrate() 추가


class ConfigManager:
    """
    THREAD  : Main Thread 전용
    DO NOT  : Worker Thread 호출, QSettings를 여러 인스턴스에서 동시 접근

    저장 항목 (명세서 7.4):
      settings_version, window/geometry, window/state,
      channel/{n}/interface|channel|bitrate|fd_mode|data_bitrate|db_path,
      log/last_path, trace/filter_id|filter_mask|auto_scroll,
      graph/rolling_window_sec
    """

    def __init__(self) -> None:
        self._qs = QSettings("PyCANoe", "PyCANoe")

    # ------------------------------------------------------------------
    # 저장
    # ------------------------------------------------------------------

    def save_window(self, window: QMainWindow) -> None:
        """윈도우 geometry + Dock 레이아웃 저장."""
        self._qs.setValue("settings_version", SETTINGS_VERSION)
        self._qs.setValue("window/geometry", window.saveGeometry())
        self._qs.setValue("window/state",    window.saveState())

    def save_channels(self, configs: list[tuple[int, ChannelConfig]]) -> None:
        """채널 설정 저장. configs = [(ch_id, ChannelConfig), ...]"""
        # settings_version 없으면 restore_channels()의 _migrate()가 v0으로 판단해 clear() 호출
        self._qs.setValue("settings_version", SETTINGS_VERSION)
        self._qs.setValue("channel/count", len(configs))
        for ch_id, cfg in configs:
            prefix = f"channel/{ch_id}"
            self._qs.setValue(f"{prefix}/interface",    cfg.interface)
            self._qs.setValue(f"{prefix}/channel",      cfg.channel)
            self._qs.setValue(f"{prefix}/bitrate",      cfg.bitrate)
            self._qs.setValue(f"{prefix}/fd_mode",      cfg.fd_mode)
            self._qs.setValue(f"{prefix}/data_bitrate", cfg.data_bitrate)
            self._qs.setValue(f"{prefix}/app_name",     cfg.app_name)
            if cfg.db_path:
                self._qs.setValue(f"{prefix}/db_path",  cfg.db_path)

    def save_log_path(self, path: str) -> None:
        self._qs.setValue("log/last_path", path)

    def save_trace_filter(
        self, filter_id: str, filter_mask: str, auto_scroll: bool
    ) -> None:
        self._qs.setValue("trace/filter_id",    filter_id)
        self._qs.setValue("trace/filter_mask",  filter_mask)
        self._qs.setValue("trace/auto_scroll",  auto_scroll)

    def save_graph_window(self, rolling_sec: int) -> None:
        """rolling_sec: 5 / 10 / 30 / 0(전체)"""
        self._qs.setValue("graph/rolling_window_sec", rolling_sec)

    # ------------------------------------------------------------------
    # 복원
    # ------------------------------------------------------------------

    def restore_window(self, window: QMainWindow) -> bool:
        """저장된 geometry/state 복원. 저장 데이터 없으면 False 반환."""
        self._migrate()
        geo   = self._qs.value("window/geometry")
        state = self._qs.value("window/state")
        if geo:
            window.restoreGeometry(geo)
        if state:
            window.restoreState(state)
        return bool(geo or state)

    def restore_channels(self) -> list[tuple[int, ChannelConfig]]:
        """
        저장된 채널 설정 복원.
        반환: [(ch_id, ChannelConfig), ...] — 없으면 빈 리스트.
        """
        from core.channel_manager import ChannelConfig

        self._migrate()
        count = int(self._qs.value("channel/count", 0))
        result: list[tuple[int, ChannelConfig]] = []
        for ch_id in range(count):
            prefix = f"channel/{ch_id}"
            if not self._qs.contains(f"{prefix}/interface"):
                continue
            cfg = ChannelConfig(
                interface    = self._qs.value(f"{prefix}/interface",    "virtual"),
                channel      = int(self._qs.value(f"{prefix}/channel",  ch_id)),
                bitrate      = int(self._qs.value(f"{prefix}/bitrate",  500_000)),
                fd_mode      = self._qs.value(f"{prefix}/fd_mode",      False, type=bool),
                data_bitrate = int(self._qs.value(f"{prefix}/data_bitrate", 2_000_000)),
                app_name     = self._qs.value(f"{prefix}/app_name",    "PyCANoe"),
                db_path      = self._qs.value(f"{prefix}/db_path",      None),
            )
            result.append((ch_id, cfg))
        return result

    def restore_log_path(self) -> str:
        return self._qs.value("log/last_path", "")

    def restore_trace_filter(self) -> tuple[str, str, bool]:
        """반환: (filter_id, filter_mask, auto_scroll)"""
        return (
            self._qs.value("trace/filter_id",   ""),
            self._qs.value("trace/filter_mask",  ""),
            self._qs.value("trace/auto_scroll",  True, type=bool),
        )

    def restore_graph_window(self) -> int:
        return int(self._qs.value("graph/rolling_window_sec", 30))

    # ------------------------------------------------------------------
    # 마이그레이션
    # ------------------------------------------------------------------

    def _migrate(self) -> None:
        """
        저장된 버전과 현재 SETTINGS_VERSION 불일치 시 마이그레이션.
        버전 업 시 이 메서드에 변환 로직 추가.
        """
        stored = int(self._qs.value("settings_version", 0))
        if stored == SETTINGS_VERSION:
            return

        if stored == 0:
            # v0 → v1: 초기 버전 — 설정 초기화
            logger.info("ConfigManager: settings v0 → v1 마이그레이션 (초기화)")
            self._qs.clear()
            self._qs.setValue("settings_version", SETTINGS_VERSION)

        # 향후 버전 추가 시:
        # if stored <= 1:
        #     ... v1 → v2 변환 ...
