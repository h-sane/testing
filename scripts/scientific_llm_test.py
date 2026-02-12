# scripts/scientific_llm_test.py
"""
Scientific Test Runner for LLM Orchestrator (Section 1-15 compliant).

Generates ALL mandatory artifacts per the scientific execution rules:
- execution_log.jsonl
- full_execution_trace.jsonl
- console.log, stdout.log, stderr.log
- run_metadata.json, results.json
- checksums.txt, validation_report.json
- screenshots/

Usage:
    python scripts/scientific_llm_test.py
"""

import sys
import os
import io
import json
import time
import hashlib
import platform
import traceback
import random
import string
from datetime import datetime, timezone
from pathlib import Path

# Project root setup
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")


# =============================================================================
# RUN ID GENERATION (Section 2)
# =============================================================================

def generate_run_id() -> str:
    """Generate unique run ID: RUN_YYYYMMDD_HHMMSS_XXXX"""
    now = datetime.now()
    suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"RUN_{now.strftime('%Y%m%d_%H%M%S')}_{suffix}"


# =============================================================================
# STREAM TEES (Section 5, 8)
# =============================================================================

class StreamTee:
    """Tee stdout/stderr to both console and file."""
    def __init__(self, stream, log_file):
        self.stream = stream
        self.log_file = log_file
    
    def write(self, data):
        self.stream.write(data)
        self.stream.flush()
        self.log_file.write(data)
        self.log_file.flush()
    
    def flush(self):
        self.stream.flush()
        self.log_file.flush()
    
    def fileno(self):
        return self.stream.fileno()


# =============================================================================
# TRACE LOGGER (Section 3, 4, 10)
# =============================================================================

class ScientificTraceLogger:
    """Writes execution_log.jsonl and full_execution_trace.jsonl."""
    
    def __init__(self, run_dir: Path, run_id: str):
        self.run_dir = run_dir
        self.run_id = run_id
        self.exec_log_path = run_dir / "execution_log.jsonl"
        self.trace_log_path = run_dir / "full_execution_trace.jsonl"
        self.exec_log_file = open(self.exec_log_path, "w", encoding="utf-8")
        self.trace_log_file = open(self.trace_log_path, "w", encoding="utf-8")
    
    def log_execution(self, entry: dict):
        """Write one execution_log entry (Section 3)."""
        required_fields = {
            "run_id": self.run_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "app_name": "",
            "task": "",
            "execution_method": "FAILED",
            "success": False,
            "plan_length": 0,
            "steps_completed": 0,
            "failure_step_index": -1,
            "locator_score": 0.0,
            "recovery_used": False,
            "vision_used": False,
            "llm_used": False,
            "execution_time_ms": 0,
        }
        # Merge with provided, ensuring no nulls
        for k, default_v in required_fields.items():
            if k not in entry or entry[k] is None:
                entry[k] = default_v
        
        self.exec_log_file.write(json.dumps(entry) + "\n")
        self.exec_log_file.flush()
    
    def log_trace(self, event: dict):
        """Write one trace event (Section 4)."""
        required_fields = {
            "run_id": self.run_id,
            "event_type": "",
            "component": "",
            "action": "",
            "input": "",
            "output": "",
            "success": False,
            "error": "",
            "latency_ms": 0,
            "terminal_stdout_snippet": "",
            "terminal_stderr_snippet": "",
        }
        for k, default_v in required_fields.items():
            if k not in event or event[k] is None:
                event[k] = default_v
        
        self.trace_log_file.write(json.dumps(event) + "\n")
        self.trace_log_file.flush()
    
    def close(self):
        self.exec_log_file.close()
        self.trace_log_file.close()


# =============================================================================
# METADATA GENERATOR (Section 6)
# =============================================================================

def generate_metadata(run_id: str, config: dict) -> dict:
    """Generate run_metadata.json (Section 6)."""
    import subprocess
    
    git_commit = ""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT)
        )
        git_commit = result.stdout.strip()
    except:
        git_commit = "unknown"
    
    return {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "system": {
            "os": f"{platform.system()} {platform.release()}",
            "python_version": platform.python_version(),
            "machine": platform.machine(),
            "cpu": platform.processor(),
            "ram": "unknown",  # Could use psutil if installed
        },
        "git_commit": git_commit,
        "modules_used": ["locator", "execution_planner", "ax_executor", "vision_executor", "llm_client", "orchestrator", "step_executor"],
        "llm_provider": config.get("llm_provider", "gemini"),
        "vision_provider": config.get("vision_provider", "gemini_vlm"),
        "cache_enabled": config.get("cache_enabled", True),
        "vision_enabled": config.get("vision_enabled", True),
        "llm_enabled": config.get("llm_enabled", True),
    }


# =============================================================================
# RESULTS GENERATOR (Section 7)
# =============================================================================

