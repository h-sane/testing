# harness/locator.py
"""
Element locator for cache-based execution.
Finds live elements matching cached fingerprints.
Includes Desktop-level window re-acquisition fallback for UI state changes.
"""

import sys
import os
import time
from typing import Optional, Tuple, Any, Dict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.automation import fingerprint, storage


# =============================================================================
# COM-RESILIENT UIA ACCESS
# =============================================================================

def _safe_descendants(window, retries=2):
    """Get descendants with COM error resilience for Chromium-based apps."""
    for attempt in range(retries):
        try:
            return window.descendants()
        except Exception as e:
            if "-2147220991" in str(e) and attempt < retries - 1:
                print(f"[locator] COM error, refocusing window (attempt {attempt+1})...")
                try:
                    window.set_focus()
                    time.sleep(0.5)
                except:
                    pass
            else:
                raise
    return []


def _reacquire_toplevel_window(window):
    """
    Re-acquire the top-level window from Desktop when the current window
    handle may be scoped to a child pane (e.g. after Settings click in
    Win11 Notepad changes the UIA tree scope).
    
    Returns a window wrapper with more descendants (including menu bar),
    or the original window if re-acquisition fails.
    """
    try:
        from pywinauto import Desktop
        title = ""
        try:
            title = window.window_text() or ""
        except:
            pass
        
        if not title:
            return window
        
        desktop = Desktop(backend="uia")
        for w in desktop.windows():
            try:
                wt = w.window_text() or ""
                if wt and (title in wt or wt in title):
                    new_descs = w.descendants()
                    old_descs = _safe_descendants(window)
                    if len(new_descs) > len(old_descs):
                        print(f"[locator] Desktop re-acquisition: {len(old_descs)} -> {len(new_descs)} descendants")
                        return w
            except:
                continue
    except Exception as e:
        print(f"[locator] Desktop re-acquisition failed: {e}")
    
    return window


def _score_element(elem, target_name, target_type, target_aid):
    """Score a single element against target properties. Returns (score, name, ctype, aid)."""
    name = ""
    try: name = (elem.window_text() or "").lower().strip()
    except: pass
    if not name:
        try: name = (getattr(elem.element_info, 'name', "") or "").lower().strip()
        except: pass
    
    ctype = ""
    try: ctype = (str(elem.element_info.control_type) or "").lower().strip()
    except: pass
    
    aid = ""
    try: aid = (getattr(elem.element_info, 'automation_id', "") or "").lower().strip()
    except: pass
    
    score = 0.0
    
    # Name (50%)
    if target_name and name:
        if target_name == name:
            score += 0.5
        elif target_name in name or name in target_name:
            score += 0.4
    elif not target_name and not name:
        score += 0.5
    
    # Automation ID (30%)
    if target_aid and aid:
        if target_aid == aid:
            score += 0.3
        elif target_aid in aid:
            score += 0.25
    elif not target_aid and not aid:
        score += 0.3
    
    # Control Type (20%)
    if target_type and ctype:
        if target_type == ctype:
            score += 0.2
        else:
            score -= 0.1
    
    return score, name, ctype, aid


# =============================================================================
# ELEMENT LOCATOR
# =============================================================================

def _search_descendants(descendants, target_name, target_type, target_aid, target_fingerprint, log_prefix=""):
    """Search a list of descendants for the best matching element."""
    best_elem = None
    best_info = {}
    best_score = 0.0
    
    for elem in descendants:
        try:
            score, name, ctype, aid = _score_element(elem, target_name, target_type, target_aid)
            
            if score > 0.4:
                print(f"[locator]{log_prefix} CANDIDATE: '{name}' Type='{ctype}' Score={score:.2f}")
            
            if score > best_score:
                best_score = score
                best_elem = elem
                best_info = {
                    "name": name,
                    "control_type": ctype,
                    "automation_id": aid,
                    "match_type": "weighted_property"
                }
                if score >= 0.95:
                    break
        except:
            continue
    
    return best_elem, best_info, best_score


