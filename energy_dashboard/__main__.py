"""Entry point: ``python -m energy_dashboard``."""
from __future__ import annotations

import energy_dashboard.qt_env  # noqa: F401 — before QApplication
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from energy_dashboard.app_entry import _configure_app_input_palette, _flush_qsettings_on_quit
from energy_dashboard.core.crash_log import (
    note_version,
    rearm_crash_logger,
    schedule_import_coredumps,
)
from energy_dashboard.core.gc_guard import install_shiboken_untrack
from energy_dashboard.core.logging import ensure_log_manager
from energy_dashboard.qt_env import configure_qt_webengine_chromium, prepare_qapplication_attributes
from energy_dashboard.version import APP_VERSION


def _install_exception_logger():
    """Log uncaught exceptions to the Console tab."""
    from energy_dashboard.core.logging import get_log_manager

    def _hook(exc_type, exc, tb):
        import traceback as _tb
        text = "".join(_tb.format_exception(exc_type, exc, tb))
        try:
            get_log_manager().err("Uncaught", text)
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _hook


def _refuse_second_dashboard(holder_pid: int | None) -> None:
    """A second launch must not open another window."""
    from PySide6.QtWidgets import QApplication, QMessageBox

    from energy_dashboard.core.single_instance import ask_dashboard_to_show

    app = QApplication.instance() or QApplication(sys.argv)
    del app
    who = f" (process {holder_pid})" if holder_pid else ""
    if ask_dashboard_to_show():
        print(
            f"Energy Dashboard is already running{who}. Showing that window.",
            flush=True,
        )
        sys.exit(0)
    print(
        f"Energy Dashboard is already running{who}. This copy will not start.",
        flush=True,
    )
    QMessageBox.information(
        None,
        "Energy Dashboard",
        "Energy Dashboard is already running"
        + (f"{who}." if who else ".")
        + "\n\nThis copy will not start. If the window is hidden, "
        "use the PowerMon tray icon.",
    )
    sys.exit(0)


def main() -> None:
    from energy_dashboard.core.single_instance import DASHBOARD_NAME, claim, listen_for_show

    dashboard_lock = claim(DASHBOARD_NAME)
    if not dashboard_lock.acquired:
        _refuse_second_dashboard(dashboard_lock.holder_pid)

    configure_qt_webengine_chromium()
    prepare_qapplication_attributes()
    app = QApplication(sys.argv)
    from energy_dashboard.ui.modal_ontop import install_modal_stay_on_top
    install_modal_stay_on_top(app)
    ensure_log_manager()
    _install_exception_logger()
    note_version(APP_VERSION)
    # Qt replaces fatal-signal handlers as WebEngine starts. Put ours back.
    rearm_crash_logger()
    QTimer.singleShot(2000, rearm_crash_logger)
    QTimer.singleShot(10000, rearm_crash_logger)

    def _announce_crash(message: str) -> None:
        try:
            from energy_dashboard.core.logging import get_log_manager
            get_log_manager().err("Crash", message)
        except Exception:
            pass

    schedule_import_coredumps(_announce_crash)

    from energy_dashboard.common import application_stylesheet
    from energy_dashboard.main_window import EnergyDashboard

    install_shiboken_untrack(app)

    # Fusion paints QWidget/QAbstractSpinBox backgrounds reliably from QSS on Linux.
    app.setStyle("Fusion")
    _configure_app_input_palette(app)
    app.setStyleSheet(application_stylesheet())
    app.setApplicationName("Energy Dashboard")
    app.setApplicationVersion(APP_VERSION)
    app.aboutToQuit.connect(_flush_qsettings_on_quit)
    window = EnergyDashboard()

    def _bring_forward() -> None:
        window.showNormal()
        window.raise_()
        window.activateWindow()

    listen_for_show(_bring_forward)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
