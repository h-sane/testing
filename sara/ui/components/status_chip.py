"""Compact status indicator chip used in top bars and cards."""

from __future__ import annotations


try:
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QLabel
except Exception as exc:
    raise ImportError("PyQt5 is required for status chip component") from exc


class StatusChip(QLabel):
    """Small pill-style status label with theme-driven colors."""

    _VALID = {"idle", "running", "error"}

    def __init__(self, status: str = "idle", parent=None):
        super().__init__(parent)
        self.setProperty("component", "statusChip")
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(24)
        self.setAccessibleName("Runtime status")
        self.set_status(status)

    def set_status(self, status: str) -> None:
        normalized = str(status or "idle").strip().lower()
        if normalized not in self._VALID:
            normalized = "idle"
        self.setProperty("chipStatus", normalized)
        self.setText(normalized.upper())
        style = self.style()
        if style is not None:
            style.unpolish(self)
            style.polish(self)
        self.update()
