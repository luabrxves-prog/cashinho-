"""Tema visual compartilhado da interface Streamlit."""

from __future__ import annotations

import streamlit as st

_LIGHT_THEME = {
    "background": "#FFFFFF",
    "secondary": "#F0F2F6",
    "text": "#31333F",
    "primary": "#5B8DEF",
}

_DARK_THEME = {
    "background": "#0E1117",
    "secondary": "#262730",
    "text": "#FAFAFA",
    "primary": "#5B8DEF",
}

CHART_COLORS = {
    "up": "#22C55E",
    "down": "#EF4444",
    "vwap": "#A78BFA",
    "band": "#94A3B8",
    "grid": "rgba(148, 163, 184, 0.28)",
    "axis": "rgba(148, 163, 184, 0.45)",
    "hover_bg": "#111827",
    "hover_text": "#F9FAFB",
    "overlay": ("#60A5FA", "#F59E0B", "#22D3EE", "#F472B6", "#A3E635"),
}

_APP_THEME_CSS = """
<style>
:root {
    --cashinho-surface: var(--secondary-background-color, #f6f8fb);
    --cashinho-surface-soft: rgba(127, 127, 127, 0.06);
    --cashinho-border: rgba(127, 127, 127, 0.22);
    --cashinho-border-strong: rgba(127, 127, 127, 0.34);
    --cashinho-muted: rgba(127, 127, 127, 0.78);
    --cashinho-focus: rgba(91, 141, 239, 0.38);
    --cashinho-disabled: rgba(127, 127, 127, 0.42);
}

@supports (color: color-mix(in srgb, white, black)) {
    :root {
        --cashinho-surface-soft: color-mix(
            in srgb,
            var(--secondary-background-color, #f6f8fb) 72%,
            var(--background-color, #ffffff)
        );
        --cashinho-border: color-mix(
            in srgb,
            var(--text-color, #31333f) 16%,
            transparent
        );
        --cashinho-border-strong: color-mix(
            in srgb,
            var(--text-color, #31333f) 26%,
            transparent
        );
        --cashinho-muted: color-mix(
            in srgb,
            var(--text-color, #31333f) 68%,
            transparent
        );
        --cashinho-focus: color-mix(
            in srgb,
            var(--primary-color, #5b8def) 42%,
            transparent
        );
        --cashinho-disabled: color-mix(
            in srgb,
            var(--text-color, #31333f) 38%,
            transparent
        );
    }
}

html,
body,
.stApp,
[data-testid="stAppViewContainer"] {
    background: var(--background-color, #ffffff);
    color: var(--text-color, #31333f);
}

[data-testid="stHeader"] {
    background: transparent;
}

[data-testid="stSidebar"],
[data-testid="stSidebarContent"] {
    background: var(--secondary-background-color, #f6f8fb);
    color: var(--text-color, #31333f);
}

[data-testid="stCaptionContainer"],
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
[data-testid="stSidebar"] code {
    color: var(--cashinho-muted);
}

[data-testid="stSidebar"] a {
    color: var(--text-color, #31333f);
}

[data-testid="stSidebar"] a:hover,
[data-testid="stSidebar"] button:hover {
    background: var(--cashinho-surface-soft);
    color: var(--text-color, #31333f);
}

[data-testid="stSidebar"] a[aria-current="page"],
[data-testid="stSidebar"] [aria-selected="true"] {
    background: var(--cashinho-surface-soft);
    color: var(--text-color, #31333f);
}

[data-testid="stSidebar"] code,
[data-testid="stMarkdownContainer"] code {
    background: var(--cashinho-surface-soft);
    border: 1px solid var(--cashinho-border);
    border-radius: 4px;
}

.cashinho-mode-badge {
    --cashinho-mode-color: var(--primary-color, #5b8def);
    background: var(--cashinho-surface-soft);
    border: 1px solid var(--cashinho-border);
    border-left: 6px solid var(--cashinho-mode-color);
    border-radius: 6px;
    color: var(--text-color, #31333f);
    margin-bottom: 12px;
    padding: 10px 12px;
}

@supports (color: color-mix(in srgb, white, black)) {
    .cashinho-mode-badge {
        background: color-mix(
            in srgb,
            var(--cashinho-mode-color) 9%,
            var(--secondary-background-color, #f6f8fb)
        );
        border-color: color-mix(
            in srgb,
            var(--cashinho-mode-color) 45%,
            var(--cashinho-border)
        );
    }
}

.cashinho-mode-badge__label,
.cashinho-mode-badge__note {
    color: var(--cashinho-muted);
    font-size: 0.72rem;
}

.cashinho-mode-badge__label {
    font-size: 0.70rem;
    letter-spacing: 0.14em;
    text-transform: uppercase;
}

.cashinho-mode-badge__value {
    color: var(--cashinho-mode-color);
    font-size: 1.30rem;
    font-weight: 700;
    line-height: 1.25;
}

[data-testid="stMetric"],
[data-testid="stVerticalBlockBorderWrapper"] {
    background: var(--cashinho-surface-soft);
    border-color: var(--cashinho-border);
}

[data-testid="stMetric"] {
    border: 1px solid var(--cashinho-border);
    border-radius: 6px;
    min-height: 100%;
    padding: 0.65rem 0.75rem;
}

[data-testid="stMetricLabel"],
[data-testid="stMetricDelta"],
[data-testid="stTable"] thead,
[data-testid="stDataFrame"] [role="columnheader"] {
    color: var(--cashinho-muted);
}

[data-testid="stMetricValue"] {
    color: var(--text-color, #31333f);
}

[data-testid="stExpander"] details {
    background: var(--cashinho-surface-soft);
    border-color: var(--cashinho-border);
    border-radius: 6px;
}

[data-testid="stExpander"] summary:hover,
[data-testid="stTabs"] button[role="tab"]:hover,
div[data-baseweb="select"] > div:hover,
div[data-baseweb="input"]:hover,
div[data-baseweb="textarea"]:hover,
div[data-baseweb="base-input"]:hover {
    border-color: var(--cashinho-border-strong);
}

div[data-baseweb="select"] > div,
div[data-baseweb="input"],
div[data-baseweb="textarea"],
div[data-baseweb="base-input"],
div[data-baseweb="popover"],
div[data-baseweb="calendar"],
ul[role="listbox"],
textarea,
input {
    background: var(--background-color, #ffffff);
    border-color: var(--cashinho-border);
    color: var(--text-color, #31333f);
}

div[data-baseweb="popover"],
div[data-baseweb="calendar"],
ul[role="listbox"] {
    border: 1px solid var(--cashinho-border);
    box-shadow: 0 12px 28px rgba(0, 0, 0, 0.18);
}

li[role="option"],
div[role="option"] {
    color: var(--text-color, #31333f);
}

li[role="option"]:hover,
div[role="option"]:hover,
li[aria-selected="true"],
div[aria-selected="true"] {
    background: var(--cashinho-surface-soft);
    color: var(--text-color, #31333f);
}

div[data-baseweb="select"] svg,
div[data-baseweb="checkbox"] svg,
div[data-baseweb="radio"] svg {
    color: var(--text-color, #31333f);
    fill: currentColor;
}

div[data-baseweb="select"] [aria-disabled="true"],
div[data-baseweb="input"][aria-disabled="true"],
textarea:disabled,
input:disabled,
button:disabled,
[disabled] {
    color: var(--cashinho-disabled) !important;
    opacity: 1;
}

div[data-baseweb="select"] [aria-disabled="true"],
div[data-baseweb="input"][aria-disabled="true"],
textarea:disabled,
input:disabled,
button:disabled {
    background: var(--cashinho-surface-soft) !important;
    border-color: var(--cashinho-border) !important;
}

div[data-baseweb="select"]:focus-within,
div[data-baseweb="input"]:focus-within,
div[data-baseweb="textarea"]:focus-within,
div[data-baseweb="base-input"]:focus-within,
button:focus-visible,
[data-testid="stTabs"] button[role="tab"]:focus-visible {
    box-shadow: 0 0 0 0.18rem var(--cashinho-focus);
    outline: none;
}

.stButton > button,
.stDownloadButton > button,
[data-testid="stBaseButton-secondary"],
[data-testid="stBaseButton-tertiary"] {
    border-color: var(--cashinho-border);
}

.stButton > button:not(:disabled):hover,
.stDownloadButton > button:not(:disabled):hover,
[data-testid="stBaseButton-secondary"]:not(:disabled):hover,
[data-testid="stBaseButton-tertiary"]:not(:disabled):hover {
    border-color: var(--primary-color, #5b8def);
}

[data-testid="stTable"],
[data-testid="stDataFrame"] {
    color: var(--text-color, #31333f);
}

[data-testid="stDataFrame"] {
    border: 1px solid var(--cashinho-border);
    border-radius: 6px;
    overflow: hidden;
}

[data-testid="stTabs"] button[role="tab"] {
    color: var(--cashinho-muted);
}

[data-testid="stTabs"] button[aria-selected="true"] {
    color: var(--text-color, #31333f);
}

[data-testid="stPlotlyChart"] {
    background: transparent;
}

[data-testid="stPlotlyChart"] .modebar {
    background: var(--cashinho-surface-soft) !important;
    border: 1px solid var(--cashinho-border);
    border-radius: 6px;
}

[data-testid="stPlotlyChart"] .modebar-btn path {
    fill: var(--cashinho-muted) !important;
}

[data-testid="stPlotlyChart"] .modebar-btn:hover path,
[data-testid="stPlotlyChart"] .modebar-btn.active path {
    fill: var(--text-color, #31333f) !important;
}

[data-testid="stPlotlyChart"] .main-svg,
[data-testid="stPlotlyChart"] .bg,
[data-testid="stPlotlyChart"] .plot-container {
    background: transparent !important;
}

[data-testid="stPlotlyChart"] .xtick text,
[data-testid="stPlotlyChart"] .ytick text,
[data-testid="stPlotlyChart"] .legend text,
[data-testid="stPlotlyChart"] .gtitle,
[data-testid="stPlotlyChart"] .xtitle,
[data-testid="stPlotlyChart"] .ytitle {
    fill: var(--text-color, #31333f) !important;
}

[data-testid="stPlotlyChart"] .gridlayer path {
    stroke: var(--cashinho-border) !important;
}

[data-testid="stPlotlyChart"] .zerolinelayer path {
    stroke: var(--cashinho-border-strong) !important;
}

[data-testid="stAlert"] {
    border-radius: 6px;
}
</style>
"""


