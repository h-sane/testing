"""
Cache integrity analyzer. Zero-tolerance checks.
Usage: python scripts/analyze_cache_integrity.py [--app AppName]
"""

import sys
import os
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.automation import storage


def analyze_integrity(app_name="Notepad"):
    print(f"=== Cache Integrity Analysis: {app_name} ===\n")
    
    cache_path = storage.get_cache_path(app_name)
    
    if not os.path.exists(cache_path):
        print(f"FAIL: Cache file not found: {cache_path}")
        return False
    
    with open(cache_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    elements = data.get("elements", {})
    print(f"Total elements: {len(elements)}")
    
    issues = []
    warnings = []
    
    def fail(msg):
        issues.append(msg)
    
    def warn(msg):
        warnings.append(msg)
    
    # ---- 1. Uniqueness (JSON keys are unique by definition) ----
    print("\n[1] Uniqueness Check...")
    # Check for effective duplicates: same name+type+path but different FP
    identity_map = {}
    dup_count = 0
    for fp, node in elements.items():
        identity = f"{node.get('name','')}|{node.get('control_type','')}|{node.get('path','')}"
        if identity in identity_map and identity.strip("|"):
            dup_count += 1
            if dup_count <= 5:
                warn(f"Effective duplicate: '{node.get('name','')}' ({node.get('control_type','')}) "
                     f"FPs: {identity_map[identity][:8]}, {fp[:8]}")
        else:
            identity_map[identity] = fp
    
    if dup_count == 0:
        print("  PASS: No effective duplicates")
    else:
        print(f"  WARN: {dup_count} effective duplicates (may be intentional — e.g., list items)")
    
    # ---- 2. Connectivity (Parent refs) ----
    print("\n[2] Connectivity Check...")
    orphan_count = 0
    orphan_details = []
    
    for fp, node in elements.items():
        parent_fp = node.get("parent_fingerprint", "")
        if parent_fp and parent_fp not in elements:
            orphan_count += 1
            if orphan_count <= 10:
                orphan_details.append(
                    f"  Orphan: '{node.get('name','?')[:30]}' ({node.get('control_type','?')}) "
                    f"-> missing parent {parent_fp[:8]}"
                )
    
    if orphan_count == 0:
        print("  PASS: All parent references valid")
    else:
        fail(f"CONNECTIVITY: {orphan_count} orphan nodes with missing parents")
        for d in orphan_details:
            print(d)
        if orphan_count > 10:
            print(f"  ... and {orphan_count - 10} more")
    
    # ---- 3. Exposure Path Validity ----
    print("\n[3] Exposure Path Validity...")
    broken_paths = 0
    
    for fp, node in elements.items():
        for step in node.get("exposure_path", []):
            step_fp = step.get("fingerprint", "")
            if step_fp and step_fp not in elements:
                broken_paths += 1
                if broken_paths <= 5:
                    fail(f"BROKEN PATH: '{node.get('name','?')[:30]}' references missing step {step_fp[:8]}")
                break
    
    if broken_paths == 0:
        print("  PASS: All exposure path steps reference cached elements")
    else:
        fail(f"EXPOSURE PATHS: {broken_paths} elements have broken paths")
    
    # ---- 4. Completeness (Heuristic depth check) ----
    print("\n[4] Completeness Check...")
    
    # Check for reasonable element count
    if len(elements) < 10:
        fail(f"COMPLETENESS: Only {len(elements)} elements — suspiciously low")
    else:
        print(f"  PASS: {len(elements)} elements (reasonable)")
    
    # Check for menu items (case-insensitive)
    control_types = set(n.get("control_type", "") for n in elements.values())
    has_menu_items = "MenuItem" in control_types
    if has_menu_items:
        menu_count = sum(1 for n in elements.values() if n.get("control_type") == "MenuItem")
        print(f"  INFO: {menu_count} MenuItems found")
    
    # App-specific known-element check (case-insensitive)
    known_elements = {
        "Notepad": ["page setup", "find", "replace", "save as"],
        "Calculator": ["one", "two", "equals", "plus"],
    }
    
    if app_name in known_elements:
        all_names_lower = {n.get("name", "").lower() for n in elements.values()}
        for expected in known_elements[app_name]:
            found = any(expected in name for name in all_names_lower)
            if found:
                print(f"  PASS: Known element '{expected}' found")
            else:
                fail(f"COMPLETENESS: Known element '{expected}' NOT found")
    
    # ---- 5. External Leak Check ----
    print("\n[5] Boundary Check...")
    leaks = []
    for fp, node in elements.items():
        name = node.get("name", "")
        if any(ext in name for ext in ["Taskbar", "Program Manager", "Desktop"]):
            leaks.append(name[:40])
    
    if not leaks:
        print("  PASS: No external app leaks")
    else:
        for l in leaks:
            fail(f"EXTERNAL LEAK: '{l}'")
    
    # ---- SUMMARY ----
    print("\n" + "=" * 50)
    
    if warnings:
        print(f"\nWarnings ({len(warnings)}):")
        for w in warnings:
            print(f"  ⚠️  {w}")
    
    if not issues:
        print("\n✅ OVERALL: PASS — Cache integrity verified")
        return True
    else:
        print(f"\n❌ OVERALL: FAIL — {len(issues)} issue(s) found:")
        for issue in issues:
            print(f"  ✗ {issue}")
        
        # Write report
        report_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 
                                   "integrity_report.txt")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(issues))
        print(f"\nReport written to: {report_path}")
        
        sys.exit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", default="Notepad", help="App name to check")
    args = parser.parse_args()
    analyze_integrity(args.app)
