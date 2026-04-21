"""Message card primitive for chat conversations."""

from __future__ import annotations


try:
    from PyQt5.QtCore import Qt, QPropertyAnimation
    from PyQt5.QtWidgets import (
        QFrame,
        QGraphicsOpacityEffect,
        QLabel,
        QPlainTextEdit,
        QVBoxLayout,
    )
except Exception as exc:
    raise ImportError("PyQt5 is required for message card component") from exc

from sara.ui.theme.tokens import DEFAULT_THEME


class MessageCard(QFrame):
    """Chat bubble with optional code rendering and fade-in entry."""

    def __init__(self, text: str, role: str = "assistant", is_code: bool = False, parent=None):
        super().__init__(parent)
        safe_role = str(role or "assistant").strip().lower()
        if safe_role not in {"user", "assistant", "code"}:
            safe_role = "assistant"
        if is_code:
            safe_role = "code"

        self.setProperty("component", "messageCard")
        self.setProperty("messageRole", safe_role)
        self.setFrameShape(QFrame.NoFrame)
        self.setMaximumWidth(DEFAULT_THEME.layout.message_max_width)

        root = QVBoxLayout(self)
        root.setContentsMargins(
            DEFAULT_THEME.spacing.md,
            DEFAULT_THEME.spacing.sm,
            DEFAULT_THEME.spacing.md,
            DEFAULT_THEME.spacing.sm,
        )
        root.setSpacing(DEFAULT_THEME.spacing.xs)

        label = QLabel("You" if safe_role == "user" else "SARA")
        label.setProperty("component", "caption")
        root.addWidget(label)

        if safe_role == "code":
            body = QPlainTextEdit()
            body.setReadOnly(True)
            body.setPlainText(str(text or ""))
            body.setMinimumHeight(72)
            body.setMaximumHeight(220)
            body.setLineWrapMode(QPlainTextEdit.NoWrap)
            body.setTextInteractionFlags(Qt.TextSelectableByMouse)
            root.addWidget(body)
        else:
            body = QLabel(str(text or ""))
            body.setWordWrap(True)
            body.setTextInteractionFlags(Qt.TextSelectableByMouse)
            root.addWidget(body)

        self._opacity = QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity)
        self._fade = QPropertyAnimation(self._opacity, b"opacity", self)
        self._fade.setDuration(DEFAULT_THEME.motion.normal_ms)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)

    def animate_in(self) -> None:
        self._fade.stop()
        self._fade.start()
