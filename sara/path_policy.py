"""Backward-compatible shim for legacy sara.path_policy imports."""

from sara.execution.path_policy import (
    MIN_PATH_COVERAGE,
    MIN_TASK_MATCH_COVERAGE,
    PROFILE_PATH,
    get_profile,
    load_profiles,
    save_profiles,
    should_enable_vision,
    update_profile,
)

__all__ = [
    "PROFILE_PATH",
    "MIN_PATH_COVERAGE",
    "MIN_TASK_MATCH_COVERAGE",
    "load_profiles",
    "save_profiles",
    "update_profile",
    "get_profile",
    "should_enable_vision",
]
