"""Energy Dashboard — PySide6 energy monitoring application."""

from energy_dashboard.version import APP_VERSION


def __getattr__(name):
    if name == "EnergyDashboard":
        from energy_dashboard.main_window import EnergyDashboard
        return EnergyDashboard
    raise AttributeError(name)


__all__ = ["APP_VERSION", "EnergyDashboard"]