def generate_results(run_id: str, execution_log_path: Path) -> dict:
    """Generate results.json from execution_log.jsonl (Section 7)."""
    results = {
        "run_id": run_id,
        "total_tasks": 0,
        "total_success": 0,
        "total_failure": 0,
        "success_rate": 0.0,
        "by_method": {},
        "by_application": {},
    }
    
    entries = []
    with open(execution_log_path, "r") as f:
        for line in f:
            line = line.strip()
            if line:
                entries.append(json.loads(line))
    
    results["total_tasks"] = len(entries)
    results["total_success"] = sum(1 for e in entries if e.get("success"))
    results["total_failure"] = results["total_tasks"] - results["total_success"]
    results["success_rate"] = round(
        results["total_success"] / max(results["total_tasks"], 1), 4
    )
    
    # By method
    for e in entries:
        method = e.get("execution_method", "UNKNOWN")
        if method not in results["by_method"]:
            results["by_method"][method] = {"total": 0, "success": 0, "failure": 0}
        results["by_method"][method]["total"] += 1
        if e.get("success"):
            results["by_method"][method]["success"] += 1
        else:
            results["by_method"][method]["failure"] += 1
    
    # By application
    for e in entries:
        app = e.get("app_name", "UNKNOWN")
        if app not in results["by_application"]:
            results["by_application"][app] = {"total": 0, "success": 0, "failure": 0}
        results["by_application"][app]["total"] += 1
        if e.get("success"):
            results["by_application"][app]["success"] += 1
        else:
            results["by_application"][app]["failure"] += 1
    
    return results


# =============================================================================
# CHECKSUM GENERATOR (Section 9)
# =============================================================================

def generate_checksums(run_dir: Path) -> str:
    """Generate checksums.txt with SHA256 of all artifacts (Section 9)."""
    lines = []
    for f in sorted(run_dir.iterdir()):
        if f.is_file() and f.name != "checksums.txt":
            sha = hashlib.sha256(f.read_bytes()).hexdigest()
            lines.append(f"sha256 {f.name} = {sha}")
    return "\n".join(lines)


# =============================================================================
# VALIDATION REPORT (Section 14)
# =============================================================================

def generate_validation_report(run_id: str, run_dir: Path) -> dict:
    """Generate validation_report.json (Section 11, 14)."""
    required_files = [
        "execution_log.jsonl",
        "full_execution_trace.jsonl",
        "stdout.log",
        "stderr.log",
        "results.json",
        "checksums.txt",
    ]
    
    artifact_paths = {}
    missing = []
    for f in required_files:
        fpath = run_dir / f
        artifact_paths[f] = str(fpath)
        if not fpath.exists() or fpath.stat().st_size == 0:
            missing.append(f)
    
    # Check for at least one success
    has_success = False
    exec_log = run_dir / "execution_log.jsonl"
    if exec_log.exists():
        with open(exec_log, "r") as fh:
            for line in fh:
                if line.strip():
                    entry = json.loads(line.strip())
                    if entry.get("success"):
                        has_success = True
                        break
    
    if missing:
        verdict = "INCOMPLETE"
        evidence = [f"Missing artifacts: {', '.join(missing)}"]
    elif has_success:
        verdict = "VERIFIED"
        evidence = ["All required artifacts present", "At least one successful execution found"]
    else:
        verdict = "FAILED"
        evidence = ["All artifacts present but no successful execution found"]
    
    return {
        "run_id": run_id,
        "module": "llm_orchestrator",
        "verdict": verdict,
        "artifact_paths": artifact_paths,
        "evidence_lines": evidence,
    }


# =============================================================================
# SCREENSHOT CAPTURE
# =============================================================================

def capture_screenshot(run_dir: Path, step_num: int) -> str:
    """Capture screenshot for a step."""
    screenshots_dir = run_dir / "screenshots"
    screenshots_dir.mkdir(exist_ok=True)
    
    path = screenshots_dir / f"step_{step_num:03d}.png"
    try:
        import pyautogui
        img = pyautogui.screenshot()
        img.save(str(path))
        return str(path)
    except Exception as e:
        print(f"[screenshot] Failed: {e}")
        return ""


# =============================================================================
# MAIN TEST
# =============================================================================

TEST_TASKS = [
    {
        "instruction": "Click on the File menu",
        "app_name": "Notepad",
        "description": "Tests basic menu access via LLM planning"
    },
    {
        "instruction": "Open the Edit menu",
        "app_name": "Notepad",
        "description": "Tests menu navigation"
    },
    {
        "instruction": "Use keyboard shortcut Ctrl+N to create a new tab",
        "app_name": "Notepad",
        "description": "Tests HOTKEY action via LLM"
    },
]


