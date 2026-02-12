import os
import json
import time
import datetime
from typing import Dict, Any, Optional

class FullExecutionTraceLogger:
    """
    Logs EVERY step of execution pipeline to ensure 100% evidence capture.
    Strictly follows the Scientific Execution & Logging Enforcement Protocol.
    """
    
    def __init__(self, run_id: str, output_dir: str = None):
        self.run_id = run_id
        
        if output_dir:
            self.log_path = os.path.join(output_dir, "full_execution_trace.jsonl")
        else:
            # Fallback (legacy)
            self.log_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                "testing", "research_runs", f"run_{run_id}", "full_execution_trace.jsonl"
            )
            
        os.makedirs(os.path.dirname(self.log_path), exist_ok=True)
        print(f"[TRACE] Initialized Trace Logger: {self.log_path}")

    def _log(self, event_type: str, data: Dict[str, Any]):
        """Internal log writer."""
        entry = {
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "event_type": event_type,
            "run_id": self.run_id,
            **data
        }
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            print(f"CRITICAL: Trace Logger failed to write: {e}")

    def log_task_start(self, app_name: str, task: str):
        self._log("TASK_START", {
            "app_name": app_name,
            "task": task
        })

    def log_cache_check(self, cache_hit: bool, fingerprint_found: Optional[str] = None, score: float = 0.0):
        self._log("CACHE_CHECK", {
            "cache_hit": cache_hit,
            "fingerprint_found": fingerprint_found,
            "confidence_score": score
        })

    def log_planner_execution(self, planner_invoked: bool, exposure_path_length: int = 0, 
                              steps_attempted: int = 0, steps_completed: int = 0, 
                              failure_step: int = -1, success: bool = False):
        self._log("PLANNER_EXECUTION", {
            "planner_invoked": planner_invoked,
            "exposure_path_length": exposure_path_length,
            "steps_attempted": steps_attempted,
            "steps_completed": steps_completed,
            "failure_step": failure_step,
            "success": success
        })

    def log_ax_execution(self, ax_scan_started: bool, elements_scanned: int = 0, 
                         best_match_score: float = 0.0, execution_attempted: bool = False, 
                         execution_success: bool = False):
        self._log("AX_EXECUTION", {
            "ax_scan_started": ax_scan_started,
            "elements_scanned": elements_scanned,
            "best_match_score": best_match_score,
            "execution_attempted": execution_attempted,
            "execution_success": execution_success
        })

    def log_vision_execution(
        self, 
        triggered: bool, 
        success: bool = False, 
        api_called: bool = False,
        latency_ms: int = 0,
        screenshot_path: str = "",
        coordinates: Optional[tuple] = None,
        trigger_reason: str = ""
    ):
        """Log vision model execution details."""
        self._log("VISION_EXECUTION", {
            "vision_triggered": triggered,
            "success": success,
            "api_called": api_called,
            "api_latency_ms": latency_ms,
            "screenshot_saved_path": screenshot_path,
            "coordinates_returned": coordinates,
            "trigger_reason": trigger_reason
        })

    def log_recovery_event(self, recovery_type: str, details: str):
        self._log("RECOVERY_EVENT", {
            "recovery_type": recovery_type, # planner_recovery, subtree_recovery, cache_regenerated
            "details": details
        })

    def log_verification(self, signals_detected: Dict[str, bool], success: bool, confidence: float):
        self._log("VERIFICATION_EVENT", {
            "signals_detected": signals_detected,
            "success": success,
            "confidence": confidence
        })

    def log_task_end(self, final_execution_method: str, success: bool, total_execution_time_ms: int):
        self._log("TASK_END", {
            "final_execution_method": final_execution_method,
            "success": success,
            "total_execution_time_ms": total_execution_time_ms
        })

