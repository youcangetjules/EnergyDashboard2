"""
Energy Dashboard — `ui/buttons.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.deps import *
from energy_dashboard.ui.theme_constants import *
# Set on QPushButton widgets that must not use the green motif (e.g. Tasmota Toggle).
PRIMARY_BUTTON_EXEMPT = 'primary_button_exempt'


def _apply_primary_button_style(btn):
    """Ensure a QPushButton uses the global green primary style (Fusion-safe)."""
    if btn is None:
        return
    btn.setAutoFillBackground(True)
    btn.setStyleSheet(_REFRESH_ALL_BTN_QSS)


def _style_all_primary_buttons(root):
    """Apply the green primary motif to every QPushButton under *root* (action buttons)."""
    if root is None:
        return
    for btn in root.findChildren(QPushButton):
        if btn.property(PRIMARY_BUTTON_EXEMPT):
            continue
        _apply_primary_button_style(btn)


def _prepare_dialog_buttons(dialog):
    """Call before showing a QDialog so its buttons match the primary motif."""
    _style_all_primary_buttons(dialog)


# Applied on QApplication: primary-button green + chart toolbar QToolButton chrome.
_APP_GLOBAL_WIDGET_QSS = (
    _REFRESH_ALL_BTN_QSS
    + "QToolButton {"
    "  background-color: transparent;"
    "  border: 1px solid transparent;"
    "  border-radius: 3px;"
    "  padding: 2px;"
    "}"
    "QToolButton:hover {"
    "  background-color: rgba(137, 180, 250, 55);"
    "  border: 1px solid rgba(137, 180, 250, 130);"
    "}"
    "QToolButton:pressed {"
    "  background-color: rgba(137, 180, 250, 100);"
    "  border: 1px solid rgba(137, 180, 250, 180);"
    "}"
)


_TASMOTA_PIN_CHART_CB_QSS = """
QCheckBox#tasmotaPinHist500 {
    color: #ffffff;
    font-weight: bold;
    padding: 5px 12px;
    border-radius: 6px;
    background-color: rgba(255, 255, 255, 28);
    border: 1px solid rgba(255, 255, 255, 130);
}
QCheckBox#tasmotaPinHist500:hover {
    background-color: rgba(255, 255, 255, 45);
    border: 1px solid rgba(255, 255, 255, 200);
}
"""


__all__ = [n for n in globals() if not n.startswith('__')]
