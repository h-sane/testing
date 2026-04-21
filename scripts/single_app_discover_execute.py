"""Safe single-app pipeline: discover -> cache coverage -> targeted execution.

Designed for low-resource machines:
- Runs one app at a time
- Ensures app cleanup between phases
- Vision fallback disabled by default
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from sara import path_policy
from src.automation import matcher, prober, storage
from src.harness import config
from src.harness.app_controller import create_controller
from src.harness.main import run_all

PROTECTED_APPS = {"VSCode"}


def _register_app_if_needed(
    app_name: str,
    app_cfg: Dict[str, Any],
    register_if_missing: bool,
    exe: str,
    title_re: str,
    electron: bool,
    tasks: List[str],
) -> Dict[str, Any] | None:
    if app_cfg:
        return app_cfg

    if not register_if_missing:
        return None

    if not exe or not title_re:
        raise ValueError("--exe and --title-re are required when --register-if-missing is used")

    registered = config.register_app(
        app_name=app_name,
        exe=exe,
        title_re=title_re,
        tasks=tasks,
        electron=electron,
        persist=True,
    )
    if not registered:
        raise RuntimeError(f"Failed to persist app registration for {app_name}")

    return config.get_app_config(app_name)


def _analyze_cache(app_name: str, task_match_threshold: float = 0.65) -> Dict[str, Any]:
    cache_path = Path(storage.get_cache_path(app_name))
    report: Dict[str, Any] = {
        "cache_path": str(cache_path),
        "cache_exists": cache_path.exists(),
        "elements_count": 0,
        "elements_with_exposure_path": 0,
        "max_exposure_path_length": 0,
        "avg_exposure_path_length": 0.0,
        "broken_exposure_paths": 0,
        "orphan_parent_refs": 0,
        "task_match_threshold": task_match_threshold,
        "task_match_hits": 0,
        "task_match_total": 0,
        "task_match_ratio": 0.0,
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

    path_lengths: List[int] = []

    for _fp, node in elements.items():
        parent_fp = node.get("parent_fingerprint", "")
        if parent_fp and parent_fp not in elements:
            report["orphan_parent_refs"] += 1

        exposure_path = node.get("exposure_path", [])
        if exposure_path:
            report["elements_with_exposure_path"] += 1
            path_lengths.append(len(exposure_path))

        for step in exposure_path:
            step_fp = step.get("fingerprint", "")
            if step_fp and step_fp not in elements:
                report["broken_exposure_paths"] += 1
                break

    if path_lengths:
        report["max_exposure_path_length"] = max(path_lengths)
        report["avg_exposure_path_length"] = round(sum(path_lengths) / len(path_lengths), 3)

    tasks = config.get_tasks_for_app(app_name)
    report["task_match_total"] = len(tasks)
    if tasks:
        hits = 0
        for task in tasks:
            cached = matcher.find_cached_element(app_name, task, min_confidence=task_match_threshold)
            if cached:
                hits += 1
        report["task_match_hits"] = hits
        report["task_match_ratio"] = round(hits / len(tasks), 4)

    return report


def _find_latest_run_dir(output_dir: Path) -> Path | None:
    run_dirs = [p for p in output_dir.glob("run_*") if p.is_dir()]
    if not run_dirs:
        return None
    run_dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return run_dirs[0]


def _cleanup_app(app_name: str) -> None:
    app_cfg = config.get_app_config(app_name)
    controller = create_controller(app_name, app_cfg)
    controller.pre_start_cleanup()


def _discover_single_app(
    app_name: str,
    max_time: int,
    clear_cache: bool,
    attach_only: bool,
    human_ready: bool,
    keep_app_open: bool,
) -> Dict[str, Any]:
    app_cfg = config.get_app_config(app_name)
    controller = create_controller(app_name, app_cfg)
    crawler = prober.UIProber(max_time=max_time)

    discovered = 0
    error = ""

    try:
        if attach_only:
            if not controller.connect(timeout=15):
                error = f"Could not attach/connect to already-open {app_name}"
                return {"discovered": 0, "error": error, "probe_log": crawler.log_path}
        elif not controller.start_or_connect():
            error = f"Could not start/connect to {app_name}"
            return {"discovered": 0, "error": error, "probe_log": crawler.log_path}

        window = controller.get_window()
        if not window:
            error = f"Window unavailable for {app_name}"
            return {"discovered": 0, "error": error, "probe_log": crawler.log_path}

        if human_ready:
            print(f"[single-app] Human-in-loop ready gate for {app_name}")
            print("[single-app] Ensure app is stable (no startup spinner/popups), then press Enter to continue probe")
            input("[single-app] Press Enter to proceed with probing: ")

        discovered = crawler.probe_window(window, app_name, clear_cache=clear_cache)

        try:
            crawler.reset_ui(window)
        except Exception:
            pass

        return {
            "discovered": discovered,
            "error": "",
            "probe_log": crawler.log_path,
            "stats": crawler.stats,
        }
    except Exception as e:  # noqa: BLE001
        error = str(e)
        return {"discovered": discovered, "error": error, "probe_log": crawler.log_path}
    finally:
        if not keep_app_open and not attach_only:
            try:
                controller.terminate_app()
            except Exception:
                pass


def _build_capability_profile(
    app_name: str,
    cache_stats: Dict[str, Any],
    discovery: Dict[str, Any],
    execution_summary: Dict[str, Any],
) -> Dict[str, Any]:
    elements_count = int(cache_stats.get("elements_count", 0))
    with_paths = int(cache_stats.get("elements_with_exposure_path", 0))
    path_cov = round((with_paths / elements_count), 4) if elements_count > 0 else 0.0

    profile = {
        "app_name": app_name,
        "path_coverage_ratio": path_cov,
        "task_match_ratio": float(cache_stats.get("task_match_ratio", 0.0)),
        "elements_count": elements_count,
        "elements_with_exposure_path": with_paths,
        "broken_exposure_paths": int(cache_stats.get("broken_exposure_paths", 0)),
        "orphan_parent_refs": int(cache_stats.get("orphan_parent_refs", 0)),
        "discovery_new_elements": int(discovery.get("discovered", 0)),
        "last_run_failures": int(execution_summary.get("failures", 0)) if execution_summary else 0,
        "last_run_cache_hits": int(execution_summary.get("cache_hits", 0)) if execution_summary else 0,
        "last_run_ax_successes": int(execution_summary.get("ax_successes", 0)) if execution_summary else 0,
        "last_run_vision_successes": int(execution_summary.get("vision_successes", 0)) if execution_summary else 0,
    }
    return profile


def _to_markdown(report: Dict[str, Any]) -> str:
    app_name = report["app_name"]
    discovery = report["discovery"]
    cache_stats = report["cache_analysis"]
    execution = report["execution"]
    profile = report.get("capability_profile", {})

    lines = [
        f"# Single-App Pipeline Report - {app_name}",
        "",
        f"Generated: {report['generated_at']}",
        "",
        "## Discovery",
        f"- Discovered new elements: {discovery.get('discovered', 0)}",
        f"- Discovery error: {discovery.get('error', '') or 'None'}",
        f"- Probe log: {discovery.get('probe_log', '')}",
        "",
        "## Cache Coverage",
        f"- Cache elements: {cache_stats.get('elements_count', 0)}",
        f"- Elements with exposure paths: {cache_stats.get('elements_with_exposure_path', 0)}",
        f"- Max exposure path length: {cache_stats.get('max_exposure_path_length', 0)}",
        f"- Avg exposure path length: {cache_stats.get('avg_exposure_path_length', 0.0)}",
        f"- Broken exposure paths: {cache_stats.get('broken_exposure_paths', 0)}",
        f"- Orphan parent refs: {cache_stats.get('orphan_parent_refs', 0)}",
        f"- Task match coverage: {cache_stats.get('task_match_hits', 0)}/{cache_stats.get('task_match_total', 0)} ({cache_stats.get('task_match_ratio', 0.0)})",
        "",
        "## Targeted Execution",
        f"- Output dir: {execution.get('output_dir', '')}",
        f"- Latest run dir: {execution.get('run_dir', '')}",
        f"- Total tasks: {execution.get('summary', {}).get('total_tasks', 0)}",
        f"- Failures: {execution.get('summary', {}).get('failures', 0)}",
        f"- Cache hits: {execution.get('summary', {}).get('cache_hits', 0)}",
        f"- AX successes: {execution.get('summary', {}).get('ax_successes', 0)}",
        f"- Vision successes: {execution.get('summary', {}).get('vision_successes', 0)}",
        "",
        "## Capability Profile",
        f"- Path coverage ratio: {profile.get('path_coverage_ratio', 0.0)}",
        f"- Task match ratio: {profile.get('task_match_ratio', 0.0)}",
        f"- Broken exposure paths: {profile.get('broken_exposure_paths', 0)}",
        f"- Orphan parent refs: {profile.get('orphan_parent_refs', 0)}",
        "",
    ]

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Discover and execute one app safely")
    parser.add_argument("--app", required=True, help="Target app name (exactly one)")
    parser.add_argument("--discover-time", type=int, default=240, help="Probe max time in seconds")
    parser.add_argument("--skip-discovery", action="store_true", help="Skip discovery phase")
    parser.add_argument("--skip-execution", action="store_true", help="Run discovery/analyze only, skip task execution")
    parser.add_argument("--clear-cache", action="store_true", help="Clear app cache before discovery")
    parser.add_argument("--use-vision", action="store_true", help="Enable vision fallback during execution")
    parser.add_argument("--max-tasks", type=int, default=None, help="Limit tasks during execution")
    parser.add_argument("--output-dir", default="runs/single_app_targeted", help="Execution output dir")
    parser.add_argument("--include-protected", action="store_true", help="Allow protected apps such as VSCode")
    parser.add_argument("--register-if-missing", action="store_true", help="Register app into config if missing")
    parser.add_argument("--exe", default="", help="Exe path for registration when app is missing")
    parser.add_argument("--title-re", default="", help="Window title regex for registration when app is missing")
    parser.add_argument("--electron", action="store_true", help="Mark registered app as electron/chromium")
    parser.add_argument("--tasks", nargs="*", default=None, help="Optional task list for registration")
    parser.add_argument("--attach-only", action="store_true", help="Attach to already-open app without pre-cleanup/start")
    parser.add_argument("--human-ready", action="store_true", help="Wait for explicit Enter before probing")
    parser.add_argument("--keep-app-open", action="store_true", help="Do not terminate app after discovery")
    args = parser.parse_args()

    app_name = args.app

    if app_name in PROTECTED_APPS and not args.include_protected:
        print(f"[single-app] Blocked protected app by default: {app_name}")
        return 1

    app_cfg = config.get_app_config(app_name)
    try:
        app_cfg = _register_app_if_needed(
            app_name=app_name,
            app_cfg=app_cfg,
            register_if_missing=args.register_if_missing,
            exe=args.exe,
            title_re=args.title_re,
            electron=args.electron,
            tasks=args.tasks or [],
        )
    except Exception as e:  # noqa: BLE001
        print(f"[single-app] Registration error: {e}")
        return 1

    if not app_cfg:
        print(f"[single-app] Unknown app: {app_name}")
        print("[single-app] Tip: use --register-if-missing --exe <path> --title-re <regex>")
        return 1

    exe = app_cfg.get("exe", "")
    if not args.attach_only and (not exe or not os.path.exists(exe)):
        print(f"[single-app] Executable missing: {app_name} -> {exe}")
        return 1

    if not args.attach_only:
        _cleanup_app(app_name)

    discovery: Dict[str, Any] = {"discovered": 0, "error": "", "probe_log": ""}
    if not args.skip_discovery:
        print(f"[single-app] Discovery start: {app_name}")
        discovery = _discover_single_app(
            app_name=app_name,
            max_time=args.discover_time,
            clear_cache=args.clear_cache,
            attach_only=args.attach_only,
            human_ready=args.human_ready,
            keep_app_open=args.keep_app_open,
        )
        print(f"[single-app] Discovery complete: discovered={discovery.get('discovered', 0)}")
        if discovery.get("error"):
            print(f"[single-app] Discovery warning: {discovery['error']}")

    print(f"[single-app] Analyzing cache for {app_name}")
    cache_stats = _analyze_cache(app_name)

    latest = None
    summary = {}
    output_dir = PROJECT_ROOT / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    if not args.skip_execution:
        print(f"[single-app] Targeted execution start: {app_name}")
        run_all(
            apps=[app_name],
            output_dir=str(output_dir),
            use_cache=True,
            use_vision=args.use_vision,
            dry_run=False,
            max_tasks=args.max_tasks,
        )

        latest = _find_latest_run_dir(output_dir)
        if latest:
            summary_path = latest / "summary.json"
            if summary_path.exists():
                summary = json.loads(summary_path.read_text(encoding="utf-8"))

        if not args.attach_only:
            _cleanup_app(app_name)
    else:
        print("[single-app] Execution skipped by --skip-execution")

    capability_profile = _build_capability_profile(
        app_name=app_name,
        cache_stats=cache_stats,
        discovery=discovery,
        execution_summary=summary,
    )
    profile_saved = path_policy.update_profile(app_name, capability_profile)
    capability_profile["profile_saved"] = profile_saved

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    result_dir = PROJECT_ROOT / "results"
    result_dir.mkdir(parents=True, exist_ok=True)

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "app_name": app_name,
        "discovery": discovery,
        "cache_analysis": cache_stats,
        "execution": {
            "output_dir": str(output_dir),
            "run_dir": str(latest) if latest else "",
            "summary": summary,
            "use_vision": args.use_vision,
            "max_tasks": args.max_tasks,
            "skipped": args.skip_execution,
        },
        "capability_profile": capability_profile,
    }

    json_path = result_dir / f"single_app_pipeline_{app_name.lower()}_{stamp}.json"
    md_path = result_dir / f"single_app_pipeline_{app_name.lower()}_{stamp}.md"

    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(_to_markdown(report), encoding="utf-8")

    print("[single-app] COMPLETE")
    print(f"[single-app] JSON: {json_path}")
    print(f"[single-app] MD:   {md_path}")

    failures = int(summary.get("failures", 0)) if isinstance(summary, dict) else 0
    return 0 if failures == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
