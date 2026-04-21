"""Windows app discovery via registry and Start Menu shortcuts."""

from __future__ import annotations

import json
import os
import re
import subprocess
from typing import Dict, List

try:
    import winreg  # type: ignore
except Exception:  # pragma: no cover - only on non-Windows environments
    winreg = None


def _extract_exe_path(raw_value: str) -> str:
    raw = str(raw_value or "").strip()
    if not raw:
        return ""

    if raw.startswith('"'):
        end = raw.find('"', 1)
        if end > 1:
            candidate = raw[1:end]
        else:
            candidate = raw.strip('"')
    else:
        candidate = raw.split(" ", 1)[0]

    if not candidate.lower().endswith(".exe"):
        match = re.search(r"([A-Za-z]:\\[^\"\r\n,]+?\.exe)", raw, flags=re.IGNORECASE)
        if match:
            candidate = match.group(1)

    candidate = os.path.expandvars(candidate).strip().strip('"')
    if candidate.lower().endswith(".exe") and os.path.exists(candidate):
        return os.path.normpath(candidate)

    return ""


def _is_launchable_app_exe(exe_path: str, app_name: str = "") -> bool:
    path = str(exe_path or "").strip()
    if not path:
        return False

    base = os.path.basename(path).lower()
    name = str(app_name or "").strip().lower()

    blocked_tokens = [
        "uninstall",
        "unins",
        "setup",
        "installer",
        "repair",
    ]
    if any(token in base for token in blocked_tokens):
        return False
    if any(token in name for token in blocked_tokens):
        return False

    return True


def _registry_discovery() -> List[Dict[str, str]]:
    if winreg is None:
        return []

    roots = [
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths"),
    ]

    uninstall_roots = [
        (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    ]

    out: List[Dict[str, str]] = []

    for root, path in roots:
        try:
            with winreg.OpenKey(root, path) as key:
                i = 0
                while True:
                    try:
                        subkey_name = winreg.EnumKey(key, i)
                        i += 1
                    except OSError:
                        break

                    app_name = os.path.splitext(subkey_name)[0]
                    if not app_name:
                        continue

                    try:
                        with winreg.OpenKey(key, subkey_name) as app_key:
                            try:
                                value, _ = winreg.QueryValueEx(app_key, None)
                            except OSError:
                                value = ""
                    except OSError:
                        continue

                    exe = _extract_exe_path(str(value))
                    if exe and _is_launchable_app_exe(exe, app_name):
                        out.append({"name": app_name, "exe": exe, "source": "registry_app_paths"})
        except OSError:
            continue

    for root, path in uninstall_roots:
        try:
            with winreg.OpenKey(root, path) as key:
                i = 0
                while True:
                    try:
                        subkey_name = winreg.EnumKey(key, i)
                        i += 1
                    except OSError:
                        break

                    try:
                        with winreg.OpenKey(key, subkey_name) as app_key:
                            try:
                                display_name, _ = winreg.QueryValueEx(app_key, "DisplayName")
                            except OSError:
                                display_name = ""
                            try:
                                display_icon, _ = winreg.QueryValueEx(app_key, "DisplayIcon")
                            except OSError:
                                display_icon = ""
                    except OSError:
                        continue

                    name = str(display_name or "").strip()
                    if not name:
                        continue

                    exe = _extract_exe_path(str(display_icon))
                    if exe and _is_launchable_app_exe(exe, name):
                        out.append({"name": name, "exe": exe, "source": "registry_uninstall"})
        except OSError:
            continue

    return out


def _start_menu_discovery() -> List[Dict[str, str]]:
    # Uses WScript.Shell COM from PowerShell to resolve .lnk target paths.
    ps_script = r"""
$ErrorActionPreference = 'SilentlyContinue'
$paths = @(
  "$env:ProgramData\Microsoft\Windows\Start Menu\Programs",
  "$env:APPDATA\Microsoft\Windows\Start Menu\Programs"
)
$shell = New-Object -ComObject WScript.Shell
$items = foreach ($p in $paths) {
  if (Test-Path $p) { Get-ChildItem -Path $p -Filter *.lnk -Recurse -ErrorAction SilentlyContinue }
}
$out = foreach ($i in $items) {
  try {
    $s = $shell.CreateShortcut($i.FullName)
    $t = $s.TargetPath
    if ($t -and $t.ToLower().EndsWith('.exe')) {
      [PSCustomObject]@{ name = $i.BaseName; exe = $t; source = 'start_menu' }
    }
  } catch {}
}
$out | ConvertTo-Json -Compress
"""

    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            capture_output=True,
            text=True,
            timeout=25,
            check=False,
        )
    except Exception:
        return []

    raw = (proc.stdout or "").strip()
    if not raw:
        return []

    try:
        parsed = json.loads(raw)
    except Exception:
        return []

    rows = parsed if isinstance(parsed, list) else [parsed]
    out: List[Dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name", "")).strip()
        exe = _extract_exe_path(str(row.get("exe", "")))
        if name and exe and _is_launchable_app_exe(exe, name):
            out.append({"name": name, "exe": exe, "source": "start_menu"})
    return out


def discover_apps(max_results: int = 400) -> List[Dict[str, str]]:
    """Discover locally installed desktop apps on Windows.

    Returns list entries in shape:
    {"name": str, "exe": str, "source": str}
    """
    if os.name != "nt":
        return []

    candidates = []
    candidates.extend(_registry_discovery())
    candidates.extend(_start_menu_discovery())

    source_rank = {
        "registry_app_paths": 3,
        "start_menu": 2,
        "registry_uninstall": 1,
    }

    deduped: Dict[str, Dict[str, str]] = {}
    for item in candidates:
        name = str(item.get("name", "")).strip()
        exe = str(item.get("exe", "")).strip()
        source = str(item.get("source", "")).strip() or "unknown"
        if not name or not exe:
            continue
        if not os.path.exists(exe):
            continue

        key = exe.lower()
        if key not in deduped:
            deduped[key] = {"name": name, "exe": exe, "source": source}
            continue

        old_source = str(deduped[key].get("source", ""))
        if source_rank.get(source, 0) > source_rank.get(old_source, 0):
            deduped[key] = {"name": name, "exe": exe, "source": source}

    ordered = sorted(deduped.values(), key=lambda x: (x["name"].lower(), x["exe"].lower()))
    return ordered[: max(1, int(max_results))]
