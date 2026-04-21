"""Shared Qt styles for SARA UI."""

from sara.ui.theme import build_main_stylesheet

# Backward-compatible alias for existing call-sites.
DARK = build_main_stylesheet()

