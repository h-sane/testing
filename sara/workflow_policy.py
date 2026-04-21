"""Global workflow policies for fragile cross-app UI sequences."""

from __future__ import annotations

import re
from typing import Any, Dict, List

_SAVE_AS_RE = re.compile(r"\bsave(?:\s+it)?\s+as\b", flags=re.IGNORECASE)
_SAVE_AS_CAPTURE_RE = re.compile(r"\bsave(?:\s+it)?\s+as\s+(.+)$", flags=re.IGNORECASE)

_SAVE_DIALOG_HOTKEYS = {
    "ctrl+shift+s",
    "ctrl+s",
    "f12",
    "alt+n",
    "alt+s",
    "enter",
    "tab",
}

_SAVE_DIALOG_CLICK_TARGETS = {
    "file name",
    "file name edit",
    "filename",
    "save",
    "save as",
}

_PERSISTENT_ACTION_RE = re.compile(r"\b(play|stream|watch|listen)\b", flags=re.IGNORECASE)
_PERSISTENT_MEDIA_TARGET_RE = re.compile(
    r"\b(song|music|playlist|video|podcast|youtube|spotify|netflix|movie|episode|audio|radio)\b",
    flags=re.IGNORECASE,
)
_KEEP_OPEN_HINT_RE = re.compile(r"\b(keep|leave)\b.{0,20}\b(open|running)\b", flags=re.IGNORECASE)
_BROWSER_APPS = {"chrome", "brave", "edge", "firefox", "browser"}
_BROWSER_NAV_HOTKEYS = {"ctrl+l", "enter"}
_URL_LIKE_RE = re.compile(r"^(?:https?://|www\.)\S+$", flags=re.IGNORECASE)


def is_save_as_intent(command: str) -> bool:
    return bool(_SAVE_AS_RE.search(str(command or "").strip()))


def looks_like_text_entry_intent(command: str) -> bool:
    text = str(command or "").lower()
    # Keep a strict word-boundary set to avoid accidental matches on app names.
    return bool(re.search(r"\b(write|type|draft|compose|letter|message|paragraph|text)\b", text))


def _looks_like_app_qualifier(value: str) -> bool:
    candidate = str(value or "").strip().strip(".,!?;:")
    if not candidate:
        return False
    if any(char in candidate for char in "\\/:"):
        return False

    tokens = re.findall(r"[A-Za-z0-9]+", candidate)
    if not tokens or len(tokens) > 4:
        return False

    return True


def _strip_trailing_app_qualifier(value: str) -> str:
    text = str(value or "").strip()
    if not text:
        return ""

    lowered = text.lower()
    for marker in (" in ", " on "):
        idx = lowered.rfind(marker)
        if idx <= 0:
            continue
        suffix = text[idx + len(marker) :].strip()
        if _looks_like_app_qualifier(suffix):
            return text[:idx].strip()

    return text


def extract_write_payload(command: str, default: str = "") -> str:
    text = str(command or "").strip()
    if not text:
        return default

    patterns = [
        r"\bsaying\s+(.+)$",
        r"\bthat says\s+(.+)$",
        r"\bwith text\s+(.+)$",
        r"\b(?:write|type|draft|compose)\b\s+(.+)$",
    ]

    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue

        candidate = match.group(1).strip().strip("\"'")
        candidate = _SAVE_AS_RE.split(candidate, maxsplit=1)[0].strip(" ,")
        candidate = _strip_trailing_app_qualifier(candidate)
        if candidate:
            return candidate

    return default


def extract_save_as_filename(command: str) -> str:
    text = str(command or "").strip()
    if not text:
        return ""

    match = _SAVE_AS_CAPTURE_RE.search(text)
    if not match:
        return ""

    candidate = match.group(1).strip()
    if "," in candidate:
        candidate = candidate.split(",", 1)[0].strip()

    candidate = _strip_trailing_app_qualifier(candidate)
    candidate = candidate.strip().strip("\"'").rstrip(".!?;:")
    return candidate


def normalize_hotkey(keys: str) -> str:
    parts = [part.strip().lower() for part in str(keys or "").split("+") if part.strip()]
    return "+".join(parts)


def build_save_as_steps(command: str, include_payload: bool = True) -> List[Dict[str, Any]]:
    if not is_save_as_intent(command):
        return []

    steps: List[Dict[str, Any]] = []

    if include_payload and looks_like_text_entry_intent(command):
        payload = extract_write_payload(command, default="")
        if payload:
            steps.append({"action": "TYPE", "text": payload})

    filename = extract_save_as_filename(command)

    # Dialog-first deterministic sequence: open save-as, focus filename field, submit.
    steps.extend(
        [
            {"action": "HOTKEY", "keys": "ctrl+shift+s"},
            {"action": "WAIT", "seconds": 0.6},
        ]
    )

    if filename:
        steps.extend(
            [
                {"action": "HOTKEY", "keys": "alt+n"},
                {"action": "TYPE", "text": filename},
                {"action": "HOTKEY", "keys": "alt+s"},
                {"action": "WAIT", "seconds": 0.4},
            ]
        )

    steps.append({"action": "DONE"})
    return steps


def should_allow_save_dialog_soft_verification(
    action: Dict[str, Any],
    command: str,
    requested_filename: str = "",
) -> bool:
    if not is_save_as_intent(command):
        return False

    action_type = str(action.get("action_type") or action.get("action") or "").strip().upper()
    if action_type == "HOTKEY":
        hotkey = normalize_hotkey(str(action.get("keys", "")))
        return hotkey in _SAVE_DIALOG_HOTKEYS

    if action_type == "CLICK":
        target = str(action.get("target", "")).strip().lower().rstrip(":")
        target = re.sub(r"\s+", " ", target)
        return target in _SAVE_DIALOG_CLICK_TARGETS

    if action_type == "TYPE":
        expected = requested_filename or extract_save_as_filename(command)
        if not expected:
            return False
        typed = str(action.get("text", "")).strip().strip("\"'")
        return typed.lower() == expected.lower()

    return False


def should_keep_app_open_after_execution(command: str) -> bool:
    text = str(command or "").strip()
    if not text:
        return False

    if _KEEP_OPEN_HINT_RE.search(text):
        return True

    if not _PERSISTENT_ACTION_RE.search(text):
        return False

    return bool(_PERSISTENT_MEDIA_TARGET_RE.search(text))


def should_allow_browser_navigation_soft_verification(
    action: Dict[str, Any],
    command: str,
    app_name: str = "",
) -> bool:
    command_l = str(command or "").lower().strip()
    app_l = str(app_name or "").lower().strip()

    browser_context = app_l in _BROWSER_APPS or any(
        marker in command_l
        for marker in (
            "youtube",
            "browser",
            "chrome",
            "brave",
            "edge",
            "firefox",
            "http://",
            "https://",
            "www.",
            "search ",
        )
    )
    if not browser_context:
        return False

    action_type = str(action.get("action_type") or action.get("action") or "").strip().upper()
    if action_type == "HOTKEY":
        hotkey = normalize_hotkey(str(action.get("keys", "")))
        return hotkey in _BROWSER_NAV_HOTKEYS

    if action_type == "TYPE":
        typed = str(action.get("text", "")).strip()
        if not typed:
            return False
        typed_l = typed.lower()
        return bool(_URL_LIKE_RE.match(typed)) or "youtube.com" in typed_l or "google.com/search" in typed_l

    return False
