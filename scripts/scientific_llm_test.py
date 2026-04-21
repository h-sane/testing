# scripts/scientific_llm_test.py
"""
Scientific LLM Orchestrator Test Runner — Full Multi-App Suite.

Tests the complete pipeline: User NL instruction → LLM planning (Gemini/Claude)
→ Step Executor → Cache/AX/Vision execution → Observation → LLM replan.

This is the end-to-end test for the research paper.

Generates scientific artifacts:
  execution_log.jsonl, traces.json, results.json,
  run_metadata.json, stdout.log, stderr.log,
  checksums.txt, validation_report.json

Usage:
    python scripts/scientific_llm_test.py --apps Notepad Calculator
    python scripts/scientific_llm_test.py --apps Notepad --max-tasks 5
    python scripts/scientific_llm_test.py                 # all available apps
"""

import sys
import os
import json
import time
import hashlib
import platform
import traceback
import random
import string
from datetime import datetime, timezone
from pathlib import Path

# Project root
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")


# =============================================================================
# HIGH-LEVEL NATURAL LANGUAGE TASK DATASET
# =============================================================================

LLM_TASKS = {
    "Notepad": [
        # Single-step
        "Open the File menu",
        "Open the Edit menu",
        "Open the Format menu",
        "Open the View menu",
        "Open the Help menu",
        # Multi-step
        "Create a new blank document",
        "Open the Find dialog to search for text",
        "Open the Replace dialog",
        "Open the Go To Line dialog",
        "Open the Font settings dialog",
        # Complex workflows
        "Type 'Hello World' into the document",
        "Select all text in the document",
        "Open the File menu and click Save As",
        "Turn on word wrap from the Format menu",
        "Open the About Notepad dialog from the Help menu",
    ],
    "Calculator": [
        "Press the number five button",
        "Press the addition button",
        "Press the number three button",
        "Press the equals button",
        "Press the Clear button to reset",
        "Calculate seven times eight",
        "Calculate one hundred divided by four",
        "Find the square root of sixteen",
        "Calculate 42 plus 58 and get the result",
        "Subtract 17 from 50",
        "Use the backspace to delete the last digit",
        "Switch to Scientific calculator mode",
        "Switch to Programmer calculator mode",
        "Store the current value in memory",
        "Recall the value from memory",
    ],
    "Chrome": [
        "Open a new tab",
        "Close the current tab",
        "Open Chrome settings",
        "Open the browsing history page",
        "Open the downloads page",
        "Open the bookmarks manager",
        "Focus the address bar so I can type a URL",
        "Go back to the previous page",
        "Refresh the current page",
        "Zoom in on the page",
        "Open a new incognito window",
        "Open the developer tools",
    ],
    "Brave": [
        "Open a new tab",
        "Close the current tab",
        "Open Brave settings",
        "Open browsing history",
        "Open the downloads page",
        "Open bookmarks",
        "Focus the address bar",
        "Go back to the previous page",
        "Go forward to the next page",
        "Refresh this page",
        "Open a private browsing window",
    ],
    "Excel": [
        "Open the File menu",
        "Create a new blank workbook",
        "Open the Save As dialog",
        "Print the current spreadsheet",
        "Undo the last action",
        "Redo the last undone action",
        "Cut the selected cells",
        "Copy the selected cells",
        "Paste from clipboard",
        "Insert a new row",
        "Insert a new column",
        "Delete the current row",
        "Delete the current column",
        "Open a workbook from disk",
        "Save the current workbook",
    ],
    "Windsurf": [
        "Open the File menu",
        "Open the Edit menu",
        "Open the View menu",
        "Toggle the sidebar visibility",
        "Open the Command Palette",
        "Create a new file",
        "Open a folder in the editor",
        "Save the current file",
        "Save all open files",
        "Open the Extensions panel",
        "Open the Settings page",
        "Toggle the integrated terminal",
    ],
    "Spotify": [
        "Go to the Home page",
        "Open the Search page",
        "Open my Library",
        "Open the playback queue",
        "Play the current track",
        "Pause the music",
        "Skip to the next track",
        "Go back to the previous track",
        "Like the current song",
        "Toggle shuffle mode",
        "Toggle repeat mode",
        "Turn the volume up",
        "Turn the volume down",
        "Mute the audio",
        "Open Spotify Settings",
    ],
}


