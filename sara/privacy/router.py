"""Privacy router for SARA command handling."""

from __future__ import annotations

from enum import Enum
from typing import Tuple

from sara.config import SENSITIVE_KEYWORDS


class PrivacySensitivity(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


_MEDIUM_KEYWORDS = {
    "file",
    "folder",
    "document",
    "save",
    "open",
    "delete",
    "rename",
    "path",
    "directory",
    "download",
    "upload",
}

_PERSONAL_PATTERNS = {
    "my name is",
    "i am ",
    "i'm ",
    "i live",
    "i work",
    "remember",
    "note that",
    "my phone",
    "my email",
    "my address",
}


class PrivacyRouter:
    """Classify command sensitivity and route to local/cloud processing."""

    def classify(self, command: str) -> PrivacySensitivity:
        text = (command or "").lower()
        if any(token in text for token in SENSITIVE_KEYWORDS):
            return PrivacySensitivity.HIGH
        if any(pattern in text for pattern in _PERSONAL_PATTERNS):
            return PrivacySensitivity.MEDIUM
        if any(token in text for token in _MEDIUM_KEYWORDS):
            return PrivacySensitivity.MEDIUM
        return PrivacySensitivity.LOW

    def route(self, command: str) -> Tuple[str, PrivacySensitivity]:
        sensitivity = self.classify(command)
        # Cloud-first deployment: all commands use cloud LLM providers, while
        # sensitivity controls sanitization strictness/observability.
        engine = "CLOUD"
        return engine, sensitivity

    def get_routing_explanation(self, command: str) -> str:
        engine, sensitivity = self.route(command)
        if sensitivity == PrivacySensitivity.LOW:
            return "Cloud route selected: low sensitivity command."
        return (
            f"Cloud route selected with privacy sanitization: "
            f"sensitivity={sensitivity.value}."
        )
