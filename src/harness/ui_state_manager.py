# harness/ui_state_manager.py
"""
Universal Home State Recovery.

Ensures an application returns to its "home" state (main UI with menu bar,
toolbar, default view) before each task.  This handles invasive pages like
Settings tabs, Backstage views, and nested navigation panes that hide the
primary UI.

Strategy (progressive, each stage is attempted only if needed):

  Stage 1 — ESC×2    : close overlay menus, tooltips, dropdowns
  Stage 2 — Dialog   : dismiss modal/modeless dialogs via ESC or Cancel
  Stage 3 — Back Nav : detect Back buttons (unlimited depth) and click
                       until the home state is restored
  Stage 4 — Validate : scan for menu bar / expected landmarks

The back-button detection is fully app-agnostic and uses common UIA
patterns found across WinUI, UWP, Electron, Office, and browser apps.
"""

import time
from typing import Optional, List, Tuple, Any

# ---------------------------------------------------------------------------
# BACK-BUTTON DETECTION PATTERNS (universal)
# ---------------------------------------------------------------------------

#  Name patterns (case-insensitive substring match)
_BACK_NAME_PATTERNS = [
    "back",
    "go back",
    "navigate back",
    "←",
    "🔙",
    "返回",          # Chinese  – common in global Electron apps
    "previous",
]

#  AutomationId patterns (case-insensitive substring match)
_BACK_AID_PATTERNS = [
    "backbutton",
    "navigationviewbackbutton",
    "btnback",
    "back_button",
    "gobackbutton",
    "nav-back",
    "btn-back",
    "back-btn",
    "arrowleft",
    "navbackbutton",
]

#  ClassName patterns (case-insensitive substring match)
_BACK_CLASSNAME_PATTERNS = [
    "navigationviewbackbutton",
    "NavigationBackButton",
]

#  ControlType filter — only these are eligible as back buttons
_BACK_CONTROL_TYPES = {"button", "menuitem", "hyperlink", "image", "custom"}


# ---------------------------------------------------------------------------
# HOME-STATE LANDMARK PATTERNS
# ---------------------------------------------------------------------------

# If any of these control types are found among the top-level descendants,
# we consider the app to be in its home state.
_HOME_LANDMARK_TYPES = {"menubar", "menuitem", "toolbar", "tabcontrol"}


# ---------------------------------------------------------------------------
# HELPERS
# ---------------------------------------------------------------------------

def _safe_descendants(window, retries: int = 2) -> list:
    """Get descendants with COM resilience."""
    for attempt in range(retries):
        try:
            return window.descendants()
        except Exception as e:
            if "-2147220991" in str(e) and attempt < retries - 1:
                try:
                    window.set_focus()
                    time.sleep(0.3)
                except:
                    pass
            else:
                raise
    return []


def _elem_prop(elem, prop: str) -> str:
    """Safely get a string property from an element."""
    try:
        if prop == "name":
            val = elem.window_text() or ""
            if not val:
                val = getattr(elem.element_info, "name", "") or ""
            return val.strip()
        if prop == "control_type":
            return (str(elem.element_info.control_type) or "").strip()
        if prop == "automation_id":
            return (getattr(elem.element_info, "automation_id", "") or "").strip()
        if prop == "class_name":
            return (getattr(elem.element_info, "class_name", "") or "").strip()
    except:
        pass
    return ""


def _matches_any(value: str, patterns: list) -> bool:
    """Case-insensitive substring match against a list of patterns."""
    v = value.lower()
    return any(p.lower() in v for p in patterns)


# ---------------------------------------------------------------------------
# DETECTION
# ---------------------------------------------------------------------------

