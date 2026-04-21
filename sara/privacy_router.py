"""Backward-compatible shim for legacy sara.privacy_router imports."""

from sara.privacy.router import PrivacyRouter, PrivacySensitivity

__all__ = ["PrivacyRouter", "PrivacySensitivity"]
