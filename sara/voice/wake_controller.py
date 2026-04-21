"""Wake-word coordination helpers for SARA."""

from __future__ import annotations

from typing import Callable


class WakeController:
    """Simple wake-word gate used by widget/chat entry points."""

    def __init__(self, wake_word: str = "hey sara"):
        self.wake_word = (wake_word or "hey sara").strip().lower()
        self.enabled = True

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)

    def handle_transcript(self, transcript: str, on_command: Callable[[str], None]) -> bool:
        """Return True if wake word matched and command callback triggered."""
        if not self.enabled:
            return False
        text = (transcript or "").strip()
        if not text:
            return False

        low = text.lower()
        if self.wake_word in low:
            cmd = text[low.find(self.wake_word) + len(self.wake_word) :].strip(" ,:;")
            if cmd:
                on_command(cmd)
            return True
        return False
