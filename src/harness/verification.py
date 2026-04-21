# harness/verification.py
"""
Research-grade Action verification layer for the hybrid GUI automation harness.
Implements multi-signal verification using Tree Hashes, Focus, Element Properties, 
Text Maps, and Screenshot Hashing.
"""

import time
import os
import json
import sys
from typing import Dict, Any, Tuple, List, Optional
from dataclasses import dataclass, field
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from src.automation import fingerprint

_VERIFY_MAX_DESCENDANTS = max(100, int(os.getenv("SARA_VERIFY_MAX_DESCENDANTS", "500") or "500"))

@dataclass
class VerificationResult:
    """Structured result of verification check."""
    success: bool
    confidence: float
    signals: Dict[str, bool] = field(default_factory=dict)
    primary_signal: str = ""
    verification_time_ms: int = 0
    details: str = ""

class VerificationEngine:
    def __init__(self, use_imagehash=True):
        self.use_imagehash = use_imagehash
        try:
            import imagehash
            self.imagehash = imagehash
        except ImportError:
            self.imagehash = None

    def capture_full_state(self, window) -> Dict[str, Any]:
        """
        Capture comprehensive UI state for multi-signal verification.
        """
        state = {
            "title": "",
            "tree_hash": "",
            "focused": "",
            "element_count": 0,
            "text_map": {},  # fingerprint -> text
            "properties": {}, # fingerprint -> {value, toggle, selection}
            "timestamp": time.time()
        }
        
        try:
            state["title"] = window.window_text() or ""
            
            # Use a bounded descendant scan that still captures modal/dialog controls.
            descendants = window.descendants()[:_VERIFY_MAX_DESCENDANTS]
            state["element_count"] = len(descendants)
            
            for idx, elem in enumerate(descendants):
                try:
                    # Basic info for fingerprinting
                    name = ""
                    try: name = elem.window_text() or ""
                    except: pass
                    
                    auto_id = ""
                    try: auto_id = getattr(elem.element_info, 'automation_id', "") or ""
                    except: pass
                    
                    control_type = ""
                    try: control_type = str(elem.element_info.control_type) if elem.element_info.control_type else ""
                    except: pass
                    
                    node_partial = {
                        "name": name[:100],
                        "control_type": control_type,
                        "automation_id": auto_id[:100],
                        "sibling_index": idx % 100
                    }
                    fp = fingerprint.compute_fingerprint(node_partial, "")

                    # Capture Properties first so editable fields can be tracked even when window_text is empty.
                    props = {}
                    if hasattr(elem, 'get_value'):
                        try:
                            value = elem.get_value()
                            if value not in (None, ""):
                                props["value"] = str(value)
                        except:
                            pass

                    if "value" not in props and hasattr(elem, 'iface_value'):
                        try:
                            iface_value = getattr(elem, 'iface_value')
                            current_value = getattr(iface_value, 'CurrentValue', None)
                            if current_value not in (None, ""):
                                props["value"] = str(current_value)
                        except:
                            pass

                    if "value" not in props and hasattr(elem, 'legacy_properties'):
                        try:
                            legacy = elem.legacy_properties() or {}
                            legacy_value = legacy.get("Value")
                            if legacy_value not in (None, ""):
                                props["value"] = str(legacy_value)
                        except:
                            pass
                    
                    # Capture Focus
                    if hasattr(elem, 'has_keyboard_focus') and elem.has_keyboard_focus():
                        state["focused"] = fp
                    
                    # Capture Text
                    display_name = name
                    if not display_name and props.get("value"):
                        display_name = props["value"]
                    state["text_map"][fp] = display_name
                    
                    patterns = [] # Heuristic patterns
                    if hasattr(elem, 'iface_toggle'): patterns.append("toggle")
                    if hasattr(elem, 'iface_selection_item'): patterns.append("selection")
                    
                    if "toggle" in patterns:
                        try: props["toggle_state"] = elem.get_toggle_state()
                        except: pass
                    
                    if props:
                        state["properties"][fp] = props
                        
                except:
                    continue
                    
            # Include both structure and visible value snapshots in tree hash.
            tree_signature = tuple(sorted((fp, state["text_map"].get(fp, "")) for fp in state["text_map"]))
            state["tree_hash"] = str(hash(tree_signature))
            
        except Exception as e:
            print(f"[verification] Error capturing state: {e}")
            
        return state

    def compute_image_hash(self, screenshot_path: str) -> Optional[str]:
        """Compute perceptual hash of image."""
        if not os.path.exists(screenshot_path):
            return None
            
        try:
            img = Image.open(screenshot_path)
            if self.imagehash:
                return str(self.imagehash.phash(img))
            else:
                return self._compute_average_hash(img)
        except:
            return None

    def _compute_average_hash(self, img: Image.Image) -> str:
        """Manual implementation of Average Hash."""
        # Grayscale -> 8x8 -> Average -> Binary
        img = img.convert('L').resize((8, 8), Image.Resampling.LANCZOS)
        pixels = list(img.getdata())
        avg = sum(pixels) / len(pixels)
        bits = "".join(['1' if p > avg else '0' for p in pixels])
        return hex(int(bits, 2))

    def verify(
        self, 
        window, 
        pre_state: Dict, 
        pre_img_path: str = None, 
        post_img_path: str = None,
        timeout_ms: int = 1500
    ) -> VerificationResult:
        """
        Execute layered verification.
        """
        start_time = time.time()
        time.sleep(0.35) # Wait briefly for UI to settle
        
        post_state = self.capture_full_state(window)
        
        signals = {
            "tree_hash_changed": post_state["tree_hash"] != pre_state["tree_hash"],
            "focus_changed": post_state["focused"] != pre_state["focused"],
            "property_changed": self._compare_properties(pre_state["properties"], post_state["properties"]),
            "text_changed": self._compare_text_maps(pre_state["text_map"], post_state["text_map"]),
            "element_count_changed": post_state["element_count"] != pre_state["element_count"],
            "screenshot_changed": False
        }
        
        # Audio/Visual signal
        if pre_img_path and post_img_path:
            pre_hash = self.compute_image_hash(pre_img_path)
            post_hash = self.compute_image_hash(post_img_path)
            if pre_hash and post_hash:
                signals["screenshot_changed"] = pre_hash != post_hash
        
        any_signal = any(signals.values())
        
        # Determine primary signal and confidence
        primary = ""
        confidence = 0.0
        if any_signal:
            priority = ["text_changed", "property_changed", "tree_hash_changed", "focus_changed", "screenshot_changed", "element_count_changed"]
            for s in priority:
                if signals[s]:
                    primary = s
                    confidence = 0.9 if s in ["text_changed", "property_changed"] else 0.7
                    break
        
        return VerificationResult(
            success=any_signal,
            confidence=confidence,
            signals=signals,
            primary_signal=primary,
            verification_time_ms=int((time.time() - start_time) * 1000),
            details=f"Primary signal: {primary}" if any_signal else "No change detected"
        )

    def _compare_properties(self, pre: Dict, post: Dict) -> bool:
        for fp, props in pre.items():
            if fp in post and post[fp] != props:
                return True
        for fp in post:
            if fp not in pre:
                return True
        return False

    def _compare_text_maps(self, pre: Dict, post: Dict) -> bool:
        for fp, text in pre.items():
            if fp in post and post[fp] != text:
                return True
        # Also check if new fingerprints appeared with text
        for fp in post:
            if fp not in pre:
                return True
        return False

# Compatibility wrappers
_engine = VerificationEngine()

def capture_state(window):
    return _engine.capture_full_state(window)

def verify_action(window, pre_state, post_wait_ms=500, timeout_ms=3000):
    # This wrapper maintains compatibility with existing calls
    res = _engine.verify(window, pre_state, timeout_ms=timeout_ms)
    return res

def quick_verify(window, pre_state):
    return _engine.verify(window, pre_state, timeout_ms=1000)

def deep_verify(window, pre_state):
    return _engine.verify(window, pre_state, timeout_ms=5000)
