# automation_tree/execution_planner.py
"""
Hierarchical Execution Planner for Automation Tree.
Transforms passive cache hits into active, verifiable execution plans.

Tuning v2 (2026-02-12):
- Batch I/O: cache loaded ONCE per plan, passed to all helpers
- UIA pattern interfaces for action execution
- Enhanced recovery with Escape-reset
- UI reset (Escape) before plan execution
- Batch self-healing writes via CacheSession
- Per-step timing metrics
"""

import time
import datetime
import json
import os
import sys

from src.harness import locator, verification
from src.automation import storage, fingerprint, builder

# =============================================================================
# CONSTANTS & CONFIG
# =============================================================================

MAX_PLAN_TIMEOUT = 10.0  # Seconds per task
STABILIZATION_TIMEOUT = 1.5  # Seconds
STABILIZATION_INTERVAL = 0.2
MAX_RETRIES = 1
SELF_HEALING_LIMIT = 2

LOG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 
                       "experiments", "stage1_rerun", "execution_log.jsonl")

# =============================================================================
# LOGGING
# =============================================================================

def log_execution(data: dict):
    """Append structured log to execution_log.jsonl."""
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        data["timestamp"] = datetime.datetime.utcnow().isoformat() + "Z"
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(data) + "\n")
    except Exception as e:
        print(f"[planner] Logging failed: {e}")

# =============================================================================
# PLANNER LOGIC
# =============================================================================

def build_execution_plan(app_name: str, target_fingerprint: str, _cache: dict = None) -> list:
    """
    Retrieve exposure path from cache and construct execution plan.
    
    Args:
        app_name: Application name
        target_fingerprint: Target element fingerprint
        _cache: Pre-loaded cache dict (avoids disk read if provided)
    
    Returns:
        List of step dicts: [{"fingerprint": ..., "action": ...}]
    """
    cache = _cache or storage.load_cache(app_name)
    elem = cache.get("elements", {}).get(target_fingerprint)
    
    print(f"[planner] Building plan for {target_fingerprint[:8]}...")
    if elem:
        print(f"[planner] Found element, exposure_path len: {len(elem.get('exposure_path', []))}")
    
    if not elem:
        print(f"[planner] Target {target_fingerprint[:8]} not found in cache.")
        return []
        
    # Get stored exposure path (ancestors)
    exposure_path = elem.get("exposure_path", [])
    
    # Append target itself with its required action
    # Determine target action based on patterns
    target_action = "click"
    if "ExpandCollapsePattern" in elem.get("patterns", []):
        target_action = "expand"
    elif "InvokePattern" in elem.get("patterns", []):
        target_action = "invoke"
        
    full_plan = list(exposure_path)
    full_plan.append({
        "fingerprint": target_fingerprint,
        "action": target_action
    })
    
    print(f"[planner] Built plan with {len(full_plan)} steps for {target_fingerprint[:8]}")
    return full_plan



