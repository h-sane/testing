"""SARA demo preflight checks.

Checks:
- Core imports
- LLM key pool status
- Optional UI availability
- Voice mode status
- App executable + cache readiness for demo apps
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _check_imports() -> dict:
    result = {"ok": True, "details": {}}
    modules = [
        "sara.host_agent",
        "sara.execution_agent",
        "sara.llm_service",
        "sara.privacy_router",
        "sara.knowledge_base_manager",
    ]
    for name in modules:
        try:
            __import__(name)
            result["details"][name] = "ok"
        except Exception as exc:
            result["ok"] = False
            result["details"][name] = f"error: {exc}"
    return result


def _check_llm() -> dict:
    out = {"ok": True, "details": {}}
    try:
        from src.llm.llm_client import get_client

        c = get_client()
        health = c.health_check()
        out["details"] = health
        if (
            health.get("gemini_available", 0)
            + health.get("claude_available", 0)
            + health.get("nvidia_available", 0)
            + health.get("bedrock_available", 0)
            <= 0
        ):
            out["ok"] = False
    except Exception as exc:
        out["ok"] = False
        out["details"] = {"error": str(exc)}
    return out


def _check_ui() -> dict:
    try:
        import PyQt5  # noqa: F401

        return {"ok": True, "details": "PyQt5 available"}
    except Exception as exc:
        return {"ok": False, "details": str(exc)}


def _check_voice() -> dict:
    try:
        from sara.voice_service import VoiceService

        status = VoiceService().get_pipeline_status()
        return {"ok": True, "details": status}
    except Exception as exc:
        return {"ok": False, "details": str(exc)}


def _check_memory_graph() -> dict:
    try:
        from sara.memory.manager import KnowledgeBaseManager

        summary = KnowledgeBaseManager().get_memory_summary()
        graph = summary.get("graph_memory", {}) if isinstance(summary, dict) else {}
        enabled = bool(graph.get("enabled", False))
        ready = bool(graph.get("ready", False))

        # If graph memory is disabled by config, it should not fail preflight.
        ok = (not enabled) or ready
        return {"ok": ok, "details": graph}
    except Exception as exc:
        return {"ok": False, "details": str(exc)}


def _check_apps() -> dict:
    from src.automation import storage
    from src.harness import config as harness_config

    demo_apps = ["Notepad", "Brave"]
    details = {}
    ok = True
    for app in demo_apps:
        cfg = harness_config.get_app_config(app)
        exe = cfg.get("exe", "") if cfg else ""
        exe_ok = bool(exe) and os.path.exists(exe)
        cache_path = storage.get_cache_path(app)
        cache_ok = os.path.exists(cache_path)
        details[app] = {
            "exe": exe,
            "exe_exists": exe_ok,
            "cache_path": cache_path,
            "cache_exists": cache_ok,
        }
        if not exe_ok:
            ok = False
    return {"ok": ok, "details": details}


def main() -> int:
    report = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "checks": {
            "imports": _check_imports(),
            "llm": _check_llm(),
            "ui": _check_ui(),
            "voice": _check_voice(),
            "memory_graph": _check_memory_graph(),
            "apps": _check_apps(),
        },
    }

    all_ok = all(section.get("ok", False) for section in report["checks"].values())
    report["ok"] = all_ok

    out_dir = ROOT / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    out_file = out_dir / f"demo_preflight_{ts}.json"
    out_file.write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(json.dumps(report, indent=2))
    print(f"preflight_report: {out_file}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
