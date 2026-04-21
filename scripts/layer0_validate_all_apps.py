"""
Layer 0 static validation for all configured applications.

Checks, per app:
1) Executable exists
2) Task list exists
3) Cache file exists and parses
4) Exposure-path integrity (missing step references)
5) Parent connectivity integrity (orphan parent references)

Writes:
- results/layer0_static_validation_<timestamp>.json
- results/layer0_static_validation_<timestamp>.md
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]

import sys

sys.path.insert(0, str(PROJECT_ROOT))

from src.harness import config
from src.automation import storage


PROTECTED_APPS = {"VSCode"}


def _analyze_cache(app_name: str) -> Dict[str, Any]:
    cache_path = Path(storage.get_cache_path(app_name))
    report: Dict[str, Any] = {
        "cache_path": str(cache_path),
        "cache_exists": cache_path.exists(),
        "elements_count": 0,
        "broken_exposure_paths": 0,
        "orphan_parent_refs": 0,
        "parse_error": "",
    }

    if not cache_path.exists():
        return report

    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001
        report["parse_error"] = str(e)
        return report

    elements = data.get("elements", {})
    report["elements_count"] = len(elements)

    for _fp, node in elements.items():
        parent_fp = node.get("parent_fingerprint", "")
        if parent_fp and parent_fp not in elements:
            report["orphan_parent_refs"] += 1

        for step in node.get("exposure_path", []):
            step_fp = step.get("fingerprint", "")
            if step_fp and step_fp not in elements:
                report["broken_exposure_paths"] += 1
                break

    return report


def _app_static_status(app_name: str, app_cfg: Dict[str, Any]) -> Dict[str, Any]:
    exe = app_cfg.get("exe", "")
    tasks = config.get_tasks_for_app(app_name)
    cache_report = _analyze_cache(app_name)

    exe_exists = bool(exe) and os.path.exists(exe)
    cache_ok = (
        cache_report["cache_exists"]
        and not cache_report["parse_error"]
        and cache_report["elements_count"] > 0
        and cache_report["broken_exposure_paths"] == 0
    )

    static_ready = exe_exists and len(tasks) > 0 and cache_ok

    return {
        "app_name": app_name,
        "exe": exe,
        "exe_exists": exe_exists,
        "tasks_count": len(tasks),
        "cache": cache_report,
        "static_ready": static_ready,
    }


def _to_markdown(summary: Dict[str, Any]) -> str:
    lines = []
    lines.append("# Layer 0 Static Validation")
    lines.append("")
    lines.append(f"Generated: {summary['generated_at']}")
    lines.append("")
    lines.append("| App | Exe | Tasks | Cache Elements | Broken Paths | Orphans | Static Ready |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")

    for item in summary["apps"]:
        cache = item["cache"]
        lines.append(
            "| {app} | {exe_ok} | {tasks} | {elems} | {broken} | {orphans} | {ready} |".format(
                app=item["app_name"],
                exe_ok="Y" if item["exe_exists"] else "N",
                tasks=item["tasks_count"],
                elems=cache["elements_count"],
                broken=cache["broken_exposure_paths"],
                orphans=cache["orphan_parent_refs"],
                ready="Y" if item["static_ready"] else "N",
            )
        )

    lines.append("")
    lines.append("## Totals")
    lines.append("")
    lines.append(f"- Configured apps: {summary['totals']['configured_apps']}")
    lines.append(f"- Exe present: {summary['totals']['exe_present']}")
    lines.append(f"- Static ready: {summary['totals']['static_ready']}")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Layer 0 static validation for configured apps")
    parser.add_argument(
        "--include-protected",
        action="store_true",
        help="Include protected apps such as VSCode (disabled by default)",
    )
    args = parser.parse_args()

    apps = []
    for app_name, app_cfg in config.APPS.items():
        if not args.include_protected and app_name in PROTECTED_APPS:
            continue
        apps.append(_app_static_status(app_name, app_cfg))

    totals = {
        "configured_apps": len(apps),
        "exe_present": sum(1 for a in apps if a["exe_exists"]),
        "static_ready": sum(1 for a in apps if a["static_ready"]),
    }

    generated_at = datetime.now().isoformat(timespec="seconds")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    summary = {
        "generated_at": generated_at,
        "totals": totals,
        "apps": apps,
    }

    out_dir = PROJECT_ROOT / "results"
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / f"layer0_static_validation_{stamp}.json"
    md_path = out_dir / f"layer0_static_validation_{stamp}.md"

    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    md_path.write_text(_to_markdown(summary), encoding="utf-8")

    print(f"Wrote: {json_path}")
    print(f"Wrote: {md_path}")
    print(f"Configured apps: {totals['configured_apps']}")
    print(f"Exe present: {totals['exe_present']}")
    print(f"Static ready: {totals['static_ready']}")


if __name__ == "__main__":
    main()
