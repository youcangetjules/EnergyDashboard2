"""Keep Python's cycle collector off worker threads.

Reference counting still frees objects straight away. The cycle collector is
the part that walks the whole heap, including PySide wrappers. If a worker
triggers that walk — a large Postgres fetch is enough — it can free or touch
a Qt object while the main thread is inside Qt (tab-bar paint). That has
segfaulted in CPython's GC (``_Py_HandlePending``) after the dashboard has
been open for hours.

Automatic collection is turned off at startup. A timer on the GUI thread
runs it between events, and skips a pass while a database fetch is in
native code.
"""
from __future__ import annotations

import gc
import threading

_lock = threading.Lock()
_native_busy = 0
_ticks = 0


def disable_automatic_gc() -> None:
    """Stop the cycle collector from running on whichever thread allocates next."""
    gc.disable()


class pause_cyclic_gc:
    """Tell the GUI collector to wait until this native call has finished."""

    def __enter__(self):
        global _native_busy
        with _lock:
            _native_busy += 1
        return self

    def __exit__(self, exc_type, exc, tb):
        global _native_busy
        with _lock:
            _native_busy = max(0, _native_busy - 1)
        return False


def _collect_on_gui() -> None:
    global _ticks
    with _lock:
        if _native_busy:
            return
        _ticks += 1
        full = (_ticks % 6) == 0
    try:
        if full:
            gc.collect()
        else:
            gc.collect(0)
    except Exception:
        pass


def install_gui_gc_timer(parent):
    """Parent a timer to ``parent`` (the QApplication) and start it.

    Young cycles every 10 s; a full sweep about once a minute. The timer is
    a child of the application so it lives for the whole session.
    """
    from PySide6.QtCore import QTimer

    disable_automatic_gc()
    timer = QTimer(parent)
    timer.setInterval(10_000)
    timer.timeout.connect(_collect_on_gui)
    timer.start()
    return timer