def _context_theme_value(name: str) -> str | None:
    try:
        theme = st.context.theme
    except RuntimeError:
        return None
    if theme is None:
        return None
    value = theme.get(name) if isinstance(theme, dict) else getattr(theme, name, None)
    return str(value) if value is not None else None


def _theme_option(option: str, context_name: str) -> str | None:
    return _context_theme_value(context_name) or st.get_option(option)


def _theme_tokens() -> dict[str, str]:
    base = (
        _context_theme_value("base")
        or _context_theme_value("type")
        or st.get_option("theme.base")
        or "light"
    )
    defaults = _DARK_THEME if str(base).lower() == "dark" else _LIGHT_THEME

    return {
        "scheme": "dark" if defaults is _DARK_THEME else "light",
        "background": _theme_option("theme.backgroundColor", "backgroundColor")
        or defaults["background"],
        "secondary": _theme_option(
            "theme.secondaryBackgroundColor",
            "secondaryBackgroundColor",
        )
        or defaults["secondary"],
        "text": _theme_option("theme.textColor", "textColor") or defaults["text"],
        "primary": _theme_option("theme.primaryColor", "primaryColor")
        or defaults["primary"],
    }


def _theme_variables() -> str:
    tokens = _theme_tokens()
    return f"""
    <style>
    :root {{
        --background-color: {tokens["background"]};
        --secondary-background-color: {tokens["secondary"]};
        --text-color: {tokens["text"]};
        --primary-color: {tokens["primary"]};
        color-scheme: {tokens["scheme"]};
    }}
    </style>
    """


def apply_app_theme() -> None:
    """Injeta ajustes que fazem os componentes seguir claro/escuro."""
    st.markdown(f"{_theme_variables()}{_APP_THEME_CSS}", unsafe_allow_html=True)
