"""Executable inventory helpers for crawler onboarding."""

from __future__ import annotations

import ctypes
import os
from pathlib import Path
from typing import Dict, List

from src.harness.windows_app_discovery import discover_apps


_FIXED_DRIVE_TYPE = 3
_BLOCKED_DIR_NAMES = {
    "$Recycle.Bin",
    "System Volume Information",
}


def _iter_fixed_drives() -> List[str]:
    if os.name != "nt":
        return []

    drives: List[str] = []
    bitmask = int(ctypes.windll.kernel32.GetLogicalDrives())
    for idx in range(26):
        if not (bitmask & (1 << idx)):
            continue
        letter = chr(ord("A") + idx)
        drive = f"{letter}:\\"
        try:
            dtype = int(ctypes.windll.kernel32.GetDriveTypeW(ctypes.c_wchar_p(drive)))
        except Exception:
            continue
        if dtype == _FIXED_DRIVE_TYPE:
            drives.append(drive)

    return sorted(drives)


def _scan_drive_for_executables(drive_root: str, max_results: int, seen: Dict[str, Dict[str, str]]) -> None:
    def _on_error(_exc):
        return None

    for root, dirnames, filenames in os.walk(drive_root, topdown=True, onerror=_on_error):
        # Skip folders that are frequently inaccessible and cause noisy scans.
        dirnames[:] = [
            name
            for name in dirnames
            if name not in _BLOCKED_DIR_NAMES and not name.startswith("$")
        ]

        for filename in filenames:
            if not filename.lower().endswith(".exe"):
                continue

            full_path = os.path.normpath(os.path.join(root, filename))
            key = full_path.lower()
            if key in seen:
                continue
            if not os.path.exists(full_path):
                continue

            stem = Path(full_path).stem.strip() or filename
            seen[key] = {
                "name": stem,
                "exe": full_path,
                "source": "filesystem_scan",
            }

            if max_results > 0 and len(seen) >= max_results:
                return


def discover_all_executables(max_results: int = 0) -> List[Dict[str, str]]:
    """Return executable inventory for crawler onboarding.

    The inventory is composed of:
    - Installed app discovery (registry/start menu)
    - Full fixed-drive filesystem scan for *.exe

    Args:
        max_results: 0 for no cap. Positive values cap output size.
    """
    cap = int(max_results)
    seen: Dict[str, Dict[str, str]] = {}

    # Seed with launchable installed apps for better naming/source hints.
    seed_limit = cap if cap > 0 else 10000
    for row in discover_apps(max_results=seed_limit):
        exe = os.path.normpath(str(row.get("exe", "")).strip())
        if not exe:
            continue
        if not os.path.exists(exe):
            continue
        key = exe.lower()
        if key in seen:
            continue
        seen[key] = {
            "name": str(row.get("name", "")).strip() or Path(exe).stem,
            "exe": exe,
            "source": str(row.get("source", "installed_app")) or "installed_app",
        }
        if cap > 0 and len(seen) >= cap:
            break

    if cap <= 0 or len(seen) < cap:
        for drive in _iter_fixed_drives():
            _scan_drive_for_executables(drive, cap, seen)
            if cap > 0 and len(seen) >= cap:
                break

    rows = sorted(
        seen.values(),
        key=lambda item: (
            str(item.get("name", "")).lower(),
            str(item.get("exe", "")).lower(),
        ),
    )

    if cap > 0:
        return rows[:cap]
    return rows
