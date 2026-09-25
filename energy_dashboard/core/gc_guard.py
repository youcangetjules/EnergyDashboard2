"""Keep automatic garbage collection on, without letting it destroy Qt objects.

A worker thread that is collecting cycles can run at the same moment the main
thread has let go of the Python lock inside a Qt teardown (seen during tab-bar
painting, while a Tasmota history fetch allocated enough to start a
collection). The collector then walks a half-destroyed Qt wrapper and the
process segfaults.

Python 3.14 still collects cycles automatically. Qt wrappers are taken off
that list as soon as they are created. Reference counting still frees them on
the thread that drops the last reference. Ordinary Python objects (lists,
query results, and so on) are collected as usual.
"""
from __future__ import annotations

import ctypes
import gc
import sys

_ctypes_ready = False
_is_tracked = None
_untrack_c = None
_wrapped: set[type] = set()


def _bind_ctypes() -> None:
    global _ctypes_ready, _is_tracked, _untrack_c
    if _ctypes_ready:
        return
    api = ctypes.pythonapi
    api.PyObject_GC_IsTracked.argtypes = [ctypes.py_object]
    api.PyObject_GC_IsTracked.restype = ctypes.c_int
    api.PyObject_GC_UnTrack.argtypes = [ctypes.py_object]
    api.PyObject_GC_UnTrack.restype = None
    _is_tracked = api.PyObject_GC_IsTracked
    _untrack_c = api.PyObject_GC_UnTrack
    _ctypes_ready = True


def untrack_qt_wrapper(obj) -> None:
    """Drop one Shiboken wrapper from the cycle collector. Refcounting is unchanged."""
    try:
        _bind_ctypes()
        if _is_tracked(obj):
            _untrack_c(obj)
    except Exception:
        pass


def _wrap_type(cls: type) -> None:
    if cls in _wrapped or not isinstance(cls, type):
        return
    module = getattr(cls, "__module__", "") or ""
    if not module.startswith("PySide6"):
        return
    try:
        orig = cls.__dict__.get("__init__", None)
        if orig is None:
            orig = cls.__init__
    except Exception:
        return
    if getattr(orig, "_powermodel_untrack", False):
        _wrapped.add(cls)
        return

    def __init__(self, *args, **kwargs):
        untrack_qt_wrapper(self)
        orig(self, *args, **kwargs)
        untrack_qt_wrapper(self)

    __init__._powermodel_untrack = True
    try:
        cls.__init__ = __init__
    except Exception:
        return
    _wrapped.add(cls)


def wrap_loaded_pyside_types() -> None:
    """Wrap PySide classes already imported so new instances are untracked."""
    modules = [
        mod for name, mod in list(sys.modules.items())
        if name.startswith("PySide6") and mod is not None
    ]
    for mod in modules:
        for name in dir(mod):
            try:
                cls = getattr(mod, name)
            except Exception:
                continue
            if isinstance(cls, type):
                _wrap_type(cls)


def untrack_existing_wrappers() -> None:
    """Untrack Qt wrappers that were created before the hook, or inside Qt."""
    try:
        import shiboken6
        wrappers = shiboken6.getAllValidWrappers()
    except Exception:
        return
    for obj in wrappers:
        untrack_qt_wrapper(obj)


def install_shiboken_untrack(parent=None):
    """Leave cyclic GC enabled. Keep Qt wrappers out of it.

    ``parent`` is the QApplication. A short timer repeats the sweep so a
    wrapper born inside Qt itself is untracked before a worker collection.
    """
    gc.enable()
    wrap_loaded_pyside_types()
    untrack_existing_wrappers()
    if parent is None:
        return None
    from PySide6.QtCore import QTimer

    timer = QTimer(parent)
    timer.setInterval(2000)
    timer.timeout.connect(_sweep)
    timer.start()
    return timer


def _sweep() -> None:
    wrap_loaded_pyside_types()
    untrack_existing_wrappers()
