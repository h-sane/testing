"""Deterministic macros for browser shortcuts and global save-dialog flows."""

import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

from sara.workflow_policy import build_save_as_steps

BROWSER_APPS = {"Chrome", "Brave"}

_MEDIA_NEXT_MARKERS = (
    "next song",
    "next track",
    "next video",
    "play next",
    "skip song",
    "skip track",
    "skip this",
    "next one",
)

_MEDIA_PAUSE_MARKERS = (
    "pause",
    "pause song",
    "pause current",
    "pause this",
)

_MEDIA_RESUME_MARKERS = (
    "resume",
    "continue",
    "continue playing",
    "resume song",
    "resume playback",
    "play current song",
)

_MEDIA_HINT_MARKERS = (
    "song",
    "track",
    "music",
    "video",
    "youtube",
    "playlist",
    "playback",
)

_SHORT_MEDIA_FOLLOWUPS = {
    "next",
    "skip",
    "pause",
    "resume",
    "continue",
    "next one",
}


def _extract_query(command: str) -> str:
    command_l = command.lower().strip()
    for marker in ("play ", "search ", "find "):
        idx = command_l.find(marker)
        if idx >= 0:
            return command[idx + len(marker):].strip()
    return ""


def _normalize_media_query(command: str) -> str:
    query = _extract_query(command).strip().strip("\"'")
    if not query:
        return "lofi music"

    # Remove platform and result-selection phrasing from natural-language commands.
    query = re.sub(r"\s+(on|in)\s+youtube\b", "", query, flags=re.IGNORECASE)
    query = re.sub(
        r"\s+(from\s+search\s+results|from\s+results|first\s+result|first\s+video)\b[\s\.,!?;:]*$",
        "",
        query,
        flags=re.IGNORECASE,
    )
    query = re.sub(r"\s+", " ", query).strip().strip("\"'")
    return query or "lofi music"


def extract_media_query(command: str) -> str:
    """Return normalized media query text from a natural-language command."""
    return _normalize_media_query(command)


def _is_youtube_play_command(command_l: str) -> bool:
    return "youtube" in command_l and any(token in command_l for token in ("play", "watch", "listen"))


def is_media_play_command(command: str) -> bool:
    command_l = str(command or "").lower().strip()
    return _is_youtube_play_command(command_l)


def _is_youtube_live_ax_selection_request(command_l: str) -> bool:
    if "youtube" not in command_l:
        return False

    markers = (
        "first result",
        "first video",
        "from search results",
        "from results",
        "select video",
        "choose video",
        "open video result",
    )
    return any(marker in command_l for marker in markers)


def _contains_any_marker(text: str, markers: tuple) -> bool:
    return any(marker in text for marker in markers)


def get_media_followup_action(command: str) -> str:
    """Classify a short playback follow-up into a deterministic media action."""
    text = str(command or "").lower().strip()
    if not text:
        return ""

    if _contains_any_marker(text, _MEDIA_NEXT_MARKERS):
        return "next"

    if _contains_any_marker(text, _MEDIA_PAUSE_MARKERS):
        return "pause_toggle"

    if _contains_any_marker(text, _MEDIA_RESUME_MARKERS):
        return "resume_toggle"

    return ""


def is_media_followup_command(command: str) -> bool:
    """Return True when command is a continuation control for current playback."""
    text = str(command or "").lower().strip()
    if not text:
        return False

    action = get_media_followup_action(text)
    if not action:
        return False

    if text in _SHORT_MEDIA_FOLLOWUPS:
        return True

    return _contains_any_marker(text, _MEDIA_HINT_MARKERS)


def get_media_followup_steps(app_name: str, command: str) -> Optional[List[Dict[str, Any]]]:
    """Deterministic continuation macro for media controls in browser tabs."""
    if app_name not in BROWSER_APPS:
        return None

    if not is_media_followup_command(command):
        return None

    action = get_media_followup_action(command)
    if not action:
        return None

    # Focus the browser window first, then send playback control hotkey.
    if action == "next":
        hotkey = "shift+n"
        wait_seconds = 1.2
    else:
        hotkey = "k"
        wait_seconds = 0.6

    return [
        {"action": "CLICK", "target": app_name},
        {"action": "HOTKEY", "keys": hotkey},
        {"action": "WAIT", "seconds": wait_seconds},
        {"action": "DONE"},
    ]


