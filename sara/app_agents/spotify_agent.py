"""Spotify AppAgent."""

from sara.app_agents.base_agent import BaseAppAgent


class SpotifyAgent(BaseAppAgent):
    app_name = "Spotify"
    exe_name = "spotify.exe"
    ui_type = "Electron"
    known_tasks = [
        "Play",
        "Pause",
        "Next track",
        "Previous track",
        "Open home",
        "Open search",
    ]

    def get_ui_summary(self) -> str:
        return "Spotify with left nav, central content area, and playback controls"