def execute_execution_plan(window, plan: list, app_name: str, _cache: dict = None) -> bool:
    """
    Execute hierarchical plan with full reliability enforcement.
    
    Tuning v2: Single cache load, per-step timing, UI reset.
    """
    start_time = time.time()
    plan_success = False
    failure_step_index = -1
    recovery_attempts = 0
    total_stabilization_ms = 0
    parent_exposure_failed = False
    step_timings = []
    
    # --- CHANGE 1: Load cache ONCE ---
    cache = _cache or storage.load_cache(app_name)
    
    print(f"[planner] Starting execution (len={len(plan)})...")
    
    # --- CHANGE 5: Universal home state recovery before execution ---
    try:
        from src.harness.ui_state_manager import ensure_home_state
        recovery = ensure_home_state(window, app_name, verbose=True)
        if recovery.get("back_clicks", 0) > 0:
            print(f"[planner] Home recovery: {recovery['back_clicks']} Back click(s)")
        print(f"[planner] UI reset complete (recovered={recovery['recovered']})")
    except Exception as e:
        # Fallback: at minimum try ESC
        try:
            window.type_keys("{ESC}{ESC}", pause=0.1)
            time.sleep(0.3)
            print(f"[planner] UI reset fallback (ESC×2): {e}")
        except:
            print(f"[planner] UI reset skipped: {e}")
    
    # 1. Pre-flight Validation (uses pre-loaded cache)
    if not _validate_start_element(window, plan[0], app_name, cache=cache):
        return False

    # 2. Execute Plan Steps
    for i, step in enumerate(plan):
        step_start = time.time()
        
        # Timeout Check
        if (time.time() - start_time) > MAX_PLAN_TIMEOUT:
            print("[planner] TIMEOUT exceeded.")
            log_execution({
                "execution_method": "PLANNER",
                "plan_success": False, 
                "planner_timeout": True,
                "steps_completed": i,
                "step_timings_ms": step_timings
            })
            return False
            
        if "parent_fingerprint" in step:
            step_fp = step["parent_fingerprint"]
        else:
            step_fp = step["fingerprint"]
            
        action = step["action"]
        # --- CHANGE 1: Use pre-loaded cache instead of disk read ---
        cached_elem = cache.get("elements", {}).get(step_fp, {})
        
        print(f"[planner] Step {i+1}/{len(plan)}: {action} on {step_fp[:8]}")
        
        # A. Locate Target
        elem, info = locator.locate_element_by_fingerprint(window, step_fp, cached_elem)
        
        # B. Partial Recovery
        if not elem:
            print(f"[planner] Step target missing. Attempting recovery...")
            elem, info = _recover_step(window, cached_elem)
            if elem:
                recovery_attempts += 1
                
        if not elem:
            print(f"[planner] Critical Failure: Could not locate element at step {i}.")
            failure_step_index = i
            step_ms = int((time.time() - step_start) * 1000)
            step_timings.append({"step": i, "ms": step_ms, "status": "LOCATE_FAILED"})
            break
            
        # C. Execute Action (CHANGE 3: UIA pattern interfaces)
        if not _execute_action_on_element(elem, action):
            print(f"[planner] Action execution failed.")
            failure_step_index = i
            step_ms = int((time.time() - step_start) * 1000)
            step_timings.append({"step": i, "ms": step_ms, "status": "ACTION_FAILED"})
            break
            
        # D. Verify Exposure (Parent Enforcement)
        if i < len(plan) - 1:
            next_step = plan[i+1]
            if not _verify_path_continuity(window, elem, next_step, app_name, cache=cache):
                print(f"[planner] Parent Enforcement Failed: Child {next_step['fingerprint'][:8]} did not appear.")
                parent_exposure_failed = True
                failure_step_index = i
                step_ms = int((time.time() - step_start) * 1000)
                step_timings.append({"step": i, "ms": step_ms, "status": "EXPOSURE_FAILED"})
                break
        else:
            time.sleep(0.5) # Final stabilize

        # --- CHANGE 7: Per-step timing ---
        step_ms = int((time.time() - step_start) * 1000)
        step_timings.append({"step": i, "ms": step_ms, "status": "OK"})
        print(f"[planner] Step {i+1} completed in {step_ms}ms")

    # End Loop
    if failure_step_index == -1:
        plan_success = True
        print("[planner] Execution Successful.")
    else:
        print("[planner] Execution Failed.")

    total_ms = int((time.time() - start_time) * 1000)

    # Log Metrics
    log_execution({
        "execution_method": "PLANNER",
        "plan_length": len(plan),
        "steps_completed": failure_step_index if failure_step_index != -1 else len(plan),
        "plan_success": plan_success,
        "failure_step_index": failure_step_index,
        "recovery_attempts": recovery_attempts,
        "parent_exposure_failed": parent_exposure_failed,
        "planner_timeout": False,
        "total_ms": total_ms,
        "step_timings_ms": step_timings
    })
    
    return plan_success


def _validate_start_element(window, step: dict, app_name: str, cache: dict = None) -> bool:
    """Ensure the starting element of the plan is visible."""
    if "parent_fingerprint" in step:
        fp = step["parent_fingerprint"]
    else:
        fp = step["fingerprint"]
    
    # --- CHANGE 1: Use provided cache ---
    _cache = cache or storage.load_cache(app_name)
    cached_node = _cache.get("elements", {}).get(fp, {})
    
    elem, _ = locator.locate_element_by_fingerprint(window, fp, cached_metadata=cached_node)
    
    if not elem:
        # Try recovery
        elem, _ = locator.recover_element(window, cached_node)
        
    if not elem:
        print(f"[planner] Pre-flight failed: Start element {fp[:8]} not found.")
        return False
        
    print("[planner] Pre-flight validation SUCCESS.")
    return True


def _execute_action_on_element(elem, action: str) -> bool:
    """
    Execute the specific action on the element.
    
    CHANGE 3: Uses UIA pattern interface detection (iface_*) 
    aligned with ax_executor.execute_element for reliability.
    """
    try:
        if action == "expand":
            if hasattr(elem, 'iface_expand_collapse') and elem.iface_expand_collapse:
                elem.expand()
                print("[planner] ExpandCollapsePattern succeeded")
            else:
                elem.click_input()
                print("[planner] click_input fallback for expand")
        elif action == "invoke":
            if hasattr(elem, 'iface_invoke') and elem.iface_invoke:
                elem.invoke()
                print("[planner] InvokePattern succeeded")
            else:
                elem.click_input()
                print("[planner] click_input fallback for invoke")
        elif action == "select":
            if hasattr(elem, 'iface_selection_item') and elem.iface_selection_item:
                elem.select()
                print("[planner] SelectionItemPattern succeeded")
            else:
                elem.click_input()
                print("[planner] click_input fallback for select")
        else:
            elem.click_input()
            print("[planner] click_input executed")
        return True
    except Exception as e:
        print(f"[planner] Action error: {e}")
        return False


