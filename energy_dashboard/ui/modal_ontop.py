"""Blocking dialogs stay above the rest of the app until they are answered.

A modal OK / Cancel box freezes the main window. If that box slips behind
the main window, nothing on screen can be clicked.

Do not install a Python event filter on QApplication. Every event is then
handed to Python while PySide may already be inside getWrapperForQObject
setting a property, and that second wrap SIGSEGVs (BUG-060). Roof layout's
satellite map died that way. A short timer pins whichever dialog is modal.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QDialog

_HINT = Qt.WindowType.WindowStaysOnTopHint
_WATCH_MS = 50


def _blocks_app(dlg: QDialog) -> bool:
    if not isinstance(dlg, QDialog) or not dlg.isWindow():
        return False
    if dlg.isModal():
        return True
    return dlg.windowModality() != Qt.WindowModality.NonModal


def _pin(dlg: QDialog) -> None:
    """Give a blocking dialog the stay-on-top flag before it is usable."""
    if not dlg.property("_pm_ontop"):
        flags = dlg.windowFlags()
        if not (flags & _HINT):
            modality = dlg.windowModality()
            was_modal = dlg.isModal()
            visible = dlg.isVisible()
            dlg.setProperty("_pm_ontop", True)
            dlg.setWindowFlags(flags | _HINT)
            if was_modal:
                dlg.setModal(True)
            elif modality != Qt.WindowModality.NonModal:
                dlg.setWindowModality(modality)
            if visible:
                dlg.show()
        else:
            dlg.setProperty("_pm_ontop", True)
    dlg.raise_()
    dlg.activateWindow()


def _watch_modal() -> None:
    modal = QApplication.activeModalWidget()
    if not isinstance(modal, QDialog) or not _blocks_app(modal):
        return
    if not modal.property("_pm_ontop"):
        _pin(modal)
        return
    if modal.isVisible() and not modal.isActiveWindow():
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