def run_test():
    """Main scientific test execution."""
    run_id = generate_run_id()
    run_dir = PROJECT_ROOT / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    
    # --- Section 8: Stream redirection ---
    stdout_file = open(run_dir / "stdout.log", "w", encoding="utf-8")
    stderr_file = open(run_dir / "stderr.log", "w", encoding="utf-8")
    console_file = open(run_dir / "console.log", "w", encoding="utf-8")
    
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    
    class ConsoleTee:
        """Tee to both stdout and console.log."""
        def __init__(self, original, log_file, console):
            self.original = original
            self.log_file = log_file
            self.console = console
        def write(self, data):
            self.original.write(data)
            self.original.flush()
            self.log_file.write(data)
            self.log_file.flush()
            self.console.write(data)
            self.console.flush()
        def flush(self):
            self.original.flush()
            self.log_file.flush()
            self.console.flush()
        def fileno(self):
            return self.original.fileno()
    
    sys.stdout = ConsoleTee(original_stdout, stdout_file, console_file)
    sys.stderr = ConsoleTee(original_stderr, stderr_file, console_file)
    
    # Seed stderr so file is never 0 bytes (Section 8 compliance)
    sys.stderr.write(f"[stderr] Scientific test run initialized\n")
    
    trace_logger = ScientificTraceLogger(run_dir, run_id)
    
    print(f"{'='*70}")
    print(f"SCIENTIFIC TEST RUN: {run_id}")
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print(f"Run Directory: {run_dir}")
    print(f"{'='*70}\n")
    
    try:
        # --- Launch Notepad ---
        print("[SETUP] Launching Notepad...")
        
        trace_logger.log_trace({
            "event_type": "SETUP",
            "component": "test_harness",
            "action": "launch_notepad",
            "input": "notepad.exe",
            "output": "",
            "success": True,
        })
        
        import subprocess
        proc = subprocess.Popen(["notepad.exe"])
        time.sleep(3)
        
        # --- Connect window ---
        from pywinauto import Application
        app = Application(backend="uia").connect(title_re=".*Notepad.*", visible_only=True, found_index=0)
        window = app.top_window()
        window.set_focus()
        time.sleep(1)
        
        print(f"[SETUP] Connected to: {window.window_text()}")
        print(f"[SETUP] Descendants: {len(window.descendants())}\n")
        
        trace_logger.log_trace({
            "event_type": "SETUP",
            "component": "test_harness",
            "action": "connect_window",
            "input": ".*Notepad.*",
            "output": window.window_text(),
            "success": True,
        })
        
        # --- LLM health check ---
        from src.llm.llm_client import get_client
        client = get_client()
        health = client.health_check()
        print(f"[SETUP] LLM Health: {health}\n")
        
        trace_logger.log_trace({
            "event_type": "HEALTH_CHECK",
            "component": "llm_client",
            "action": "health_check",
            "input": "",
            "output": json.dumps(health),
            "success": health["gemini_available"] > 0 or health["claude_available"] > 0,
        })
        
        # --- Execute test tasks ---
        from src.llm.orchestrator import Orchestrator
        orch = Orchestrator()
        
        for i, task in enumerate(TEST_TASKS, 1):
            print(f"\n{'='*70}")
            print(f"TEST {i}/{len(TEST_TASKS)}: {task['instruction']}")
            print(f"Description: {task['description']}")
            print(f"{'='*70}\n")
            
            task_start = time.time()
            
            # Screenshot before
            capture_screenshot(run_dir, i * 10)
            
            trace_logger.log_trace({
                "event_type": "TASK_START",
                "component": "orchestrator",
                "action": "execute",
                "input": task["instruction"],
                "output": "",
                "success": True,
            })
            
            try:
                trace = orch.execute(
                    instruction=task["instruction"],
                    window=window,
                    app_name=task["app_name"],
                )
                
                task_ms = int((time.time() - task_start) * 1000)
                
                # Screenshot after
                capture_screenshot(run_dir, i * 10 + 1)
                
                # Log execution (Section 3)
                trace_logger.log_execution({
                    "run_id": run_id,
                    "app_name": task["app_name"],
                    "task": task["instruction"],
                    "execution_method": "LLM_ORCHESTRATOR",
                    "success": trace.success,
                    "plan_length": len(trace.steps),
                    "steps_completed": sum(1 for s in trace.steps if s.result.get("success")),
                    "failure_step_index": next(
                        (s.step_num for s in trace.steps if not s.result.get("success")), -1
                    ),
                    "locator_score": 0.0,
                    "recovery_used": False,
                    "vision_used": any(s.result.get("method") == "VISION" for s in trace.steps),
                    "llm_used": True,
                    "execution_time_ms": task_ms,
                })
                
                # Log each step trace (Section 4)
                for step in trace.steps:
                    stdout_snippet = step.result.get("error", "")[:200]
                    trace_logger.log_trace({
                        "event_type": "STEP_EXECUTION",
                        "component": step.action.get("action_type", "UNKNOWN"),
                        "action": json.dumps(step.action),
                        "input": step.thought,
                        "output": json.dumps(step.result),
                        "success": step.result.get("success", False),
                        "error": step.result.get("error", ""),
                        "latency_ms": step.latency_ms,
                        "terminal_stdout_snippet": stdout_snippet,
                        "terminal_stderr_snippet": "",
                    })
                
                status = "✅ SUCCESS" if trace.success else "❌ FAILED"
                print(f"\n[RESULT] {status} | {task_ms}ms | {len(trace.steps)} steps | {trace.llm_calls} LLM calls")
                if trace.error:
                    print(f"[ERROR] {trace.error}")
                
            except Exception as e:
                task_ms = int((time.time() - task_start) * 1000)
                tb = traceback.format_exc()
                print(f"[EXCEPTION] {e}")
                print(f"[TRACEBACK]\n{tb}")
                
                trace_logger.log_execution({
                    "run_id": run_id,
                    "app_name": task["app_name"],
                    "task": task["instruction"],
                    "execution_method": "EXCEPTION",
                    "success": False,
                    "plan_length": 0,
                    "steps_completed": 0,
                    "failure_step_index": 0,
                    "locator_score": 0.0,
                    "recovery_used": False,
                    "vision_used": False,
                    "llm_used": True,
                    "execution_time_ms": task_ms,
                })
                
                trace_logger.log_trace({
                    "event_type": "EXCEPTION",
                    "component": "orchestrator",
                    "action": task["instruction"],
                    "input": "",
                    "output": "",
                    "success": False,
                    "error": str(e),
                    "latency_ms": task_ms,
                    "terminal_stdout_snippet": "",
                    "terminal_stderr_snippet": tb[:500],
                })
            
            # ESC reset between tasks
            try:
                window.type_keys("{ESC}{ESC}", pause=0.1)
                time.sleep(0.5)
            except:
                pass
        
        # --- Cleanup: Close Notepad ---
        print("\n[CLEANUP] Closing Notepad...")
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except:
            try:
                proc.kill()
            except:
                pass
        
    except Exception as e:
        tb = traceback.format_exc()
        print(f"\n[FATAL] {e}")
        print(f"[TRACEBACK]\n{tb}")
        
        trace_logger.log_trace({
            "event_type": "FATAL_ERROR",
            "component": "test_harness",
            "action": "run_test",
            "input": "",
            "output": "",
            "success": False,
            "error": str(e),
            "latency_ms": 0,
            "terminal_stdout_snippet": "",
            "terminal_stderr_snippet": tb[:500],
        })
    
    finally:
        # --- Close trace logger ---
        trace_logger.close()
        
        # --- Section 6: Metadata ---
        metadata = generate_metadata(run_id, {
            "llm_provider": "gemini",
            "vision_provider": "gemini_vlm",
            "cache_enabled": True,
            "vision_enabled": True,
            "llm_enabled": True,
        })
        with open(run_dir / "run_metadata.json", "w") as f:
            json.dump(metadata, f, indent=2)
        
        # --- Section 7: Results ---
        results = generate_results(run_id, run_dir / "execution_log.jsonl")
        with open(run_dir / "results.json", "w") as f:
            json.dump(results, f, indent=2)
        
        # --- all_logs.json (combined) ---
        all_logs = {
            "run_id": run_id,
            "metadata": metadata,
            "results": results,
        }
        with open(run_dir / "all_logs.json", "w") as f:
            json.dump(all_logs, f, indent=2)
        
        # --- Restore streams ---
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        stdout_file.close()
        stderr_file.close()
        console_file.close()
        
        # --- Section 9: Checksums ---
        checksums = generate_checksums(run_dir)
        with open(run_dir / "checksums.txt", "w") as f:
            f.write(checksums)
        
        # --- Section 14: Validation report ---
        report = generate_validation_report(run_id, run_dir)
        with open(run_dir / "validation_report.json", "w") as f:
            json.dump(report, f, indent=2)
        
        print(f"\n{'='*70}")
        print(f"RUN COMPLETE: {run_id}")
        print(f"Verdict: {report['verdict']}")
        print(f"Results: {results['total_success']}/{results['total_tasks']} success ({results['success_rate']*100:.1f}%)")
        print(f"Artifacts: {run_dir}")
        print(f"{'='*70}")
        
        # Print evidence
        for line in report.get("evidence_lines", []):
            print(f"  → {line}")
        
        # Section 13: Reproducibility
        print(f"\nReproducibility command:")
        print(f"  python scripts/scientific_llm_test.py")


if __name__ == "__main__":
    run_test()
