"""Keep automatic garbage collection on, without letting it destroy Qt objects.

A worker thread that is collecting cycles can run at the same moment the main
thread has let go of the Python lock inside a Qt teardown (seen during tab-bar
painting, while a fetch allocated enough to start a collection). The collector
then walks a half-destroyed Qt wrapper and the process segfaults.

PySide also replaces the built-in import with its own hook, so that
``from __feature__ import snake_case`` can rename methods. This app does not
use that. Every later import — including one inside an Octopus fetch — still
entered that hook, and the hook calls into Shiboken. Doing that while the tab
bar is painting segfaults the same way.

Python 3.14 still collects cycles automatically. Qt wrappers are taken off
that list as soon as they are created. The built-in import PySide saved is put
back, so a worker import does not enter Shiboken. Reference counting still
frees Qt objects on the thread that drops the last reference. Ordinary Python
objects (lists, query results, and so on) are collected as usual.
"""
from __future__ import annotations

import ctypes
import gc
import sys

_ctypes_ready = False
_is_tracked = None
_untrack_c = None
_wrapped: set[type] = set()
_pyside_modules_seen: tuple[str, ...] | None = None


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
    """Wrap PySide classes already imported so new instances are untracked.

    Scanning every PySide module is expensive. Skip it when the set of
    imported modules has not changed since the last sweep.
    """
    global _pyside_modules_seen
    names = tuple(
        name for name, mod in sys.modules.items()
        if name.startswith("PySide6") and mod is not None
    )
    if names == _pyside_modules_seen:
        return
    modules = [sys.modules[name] for name in names]
    for mod in modules:
        for name in dir(mod):
            try:
                cls = getattr(mod, name)
            except Exception:
                continue
            if isinstance(cls, type):
                _wrap_type(cls)
    _pyside_modules_seen = names


def untrack_existing_wrappers() -> None:
    """Untrack Qt wrappers that were created before the hook, or inside Qt."""
    try:
        import shiboken6
        wrappers = shiboken6.getAllValidWrappers()
    except Exception:
        return
    for obj in wrappers:
        untrack_qt_wrapper(obj)


def restore_builtin_import() -> None:
    """Put back the import PySide replaced.

    PySide's hook is only there for ``from __feature__ import ...``. A worker
    that imports while the window is painting enters Shiboken through that
    hook and the process segfaults. If the hook is what is installed, put the
    saved import back. Leave any other replacement alone.
    """
    import builtins
    orig = getattr(builtins, "__orig_import__", None)
    feature = getattr(builtins, "__feature_import__", None)
    if orig is None or feature is None:
        return
    if builtins.__import__ is not feature:
        return
    builtins.__import__ = orig


def install_shiboken_untrack(parent=None):
    """Leave cyclic GC enabled. Keep Qt wrappers out of it.

    ``parent`` is the QApplication. A short timer repeats the sweep so a
    wrapper born inside Qt itself is untracked before a worker collection.
    The same sweep puts the built-in import back if PySide has replaced it.
    """
    gc.enable()
    restore_builtin_import()
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
    restore_builtin_import()
    wrap_loaded_pyside_types()
    untrack_existing_wrappers()
