"""Transient on-screen confirmations (e.g. green Saved flash)."""
from __future__ import annotations

from energy_dashboard.deps import *


class SavedToast(QLabel):
    """Centered green “Saved” flash over the host window."""

    def __init__(self, host: QWidget):
        super().__init__(host)
        self.setObjectName("savedToast")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setStyleSheet(
            """
            QLabel#savedToast {
                background-color: rgba(30, 30, 46, 235);
                color: #a6e3a1;
                border: 2px solid #a6e3a1;
                border-radius: 12px;
                padding: 16px 36px;
                font-size: 20px;
                font-weight: 700;
            }
            """
        )
        self.hide()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def flash(self, text: str = "Saved", *, ms: int = 1600) -> None:
        self.setText(str(text or "Saved"))
        self.adjustSize()
        host = self.parentWidget()
        if host is not None:
            self.adjustSize()
            w = max(self.width(), 120)
            h = max(self.height(), 48)
            self.resize(w, h)
            x = max(0, (host.width() - w) // 2)
            y = max(24, host.height() // 6)
            self.move(x, y)
        self.show()
        self.raise_()
        self._timer.start(max(400, int(ms)))


def flash_saved(host: QWidget | None, text: str = "Saved", *, ms: int = 1600) -> None:
    """Show a green Saved toast on ``host`` (creates one toast per host).

    Always runs on the GUI thread — creating/showing a QLabel from a worker
    during paint is a known segfault path under PySide6.
    """
    if host is None:
        return
    app = QApplication.instance()
    if app is None:
        return
    if QThread.currentThread() is not app.thread():
        QTimer.singleShot(0, host, lambda: flash_saved(host, text, ms=ms))
        return
    # Defer one event-loop tick so we never create/resize widgets mid-paint.
    if getattr(host, "_saved_toast_pending", False):
        host._saved_toast_text = text
        host._saved_toast_ms = ms
        return

    def _do_flash():
        host._saved_toast_pending = False
        msg = getattr(host, "_saved_toast_text", text)
        dur = getattr(host, "_saved_toast_ms", ms)
        try:
            toast = getattr(host, "_saved_toast", None)
            if toast is None or toast.parent() is not host:
                toast = SavedToast(host)
                host._saved_toast = toast
            toast.flash(msg, ms=dur)
        except RuntimeError:
            pass

    host._saved_toast_pending = True
    host._saved_toast_text = text
    host._saved_toast_ms = ms
    QTimer.singleShot(0, host, _do_flash)


__all__ = ["SavedToast", "flash_saved"]
