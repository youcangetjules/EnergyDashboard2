"""Latest number in one logger column, for an alarm signal.

The table and field come from Alarm defs. Only logger tables and columns
declared in the schema are accepted, so the SQL cannot name anything else.
"""
from __future__ import annotations

import re

from energy_dashboard.db.full_schema import (
    TABLE_ORDER_COL,
    TABLE_SUMMARIES,
    logger_table_columns,
)

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TABLES = {name for name, _blurb in TABLE_SUMMARIES}


def latest_numeric(data_logger, table: str, field: str) -> float | None:
    """Newest number in ``table.field``, or None when it cannot be read.

    "Newest" is the latest row by that table's time column (or ``id``).
    A missing table, a blank column, or a closed database is None — the
    alarm then says the field has no number, and does not invent one.
    """
    table = str(table or "").strip()
    field = str(field or "").strip()
    if table not in _TABLES or not _IDENT.match(table) or not _IDENT.match(field):
        return None
    columns = logger_table_columns().get(table) or ()
    if field not in columns:
        return None
    order = TABLE_ORDER_COL.get(table, "id")
    if order not in columns:
        order = "id" if "id" in columns else field
    if not _IDENT.match(order):
        return None
    backend = None
    try:
        backend = data_logger._primary_storage_backend()
    except Exception:
        return None
    if not backend:
        return None
    sql = (
        f"SELECT {field} FROM {table} "
        f"WHERE {field} IS NOT NULL "
        f"ORDER BY {order} DESC LIMIT 1"
    )
    try:
        frame = data_logger._query_pl(backend, sql, [])
    except Exception:
        return None
    if frame is None or getattr(frame, "height", 0) < 1:
        return None
    try:
        raw = frame.to_series(0)[0]
    except Exception:
        return None
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None
