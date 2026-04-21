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

logger = logging.getLogger("sara.step_executor")


_SEND_KEYS_SPECIALS = set("+^%~(){}[]")
_PYAUTOGUI_ENABLED = os.getenv("SARA_PYAUTOGUI", "0").strip().lower() in {"1", "true", "yes", "on"}
_PYAUTOGUI_IMPORT_FAILED = False


def _escape_send_keys_text(text: str) -> str:
    """Escape text for pywinauto.keyboard.send_keys literal typing."""
    chunks = []
    for ch in text:
        if ch == "\n":
            chunks.append("{ENTER}")
        elif ch == "\t":
            chunks.append("{TAB}")
        elif ch in _SEND_KEYS_SPECIALS:
            chunks.append("{" + ch + "}")
        else:
            chunks.append(ch)
    return "".join(chunks)


def _key_name_to_send_keys_token(key: str) -> str:
    """Map a hotkey token to pywinauto send_keys syntax."""
    k = key.strip().lower()
    if not k:
        return ""

    aliases = {
        "enter": "{ENTER}",
        "return": "{ENTER}",
        "tab": "{TAB}",
        "esc": "{ESC}",
        "escape": "{ESC}",
        "space": "{SPACE}",
        "backspace": "{BACKSPACE}",
        "delete": "{DELETE}",
    }
    if k in aliases:
        return aliases[k]

    if k.startswith("f") and k[1:].isdigit():
        return "{" + k.upper() + "}"

    if len(k) == 1 and k in _SEND_KEYS_SPECIALS:
        return "{" + k + "}"

    return k


def _hotkey_to_send_keys(keys: str) -> str:
    """Convert hotkey string (ctrl+shift+n) into send_keys sequence."""
    parts = [p.strip().lower() for p in keys.split("+") if p.strip()]
    mod_map = {"ctrl": "^", "alt": "%", "shift": "+"}

    prefix = ""
    non_mod = []
    for part in parts:
        if part in mod_map:
            prefix += mod_map[part]
        else:
            non_mod.append(part)

    if not non_mod:
        return prefix

    if len(non_mod) == 1:
        return prefix + _key_name_to_send_keys_token(non_mod[0])

    # Multiple non-mod keys are sent sequentially after modifiers.
    return prefix + "".join(_key_name_to_send_keys_token(k) for k in non_mod)


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

    # Special-case: planners often emit "CLICK <app_name>" as a focus step.
    # Resolve this as a window focus action instead of an element search.
    target_norm = (target or "").strip().lower()
    app_norm = (app_name or "").strip().lower()
    focus_aliases = {app_norm, f"{app_norm} app", f"{app_norm} window"}
    if window is not None and target_norm in {alias for alias in focus_aliases if alias}:
        try:
            window.set_focus()
            time.sleep(0.1)
            result["success"] = True
            result["method"] = "WINDOW_FOCUS"
            logger.info("[step_executor] Focused '%s' window via app-name click target", app_name)
            return result
        except Exception as exc:
            logger.warning("[step_executor] Window focus fallback failed for '%s': %s", app_name, exc)
    
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


