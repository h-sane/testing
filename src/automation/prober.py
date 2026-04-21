# automation_tree/prober.py
"""
Production-quality UI crawler for automation tree discovery.
Three-phase BFS architecture with universal content boundary detection:
    Phase 1: Static snapshot (capture all visible elements)
    Phase 2: Interactive BFS probing (expand menus, probe tabs, discover popups)
    Phase 3: Dialog probing (invoke safe menu items to discover dialogs)

Content boundary detection (universal, no per-app config):
    - Document/DataGrid/Table boundaries: stop recursion into rendered content
    - Homogeneous sibling explosion: detect data lists (bookmarks, history)
    - Popup content filter: skip browser tabs/extension popups

General-purpose: works on any UIA-compatible Windows application.
"""

import time
import datetime
import os
import sys
import collections
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.automation import fingerprint, storage, builder
from pywinauto import Desktop
from pywinauto.keyboard import send_keys


# =============================================================================
# CONSTANTS
# =============================================================================

# Actions considered destructive and never performed during probing
DEFAULT_BLACKLIST = [
    "delete", "remove", "close window", "exit", "quit", 
    "clear all", "format disk", "shutdown", "restart",
    "sign out", "log off", "uninstall"
]

# Additional blacklist for dialog-opening invoke actions
# These actions are destructive or cause side effects even if closeable
INVOKE_BLACKLIST = [
    "save", "save as", "print", "new", "new window", "new tab",
    "open", "close", "exit", "quit", "delete", "remove",
    "send", "share", "export", "import", "run",
    "sign in", "sign out", "log", "update", "install",
    "format", "reset", "clear", "undo", "redo",
    "cut", "copy", "paste", "select all"
]

# Control types that act as containers (recurse into them)
CONTAINER_TYPES = {
    "Window", "Pane", "Group", "Tree", "TreeItem",
    "List", "Tab", "TabItem", "Menu", "MenuBar", 
    "ToolBar", "StatusBar", "ScrollBar", "Custom",
    "Document", "Header", "DataGrid", "Table"
}

# =============================================================================
# UNIVERSAL CONTENT BOUNDARY DETECTION
# =============================================================================

# Control types that mark the boundary between app chrome and user content.
# The element itself is cached, but its children are NOT recursed into.
# These work universally across all apps (browsers, Office, etc.)
CONTENT_BOUNDARY_TYPES = {"Document", "DataGrid", "Table"}

# Apps whose main UI lives inside a Document (Electron/SPA); skip boundary for them.
DOCUMENT_BOUNDARY_EXEMPT_APPS = {"Windsurf", "Spotify"}

# Homogeneous sibling explosion detection:
# When expanding an element reveals many children of the same type,
# it's a data list (bookmarks, history, file list) — not app controls.
DATA_EXPLOSION_THRESHOLD = 15     # Minimum children to trigger check
DATA_EXPLOSION_HOMOGENEITY = 0.75 # Minimum ratio of dominant type

# Control types whose children should be probed via interaction
EXPANDABLE_PATTERNS = {"ExpandCollapsePattern"}

# Probing actions by pattern priority
PROBE_ACTIONS = [
    ("ExpandCollapsePattern", "expand"),
    ("InvokePattern", "invoke"),
    ("SelectionItemPattern", "select"),
]

# Restrict probing to safer chrome-like controls. Avoid blind clicking buttons.
PROBE_ELIGIBLE_TYPES = {
    "MenuBar", "Menu", "MenuItem",
    "Tab", "TabItem",
    "Tree", "TreeItem",
    "SplitButton",
}

LOG_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "experiments", "crawl_logs"
)


# =============================================================================
# PROBER
# =============================================================================