# =============================================================================
# HELPERS
# =============================================================================

def generate_run_id() -> str:
    now = datetime.now()
    suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"LLM_{now.strftime('%Y%m%d_%H%M%S')}_{suffix}"


class Tee:
    """Tee stdout/stderr to console + file."""
    def __init__(self, original, *log_files):
        self.original = original
        self.log_files = log_files
    def write(self, data):
        self.original.write(data)
        self.original.flush()
        for f in self.log_files:
            f.write(data)
            f.flush()
    def flush(self):
        self.original.flush()
        for f in self.log_files:
            f.flush()
    def fileno(self):
        return self.original.fileno()


def generate_metadata(run_id, run_dir, apps, cfg):
    import subprocess as sp
    git_commit = ""
    try:
        r = sp.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=str(PROJECT_ROOT))
        git_commit = r.stdout.strip()
    except:
        git_commit = "unknown"
    return {
        "run_id": run_id,
        "test_type": "LLM_ORCHESTRATOR",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "system": {
            "os": f"{platform.system()} {platform.release()}",
            "python": platform.python_version(),
            "machine": platform.machine(),
        },
        "git_commit": git_commit,
        "apps_tested": apps,
        "llm_providers": cfg.get("llm_providers", "gemini+claude"),
        "cache_enabled": True,
        "vision_enabled": cfg.get("vision_enabled", True),
        "llm_enabled": True,
        "max_steps_per_task": 15,
    }


def generate_checksums(run_dir):
    lines = []
    for f in sorted(run_dir.iterdir()):
        if f.is_file() and f.name != "checksums.txt":
            sha = hashlib.sha256(f.read_bytes()).hexdigest()
            lines.append(f"sha256 {f.name} = {sha}")
    return "\n".join(lines)


def build_results(run_id, all_traces):
    """Build results.json from execution traces."""
    results = {
        "run_id": run_id,
        "test_type": "LLM_ORCHESTRATOR",
        "total_tasks": len(all_traces),
        "total_success": 0,
        "total_failure": 0,
        "success_rate": 0.0,
        "total_llm_calls": 0,
        "total_steps": 0,
        "avg_steps_per_task": 0.0,
        "avg_latency_ms": 0.0,
        "by_application": {},
        "by_action_type": {},
        "by_step_method": {},
        "task_details": [],
    }

    for t in all_traces:
        app = t["app_name"]
        success = t["success"]

        if app not in results["by_application"]:
            results["by_application"][app] = {
                "total": 0, "success": 0, "failure": 0,
                "llm_calls": 0, "total_steps": 0, "total_ms": 0,
            }
        ba = results["by_application"][app]
        ba["total"] += 1
        ba["llm_calls"] += t.get("llm_calls", 0)
        ba["total_steps"] += t.get("num_steps", 0)
        ba["total_ms"] += t.get("total_ms", 0)

        if success:
            results["total_success"] += 1
            ba["success"] += 1
        else:
            results["total_failure"] += 1
            ba["failure"] += 1

        results["total_llm_calls"] += t.get("llm_calls", 0)
        results["total_steps"] += t.get("num_steps", 0)

        # By action type (CLICK, TYPE, HOTKEY, WAIT, DONE, FAIL)
        for step in t.get("steps", []):
            atype = step.get("action", {}).get("action_type", "UNKNOWN")
            if atype not in results["by_action_type"]:
                results["by_action_type"][atype] = {"total": 0, "success": 0, "failure": 0}
            results["by_action_type"][atype]["total"] += 1
            if step.get("result", {}).get("success"):
                results["by_action_type"][atype]["success"] += 1
            else:
                results["by_action_type"][atype]["failure"] += 1

        # By step method (CACHE_PLANNER, AX, VISION, TYPE, HOTKEY, etc.)
        for step in t.get("steps", []):
            method = step.get("result", {}).get("method", "UNKNOWN")
            if method not in results["by_step_method"]:
                results["by_step_method"][method] = {"total": 0, "success": 0, "failure": 0}
            results["by_step_method"][method]["total"] += 1
            if step.get("result", {}).get("success"):
                results["by_step_method"][method]["success"] += 1
            else:
                results["by_step_method"][method]["failure"] += 1

        results["task_details"].append({
            "app": app,
            "instruction": t["instruction"],
            "success": success,
            "steps": t.get("num_steps", 0),
            "llm_calls": t.get("llm_calls", 0),
            "total_ms": t.get("total_ms", 0),
            "error": t.get("error", ""),
            "methods_used": t.get("methods_used", []),
        })

    n = max(len(all_traces), 1)
    results["success_rate"] = round(results["total_success"] / n, 4)
    results["avg_steps_per_task"] = round(results["total_steps"] / n, 2)
    total_ms = sum(t.get("total_ms", 0) for t in all_traces)
    results["avg_latency_ms"] = round(total_ms / n, 1)

    for app, ba in results["by_application"].items():
        ba["success_rate"] = round(ba["success"] / max(ba["total"], 1), 4)
        ba["avg_ms"] = round(ba["total_ms"] / max(ba["total"], 1), 1)

    return results