def _find_back_button(descendants: list) -> Optional[Any]:
    """
    Scan descendants for a back-navigation button using universal heuristics.
    Returns the best candidate element or None.
    """
    candidates: List[Tuple[int, Any]] = []   # (priority, elem)

    for elem in descendants:
        ctype = _elem_prop(elem, "control_type").lower()
        if ctype and ctype not in _BACK_CONTROL_TYPES:
            continue

        name = _elem_prop(elem, "name")
        aid  = _elem_prop(elem, "automation_id")
        cls  = _elem_prop(elem, "class_name")

        # Priority scoring — lower = better match
        priority = 100

        # AutomationId is the most reliable signal
        if aid and _matches_any(aid, _BACK_AID_PATTERNS):
            priority = 10

        # ClassName is reliable for WinUI
        elif cls and _matches_any(cls, _BACK_CLASSNAME_PATTERNS):
            priority = 15

        # Name is common but can false-positive ("Playback", etc.)
        elif name and _matches_any(name, _BACK_NAME_PATTERNS):
            # Exclude false positives by checking name length and specificity
            n_lower = name.lower().strip()
            if n_lower in ("back", "go back", "←", "🔙", "navigate back", "返回", "previous"):
                priority = 20
            elif n_lower.startswith("back") and len(n_lower) < 15:
                priority = 30
            else:
                # "Playback", "Feedback", etc. — skip
                continue
        else:
            continue

        candidates.append((priority, elem))

    if not candidates:
        return None

    # Return the highest-priority (lowest number) candidate
    candidates.sort(key=lambda x: x[0])
    winner = candidates[0]
    name = _elem_prop(winner[1], "name")
    aid  = _elem_prop(winner[1], "automation_id")
    print(f"[home_recovery] Back button detected: name='{name}' aid='{aid}' priority={winner[0]}")
    return winner[1]


def _has_home_landmarks(descendants: list) -> bool:
    """Check if any home-state landmark elements are present."""
    for elem in descendants:
        ctype = _elem_prop(elem, "control_type").lower()
        if ctype in _HOME_LANDMARK_TYPES:
            return True
    return False


def _has_back_button(descendants: list) -> bool:
    """Quick check whether a back-navigation button is visible.

    A visible Back button is the strongest universal signal that the app
    is NOT in its home state (it is on a sub-page).  Even if other home
    landmarks like TabControl exist, the presence of a Back button means
    we must navigate back first.
    """
    for elem in descendants:
        ctype = _elem_prop(elem, "control_type").lower()
        if ctype and ctype not in _BACK_CONTROL_TYPES:
            continue
        aid = _elem_prop(elem, "automation_id")
        if aid and _matches_any(aid, _BACK_AID_PATTERNS):
            return True
        cls = _elem_prop(elem, "class_name")
        if cls and _matches_any(cls, _BACK_CLASSNAME_PATTERNS):
            return True
        name = _elem_prop(elem, "name")
        if name:
            n_lower = name.lower().strip()
            if n_lower in ("back", "go back", "\u2190", "\U0001f519",
                           "navigate back", "\u8fd4\u56de", "previous"):
                return True
            if n_lower.startswith("back") and len(n_lower) < 15:
                return True
    return False


def _is_truly_home(descendants: list) -> bool:
    """Combined home-state check: landmarks present AND no Back button.

    Win11 apps (e.g. Notepad Settings page) can show TabControl and
    MenuItem elements even on sub-pages.  The Back button is the
    universal indicator that the user has navigated away from the
    primary view.
    """
    if not _has_home_landmarks(descendants):
        return False
    if _has_back_button(descendants):
        return False          # sub-page — must navigate back
    return True


def _has_dialog(descendants: list) -> bool:
    """Check if a modal dialog is open."""
    for elem in descendants:
        ctype = _elem_prop(elem, "control_type").lower()
        if ctype in ("dialog", "window"):
            name = _elem_prop(elem, "name")
            # True dialog windows typically have a name
            if name and len(name) > 2:
                cls = _elem_prop(elem, "class_name")
                if "dialog" in cls.lower() or "popup" in cls.lower():
                    return True
    return False


# ---------------------------------------------------------------------------
# PUBLIC API
# ---------------------------------------------------------------------------

