"""Scrollable chat container composed of animated message cards."""

from __future__ import annotations


try:
    from PyQt5.QtCore import Qt, QTimer, QPropertyAnimation
    from PyQt5.QtWidgets import (
        QHBoxLayout,
        QScrollArea,
        QSizePolicy,
        QSpacerItem,
        QVBoxLayout,
        QWidget,
    )
except Exception as exc:
    raise ImportError("PyQt5 is required for chat container component") from exc

from sara.ui.components.message_card import MessageCard
from sara.ui.theme.tokens import DEFAULT_THEME


class ChatContainer(QWidget):
    """Handles message layout, entry animation, and smooth autoscroll."""

    def __init__(self, parent=None):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)

        self.content = QWidget()
        self.messages_layout = QVBoxLayout(self.content)
        self.messages_layout.setContentsMargins(
            DEFAULT_THEME.spacing.xl,
            DEFAULT_THEME.spacing.xl,
            DEFAULT_THEME.spacing.xl,
            DEFAULT_THEME.spacing.xl,
        )
        self.messages_layout.setSpacing(DEFAULT_THEME.layout.message_spacing)

        self._end_spacer = QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Expanding)
        self.messages_layout.addSpacerItem(self._end_spacer)
        self.scroll.setWidget(self.content)
        root.addWidget(self.scroll)

        self._scroll_animation = QPropertyAnimation(self.scroll.verticalScrollBar(), b"value", self)
        self._scroll_animation.setDuration(DEFAULT_THEME.motion.normal_ms)

    def clear_messages(self) -> None:
        while self.messages_layout.count() > 1:
            item = self.messages_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def user_message(self, text: str) -> None:
        self.add_message(text=text, role="user")

    def assistant_message(self, text: str) -> None:
        self.add_message(text=text, role="assistant")

    def code_block(self, code: str) -> None:
        self.add_message(text=code, role="code", is_code=True)

    def add_message(self, text: str, role: str = "assistant", is_code: bool = False) -> None:
        card = MessageCard(text=text, role=role, is_code=is_code)

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(0)

        is_user = str(role or "").strip().lower() == "user" and not is_code
        if is_user:
            row_layout.addStretch(1)
            row_layout.addWidget(card, 0, Qt.AlignRight)
        else:
            row_layout.addWidget(card, 0, Qt.AlignLeft)
            row_layout.addStretch(1)

        insert_index = max(0, self.messages_layout.count() - 1)
        self.messages_layout.insertWidget(insert_index, row)
        card.animate_in()
        QTimer.singleShot(0, self._smooth_scroll_to_bottom)

    def _smooth_scroll_to_bottom(self) -> None:
        bar = self.scroll.verticalScrollBar()
        start_value = int(bar.value())
        end_value = int(bar.maximum())
        if end_value <= start_value:
            return
        self._scroll_animation.stop()
        self._scroll_animation.setStartValue(start_value)
        self._scroll_animation.setEndValue(end_value)
        self._scroll_animation.start()
