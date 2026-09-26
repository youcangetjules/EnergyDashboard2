"""Blocking dialogs stay above the rest of the app until they are answered.

A modal OK / Cancel box freezes the main window. If that box slips behind
the main window, nothing on screen can be clicked.

Do not install a Python event filter on QApplication. Every event is then
handed to Python while PySide may already be inside getWrapperForQObject
setting a property, and that second wrap SIGSEGVs (BUG-060). Roof layout's
satellite map died that way. A short timer only raises a dialog that has
slipped behind.

Do not change a dialog's window flags once it is visible. Qt hides a window
when its flags change. Doing that during exec() left Connectivity popups on
screen for a moment, then stuck the dashboard waiting for a window the user
could no longer see (BUG-066).
"""
from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QDialog

_HINT = Qt.WindowType.WindowStaysOnTopHint
_WATCH_MS = 50
_ARMED = "_pm_ontop"


def _blocks_app(dlg: QDialog) -> bool:
    if not isinstance(dlg, QDialog) or not dlg.isWindow():
        return False
    if dlg.isModal():
        return True
    return dlg.windowModality() != Qt.WindowModality.NonModal


def _arm_before_show(dlg: QDialog) -> None:
    """Stay-on-top is applied only while the dialog is still hidden."""
    if not isinstance(dlg, QDialog) or dlg.property(_ARMED):
        return
    if dlg.isVisible():
        # Too late. Changing flags now would hide the window (BUG-066).
        dlg.setProperty(_ARMED, True)
        return
    flags = dlg.windowFlags()
    dlg.setProperty(_ARMED, True)
    if flags & _HINT:
        return
    modality = dlg.windowModality()
    was_modal = dlg.isModal()
    dlg.setWindowFlags(flags | _HINT)
    if was_modal:
        dlg.setModal(True)
    elif modality != Qt.WindowModality.NonModal:
        dlg.setWindowModality(modality)


def _watch_modal() -> None:
    modal = QApplication.activeModalWidget()
    if not isinstance(modal, QDialog) or not _blocks_app(modal):
        return
    if not modal.property(_ARMED):
        modal.setProperty(_ARMED, True)
    if modal.isVisible() and not modal.isActiveWindow():
        modal.raise_()
        modal.activateWindow()


def _install_arm_hooks() -> None:
    """Put the stay-on-top flag on before Python shows or runs a dialog."""
    if getattr(QDialog, "_pm_exec_armed", False):
        return
    orig_exec = QDialog.exec
    orig_open = QDialog.open
    orig_show = QDialog.show

    def exec_(self, *args, **kwargs):
        _arm_before_show(self)
        return orig_exec(self, *args, **kwargs)

    def open_(self, *args, **kwargs):
        _arm_before_show(self)
        return orig_open(self, *args, **kwargs)

    def show_(self, *args, **kwargs):
        _arm_before_show(self)
        return orig_show(self, *args, **kwargs)

    QDialog.exec = exec_
    QDialog.open = open_
    QDialog.show = show_
    QDialog._pm_exec_armed = True


def install_modal_stay_on_top(app) -> None:
    """Start the modal watch once. Safe to call again."""
    if getattr(app, "_pm_modal_stay_on_top", None) is not None:
        return
    _install_arm_hooks()
    timer = QTimer(app)
    timer.setInterval(_WATCH_MS)
    timer.timeout.connect(_watch_modal)
    timer.start()
    app._pm_modal_stay_on_top = timer
