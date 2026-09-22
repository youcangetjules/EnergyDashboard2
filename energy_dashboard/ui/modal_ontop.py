"""Blocking dialogs stay above the rest of the app until they are answered.

A modal OK / Cancel box freezes the main window. If that box slips behind
the main window, nothing on screen can be clicked. Every application-modal
or window-modal dialog is pinned to the top as it is shown.
"""
from __future__ import annotations

import weakref

from PySide6.QtCore import QEvent, QObject, QTimer, Qt
from PySide6.QtWidgets import QApplication, QDialog

_HINT = Qt.WindowType.WindowStaysOnTopHint


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


def _raise_later(dlg: QDialog) -> None:
    if dlg is None or dlg.property("_pm_raise_pending"):
        return
    dlg.setProperty("_pm_raise_pending", True)
    ref = weakref.ref(dlg)

    def _go():
        window = ref()
        if window is None:
            return
        window.setProperty("_pm_raise_pending", False)
        if window.isVisible() and _blocks_app(window):
            window.raise_()
            window.activateWindow()

    QTimer.singleShot(0, _go)


class _ModalStayOnTop(QObject):
    def eventFilter(self, obj, event):
        etype = event.type()
        if isinstance(obj, QDialog) and etype in (
            QEvent.Type.Polish,
            QEvent.Type.Show,
        ):
            if _blocks_app(obj):
                _pin(obj)
        elif isinstance(obj, QDialog) and etype == QEvent.Type.WindowDeactivate:
            if obj.isVisible() and _blocks_app(obj):
                _raise_later(obj)
        elif etype == QEvent.Type.WindowActivate:
            modal = QApplication.activeModalWidget()
            if (
                isinstance(modal, QDialog)
                and modal is not obj
                and _blocks_app(modal)
            ):
                _raise_later(modal)
        elif etype == QEvent.Type.WindowBlocked:
            modal = QApplication.activeModalWidget()
            if isinstance(modal, QDialog) and _blocks_app(modal):
                _raise_later(modal)
        return False


def install_modal_stay_on_top(app) -> None:
    """Install once on the QApplication. Safe to call again."""
    if getattr(app, "_pm_modal_stay_on_top", None) is not None:
        return
    filt = _ModalStayOnTop(app)
    app.installEventFilter(filt)
    app._pm_modal_stay_on_top = filt
