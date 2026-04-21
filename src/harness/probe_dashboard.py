"""Probe runner + cache analytics for dashboard reporting."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from src.automation import matcher, prober, storage
from src.harness import config
from src.harness.app_controller import create_controller


def _analyze_cache(app_name: str, task_match_threshold: float = 0.65) -> Dict[str, Any]:
    cache_path = Path(storage.get_cache_path(app_name))
    report: Dict[str, Any] = {
        "cache_path": str(cache_path),
        "cache_exists": cache_path.exists(),
        "elements_count": 0,
        "elements_with_exposure_path": 0,
        "broken_exposure_paths": 0,
        "orphan_parent_refs": 0,
        "task_match_threshold": task_match_threshold,
        "task_match_hits": 0,
        "task_match_total": 0,
        "task_match_misses": 0,
        "task_match_ratio": 0.0,
        "parse_error": "",
    }

    if not cache_path.exists():
        tasks = config.get_tasks_for_app(app_name)
        report["task_match_total"] = len(tasks)
        report["task_match_misses"] = len(tasks)
        return report

    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception as exc:
        report["parse_error"] = str(exc)
        return report

    elements = data.get("elements", {})
    report["elements_count"] = len(elements)

    for node in elements.values():
        if not isinstance(node, dict):
            continue

        parent_fp = str(node.get("parent_fingerprint", "")).strip()
        if parent_fp and parent_fp not in elements:
            report["orphan_parent_refs"] += 1

        exposure_path = node.get("exposure_path", [])
        if isinstance(exposure_path, list) and exposure_path:
            report["elements_with_exposure_path"] += 1
            for step in exposure_path:
                if not isinstance(step, dict):
                    continue
                step_fp = str(step.get("fingerprint", "")).strip()
                if step_fp and step_fp not in elements:
                    report["broken_exposure_paths"] += 1
                    break

    tasks = config.get_tasks_for_app(app_name)
    report["task_match_total"] = len(tasks)
    if tasks:
        hits = 0
        for task in tasks:
            cached = matcher.find_cached_element(app_name, task, min_confidence=task_match_threshold)
            if cached:
                hits += 1
        total = len(tasks)
        misses = max(0, total - hits)
        report["task_match_hits"] = hits
        report["task_match_misses"] = misses
        report["task_match_ratio"] = round(hits / total, 4) if total else 0.0

    return report


def run_probe_report(
    app_name: str,
    max_time: int = 180,
    clear_cache: bool = False,
    task_match_threshold: float = 0.65,
) -> Dict[str, Any]:
    app_cfg = config.get_app_config(app_name)
    if not app_cfg:
        return {
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "app_name": app_name,
            "discovery": {"discovered": 0, "error": f"Unknown app: {app_name}", "probe_log": "", "stats": {}},
            "cache_analysis": _analyze_cache(app_name, task_match_threshold),
        }

    controller = create_controller(app_name, app_cfg)
    crawler = prober.UIProber(max_depth=12, max_time=int(max_time))
    discovered = 0
    error = ""

    try:
        if not controller.start_or_connect():
            error = f"Could not start/connect to {app_name}"
        else:
            window = controller.get_window()
            if not window:
                error = f"Could not get window for {app_name}"
            else:
                discovered = int(crawler.probe_window(window, app_name, clear_cache=bool(clear_cache)))
                try:
                    crawler.reset_ui(window)
                except Exception:
                    pass
    except Exception as exc:
        error = str(exc)
    finally:
        try:
            controller.close()
        except Exception:
            pass

    return {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "app_name": app_name,
        "discovery": {
            "discovered": discovered,
            "error": error,
            "probe_log": str(getattr(crawler, "log_path", "")),
            "stats": dict(getattr(crawler, "stats", {})),
        },
        "cache_analysis": _analyze_cache(app_name, task_match_threshold),
    }
