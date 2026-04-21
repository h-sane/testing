"""Token-driven stylesheet generation for SARA Qt widgets."""

from __future__ import annotations

from .tokens import DEFAULT_THEME, ThemeTokens


def build_main_stylesheet(theme: ThemeTokens = DEFAULT_THEME) -> str:
    c = theme.colors
    s = theme.spacing
    r = theme.radius
    t = theme.typography

    return f"""
QMainWindow, QWidget {{
    background: {c.app_background};
    color: {c.text_primary};
    font-family: {t.family};
    font-size: {t.body}px;
}}

QWidget[component="leftNav"], QWidget[component="contextPanel"], QWidget[component="topBar"] {{
    background: {c.panel_background};
}}

QFrame[component="infoCard"],
QFrame[component="messageCard"],
QWidget[component="composerRow"],
QWidget[component="assistantToolbar"] {{
    background: {c.surface_background};
    border: 1px solid {c.border};
    border-radius: {r.md}px;
}}

QFrame[component="messageCard"][messageRole="user"] {{
    background: {c.user_message_bg};
}}

QFrame[component="messageCard"][messageRole="assistant"] {{
    background: {c.assistant_message_bg};
}}

QFrame[component="messageCard"][messageRole="code"] {{
    background: {c.code_bg};
}}

QLineEdit, QTextEdit, QPlainTextEdit, QComboBox {{
    background: {c.surface_background};
    color: {c.text_primary};
    border: 1px solid {c.border};
    border-radius: {r.sm}px;
    padding: {s.md}px {s.lg}px;
    font-size: {t.body}px;
    selection-background-color: {c.accent};
}}

QPushButton {{
    background: {c.accent};
    color: {c.text_primary};
    border: none;
    border-radius: {r.sm}px;
    padding: {s.sm}px {s.xl}px;
    min-height: 36px;
    font-size: {t.body}px;
    font-weight: 600;
}}

QPushButton:hover {{
    background: {c.accent_hover};
}}

QPushButton:pressed {{
    background: {c.accent_soft};
}}

QPushButton[variant="ghost"] {{
    background: transparent;
    color: {c.text_muted};
    border: 1px solid {c.border};
}}

QPushButton[variant="ghost"]:hover {{
    color: {c.text_primary};
    border-color: {c.accent};
}}

QPushButton[component="navButton"] {{
    text-align: left;
    padding-left: {s.md}px;
    min-height: 38px;
}}

QPushButton[component="navButton"][active="true"] {{
    background: {c.accent_soft};
    color: {c.text_primary};
    border: 1px solid {c.accent};
}}

QLabel[component="title"] {{
    font-size: {t.title}px;
    font-weight: 600;
}}

QLabel[component="sectionTitle"] {{
    font-size: {t.section}px;
    font-weight: 600;
}}

QLabel[component="caption"] {{
    font-size: {t.caption}px;
    color: {c.text_muted};
}}

QLabel[component="statusChip"] {{
    border-radius: {r.lg}px;
    padding: {s.xs}px {s.md}px;
    font-size: {t.caption}px;
    font-weight: 600;
    border: 1px solid {c.border};
}}

QLabel[component="statusChip"][chipStatus="idle"] {{
    color: {c.text_primary};
    background: {c.surface_background};
}}

QLabel[component="statusChip"][chipStatus="running"] {{
    color: {c.text_primary};
    background: {c.accent_soft};
    border-color: {c.accent};
}}

QLabel[component="statusChip"][chipStatus="error"] {{
    color: {c.text_primary};
    background: {c.error};
    border-color: {c.error};
}}

QScrollArea {{
    border: none;
    background: transparent;
}}

QScrollBar:vertical {{
    background: {c.panel_background};
    width: {s.md}px;
    margin: {s.xs}px;
    border-radius: {r.sm}px;
}}

QScrollBar::handle:vertical {{
    background: {c.border};
    min-height: {s.xl}px;
    border-radius: {r.sm}px;
}}

QScrollBar::handle:vertical:hover {{
    background: {c.accent};
}}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {{
    background: none;
    border: none;
}}

QWidget:focus,
QPushButton:focus,
QLineEdit:focus,
QTextEdit:focus,
QComboBox:focus {{
    border: 1px solid {c.focus_ring};
    outline: none;
}}
"""
