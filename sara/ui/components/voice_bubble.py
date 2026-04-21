"""Animated voice state bubble used to show listening and speaking status."""

from __future__ import annotations


try:
    from PyQt5.QtCore import QEasingCurve, QPointF, QPropertyAnimation, QVariantAnimation, Qt, pyqtSignal
    from PyQt5.QtGui import QColor, QPainter
    from PyQt5.QtWidgets import QGraphicsOpacityEffect, QWidget
except Exception as exc:
    raise ImportError("PyQt5 is required for voice bubble component") from exc

from sara.ui.theme.tokens import DEFAULT_THEME


class VoiceBubble(QWidget):
    """Circular animated indicator for voice pipeline state."""

    state_changed = pyqtSignal(str)

    _STATE_COLORS = {
        "idle": DEFAULT_THEME.colors.voice_idle,
        "listening": DEFAULT_THEME.colors.voice_listening,
        "processing": DEFAULT_THEME.colors.voice_processing,
        "speaking": DEFAULT_THEME.colors.voice_speaking,
        "error": DEFAULT_THEME.colors.voice_error,
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state = "idle"
        self._scale = 1.0
        self.setFixedSize(42, 42)
        self.setToolTip("Voice state")
        self.setAccessibleName("Voice state bubble")

        self._opacity_effect = QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity_effect)

        self._opacity_animation = QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._opacity_animation.setDuration(DEFAULT_THEME.motion.normal_ms)
        self._opacity_animation.setStartValue(0.6)
        self._opacity_animation.setEndValue(1.0)
        self._opacity_animation.setEasingCurve(QEasingCurve.InOutSine)

        self._scale_animation = QVariantAnimation(self)
        self._scale_animation.setDuration(DEFAULT_THEME.motion.normal_ms)
        self._scale_animation.setStartValue(1.0)
        self._scale_animation.setEndValue(1.0)
        self._scale_animation.setEasingCurve(QEasingCurve.OutCubic)
        self._scale_animation.valueChanged.connect(self._on_scale_value)

    def state(self) -> str:
        return self._state

    def set_state(self, state: str) -> None:
        normalized = str(state or "idle").strip().lower()
        if normalized not in self._STATE_COLORS:
            normalized = "idle"
        if normalized == self._state:
            return
        self._state = normalized
        self._run_transition()
        self.state_changed.emit(self._state)
        self.update()

    def _run_transition(self) -> None:
        self._opacity_animation.stop()
        self._opacity_animation.start()

        self._scale_animation.stop()
        self._scale_animation.setStartValue(0.92)
        self._scale_animation.setEndValue(1.0)
        self._scale_animation.start()

    def _on_scale_value(self, value) -> None:
        try:
            self._scale = float(value)
        except (TypeError, ValueError):
            self._scale = 1.0
        self.update()

    def paintEvent(self, event) -> None:
        del event
        color = QColor(self._STATE_COLORS.get(self._state, self._STATE_COLORS["idle"]))

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setPen(Qt.NoPen)

        width = float(self.width())
        height = float(self.height())
        diameter = min(width, height) * 0.76 * self._scale
        radius = diameter / 2.0
        center = QPointF(width / 2.0, height / 2.0)

        painter.setBrush(color)
        painter.drawEllipse(center, radius, radius)