def _youtube_search_macro(command: str) -> List[Dict[str, Any]]:
    query = _normalize_media_query(command)
    safe_query = quote_plus(query)
    search_url = f"https://www.youtube.com/results?search_query={safe_query}"

    return [
        {"action": "HOTKEY", "keys": "ctrl+l"},
        {"action": "TYPE", "text": search_url},
        {"action": "HOTKEY", "keys": "enter"},
        {"action": "WAIT", "seconds": 2.0},
        {"action": "DONE"},
    ]


def _youtube_play_macro(command: str) -> List[Dict[str, Any]]:
    query = _normalize_media_query(command)
    lucky_query = quote_plus(f"site:youtube.com/watch {query}")
    lucky_url = f"https://www.google.com/search?btnI=1&q={lucky_query}"

    return [
        {"action": "HOTKEY", "keys": "ctrl+l"},
        {"action": "TYPE", "text": lucky_url},
        {"action": "HOTKEY", "keys": "enter"},
        {"action": "WAIT", "seconds": 2.5},
        {"action": "DONE"},
    ]


def _youtube_play_seed_steps(command: str) -> List[Dict[str, Any]]:
    query = _normalize_media_query(command)
    safe_query = quote_plus(query)
    search_url = f"https://www.youtube.com/results?search_query={safe_query}"

    # Bootstrap to search results, then let iterative LLM choose using live AX tree.
    return [
        {"action": "HOTKEY", "keys": "ctrl+l"},
        {"action": "TYPE", "text": search_url},
        {"action": "HOTKEY", "keys": "enter"},
        {"action": "WAIT", "seconds": 2.0},
    ]


def needs_live_ax_selection(app_name: str, command: str) -> bool:
    if app_name not in BROWSER_APPS:
        return False
    command_l = str(command or "").lower().strip()
    return _is_youtube_play_command(command_l) and _is_youtube_live_ax_selection_request(command_l)


def get_iterative_bootstrap_steps(app_name: str, command: str) -> Optional[List[Dict[str, Any]]]:
    if not needs_live_ax_selection(app_name, command):
        return None
    return _youtube_play_seed_steps(command)


def get_live_ax_recovery_steps(app_name: str, command: str) -> Optional[List[Dict[str, Any]]]:
    """Return deterministic fallback steps when live-AX selection becomes unstable."""
    if not needs_live_ax_selection(app_name, command):
        return None
    return _youtube_play_macro(command)


def get_macro_steps(app_name: str, command: str) -> Optional[List[Dict[str, Any]]]:
    """Return deterministic macro steps for globally safe and browser flows."""
    save_as_steps = build_save_as_steps(command, include_payload=True)
    if save_as_steps:
        return save_as_steps

    if app_name not in BROWSER_APPS:
        return None

    command_l = command.lower().strip()

    if "open new tab" in command_l:
        return [{"action": "HOTKEY", "keys": "ctrl+t"}, {"action": "DONE"}]

    if "focus address bar" in command_l:
        return [{"action": "HOTKEY", "keys": "ctrl+l"}, {"action": "DONE"}]

    if "open history" in command_l:
        return [{"action": "HOTKEY", "keys": "ctrl+h"}, {"action": "DONE"}]

    if "open downloads" in command_l:
        return [{"action": "HOTKEY", "keys": "ctrl+j"}, {"action": "DONE"}]

    if "open settings" in command_l:
        settings_url = "brave://settings" if app_name == "Brave" else "chrome://settings"
        return [
            {"action": "HOTKEY", "keys": "ctrl+l"},
            {"action": "TYPE", "text": settings_url},
            {"action": "HOTKEY", "keys": "enter"},
            {"action": "DONE"},
        ]

    if _is_youtube_play_command(command_l):
        if _is_youtube_live_ax_selection_request(command_l):
            # Playback selection should use iterative live-AX loop when requested.
            return None
        return _youtube_play_macro(command)

    if "youtube" in command_l and ("search" in command_l or "find" in command_l):
        return _youtube_search_macro(command)

    return None
