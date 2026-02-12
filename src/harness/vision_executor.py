# harness/vision_executor.py
"""
Vision Executor using Unified VLM Provider.
Locates UI elements using Gemini/Qwen/HF via vlm_provider.
"""

import sys
import os
import time
import threading
import concurrent.futures
from dataclasses import dataclass
from typing import Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.harness import vlm_provider

@dataclass
class VisionResult:
    clicked: bool = False
    coordinates: Optional[Tuple[int, int]] = None
    confidence: float = 0.0
    latency_ms: int = 0
    api_called: bool = False
    error: str = ""
    screenshot_path: str = ""

def capture_screenshot(window, path: str) -> bool:
    """
    Capture screenshot with synchronous retry and verification.
    """
    for attempt in range(2):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            import pyautogui
            rect = window.rectangle()
            screenshot = pyautogui.screenshot(region=(rect.left, rect.top, rect.width(), rect.height()))
            screenshot.save(path)
            
            # Verify file exists and has size
            if os.path.exists(path) and os.path.getsize(path) > 0:
                print(f"[vision_executor] Screenshot saved: {path}")
                return True
            else:
                print(f"[vision_executor] Screenshot file missing or empty (Attempt {attempt+1})")
                
        except Exception as e:
            print(f"[vision_executor] Screenshot error (Attempt {attempt+1}): {e}")
            
        time.sleep(0.2) # 200ms delay
        
    return False

def locate_element(window, task: str, run_id: str = "unknown", logger=None) -> VisionResult:
    """
    Locate element using VLM provider.
    Returns VisionResult with details.
    """
    print(f"[vision_executor] Processing visual request: '{task}'")
    result = VisionResult()
    
    # Absolute path
    root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    abs_run_dir = os.path.abspath(os.path.join(root_dir, "experiments", f"run_{run_id}"))
    os.makedirs(abs_run_dir, exist_ok=True)
    screenshot_path = os.path.join(abs_run_dir, f"screen_{int(time.time()*1000)}.png")
    result.screenshot_path = screenshot_path
    
    # Log Start
    if logger and hasattr(logger, "log_execution_event"):
        logger.log_execution_event("VISION_CALL_START", {
            "task": task,
            "screenshot_saved_path": screenshot_path
        })
    
    # Capture
    if not capture_screenshot(window, screenshot_path):
        result.error = "Screenshot capture failed after retries"
        return result
    
    # Call VLM
    api_success = False
    for attempt in range(2): # Retry API once
        try:
            start_time = time.time()
            result.api_called = True 
            
            # Log API Call Attempt? (User said "as soon as API is invoked")
            # We can log here or result. but let's do the call first.
            
            results = vlm_provider.locate_elements(screenshot_path, task, top_k=1)
            duration = int((time.time() - start_time) * 1000)
            result.latency_ms = duration
            
            # Log API Result
            if logger and hasattr(logger, "log_execution_event"):
                logger.log_execution_event("VISION_API_CALL", {
                    "task": task,
                    "vision_api_called": True,
                    "api_latency_ms": duration,
                    "vision_result": results[0] if results else None
                })

            if results:
                best = results[0]
                result.confidence = best.get('conf', 0.0)
                result.coordinates = (best['x'], best['y'])
                print(f"[vision_executor] VLM found match in {duration}ms (Conf: {result.confidence})")
                return result
            else:
                print(f"[vision_executor] VLM found no matches in {duration}ms")
                # Don't retry if no matches, only on exception? User said "if API call fails, retry 1 time".
                # "Fails" usually means exception. Empty result is a valid response.
                result.error = "No matches found by VLM"
                return result
                
        except Exception as e:
            print(f"[vision_executor] VLM error (Attempt {attempt+1}): {e}")
            result.error = f"VLM error: {str(e)}"
            # Retry loop continues
            
    # If we get here, all retries failed (exceptions)
    # Log failure
    if logger and hasattr(logger, "log_execution_event"):
         logger.log_execution_event("VISION_API_CALL", {
            "task": task,
            "vision_api_called": True, # We tried
            "api_latency_ms": 0,
            "vision_result": None,
            "error": result.error
        })
        
    return result


def locate_elements(screenshot_path: str, task: str = "all interactable buttons and menu items") -> list:
    """Locate multiple elements via VLM."""
    import src.harness.vlm_provider as vlm_provider
    print(f"[vision_executor] Batch visual request: '{task}'")
    try:
        results = vlm_provider.locate_elements(screenshot_path, task, top_k=10)
        return results
    except Exception as e:
        print(f"[vision_executor] Batch VLM error: {e}")
        return []


def execute_action(window, result: VisionResult) -> bool:
    """
    Execute action on located element coordinates.
    """
    if not result.coordinates:
        return False
        
    try:
        x, y = result.coordinates
        print(f"[vision_executor] Clicking at ({x}, {y})...")
        
        # Convert window-relative to screen coordinates
        rect = window.rectangle()
        screen_x = rect.left + x
        screen_y = rect.top + y
        
        # Click
        import pyautogui
        pyautogui.click(screen_x, screen_y)
        result.clicked = True
        return True
        
    except Exception as e:
        print(f"[vision_executor] Execution failed: {e}")
        result.error = f"Click execution failed: {e}"
        return False


def detect_and_click(window, task: str, app_name: str, run_id: str = "unknown", logger=None, timeout: float = 15.0) -> VisionResult:
    """
    Combined locate and execute function with timeout.
    """
    start_time = time.time()
    result_container = [VisionResult(error="Timeout")]

    def _vision_task():
        # Locate
        res = locate_element(window, task, run_id, logger)
        result_container[0] = res
        if res.coordinates:
            execute_action(window, res)

    with concurrent.futures.ThreadPoolExecutor() as executor:
        future = executor.submit(_vision_task)
        try:
            future.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            result_container[0].error = "Vision timeout"
        except Exception as e:
            result_container[0].error = f"Thread error: {e}"
            
    final_result = result_container[0]
    # Ensure latency is total time if not set by inner
    if final_result.latency_ms == 0:
        final_result.latency_ms = int((time.time() - start_time) * 1000)
        
    return final_result
