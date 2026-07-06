"""
Energy Dashboard — `tabs/registry.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.deps import *
# Main window tab bar: (QSettings key or None = always visible, attribute on
# EnergyDashboard, tab title string). Order is the canonical bar order.
_MAIN_TAB_BAR_REGISTRY = (
    (None, "growatt_tab", "  Growatt Live Status  "),
    ("octopus_live", "octopus_live_tab", "  Octopus Live  "),
    ("tasmota", "tasmota_tab", "  Tasmota Devices  "),
    (None, "octopus_tab", "  Octopus Energy Data  "),
    ("device_costs", "device_costs_tab", "  Daily import costs  "),
    ("combined", "combined_tab", "  Combined Dashboard  "),
    ("battery", "battery_tab", "  Battery Analysis  "),
    ("analytics", "analytics_tab", "  Battery Simulation  "),
    ("forecasts", "forecasts_tab", "  Forecasts  "),
    ("agile_prices", "agile_prices_tab", "  Agile Spot Prices  "),
    ("advisor", "advisor_tab", "  Smart Advisor  "),
    ("optimiser", "optimiser_tab", "  Optimiser  "),
    ("shadow_trial", "shadow_trial_tab", "  Shadow Trial  "),
    ("maximiser", "maximiser_tab", "  Maximiser  "),
    ("connectivity", "connectivity_tab", "  Connectivity Status  "),
    ("command_sim", "command_sim_tab", "  Command Sim  "),
    ("db_viewer", "db_viewer_tab", "  Database Viewer  "),
    ("export", "export_tab", "  Export  "),
    ("console", "console_tab", "  Console  "),
    (None, "parameters_tab", "  Setup & Info  "),
    ("license", "license_tab", "  License  "),
)


__all__ = [n for n in globals() if not n.startswith('__')]
