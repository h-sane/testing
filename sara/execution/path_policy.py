"""Path coverage capability profile and vision fallback policy."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Tuple

from src.automation import matcher

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROFILE_PATH = PROJECT_ROOT / ".cache" / "app_capabilities.json"

# Conservative thresholds to avoid over-triggering vision.
MIN_PATH_COVERAGE = 0.50
MIN_TASK_MATCH_COVERAGE = 0.60


def load_profiles() -> Dict[str, Any]:
    if not PROFILE_PATH.exists():
        return {"apps": {}}

    try:
        data = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("apps", {}), dict):
            return data
    except Exception:
        pass

    return {"apps": {}}


def save_profiles(profiles: Dict[str, Any]) -> bool:
    try:
        PROFILE_PATH.parent.mkdir(parents=True, exist_ok=True)
        PROFILE_PATH.write_text(json.dumps(profiles, indent=2, ensure_ascii=False), encoding="utf-8")
        return True
    except Exception:
        return False


def update_profile(app_name: str, profile: Dict[str, Any]) -> bool:
    profiles = load_profiles()
    apps = profiles.setdefault("apps", {})

    app_profile = dict(profile)
    app_profile["updated_at"] = datetime.utcnow().isoformat() + "Z"
    apps[app_name] = app_profile

    return save_profiles(profiles)


def get_profile(app_name: str) -> Dict[str, Any]:
    profiles = load_profiles()
    return dict(profiles.get("apps", {}).get(app_name, {}))


def should_enable_vision(
    app_name: str,
    target: str,
    default_use_vision: bool = False,
) -> Tuple[bool, str]:
    """
    Determine if this step should use vision fallback.

    Policy:
    1) If explicitly enabled, keep it enabled.
    2) If target is already cache-matchable, keep planner/AX-first path.
    3) If profile coverage is weak, allow vision for this step.
    """
    if default_use_vision:
        return True, "vision-enabled-by-config"

    if target:
        cached = matcher.find_cached_element(app_name, target, min_confidence=0.65)
        if cached:
            return False, "target-has-cache-path"

    profile = get_profile(app_name)
    if not profile:
        return False, "no-profile-default-no-vision"

    path_cov = float(profile.get("path_coverage_ratio", 0.0))
    task_cov = float(profile.get("task_match_ratio", 0.0))

    if path_cov < MIN_PATH_COVERAGE or task_cov < MIN_TASK_MATCH_COVERAGE:
        return True, f"low-coverage(path={path_cov:.2f},task={task_cov:.2f})"

    return False, f"coverage-ok(path={path_cov:.2f},task={task_cov:.2f})"
