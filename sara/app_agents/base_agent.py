"""Base AppAgent contract for SARA."""

from __future__ import annotations

from typing import Dict, List


class BaseAppAgent:
    app_name = "Generic"
    exe_name = ""
    ui_type = "Unknown"
    known_tasks: List[str] = []

    def __init__(self, app_name: str = ""):
        self._app_name = app_name or self.app_name

    def get_ui_summary(self) -> str:
        return f"{self._app_name}: standard desktop UI with menu/content regions"

    def get_pre_seeded_paths(self) -> Dict[str, List[Dict]]:
        return {}

    def get_common_tasks(self) -> List[str]:
        return list(self.known_tasks)

    def get_description(self) -> str:
        return f"{self._app_name} ({self.ui_type}) with {len(self.known_tasks)} known tasks"

    def validate_preconditions(self) -> bool:
        return True

    def get_electron_warning(self) -> str:
        if "electron" in self.ui_type.lower() or "chromium" in self.ui_type.lower():
            return (
                f"{self._app_name} is Chromium/Electron-based. "
                "Some controls may require fallback interactions."
            )
        return ""
