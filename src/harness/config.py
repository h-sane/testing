# harness/config.py
"""
Application and task configuration for the hybrid GUI automation harness.
Defines target apps, executable paths, and tasks to execute.
Includes numeric normalization for calculator-style tasks.
"""

import os
import re
from dotenv import load_dotenv

# MANDATORY: Load environment variables at process start
load_dotenv()

# VALIDATION CHECK
if not os.getenv("GEMINI_API_KEY") and not os.getenv("HF_TOKEN"):
    print("[CONFIG WARNING] No VLM API keys detected in environment.")

# =============================================================================
# KEYBOARD FALLBACK MAPPINGS
# Alt+key shortcuts for menu actions when AX fails
# =============================================================================

KEYBOARD_FALLBACKS = {
    "Notepad": {
        "help": "%H",       # Alt+H for Help menu
        "file": "%F",       # Alt+F for File menu
        "edit": "%E",       # Alt+E for Edit menu
        "format": "%O",     # Alt+O for Format menu
        "view": "%V",       # Alt+V for View menu
    },
    "Calculator": {},
    "Chrome": {},
    "VSCode": {
        "file": "%F",
        "edit": "%E",
        "view": "%V",
        "help": "%H",
    },
}

# =============================================================================
# TARGET APPLICATIONS
# =============================================================================

APPS = {
    "Notepad": {
        "exe": r"C:\Windows\notepad.exe",
        "title_re": ".* - Notepad$"
    },
    "Calculator": {
        "exe": r"C:\Windows\System32\calc.exe",
        "title_re": ".*Calculator.*"
    },
    "Chrome": {
        "exe": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        "title_re": ".*Google Chrome.*"
    },
    "VSCode": {
        "exe": r"C:\Users\husai\AppData\Local\Programs\Microsoft VS Code\Code.exe",
        "title_re": ".*Visual Studio Code.*"
    },
    "WhatsApp": {
        "exe": r"C:\Users\husai\AppData\Local\WhatsApp\WhatsApp.exe",
        "title_re": ".*WhatsApp.*"
    },
    "Spotify": {
        "exe": r"C:\Users\husai\AppData\Roaming\Spotify\Spotify.exe",
        "title_re": ".*Spotify.*"
    },
    "Zoom": {
        "exe": r"C:\Users\husai\AppData\Roaming\Zoom\bin\Zoom.exe",
        "title_re": ".*Zoom.*"
    },
    "Excel": {
        "exe": r"C:\Program Files\Microsoft Office\root\Office16\EXCEL.EXE",
        "title_re": ".*Excel.*"
    },
    "Telegram": {
        "exe": r"C:\Users\husai\AppData\Roaming\Telegram Desktop\Telegram.exe",
        "title_re": ".*Telegram.*"
    },
    "Brave": {
        "exe": r"C:\Users\husai\AppData\Local\BraveSoftware\Brave-Browser\Application\brave.exe",
        "title_re": ".*Brave.*"
    }
}

# =============================================================================
# TASKS PER APPLICATION
# Calculator tasks use actual button names (One, Two, Plus, etc.)
# =============================================================================

TASKS = {
    "Notepad": [
        "File",
        "Edit",
        "View",
        "Settings",
        "New tab",
        "Open",
        "Save",
        "Save as",
        "Print",
        "Undo",
        "Cut",
        "Copy",
        "Paste",
        "Find",
        "Replace",
        "Go to",
        "Select all",
        "Time/Date",
        "Word wrap",
        "Add New Tab"
    ],
    "Calculator": [
        # Using actual Windows Calculator button names
        "click One",
        "click Two",
        "click Three",
        "click Four",
        "click Five",
        "click Six",
        "click Seven",
        "click Eight",
        "click Nine",
        "click Zero",
        "click Plus",
        "click Minus",
        "click Multiply by",
        "click Divide by",
        "click Equals",
        "click Clear",
        "click Backspace",
        "click Percent",
        "click Square root",
        "click Memory recall"
    ],
    "Chrome": [
        "open new tab",
        "close tab",
        "open settings",
        "open history",
        "open downloads",
        "open bookmarks",
        "focus address bar",
        "go back",
        "go forward",
        "refresh page",
        "zoom in",
        "zoom out",
        "open developer tools",
        "open incognito window",
        "print page"
    ],
    "VSCode": [
        "open file menu",
        "open edit menu",
        "open view menu",
        "open go menu",
        "open run menu",
        "open terminal menu",
        "open help menu",
        "new file",
        "open file",
        "save file",
        "save all",
        "open folder",
        "open settings",
        "open extensions",
        "toggle sidebar"
    ],
    "WhatsApp": [
        "open new chat",
        "open settings",
        "search chats",
        "open profile",
        "mute notifications",
        "archive chat",
        "delete chat",
        "pin chat",
        "mark as unread",
        "open status"
    ],
    "Spotify": [
        "play",
        "pause",
        "next track",
        "previous track",
        "shuffle",
        "repeat",
        "volume up",
        "volume down",
        "mute",
        "open search",
        "open library",
        "open home",
        "open queue",
        "like song",
        "open settings"
    ],
    "Zoom": [
        "join meeting",
        "start meeting",
        "schedule meeting",
        "open settings",
        "share screen",
        "mute audio",
        "stop video",
        "open chat",
        "open participants",
        "leave meeting"
    ],
    "Excel": [
        "open file menu",
        "new workbook",
        "open workbook",
        "save workbook",
        "save as",
        "print",
        "undo",
        "redo",
        "cut",
        "copy",
        "paste",
        "insert row",
        "insert column",
        "delete row",
        "delete column"
    ],
    "Telegram": [
        "open new chat",
        "search",
        "open settings",
        "create group",
        "create channel",
        "open saved messages",
        "open contacts",
        "mute chat",
        "pin chat",
        "archive chat"
    ],
    "Brave": [
        "open new tab",
        "close tab",
        "open settings",
        "open history",
        "open downloads",
        "open bookmarks",
        "focus address bar",
        "go back",
        "go forward",
        "refresh page",
        "open brave rewards",
        "open brave shields",
        "open private window"
    ]
}

# =============================================================================
# UTILITIES
# =============================================================================

def get_available_apps() -> list:
    """Return list of apps whose exe exists on this system."""
    available = []
    for name, config in APPS.items():
        if os.path.exists(config["exe"]):
            available.append(name)
    return available


def get_tasks_for_app(app_name: str) -> list:
    """Get task list for an app."""
    return TASKS.get(app_name, [])


def get_app_config(app_name: str) -> dict:
    """Get config dict for an app."""
    return APPS.get(app_name, {})
