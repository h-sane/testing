"""Layer 1 all-app smoke: HostAgent + ExecutionAgent with no-vision default."""

import argparse
import datetime
import json
import os
import sys
from typing import Dict, List

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from sara.config import PROTECTED_APPS
from sara.host_agent import HostAgent
from src.harness import config


def _format_markdown(results: List[Dict], run_name: str) -> str:
    total = len(results)
    passed = sum(1 for r in results if r.get("success"))
    failed = total - passed

    lines = [
        f"# Layer 1 Agentic Smoke Report - {run_name}",
        "",
        f"- Total apps: {total}",
        f"- Passed: {passed}",
        f"- Failed: {failed}",
        "",
        "| App | Command | Success | Steps | Replans | Error |",
        "|---|---|---|---:|---:|---|",
    ]

    for r in results:
        app = r.get("app_name", "")
        command = str(r.get("command", "")).replace("|", " /")
        success = "YES" if r.get("success") else "NO"
        steps = len(r.get("steps", []))
        replans = r.get("replan_rounds_used", 0)
        error = str(r.get("error", "")).replace("|", " /")
        lines.append(f"| {app} | {command} | {success} | {steps} | {replans} | {error} |")

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Layer 1 agentic smoke test across apps")
    parser.add_argument("--apps", nargs="*", help="Optional app list")
    parser.add_argument(
        "--all-apps",
        action="store_true",
        help="Run against all available apps (disabled by default for low-resource safety)",
    )
    parser.add_argument("--include-vscode", action="store_true", help="Allow protected apps")
    parser.add_argument("--use-vision", action="store_true", help="Enable vision fallback")
    parser.add_argument("--trace-root", default="runs/layer1_agentic_smoke", help="Trace output directory")
    args = parser.parse_args()

    available = config.get_available_apps()
    if args.apps:
        apps = args.apps
    elif args.all_apps:
        apps = available
    else:
        # Safe default for low-resource machines: run one app unless explicitly expanded.
        apps = ["Notepad"] if "Notepad" in available else (available[:1] if available else [])
    apps = [a for a in apps if a in available]

    if not args.include_vscode:
        apps = [a for a in apps if a not in PROTECTED_APPS]

    if not apps:
        print("[layer1] No apps available for smoke run")
        return 1

    print(f"[layer1] Apps: {apps}")
    print(f"[layer1] Vision: {'enabled' if args.use_vision else 'disabled'}")

    agent = HostAgent(use_vision=args.use_vision, trace_root=args.trace_root)
    results: List[Dict] = []

    for app in apps:
        tasks = config.get_tasks_for_app(app)
        command = tasks[0] if tasks else "open"
        print(f"\n[layer1] {app}: {command}")

        result = agent.execute(
            command=command,
            target_app=app,
            allow_protected=args.include_vscode,
        )

        success = "PASS" if result.get("success") else "FAIL"
        print(f"[layer1] {app}: {success}")
        if result.get("error"):
            print(f"[layer1] error: {result['error']}")

        results.append(result)

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    run_name = f"layer1_agentic_smoke_{ts}"
    os.makedirs("results", exist_ok=True)

    json_path = os.path.join("results", f"{run_name}.json")
    md_path = os.path.join("results", f"{run_name}.md")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    with open(md_path, "w", encoding="utf-8") as f:
        f.write(_format_markdown(results, run_name))

    print("\n[layer1] COMPLETE")
    print(f"[layer1] JSON: {json_path}")
    print(f"[layer1] MD:   {md_path}")

    failed = sum(1 for r in results if not r.get("success"))
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
