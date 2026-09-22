"""One CREATE-ALL script per database engine.

Setup Database and the Setup & Info SQL pane use the same statement list as
DataLogger ``_ensure_*``, so a new logger table cannot be missed on first
setup. Statements are ``CREATE … IF NOT EXISTS`` — existing rows stay.
"""
from __future__ import annotations

DIALECTS = ("sqlite", "mysql", "pg")

_ENGINE_TITLE = {
    "sqlite": "SQLite",
    "mysql": "MySQL",
    "pg": "PostgreSQL",
}

# Shown beside the CREATE script. Keep in sync with dialect_statements().
TABLE_SUMMARIES: tuple[tuple[str, str], ...] = (
    ("growatt_readings", "inverter SOC and power (kW / today kWh)"),
    ("tasmota_readings", "Tasmota plug / CT watts each poll"),
    ("tasmota_devices", "one row per Tasmota IP (last seen)"),
    ("octopus_readings", "half-hour import / export from the meter"),
    ("solar_forecast_snapshots", "what the solar forecast said at fetch time"),
    ("agile_price_snapshots", "Agile import / export slot prices"),
    ("agile_year_daily", "Agile Year daily high / low / average"),
    ("growatt_mix_chart", "MIX 5-minute chart slots"),
    ("optimiser_shadow_plans", "nightly frozen optimiser plans"),
    ("optimiser_shadow_scores", "next-day score of those plans"),
    ("connectivity_events", "Connectivity Status history"),
    ("pv_string_charge", "2-minute string PV and charge lots"),
)


def _pick(mod, stem: str, dialect: str):
    if dialect == "sqlite":
        return getattr(mod, stem)
    suffix = "_MY" if dialect == "mysql" else "_PG"
    return getattr(mod, f"{stem}{suffix}")


def dialect_statements(dialect: str) -> tuple[str, ...]:
    """CREATE TABLE / INDEX statements for one engine, in apply order."""
    if dialect not in DIALECTS:
        raise ValueError(f"Unknown database dialect: {dialect!r}")
    from energy_dashboard.db import agile_year_daily as ay
    from energy_dashboard.db import connectivity_events as ce
    from energy_dashboard.db import logger as lg
    from energy_dashboard.db import mix_chart as mc
    from energy_dashboard.db import pv_string_charge as pv
    from energy_dashboard.db import shadow_trial as st

    stmts = (
        _pick(lg, "_GROWATT_DDL", dialect),
        _pick(lg, "_TASMOTA_DDL", dialect),
        _pick(lg, "_TASMOTA_DEVICES_DDL", dialect),
        _pick(lg, "_OCTOPUS_DDL", dialect),
        _pick(lg, "_SOLAR_FC_DDL", dialect),
        _pick(lg, "_AGILE_FC_DDL", dialect),
        _pick(ay, "_AGILE_YEAR_DAILY_DDL", dialect),
        *ay._AGILE_YEAR_DAILY_IDX,
        _pick(mc, "_GROWATT_MIX_CHART_DDL", dialect),
        *mc._GROWATT_MIX_CHART_IDX,
        _pick(st, "_SHADOW_PLAN_DDL", dialect),
        _pick(st, "_SHADOW_SCORE_DDL", dialect),
        *lg._SOLAR_FC_IDX_DDL,
        *lg._AGILE_FC_IDX_DDL,
        _pick(ce, "_CONNECTIVITY_EVENTS_DDL", dialect),
        *ce._CONNECTIVITY_EVENTS_IDX,
        _pick(pv, "_PV_STRING_CHARGE_DDL", dialect),
    )
    return tuple(str(s).strip() for s in stmts)


def _quote_ident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def grant_statements(role: str) -> tuple[str, ...]:
    """PostgreSQL GRANTs the dashboard login needs on the logger tables.

    ``SELECT`` for charts, ``INSERT`` for logging, ``UPDATE`` for the
    upserts (``ON CONFLICT DO UPDATE``), ``DELETE`` for ring-buffer
    retention. ``SERIAL`` id columns also need their sequence.
    """
    role_sql = _quote_ident(role)
    serial_tables = {
        name
        for name, stmt in zip(
            (n for n, _b in TABLE_SUMMARIES), _table_create_statements("pg"),
        )
        if "SERIAL PRIMARY KEY" in stmt
    }
    out = []
    for name, _blurb in TABLE_SUMMARIES:
        out.append(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON "
            f"{_quote_ident(name)} TO {role_sql}"
        )
        if name in serial_tables:
            out.append(
                f"GRANT USAGE, SELECT ON SEQUENCE "
                f"{_quote_ident(name + '_id_seq')} TO {role_sql}"
            )
    return tuple(out)


