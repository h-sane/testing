"""Register a new app and optionally run discovery/probing.

Examples:
  python scripts/register_and_probe_app.py --app Slack --exe "C:\\Users\\husai\\AppData\\Local\\slack\\slack.exe" --title-re ".*Slack.*" --discover
  python scripts/register_and_probe_app.py --app Word --exe "C:\\Program Files\\Microsoft Office\\root\\Office16\\WINWORD.EXE" --title-re ".*Word.*" --task "open file menu" --task "new document" --discover --discover-time 240
"""

from __future__ import annotations

import argparse
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.harness import config
from src.harness.main import run_discovery


def _validate_inputs(app: str, exe: str, title_re: str) -> None:
    if not app.strip():
        raise ValueError("--app is required")
    if not exe.strip():
        raise ValueError("--exe is required")
    if not title_re.strip():
        raise ValueError("--title-re is required")
    try:
        re.compile(title_re)
    except re.error as exc:
        raise ValueError(f"Invalid --title-re regex: {exc}") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Register and optionally probe a new app")
    parser.add_argument("--app", required=True, help="Display name for the app, e.g. Slack")
    parser.add_argument("--exe", required=True, help="Full executable path")
    parser.add_argument("--title-re", required=True, help="Window title regex")
    parser.add_argument(
        "--task",
        action="append",
        default=[],
        help="Seed task for this app (repeatable)",
    )
    parser.add_argument(
        "--menu-fallback",
        action="append",
        default=[],
        help="Keyboard fallback mapping in key=value format, e.g. file=%%F",
    )
    parser.add_argument(
        "--electron",
        action="store_true",
        help="Mark app as Electron/Chromium style",
    )
    parser.add_argument(
        "--discover",
        action="store_true",
        help="Run discovery immediately after registration",
    )
    parser.add_argument(
        "--discover-time",
        type=int,
        default=180,
        help="Discovery time budget in seconds",
    )
    args = parser.parse_args()

    try:
        _validate_inputs(args.app, args.exe, args.title_re)
    except ValueError as exc:
        print(f"[register] {exc}")
        return 2

    if not os.path.exists(args.exe):
        print(f"[register] Warning: executable path does not exist: {args.exe}")

    fallbacks = {}
    for raw in args.menu_fallback:
        if "=" not in raw:
            print(f"[register] Ignoring invalid --menu-fallback '{raw}' (expected key=value)")
            continue
        k, v = raw.split("=", 1)
        k = k.strip().lower()
        v = v.strip()
        if not k or not v:
            continue
        fallbacks[k] = v

    ok = config.register_app(
        app_name=args.app.strip(),
        exe=args.exe.strip(),
        title_re=args.title_re.strip(),
        tasks=list(args.task),
        keyboard_fallbacks=fallbacks,
        electron=bool(args.electron),
        persist=True,
    )

    if not ok:
        print("[register] Failed to register app")
        return 1

    print(f"[register] Registered app: {args.app}")
    print("[register] Saved to .config/user_apps.json")

    if args.discover:
        print(f"[probe] Starting discovery for {args.app} (max_time={args.discover_time}s)")
        run_discovery(apps=[args.app], max_time=int(args.discover_time))
        print(f"[probe] Done. Inspect .cache/{args.app.lower()}.json and experiments/crawl_logs/")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
