"""Design tokens for SARA UI surfaces."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ColorTokens:
    app_background: str
    panel_background: str
    surface_background: str
    border: str
    text_primary: str
    text_muted: str
    accent: str
    accent_hover: str
    accent_soft: str
    success: str
    warning: str
    error: str
    user_message_bg: str
    assistant_message_bg: str
    code_bg: str
    focus_ring: str
    voice_idle: str
    voice_listening: str
    voice_processing: str
    voice_speaking: str
    voice_error: str


@dataclass(frozen=True)
class SpacingTokens:
    xs: int = 4
    sm: int = 8
    md: int = 12
    lg: int = 16
    xl: int = 24


@dataclass(frozen=True)
class RadiusTokens:
    sm: int = 8
    md: int = 12
    lg: int = 16


@dataclass(frozen=True)
class TypographyTokens:
    family: str
    title: int
    section: int
    body: int
    caption: int


@dataclass(frozen=True)
class MotionTokens:
    fast_ms: int
    normal_ms: int
    slow_ms: int


@dataclass(frozen=True)
class LayoutTokens:
    nav_collapsed_width: int
    nav_expanded_width: int
    context_panel_width: int
    message_max_width: int
    message_spacing: int


@dataclass(frozen=True)
class ThemeTokens:
    colors: ColorTokens
    spacing: SpacingTokens
    radius: RadiusTokens
    typography: TypographyTokens
    motion: MotionTokens
    layout: LayoutTokens


DEFAULT_THEME = ThemeTokens(
    colors=ColorTokens(
        app_background="#0E1116",
        panel_background="#151A22",
        surface_background="#1D2430",
        border="#2A3444",
        text_primary="#F4F7FC",
        text_muted="#A9B4C4",
        accent="#26A0F8",
        accent_hover="#4BB4FF",
        accent_soft="#14324A",
        success="#2BB673",
        warning="#F4B740",
        error="#EF5D68",
        user_message_bg="#1E3A5F",
        assistant_message_bg="#1B2533",
        code_bg="#101722",
        focus_ring="#7BC6FF",
        voice_idle="#6B7685",
        voice_listening="#26A0F8",
        voice_processing="#F4B740",
        voice_speaking="#2BB673",
        voice_error="#EF5D68",
    ),
    spacing=SpacingTokens(),
    radius=RadiusTokens(),
    typography=TypographyTokens(
        family="Segoe UI, Segoe UI Variable Text",
        title=34,
        section=24,
        body=16,
        caption=14,
    ),
    motion=MotionTokens(
        fast_ms=140,
        normal_ms=180,
        slow_ms=240,
    ),
    layout=LayoutTokens(
        nav_collapsed_width=68,
        nav_expanded_width=152,
        context_panel_width=220,
        message_max_width=560,
        message_spacing=18,
    ),
)
