"""Bring a blocking dialog back if the main window covers it.

A modal OK / Cancel box freezes the main window. If that box slips behind
the main window, nothing on screen can be clicked.

The dialog stays a normal window. Marking it "always on top" made Plasma
treat it as a layer the screenshot tool skips, and a focus grab every
50 ms closed the Copy / Paste menu before it could be used (BUG-069).

Do not install a Python event filter on QApplication. Every event is then
handed to Python while PySide may already be inside getWrapperForQObject
setting a property, and that second wrap SIGSEGVs (BUG-060).

Do not change a dialog's window flags once it is visible. Qt hides a window
when its flags change (BUG-066).
"""
from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QDialog

_WATCH_MS = 50


def _blocks_app(dlg: QDialog) -> bool:
    if not isinstance(dlg, QDialog) or not dlg.isWindow():
        return False
    if dlg.isModal():
        return True
    return dlg.windowModality() != Qt.WindowModality.NonModal


def _main_window_covered_it(dlg: QDialog) -> bool:
    """True only when the dashboard itself is the window in front."""
    if dlg.isActiveWindow():
        return False
    parent = dlg.parentWidget()
    if parent is None:
        return False
    owner = parent.window()
    return owner is not None and owner is not dlg and owner.isActiveWindow()


def _watch_modal() -> None:
    modal = QApplication.activeModalWidget()
    if not isinstance(modal, QDialog) or not _blocks_app(modal):
        return
    if not modal.isVisible() or not _main_window_covered_it(modal):
        return
    modal.raise_()
    modal.activateWindow()


def install_modal_stay_on_top(app) -> None:
    """Start the modal watch once. Safe to call again."""
    if getattr(app, "_pm_modal_stay_on_top", None) is not None:
        return
    timer = QTimer(app)
    timer.setInterval(_WATCH_MS)
    timer.timeout.connect(_watch_modal)
    timer.start()
    app._pm_modal_stay_on_top = timer