def execute_type(text: str, window=None, app_name: str = "") -> Dict[str, Any]:
    """
    Execute a TYPE action using pyautogui.
    
    Args:
        text: Text to type
    
    Returns:
        Result dict with success status
    """
    result = {"success": False, "method": "TYPE", "error": ""}
    
    try:
        # TYPE actions are often first after plan sanitization, so proactively
        # focus the app window to avoid typing into a stale foreground target.
        if window is not None:
            try:
                window.set_focus()
                time.sleep(0.05)
                if app_name:
                    logger.info("[step_executor] Focused '%s' window before TYPE", app_name)
            except Exception as focus_error:
                logger.warning("[step_executor] Could not focus window before TYPE: %s", focus_error)

        global _PYAUTOGUI_IMPORT_FAILED

        if _PYAUTOGUI_ENABLED and not _PYAUTOGUI_IMPORT_FAILED:
            try:
                import pyautogui

                pyautogui.PAUSE = 0.05
                pyautogui.typewrite(text, interval=0.02) if text.isascii() else pyautogui.write(text)
                result["success"] = True
                logger.info(f"[step_executor] Typed {len(text)} chars (pyautogui)")
                return result
            except Exception as pyautogui_error:
                _PYAUTOGUI_IMPORT_FAILED = True
                logger.warning(f"[step_executor] pyautogui unavailable for TYPE, using send_keys fallback: {pyautogui_error}")

        from pywinauto.keyboard import send_keys

        escaped = _escape_send_keys_text(text)
        send_keys_error = ""

        for attempt in range(1, 3):
            try:
                if window is not None and attempt > 1:
                    try:
                        window.set_focus()
                        time.sleep(0.08)
                    except Exception as refocus_error:
                        logger.warning("[step_executor] Refocus before TYPE retry failed: %s", refocus_error)

                send_keys(escaped, pause=0.02, with_spaces=True, with_tabs=True, with_newlines=True)
                result["success"] = True
                logger.info(f"[step_executor] Typed {len(text)} chars (send_keys fallback, attempt={attempt})")
                return result
            except Exception as send_exc:
                send_keys_error = str(send_exc)
                logger.warning("[step_executor] send_keys TYPE attempt %s failed: %s", attempt, send_keys_error)

        # Final fallback even when pyautogui isn't enabled globally.
        try:
            import pyautogui

            pyautogui.PAUSE = 0.05
            pyautogui.typewrite(text, interval=0.02) if text.isascii() else pyautogui.write(text)
            result["success"] = True
            result["method"] = "TYPE_PYAUTOGUI_FALLBACK"
            logger.info(f"[step_executor] Typed {len(text)} chars (pyautogui post-send_keys fallback)")
            return result
        except Exception as pyautogui_fallback_error:
            logger.warning(
                "[step_executor] pyautogui fallback after send_keys failure also failed: %s",
                pyautogui_fallback_error,
            )
            result["error"] = send_keys_error or str(pyautogui_fallback_error)
            return result
    except Exception as e:
        result["error"] = str(e)
        logger.error(f"[step_executor] Type failed: {e}")
    
    return result


def execute_hotkey(keys: str, window=None, app_name: str = "") -> Dict[str, Any]:
    """
    Execute a HOTKEY action using pyautogui.
    
    Args:
        keys: Key combination string (e.g., "ctrl+s", "ctrl+shift+n", "alt+f4")
    
    Returns:
        Result dict with success status
    """
    result = {"success": False, "method": "HOTKEY", "error": ""}
    
    try:
        global _PYAUTOGUI_IMPORT_FAILED

        key_list = [k.strip().lower() for k in keys.split("+") if k.strip()]

        if window is not None:
            try:
                window.set_focus()
                time.sleep(0.05)
                if app_name:
                    logger.info("[step_executor] Focused '%s' window before HOTKEY", app_name)
            except Exception as focus_error:
                logger.warning("[step_executor] Could not focus window before HOTKEY: %s", focus_error)

        if _PYAUTOGUI_ENABLED and not _PYAUTOGUI_IMPORT_FAILED:
            try:
                import pyautogui

                pyautogui.hotkey(*key_list)
                time.sleep(0.3)
                result["success"] = True
                logger.info(f"[step_executor] Hotkey: {'+'.join(key_list)} (pyautogui)")
                return result
            except Exception as pyautogui_error:
                _PYAUTOGUI_IMPORT_FAILED = True
                logger.warning(f"[step_executor] pyautogui unavailable for HOTKEY, using send_keys fallback: {pyautogui_error}")

        from pywinauto.keyboard import send_keys

        send_seq = _hotkey_to_send_keys(keys)
        send_keys(send_seq)
        time.sleep(0.3)

        result["success"] = True
        logger.info(f"[step_executor] Hotkey: {'+'.join(key_list)} (send_keys fallback)")
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
    app_name: str = "",
    use_vision: bool = True,
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
    logger.info(
        "[step_executor] Dispatch action=%s app=%s target=%s keys=%s text_len=%s use_vision=%s",
        action_type,
        app_name,
        action.get("target", ""),
        action.get("keys", ""),
        len(str(action.get("text", ""))),
        use_vision,
    )
    
    if action_type == "CLICK":
        target = action.get("target", "")
        if not target:
            return {"success": False, "method": "CLICK", "error": "Missing target"}
        return execute_click(window, target, app_name, use_vision=use_vision)
    
    elif action_type == "TYPE":
        text = action.get("text", "")
        if not text:
            return {"success": False, "method": "TYPE", "error": "Missing text"}
        return execute_type(text, window=window, app_name=app_name)
    
    elif action_type == "HOTKEY":
        keys = action.get("keys", "")
        if not keys:
            return {"success": False, "method": "HOTKEY", "error": "Missing keys"}
        return execute_hotkey(keys, window=window, app_name=app_name)
    
    elif action_type == "WAIT":
        seconds = action.get("seconds", 1.0)
        return execute_wait(seconds)
    
    else:
        return {"success": False, "method": "UNKNOWN", "error": f"Unknown action: {action_type}"}