# =============================================================================
# ALSO WRITE execution_log.jsonl FOR CROSS-COMPATIBILITY
# =============================================================================

def write_execution_log(run_dir, run_id, all_traces):
    """Write execution_log.jsonl (harness-compatible format)."""
    path = run_dir / "execution_log.jsonl"
    with open(path, "w", encoding="utf-8") as f:
        for t in all_traces:
            entry = {
                "run_id": run_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "app_name": t["app_name"],
                "task": t["instruction"],
                "execution_method": "LLM_ORCHESTRATOR" if t["success"] else "FAILED",
                "success": t["success"],
                "llm_used": True,
                "execution_time_ms": t.get("total_ms", 0),
                "llm_calls": t.get("llm_calls", 0),
                "steps": t.get("num_steps", 0),
                "error": t.get("error", ""),
            }
            f.write(json.dumps(entry) + "\n")


# =============================================================================
# MAIN
# =============================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Scientific LLM Orchestrator Test")
    parser.add_argument("--apps", nargs="+", default=None,
                        help="Apps to test (default: all available)")
    parser.add_argument(
        "--include-vscode",
        action="store_true",
        help="Include VSCode in test apps (disabled by default for safety)",
    )
    parser.add_argument("--max-tasks", type=int, default=None,
                        help="Max tasks per app")
    parser.add_argument("--no-vision", action="store_true",
                        help="Disable vision fallback in step executor")
    parser.add_argument("--prefer-provider", default="gemini",
                        choices=["gemini", "claude"],
                        help="Preferred LLM provider (default: gemini)")
    args = parser.parse_args()

    # --- Run directory ---
    run_id = generate_run_id()
    run_dir = PROJECT_ROOT / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    # --- Stream capture ---
    stdout_file = open(run_dir / "stdout.log", "w", encoding="utf-8")
    stderr_file = open(run_dir / "stderr.log", "w", encoding="utf-8")
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    sys.stdout = Tee(original_stdout, stdout_file)
    sys.stderr = Tee(original_stderr, stderr_file)
    sys.stderr.write(f"[stderr] LLM test initialized: {run_id}\n")

    all_traces = []

    print(f"{'='*70}")
    print(f"SCIENTIFIC LLM ORCHESTRATOR TEST: {run_id}")
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print(f"Provider preference: {args.prefer_provider}")
    print(f"Vision: {'enabled' if not args.no_vision else 'disabled'}")
    print(f"Run Directory: {run_dir}")
    print(f"{'='*70}\n")

    try:
        from src.harness import config as harness_config
        from src.harness.app_controller import create_controller
        from src.llm.orchestrator import Orchestrator
        from src.llm.llm_client import get_client

        # --- LLM health check ---
        client = get_client()
        health = client.health_check()
        print(f"[llm] Key pool: {json.dumps(health)}")
        if health["gemini_available"] == 0 and health["claude_available"] == 0:
            print("[FATAL] No LLM API keys available. Aborting.")
            return

        # --- Determine apps ---
        available = harness_config.get_available_apps()
        if args.apps:
            apps_to_test = [a for a in args.apps if a in available]
        else:
            # All available that have LLM tasks defined
            apps_to_test = [a for a in available if a in LLM_TASKS]

        if not args.include_vscode:
            apps_to_test = [a for a in apps_to_test if a != "VSCode"]

        print(f"[scientific] Testing apps: {apps_to_test}")
        print(f"[scientific] Available apps: {available}\n")

        orchestrator = Orchestrator()

        for app_name in apps_to_test:
            tasks = LLM_TASKS.get(app_name, [])
            if not tasks:
                print(f"[scientific] No LLM tasks for {app_name}, skipping")
                continue
            if args.max_tasks:
                tasks = tasks[:args.max_tasks]

            print(f"\n{'='*70}")
            print(f"APP: {app_name} ({len(tasks)} tasks)")
            print(f"{'='*70}")

            app_config = harness_config.get_app_config(app_name)
            controller = create_controller(app_name, app_config)

            if not controller.start_or_connect():
                print(f"[scientific] ERROR: Cannot start/connect {app_name}")
                for task in tasks:
                    all_traces.append({
                        "app_name": app_name, "instruction": task,
                        "success": False, "num_steps": 0, "llm_calls": 0,
                        "total_ms": 0, "error": "App launch failed",
                        "steps": [], "methods_used": [],
                    })
                continue

            controller.focus()
            time.sleep(1.0)

            window = controller.get_window()
            if not window:
                print(f"[scientific] ERROR: No window for {app_name}")
                for task in tasks:
                    all_traces.append({
                        "app_name": app_name, "instruction": task,
                        "success": False, "num_steps": 0, "llm_calls": 0,
                        "total_ms": 0, "error": "No window handle",
                        "steps": [], "methods_used": [],
                    })
                continue

            for i, task in enumerate(tasks):
                print(f"\n--- [{app_name}] Task {i+1}/{len(tasks)}: {task} ---")

                try:
                    trace = orchestrator.execute(
                        instruction=task,
                        window=window,
                        app_name=app_name,
                    )

                    # Collect unique methods used across steps
                    methods = []
                    for s in trace.steps:
                        m = s.result.get("method", "UNKNOWN")
                        if m not in methods:
                            methods.append(m)

                    # Serialize step data
                    steps_data = []
                    for s in trace.steps:
                        steps_data.append({
                            "step_num": s.step_num,
                            "thought": s.thought,
                            "action": s.action,
                            "result": s.result,
                            "latency_ms": s.latency_ms,
                        })

                    all_traces.append({
                        "app_name": app_name,
                        "instruction": task,
                        "success": trace.success,
                        "num_steps": len(trace.steps),
                        "llm_calls": trace.llm_calls,
                        "total_ms": trace.total_ms,
                        "error": trace.error,
                        "steps": steps_data,
                        "methods_used": methods,
                    })

                except Exception as e:
                    tb = traceback.format_exc()
                    print(f"[scientific] Task exception: {e}\n{tb}")
                    all_traces.append({
                        "app_name": app_name, "instruction": task,
                        "success": False, "num_steps": 0, "llm_calls": 0,
                        "total_ms": 0, "error": str(e),
                        "steps": [], "methods_used": [],
                    })

                # Dismiss any dialogs and re-focus between tasks
                time.sleep(0.8)
                try:
                    import pyautogui
                    pyautogui.press("escape")
                    time.sleep(0.3)
                except:
                    pass
                try:
                    controller.focus()
                    time.sleep(0.3)
                except:
                    pass

            # Kill app after all its tasks
            try:
                controller.terminate_app()
            except:
                pass
            time.sleep(2.0)

    except Exception as e:
        tb = traceback.format_exc()
        print(f"\n[FATAL] {e}\n{tb}")

    finally:
        # --- Restore streams ---
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        stdout_file.close()
        stderr_file.close()

        # --- results.json ---
        results = build_results(run_id, all_traces)
        with open(run_dir / "results.json", "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2)

        # --- traces.json (full step-level detail) ---
        with open(run_dir / "traces.json", "w", encoding="utf-8") as f:
            json.dump(all_traces, f, indent=2)

        # --- execution_log.jsonl (harness-compatible) ---
        write_execution_log(run_dir, run_id, all_traces)

        # --- run_metadata.json ---
        tested_apps = sorted(set(t["app_name"] for t in all_traces))
        metadata = generate_metadata(run_id, run_dir, tested_apps, {
            "vision_enabled": not args.no_vision if hasattr(args, "no_vision") else True,
            "llm_providers": args.prefer_provider if hasattr(args, "prefer_provider") else "gemini",
        })
        with open(run_dir / "run_metadata.json", "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2)

        # --- checksums.txt ---
        checksums = generate_checksums(run_dir)
        with open(run_dir / "checksums.txt", "w", encoding="utf-8") as f:
            f.write(checksums)

        # --- validation_report.json ---
        verdict = "VERIFIED" if results["total_success"] > 0 else "FAILED"
        validation = {
            "run_id": run_id,
            "module": "llm_orchestrator",
            "verdict": verdict,
            "evidence_lines": [
                f"Total: {results['total_tasks']} tasks across {len(tested_apps)} apps",
                f"Success: {results['total_success']}/{results['total_tasks']} ({results['success_rate']*100:.1f}%)",
                f"LLM calls: {results['total_llm_calls']}",
                f"Avg steps/task: {results['avg_steps_per_task']}",
                f"Avg latency: {results['avg_latency_ms']}ms/task",
            ],
        }
        with open(run_dir / "validation_report.json", "w", encoding="utf-8") as f:
            json.dump(validation, f, indent=2)

        # --- Print summary ---
        print(f"\n{'='*70}")
        print(f"LLM ORCHESTRATOR TEST COMPLETE: {run_id}")
        print(f"{'='*70}")
        print(f"Total: {results['total_success']}/{results['total_tasks']} "
              f"({results['success_rate']*100:.1f}%)")
        print(f"LLM Calls: {results['total_llm_calls']}")
        print(f"Steps: {results['total_steps']} "
              f"(avg {results['avg_steps_per_task']}/task)")
        print(f"Latency: avg {results['avg_latency_ms']}ms/task")
        print()

        print("Per-app breakdown:")
        for app, ba in sorted(results["by_application"].items()):
            rate = ba["success_rate"] * 100
            print(f"  {app:15s}: {ba['success']}/{ba['total']} ({rate:.0f}%) | "
                  f"LLM: {ba['llm_calls']} | avg {ba['avg_ms']:.0f}ms")
        print()

        if results["by_action_type"]:
            print("Action types:")
            for atype, ad in sorted(results["by_action_type"].items()):
                print(f"  {atype:12s}: {ad['success']}/{ad['total']}")
            print()

        if results["by_step_method"]:
            print("Step methods:")
            for method, md in sorted(results["by_step_method"].items()):
                print(f"  {method:18s}: {md['success']}/{md['total']}")
            print()

        print(f"Verdict: {verdict}")
        print(f"Artifacts: {run_dir}")
        print(f"\nReproduce:")
        if tested_apps:
            print(f"  python scripts/scientific_llm_test.py --apps {' '.join(tested_apps)}")


if __name__ == "__main__":
    main()