def _table_create_statements(dialect: str) -> tuple[str, ...]:
    """CREATE TABLE statements only, in ``TABLE_SUMMARIES`` order."""
    by_name = {}
    for stmt in dialect_statements(dialect):
        for name, _blurb in TABLE_SUMMARIES:
            if f"CREATE TABLE IF NOT EXISTS {name} " in f"{stmt} ":
                by_name[name] = stmt
    return tuple(by_name.get(n, "") for n, _b in TABLE_SUMMARIES)


def schema_script(dialect: str, *, grant_role: str | None = None) -> str:
    """Full SQL text for the Setup & Info viewer and Copy SQL."""
    title = _ENGINE_TITLE[dialect]
    names = ", ".join(name for name, _blurb in TABLE_SUMMARIES)
    body = "\n\n".join(f"{stmt};" for stmt in dialect_statements(dialect))
    if dialect != "pg":
        header = (
            f"-- Energy Dashboard — {title} CREATE for all logger tables\n"
            "-- Setup Database runs this (CREATE IF NOT EXISTS; existing rows stay).\n"
            f"-- Tables: {names}\n"
        )
        return f"{header}\n{body}\n"

    role = (grant_role or "").strip()
    header = (
        "-- Energy Dashboard — PostgreSQL setup for every logger table.\n"
        "-- Run this by hand as the database owner (psql, e.g. user postgres).\n"
        "-- The dashboard login, including the EMQX user, is not allowed to\n"
        "-- create tables or grant itself access.\n"
        "-- CREATE IF NOT EXISTS: tables already present keep their rows.\n"
        f"-- Tables: {names}\n"
    )
    if not role:
        return (
            f"{header}\n{body}\n\n"
            "-- Then grant the dashboard login access. Set the PostgreSQL user\n"
            "-- on the left first and this script will list the GRANT lines.\n"
        )
    grants = "\n".join(f"{stmt};" for stmt in grant_statements(role))
    return (
        f"{header}\n{body}\n\n"
        f"-- Access for the dashboard login ({role}). Creating the tables does\n"
        "-- not grant this. SELECT reads charts, INSERT logs, UPDATE covers the\n"
        "-- upserts, DELETE covers ring-buffer retention. Do not add CREATE.\n"
        f"{grants}\n"
    )


def schema_info_html(dialect: str) -> str:
    """Short caption + table list for the right-hand Setup pane."""
    title = _ENGINE_TITLE[dialect]
    names = ", ".join(f"<code>{name}</code>" for name, _blurb in TABLE_SUMMARIES)
    if dialect == "pg":
        lead = (
            f"<b>{title} — create-all SQL</b><br/>"
            "Run this by hand as the database owner. It creates every logger "
            "table and grants the dashboard login read/write on them. "
            "Tables already present keep their data.<br/>"
        )
    else:
        lead = (
            f"<b>{title} — create-all SQL</b><br/>"
            "Setup Database runs this script. "
            "Tables already present are left alone (including their data).<br/>"
        )
    return f"{lead}<b>Tables:</b> {names}"


def _exec(conn, dialect: str, stmt: str) -> None:
    if dialect == "sqlite":
        conn.execute(stmt)
        return
    with conn.cursor() as cur:
        cur.execute(stmt)


def apply_full_schema(conn, dialect: str) -> None:
    """Create every logger table/index on an open connection.

    ``pv_string_charge`` may drop and rebuild if an older wide-column table
    is still present (same rule as live logging).
    """
    for stmt in dialect_statements(dialect):
        _exec(conn, dialect, stmt)
    from energy_dashboard.db.pv_string_charge import ensure_pv_string_charge

    ensure_pv_string_charge(conn, dialect=dialect)
    if dialect == "sqlite":
        conn.commit()


__all__ = [
    "DIALECTS",
    "TABLE_SUMMARIES",
    "apply_full_schema",
    "dialect_statements",
    "grant_statements",
    "schema_info_html",
    "schema_script",
]
