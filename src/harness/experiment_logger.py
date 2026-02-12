# harness/experiment_logger.py
"""
Research-grade experiment logging and evidence storage.
Creates structured EXP_ID directories with manifest, JSONL logs, and analytics.
"""

import os
import json
import time
import datetime
import shutil
import platform
import sys
import math
from typing import Dict, Any, List

class ExperimentLogger:
    def __init__(self, base_dir="testing/research_runs"):
        self.base_dir = base_dir
        self.exp_id = ""
        self.exp_dir = ""
        self.start_time = 0
        self.app_names = []
        self.tasks_logged = 0
        os.makedirs(base_dir, exist_ok=True)

    def start_experiment(self, apps: List[str], config_meta: Dict = None, custom_name: str = None):
        """Initialize a new experiment directory and manifest."""
        self.start_time = time.time()
        self.app_names = apps
        
        if custom_name:
            self.exp_id = custom_name
        else:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            apps_slug = "_".join(apps[:3]).upper()
            self.exp_id = f"EXP_{ts}_{apps_slug}"
        self.exp_dir = os.path.join(self.base_dir, self.exp_id)
        
        os.makedirs(self.exp_dir, exist_ok=True)
        os.makedirs(os.path.join(self.exp_dir, "screenshots"), exist_ok=True)
        os.makedirs(os.path.join(self.exp_dir, "tree_snapshots"), exist_ok=True)
        os.makedirs(os.path.join(self.exp_dir, "cache_snapshot"), exist_ok=True)
        
        self._write_manifest(config_meta)
        print(f"[research] Experiment started: {self.exp_id}")

    def _write_manifest(self, config_meta: Dict):
        manifest = {
            "experiment_id": self.exp_id,
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "system_info": {
                "os": platform.system() + " " + platform.version(),
                "python_version": sys.version,
                "cpu": platform.processor(),
                "ram": "Unknown" # psutil would be better but keeping it vanilla
            },
            "harness_version": "2.0-research",
            "apps_tested": self.app_names,
            "vlm_config": {
                "gemini_model": "gemini-2.0-flash",
                "fallback_order": ["GEMINI", "HF"]
            },
            "probing_enabled": config_meta.get("probing_enabled", False) if config_meta else False,
            "verification_signals": [
                "tree_hash", "focus", "properties", "text_map", "element_count", "screenshot_hash"
            ]
        }
        with open(os.path.join(self.exp_dir, "manifest.json"), "w") as f:
            json.dump(manifest, f, indent=2)

    def _log_jsonl(self, filename: str, data: Dict):
        path = os.path.join(self.exp_dir, f"{filename}.jsonl")
        data["timestamp"] = datetime.datetime.utcnow().isoformat() + "Z"
        data["experiment_id"] = self.exp_id
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(data) + "\n")

    def log_execution(self, event: Dict):
        self.tasks_logged += 1
        self._log_jsonl("execution_log", event)

    def log_verification(self, event: Dict):
        self._log_jsonl("verification_log", event)

    def log_matcher(self, event: Dict):
        self._log_jsonl("matcher_log", event)

    def log_vlm(self, event: Dict):
        self._log_jsonl("vlm_log", event)

    def finalize_experiment(self):
        """Finalize logs, compute analytics, and snapshot cache."""
        exec_times = []
        successes = 0
        
        # Load execution log to compute metrics
        log_path = os.path.join(self.exp_dir, "execution_log.jsonl")
        if os.path.exists(log_path):
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    data = json.loads(line)
                    exec_times.append(data.get("execution_time_ms", 0))
                    if data.get("success"):
                        successes += 1
        
        # Tree Analytics
        tree_metrics = {
            "elements_before": 0,
            "elements_after": 0,
            "elements_discovered": 0,
            "elements_discovered_by_method": {"AX": 0, "VISION": 0, "PROBING": 0}
        }
        
        cache_source = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cache")
        if os.path.exists(cache_source):
            for item in os.listdir(cache_source):
                if item.endswith(".json"):
                    with open(os.path.join(cache_source, item), "r", encoding="utf-8") as f:
                        cache_data = json.load(f)
                        elements = cache_data.get("elements", {})
                        tree_metrics["elements_after"] += len(elements)
                        for val in elements.values():
                            if isinstance(val, dict):
                                method = val.get("discovery_method", "AX")
                                if method == "PROBE": method = "PROBING"
                                tree_metrics["elements_discovered_by_method"][method] = tree_metrics["elements_discovered_by_method"].get(method, 0) + 1
                    
                    shutil.copy2(os.path.join(cache_source, item), 
                                 os.path.join(self.exp_dir, "cache_snapshot", item))
        
        tree_metrics["elements_discovered"] = sum(tree_metrics["elements_discovered_by_method"].values())
        tree_metrics["elements_before"] = tree_metrics["elements_after"] - tree_metrics["elements_discovered"]
        
        # Coverage counts
        total_e = tree_metrics["elements_after"]
        tree_metrics.update({
            "total_elements": total_e,
            "ax_discovered": tree_metrics["elements_discovered_by_method"].get("AX", 0),
            "probe_discovered": tree_metrics["elements_discovered_by_method"].get("PROBING", 0),
            "vision_discovered": tree_metrics["elements_discovered_by_method"].get("VISION", 0),
            "ax_coverage_percent": (tree_metrics["elements_discovered_by_method"].get("AX", 0) / total_e * 100) if total_e > 0 else 0,
            "probe_contribution_percent": (tree_metrics["elements_discovered_by_method"].get("PROBING", 0) / total_e * 100) if total_e > 0 else 0,
            "vision_contribution_percent": (tree_metrics["elements_discovered_by_method"].get("VISION", 0) / total_e * 100) if total_e > 0 else 0,
        })
        
        # Load execution log for stability metrics
        cache_attempts = 0
        cache_hits = 0
        if os.path.exists(log_path):
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    data = json.loads(line)
                    # We can infer cache attempts from the method or specific logs
                    if data.get("method") == "CACHE":
                        cache_attempts += 1
                        cache_hits += 1
                    elif data.get("method") in ["AX", "VISION", "FAILED"]:
                        # This is an approximation; in reality we'd need a specific 'cache_lookups' event
                        # But for Phase 2 we assume every task attempted cache lookups if enabled
                        cache_attempts += 1
        
        # Performance metrics
        metrics = {
            "total_tasks": self.tasks_logged,
            "success_rate": successes / self.tasks_logged if self.tasks_logged > 0 else 0,
            "mean_execution_time": sum(exec_times) / len(exec_times) if exec_times else 0,
            "p50_execution_time": self._percentile(exec_times, 50) if exec_times else 0,
            "p95_execution_time": self._percentile(exec_times, 95) if exec_times else 0,
            "tree_growth": tree_metrics,
            "cache_lookup_attempts": cache_attempts,
            "cache_hits": cache_hits,
            "fingerprint_match_rate": (cache_hits / cache_attempts) if cache_attempts > 0 else 0
        }
        
        with open(os.path.join(self.exp_dir, "performance_metrics.json"), "w") as f:
            json.dump(metrics, f, indent=2)
            
        with open(os.path.join(self.exp_dir, "automation_tree_metrics.json"), "w") as f:
            json.dump(tree_metrics, f, indent=2)

        # Summary
        summary = {
            "experiment_id": self.exp_id,
            "duration_sec": int(time.time() - self.start_time),
            "total_tasks": self.tasks_logged,
            "successes": successes,
            "success_rate": metrics["success_rate"],
            "elements_discovered": tree_metrics["elements_discovered"],
            "probe_only": self.tasks_logged == 0
        }
        with open(os.path.join(self.exp_dir, "summary.json"), "w") as f:
            json.dump(summary, f, indent=2)
            
        print(f"[research] Experiment finalized. Metrics saved to {self.exp_dir}")

    def _percentile(self, data, p):
        if not data: return 0
        size = len(data)
        return sorted(data)[int(math.ceil((size * p) / 100)) - 1]