def ensure_home_state(
    window,
    app_name: str,
    trace_logger=None,
    max_back_attempts: int = 20,     # safety limit only (not functional cap)
    verbose: bool = True,
) -> dict:
    """
    Ensure the application is in its home state.

    Runs a progressive 4-stage recovery and returns a result dict:
        {
            "recovered": bool,
            "stages_used": list[str],
            "back_clicks": int,
            "home_landmarks_found": bool,
        }

    Parameters
    ----------
    window : pywinauto WindowSpecification
        The application window handle.
    app_name : str
        Application name (for logging only).
    trace_logger : optional
        If provided, log recovery events.
    max_back_attempts : int
        Safety ceiling on how many Back clicks are attempted.
        This is NOT a functional limit — the loop exits as soon
        as no more Back buttons are found or home landmarks appear.
    verbose : bool
        Print progress to stdout.
    """
    result = {
        "recovered": False,
        "stages_used": [],
        "back_clicks": 0,
        "home_landmarks_found": False,
    }

    tag = f"[home_recovery] [{app_name}]"

    # ------------------------------------------------------------------
    # Stage 1: ESC×2 — close overlay menus
    # ------------------------------------------------------------------
    try:
        if verbose:
            print(f"{tag} Stage 1: ESC×2 overlay dismiss")
        window.type_keys("{ESC}{ESC}", pause=0.05)
        time.sleep(0.2)
        result["stages_used"].append("ESC")
    except Exception as e:
        if verbose:
            print(f"{tag} Stage 1 skipped: {e}")

    # Quick check — maybe ESC was enough
    descendants = _safe_descendants(window)
    if _is_truly_home(descendants):
        result["recovered"] = True
        result["home_landmarks_found"] = True
        if verbose:
            print(f"{tag} Home state confirmed after ESC ({len(descendants)} elements)")
        return result
    elif _has_home_landmarks(descendants) and _has_back_button(descendants):
        if verbose:
            print(f"{tag} Landmarks present but Back button detected — sub-page, "
                  f"continuing to Stage 3 ({len(descendants)} elements)")

    # ------------------------------------------------------------------
    # Stage 2: Dialog dismissal
    # ------------------------------------------------------------------
    if _has_dialog(descendants):
        try:
            if verbose:
                print(f"{tag} Stage 2: Dialog detected, sending ESC")
            window.type_keys("{ESC}", pause=0.05)
            time.sleep(0.3)
            result["stages_used"].append("DIALOG_DISMISS")
            descendants = _safe_descendants(window)
            if _is_truly_home(descendants):
                result["recovered"] = True
                result["home_landmarks_found"] = True
                if verbose:
                    print(f"{tag} Home state confirmed after dialog dismiss")
                return result
        except Exception as e:
            if verbose:
                print(f"{tag} Stage 2 error: {e}")

    # ------------------------------------------------------------------
    # Stage 3: Back-button navigation (unlimited depth)
    # ------------------------------------------------------------------
    back_clicks = 0
    if verbose:
        print(f"{tag} Stage 3: Back-button navigation scan")

    prev_count = len(_safe_descendants(window))
    stale_rounds = 0          # consecutive clicks with no tree change

    while back_clicks < max_back_attempts:
        descendants = _safe_descendants(window)
        back_btn = _find_back_button(descendants)

        if back_btn is None:
            if verbose:
                print(f"{tag} No more Back buttons found after {back_clicks} clicks")
            break

        try:
            if verbose:
                name = _elem_prop(back_btn, "name")
                print(f"{tag} Clicking Back button: '{name}' (click #{back_clicks + 1})")
            back_btn.click_input()
            back_clicks += 1
            time.sleep(0.5)

            # Re-scan after click
            descendants = _safe_descendants(window)
            cur_count = len(descendants)

            # Detect stale clicks (no meaningful tree change)
            if abs(cur_count - prev_count) < 3:
                stale_rounds += 1
                if stale_rounds >= 3:
                    if verbose:
                        print(f"{tag} Back clicks not changing tree "
                              f"({cur_count} elements) — aborting Stage 3")
                    break
            else:
                stale_rounds = 0
            prev_count = cur_count

            if _is_truly_home(descendants):
                if verbose:
                    print(f"{tag} Home state restored after {back_clicks} Back click(s) "
                          f"({cur_count} elements)")
                result["recovered"] = True
                result["home_landmarks_found"] = True
                result["back_clicks"] = back_clicks
                result["stages_used"].append(f"BACK_NAV×{back_clicks}")
                return result
        except Exception as e:
            if verbose:
                print(f"{tag} Back button click failed: {e}")
            break

    result["back_clicks"] = back_clicks
    if back_clicks > 0:
        result["stages_used"].append(f"BACK_NAV×{back_clicks}")

    # ------------------------------------------------------------------
    # Stage 4: Validate home state
    # ------------------------------------------------------------------
    descendants = _safe_descendants(window)
    result["home_landmarks_found"] = _has_home_landmarks(descendants)
    result["recovered"] = _is_truly_home(descendants)

    if verbose:
        if result["recovered"]:
            print(f"{tag} Stage 4: Home state CONFIRMED ({len(descendants)} elements)")
        else:
            has_back = _has_back_button(descendants)
            reason = "Back button still visible" if has_back else "no home landmarks"
            print(f"{tag} Stage 4: Home state NOT confirmed "
                  f"({len(descendants)} elements, {reason}). Proceeding anyway.")

    # Log to trace logger if available
    if trace_logger:
        try:
            trace_logger.log_trace({
                "event_type": "HOME_STATE_RECOVERY",
                "component": "ui_state_manager",
                "action": "ensure_home_state",
                "input": app_name,
                "output": str(result),
                "success": result["recovered"],
            })
        except:
            pass

    return result
