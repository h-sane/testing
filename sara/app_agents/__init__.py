"""AppAgent registry for SARA."""

from sara.app_agents.base_agent import BaseAppAgent
from sara.app_agents.notepad_agent import NotepadAgent
from sara.app_agents.calculator_agent import CalculatorAgent
from sara.app_agents.excel_agent import ExcelAgent
from sara.app_agents.chrome_agent import ChromeAgent
from sara.app_agents.brave_agent import BraveAgent
from sara.app_agents.spotify_agent import SpotifyAgent

APP_AGENT_REGISTRY = {
    "notepad": NotepadAgent,
    "notepad.exe": NotepadAgent,
    "calculator": CalculatorAgent,
    "calc.exe": CalculatorAgent,
    "excel": ExcelAgent,
    "excel.exe": ExcelAgent,
    "chrome": ChromeAgent,
    "chrome.exe": ChromeAgent,
    "brave": BraveAgent,
    "brave.exe": BraveAgent,
    "spotify": SpotifyAgent,
    "spotify.exe": SpotifyAgent,
}


def get_agent_for_app(app_name: str) -> BaseAppAgent:
    cls = APP_AGENT_REGISTRY.get((app_name or "").lower(), BaseAppAgent)
    return cls(app_name)


__all__ = [
    "BaseAppAgent",
    "NotepadAgent",
    "CalculatorAgent",
    "ExcelAgent",
    "ChromeAgent",
    "BraveAgent",
    "SpotifyAgent",
    "APP_AGENT_REGISTRY",
    "get_agent_for_app",
]
