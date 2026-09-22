"""
Probe database backends for connectivity and read/write access.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

# Unreachable MySQL/Postgres otherwise wait on the OS TCP SYN timeout
# (~1–2 minutes). Keep this short so a down server cannot freeze the GUI.
DB_CONNECT_TIMEOUT_S = 3
DB_SETUP_TIMEOUT_S = 8


def mysql_connect(
    host,
    port,
    user,
    password,
    database=None,
    *,
    autocommit: bool = False,
    timeout: int | float | None = None,
):
    """Open a MySQL connection with a bounded TCP wait."""
    import pymysql

    t = int(timeout if timeout is not None else DB_CONNECT_TIMEOUT_S)
    kw = {
        "host": host or "localhost",
        "port": int(port or 3306),
        "user": user or "",
        "password": password or "",
        "charset": "utf8mb4",
        "autocommit": autocommit,
        "connect_timeout": t,
    }
    if database:
        kw["database"] = database
    return pymysql.connect(**kw)


def postgresql_connect(
    host,
    port,
    user,
    password,
    dbname,
    *,
    autocommit: bool = False,
    timeout: int | float | None = None,
):
    """Open a PostgreSQL connection with a bounded TCP wait."""
    import psycopg2

    t = int(timeout if timeout is not None else DB_CONNECT_TIMEOUT_S)
    conn = psycopg2.connect(
        host=host or "localhost",
        port=int(port or 5432),
        dbname=dbname,
        user=user or "",
        password=password or "",
        connect_timeout=max(1, t),
    )
    if autocommit:
        conn.autocommit = True
    return conn


def _access_from_write_probe(probe_write_fn) -> str:
    try:
        probe_write_fn()
        return "read+write"
    except Exception:
        return "read-only"


def probe_sqlite(path: str) -> tuple[bool, dict | str]:
    path = (path or "").strip() or str(Path.home() / "energy_dashboard.db")
    try:
        p = Path(path)
        if not p.parent.exists():
            p.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(p))
        try:
            conn.execute("SELECT 1")

            def _write():
                conn.execute("BEGIN")
                conn.execute("CREATE TEMP TABLE _pm_probe (x INTEGER)")
                conn.execute("INSERT INTO _pm_probe VALUES (1)")
                conn.execute("ROLLBACK")

            access = _access_from_write_probe(_write)
        finally:
            conn.close()
        file_rw = os.access(str(p), os.W_OK) if p.exists() else True
        if access == "read+write" and not file_rw:
            access = "read-only (file not writable)"
        return True, {
            "host": "local file",
            "port": "—",
            "user": "—",
            "db": path,
            "access": access,
        }
    except Exception as e:
        return False, str(e)


def probe_mysql(host, port, user, password, database) -> tuple[bool, dict | str]:
    try:
        import pymysql
    except ImportError:
        return False, "pymysql not installed (pip install pymysql)"
    host = host or "localhost"
    database = (database or "").strip() or "energy"
    try:
        conn = mysql_connect(host, port, user, password, database)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")

                def _write():
                    cur.execute("START TRANSACTION")
                    cur.execute("CREATE TEMPORARY TABLE _pm_probe (x INT)")
                    cur.execute("INSERT INTO _pm_probe VALUES (1)")
                    conn.rollback()

                access = _access_from_write_probe(_write)
        finally:
            conn.close()
        return True, {
            "host": host,
            "port": int(port),
            "user": user or "—",
            "db": database,
            "access": access,
        }
    except Exception as e:
        return False, str(e)


def probe_postgresql(host, port, user, password, database) -> tuple[bool, dict | str]:
    try:
        import psycopg2
    except ImportError:
        return False, "psycopg2 not installed (pip install psycopg2-binary)"
    host = host or "localhost"
    database = (database or "").strip() or "powermon"
    try:
        conn = postgresql_connect(host, port, user, password, database)
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT current_user")
                db_user = (cur.fetchone() or [user or "—"])[0]

                def _write():
                    cur.execute("SAVEPOINT pm_probe")
                    cur.execute("CREATE TEMP TABLE _pm_probe (x INTEGER)")
                    cur.execute("INSERT INTO _pm_probe VALUES (1)")
                    cur.execute("ROLLBACK TO SAVEPOINT pm_probe")
                    cur.execute("RELEASE SAVEPOINT pm_probe")

                try:
                    access = _access_from_write_probe(_write)
                except Exception:
                    conn.rollback()
                    access = "read-only"
        finally:
            conn.close()
        return True, {
            "host": host,
            "port": int(port),
            "user": db_user,
            "db": database,
            "access": access,
        }
    except Exception as e:
        return False, str(e)


def format_probe_summary(info: dict) -> str:
    """One-line status for row label / summary bar."""
    access = info.get("access", "—")
    if info.get("host") == "local file":
        return f"local file · {access} · {info['db']}"
    port = info.get("port", "—")
    user = info.get("user", "—")
    host = info.get("host", "—")
    db = info.get("db", "—")
    return f"port {port}, username {user} with {access} ({host}/{db})"


def format_probe_tooltip(info: dict) -> str:
    lines = [
        f"Host: {info.get('host', '—')}",
        f"Port: {info.get('port', '—')}",
        f"Username: {info.get('user', '—')}",
        f"Database: {info.get('db', '—')}",
        f"Access: {info.get('access', '—')}",
    ]
    return "\n".join(lines)


def _expected_logger_tables() -> list[str]:
    from energy_dashboard.db.full_schema import TABLE_SUMMARIES

    return [name for name, _blurb in TABLE_SUMMARIES]


def _classify_connect_error(err: str) -> str:
    e = (err or "").lower()
    if "password authentication failed" in e or "access denied" in e:
        return "auth"
    if "unknown database" in e:
        return "no_db"
    if "does not exist" in e and "database" in e:
        return "no_db"
    if "timeout" in e or "timed out" in e:
        return "timeout"
    if (
        "refused" in e
        or "could not connect" in e
        or "name or service not known" in e
        or "no route to host" in e
        or "network is unreachable" in e
    ):
        return "unreachable"
    if "no such file" in e or "unable to open database file" in e:
        return "no_file"
    return "other"


def _short_connect_reason(err: str) -> str:
    kind = _classify_connect_error(err)
    if kind == "auth":
        return "username or password rejected"
    if kind == "no_db":
        return "named database does not exist"
    if kind == "timeout":
        return "server did not answer in time"
    if kind == "unreachable":
        return "host or port not reachable"
    if kind == "no_file":
        return "SQLite file not found"
    text = (err or "").strip() or "unknown error"
    return text.splitlines()[0][:180]


def is_table_privilege_error(err: str) -> bool:
    """True when the engine answered, but this login cannot use a table."""
    e = (err or "").lower()
    return (
        "permission denied for table" in e
        or "permission denied for relation" in e
        or "insufficientprivilege" in e
        or "command denied to user" in e
        or "access denied for table" in e
    )


def _pg_table_can_select_insert(conn, name: str) -> tuple[bool, bool]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT has_table_privilege(%s, 'SELECT'), "
            "has_table_privilege(%s, 'INSERT')",
            (name, name),
        )
        row = cur.fetchone() or (False, False)
    return bool(row[0]), bool(row[1])


def _try_select_one(conn, dialect: str, name: str) -> bool:
    try:
        if dialect == "sqlite":
            conn.execute(f'SELECT 1 FROM "{name}" LIMIT 1')
            return True
        with conn.cursor() as cur:
            if dialect == "mysql":
                cur.execute(f"SELECT 1 FROM `{name}` LIMIT 1")
            else:
                cur.execute(f'SELECT 1 FROM "{name}" LIMIT 1')
        return True
    except Exception:
        if dialect == "pg":
            try:
                conn.rollback()
            except Exception:
                pass
        return False


def _table_can_select_insert(conn, dialect: str, name: str) -> tuple[bool, bool]:
    """(can_select, can_insert) for a logger table this login can see."""
    if dialect == "pg":
        try:
            return _pg_table_can_select_insert(conn, name)
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            return False, False
    ok_sel = _try_select_one(conn, dialect, name)
    # SQLite/MySQL: if SELECT works, treat INSERT as unknown-ok unless the
    # connect probe already marked the session read-only (checked by caller).
    return ok_sel, ok_sel


def _list_tables(conn, dialect: str) -> set[str]:
    names: set[str] = set()
    if dialect == "sqlite":
        cur = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        rows = cur.fetchall()
    elif dialect == "mysql":
        with conn.cursor() as cur:
            cur.execute("SHOW TABLES")
            rows = cur.fetchall()
    else:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
            )
            rows = cur.fetchall()
    for row in rows or ():
        if not row:
            continue
        names.add(str(row[0]))
    return names


def _tables_stage(conn, dialect: str) -> tuple[bool, str, str]:
    """Tables exist *and* this login can SELECT/INSERT them."""
    present = _list_tables(conn, dialect)
    expected = _expected_logger_tables()
    missing = [name for name in expected if name not in present]
    denied = []
    readonly = []
    for name in expected:
        if name not in present:
            continue
        can_sel, can_ins = _table_can_select_insert(conn, dialect, name)
        if not can_sel:
            denied.append(name)
        elif not can_ins:
            readonly.append(name)
    total = len(expected)
    usable = total - len(missing) - len(denied) - len(readonly)
    if denied:
        parts = ["cannot read: " + ", ".join(denied)]
        if missing:
            parts.append("not created yet: " + ", ".join(missing))
        if readonly:
            parts.append("read-only: " + ", ".join(readonly))
        tip = (
            "This login can connect, but the logger tables are not usable ("
            + "; ".join(parts)
            + "). Creating a table does not grant access to it, and this login "
            "cannot grant itself any. Run the SQL on the right by hand as the "
            "database owner — it creates the tables and includes the GRANT "
            "lines for this login."
        )
        return False, f"Tables not readable ({usable}/{total})", tip
    if readonly:
        tip = (
            "This database login can read but not write: "
            + ", ".join(readonly)
            + ". Ingest will stay at zero until INSERT is granted."
        )
        return False, f"Tables read-only ({usable}/{total})", tip
    if missing:
        tip = "Missing: " + ", ".join(missing)
        return False, f"Tables not connected ({usable}/{total})", tip
    return True, f"Tables connected ({usable}/{total})", "All logger tables are present and usable."


def _stage_result(
    *,
    engine: str,
    seen_ok: bool,
    seen_tip: str,
    conn_ok: bool,
    conn_tip: str,
    tables_ok: bool,
    tables_label: str,
    tables_tip: str,
    summary: str,
    conn_detail=None,
) -> dict:
    seen_label = f"{engine} DB seen" if seen_ok else f"{engine} DB not seen"
    if conn_ok:
        conn_label = "Database connected"
    else:
        conn_label = "Database not connected"
    return {
        "engine": engine,
        "seen_ok": seen_ok,
        "seen_label": seen_label,
        "seen_tip": seen_tip,
        "conn_ok": conn_ok,
        "conn_label": conn_label,
        "conn_tip": conn_tip,
        "tables_ok": tables_ok,
        "tables_label": tables_label,
        "tables_tip": tables_tip,
        "summary": summary,
        "ok": bool(seen_ok and conn_ok and tables_ok),
        "conn_detail": conn_detail,
    }


def _not_connected_tables() -> tuple[bool, str, str]:
    return False, "Tables not connected", "Not checked — database is not connected."


def probe_engine_stages(engine: str, **kwargs) -> dict:
    """Three Setup & Info checks: DB seen, connected, tables present."""
    if engine == "SQLite":
        return _probe_sqlite_stages(kwargs.get("path") or "")
    if engine == "MySQL":
        return _probe_mysql_stages(
            kwargs.get("host"),
            kwargs.get("port"),
            kwargs.get("user"),
            kwargs.get("password"),
            kwargs.get("database"),
        )
    return _probe_postgresql_stages(
        kwargs.get("host"),
        kwargs.get("port"),
        kwargs.get("user"),
        kwargs.get("password"),
        kwargs.get("database"),
    )


def _probe_sqlite_stages(path: str) -> dict:
    path = (path or "").strip() or str(Path.home() / "energy_dashboard.db")
    p = Path(path)
    tables_ok, tables_label, tables_tip = _not_connected_tables()
    if not p.is_file():
        tip = f"No SQLite file at {path}."
        return _stage_result(
            engine="SQLite",
            seen_ok=False,
            seen_tip=tip,
            conn_ok=False,
            conn_tip="Not connected — the file is missing. Use Setup Database to create it.",
            tables_ok=tables_ok,
            tables_label=tables_label,
            tables_tip=tables_tip,
            summary="SQLite: DB not seen — file missing",
        )
    ok, detail = probe_sqlite(path)
    if not ok:
        reason = _short_connect_reason(str(detail))
        return _stage_result(
            engine="SQLite",
            seen_ok=True,
            seen_tip=path,
            conn_ok=False,
            conn_tip=str(detail),
            tables_ok=tables_ok,
            tables_label=tables_label,
            tables_tip=tables_tip,
            summary=f"SQLite: DB seen · not connected — {reason}",
        )
    conn = sqlite3.connect(path)
    try:
        tables_ok, tables_label, tables_tip = _tables_stage(conn, "sqlite")
    finally:
        conn.close()
    extra = ""
    if isinstance(detail, dict) and str(detail.get("access", "")).startswith("read-only"):
        extra = " (read-only)"
    return _stage_result(
        engine="SQLite",
        seen_ok=True,
        seen_tip=path,
        conn_ok=True,
        conn_tip=format_probe_tooltip(detail) if isinstance(detail, dict) else str(detail),
        tables_ok=tables_ok,
        tables_label=tables_label,
        tables_tip=tables_tip,
        summary=(
            f"SQLite: DB seen · connected{extra} · {tables_label.lower()}"
        ),
        conn_detail=detail,
    )


def _probe_mysql_stages(host, port, user, password, database) -> dict:
    try:
        import pymysql  # noqa: F401
    except ImportError:
        tip = "pymysql not installed (pip install pymysql)"
        t_ok, t_lbl, t_tip = _not_connected_tables()
        return _stage_result(
            engine="MySQL",
            seen_ok=False,
            seen_tip=tip,
            conn_ok=False,
            conn_tip=tip,
            tables_ok=t_ok,
            tables_label=t_lbl,
            tables_tip=t_tip,
            summary=f"MySQL: DB not seen — {tip}",
        )
    host = host or "localhost"
    database = (database or "").strip() or "energy"
    where = f"{host}/{database}"
    t_ok, t_lbl, t_tip = _not_connected_tables()
    ok, detail = probe_mysql(host, port, user, password, database)
    if ok:
        conn = mysql_connect(host, port, user, password, database)
        try:
            t_ok, t_lbl, t_tip = _tables_stage(conn, "mysql")
        finally:
            conn.close()
        extra = ""
        if isinstance(detail, dict) and str(detail.get("access", "")).startswith("read-only"):
            extra = " (read-only)"
        return _stage_result(
            engine="MySQL",
            seen_ok=True,
            seen_tip=where,
            conn_ok=True,
            conn_tip=format_probe_tooltip(detail) if isinstance(detail, dict) else str(detail),
            tables_ok=t_ok,
            tables_label=t_lbl,
            tables_tip=t_tip,
            summary=f"MySQL: DB seen · connected{extra} · {t_lbl.lower()}",
            conn_detail=detail,
        )
    err = str(detail)
    kind = _classify_connect_error(err)
    reason = _short_connect_reason(err)
    seen_ok = kind in ("auth", "no_db") or kind == "other"
    if kind == "no_db":
        seen_ok = False
        seen_tip = f"MySQL server answered; database '{database}' is not on {host}."
    elif kind == "auth":
        seen_ok = True
        seen_tip = (
            f"MySQL server at {host} answered. Login failed, so the named "
            f"database '{database}' was not confirmed."
        )
    elif kind in ("timeout", "unreachable"):
        seen_ok = False
        seen_tip = f"No MySQL server at {host}:{port} — {reason}."
    else:
        seen_ok = False
        seen_tip = err
    return _stage_result(
        engine="MySQL",
        seen_ok=seen_ok,
        seen_tip=seen_tip,
        conn_ok=False,
        conn_tip=err,
        tables_ok=t_ok,
        tables_label=t_lbl,
        tables_tip=t_tip,
        summary=f"MySQL: {('DB seen' if seen_ok else 'DB not seen')} · not connected — {reason}",
    )


def _probe_postgresql_stages(host, port, user, password, database) -> dict:
    try:
        import psycopg2  # noqa: F401
    except ImportError:
        tip = "psycopg2 not installed (pip install psycopg2-binary)"
        t_ok, t_lbl, t_tip = _not_connected_tables()
        return _stage_result(
            engine="PostgreSQL",
            seen_ok=False,
            seen_tip=tip,
            conn_ok=False,
            conn_tip=tip,
            tables_ok=t_ok,
            tables_label=t_lbl,
            tables_tip=t_tip,
            summary=f"PostgreSQL: DB not seen — {tip}",
        )
    host = host or "localhost"
    database = (database or "").strip() or "powermon"
    where = f"{host}/{database}"
    t_ok, t_lbl, t_tip = _not_connected_tables()
    ok, detail = probe_postgresql(host, port, user, password, database)
    if ok:
        conn = postgresql_connect(host, port, user, password, database)
        try:
            t_ok, t_lbl, t_tip = _tables_stage(conn, "pg")
        finally:
            conn.close()
        extra = ""
        if isinstance(detail, dict) and str(detail.get("access", "")).startswith("read-only"):
            extra = " (read-only)"
        return _stage_result(
            engine="PostgreSQL",
            seen_ok=True,
            seen_tip=where,
            conn_ok=True,
            conn_tip=format_probe_tooltip(detail) if isinstance(detail, dict) else str(detail),
            tables_ok=t_ok,
            tables_label=t_lbl,
            tables_tip=t_tip,
            summary=f"PostgreSQL: DB seen · connected{extra} · {t_lbl.lower()}",
            conn_detail=detail,
        )
    err = str(detail)
    kind = _classify_connect_error(err)
    reason = _short_connect_reason(err)
    if kind == "no_db":
        seen_ok = False
        seen_tip = f"PostgreSQL server answered; database '{database}' does not exist."
    elif kind == "auth":
        seen_ok = True
        seen_tip = (
            f"PostgreSQL server at {host}:{port} answered. Login failed for "
            f"user '{user or '—'}', so database '{database}' was not opened."
        )
    elif kind in ("timeout", "unreachable"):
        seen_ok = False
        seen_tip = f"No PostgreSQL server at {host}:{port} — {reason}."
    else:
        seen_ok = False
        seen_tip = err
    return _stage_result(
        engine="PostgreSQL",
        seen_ok=seen_ok,
        seen_tip=seen_tip,
        conn_ok=False,
        conn_tip=err,
        tables_ok=t_ok,
        tables_label=t_lbl,
        tables_tip=t_tip,
        summary=(
            f"PostgreSQL: {('DB seen' if seen_ok else 'DB not seen')} "
            f"· not connected — {reason}"
        ),
    )


def check_sqlite_file_exists(path: str) -> tuple[bool, str]:
    """Return whether the SQLite file already exists on disk."""
    path = (path or "").strip() or str(Path.home() / "energy_dashboard.db")
    p = Path(path)
    if p.is_file():
        return True, path
    return False, f"file not found: {path}"


def check_mysql_database_exists(host, port, user, password, database) -> tuple[bool, str]:
    """Return whether the named MySQL database exists on the server."""
    try:
        import pymysql
    except ImportError:
        return False, "pymysql not installed"
    host = host or "localhost"
    database = (database or "").strip() or "energy"
    try:
        conn = mysql_connect(host, port, user, password)
        try:
            with conn.cursor() as cur:
                cur.execute("SHOW DATABASES LIKE %s", (database,))
                row = cur.fetchone()
            if row:
                return True, f"{host}/{database}"
            return False, f"database '{database}' not found on {host}"
        finally:
            conn.close()
    except Exception as e:
        return False, str(e)


def check_postgresql_database_exists(host, port, user, password, database) -> tuple[bool, str]:
    """Return whether the named PostgreSQL database exists on the server."""
    try:
        import psycopg2
    except ImportError:
        return False, "psycopg2 not installed"
    host = host or "localhost"
    database = (database or "").strip() or "powermon"
    try:
        conn = postgresql_connect(host, port, user, password, "postgres")
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database,))
                row = cur.fetchone()
            if row:
                return True, f"{host}/{database}"
            return False, f"database '{database}' not found on {host}"
        finally:
            conn.close()
    except Exception as e:
        return False, str(e)
