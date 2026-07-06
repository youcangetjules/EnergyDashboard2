#!/usr/bin/env python3
"""One-shot splitter: EnergyDashboard2.py -> energy_dashboard/ package."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "EnergyDashboard2.py"
PKG = ROOT / "energy_dashboard"

# (relative path under energy_dashboard/, start_line, end_line) — 1-based inclusive
SECTIONS: list[tuple[str, int, int]] = [
    ("version.py", 60, 65),
    ("content/about.py", 67, 1334),
    ("content/help.py", 1337, 1592),
    ("content/license_text.py", 1595, 1756),
    ("ui/theme_constants.py", 1759, 1834),
    ("ui/buttons.py", 1837, 1908),
    ("ui/toolbar.py", 1911, 2010),
    ("core/console_paths.py", 2011, 2017),
    ("core/invoker.py", 2021, 2039),
    ("ui/columns.py", 2044, 2200),
    ("core/logging.py", 2204, 2347),
    ("config.py", 2350, 2407),
    ("db/logger.py", 2412, 3236),
    ("db/schema.py", 3238, 3367),
    ("fetch/octopus_rest.py", 3371, 3860),
    ("fetch/octopus_gql.py", 3863, 4102),
    ("ui/cards.py", 4106, 4513),
    ("tabs/growatt.py", 4515, 5266),
    ("tabs/octopus.py", 5269, 5946),
    ("ui/palette.py", 5950, 6030),
    ("ui/styles.py", 6033, 6478),
    ("ui/chart_utils.py", 6480, 6827),
    ("tabs/combined.py", 6829, 7043),
    ("tabs/battery_analysis.py", 7047, 7498),
    ("tabs/analytics.py", 7502, 8521),
    ("tabs/forecasts.py", 8523, 9770),
    ("dialogs/map_picker.py", 9774, 10812),
    ("dialogs/about_history.py", 10816, 10920),
    ("tabs/device_import_costs.py", 10924, 11244),
    ("tabs/octopus_live.py", 11248, 12034),
    ("tabs/tasmota.py", 12036, 13408),
    ("planner/core.py", 13414, 13985),
    ("tabs/smart_advisor.py", 13989, 15471),
    ("tabs/optimiser.py", 15475, 19669),
    ("planner/maximiser.py", 19674, 20203),
    ("tabs/registry.py", 20207, 20229),
    ("tabs/parameters.py", 20232, 21384),
    ("tabs/database_viewer.py", 21386, 21554),
    ("tabs/console.py", 21556, 21697),
    ("tabs/license.py", 21699, 21718),
    ("tabs/export_tab.py", 21722, 22288),
    ("modbus/command_sim.py", 22292, 23013),
    ("tabs/connectivity.py", 23015, 23730),
    ("ui/tab_bar.py", 23732, 23945),
    ("main_window.py", 23949, 24843),
    ("app_entry.py", 24847, 24855),
]

DEPS_LINES = (22, 58)


def main() -> None:
    lines = SRC.read_text(encoding="utf-8").splitlines(keepends=True)
    PKG.mkdir(exist_ok=True)

    deps_body = "".join(lines[DEPS_LINES[0] - 1 : DEPS_LINES[1]])
    (PKG / "deps.py").write_text(
        '"""Third-party and stdlib imports shared across the dashboard."""\n'
        + deps_body,
        encoding="utf-8",
    )

    (PKG / "paths.py").write_text(
        '''"""Filesystem paths for repo-root assets (venv, _ui_assets, etc.)."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
UI_ASSETS_DIR = REPO_ROOT / "_ui_assets"
ASSETS_DIR = REPO_ROOT / "assets"
''',
        encoding="utf-8",
    )

    for rel, start, end in SECTIONS:
        out = PKG / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        chunk = "".join(lines[start - 1 : end])
        chunk = chunk.replace(
            "Path(__file__).resolve().parent / \"_ui_assets\"",
            "UI_ASSETS_DIR  # was Path(__file__).parent / _ui_assets",
        )
        chunk = chunk.replace(
            'Path(__file__).resolve().parent / "assets"',
            "ASSETS_DIR",
        )
        header = f'"""\nEnergy Dashboard — `{rel}` (split from EnergyDashboard2.py).\n"""\nfrom __future__ import annotations\n\n'
        out.write_text(header + chunk, encoding="utf-8")

    for init_dir in [
        PKG,
        PKG / "content",
        PKG / "ui",
        PKG / "core",
        PKG / "db",
        PKG / "fetch",
        PKG / "tabs",
        PKG / "dialogs",
        PKG / "planner",
        PKG / "modbus",
    ]:
        init_dir.mkdir(parents=True, exist_ok=True)
        init_file = init_dir / "__init__.py"
        if not init_file.exists():
            init_file.write_text('"""Energy Dashboard package."""\n', encoding="utf-8")

    print(f"Wrote {len(SECTIONS) + 2} module files under {PKG}")


if __name__ == "__main__":
    main()
