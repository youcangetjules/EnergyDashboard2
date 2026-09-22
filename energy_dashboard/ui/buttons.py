"""
Energy Dashboard — `ui/buttons.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.deps import *
from energy_dashboard.ui.palette import _TAB_PAGE_NOT_UPDATED, _TAB_PAGE_UPDATEABLE
from energy_dashboard.ui.theme_constants import *
# Set on QPushButton widgets that must not use the green motif (e.g. Tasmota Toggle).
PRIMARY_BUTTON_EXEMPT = 'primary_button_exempt'


def _apply_primary_button_style(btn):
    """Ensure a QPushButton uses the global green primary style (Fusion-safe)."""
    if btn is None:
        return
    if btn.property(PRIMARY_BUTTON_EXEMPT):
        return
    if btn.objectName() == "mainTabGroupBtn":
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
        if btn.objectName() == "mainTabGroupBtn":
            continue
        _apply_primary_button_style(btn)


def _prepare_dialog_buttons(dialog):
    """Call before showing a QDialog so its buttons match the primary motif."""
    _style_all_primary_buttons(dialog)


def _action_outcome_button_qss(ok: bool) -> str:
    """One-shot action after it has run: pale green if it worked, black if it failed.

    Pale green is the same fill as a page tab that has just refreshed
    (``_TAB_PAGE_UPDATEABLE``). Black is the same as a tab that never updated.
    """
    if ok:
        bg = _TAB_PAGE_UPDATEABLE
        # Same pairing as a freshly refreshed page tab: dark label on this green.
        fg = "#000000"
        hover = "#6ec484"
        press = "#4e9a60"
        border = "rgba(0, 0, 0, 55)"
    else:
        bg = _TAB_PAGE_NOT_UPDATED
        fg = "#ffffff"
        hover = "#313244"
        press = "#11111b"
        border = "#45475a"
    return (
        "QPushButton {"
        f"  background-color: {bg};"
        f"  color: {fg};"
        f"  border: 1px solid {border};"
        "  border-radius: 3px;"
        "  padding: 4px 14px;"
        "  font-weight: 600;"
        "}"
        "QPushButton:hover {"
        f"  background-color: {hover};"
        f"  color: {fg};"
        "}"
        "QPushButton:pressed {"
        f"  background-color: {press};"
        f"  color: {fg};"
        "  padding-top: 5px; padding-bottom: 3px; padding-left: 13px; padding-right: 13px;"
        "}"
        "QPushButton:disabled {"
        f"  background-color: {bg};"
        f"  color: {fg};"
        f"  border: 1px solid {border};"
        "}"
    )


def _apply_action_outcome_style(btn, ok: bool):
    """Paint a one-shot action button for its last result. Later primary-style walks skip it."""
    if btn is None:
        return
    btn.setProperty(PRIMARY_BUTTON_EXEMPT, True)
    btn.setAutoFillBackground(True)
    btn.setStyleSheet(_action_outcome_button_qss(bool(ok)))


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
QCheckBox#tasmotaPinHistY {
    color: #ffffff;
    font-weight: bold;
    padding: 5px 8px 5px 12px;
    border-radius: 6px;
    background-color: rgba(255, 255, 255, 28);
    border: 1px solid rgba(255, 255, 255, 130);
}
QCheckBox#tasmotaPinHistY:hover {
    background-color: rgba(255, 255, 255, 45);
    border: 1px solid rgba(255, 255, 255, 200);
}
QSpinBox#tasmotaPinHistW {
    color: #ffffff;
    font-weight: bold;
    padding: 3px 6px;
    border-radius: 6px;
    background-color: rgba(255, 255, 255, 28);
    border: 1px solid rgba(255, 255, 255, 130);
    min-width: 72px;
}
QSpinBox#tasmotaPinHistW:hover {
    background-color: rgba(255, 255, 255, 45);
    border: 1px solid rgba(255, 255, 255, 200);
}
"""


__all__ = [n for n in globals() if not n.startswith('__')]
