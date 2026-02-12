# harness/ax_executor.py
"""
AX Executor using hardened matcher logic.
Executes UI actions via Windows Accessibility (UIA).
Includes keyboard fallback for menu actions.
"""

import sys
import os
import time
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.automation import matcher, storage, fingerprint, builder
from src.harness.locator import locate_element_by_fingerprint
from src.harness import config


# =============================================================================
# CONFIGURATION
# =============================================================================

AUTO_EXECUTE_THRESHOLD = 0.82
VERIFY_THRESHOLD_LOW = 0.65

RUNS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "experiments")
DEBUG_LOG_PATH = os.path.join(RUNS_DIR, "matcher_debug.log")


# =============================================================================
# DEBUG LOGGING
# =============================================================================

def log_candidate(
    app_name: str,
    task: str,
    candidate_name: str,
    score: float,
    source: str,
    action: str
):
    """Log candidate examination to matcher_debug.log."""
    try:
        os.makedirs(RUNS_DIR, exist_ok=True)
        ts = datetime.datetime.now().isoformat()
        line = (
            f"{ts} | APP={app_name} | TASK=\"{task[:40]}\" | "
            f"CAND=\"{candidate_name[:30]}\" | SCORE={score:.3f} | "
            f"SOURCE={source} | ACTION={action}\n"
        )
        with open(DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


# =============================================================================
# ELEMENT SEARCH
# =============================================================================

def search_elements(window, task: str, app_name: str) -> list:
    """
    Search window descendants for elements matching task.
    Uses hardened matcher.match_score() for scoring.
    Returns list of (element, score, name) sorted by score desc.
    """
    results = []
    
    try:
        descendants = window.descendants()
        print(f"[ax_executor] Scanning {len(descendants)} elements...")
        
        for elem in descendants:
            try:
                # Get element properties
                name = ""
                try:
                    name = elem.window_text() or ""
                except:
                    pass
                if not name:
                    try:
                        name = getattr(elem.element_info, 'name', "") or ""
                    except:
                        pass
                
                if not name or len(name.strip()) < 1:
                    continue
                
                auto_id = ""
                try:
                    auto_id = getattr(elem.element_info, 'automation_id', "") or ""
                except:
                    pass
                
                # Use hardened matcher
                from src.harness import config
                app_meta = config.get_app_config(app_name)
                
                result = matcher.match_score(
                    task=task,
                    element_name=name,
                    element_auto_id=auto_id,
                    tasks_succeeded=[],
                    app_metadata=app_meta
                )
                score = result["score"]
                
                if score >= 0.3:  # Only log meaningful candidates
                    log_candidate(app_name, task, name, score, "ax_search", "evaluated")
                
                if score >= VERIFY_THRESHOLD_LOW:
                    results.append((elem, score, name, auto_id))
                    
            except Exception:
                continue
                
    except Exception as e:
        print(f"[ax_executor] Error scanning: {e}")
    
    # Sort by score descending
    results.sort(key=lambda x: x[1], reverse=True)
    return results


# =============================================================================
# ELEMENT EXECUTION
# =============================================================================

def execute_element(elem, name: str) -> bool:
    """Execute action on element. Returns True if successful."""
    
    # Try InvokePattern
    try:
        if hasattr(elem, 'iface_invoke') and elem.iface_invoke:
            elem.invoke()
            print(f"[ax_executor] InvokePattern succeeded")
            return True
    except Exception as e:
        pass
    
    # Try ExpandCollapsePattern
    try:
        if hasattr(elem, 'iface_expand_collapse') and elem.iface_expand_collapse:
            elem.expand()
            print(f"[ax_executor] ExpandCollapsePattern succeeded")
            return True
    except Exception:
        pass
    
    # Try SelectionItemPattern
    try:
        if hasattr(elem, 'iface_selection_item') and elem.iface_selection_item:
            elem.select()
            print(f"[ax_executor] SelectionItemPattern succeeded")
            return True
    except Exception:
        pass
    
    # Fallback: click_input
    try:
        elem.click_input()
        print(f"[ax_executor] click_input succeeded")
        return True
    except Exception as e:
        print(f"[ax_executor] click_input failed: {e}")
    
    return False


def cache_element(app_name: str, elem, name: str, auto_id: str, task: str):
    """Cache a successfully executed element."""
    try:
        # Build node dict for fingerprinting
        rect = None
        try:
            r = elem.rectangle()
            rect = [r.left, r.top, r.right - r.left, r.bottom - r.top]
        except:
            pass
        
        control_type = ""
        try:
            control_type = str(elem.element_info.control_type) if elem.element_info.control_type else ""
        except:
            pass
        
        node = {
            "name": name[:200],
            "control_type": control_type,
            "automation_id": auto_id[:200] if auto_id else "",
            "rect": rect,
            "patterns": [],
            "sibling_index": 0,
            "path": ""
        }
        
        fp = fingerprint.compute_fingerprint(node, "")
        storage.add_element(app_name, fp, node, discovery_method="AX")
        storage.record_success(app_name, fp, task)
        
    except Exception as e:
        print(f"[ax_executor] Error caching: {e}")


# =============================================================================
# KEYBOARD FALLBACK
# =============================================================================

def is_menu_action(task: str) -> bool:
    """Check if task looks like a menu action."""
    tokens = matcher.tokenize_and_normalize(task)
    return "menu" in tokens or ("help" in tokens)


def get_keyboard_fallback(app_name: str, task: str) -> str:
    """Get keyboard shortcut for menu action."""
    fallbacks = config.KEYBOARD_FALLBACKS.get(app_name, {})
    
    # Check for exact task match
    task_key = task.lower().replace(" ", "_")
    if task_key in fallbacks:
        return fallbacks[task_key]
    
    # Check for partial match
    for key, shortcut in fallbacks.items():
        if key in task.lower():
            return shortcut
    
    # Generic: Alt + first letter of menu word
    tokens = matcher.tokenize_and_normalize(task)
    for token in tokens:
        if token not in {"menu", "click", "open", "press"} and len(token) > 0:
            first_letter = token[0].upper()
            if first_letter.isalpha():
                return f"%{first_letter}"  # Alt + letter
    
    return None


def try_keyboard_fallback(window, app_name: str, task: str) -> bool:
    """Attempt keyboard fallback for menu action."""
    shortcut = get_keyboard_fallback(app_name, task)
    
    if not shortcut:
        print(f"[ax_executor] No keyboard fallback for '{task}'")
        return False
    
    print(f"[ax_executor] Trying keyboard fallback: {shortcut}")
    
    try:
        window.type_keys(shortcut, pause=0.1)
        time.sleep(0.3)
        print(f"[ax_executor] Keyboard fallback sent: {shortcut}")
        log_candidate(app_name, task, f"KEYBOARD:{shortcut}", 1.0, "keyboard", "executed")
        return True
    except Exception as e:
        print(f"[ax_executor] Keyboard fallback failed: {e}")
        return False


# =============================================================================
# BUILDER RESCAN
# =============================================================================

def rescan_tree(window, app_name: str) -> bool:
    """Force builder rescan to refresh element tree."""
    print(f"[ax_executor] Forcing builder rescan...")
    try:
        tree = builder.build_tree_from_window(window, app_name)
        if tree and tree.get("root"):
            print(f"[ax_executor] Rescan found {builder.count_nodes(tree['root'])} nodes")
            return True
    except Exception as e:
        print(f"[ax_executor] Rescan failed: {e}")
    return False


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def find_and_execute(
    window,
    task: str,
    app_name: str,
    min_confidence: float = AUTO_EXECUTE_THRESHOLD
) -> dict:
    """
    Find and execute element matching task using hardened matcher.
    
    Flow:
    1. Search elements using matcher.match_score()
    2. If confident match found (>= 0.82), execute immediately
    3. If verify-band match (0.65-0.82), execute with verification flag
    4. If no match, try keyboard fallback for menu actions
    5. Return result dict
    """
    print(f"[ax_executor] Searching for: '{task}'")
    
    result = {
        "element_found": False,
        "executed": False,
        "score": 0.0,
        "name": "",
        "method": "none",
        "patterns": [],
        "error": None,
        "requires_verification": False
    }
    
    # Search elements
    candidates = search_elements(window, task, app_name)
    
    if candidates:
        best_elem, best_score, best_name, best_auto_id = candidates[0]
        result["element_found"] = True
        result["score"] = best_score
        result["name"] = best_name
        
        print(f"[ax_executor] Found: '{best_name}' (score={best_score:.2f})")
        
        # Check confidence level
        if best_score >= min_confidence:
            # High confidence - execute
            log_candidate(app_name, task, best_name, best_score, "ax_search", "executed")
            
            if execute_element(best_elem, best_name):
                result["executed"] = True
                result["method"] = "ax_direct"
                cache_element(app_name, best_elem, best_name, best_auto_id, task)
                return result
            else:
                result["error"] = "Execution failed"
                
        elif best_score >= VERIFY_THRESHOLD_LOW:
            # Verify band - execute with flag
            print(f"[ax_executor] Verify-band match, proceeding with caution")
            result["requires_verification"] = True
            log_candidate(app_name, task, best_name, best_score, "ax_search", "executed_verify")
            
            if execute_element(best_elem, best_name):
                result["executed"] = True
                result["method"] = "ax_verify"
                cache_element(app_name, best_elem, best_name, best_auto_id, task)
                return result
        else:
            log_candidate(app_name, task, best_name, best_score, "ax_search", "skipped")
            print(f"[ax_executor] Score {best_score:.2f} below threshold {VERIFY_THRESHOLD_LOW}")
    else:
        print(f"[ax_executor] No confident match (best score below threshold)")
    
    # Try keyboard fallback for menu actions
    if is_menu_action(task):
        print(f"[ax_executor] Attempting keyboard fallback for menu action...")
        
        if try_keyboard_fallback(window, app_name, task):
            result["executed"] = True
            result["method"] = "keyboard"
            return result
    
    # If still no success, try rescan + retry
    if not result["executed"]:
        rescan_tree(window, app_name)
        
        # Retry search after rescan
        candidates = search_elements(window, task, app_name)
        
        if candidates:
            best_elem, best_score, best_name, best_auto_id = candidates[0]
            
            if best_score >= VERIFY_THRESHOLD_LOW:
                print(f"[ax_executor] After rescan: '{best_name}' (score={best_score:.2f})")
                log_candidate(app_name, task, best_name, best_score, "ax_rescan", "executed")
                
                if execute_element(best_elem, best_name):
                    result["executed"] = True
                    result["element_found"] = True
                    result["score"] = best_score
                    result["name"] = best_name
                    result["method"] = "ax_rescan"
                    cache_element(app_name, best_elem, best_name, best_auto_id, task)
                    return result
    
    if not result["executed"]:
        result["error"] = "No confident match found"
    
    return result
