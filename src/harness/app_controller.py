# harness/app_controller.py
"""
Application lifecycle management for the hybrid GUI automation harness.
Handles safe launching, connecting, and killing of applications.
"""

import time
import psutil
import os
import signal
from typing import Optional, Tuple

from pywinauto import Application
from pywinauto.findwindows import ElementNotFoundError


# =============================================================================
# APP CONTROLLER
# =============================================================================

class AppController:
    """Manages application lifecycle."""
    
    def __init__(self, app_name: str, exe_path: str, title_re: str):
        self.app_name = app_name
        self.exe_path = exe_path
        self.title_re = title_re
        self.app: Optional[Application] = None
        self.window = None
    
    def pre_start_cleanup(self):
        """Scan system and terminate any existing instances of the target app."""
        print(f"[app_controller] Pre-start cleanup for {self.app_name}...")
        count = 0
        try:
            for proc in psutil.process_iter(['name', 'exe']):
                try:
                    # Check by name regex or raw name if regex matches simple string
                    # Simple check: name in proc.name
                    if self.app_name.lower() in proc.info['name'].lower():
                        proc.kill()
                        count += 1
                        continue
                        
                    # Detailed check if exe_path is known
                    if self.exe_path and proc.info['exe']:
                        if os.path.normpath(proc.info['exe']) == os.path.normpath(self.exe_path):
                            proc.kill()
                            count += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception as e:
            print(f"[app_controller] Cleanup error: {e}")
            
        if count > 0:
            time.sleep(1)
            print(f"[app_controller] Cleaned up {count} orphaned processes.")

    def start(self, timeout: int = 10, wait_ready: int = 3) -> bool:
        """
        Start the application.
        
        Args:
            timeout: Max seconds to wait for window
            wait_ready: Seconds to wait after window appears
        
        Returns:
            True if started successfully
        """
        print(f"[app_controller] Starting {self.app_name}...")
        
        try:
            self.app = Application(backend="uia").start(self.exe_path)
            
            # Wait for CPU to settle
            try:
                self.app.wait_cpu_usage_lower(threshold=5, timeout=timeout)
            except Exception:
                pass
            
            time.sleep(wait_ready)
            
            # Get window
            self.window = self._get_window()
            if self.window:
                print(f"[app_controller] Window found: {self.window.window_text()[:50]}")
                return True
            
            return False
            
        except Exception as e:
            print(f"[app_controller] Error starting {self.app_name}: {e}")
            return False
    
    def connect(self, timeout: int = 5) -> bool:
        """
        Connect to an already running application.
        
        Returns:
            True if connected successfully
        """
        print(f"[app_controller] Connecting to {self.app_name}...")
        
        try:
            self.app = Application(backend="uia").connect(
                title_re=self.title_re,
                timeout=timeout,
                found_index=0
            )
            self.window = self.app.top_window()
            print(f"[app_controller] Connected: {self.window.window_text()[:50]}")
            return True
            
        except ElementNotFoundError:
            print(f"[app_controller] {self.app_name} not running")
            return False
        except Exception as e:
            print(f"[app_controller] Error connecting: {e}")
            return False
    
    def start_or_connect(self, timeout: int = 10) -> bool:
        """
        Always cleanup first, then start or connect.
        """
        self.pre_start_cleanup()
        return self.start(timeout=timeout)
    
    def close(self, timeout: int = 5):
        """
        Gracefully close the application.
        Tries close_dialog → kill if that fails.
        """
        print(f"[app_controller] Closing {self.app_name}...")
        try:
            if self.app:
                # Try graceful close
                try:
                    if self.window:
                        self.window.close()
                        time.sleep(1)
                except Exception:
                    pass
                
                # Kill remaining processes
                try:
                    self.app.kill()
                except Exception:
                    pass
            
            # Fallback: kill by process name
            self.pre_start_cleanup()
            self.app = None
            self.window = None
            print(f"[app_controller] {self.app_name} closed.")
        except Exception as e:
            print(f"[app_controller] Error closing {self.app_name}: {e}")
            # Force cleanup
            self.pre_start_cleanup()
    
    def _get_window(self):
        """Get the top window, with fallback to title-based search."""
        for attempt in range(3):
            time.sleep(2) # Give it time to appear
            try:
                if self.app:
                    window = self.app.top_window()
                    window.wait("ready", timeout=5)
                    return window
            except Exception as e:
                print(f"[app_controller] _get_window attempt {attempt+1} failed: {e}")
            
            # Fallback: connect by title
            try:
                print(f"[app_controller] Attempting connect by title (attempt {attempt+1})...")
                self.app = Application(backend="uia").connect(
                    title_re=self.title_re,
                    timeout=5,
                    visible_only=True,
                    found_index=0
                )
                return self.app.top_window()
            except Exception as e:
                print(f"[app_controller] Connect by title failed: {e}")
                
        return None
    
    def get_window(self):
        """Get the current window."""
        if self.window:
            return self.window
        self.window = self._get_window()
        return self.window
    
    def terminate_app(self) -> dict:
        """
        Strict application lifecycle termination.
        Graceful -> Kill -> Force
        """
        print(f"[app_controller] Strict termination sequence for {self.app_name}...")
        result = {"success": False, "method": "none", "termination_failure": False}
        
        # Step 1: Graceful close
        try:
            if self.window:
                self.window.close()
                time.sleep(2)
                if not self.is_running():
                    result["success"] = True
                    result["method"] = "graceful"
                    print("[app_controller] Graceful termination succeeded")
                    return result
        except Exception:
            pass

        # Step 2: Kill app object
        try:
            if self.app:
                self.app.kill()
                time.sleep(1)
                if not self.is_running():
                    result["success"] = True
                    result["method"] = "kill"
                    print("[app_controller] Standard kill succeeded")
                    return result
        except Exception:
            pass

        # Step 3: Force kill using psutil
        try:
            print("[app_controller] Attempting force kill via psutil...")
            for proc in psutil.process_iter(['name', 'exe']):
                try:
                    if self.app_name.lower() in proc.info['name'].lower():
                        proc.kill()
                        result["method"] = "force"
                    elif self.exe_path and proc.info['exe'] and os.path.normpath(proc.info['exe']) == os.path.normpath(self.exe_path):
                        proc.kill()
                        result["method"] = "force"
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            
            time.sleep(1)
            if not self.is_running():
                result["success"] = True
                if result["method"] == "none": result["method"] = "force" # it was force if we got here and it died
                print("[app_controller] Force kill succeeded")
                return result
        except Exception as e:
            print(f"[app_controller] Force kill failed: {e}")

        # Step 4: Verification
        if self.is_running():
            print(f"[app_controller] ERROR: Termination failure for {self.app_name}")
            print(f"[app_controller] LOG: app_closed=False pid=UNKNOWN")
            result["termination_failure"] = True
        else:
             print(f"[app_controller] LOG: app_closed=True pid=UNKNOWN method={result.get('method')}")
             result["success"] = True
        
        self.app = None
        self.window = None
        return result

    def kill(self) -> bool:
        """Legacy killing method, now redirects to terminate_app."""
        res = self.terminate_app()
        return res["success"]
    
    def focus(self) -> bool:
        """Bring window to foreground."""
        if not self.window:
            return False
        
        try:
            self.window.set_focus()
            return True
        except Exception:
            return False
    
    def is_running(self) -> bool:
        """Check if app is running using psutil for robustness."""
        # First check pywinauto object
        if self.app:
            try:
                if self.app.is_process_running():
                    return True
            except Exception:
                pass
        
        # Fallback to psutil check
        try:
            for proc in psutil.process_iter(['name', 'exe']):
                try:
                    if self.app_name.lower() in proc.info['name'].lower():
                        return True
                    if self.exe_path and proc.info['exe'] and os.path.normpath(proc.info['exe']) == os.path.normpath(self.exe_path):
                        return True
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                     continue
        except Exception:
            pass
            
        return False


# =============================================================================
# FACTORY
# =============================================================================

def create_controller(app_name: str, config: dict) -> AppController:
    """
    Create an AppController from config.
    
    Args:
        app_name: Application name
        config: Dict with 'exe' and 'title_re' keys
    
    Returns:
        AppController instance
    """
    return AppController(
        app_name=app_name,
        exe_path=config.get("exe", ""),
        title_re=config.get("title_re", f".*{app_name}.*")
    )
