"""Chrome AppAgent."""

from sara.app_agents.base_agent import BaseAppAgent


class ChromeAgent(BaseAppAgent):
    app_name = "Chrome"
    exe_name = "chrome.exe"
    ui_type = "Electron (Chromium)"
    known_tasks = [
        "Open new tab",
        "Focus address bar",
        "Open downloads",
        "Open settings",
        "Search YouTube",
    ]

    def get_ui_summary(self) -> str:
        return "Chrome with omnibox, tab strip, toolbar buttons and overflow menu"
