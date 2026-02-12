# harness/logger.py
"""
Structured JSON logging for the hybrid GUI automation harness.
Logs each execution attempt with all required fields.
"""

import datetime
import json
import os
import sys
from dataclasses import dataclass, field, asdict
from typing import Optional, List


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class ExecutionLog:
    """Single execution attempt log entry."""
    app_name: str
    task: str
    execution_method: str  # "CACHE", "AX", "VISION", "FAILED"
    success: bool
    ax_element_found: bool = False
    ax_patterns_available: List[str] = field(default_factory=list)
    cache_hit: bool = False
    vision_used: bool = False
    coordinates: Optional[tuple] = None
    verification_success: bool = False
    verification_method: str = ""
    error: str = ""
    timestamp: str = ""
    execution_time_ms: int = 0
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.datetime.utcnow().isoformat() + "Z"


@dataclass
class RunSummary:
    """Aggregate statistics for a complete run."""
    run_id: str
    started_at: str
    ended_at: str = ""
    total_tasks: int = 0
    cache_hits: int = 0
    ax_successes: int = 0
    vision_successes: int = 0
    failures: int = 0
    apps_tested: List[str] = field(default_factory=list)


# =============================================================================
# LOGGER CLASS
# =============================================================================

class HarnessLogger:
    """Logger for harness execution runs."""
    
    def __init__(self, output_dir: str = "runs"):
        self.output_dir = output_dir
        self.run_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_dir = os.path.join(output_dir, f"run_{self.run_id}")
        self.logs: List[ExecutionLog] = []
        self.summary = RunSummary(
            run_id=self.run_id,
            started_at=datetime.datetime.utcnow().isoformat() + "Z"
        )
        
        # Create run directory
        os.makedirs(self.run_dir, exist_ok=True)
        print(f"[logger] Run directory: {self.run_dir}")
    
    def log_execution(self, log: ExecutionLog) -> None:
        """Log a single execution attempt."""
        self.logs.append(log)
        
        # STREAMING SAVE (Mandatory for crash recovery)
        try:
            log_path = os.path.join(self.run_dir, "all_logs.jsonl")
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(log), ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"[logger] Failed to stream log: {e}")
        
        # Update summary
        self.summary.total_tasks += 1
        if log.cache_hit:
            self.summary.cache_hits += 1
        if log.execution_method == "AX" and log.success:
            self.summary.ax_successes += 1
        if log.execution_method == "VISION" and log.success:
            self.summary.vision_successes += 1
        if not log.success:
            self.summary.failures += 1
        if log.app_name not in self.summary.apps_tested:
            self.summary.apps_tested.append(log.app_name)
        
        # Print status
        status = "✅" if log.success else "❌"
        try:
            print(f"[logger] {status} {log.app_name}/{log.task} [{log.execution_method}] {log.execution_time_ms}ms")
        except UnicodeEncodeError:
            # Fallback for Windows consoles that dont support emojis
            status_safe = "SUCCESS" if log.success else "FAILURE"
            print(f"[logger] {status_safe} {log.app_name}/{log.task} [{log.execution_method}] {log.execution_time_ms}ms")
    
    def save_app_log(self, app_name: str) -> str:
        """Save logs for a specific app to JSON file."""
        app_logs = [asdict(log) for log in self.logs if log.app_name == app_name]
        path = os.path.join(self.run_dir, f"{app_name}.json")
        
        with open(path, "w", encoding="utf-8") as f:
            json.dump(app_logs, f, indent=2, ensure_ascii=False)
        
        return path
    
    def save_summary(self) -> str:
        """Save run summary to JSON file."""
        self.summary.ended_at = datetime.datetime.utcnow().isoformat() + "Z"
        path = os.path.join(self.run_dir, "summary.json")
        
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self.summary), f, indent=2, ensure_ascii=False)
        
        print(f"[logger] Summary saved: {path}")
        return path

    def log_execution_event(self, event_name: str, payload: dict):
        """
        Append a raw JSON event to execution_log.jsonl.
        Strictly follows user requirement for granular event logging.
        """
        log_path = os.path.join(self.run_dir, "execution_log.jsonl")
        entry = {
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "run_id": self.run_id,
            "event": event_name,
            **payload
        }
        try:
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            print(f"[logger] Failed to write to execution_log.jsonl: {e}")
    
    def save_all(self) -> None:
        """Save all logs and summary."""
        # Save per-app logs
        for app in self.summary.apps_tested:
            self.save_app_log(app)
        
        # Save full log
        all_logs_path = os.path.join(self.run_dir, "all_logs.json")
        with open(all_logs_path, "w", encoding="utf-8") as f:
            json.dump([asdict(log) for log in self.logs], f, indent=2, ensure_ascii=False)
        
        # Save summary
        self.save_summary()
        
        # Print final stats
        print("\n" + "=" * 50)
        print("RUN COMPLETE")
        print("=" * 50)
        print(f"  Total tasks: {self.summary.total_tasks}")
        print(f"  Cache hits:  {self.summary.cache_hits}")
        print(f"  AX success:  {self.summary.ax_successes}")
        print(f"  Vision:      {self.summary.vision_successes}")
        print(f"  Failures:    {self.summary.failures}")
        print(f"  Output:      {self.run_dir}")
        print("=" * 50)


# =============================================================================
# STDOUT/STDERR CAPTURE
# =============================================================================

class RedirectStdout:
    """
    Context manager to capture stdout/stderr to a log file while maintaining console output.
    MANDATORY for scientific logging integrity.
    """
    def __init__(self, log_path: str):
        self.log_path = log_path
        self.log_file = None
        self.stdout_original = sys.stdout
        self.stderr_original = sys.stderr

    def __enter__(self):
        self.log_file = open(self.log_path, 'a', encoding='utf-8', buffering=1) # Line buffered
        sys.stdout = self._make_stream(self.stdout_original, "STDOUT")
        sys.stderr = self._make_stream(self.stderr_original, "STDERR")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        sys.stdout = self.stdout_original
        sys.stderr = self.stderr_original
        if self.log_file:
            self.log_file.close()

    def _make_stream(self, original_stream, label):
        """Create a proxy stream that writes to both original and file."""
        log_file = self.log_file
        
        class TeeStream:
            def write(self, message):
                original_stream.write(message)
                log_file.write(message)
                # Auto-flush on newlines to ensure crash logs are captured
                if '\n' in message:
                    original_stream.flush()
                    log_file.flush()
            
            def flush(self):
                original_stream.flush()
                log_file.flush()
                
            def isatty(self):
                return original_stream.isatty()
        
        return TeeStream()


# =============================================================================
# PARAMETERIZED UTILS
# =============================================================================

def create_logger(output_dir: str = "runs") -> HarnessLogger:
    """Create a new logger instance."""
    return HarnessLogger(output_dir)
