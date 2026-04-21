# harness/app_controller.py
"""
Application lifecycle management for the hybrid GUI automation harness.
Handles safe launching, connecting, and killing of applications.
Includes Electron/Chromium-specific launch and accessibility warm-up.
"""

import time
import subprocess
import psutil
import os
import signal
from typing import Optional, Tuple

from pywinauto import Application, Desktop
from pywinauto.findwindows import ElementNotFoundError


# =============================================================================
# APP CONTROLLER
# =============================================================================

class AppController:
    """Manages application lifecycle."""
    
    def __init__(self, app_name: str, exe_path: str, title_re: str, electron: bool = False):
        self.app_name = app_name
        self.exe_path = exe_path
        self.title_re = title_re
        self.electron = electron
        self.app: Optional[Application] = None
        self.window = None
    
    def pre_start_cleanup(self):
        """Scan system and terminate any existing instances of the target app."""
        print(f"[app_controller] Pre-start cleanup for {self.app_name}...")
        count = 0
        try:
            for proc in psutil.process_iter(['name', 'exe']):
                try:
                    proc_name = (proc.info['name'] or '').lower()
                    proc_exe = (proc.info['exe'] or '').lower()
                    
                    # Skip unrelated java processes that live inside app extension dirs
                    if 'java' in proc_name:
                        continue
                    
                    # Match by app name in process name
                    if self.app_name.lower() in proc_name:
                        proc.kill()
                        count += 1
                        continue
                        
                    # Match by exact exe path
                    if self.exe_path and proc.info['exe']:
                        if os.path.normpath(proc.info['exe']) == os.path.normpath(self.exe_path):
                            proc.kill()
                            count += 1
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception as e:
            print(f"[app_controller] Cleanup error: {e}")
            
        if count > 0:
            time.sleep(2)
            print(f"[app_controller] Cleaned up {count} orphaned processes.")

    def start(self, timeout: int = 10, wait_ready: int = 3) -> bool:
        """
        Start the application.
        
        For Electron/Chromium apps, uses PowerShell Start-Process since
        subprocess.Popen often fails to spawn the full process tree.
        After launch, triggers Chromium's lazy accessibility tree build
        by querying descendants, then waits for the tree to populate.
        
        Args:
            timeout: Max seconds to wait for window
            wait_ready: Seconds to wait after window appears
        
        Returns:
            True if started successfully
        """
        print(f"[app_controller] Starting {self.app_name} (electron={self.electron})...")
        
        try:
            if self.electron:
                return self._start_electron(timeout=timeout, wait_ready=wait_ready)
            
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
    
    def _start_electron(self, timeout: int = 30, wait_ready: int = 5) -> bool:
        """
        Launch an Electron/Chromium app via PowerShell Start-Process.
        
        Python's subprocess.Popen often fails for Electron apps because the
        launcher process exits immediately and spawns a separate process tree.
        PowerShell's Start-Process correctly handles this.
        
        After the window appears, performs an accessibility tree warm-up:
        queries .descendants() to trigger Chromium's lazy a11y bridge,
        then waits for the tree to fully populate.
        """
        import re
        
        # Launch via PowerShell Start-Process
        ps_cmd = f'Start-Process -FilePath "{self.exe_path}"'
        print(f"[app_controller] Electron launch via PowerShell...")
        subprocess.Popen(
            ['powershell', '-NoProfile', '-Command', ps_cmd],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        
        # Give PowerShell + app startup a head start
        time.sleep(5)
        
        # Wait for the window to appear on Desktop
        window = None
        title_pattern = re.compile(self.title_re)
        
        for elapsed in range(0, timeout * 2, 2):
            time.sleep(2)
            
            for w in Desktop(backend="uia").windows():
                try:
                    title = w.window_text()
                    pid = w.process_id()
                    # Match title but exclude explorer.exe false positives
                    if title and title_pattern.match(title):
                        try:
                            proc_name = psutil.Process(pid).name().lower()
                        except (psutil.NoSuchProcess, psutil.AccessDenied):
                            proc_name = ""
                        if proc_name == "explorer.exe":
                            continue  # Skip File Explorer windows
                        window = w
                        break
                except Exception:
                    continue
            
            if window:
                break
            print(f"[app_controller] Waiting for {self.app_name} window... ({elapsed+2}s)")
        
        if not window:
            print(f"[app_controller] {self.app_name} window not found after {timeout}s")
            return False
        
        title = window.window_text()
        pid = window.process_id()
        print(f"[app_controller] Window found: '{title[:50]}' PID={pid}")
        
        # Connect pywinauto Application to this PID
        self.app = Application(backend="uia").connect(process=pid, timeout=10)
        self.window = self.app.top_window()
        
        # Accessibility warm-up: trigger Chromium's lazy a11y tree build
        self._warmup_accessibility()
        
        return True
    
    def _warmup_accessibility(self):
        """
        Trigger Chromium's lazy accessibility tree build and wait for it to stabilize.
        
        Chromium-based apps don't populate their UIA tree until an automation
        client first queries it. The initial query triggers the build, but the
        tree populates asynchronously over several seconds. This method polls
        until the tree stops growing, ensuring Phase 1 captures all elements.
        """
        if not self.window:
            return
        
        print(f"[app_controller] Warming up accessibility tree...")
        try:
            prev_count = 0
            stable_ticks = 0
            max_warmup = 30  # seconds
            
            for tick in range(0, max_warmup, 2):
                count = len(self.window.descendants())
                delta = count - prev_count
                print(f"[app_controller]   [{tick}s] {count} descendants (delta={delta})")
                
                if delta == 0 and count > 20:
                    stable_ticks += 1
                    if stable_ticks >= 2:  # Stable for 4+ seconds
                        break
                else:
                    stable_ticks = 0
                
                prev_count = count
                time.sleep(2)
            
            print(f"[app_controller] Accessibility warm-up complete ({count} elements)")
        except Exception as e:
            print(f"[app_controller] Warm-up error (continuing): {e}")
    
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
        Uses a longer timeout for Electron apps.
        """
        self.pre_start_cleanup()
        effective_timeout = max(timeout, 30) if self.electron else timeout
        return self.start(timeout=effective_timeout)
    
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
        config: Dict with 'exe', 'title_re', and optional 'electron' keys
    
    Returns:
        AppController instance
    """
    return AppController(
        app_name=app_name,
        exe_path=config.get("exe", ""),
        title_re=config.get("title_re", f".*{app_name}.*"),
        electron=config.get("electron", False)
    )