def _recover_step(window, cached_node: dict):
    """
    Encapsulated step recovery strategy.
    
    CHANGE 4: Escape-reset before recovery attempt.
    """
    # 1. Reset UI state to dismiss any leftover menus/popups
    try:
        window.type_keys("{ESC}", pause=0.1)
        time.sleep(0.3)
        print("[planner] Recovery: UI reset (ESC) sent.")
    except Exception:
        pass
    
    # 2. Standard recovery using locator
    return locator.recover_element(window, cached_node)


def _verify_path_continuity(window, parent_elem, next_step: dict, app_name: str, cache: dict = None) -> bool:
    """
    Verify that executing action on parent actually exposed the child.
    Includes stabilization loop and ONE retry interaction.
    """
    if "parent_fingerprint" in next_step:
        next_fp = next_step["parent_fingerprint"]
    else:
        next_fp = next_step["fingerprint"]
    
    # --- CHANGE 1: Use provided cache ---
    _cache = cache or storage.load_cache(app_name)
    cached_next = _cache.get("elements", {}).get(next_fp, {})
    
    # Wait/Stabilize
    start = time.time()
    found = False
    while (time.time() - start) < STABILIZATION_TIMEOUT:
        try:
            child, _ = locator.locate_element_by_fingerprint(window, next_fp, cached_metadata=cached_next)
            if child:
                found = True
                break
        except:
            pass
        time.sleep(STABILIZATION_INTERVAL)
        
    if found:
        return True
        
    # Retry Action logic
    print(f"[planner] Verification failed for {next_fp[:8]}. Retrying parent action...")
    try:
        # Hard retry: click input again
        parent_elem.click_input()
        time.sleep(0.5)
        
        # Check again
        child, _ = locator.locate_element_by_fingerprint(window, next_fp, cached_metadata=cached_next)
        if child:
            print("[planner] Retry SUCCESS.")
            return True
    except Exception as e:
        print(f"[planner] Retry action failed: {e}")
        
    return False


def execute_with_self_healing(window, app_name: str, target_fingerprint: str) -> bool:
    """
    Execute plan with self-healing capabilities.
    If execution fails twice, regenerate tree/cache and retry.
    """
    # Load cache once for the entire self-healing loop
    cache = storage.load_cache(app_name)
    
    for attempt in range(SELF_HEALING_LIMIT + 1):
        # 1. Build Plan (pass cache to avoid reload)
        plan = build_execution_plan(app_name, target_fingerprint, _cache=cache)
        
        if not plan:
            print("[planner] No plan available (target not in cache).")
            return False
            
        # 2. Execute active plan (pass cache to avoid reload)
        success = execute_execution_plan(window, plan, app_name, _cache=cache)
        
        if success:
            return True
            
        # 3. Handle Failure & Self-Healing
        print(f"[planner] Plan execution failed (Attempt {attempt+1}/{SELF_HEALING_LIMIT + 1})")
        
        if attempt < SELF_HEALING_LIMIT:
            print("[planner] Triggering SELF-HEALING: Re-building tree & updating cache...")
            try:
                # Re-build tree to get fresh exposure paths
                tree = builder.build_tree_from_window(window, app_name)
                
                # --- CHANGE 6: Batch writes via CacheSession ---
                _update_cache_from_tree(app_name, tree["root"])
                
                # Reload cache after self-healing update
                cache = storage.load_cache(app_name)
                
                log_execution({
                    "execution_method": "PLANNER",
                    "exposure_path_regenerated": True,
                    "attempt": attempt + 1
                })
                
            except Exception as e:
                print(f"[planner] Self-healing error: {e}")
                return False
        else:
            print("[planner] Self-healing exhausted. Aborting.")
            
    return False


def _update_cache_from_tree(app_name: str, root_node: dict):
    """
    Recursively update cache from a fresh tree node.
    
    CHANGE 6: Uses CacheSession for batch I/O instead of
    per-element storage.add_element() calls.
    """
    session = storage.CacheSession(app_name)
    _walk_and_add(session, root_node)
    session.flush()
    print(f"[planner] Self-healing batch write: {session.stats}")


def _walk_and_add(session, node: dict):
    """Recursively walk tree and add nodes to CacheSession."""
    try:
        fp = fingerprint.compute_fingerprint(node, node.get("path", ""))
        session.add(fp, node, discovery_method="SELF_HEALING")
        for child in node.get("children", []):
            _walk_and_add(session, child)
    except:
        pass
