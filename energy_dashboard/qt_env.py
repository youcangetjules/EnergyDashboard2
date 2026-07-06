"""Qt platform env — must run before any PySide6 / QApplication import."""
from __future__ import annotations

import os
import sys


def configure_qt_platform() -> None:
    """Apply process-wide Qt settings for this app."""
    # Matplotlib QtAgg backend defaults to PyQt6 when both bindings are installed.
    os.environ.setdefault("QT_API", "pyside6")

    if not sys.platform.startswith("linux"):
        return
    # Screen-reader users can set POWERMODEL_QT_A11Y=1 to keep AT-SPI logging.
    if os.environ.get("POWERMODEL_QT_A11Y", "").strip().lower() in ("1", "true", "yes"):
        return
    rule = "qt.accessibility.atspi=false"
    existing = os.environ.get("QT_LOGGING_RULES", "").strip()
    if rule not in existing:
        os.environ["QT_LOGGING_RULES"] = f"{existing};{rule}".strip(";")


configure_qt_platform()
