"""
Energy Dashboard — `core/invoker.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.deps import *
class Invoker(QObject):
    """Thread-safe mechanism to run callbacks on the main/GUI thread."""
    _signal = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._signal.connect(self._execute)

    @Slot(object)
    def _execute(self, fn):
        fn()

    def invoke(self, fn):
        try:
            self._signal.emit(fn)
        except RuntimeError:
            # Invoker or its QObject graph destroyed (e.g. window closed while a
            # worker thread still calls invoke) — drop the callback safely.
            pass


__all__ = [n for n in globals() if not n.startswith('__')]