def locate_element_by_fingerprint(window, target_fingerprint: str, cached_metadata: dict = None) -> Tuple[Any, Dict]:
    """
    Locate a live element matching the cached properties.
    Uses robust property matching with Desktop-level fallback.
    
    If element is not found in the current window's descendants,
    re-acquires the top-level window from Desktop and retries.
    This handles cases where the UIA tree scope changes after
    UI interactions (e.g. Settings pane in Win11 Notepad).
    
    Args:
        window: pywinauto window
        target_fingerprint: Expected fingerprint from cache
        cached_metadata: Optional metadata (name, control_type, etc.)
    
    Returns:
        Tuple of (element, info_dict) or (None, {})
    """
    try:
        target_name = (cached_metadata.get("name") or "").lower().strip()
        target_type = (cached_metadata.get("control_type") or "").lower().strip()
        target_aid = (cached_metadata.get("automation_id") or "").lower().strip()
        
        # --- Pass 1: Search current window ---
        descendants = _safe_descendants(window)
        print(f"[locator] Scanning {len(descendants)} descendants for {target_fingerprint[:8]}")
        
        best_elem, best_info, best_score = _search_descendants(
            descendants, target_name, target_type, target_aid, target_fingerprint
        )
        
        print(f"[locator] Best: {best_info.get('name', '?')} Score={best_score:.2f}")

        if best_score >= 0.7:
            print(f"[locator] Match Found: '{best_info.get('name')}' (Score={best_score:.2f})")
            return best_elem, best_info
        
        # --- Pass 2: Desktop re-acquisition fallback ---
        print(f"[locator] Pass 1 failed (score={best_score:.2f}). Trying Desktop re-acquisition...")
        toplevel = _reacquire_toplevel_window(window)
        
        if toplevel is not window:
            descendants2 = _safe_descendants(toplevel)
            print(f"[locator] Re-acquired window: scanning {len(descendants2)} descendants")
            
            best_elem2, best_info2, best_score2 = _search_descendants(
                descendants2, target_name, target_type, target_aid, target_fingerprint,
                log_prefix=" [reacq]"
            )
            
            if best_score2 >= 0.7:
                print(f"[locator] Desktop fallback Match: '{best_info2.get('name')}' (Score={best_score2:.2f})")
                return best_elem2, best_info2
            else:
                print(f"[locator] Desktop fallback also failed (score={best_score2:.2f})")
        
        print(f"[locator] No match found (Best Score={best_score:.2f})")
        return None, {}
        
    except Exception as e:
        print(f"[locator] Error: {e}")
        return None, {}


def compute_fuzzy_score(cached: dict, name: str, auto_id: str, control_type: str) -> float:
    """Legacy helper, now localized."""
    return 0.0 # Unused



def recover_element(
    window, 
    cached_node: dict, 
    min_confidence: float = 0.8
) -> Tuple[Any, Dict]:
    """
    Attempt to recover an element when fingerprint match fails.
    Uses weighted scoring with Desktop-level fallback.
    
    Args:
        window: Root window to search
        cached_node: Original cached node data
        min_confidence: Threshold for recovery acceptance
        
    Returns:
        (element, info_dict) or (None, {})
    """
    print(f"[locator] Recovery: searching for '{cached_node.get('name')}'...")
    
    target_name = (cached_node.get("name") or "").lower().strip()
    target_type = (cached_node.get("control_type") or "").lower().strip()
    target_aid = (cached_node.get("automation_id") or "").lower().strip()
    
    # Try both current window and Desktop re-acquired window
    windows_to_try = [window]
    toplevel = _reacquire_toplevel_window(window)
    if toplevel is not window:
        windows_to_try.append(toplevel)
    
    for w in windows_to_try:
        candidates = []
        try:
            descendants = _safe_descendants(w)
            
            for elem in descendants:
                score, name, ctype, aid = _score_element(elem, target_name, target_type, target_aid)
                
                if score >= min_confidence:
                    candidates.append((score, elem, name, ctype, aid))
            
            candidates.sort(key=lambda x: x[0], reverse=True)
            
            if candidates:
                best = candidates[0]
                print(f"[locator] Recovery SUCCESS: Found '{best[2]}' ({best[3]}) Score={best[0]:.2f}")
                
                info = {
                    "name": best[2],
                    "control_type": best[3],
                    "automation_id": best[4],
                    "score": best[0],
                    "match_type": "recovery"
                }
                try:
                    r = best[1].rectangle()
                    info["rect"] = [r.left, r.top, r.right - r.left, r.bottom - r.top]
                except:
                    pass
                    
                return best[1], info
                
        except Exception as e:
            print(f"[locator] Recovery Error: {e}")
        
    print(f"[locator] Recovery FAILED.")
    return None, {}
