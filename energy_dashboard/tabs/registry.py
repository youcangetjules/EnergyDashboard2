"""
Energy Dashboard — `tabs/registry.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.deps import *

# Group strip (left of the main tab bar). Order is left-to-right; always visible.
_MAIN_TAB_GROUPS = (
    # Dashboards is the landing group: first in the strip, and the
    # window always opens here (see main_window startup).
    ("usage", "Dashboards"),
    ("physical_plant", "Physical Plant Tools"),
    ("import_export", "Energy Import/Export"),
    ("forecasts", "Energy Forecasts"),
    ("calculators", "Calculators"),
    ("controls", "Controls"),
)

# Main window tab bar:
# (QSettings key or None = always visible, attribute on EnergyDashboard,
#  tab title, group id, updateable).
# updateable=True → solid green page tab; False → solid blue (static pages).
_MAIN_TAB_BAR_REGISTRY = (
    ("octopus_live", "octopus_live_tab", "  Octopus Live  ", "import_export", True),
    (None, "octopus_tab", "  Octopus Energy Data  ", "import_export", True),
    ("device_costs", "device_costs_tab", "  Daily import costs  ", "import_export", True),
    (None, "growatt_tab", "  Growatt Live Status  ", "usage", True),
    ("tasmota", "tasmota_tab", "  Tasmota Devices  ", "usage", True),
    ("combined", "combined_tab", "  Combined Dashboard  ", "usage", True),
    ("battery", "battery_tab", "  Battery Analysis  ", "physical_plant", True),
    ("pv_string_charge", "pv_string_charge_tab", "  PV String Charge  ", "physical_plant", True),
    ("pv_string_voltage", "pv_string_voltage_tab", "  String voltage  ", "physical_plant", True),
    ("pot_issues", "pot_issues_tab", "  Potential Issues  ", "physical_plant", True),
    ("roof_layout", "roof_layout_tab", "  Roof layout  ", "physical_plant", False),
    ("forecasts", "forecasts_tab", "  Forecasts  ", "forecasts", True),
    ("agile_prices", "agile_prices_tab", "  Agile Spot Prices  ", "forecasts", True),
    ("agile_year", "agile_year_tab", "  Agile Year  ", "forecasts", True),
    ("analytics", "analytics_tab", "  Battery Simulation  ", "calculators", True),
    ("advisor", "advisor_tab", "  Smart Advisor  ", "calculators", True),
    ("optimiser", "optimiser_tab", "  Optimiser  ", "calculators", True),
    ("shadow_trial", "shadow_trial_tab", "  Shadow Trial  ", "calculators", True),
    ("maximiser", "maximiser_tab", "  Maximiser  ", "calculators", True),
    ("grott_align", "grott_align_tab", "  Grott / API Align  ", "calculators", True),
    ("connectivity", "connectivity_tab", "  Connectivity Status  ", "controls", False),
    ("grott_setup", "grott_setup_tab", "  Grott Setup  ", "controls", False),
    ("command_sim", "command_sim_tab", "  Command Sim  ", "controls", False),
    ("db_viewer", "db_viewer_tab", "  Database Viewer  ", "controls", False),
    ("export", "export_tab", "  Export  ", "controls", False),
    ("console", "console_tab", "  Console  ", "controls", False),
    ("bug_tracker", "bug_tracker_tab", "  Bug Tracker  ", "controls", False),
    (None, "parameters_tab", "  Setup & Info  ", "controls", False),
    ("license", "license_tab", "  License  ", "controls", False),
)


def _main_tab_is_updateable(attr: str) -> bool:
    for _key, a, _title, _gid, updateable in _MAIN_TAB_BAR_REGISTRY:
        if a == attr:
            return bool(updateable)
    return True


__all__ = [n for n in globals() if not n.startswith('__')]
