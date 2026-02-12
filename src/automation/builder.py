# automation_tree/builder.py
"""
Build accessibility tree snapshot from pywinauto window.
Converts UIA elements to normalized node format for fingerprinting and caching.
"""

import datetime
import json
import os

# Import fingerprint for tree hash computation
from src.automation import fingerprint


MAX_DEPTH = 12  # Support deep trees (Excel ribbon ~8 levels, dialogs ~10)
MAX_NAME_LEN = 512  # Truncate extremely long names


def get_patterns(elem) -> list:
    """Detect available UIA patterns on element."""
    patterns = []
    try:
        if hasattr(elem, 'iface_invoke') and elem.iface_invoke is not None:
            patterns.append("InvokePattern")
    except Exception:
        pass
    try:
        if hasattr(elem, 'iface_value') and elem.iface_value is not None:
            patterns.append("ValuePattern")
    except Exception:
        pass
    try:
        if hasattr(elem, 'iface_selection') and elem.iface_selection is not None:
            patterns.append("SelectionPattern")
    except Exception:
        pass
    try:
        if hasattr(elem, 'iface_selection_item'):
            # print(f"DEBUG: Checking SelectionItem for {elem} -> {elem.iface_selection_item}")
            if elem.iface_selection_item is not None:
                patterns.append("SelectionItemPattern")
    except Exception as e:
        # print(f"DEBUG: Error checking SelectionItem for {elem}: {e}")
        pass
    try:
        if hasattr(elem, 'iface_expand_collapse') and elem.iface_expand_collapse is not None:
            patterns.append("ExpandCollapsePattern")
    except Exception:
        pass
    try:
        if hasattr(elem, 'iface_text') and elem.iface_text is not None:
            patterns.append("TextPattern")
    except Exception:
        pass
    return patterns


def get_rect(elem) -> list:
    """Get bounding rectangle as [x, y, w, h]."""
    try:
        r = elem.rectangle()
        return [r.left, r.top, r.right - r.left, r.bottom - r.top]
    except Exception:
        return None


def truncate(s: str, max_len: int = MAX_NAME_LEN) -> str:
    """Truncate string if too long."""
    if s and len(s) > max_len:
        return s[:max_len] + "..."
    return s or ""


