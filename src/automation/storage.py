# automation_tree/storage.py
"""
Persistent cache manager for discovered UI elements.
Stores elements by fingerprint with task history for future reuse.
"""

import datetime
import json
import os
import re

# Cache directory relative to this module
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), ".cache")

CRAWLER_VERSION = "1.0"
MAX_NAME_LEN = 512


def safe_filename(app_name: str) -> str:
    """Convert app name to safe filename."""
    s = re.sub(r'[^\w\-]', '_', app_name)
    return s.lower()


def get_cache_path(app_name: str) -> str:
    """
    Get path to cache file for an app.
    Creates cache directory if missing.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    return os.path.join(CACHE_DIR, f"{safe_filename(app_name)}.json")


def utc_now_iso() -> str:
    """Get current UTC timestamp in ISO-8601 format."""
    return datetime.datetime.utcnow().isoformat() + "Z"


def load_cache(app_name: str) -> dict:
    """
    Load cache for an app from disk.
    Returns skeleton dict if file doesn't exist.
    """
    path = get_cache_path(app_name)
    
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                cache = json.load(f)
                print(f"[storage] Loaded cache for '{app_name}' with {len(cache.get('elements', {}))} elements")
                return cache
        except Exception as e:
            print(f"[storage] Error loading cache: {e}")
    
    # Return skeleton
    return {
        "app": app_name,
        "app_hash": None,
        "crawler_version": CRAWLER_VERSION,
        "last_updated": None,
        "elements": {}
    }


def save_cache(app_name: str, cache_dict: dict) -> bool:
    """
    Save cache to disk atomically (tmp + rename).
    
    Returns:
        True on success, False on failure
    """
    path = get_cache_path(app_name)
    tmp_path = path + ".tmp"
    
    try:
        # Update timestamp
        cache_dict["last_updated"] = utc_now_iso()
        
        # Write to temp file
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(cache_dict, f, indent=2, ensure_ascii=False)
        
        # Atomic rename
        if os.path.exists(path):
            os.remove(path)
        os.rename(tmp_path, path)
        
        print(f"[storage] Cache saved: {path}")
        return True
    except Exception as e:
        print(f"[storage] Error saving cache: {e}")
        # Cleanup temp file if exists
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except Exception:
                pass
        return False


def truncate(s: str, max_len: int = MAX_NAME_LEN) -> str:
    """Truncate string if too long."""
    if s and len(s) > max_len:
        return s[:max_len] + "..."
    return s or ""


def add_element(
    app_name: str, 
    fingerprint_val: str, 
    node_dict: dict, 
    discovery_method: str = "AX",
    exposure_path: list = None
) -> bool:
    """
    Add or update an element in the cache.
    
    Args:
        app_name: Application name
        fingerprint_val: Element fingerprint (hex string)
        node_dict: Node dictionary from builder
        discovery_method: "AX" or "VISION"
        exposure_path: Action-aware exposure path (list of dicts)
    
    Returns:
        True on success
    """
    cache = load_cache(app_name)
    now = utc_now_iso()
    
    # Check if element already exists
    if fingerprint_val in cache["elements"]:
        # Update last_used only
        cache["elements"][fingerprint_val]["last_used"] = now
        print(f"[storage] Updated existing element: {fingerprint_val[:8]}...")
    else:
        # Add new element
        cache["elements"][fingerprint_val] = {
            "name": truncate(node_dict.get("name", "")),
            "control_type": str(node_dict.get("control_type", "")),
            "automation_id": truncate(node_dict.get("automation_id", "")),
            "path": node_dict.get("path", ""),
            "rect": node_dict.get("rect"),
            "patterns": node_dict.get("patterns", []),
            "timestamp": datetime.datetime.utcnow().isoformat(),
            # Use argument OR node_dict, defaulting to []
            "exposure_path": exposure_path if exposure_path is not None else node_dict.get("exposure_path", []),
            "parent_fingerprint": node_dict.get("parent_fingerprint", ""),
            "anchor_neighbors": node_dict.get("anchor_neighbors", {}),
            "tasks_succeeded": [],
            # Performance/History stats (preserve if exists)
            "discovery_method": discovery_method,
            "content_boundary": node_dict.get("content_boundary", False),
            "created_at": now,
            "last_used": now
        }
        print(f"[storage] Added new element: {fingerprint_val[:8]}... ({node_dict.get('name', 'unnamed')[:30]})")
    
    return save_cache(app_name, cache)


def record_success(app_name: str, fingerprint: str, task: str) -> bool:
    """
    Record a successful task execution for an element.
    
    Args:
        app_name: Application name
        fingerprint: Element fingerprint
        task: Task description that succeeded
    
    Returns:
        True on success
    """
    cache = load_cache(app_name)
    
    if fingerprint not in cache["elements"]:
        print(f"[storage] Warning: fingerprint {fingerprint[:8]}... not found in cache")
        return False
    
    elem = cache["elements"][fingerprint]
    
    # Add task if not already recorded
    if task not in elem["tasks_succeeded"]:
        elem["tasks_succeeded"].append(task)
        print(f"[storage] Recorded success for task: '{task[:30]}...'")
    
    # Update last_used
    elem["last_used"] = utc_now_iso()
    
    return save_cache(app_name, cache)


def remove_element(app_name: str, fingerprint: str) -> bool:
    """
    Remove an element from the cache.
    
    Args:
        app_name: Application name
        fingerprint: Element fingerprint to remove
    
    Returns:
        True if removed, False if not found or error
    """
    cache = load_cache(app_name)
    
    if fingerprint not in cache["elements"]:
        print(f"[storage] Element {fingerprint[:8]}... not found")
        return False
    
    del cache["elements"][fingerprint]
    print(f"[storage] Removed element: {fingerprint[:8]}...")
    
    return save_cache(app_name, cache)


def get_all_elements(app_name: str) -> dict:
    """Get all cached elements for an app."""
    cache = load_cache(app_name)
    return cache.get("elements", {})


def clear_cache(app_name: str) -> bool:
    """Clear all elements from cache (keep structure)."""
    cache = load_cache(app_name)
    cache["elements"] = {}
    return save_cache(app_name, cache)


class CacheSession:
    """
    In-memory cache session for batch operations.
    Loads JSON once, accumulates changes, writes once on flush().
    
    Usage:
        session = CacheSession("Notepad")
        session.add("fp1", node1)
        session.add("fp2", node2)
        session.flush()  # Single disk write
    """
    
    def __init__(self, app_name: str, clear: bool = False):
        self.app_name = app_name
        if clear:
            clear_cache(app_name)
        self.cache = load_cache(app_name)
        self._dirty = False
        self._added = 0
        self._updated = 0
    
    def add(self, fingerprint_val: str, node_dict: dict, 
            discovery_method: str = "PROBE", exposure_path: list = None) -> bool:
        """Add or update element in memory. Returns True if new."""
        now = utc_now_iso()
        
        if fingerprint_val in self.cache["elements"]:
            self.cache["elements"][fingerprint_val]["last_used"] = now
            self._updated += 1
            self._dirty = True
            return False
        else:
            self.cache["elements"][fingerprint_val] = {
                "name": truncate(node_dict.get("name", "")),
                "control_type": str(node_dict.get("control_type", "")),
                "automation_id": truncate(node_dict.get("automation_id", "")),
                "path": node_dict.get("path", ""),
                "rect": node_dict.get("rect"),
                "patterns": node_dict.get("patterns", []),
                "timestamp": datetime.datetime.utcnow().isoformat(),
                "exposure_path": exposure_path if exposure_path is not None else node_dict.get("exposure_path", []),
                "parent_fingerprint": node_dict.get("parent_fingerprint", ""),
                "anchor_neighbors": node_dict.get("anchor_neighbors", {}),
                "tasks_succeeded": [],
                "discovery_method": discovery_method,
                "created_at": now,
                "last_used": now
            }
            self._added += 1
            self._dirty = True
            return True
    
    def has(self, fingerprint_val: str) -> bool:
        """Check if fingerprint exists in session cache."""
        return fingerprint_val in self.cache.get("elements", {})
    
    def get(self, fingerprint_val: str) -> dict:
        """Get element by fingerprint, or empty dict."""
        return self.cache.get("elements", {}).get(fingerprint_val, {})
    
    def count(self) -> int:
        """Total elements in session."""
        return len(self.cache.get("elements", {}))
    
    def flush(self) -> bool:
        """Write accumulated changes to disk (single I/O op)."""
        if not self._dirty:
            return True
        print(f"[storage] Flushing session: {self._added} added, {self._updated} updated, {self.count()} total")
        result = save_cache(self.app_name, self.cache)
        if result:
            self._dirty = False
        return result
    
    @property
    def stats(self) -> dict:
        return {"added": self._added, "updated": self._updated, "total": self.count()}
