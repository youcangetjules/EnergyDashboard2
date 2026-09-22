"""Entry point: ``python -m energy_dashboard``."""
from __future__ import annotations

import energy_dashboard.qt_env  # noqa: F401 — before QApplication
import sys

from PySide6.QtWidgets import QApplication

from energy_dashboard.app_entry import _configure_app_input_palette, _flush_qsettings_on_quit
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


def main() -> None:
    configure_qt_webengine_chromium()
    prepare_qapplication_attributes()
    app = QApplication(sys.argv)
    from energy_dashboard.ui.modal_ontop import install_modal_stay_on_top
    install_modal_stay_on_top(app)
    ensure_log_manager()
    _install_exception_logger()

    from energy_dashboard.common import application_stylesheet
    from energy_dashboard.main_window import EnergyDashboard

    # Fusion paints QWidget/QAbstractSpinBox backgrounds reliably from QSS on Linux.
    app.setStyle("Fusion")
    _configure_app_input_palette(app)
    app.setStyleSheet(application_stylesheet())
    app.setApplicationName("Energy Dashboard")
    app.setApplicationVersion(APP_VERSION)
    app.aboutToQuit.connect(_flush_qsettings_on_quit)
    window = EnergyDashboard()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
