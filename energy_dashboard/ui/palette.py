"""
Energy Dashboard — `ui/palette.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.deps import *

_DARK_BG   = '#1e1e2e'
_DARK_FACE = '#2a2a3c'
_DARK_GRID = '#3a3a4c'
_DARK_TEXT = '#cdd6f4'
_DARK_MANTLE = '#181825'
_DARK_SURFACE0 = '#313244'
_DARK_SUBTEXT = '#a6adc8'
_DARK_OVERLAY = '#6c7086'

# Main tab bar: fresh data tint fades to _DARK_BG over this many seconds.
_TAB_FRESH_MAX_AGE_SEC = 600
_TAB_FRESH_TINT = '#c8f0c0'
_TAB_TEXT_ON_LIGHT_BG = '#000000'
_TAB_TEXT_ON_DARK_BG = _DARK_TEXT
_TAB_CORNER_RADIUS = 8
# Faint tab chrome (ARGB) — visible on green freshness tints and dark tabs alike.
_TAB_OUTLINE_FAINT = QColor(69, 71, 90, 72)
_TAB_OUTLINE_SELECTED = QColor(108, 112, 134, 130)

# Main tab bar only — no ::tab background (FreshnessTabBar paints per-tab tint).
_FRESH_MAIN_TAB_BAR_QSS = f"""
QTabBar#freshMainTabBar {{
    background: {_DARK_BG};
}}
QTabBar#freshMainTabBar::tab {{
    color: {_DARK_OVERLAY};
    padding: 6px 14px;
    border: 1px solid transparent;
    border-bottom: none;
    border-top-left-radius: {_TAB_CORNER_RADIUS}px;
    border-top-right-radius: {_TAB_CORNER_RADIUS}px;
    margin-right: 3px;
}}
QTabBar#freshMainTabBar::tab:selected {{
    font-weight: bold;
    border: 1px solid {_DARK_GRID};
    border-bottom: 1px solid {_DARK_BG};
}}
QTabBar#freshMainTabBar::tab:hover:!selected {{
    color: {_DARK_SUBTEXT};
}}
"""


def _hex_to_rgb(hex_color):
    h = hex_color.lstrip('#')
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(rgb):
    return '#{:02x}{:02x}{:02x}'.format(*rgb)


def _lerp_hex(c0, c1, t):
    """Linear blend; t=0 → c0, t=1 → c1."""
    t = max(0.0, min(1.0, float(t)))
    a, b = _hex_to_rgb(c0), _hex_to_rgb(c1)
    return _rgb_to_hex(tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b)))


# Panels/dialogues: gentle lift. Text fields: barely lighter than app background.
_DARK_PANEL_LIFT = 0.10
_DARK_INPUT_LIFT = 0.06
_DARK_SURFACE_BG = _lerp_hex(_DARK_BG, '#ffffff', _DARK_PANEL_LIFT)
_DARK_INPUT_BG = _lerp_hex(_DARK_BG, '#ffffff', _DARK_INPUT_LIFT)
_DARK_INPUT_BORDER = _lerp_hex(_DARK_BG, '#ffffff', 0.14)
_SPIN_STEP_BTN_HOVER = _lerp_hex(_DARK_INPUT_BG, '#ffffff', 0.05)
_SPIN_STEP_BTN_PRESSED = _lerp_hex(_DARK_INPUT_BG, '#000000', 0.10)
# Combo / spin arrow strip: same fill as the field (no vertical divider).
_COMBO_DROP_W = 20
_INPUT_STEP_W = 18
_INPUT_FIELD_RADIUS = 4
_INPUT_FIELD_PADDING_LEFT = '5px'
_INPUT_FIELD_PADDING = f'3px 2px 3px {_INPUT_FIELD_PADDING_LEFT}'
_INPUT_FIELD_MIN_H = 22
# Spin-field design motif: electric-blue border; fill 15% lighter grey than panel surface.
_ELECTRIC_BLUE = '#00a8ff'
_SPIN_FIELD_LIFT = 0.15
_SPIN_FIELD_BG = _lerp_hex(_DARK_SURFACE_BG, '#ffffff', _SPIN_FIELD_LIFT)
_SPIN_FIELD_MOTIF_W = 98
_SPIN_FIELD_MOTIF_H = 20
_SPIN_FIELD_MOTIF_DB_W = _SPIN_FIELD_MOTIF_W + 30  # port / wide numeric fields
_FLAT_TARIFF_INPUT_BG = _SPIN_FIELD_BG
_FLAT_TARIFF_INPUT_BORDER = _ELECTRIC_BLUE
_FLAT_TARIFF_STEP_HOVER = _lerp_hex(_SPIN_FIELD_BG, '#ffffff', 0.08)
_FLAT_TARIFF_STEP_PRESSED = _lerp_hex(_SPIN_FIELD_BG, '#000000', 0.08)
_FLAT_TARIFF_FOCUS_BORDER = _ELECTRIC_BLUE
# normal 400 + 30% of the way toward bold (700)
_FLAT_TARIFF_FONT_WEIGHT = 490
# Aliases — Setup & Info grid uses the global spin-field motif footprint.
_SETUP_INFO_SPIN_W = _SPIN_FIELD_MOTIF_W
_SETUP_INFO_SPIN_H = _SPIN_FIELD_MOTIF_H
__all__ = [n for n in globals() if not n.startswith('__')]
