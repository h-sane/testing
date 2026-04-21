# harness/config.py
"""
Application and task configuration for the hybrid GUI automation harness.
Defines target apps, executable paths, and tasks to execute.
Includes numeric normalization for calculator-style tasks.
"""
import json
import os
import re
from dotenv import load_dotenv

# MANDATORY: Load environment variables at process start
load_dotenv()

# VALIDATION CHECK
if not os.getenv("GEMINI_API_KEY") and not os.getenv("HF_TOKEN"):
    print("[CONFIG WARNING] No VLM API keys detected in environment.")

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
USER_CONFIG_DIR = os.path.join(PROJECT_ROOT, ".config")
USER_APPS_PATH = os.path.join(USER_CONFIG_DIR, "user_apps.json")

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
    "Windsurf": {
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
    "Windsurf": {
        "exe": r"C:\Users\husai\AppData\Local\Programs\Windsurf\Windsurf.exe",
        "title_re": ".*- Windsurf$",
        "electron": True
    },
    "WhatsApp": {
        "exe": r"C:\Users\husai\AppData\Local\WhatsApp\WhatsApp.exe",
        "title_re": ".*WhatsApp.*"
    },
    "Spotify": {
        "exe": r"C:\Users\husai\AppData\Roaming\Spotify\Spotify.exe",
        "title_re": "^Spotify.*",
        "electron": True
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
        "Add New Tab",
        "Settings",
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
    "Windsurf": [
        "open file menu",
        "open edit menu",
        "open view menu",
        "toggle sidebar",
        "open command palette",
        "new file",
        "open folder",
        "save file",
        "save all",
        "open extensions",
        "open settings",
        "toggle terminal"
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
        "open home",
        "open search",
        "open library",
        "open queue",
        "play",
        "pause",
        "next track",
        "previous track",
        "like song",
        "shuffle",
        "repeat",
        "volume up",
        "volume down",
        "mute",
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


def _load_user_apps_config() -> dict:
    """Load user-registered app overrides from disk."""
    if not os.path.exists(USER_APPS_PATH):
        return {"apps": {}, "tasks": {}, "keyboard_fallbacks": {}}

    try:
        with open(USER_APPS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"apps": {}, "tasks": {}, "keyboard_fallbacks": {}}
        return {
            "apps": data.get("apps", {}) if isinstance(data.get("apps", {}), dict) else {},
            "tasks": data.get("tasks", {}) if isinstance(data.get("tasks", {}), dict) else {},
            "keyboard_fallbacks": data.get("keyboard_fallbacks", {}) if isinstance(data.get("keyboard_fallbacks", {}), dict) else {},
        }
    except Exception as e:
        print(f"[CONFIG WARNING] Failed to read user app config: {e}")
        return {"apps": {}, "tasks": {}, "keyboard_fallbacks": {}}


def _save_user_apps_config(data: dict) -> bool:
    """Persist user app overrides to disk."""
    try:
        os.makedirs(USER_CONFIG_DIR, exist_ok=True)
        with open(USER_APPS_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        print(f"[CONFIG WARNING] Failed to save user app config: {e}")
        return False


def _apply_user_overrides() -> None:
    """Merge user-registered apps/tasks into in-memory config maps."""
    user = _load_user_apps_config()

    for app_name, app_cfg in user.get("apps", {}).items():
        if isinstance(app_cfg, dict):
            APPS[app_name] = app_cfg

    for app_name, task_list in user.get("tasks", {}).items():
        if isinstance(task_list, list):
            TASKS[app_name] = task_list

    for app_name, fallback_map in user.get("keyboard_fallbacks", {}).items():
        if isinstance(fallback_map, dict):
            KEYBOARD_FALLBACKS[app_name] = fallback_map


def register_app(
    app_name: str,
    exe: str,
    title_re: str,
    tasks: list | None = None,
    keyboard_fallbacks: dict | None = None,
    electron: bool = False,
    persist: bool = True,
) -> bool:
    """
    Register or update an app entry.

    This updates in-memory APPS/TASKS maps immediately and optionally
    persists user-defined entries to .config/user_apps.json.
    """
    if not app_name or not isinstance(app_name, str):
        return False

    app_name = app_name.strip()
    if not app_name:
        return False

    app_cfg = {
        "exe": exe,
        "title_re": title_re,
    }
    if electron:
        app_cfg["electron"] = True

    APPS[app_name] = app_cfg

    if tasks is not None:
        TASKS[app_name] = list(tasks)
    elif app_name not in TASKS:
        TASKS[app_name] = []

    if keyboard_fallbacks is not None:
        KEYBOARD_FALLBACKS[app_name] = dict(keyboard_fallbacks)
    elif app_name not in KEYBOARD_FALLBACKS:
        KEYBOARD_FALLBACKS[app_name] = {}

    if not persist:
        return True

    user = _load_user_apps_config()
    user.setdefault("apps", {})[app_name] = app_cfg
    user.setdefault("tasks", {})[app_name] = TASKS.get(app_name, [])

    if app_name in KEYBOARD_FALLBACKS:
        user.setdefault("keyboard_fallbacks", {})[app_name] = KEYBOARD_FALLBACKS.get(app_name, {})

    return _save_user_apps_config(user)


def list_user_registered_apps() -> list:
    """Return only user-registered app names from persisted config."""
    user = _load_user_apps_config()
    return sorted(user.get("apps", {}).keys())


_apply_user_overrides()

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
