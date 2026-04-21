"""Context panel information cards for active task, plan, and health summaries."""

from __future__ import annotations

from typing import Iterable


try:
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QFrame, QLabel, QVBoxLayout
except Exception as exc:
    raise ImportError("PyQt5 is required for info card component") from exc

from sara.ui.components.status_chip import StatusChip
from sara.ui.theme.tokens import DEFAULT_THEME


class InfoCard(QFrame):
    """Reusable card shell with title and body sections."""

    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setProperty("component", "infoCard")
        self.setFrameShape(QFrame.NoFrame)
        self.setAccessibleName(title)

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(
            DEFAULT_THEME.spacing.lg,
            DEFAULT_THEME.spacing.lg,
            DEFAULT_THEME.spacing.lg,
            DEFAULT_THEME.spacing.lg,
        )
        self._root.setSpacing(DEFAULT_THEME.spacing.sm)

        self.title_label = QLabel(title)
        self.title_label.setProperty("component", "sectionTitle")
        self._root.addWidget(self.title_label)

        self.body_label = QLabel("")
        self.body_label.setWordWrap(True)
        self.body_label.setProperty("component", "caption")
        self.body_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._root.addWidget(self.body_label)

    def set_body_text(self, text: str) -> None:
        self.body_label.setText(str(text or ""))


class ActiveTaskCard(InfoCard):
    """Displays currently active user request and runtime status."""

    def __init__(self, parent=None):
        super().__init__("Active Task", parent=parent)
        self.status_chip = StatusChip("idle")
        self._root.insertWidget(1, self.status_chip)
        self.task_label = QLabel("No active task")
        self.task_label.setWordWrap(True)
        self.task_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._root.addWidget(self.task_label)

    def set_task(self, task: str, status: str = "idle") -> None:
        text = str(task or "No active task").strip()
        self.task_label.setText(text if text else "No active task")
        self.status_chip.set_status(status)


class PlanCard(InfoCard):
    """Shows a compact summary of the current execution plan."""

    def __init__(self, parent=None):
        super().__init__("Plan", parent=parent)

    def set_plan_lines(self, lines: Iterable[str]) -> None:
        prepared = [str(item).strip() for item in lines if str(item or "").strip()]
        if not prepared:
            self.set_body_text("No planned steps yet.")
            return
        joined = "\n".join(f"- {item}" for item in prepared[:5])
        self.set_body_text(joined)


class HealthCard(InfoCard):
    """Presents system health snapshot and latest error state."""

    def __init__(self, parent=None):
        super().__init__("Health", parent=parent)

    def set_health(self, mode: str, wake_state: str, last_error: str = "") -> None:
        mode_text = str(mode or "unknown")
        wake_text = str(wake_state or "unknown")
        error_text = str(last_error or "").strip()
        lines = [f"Mode: {mode_text}", f"Wake: {wake_text}"]
        if error_text:
            lines.append(f"Last error: {error_text}")
        self.set_body_text("\n".join(lines))
