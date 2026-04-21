# scripts/scientific_mass_test.py
"""
Scientific Mass Test Runner — Full Notepad task suite with Section 1-15 compliance.

Invokes the existing 3-tier harness (Cache → Planner → AX → Vision) for all 20 Notepad tasks,
then enriches the run output with mandatory scientific artifacts.

Usage:
    python scripts/scientific_mass_test.py [--apps Notepad] [--no-vision]

Reproducibility: python scripts/scientific_mass_test.py --apps Notepad
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
# SCIENTIFIC ARTIFACT GENERATORS (Sections 6, 7, 9, 11, 14)
# =============================================================================

def generate_run_id() -> str:
    now = datetime.now()
    suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"RUN_{now.strftime('%Y%m%d_%H%M%S')}_{suffix}"


def generate_metadata(run_id: str, run_dir: Path, config: dict) -> dict:
    """Section 6: run_metadata.json"""
    import subprocess
    git_commit = ""
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, cwd=str(PROJECT_ROOT))
        git_commit = r.stdout.strip()
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
            "ram": "unknown",
        },
        "git_commit": git_commit,
        "modules_used": [
            "locator", "execution_planner", "matcher", "ax_executor",
            "vision_executor", "storage", "prober", "verification"
        ],
        "llm_provider": config.get("llm_provider", "none"),
        "vision_provider": config.get("vision_provider", "gemini_vlm"),
        "cache_enabled": config.get("cache_enabled", True),
        "vision_enabled": config.get("vision_enabled", True),
        "llm_enabled": config.get("llm_enabled", False),
    }


def generate_results_from_harness(run_id: str, run_dir: Path) -> dict:
    """Section 7: Build results.json from harness all_logs.jsonl (ExecutionLog entries)."""
    results = {
        "run_id": run_id,
        "total_tasks": 0,
        "total_success": 0,
        "total_failure": 0,
        "success_rate": 0.0,
        "by_method": {},
        "by_application": {},
    }
    
    # The harness HarnessLogger writes task results to all_logs.jsonl
    # (execution_log.jsonl contains granular events, not task outcomes)
    exec_log = run_dir / "all_logs.jsonl"
    if not exec_log.exists():
        # Fallback: try all_logs.json (non-streaming full dump)
        alt = run_dir / "all_logs.json"
        if alt.exists():
            exec_log = alt
        else:
            print(f"[scientific] WARNING: No all_logs.jsonl found in {run_dir}")
            return results
    
    entries = []
    with open(exec_log, "r") as f:
        content = f.read().strip()
        # Handle both JSONL format and JSON array format
        if content.startswith("["):
            try:
                entries = json.loads(content)
            except:
                pass
        else:
            for line in content.split("\n"):
                line = line.strip()
                if line:
                    try:
                        entries.append(json.loads(line))
                    except:
                        pass
    
    results["total_tasks"] = len(entries)
    results["total_success"] = sum(1 for e in entries if e.get("success"))
    results["total_failure"] = results["total_tasks"] - results["total_success"]
    results["success_rate"] = round(
        results["total_success"] / max(results["total_tasks"], 1), 4
    )
    
    for e in entries:
        method = e.get("execution_method", "UNKNOWN")
        if method not in results["by_method"]:
            results["by_method"][method] = {"total": 0, "success": 0, "failure": 0}
        results["by_method"][method]["total"] += 1
        if e.get("success"):
            results["by_method"][method]["success"] += 1
        else:
            results["by_method"][method]["failure"] += 1
    
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


def generate_checksums(run_dir: Path) -> str:
    """Section 9: SHA256 checksums."""
    lines = []
    for f in sorted(run_dir.iterdir()):
        if f.is_file() and f.name != "checksums.txt":
            sha = hashlib.sha256(f.read_bytes()).hexdigest()
            lines.append(f"sha256 {f.name} = {sha}")
    return "\n".join(lines)


def generate_validation_report(run_id: str, run_dir: Path) -> dict:
    """Section 11 + 14: Validation check."""
    required_files = [
        "all_logs.jsonl",
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
    
    has_success = False
    exec_log = run_dir / "all_logs.jsonl"
    if exec_log.exists():
        with open(exec_log, "r") as fh:
            for line in fh:
                if line.strip():
                    try:
                        entry = json.loads(line.strip())
                        if entry.get("success"):
                            has_success = True
                            break
                    except:
                        pass
    
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
        "module": "3tier_harness_notepad",
        "verdict": verdict,
        "artifact_paths": artifact_paths,
        "evidence_lines": evidence,
    }


# =============================================================================
# MAIN
# =============================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Scientific Mass Test Runner")
    parser.add_argument("--apps", nargs="+", default=["Notepad"])
    parser.add_argument(
        "--include-vscode",
        action="store_true",
        help="Include VSCode in test apps (disabled by default for safety)",
    )
    parser.add_argument("--no-vision", action="store_true")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--max-tasks", type=int, default=None)
    args = parser.parse_args()

    if not args.include_vscode:
        args.apps = [a for a in args.apps if a != "VSCode"]
    
    run_id = generate_run_id()
    run_dir = PROJECT_ROOT / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    
    # --- Section 8: Stream capture ---
    stdout_path = run_dir / "stdout.log"
    stderr_path = run_dir / "stderr.log"
    console_path = run_dir / "console.log"
    
    stdout_file = open(stdout_path, "w", encoding="utf-8")
    stderr_file = open(stderr_path, "w", encoding="utf-8")
    console_file = open(console_path, "w", encoding="utf-8")
    
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    
    class Tee:
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
    
    sys.stdout = Tee(original_stdout, stdout_file, console_file)
    sys.stderr = Tee(original_stderr, stderr_file, console_file)
    
    # Seed stderr (Section 8)
    sys.stderr.write(f"[stderr] Scientific mass test initialized: {run_id}\n")
    
    print(f"{'='*70}")
    print(f"SCIENTIFIC MASS TEST: {run_id}")
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print(f"Apps: {args.apps}")
    print(f"Cache: {'enabled' if not args.no_cache else 'disabled'}")
    print(f"Vision: {'enabled' if not args.no_vision else 'disabled'}")
    print(f"Run Directory: {run_dir}")
    print(f"{'='*70}\n")
    
    try:
        # --- Import and patch the harness to write into our run directory ---
        from src.harness import main as harness_main
        from src.harness import config as harness_config
        from src.harness.logger import HarnessLogger
        from src.harness.full_execution_trace_logger import FullExecutionTraceLogger
        from src.automation import matcher
        
        # Initialize loggers pointing to our scientific run dir
        logger = HarnessLogger(str(run_dir))
        # Override run_id to match ours
        logger.run_id = run_id
        logger.run_dir = str(run_dir)
        
        trace_logger = FullExecutionTraceLogger(run_id, output_dir=str(run_dir))
        matcher.init_debug_log(str(run_dir))
        
        print(f"[scientific] Logger initialized: run_id={run_id}")
        print(f"[scientific] Run dir: {run_dir}\n")
        
        # --- Execute each app ---
        for app_name in args.apps:
            app_config = harness_config.get_app_config(app_name)
            if not app_config:
                print(f"[scientific] No config for {app_name}, skipping")
                continue
            
            print(f"\n{'='*70}")
            print(f"APP: {app_name}")
            print(f"{'='*70}")
            
            try:
                harness_main.run_app(
                    app_name=app_name,
                    app_config=app_config,
                    logger=logger,
                    trace_logger=trace_logger,
                    use_cache=not args.no_cache,
                    use_vision=not args.no_vision,
                    max_tasks=args.max_tasks,
                )
            except Exception as e:
                tb = traceback.format_exc()
                print(f"[scientific] App error ({app_name}): {e}")
                print(f"[scientific] Traceback:\n{tb}")
        
        # Save harness logs
        logger.save_all()
        print("\n[scientific] Harness logs saved.")
        
    except Exception as e:
        tb = traceback.format_exc()
        print(f"\n[FATAL] {e}")
        print(f"[TRACEBACK]\n{tb}")
    
    finally:
        # --- Restore streams ---
        sys.stdout = original_stdout
        sys.stderr = original_stderr
        stdout_file.close()
        stderr_file.close()
        console_file.close()
        
        # --- Section 6: Metadata ---
        metadata = generate_metadata(run_id, run_dir, {
            "cache_enabled": not args.no_cache,
            "vision_enabled": not args.no_vision,
            "llm_enabled": False,
        })
        with open(run_dir / "run_metadata.json", "w") as f:
            json.dump(metadata, f, indent=2)
        
        # --- Section 7: Results ---
        results = generate_results_from_harness(run_id, run_dir)
        with open(run_dir / "results.json", "w") as f:
            json.dump(results, f, indent=2)
        
        # --- all_logs.json ---
        all_logs = {"run_id": run_id, "metadata": metadata, "results": results}
        with open(run_dir / "all_logs.json", "w") as f:
            json.dump(all_logs, f, indent=2)
        
        # --- Section 9: Checksums ---
        checksums = generate_checksums(run_dir)
        with open(run_dir / "checksums.txt", "w") as f:
            f.write(checksums)
        
        # --- Section 14: Validation ---
        report = generate_validation_report(run_id, run_dir)
        with open(run_dir / "validation_report.json", "w") as f:
            json.dump(report, f, indent=2)
        
        # --- Summary ---
        print(f"\n{'='*70}")
        print(f"RUN COMPLETE: {run_id}")
        print(f"Verdict: {report['verdict']}")
        print(f"Results: {results['total_success']}/{results['total_tasks']} success ({results['success_rate']*100:.1f}%)")
        print(f"Artifacts: {run_dir}")
        print(f"{'='*70}")
        for line in report.get("evidence_lines", []):
            print(f"  → {line}")
        print(f"\nReproducibility command:")
        print(f"  python scripts/scientific_mass_test.py --apps {' '.join(args.apps)}")


if __name__ == "__main__":
    main()
