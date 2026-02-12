"""
Script to compute grounded metrics from all experiment logs.
Produces a JSON summary for the scientific report.
"""
import json
import os
import datetime

EXPERIMENTS_DIR = "experiments"
CACHE_DIR = ".cache"

def scan_execution_logs():
    """Scan all execution_log.jsonl files and compute metrics."""
    all_entries = []
    log_sources = []

    for base_dir in [EXPERIMENTS_DIR, "runs"]:
        if not os.path.exists(base_dir): continue
        for root, dirs, files in os.walk(base_dir):
            for f in files:
                if f == "execution_log.jsonl":
                    path = os.path.join(root, f)
                    try:
                        with open(path, "r", encoding="utf-8") as fh:
                            lines = fh.readlines()
                        entries = []
                        for line in lines:
                            try:
                                entries.append(json.loads(line.strip()))
                            except:
                                pass
                        if entries:
                            log_sources.append({"path": path, "count": len(entries)})
                            all_entries.extend(entries)
                    except Exception as e:
                        print(f"Error reading {path}: {e}")

    return all_entries, log_sources


def compute_metrics(entries):
    """Compute all metrics from execution log entries."""
    methods = {}
    apps = {}
    success_count = 0
    fail_count = 0
    planner_entries = []

    for e in entries:
        m = e.get("execution_method", "UNKNOWN")
        s = e.get("success", e.get("plan_success", False))
        a = e.get("app_name", "UNKNOWN")

        # Method breakdown
        if m not in methods:
            methods[m] = {"total": 0, "success": 0, "fail": 0}
        methods[m]["total"] += 1
        if s:
            methods[m]["success"] += 1
            success_count += 1
        else:
            methods[m]["fail"] += 1
            fail_count += 1

        # App breakdown
        if a not in apps:
            apps[a] = {"total": 0, "success": 0, "fail": 0}
        apps[a]["total"] += 1
        if s:
            apps[a]["success"] += 1
        else:
            apps[a]["fail"] += 1

        # Planner-specific
        if m == "PLANNER":
            planner_entries.append(e)

    return {
        "total_entries": len(entries),
        "success_count": success_count,
        "fail_count": fail_count,
        "success_rate": round(100 * success_count / max(1, len(entries)), 2),
        "by_method": methods,
        "by_app": apps,
        "planner_count": len(planner_entries),
        "planner_details": [
            {
                "steps": pe.get("plan_length", "?"),
                "success": pe.get("plan_success", pe.get("success")),
                "timeout": pe.get("planner_timeout", False),
                "recovery": pe.get("recovery_attempts", 0),
            }
            for pe in planner_entries[:20]
        ],
    }


def scan_cache_files():
    """Scan all cache .json files and report element counts."""
    cache_stats = {}
    if not os.path.exists(CACHE_DIR):
        return cache_stats

    for f in os.listdir(CACHE_DIR):
        if f.endswith(".json"):
            path = os.path.join(CACHE_DIR, f)
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    c = json.load(fh)
                elems = c.get("elements", {})
                cache_stats[f.replace(".json", "")] = {
                    "element_count": len(elems),
                    "last_updated": c.get("last_updated", "unknown"),
                }
            except Exception as e:
                cache_stats[f] = {"error": str(e)}

    return cache_stats


def scan_verification_logs():
    """Scan all verification_log.jsonl files."""
    all_entries = []
    for root, dirs, files in os.walk(EXPERIMENTS_DIR):
        for f in files:
            if f == "verification_log.jsonl":
                path = os.path.join(root, f)
                try:
                    with open(path, "r", encoding="utf-8") as fh:
                        for line in fh:
                            try:
                                all_entries.append(json.loads(line.strip()))
                            except:
                                pass
                except:
                    pass
    return all_entries


def main():
    print("=" * 60)
    print("EXPERIMENT DATA EXTRACTION")
    print("=" * 60)

    # 1. Execution logs
    entries, sources = scan_execution_logs()
    print(f"\nTotal execution_log.jsonl files: {len(sources)}")
    print(f"Total execution entries: {len(entries)}")
    for s in sources:
        print(f"  {s['path']}: {s['count']} entries")

    metrics = compute_metrics(entries)
    print(f"\nSuccess: {metrics['success_count']}/{metrics['total_entries']} ({metrics['success_rate']}%)")
    print(f"Failed: {metrics['fail_count']}/{metrics['total_entries']}")

    print("\nBy Method:")
    for m, c in sorted(metrics["by_method"].items()):
        rate = round(100 * c["success"] / max(1, c["total"]), 1)
        print(f"  {m}: {c['success']}/{c['total']} ({rate}%)")

    print("\nBy Application:")
    for a, c in sorted(metrics["by_app"].items()):
        rate = round(100 * c["success"] / max(1, c["total"]), 1)
        print(f"  {a}: {c['success']}/{c['total']} ({rate}%)")

    print(f"\nPLANNER entries: {metrics['planner_count']}")
    for pd in metrics["planner_details"]:
        print(f"  steps={pd['steps']}, success={pd['success']}, timeout={pd['timeout']}, recovery={pd['recovery']}")

    # 2. Cache stats
    print("\nCache Stats:")
    cache_stats = scan_cache_files()
    for name, info in sorted(cache_stats.items()):
        print(f"  {name}: {info}")

    # 3. Verification logs
    ver_entries = scan_verification_logs()
    print(f"\nVerification log entries: {len(ver_entries)}")
    ver_success = sum(1 for v in ver_entries if v.get("success"))
    ver_fail = sum(1 for v in ver_entries if not v.get("success"))
    print(f"  Success: {ver_success}, Fail: {ver_fail}")

    # 4. Save summary
    summary = {
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
        "execution_metrics": metrics,
        "cache_stats": cache_stats,
        "verification_summary": {
            "total": len(ver_entries),
            "success": ver_success,
            "fail": ver_fail,
        },
        "log_sources": sources,
    }

    os.makedirs("results", exist_ok=True)
    with open("results/experiment_data_summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nSaved to results/experiment_data_summary.json")


if __name__ == "__main__":
    main()
