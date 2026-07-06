#!/usr/bin/env python3
"""Prepend import headers to split energy_dashboard modules."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PKG = ROOT / "energy_dashboard"

FOUNDATION = {
    "version.py": "from energy_dashboard.deps import *\n",
    "content/about.py": (
        "from energy_dashboard.deps import *\n"
        "from energy_dashboard.version import APP_VERSION\n"
    ),
    "content/help.py": "from energy_dashboard.deps import *\n",
    "content/license_text.py": "from energy_dashboard.deps import *\n",
    "ui/theme_constants.py": "from energy_dashboard.deps import *\n",
    "ui/buttons.py": (
        "from energy_dashboard.deps import *\n"
        "from energy_dashboard.ui.theme_constants import *\n"
    ),
    "ui/toolbar.py": (
        "from energy_dashboard.deps import *\n"
        "from energy_dashboard.ui.theme_constants import _TASMOTA_PIN_CHART_CB_QSS\n"
    ),
    "core/console_paths.py": (
        "from energy_dashboard.deps import Path\n"
    ),
    "core/invoker.py": "from energy_dashboard.deps import *\n",
    "ui/columns.py": "from energy_dashboard.deps import *\n",
    "core/logging.py": (
        "from energy_dashboard.deps import *\n"
        "from energy_dashboard.core.console_paths import *\n"
        "from energy_dashboard.version import APP_VERSION\n"
    ),
    "config.py": "from energy_dashboard.deps import *\n",
    "db/logger.py": (
        "from energy_dashboard.deps import *\n"
        "from energy_dashboard.config import *\n"
    ),
    "db/schema.py": "from energy_dashboard.deps import *\n",
    "fetch/octopus_rest.py": (
        "from energy_dashboard.deps import *\n"
        "from energy_dashboard.core.logging import _log\n"
    ),
    "fetch/octopus_gql.py": (
        "from energy_dashboard.deps import *\n"
        "from energy_dashboard.core.logging import _log\n"
    ),
    "ui/cards.py": (
        "from energy_dashboard.deps import *\n"
        "from energy_dashboard.config import AppParameters\n"
        "from energy_dashboard.core.logging import _log\n"
    ),
    "ui/palette.py": "from energy_dashboard.deps import *\n",
    "ui/styles.py": (
        "from energy_dashboard.deps import *\n"
        "from energy_dashboard.paths import UI_ASSETS_DIR\n"
        "from energy_dashboard.ui.palette import *\n"
        "from energy_dashboard.ui.theme_constants import _APP_GLOBAL_WIDGET_QSS\n"
    ),
    "ui/chart_utils.py": (
        "from energy_dashboard.deps import *\n"
        "from energy_dashboard.ui.palette import *\n"
    ),
    "planner/core.py": "from energy_dashboard.deps import *\n",
    "planner/maximiser.py": "from energy_dashboard.deps import *\n",
    "modbus/command_sim.py": (
        "from energy_dashboard.deps import *\n"
        "from energy_dashboard.core.logging import _log\n"
    ),
    "tabs/registry.py": "from energy_dashboard.deps import *\n",
}

COMMON_HEADER = "from energy_dashboard.common import *\n"

TAB_AND_DIALOG = {
    "tabs/growatt.py",
    "tabs/octopus.py",
    "tabs/combined.py",
    "tabs/battery_analysis.py",
    "tabs/analytics.py",
    "tabs/forecasts.py",
    "tabs/device_import_costs.py",
    "tabs/octopus_live.py",
    "tabs/tasmota.py",
    "tabs/smart_advisor.py",
    "tabs/optimiser.py",
    "tabs/parameters.py",
    "tabs/database_viewer.py",
    "tabs/console.py",
    "tabs/license.py",
    "tabs/export_tab.py",
    "tabs/connectivity.py",
    "dialogs/map_picker.py",
    "dialogs/about_history.py",
    "main_window.py",
    "app_entry.py",
}


def prepend(rel: str, header: str) -> None:
    path = PKG / rel
    text = path.read_text(encoding="utf-8")
    marker = "from __future__ import annotations\n\n"
    if marker not in text:
        raise SystemExit(f"unexpected header in {rel}")
    body = text.split(marker, 1)[1]
    if body.startswith("from energy_dashboard."):
        return
    path.write_text(text.split(marker, 1)[0] + marker + header + body, encoding="utf-8")


def main() -> None:
    for rel, header in FOUNDATION.items():
        prepend(rel, header)
    for rel in TAB_AND_DIALOG:
        prepend(rel, COMMON_HEADER)
    print("Prepended import headers.")


if __name__ == "__main__":
    main()
