# uia_utils.py
from pywinauto import Application
from pywinauto import Desktop
import json, time, os

def attach_or_start(exe_path, timeout=8):
    """Try to attach to a running process by exe_path; otherwise start it if available."""
    try:
        app = Application(backend="uia").connect(path=exe_path, timeout=2)
        return app
    except Exception:
        try:
            app = Application(backend="uia").start(exe_path, timeout=timeout)
            time.sleep(2)
            return app
        except Exception as e:
            return None

def dump_window_tree(window, out_path):
    """
    Save a textual snapshot of window children to out_path.
    window: pywinauto WindowSpecification or ElementInfo
    """
    def rec(elem, depth=0):
        try:
            props = elem.element_info._element
        except Exception:
            props = None
        try:
            name = elem.window_text() if hasattr(elem, "window_text") else str(elem)
        except Exception:
            name = "(no name)"
        ctrl_type = getattr(elem.element_info, "control_type", "Unknown")
        aid = getattr(elem.element_info, "automation_id", None)
        node = {"name": name, "control_type": ctrl_type, "automation_id": aid}
        children = []
        try:
            for ch in elem.children():
                children.append(rec(ch, depth+1))
        except Exception:
            pass
        node["children"] = children
        return node
    try:
        root = rec(window)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(root, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e:
        return False

def find_candidate_by_name(window, target_text, fuzz=False):
    """Find first child whose name contains target_text (case-insensitive)."""
    target = target_text.lower().strip()
    try:
        for elem in window.descendants():
            try:
                name = (elem.window_text() or "").lower()
            except Exception:
                name = ""
            if not name:
                continue
            if target in name:
                return elem
        return None
    except Exception:
        return None

def try_invoke(elem):
    """Try to invoke element using InvokePattern."""
    try:
        elem.invoke()
        return True
    except Exception:
        # fallback: try click_input()
        try:
            elem.click_input()
            return True
        except Exception:
            return False
