# automation_tree/fingerprint.py
import hashlib
import json
import re

def normalize_text(s: str) -> str:
    if s is None:
        return ""
    s = s.lower().strip()
    # remove punctuation except dash/underscore
    s = re.sub(r"[^\w\s\-]", "", s)
    s = re.sub(r"\s+", " ", s)
    return s

def node_identity_string(node: dict, parent_path: str = "") -> str:
    """
    node: dict with keys: name, control_type, automation_id, bounding_box, sibling_index
    parent_path: string like "Window>Toolbar"
    """
    parts = []
    parts.append(node.get("control_type", "") or "")
    # normalized name: take only short label
    parts.append(normalize_text(node.get("name", "") or ""))
    parts.append(normalize_text(node.get("automation_id", "") or ""))
    parts.append(parent_path or "")
    # sibling index ensures difference among repeated items
    parts.append(str(node.get("sibling_index", "")))
    # bounding box quantized at 20px grid (configurable)
    bbox = node.get("rect")
    if bbox:
        x, y, w, h = bbox
        gx = int(x // 20)
        gy = int(y // 20)
        parts.append(f"{gx}:{gy}")
    identity = "|".join(parts)
    return identity

def compute_hybrid_fingerprint(node: dict, parent_path: str = "") -> dict:
    """
    Compute a multi-modal fingerprint:
    - stable: core identity (Role, Name, Parent)
    - contextual: SimHash-style summary of local neighborhood
    """
    # 1. Stable Identity (Fuzzy)
    s_parts = [
        str(node.get("control_type", "")),
        normalize_text(node.get("name", "") or ""),
        parent_path or ""
    ]
    stable_str = "|".join(s_parts)
    stable_hash = hashlib.sha256(stable_str.encode("utf-8")).hexdigest()[:16]
    
    # 2. Contextual Summary (Children & Siblings)
    neighbor_names = [normalize_text(c.get("name", "")) for c in node.get("children", [])[:5]]
    context_str = stable_str + ":" + "-".join(neighbor_names)
    context_hash = hashlib.sha256(context_str.encode("utf-8")).hexdigest()[:16]
    
    return {
        "stable": stable_hash,
        "contextual": context_hash,
        "full_identity": stable_str + "|" + str(node.get("sibling_index", ""))
    }

def compute_fingerprint(node: dict, parent_path: str = "") -> str:
    """Legacy wrapper for backward compatibility."""
    return compute_hybrid_fingerprint(node, parent_path)["stable"]

def compute_tree_hash(tree: dict) -> str:
    """
    Compute a hash for entire tree to detect major UI changes.
    Approach: collect fingerprints of all nodes, sort, concat and hash.
    """
    fingerprints = []

    def rec(n, path=""):
        # sibling_index might not exist; ensure it's set by builder
        fp = compute_fingerprint(n, path)
        fingerprints.append(fp)
        for idx, ch in enumerate(n.get("children", [])):
            child_path = path + ">" + normalize_text(n.get("name", "") or n.get("control_type", ""))
            # ensure child carries sibling_index if not set
            if "sibling_index" not in ch:
                ch["sibling_index"] = idx
            rec(ch, child_path)

    rec(tree, "")
    fingerprints.sort()
    big = "".join(fingerprints)
    return hashlib.sha256(big.encode("utf-8")).hexdigest()