def node_from_elem(
    elem, 
    sibling_index: int, 
    parent_path: str = "", 
    depth: int = 0,
    parent_fingerprint: str = "",
    parent_exposure_path: list = None
) -> dict:
    """
    Build a node dict from a single pywinauto element.
    
    Args:
        elem: pywinauto element
        sibling_index: 0-based index
        parent_path: path string
        depth: recursion depth
        parent_fingerprint: fingerprint of parent node
        parent_exposure_path: list of steps to reach parent
    """
    if parent_exposure_path is None:
        parent_exposure_path = []
    
    # Extract name
    name = ""
    try:
        name = elem.window_text() or ""
    except Exception:
        pass
    if not name:
        try:
            name = getattr(elem.element_info, 'name', "") or ""
        except Exception:
            pass
    name = truncate(name)
    
    # Extract control type
    control_type = ""
    try:
        ct = elem.element_info.control_type
        control_type = str(ct) if ct else ""
    except Exception:
        pass
    
    # Extract automation ID
    automation_id = ""
    try:
        automation_id = getattr(elem.element_info, 'automation_id', "") or ""
    except Exception:
        pass
    automation_id = truncate(automation_id)
    
    # Build node
    node = {
        "name": name,
        "control_type": control_type,
        "automation_id": automation_id,
        "rect": get_rect(elem),
        "sibling_index": sibling_index,
        "patterns": get_patterns(elem),
        "path": parent_path,
        "children": [],
        "parent_fingerprint": parent_fingerprint
    }
    
    # Calculate Fingerprint (Stable)
    current_fp = ""
    try:
        current_fp = fingerprint.compute_fingerprint(node, parent_path)
    except Exception:
        pass

    # Determine Action Type
    action_type = "click" # Default
    if "ExpandCollapsePattern" in node["patterns"]:
        action_type = "expand"
    elif "InvokePattern" in node["patterns"]:
        action_type = "invoke"
    elif "SelectionItemPattern" in node["patterns"]:
        action_type = "select"
    
    # Construct Exposure Path (Parent Path + Current Step)
    current_step = {
        "fingerprint": current_fp,
        "action": action_type
    }
    
    # If parent has exposure path, append current step. 
    # But wait, parent_exposure_path is passed in.
    # The node's stored exposure path is how to reach IT.
    # So it should include parent's path + parent's action?
    # No, the exposure path is the sequence of actions to reach the *target*.
    # Actually, to reach *this* node, we need to have executed the parent's exposure path
    # AND then executed the action on the PARENT to verify/expose this node?
    # Or is exposure path just the chain of ancestors?
    # Requirement: "Step 1: Locate MenuBar -> Step 2: Click MenuBar"
    # So if I want to reach "Undo", I need to Click Edit Menu.
    # So "Undo" exposure path = [MenuBar(Click), EditMenu(Click/Expand)]
    # It does NOT include "Undo" itself in the exposure path steps that *expose* it.
    # But for execution planner, we might want the full chain including self?
    # Req: "Each element must store exposure path... Steps: Locate MenuBar -> Click MenuBar... Locate Undo -> Click Undo"
    # Actually, `build_execution_plan` uses this.
    # Let's store the ancestors in `exposure_path`.
    
    # Inherit parent exposure
    node_exposure = list(parent_exposure_path) 
    
    # If we have a parent fingerprint, add parent step to THIS node's exposure
    # Wait, parent_exposure_path passed to this function is the exposure path OF THE PARENT.
    # To expose THIS node, we need to interact with the PARENT.
    # So we add the parent's step to the list.
    
    # Correction: The `parent_exposure_path` arg should already include the path TO the parent.
    # We just store it? 
    # No, if I am a child of "Edit Menu", to reach me, "Edit Menu" must be expanded.
    # So my exposure path is: [Path to Edit Menu] + [Edit Menu Action].
    
    node["exposure_path"] = node_exposure
    
    # Calculate Anchor Neighbors (Phase 4 Requirement)
    # We do this logic later/in separate pass? 
    # Or capture simple ones here. For speed, maybe skip complex geometric anchors here 
    # and rely on locator dynamic recovery.
    node["anchor_neighbors"] = {} 
    
    # Build children if not at max depth
    if depth < MAX_DEPTH:
        try:
            children = elem.children()
            
            # Prepare exposure path to pass to children
            # It is MY exposure path + Action on ME.
            child_exposure = list(node_exposure)
            if current_fp:
                child_exposure.append({
                    "fingerprint": current_fp,
                    "action": action_type
                })
                
            for idx, child in enumerate(children):
                child_path = parent_path + ">" + (name or control_type) if parent_path else (name or control_type)
                
                # RECURSIVE CALL
                child_node = node_from_elem(
                    child, 
                    idx, 
                    child_path, 
                    depth + 1,
                    parent_fingerprint=current_fp,
                    parent_exposure_path=child_exposure
                )
                node["children"].append(child_node)
        except Exception as e:
            # Mark that children were inaccessible
            node["children_error"] = str(e)
    else:
        # Mark truncation at max depth
        try:
            if elem.children():
                node["children_truncated"] = True
        except Exception:
            pass
    
    return node



def count_nodes(node: dict) -> int:
    """Recursively count nodes in tree."""
    return 1 + sum(count_nodes(c) for c in node.get("children", []))


def build_tree_from_window(window, app_name: str = None) -> dict:
    """
    Build full accessibility tree from a pywinauto window.
    
    Args:
        window: pywinauto WindowSpecification
        app_name: optional app name for metadata
    
    Returns:
        Dict with "meta" and "root" keys
    """
    print(f"[builder] Building tree from window...")
    
    # Build root node
    root = node_from_elem(
        window, 
        sibling_index=0, 
        parent_path="", 
        depth=0,
        parent_fingerprint="",
        parent_exposure_path=[]
    )
    
    # Compute tree hash
    tree_hash = ""
    try:
        tree_hash = fingerprint.compute_tree_hash(root)
    except Exception as e:
        print(f"[builder] Warning: could not compute tree hash: {e}")
    
    # Build result with metadata
    result = {
        "meta": {
            "tree_hash": tree_hash,
            "generated_at": datetime.datetime.utcnow().isoformat() + "Z"
        },
        "root": root
    }
    
    if app_name:
        result["meta"]["app"] = app_name
    
    total = count_nodes(root)
    print(f"[builder] Tree built with {total} nodes")
    
    return result


def save_tree(tree: dict, out_path: str) -> bool:
    """
    Save tree JSON to disk (pretty-printed, UTF-8).
    
    Args:
        tree: tree dict from build_tree_from_window
        out_path: output file path
    
    Returns:
        True on success, False on failure
    """
    try:
        # Ensure directory exists
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        
        # Write atomically (tmp + rename)
        tmp_path = out_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(tree, f, indent=2, ensure_ascii=False)
        
        # Atomic rename
        if os.path.exists(out_path):
            os.remove(out_path)
        os.rename(tmp_path, out_path)
        
        print(f"[builder] Tree saved to: {out_path}")
        return True
    except Exception as e:
        print(f"[builder] Error saving tree: {e}")
        return False
