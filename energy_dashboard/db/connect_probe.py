"""
Probe database backends for connectivity and read/write access.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path


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
        conn = pymysql.connect(
            host=host, port=int(port), user=user, password=password,
            database=database, charset="utf8mb4",
        )
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
        conn = psycopg2.connect(
            host=host, port=int(port), dbname=database,
            user=user, password=password,
        )
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
        conn = pymysql.connect(
            host=host,
            port=int(port),
            user=user,
            password=password,
            charset="utf8mb4",
        )
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
        conn = psycopg2.connect(
            host=host,
            port=int(port),
            dbname="postgres",
            user=user,
            password=password,
        )
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
