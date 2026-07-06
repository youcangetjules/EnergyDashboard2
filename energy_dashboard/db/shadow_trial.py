"""
Energy Dashboard — `db/shadow_trial.py`.

Storage for the Shadow Trial: nightly frozen optimiser plans and the
daily four-way scores (actual vs shadow vs baseline vs perfect foresight).

Follows the `mix_chart.py` pattern: this module owns the DDL and the
cursor-level upsert helpers; `DataLogger` executes the DDL in its
`_ensure_*` methods and enqueues writes through its writer thread.
"""
from __future__ import annotations

# One row per London calendar day the frozen plan covers. `plan_json` holds
# the per-slot inputs AND the DP's chosen actions, so the evaluator never
# has to reconstruct what was knowable at freeze time.
_SHADOW_PLAN_DDL = """
CREATE TABLE IF NOT EXISTS optimiser_shadow_plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day_date TEXT NOT NULL UNIQUE,
    built_at TEXT NOT NULL,
    soc_start_pct REAL,
    soc_source TEXT,
    capacity_kwh REAL,
    eta REAL,
    max_kw REAL,
    soc_min_pct REAL,
    allow_export INTEGER,
    planned_cost_p REAL,
    slot_count INTEGER,
    plan_json TEXT NOT NULL
)"""

_SHADOW_SCORE_DDL = """
CREATE TABLE IF NOT EXISTS optimiser_shadow_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day_date TEXT NOT NULL UNIQUE,
    scored_at TEXT NOT NULL,
    octopus_complete INTEGER,
    telemetry_slots INTEGER,
    expected_slots INTEGER,
    soc_start_pct REAL,
    actual_cost_p REAL,
    shadow_cost_p REAL,
    baseline_cost_p REAL,
    perfect_cost_p REAL,
    actual_capture REAL,
    shadow_capture REAL,
    detail_json TEXT
)"""

_SHADOW_PLAN_DDL_PG = _SHADOW_PLAN_DDL.replace(
    "INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
_SHADOW_SCORE_DDL_PG = _SHADOW_SCORE_DDL.replace(
    "INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
_SHADOW_PLAN_DDL_MY = _SHADOW_PLAN_DDL.replace(
    "INTEGER PRIMARY KEY AUTOINCREMENT", "INTEGER PRIMARY KEY AUTO_INCREMENT"
).replace("plan_json TEXT NOT NULL", "plan_json MEDIUMTEXT NOT NULL")
_SHADOW_SCORE_DDL_MY = _SHADOW_SCORE_DDL.replace(
    "INTEGER PRIMARY KEY AUTOINCREMENT", "INTEGER PRIMARY KEY AUTO_INCREMENT"
).replace("detail_json TEXT", "detail_json MEDIUMTEXT")

_PLAN_COLS = (
    "day_date", "built_at", "soc_start_pct", "soc_source", "capacity_kwh",
    "eta", "max_kw", "soc_min_pct", "allow_export", "planned_cost_p",
    "slot_count", "plan_json",
)
_SCORE_COLS = (
    "day_date", "scored_at", "octopus_complete", "telemetry_slots",
    "expected_slots", "soc_start_pct", "actual_cost_p", "shadow_cost_p",
    "baseline_cost_p", "perfect_cost_p", "actual_capture", "shadow_capture",
    "detail_json",
)


def _upsert_sql(table: str, cols: tuple, key: str, dialect: str) -> str:
    ph = "?" if dialect == "sqlite" else "%s"
    collist = ", ".join(cols)
    values = ", ".join([ph] * len(cols))
    updates_src = [c for c in cols if c != key]
    if dialect == "mysql":
        updates = ", ".join(f"{c} = VALUES({c})" for c in updates_src)
        return (f"INSERT INTO {table} ({collist}) VALUES ({values}) "
                f"ON DUPLICATE KEY UPDATE {updates}")
    kw = "excluded" if dialect == "sqlite" else "EXCLUDED"
    updates = ", ".join(f"{c} = {kw}.{c}" for c in updates_src)
    return (f"INSERT INTO {table} ({collist}) VALUES ({values}) "
            f"ON CONFLICT({key}) DO UPDATE SET {updates}")


def upsert_shadow_plan(cur, dialect: str, row: dict) -> None:
    """UPSERT one frozen plan keyed on day_date. `row` keys = `_PLAN_COLS`."""
    sql = _upsert_sql("optimiser_shadow_plans", _PLAN_COLS, "day_date", dialect)
    cur.execute(sql, tuple(row.get(c) for c in _PLAN_COLS))


def upsert_shadow_score(cur, dialect: str, row: dict) -> None:
    """UPSERT one daily score keyed on day_date. `row` keys = `_SCORE_COLS`."""
    sql = _upsert_sql("optimiser_shadow_scores", _SCORE_COLS, "day_date", dialect)
    cur.execute(sql, tuple(row.get(c) for c in _SCORE_COLS))
