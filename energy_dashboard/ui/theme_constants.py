"""
Energy Dashboard — `ui/theme_constants.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.deps import *
# Qt status / progress text on dark chrome (#89b4fa and Qt "blue" read too dark on many displays)
_UI_BLUE = '#b8dcff'
_UI_BLUE_MUTED = '#b0c8f0'

# Click-through cycle for the live banner's auto-refresh button.  Each entry
# is `(seconds, color, label)`; `seconds == 0` means the periodic timers stop
# and the user must hit each tab's Fetch / Poll button manually.  Colours go
# warm-fast → cool-slow so a glance at the top right tells you how aggressive
# the polling is.
_REFRESH_CYCLE = (
    (10,  '#f38ba8', 'Auto 10s'),    # red — very aggressive
    (30,  '#f38ba8', 'Auto 30s'),    # red — still hot
    (60,  '#fab387', 'Auto 60s'),    # amber
    (180, '#94e2d5', 'Auto 180s'),   # teal
    (300, '#a6e3a1', 'Auto 300s'),   # green — sensible default
    (600, '#a6e3a1', 'Auto 600s'),   # green — light touch
    (0,   '#cba6f7', 'Manual only'), # purple — no auto polling
)

# Muted green fill (readable on #1e1e2e) — default for every QPushButton = Refresh All.
_BTN_GREEN_BG = '#354a3f'
_BTN_GREEN_BG_HOVER = '#3f5649'
_BTN_GREEN_BG_PRESS = '#4a6352'
_BTN_GREEN_BORDER = 'rgba(166, 227, 161, 175)'
_REFRESH_ALL_BTN_QSS = (
    "QPushButton {"
    f"  background-color: {_BTN_GREEN_BG};"
    "  color: #e8f5e9;"
    f"  border: 1px solid {_BTN_GREEN_BORDER};"
    "  border-radius: 3px;"
    "  padding: 4px 14px;"
    "  font-weight: normal;"
    "}"
    "QPushButton:hover {"
    f"  background-color: {_BTN_GREEN_BG_HOVER};"
    "  border: 1px solid rgba(166, 227, 161, 210);"
    "  color: #f0fff0;"
    "}"
    "QPushButton:pressed {"
    f"  background-color: {_BTN_GREEN_BG_PRESS};"
    "  border: 1px solid rgba(166, 227, 161, 230);"
    "  padding-top: 5px; padding-bottom: 3px; padding-left: 13px; padding-right: 13px;"
    "}"
    "QPushButton:disabled {"
    "  background-color: rgba(166, 227, 161, 22);"
    "  color: #45475a;"
    "  border: 1px solid rgba(166, 227, 161, 40);"
    "}"
)

# Bottom-bar Alarms only. Same footprint as the green action buttons, red fill.
_BTN_ALARM_BG = "#8b3a44"
_BTN_ALARM_BG_HOVER = "#a34852"
_BTN_ALARM_BG_PRESS = "#6e2e36"
_ALARMS_BTN_QSS = (
    "QPushButton {"
    f"  background-color: {_BTN_ALARM_BG};"
    "  color: #ffe8ea;"
    "  border: 1px solid rgba(243, 139, 168, 180);"
    "  border-radius: 3px;"
    "  padding: 4px 14px;"
    "  font-weight: normal;"
    "}"
    "QPushButton:hover {"
    f"  background-color: {_BTN_ALARM_BG_HOVER};"
    "  color: #fff5f6;"
    "}"
    "QPushButton:pressed {"
    f"  background-color: {_BTN_ALARM_BG_PRESS};"
    "  padding-top: 5px; padding-bottom: 3px; padding-left: 13px; padding-right: 13px;"
    "}"
)

# Live-banner auto-refresh cycle pill (two-line status, same green motif).
_BANNER_REFRESH_CYCLE_QSS = (
    "QFrame#bannerRefreshCyclePill {"
    f"  background-color: {_BTN_GREEN_BG};"
    f"  border: 1px solid {_BTN_GREEN_BORDER};"
    "  border-radius: 6px;"
    "}"
    "QFrame#bannerRefreshCyclePill:hover {"
    f"  background-color: {_BTN_GREEN_BG_HOVER};"
    "  border: 1px solid rgba(166, 227, 161, 210);"
    "}"
    "QLabel#bannerRefreshCycleLine {"
    "  background: transparent;"
    "  border: none;"
    "  color: #e8f5e9;"
    "  font-size: 10px;"
    "  font-weight: 600;"
    "  padding: 0;"
    "  margin: 0;"
    "}"
)


__all__ = [n for n in globals() if not n.startswith('__')]
