"""
Energy Dashboard — `version.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.deps import *
# Semantic version (major.minor.patch). Default: increment APP_VERSION_PATCH for
# each routine update. Bump minor or major only when explicitly requested.
APP_VERSION_MAJOR = 2
APP_VERSION_MINOR = 9
APP_VERSION_PATCH = 455
APP_VERSION = f"{APP_VERSION_MAJOR}.{APP_VERSION_MINOR}.{APP_VERSION_PATCH}"


__all__ = [n for n in globals() if not n.startswith('__')]
