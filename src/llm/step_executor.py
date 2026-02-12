# src/llm/step_executor.py
"""
Step Executor: Bridges LLM-planned steps to the existing 3-tier execution engine.

Translates structured action dicts from the orchestrator into concrete UI actions
via the Cache → AX → Vision pipeline, plus direct pyautogui for TYPE/HOTKEY.
"""

import os
import sys
import time
import logging
from typing import Dict, Any, Optional, Tuple

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

logger = logging.getLogger("step_executor")


# =============================================================================
# ACTION HANDLERS
# =============================================================================

def execute_click(
    window, 
    target: str, 
    app_name: str,
    use_cache: bool = True,
    use_vision: bool = True
) -> Dict[str, Any]:
    """
    Execute a CLICK action using the 3-tier strategy: Cache → AX → Vision.
    
    Args:
        window: pywinauto window wrapper
        target: Element label/name to click (e.g., "File", "Open")
        app_name: Application name for cache lookup
        use_cache: Enable cache tier
        use_vision: Enable vision tier
    
    Returns:
        Result dict with keys: success, method, element_name, error
    """
    result = {"success": False, "method": "FAILED", "element_name": target, "error": ""}
    
    # --- Tier 1: Cache + Planner ---
    if use_cache:
        try:
            from src.automation import matcher, execution_planner
            
            cached = matcher.find_cached_element(app_name, target, min_confidence=0.6)
            if cached and cached.get("score", 0) >= 0.8:
                fp = cached.get("fingerprint")
                logger.info(f"[step_executor] Cache hit for '{target}' (score={cached['score']:.2f}, fp={fp[:8]})")
                
                success = execution_planner.execute_with_self_healing(window, app_name, fp)
                if success:
                    result["success"] = True
                    result["method"] = "CACHE_PLANNER"
                    return result
                else:
                    logger.info(f"[step_executor] Planner failed for '{target}', falling through")
        except Exception as e:
            logger.warning(f"[step_executor] Cache/Planner error: {e}")
    
    # --- Tier 2: AX Direct ---
    try:
        from src.harness import ax_executor
        
        ax_result = ax_executor.find_and_execute(window, target, app_name, min_confidence=0.6)
        if ax_result.get("executed", False):
            result["success"] = True
            result["method"] = "AX"
            return result
    except Exception as e:
        logger.warning(f"[step_executor] AX error: {e}")
    
    # --- Tier 3: Vision (VLM) ---
    if use_vision:
        try:
            from src.harness import vision_executor
            
            vision_result = vision_executor.detect_and_click(
                window, target, app_name,
                run_id="llm_orchestrator",
                timeout=20.0
            )
            if vision_result.clicked:
                result["success"] = True
                result["method"] = "VISION"
                return result
            else:
                result["error"] = vision_result.error or "VLM found no matches"
        except Exception as e:
            logger.warning(f"[step_executor] Vision error: {e}")
            result["error"] = str(e)
    
    result["method"] = "FAILED"
    return result


def execute_type(text: str) -> Dict[str, Any]:
    """
    Execute a TYPE action using pyautogui.
    
    Args:
        text: Text to type
    
    Returns:
        Result dict with success status
    """
    result = {"success": False, "method": "TYPE", "error": ""}
    
    try:
        import pyautogui
        pyautogui.PAUSE = 0.05
        
        # Type with interval between characters
        pyautogui.typewrite(text, interval=0.02) if text.isascii() else pyautogui.write(text)
        
        result["success"] = True
        logger.info(f"[step_executor] Typed {len(text)} chars")
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"[step_executor] Type failed: {e}")
    
    return result


def execute_hotkey(keys: str) -> Dict[str, Any]:
    """
    Execute a HOTKEY action using pyautogui.
    
    Args:
        keys: Key combination string (e.g., "ctrl+s", "ctrl+shift+n", "alt+f4")
    
    Returns:
        Result dict with success status
    """
    result = {"success": False, "method": "HOTKEY", "error": ""}
    
    try:
        import pyautogui
        
        # Parse keys: "ctrl+s" -> ["ctrl", "s"]
        key_list = [k.strip().lower() for k in keys.split("+")]
        
        pyautogui.hotkey(*key_list)
        time.sleep(0.3)  # Brief pause for UI to process
        
        result["success"] = True
        logger.info(f"[step_executor] Hotkey: {'+'.join(key_list)}")
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"[step_executor] Hotkey failed: {e}")
    
    return result


def execute_wait(seconds: float = 1.0) -> Dict[str, Any]:
    """Execute a WAIT action."""
    time.sleep(seconds)
    return {"success": True, "method": "WAIT", "error": ""}


# =============================================================================
# DISPATCHER
# =============================================================================

def execute_step(
    action: Dict[str, Any],
    window=None,
    app_name: str = ""
) -> Dict[str, Any]:
    """
    Route a single LLM-planned step to the appropriate handler.
    
    Args:
        action: Dict with keys:
            - action_type: "CLICK" | "TYPE" | "HOTKEY" | "WAIT"
            - target: Element label (for CLICK)
            - text: Text to type (for TYPE)
            - keys: Key combo (for HOTKEY)
            - seconds: Wait duration (for WAIT)
        window: pywinauto window (required for CLICK)
        app_name: App name for cache (required for CLICK)
    
    Returns:
        Result dict from the handler
    """
    action_type = action.get("action_type", "").upper()
    
    if action_type == "CLICK":
        target = action.get("target", "")
        if not target:
            return {"success": False, "method": "CLICK", "error": "Missing target"}
        return execute_click(window, target, app_name)
    
    elif action_type == "TYPE":
        text = action.get("text", "")
        if not text:
            return {"success": False, "method": "TYPE", "error": "Missing text"}
        return execute_type(text)
    
    elif action_type == "HOTKEY":
        keys = action.get("keys", "")
        if not keys:
            return {"success": False, "method": "HOTKEY", "error": "Missing keys"}
        return execute_hotkey(keys)
    
    elif action_type == "WAIT":
        seconds = action.get("seconds", 1.0)
        return execute_wait(seconds)
    
    else:
        return {"success": False, "method": "UNKNOWN", "error": f"Unknown action: {action_type}"}