class UIProber:
    """
    Three-phase crawler for automation tree discovery.
    Phase 1: Static snapshot — build tree from window, store all nodes.
    Phase 2: Interactive BFS — expand/invoke elements, discover hidden children.
    Phase 3: Dialog probing — invoke safe menu items to surface dialogs.
    """
    
    def __init__(self, max_depth=12, max_time=120, blacklist=None, probe_dialogs=True):
        self.max_depth = max_depth
        self.max_time = max_time
        self.blacklist = blacklist or DEFAULT_BLACKLIST
        self.probe_dialogs = probe_dialogs
        self.app_name = ""
        
        # Runtime state
        self.session = None          # CacheSession (batch I/O)
        self.root_window = None      # pywinauto window reference
        self.target_pid = None       # App PID for popup filtering
        self.start_time = 0
        
        # BFS queue: (pywinauto_elem, exposure_path, depth)
        # We store enough info to re-locate elements after UI reset
        self.probe_queue = collections.deque()
        
        # Tracking
        self.stored_fps = set()       # All fingerprints in session
        self.interacted_fps = set()   # Elements we've already probed
        self.invoked_fps = set()      # Elements we've invoked for dialog probing
        self.stats = {"discovered": 0, "actions": 0, "popups": 0, "dialogs": 0, "errors": 0}
        
        # Logging
        os.makedirs(LOG_DIR, exist_ok=True)
        self.log_path = os.path.join(LOG_DIR, f"probe_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.log")

    def _get_probe_action(self, control_type: str, patterns: list):
        """Map available patterns to a safe probe action for whitelisted control types."""
        if not patterns or control_type not in PROBE_ELIGIBLE_TYPES:
            return None
        for pattern, action in PROBE_ACTIONS:
            if pattern in patterns:
                return action
        return None
    
    # -------------------------------------------------------------------------
    # LOGGING
    # -------------------------------------------------------------------------
    
    def log(self, msg, level="INFO"):
        try:
            ts = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]
            line = f"[{ts}] [{level}] {msg}"
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            print(f"[PROBE] {msg}")
        except Exception:
            pass
    
    # -------------------------------------------------------------------------
    # SAFETY
    # -------------------------------------------------------------------------
    
    def is_safe(self, name):
        """Check if element name is safe to interact with."""
        if not name:
            return True
        name_lower = name.lower().strip()
        for bad in self.blacklist:
            if bad in name_lower:
                self.log(f"BLACKLISTED: '{name}' (matched '{bad}')", "WARN")
                return False
        return True
    
    def is_timed_out(self):
        return (time.time() - self.start_time) > self.max_time
    
    # -------------------------------------------------------------------------
    # CONTENT BOUNDARY DETECTION (Universal)
    # -------------------------------------------------------------------------
    
    def _is_content_boundary(self, control_type):
        """Check if a control type marks a content boundary.
        
        Elements of these types are cached (so we know they exist),
        but their children are NOT recursed into — they contain
        ephemeral user content (web pages, spreadsheet cells, etc.).
        """
        if control_type == "Document" and self.app_name in DOCUMENT_BOUNDARY_EXEMPT_APPS:
            return False
        return control_type in CONTENT_BOUNDARY_TYPES
    
    def _is_data_explosion(self, new_children):
        """Detect homogeneous sibling explosion (universal data list heuristic).
        
        When expanding an element yields many children of the same control type,
        it's almost certainly a data list (bookmarks, history, files, contacts)
        rather than app controls (which are typically heterogeneous).
        
        Args:
            new_children: list of node dicts discovered after expansion
            
        Returns:
            True if this looks like a data list, False if it looks like app controls
        """
        if len(new_children) < DATA_EXPLOSION_THRESHOLD:
            return False
        
        type_counts = Counter(c.get("control_type", "") for c in new_children)
        if not type_counts:
            return False
        
        dominant_type, dominant_count = type_counts.most_common(1)[0]
        homogeneity = dominant_count / len(new_children)
        
        if homogeneity >= DATA_EXPLOSION_HOMOGENEITY:
            self.log(
                f"DATA EXPLOSION detected: {len(new_children)} children, "
                f"{dominant_count} are '{dominant_type}' ({homogeneity:.0%})",
                "WARN"
            )
            return True
        return False
    
    def _is_content_popup(self, popup_node):
        """Check if a popup window is a content window (browser tab, extension).
        
        If the popup's primary children include a Document element, it's
        rendering web content — not a dialog. Skip crawling it.
        """
        for child in popup_node.get("children", []):
            if child.get("control_type") == "Document":
                return True
        return False
    
    # -------------------------------------------------------------------------
    # MAIN ENTRY POINT
    # -------------------------------------------------------------------------
    
    def probe_window(self, window, app_name, clear_cache=True):
        """
        Main entry point. Crawls the entire application window.
        
        Args:
            window: pywinauto window object
            app_name: Application name (used as cache key)
            clear_cache: If True, start with empty cache
            
        Returns:
            int: Number of new elements discovered
        """
        self.log(f"=== Starting probe for '{app_name}' ===")
        self.log(f"Config: max_depth={self.max_depth}, max_time={self.max_time}s")
        
        self.app_name = app_name
        self.root_window = window
        self.target_pid = window.process_id()
        self.start_time = time.time()
        self.stored_fps = set()
        self.interacted_fps = set()
        self.invoked_fps = set()
        self.probe_queue = collections.deque()
        self.stats = {"discovered": 0, "actions": 0, "popups": 0, "dialogs": 0, "errors": 0}
        
        # Initialize batch session
        self.session = storage.CacheSession(app_name, clear=clear_cache)
        
        try:
            # ---- PHASE 1: Static Snapshot ----
            self.log("--- Phase 1: Static Snapshot ---")
            self._phase1_static_snapshot(app_name)
            self.log(f"Phase 1 complete: {self.stats['discovered']} elements, "
                     f"{len(self.probe_queue)} expandables queued")
            
            # Flush phase 1 to disk (checkpoint)
            self.session.flush()
            
            # ---- PHASE 2: Interactive BFS Probing ----
            self.log("--- Phase 2: Interactive BFS Probing ---")
            self._phase2_bfs_probing(app_name)
            
            # Checkpoint
            self.session.flush()
            
            # ---- PHASE 3: Dialog Probing (invoke menu items) ----
            if self.probe_dialogs:
                self.log("--- Phase 3: Dialog Probing ---")
                self._phase3_dialog_probing(app_name)
            
            # Final flush
            self.session.flush()
            
        except Exception as e:
            self.log(f"FATAL: {e}", "ERROR")
            import traceback
            self.log(traceback.format_exc(), "ERROR")
            self.stats["errors"] += 1
            # Emergency flush whatever we have
            try:
                self.session.flush()
            except Exception:
                pass
        
        elapsed = time.time() - self.start_time
        self.log(f"=== Probe complete for '{app_name}' ===")
        self.log(f"Stats: {self.stats}")
        self.log(f"Total elements in cache: {self.session.count()}")
        self.log(f"Elapsed: {elapsed:.1f}s")
        
        return self.stats["discovered"]
    
    # -------------------------------------------------------------------------
    # PHASE 1: STATIC SNAPSHOT
    # -------------------------------------------------------------------------
    
    def _phase1_static_snapshot(self, app_name):
        """
        Build complete tree from window and store all nodes.
        All Phase 1 elements have empty exposure paths (they're visible).
        Collects expandable elements for Phase 2.
        """
        root_node = builder.node_from_elem(
            self.root_window, 
            sibling_index=0, 
            parent_path="", 
            depth=0,
            parent_fingerprint="",
            parent_exposure_path=[]
        )
        
        # Walk tree and store every node with EMPTY exposure path
        self._store_tree_phase1(root_node, depth=0)
    
    def _store_tree_phase1(self, node, depth):
        """
        Walk builder tree and store nodes to session.
        Phase 1: all elements are visible, so exposure_path = [].
        Enqueue expandable elements for Phase 2 probing.
        
        Content boundary: if the node's control_type is in CONTENT_BOUNDARY_TYPES,
        the node itself is stored (tagged as content_boundary=True) but its
        children are NOT recursed into.
        """
        fp = fingerprint.compute_fingerprint(node, node.get("path", ""))
        
        control_type = node.get("control_type", "")
        is_boundary = self._is_content_boundary(control_type)
        
        if fp and fp not in self.stored_fps:
            # Tag boundary nodes so the executor knows content lives here
            if is_boundary:
                node["content_boundary"] = True
                self.log(f"CONTENT BOUNDARY (Phase 1): '{node.get('name', '')}' ({control_type}) — skipping children")
            
            is_new = self.session.add(
                fingerprint_val=fp,
                node_dict=node,
                discovery_method="STATIC",
                exposure_path=[]  # Visible elements have empty exposure paths
            )
            if is_new:
                self.stored_fps.add(fp)
                self.stats["discovered"] += 1
            
            # Do NOT enqueue boundary elements for interactive probing
            if not is_boundary:
                # Check if this element should be probed interactively
                patterns = node.get("patterns", [])
                action = self._get_probe_action(control_type, patterns)
                if action and self.is_safe(node.get("name", "")):
                    self.probe_queue.append({
                        "fingerprint": fp,
                        "name": node.get("name", "unnamed"),
                        "control_type": control_type,
                        "automation_id": node.get("automation_id", ""),
                        "depth": depth,
                        "parent_exposure": [],  # How to *get to* this element
                        "action": action,
                    })
        elif fp:
            self.stored_fps.add(fp)
        
        # Do NOT recurse into content boundary children
        if is_boundary:
            return
        
        # Recurse into children
        for child in node.get("children", []):
            self._store_tree_phase1(child, depth + 1)
    
    # -------------------------------------------------------------------------
    # PHASE 2: BFS INTERACTIVE PROBING
    # -------------------------------------------------------------------------
    
    def _phase2_bfs_probing(self, app_name):
        """
        Process expandable elements in BFS order.
        For each: reset UI → find element live → expand → capture new children → reset.
        """
        processed = 0
        
        while self.probe_queue and not self.is_timed_out():
            item = self.probe_queue.popleft()
            fp = item["fingerprint"]
            name = item["name"]
            
            # Skip if already probed
            if fp in self.interacted_fps:
                continue
            
            self.interacted_fps.add(fp)
            processed += 1
            
            self.log(f"BFS [{processed}/{processed + len(self.probe_queue)}]: "
                     f"Probing '{name}' ({item['control_type']})")
            
            # 1. Reset UI to clean state
            self._reset_ui()
            time.sleep(0.3)
            
            # 2. Execute any parent exposure steps needed (for deeper elements)
            parent_exposure = item.get("parent_exposure", [])
            if parent_exposure:
                success = self._execute_exposure_steps(parent_exposure)
                if not success:
                    self.log(f"Failed to execute parent exposure for '{name}'", "WARN")
                    self.stats["errors"] += 1
                    continue
                time.sleep(0.3)
            
            # 3. Find the TARGET element directly in the live UI
            target_elem = self._find_element_live(
                name=item["name"],
                control_type=item["control_type"],
                automation_id=item.get("automation_id", "")
            )
            
            if not target_elem:
                self.log(f"Could not find '{name}' in live UI", "WARN")
                self.stats["errors"] += 1
                continue
            
            action = item.get("action", "expand")

            # 4. Expand the element
            if not self._take_action(target_elem, action):
                self.log(f"{action.title()} failed on '{name}'", "WARN")
                self.stats["errors"] += 1
                continue
            
            self.stats["actions"] += 1
            
            # 5. Wait for UI stabilization
            time.sleep(0.5)
            
            # 6. Capture new elements
            before_count = self.stats["discovered"]
            
            # The exposure path for children of THIS element
            child_exposure = list(parent_exposure) + [{"fingerprint": fp, "action": action}]
            
            # 6a. Re-snapshot the main window
            new_children = self._capture_new_elements(app_name, child_exposure)
            
            # 6b. Check for data explosion BEFORE scanning popups
            # If the expansion yielded a homogeneous data list, don't probe deeper
            if new_children and self._is_data_explosion(new_children):
                # Remove any newly enqueued items from this expansion
                # (they're data items, not app controls)
                self._dequeue_data_children(new_children)
            
            # 6c. Scan Desktop for popup windows (PID-filtered)
            self._scan_popups(app_name, child_exposure)
            
            after_count = self.stats["discovered"]
            new_found = after_count - before_count
            
            if new_found > 0:
                self.log(f"Discovered {new_found} new elements after expanding '{name}'")
                # Flush periodically
                self.session.flush()
            
            # 7. Collapse / reset
            self._reset_ui()
        
        if self.is_timed_out():
            self.log(f"Phase 2 timed out after {processed} probes", "WARN")
        else:
            self.log(f"Phase 2 complete: {processed} elements probed")
    
    # -------------------------------------------------------------------------
    # PHASE 3: DIALOG PROBING
    # -------------------------------------------------------------------------
    
    def _is_invoke_safe(self, name):
        """Check if a menu item is safe to invoke for dialog probing."""
        if not name:
            return False
        name_lower = name.lower().strip()
        # Check general blacklist first
        if not self.is_safe(name):
            return False
        # Check invoke-specific blacklist
        for bad in INVOKE_BLACKLIST:
            if bad == name_lower or name_lower.startswith(bad + " "):
                return False
        return True
    
    def _phase3_dialog_probing(self, app_name):
        """
        Invoke MenuItem elements to discover dialog contents.
        Only invokes elements deemed safe (won't cause side effects).
        After invoking, captures any new popup/dialog windows and their children.
        """
        # Collect all MenuItem elements with InvokePattern from cache
        invokable = []
        for fp, node in self.session.cache.get("elements", {}).items():
            if fp in self.invoked_fps:
                continue
            ct = node.get("control_type", "")
            patterns = node.get("patterns", [])
            name = node.get("name", "")
            
            # Only invoke MenuItems that have InvokePattern and are safe
            if ct == "MenuItem" and "InvokePattern" in patterns:
                if self._is_invoke_safe(name):
                    invokable.append({
                        "fingerprint": fp,
                        "name": name,
                        "control_type": ct,
                        "automation_id": node.get("automation_id", ""),
                        "exposure_path": node.get("exposure_path", [])
                    })
        
        if not invokable:
            self.log("Phase 3: No invokable elements found")
            return
        
        self.log(f"Phase 3: {len(invokable)} invokable elements to probe")
        probed = 0
        
        for item in invokable:
            if self.is_timed_out():
                self.log(f"Phase 3 timed out after {probed} dialogs", "WARN")
                break
            
            fp = item["fingerprint"]
            name = item["name"]
            self.invoked_fps.add(fp)
            
            self.log(f"  Dialog [{probed+1}/{len(invokable)}]: Invoking '{name}'")
            
            # 1. Reset UI
            self._reset_ui()
            time.sleep(0.3)
            
            # 2. Execute exposure path (open parent menu first)
            exposure = item.get("exposure_path", [])
            if exposure:
                success = self._execute_exposure_steps(exposure)
                if not success:
                    self.log(f"  Could not replay exposure for '{name}'", "WARN")
                    self.stats["errors"] += 1
                    continue
                time.sleep(0.3)
            
            # 3. Find and invoke the target
            target = self._find_element_live(
                name=item["name"],
                control_type=item["control_type"],
                automation_id=item.get("automation_id", "")
            )
            
            if not target:
                self.log(f"  Could not find '{name}' in live UI", "WARN")
                self.stats["errors"] += 1
                continue
            
            # 4. Invoke it
            if not self._take_action(target, "invoke"):
                self.log(f"  Invoke failed on '{name}'", "WARN")
                self.stats["errors"] += 1
                continue
            
            self.stats["actions"] += 1
            time.sleep(0.8)  # Dialogs take longer to appear
            
            # 5. Scan for new dialog windows AND main window changes
            before_count = self.stats["discovered"]
            dialog_exposure = list(exposure) + [{"fingerprint": fp, "action": "invoke"}]
            
            # 5a. Scan main window for new elements (some dialogs are child windows)
            self._capture_new_elements(app_name, dialog_exposure)
            
            # 5b. Scan Desktop for popup/dialog windows
            self._scan_popups(app_name, dialog_exposure)
            
            after_count = self.stats["discovered"]
            new_found = after_count - before_count
            
            if new_found > 0:
                self.log(f"  Discovered {new_found} elements in dialog from '{name}'")
                self.stats["dialogs"] += 1
                self.session.flush()
            
            # 6. Close the dialog
            self._reset_ui()
            time.sleep(0.3)
            
            probed += 1
        
        self.log(f"Phase 3 complete: {probed} dialogs probed, {self.stats['dialogs']} had new elements")
    
    def _execute_exposure_steps(self, steps):
        """
        Execute a sequence of exposure steps (find + act).
        Used for deep elements that need parent menus opened first.
        """
        for i, step in enumerate(steps):
            step_fp = step.get("fingerprint", "")
            action = step.get("action", "click")
            
            # Find via cached metadata
            cached = self.session.get(step_fp)
            if not cached:
                self.log(f"  Step {i+1}: FP {step_fp[:8]} not in cache", "WARN")
                return False
            
            elem = self._find_element_live(
                name=cached.get("name", ""),
                control_type=cached.get("control_type", ""),
                automation_id=cached.get("automation_id", "")
            )
            
            if not elem:
                self.log(f"  Step {i+1}: Could not find '{cached.get('name', '?')}'", "WARN")
                return False
            
            if not self._take_action(elem, action):
                self.log(f"  Step {i+1}: Action '{action}' failed", "WARN")
                return False
            
            # Expand actions need more time for menus/popups to appear
            wait = 0.5 if action == "expand" else 0.3
            time.sleep(wait)
        
        return True
    
    def _find_element_live(self, name, control_type, automation_id=""):
        """
        Find a live pywinauto element by its properties.
        Uses pywinauto's built-in search (fast, no fingerprint recompute).
        """
        try:
            # Search all windows of the app (including popups)
            windows_to_search = [self.root_window]
            try:
                desktop = Desktop(backend="uia")
                for w in desktop.windows():
                    try:
                        if w.process_id() == self.target_pid and w != self.root_window:
                            windows_to_search.append(w)
                    except Exception:
                        continue
            except Exception:
                pass
            
            for win in windows_to_search:
                # Try automation_id first (most reliable)
                if automation_id:
                    try:
                        candidates = win.descendants(
                            control_type=control_type,
                            auto_id=automation_id
                        )
                        if candidates:
                            return candidates[0]
                    except Exception:
                        pass
                
                # Try name + control_type
                if name:
                    try:
                        candidates = win.descendants(
                            control_type=control_type,
                            title=name
                        )
                        if candidates:
                            return candidates[0]
                    except Exception:
                        pass
                
                # Try name only (looser match)
                if name:
                    try:
                        candidates = win.descendants(title=name)
                        if len(candidates) == 1:
                            return candidates[0]
                    except Exception:
                        pass
        
        except Exception as e:
            self.log(f"Element search failed: {e}", "WARN")
        
        return None
    
    def _quick_node(self, elem):
        """Build minimal node dict for fingerprint computation (no recursion)."""
        name = ""
        try:
            name = elem.window_text() or ""
        except Exception:
            try:
                name = getattr(elem.element_info, 'name', "") or ""
            except Exception:
                pass
        
        control_type = ""
        try:
            ct = elem.element_info.control_type
            control_type = str(ct) if ct else ""
        except Exception:
            pass
        
        automation_id = ""
        try:
            automation_id = getattr(elem.element_info, 'automation_id', "") or ""
        except Exception:
            pass
        
        return {
            "name": name[:512],
            "control_type": control_type,
            "automation_id": automation_id[:512],
            "path": "",  # Will be computed relative to discovery context
            "sibling_index": 0,
            "patterns": [],
            "children": []
        }
    
    def _capture_new_elements(self, app_name, exposure_path):
        """
        Re-snapshot the main window and store any new elements.
        New elements in Phase 2 get the provided exposure_path.
        
        Returns:
            list: New children discovered (for data explosion checking)
        """
        new_children = []
        try:
            root_node = builder.node_from_elem(
                self.root_window,
                sibling_index=0,
                parent_path="",
                depth=0,
                parent_fingerprint="",
                parent_exposure_path=[]
            )
            new_children = self._store_tree_phase2(root_node, exposure_path, depth=0)
        except Exception as e:
            self.log(f"Window re-snapshot failed: {e}", "WARN")
            self.stats["errors"] += 1
        return new_children
    
    def _scan_popups(self, app_name, exposure_path):
        """
        Scan Desktop for new top-level windows belonging to the app.
        Filters out content popups (browser tabs, extension windows).
        """
        try:
            desktop = Desktop(backend="uia")
            for w in desktop.windows():
                try:
                    w_pid = w.process_id()
                    if w_pid != self.target_pid:
                        continue
                    
                    popup_node = builder.node_from_elem(
                        w, 
                        sibling_index=0, 
                        parent_path="",
                        depth=0,
                        parent_fingerprint="",
                        parent_exposure_path=[]
                    )
                    
                    popup_fp = fingerprint.compute_fingerprint(popup_node, popup_node.get("path", ""))
                    
                    # Content popup filter: skip browser tabs / extension windows
                    if popup_fp not in self.stored_fps:
                        if self._is_content_popup(popup_node):
                            self.log(
                                f"CONTENT POPUP skipped: '{popup_node.get('name', 'unnamed')}' "
                                f"(contains Document element)",
                                "WARN"
                            )
                            # Still record the popup window itself (but not its children)
                            popup_node["content_boundary"] = True
                            popup_node["children"] = []  # Strip children
                            self.session.add(
                                fingerprint_val=popup_fp,
                                node_dict=popup_node,
                                discovery_method="PROBE",
                                exposure_path=exposure_path
                            )
                            self.stored_fps.add(popup_fp)
                            self.stats["discovered"] += 1
                            self.stats["popups"] += 1
                            continue
                        
                        self.log(f"Found popup: '{popup_node.get('name', 'unnamed')}'")
                        self.stats["popups"] += 1
                    
                    self._store_tree_phase2(popup_node, exposure_path, depth=0)
                    
                except Exception:
                    continue
        except Exception as e:
            self.log(f"Desktop scan failed: {e}", "WARN")
    
    def _store_tree_phase2(self, node, exposure_path, depth):
        """
        Store tree nodes from Phase 2 discovery.
        New elements get the provided exposure_path.
        Also enqueues newly found expandables.
        
        Content boundary: stops recursion at boundary types.
        
        Returns:
            list: All newly discovered nodes (for data explosion checking)
        """
        new_nodes = []
        fp = fingerprint.compute_fingerprint(node, node.get("path", ""))
        
        control_type = node.get("control_type", "")
        is_boundary = self._is_content_boundary(control_type)
        
        if fp and fp not in self.stored_fps:
            # Tag boundary nodes
            if is_boundary:
                node["content_boundary"] = True
                self.log(f"CONTENT BOUNDARY (Phase 2): '{node.get('name', '')}' ({control_type}) — skipping children")
            
            is_new = self.session.add(
                fingerprint_val=fp,
                node_dict=node,
                discovery_method="PROBE",
                exposure_path=exposure_path
            )
            if is_new:
                self.stored_fps.add(fp)
                self.stats["discovered"] += 1
                new_nodes.append(node)
                
                # Do NOT enqueue boundary elements for deeper probing
                if not is_boundary:
                    patterns = node.get("patterns", [])
                    action = self._get_probe_action(control_type, patterns)
                    if action and self.is_safe(node.get("name", "")):
                        self.probe_queue.append({
                            "fingerprint": fp,
                            "name": node.get("name", "unnamed"),
                            "control_type": control_type,
                            "automation_id": node.get("automation_id", ""),
                            "depth": depth,
                            "parent_exposure": exposure_path,
                            "action": action,
                        })
        elif fp:
            self.stored_fps.add(fp)
        
        # Do NOT recurse into content boundary children
        if is_boundary:
            return new_nodes
        
        for child in node.get("children", []):
            child_new = self._store_tree_phase2(child, exposure_path, depth + 1)
            new_nodes.extend(child_new)
        
        return new_nodes
    
    def _dequeue_data_children(self, new_children):
        """Remove any queued items whose fingerprints match data explosion children.
        
        When a data explosion is detected, we've already stored the children
        in the cache (they're valid elements), but we should NOT probe them
        further — they're data items, not app controls.
        """
        # Collect fingerprints of the data children
        data_fps = set()
        for child in new_children:
            fp = fingerprint.compute_fingerprint(child, child.get("path", ""))
            if fp:
                data_fps.add(fp)
        
        if not data_fps:
            return
        
        # Filter the probe queue
        original_len = len(self.probe_queue)
        self.probe_queue = collections.deque(
            item for item in self.probe_queue
            if item["fingerprint"] not in data_fps
        )
        removed = original_len - len(self.probe_queue)
        if removed > 0:
            self.log(f"Dequeued {removed} data items from probe queue")
    
    # -------------------------------------------------------------------------
    # UI INTERACTION
    # -------------------------------------------------------------------------
    
    def _take_action(self, element, action):
        """Execute a UI action on an element. Returns True on success."""
        try:
            if action == "expand":
                try:
                    element.expand()
                except Exception:
                    # Fallback: click to expand
                    element.click_input()
                return True
            elif action == "invoke":
                try:
                    element.invoke()
                except Exception:
                    element.click_input()
                return True
            elif action == "select":
                try:
                    element.select()
                except Exception:
                    element.click_input()
                return True
            elif action == "click":
                element.click_input()
                return True
        except Exception as e:
            self.log(f"Action '{action}' failed: {e}", "WARN")
        return False
    
    def _reset_ui(self):
        """
        Reset UI state by sending Escape keys and clicking safe area.
        Generic: works for any app with menus/dialogs.
        """
        try:
            # Send Escape multiple times to close menus/dialogs
            for _ in range(4):
                send_keys("{ESC}")
                time.sleep(0.1)
            
            # Click the center of the main window (safe area)
            try:
                rect = self.root_window.rectangle()
                center_x = rect.left + (rect.width() // 2)
                center_y = rect.top + (rect.height() // 2)
                import pyautogui
                pyautogui.click(center_x, center_y)
            except Exception:
                pass
            
            time.sleep(0.2)
        except Exception as e:
            self.log(f"UI reset error: {e}", "WARN")
    
    # -------------------------------------------------------------------------
    # LEGACY COMPAT
    # -------------------------------------------------------------------------
    
    def reset_ui(self, window):
        """Legacy compatibility wrapper."""
        self.root_window = window
        self._reset_ui()
