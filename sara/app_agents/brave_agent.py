"""Brave AppAgent."""

from sara.app_agents.base_agent import BaseAppAgent


class BraveAgent(BaseAppAgent):
    app_name = "Brave"
    exe_name = "brave.exe"
    ui_type = "Electron (Chromium)"
    known_tasks = [
        "Open new tab",
        "Focus address bar",
        "Open history",
        "Open settings",
        "Search YouTube",
    ]

    def get_ui_summary(self) -> str:
        return "Brave browser with omnibox, tabs, toolbar and settings menu"
