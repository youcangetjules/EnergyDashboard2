"""
Shared symbols for tab, dialog, and main-window modules.

Tab modules: ``from energy_dashboard.common import *``
"""
from __future__ import annotations

from energy_dashboard import _export as _x

_common = globals()
for _mod in (
    "energy_dashboard.deps",
    "energy_dashboard.paths",
    "energy_dashboard.version",
    "energy_dashboard.content.about",
    "energy_dashboard.content.help",
    "energy_dashboard.content.license_text",
    "energy_dashboard.ui.theme_constants",
    "energy_dashboard.ui.buttons",
    "energy_dashboard.ui.toolbar",
    "energy_dashboard.core.console_paths",
    "energy_dashboard.core.invoker",
    "energy_dashboard.ui.columns",
    "energy_dashboard.core.logging",
    "energy_dashboard.config",
    "energy_dashboard.db.logger",
    "energy_dashboard.db.schema",
    "energy_dashboard.fetch.octopus_rest",
    "energy_dashboard.fetch.octopus_gql",
    "energy_dashboard.ui.cards",
    "energy_dashboard.ui.palette",
    "energy_dashboard.ui.styles",
    "energy_dashboard.ui.chart_utils",
    "energy_dashboard.planner.core",
    "energy_dashboard.planner.shadow",
    "energy_dashboard.modbus.command_sim",
    "energy_dashboard.utils.agile_rates",
    "energy_dashboard.tabs.registry",
):
    _x.load(_common, _mod)

__all__ = [n for n in globals() if not n.startswith("__") and not n.startswith("_mod") and n != "_common" and n != "_x"]
