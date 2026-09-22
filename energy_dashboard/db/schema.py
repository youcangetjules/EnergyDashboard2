"""
Energy Dashboard — `db/schema.py` (split from EnergyDashboard2.py).
"""
from __future__ import annotations

from energy_dashboard.deps import *
from energy_dashboard.db.full_schema import apply_full_schema
from energy_dashboard.db.connect_probe import (
    DB_SETUP_TIMEOUT_S,
    mysql_connect,
    postgresql_connect,
)


def _safe_db_name(name: str) -> bool:
    return bool(name and re.fullmatch(r'[A-Za-z0-9_]+', name))


def setup_sqlite_schema(path: str) -> tuple[bool, str]:
    """Create parent dirs, SQLite file, and all logger tables."""
    path = (path or "").strip() or str(Path.home() / "energy_dashboard.db")
    try:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(p))
        try:
            apply_full_schema(conn, "sqlite")
        finally:
            conn.close()
        return True, f"SQLite: OK ({path})"
    except Exception as e:
        return False, f"SQLite: {e}"


def setup_mysql_schema(host: str, port: int, user: str, password: str, database: str) -> tuple[bool, str]:
    """CREATE DATABASE if needed, then create all logger tables."""
    database = (database or "").strip() or "energy"
    if not _safe_db_name(database):
        return False, "MySQL: DB name must be letters, numbers, underscore only"
    try:
        import pymysql
    except ImportError:
        return False, "MySQL: pymysql not installed (pip install pymysql)"
    try:
        conn = mysql_connect(
            host, port, user, password, autocommit=True, timeout=DB_SETUP_TIMEOUT_S,
        )
        try:
            with conn.cursor() as cur:
                cur.execute(f"CREATE DATABASE IF NOT EXISTS `{database}`")
        finally:
            conn.close()
        conn = mysql_connect(
            host, port, user, password, database, autocommit=True, timeout=DB_SETUP_TIMEOUT_S,
        )
        try:
            apply_full_schema(conn, "mysql")
        finally:
            conn.close()
        return True, f"MySQL: OK (DB `{database}` + tables)"
    except Exception as e:
        return False, f"MySQL: {e}"


def setup_postgresql_schema(host: str, port: int, user: str, password: str, database: str) -> tuple[bool, str]:
    """Create database if missing (connect via postgres/template1), then all logger tables."""
    database = (database or "").strip() or "powermon"
    if not _safe_db_name(database):
        return False, "PostgreSQL: DB name must be letters, numbers, underscore only"
    try:
        import psycopg2
        from psycopg2 import sql
    except ImportError:
        return False, "PostgreSQL: psycopg2 not installed (pip install psycopg2-binary)"

    try:
        conn = postgresql_connect(
            host, port, user, password, database, timeout=DB_SETUP_TIMEOUT_S,
        )
        try:
            conn.autocommit = True
            apply_full_schema(conn, "pg")
        finally:
            conn.close()
        return True, f"PostgreSQL: OK (existing DB `{database}` + tables)"
    except psycopg2.OperationalError as e:
        err = str(e).lower()
        if 'does not exist' not in err:
            return False, f"PostgreSQL: {e}"
    except Exception as e:
        return False, f"PostgreSQL: {e}"

    admin_conn = None
    for adm in ('postgres', 'template1'):
        try:
            admin_conn = postgresql_connect(
                host, port, user, password, adm, timeout=DB_SETUP_TIMEOUT_S,
            )
            break
        except Exception:
            continue
    if admin_conn is None:
        return False, "PostgreSQL: cannot connect to `postgres` or `template1` to create database"
    try:
        admin_conn.autocommit = True
        with admin_conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (database,))
            if not cur.fetchone():
                cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database)))
    finally:
        admin_conn.close()

    try:
        conn = postgresql_connect(
            host, port, user, password, database, timeout=DB_SETUP_TIMEOUT_S,
        )
        try:
            conn.autocommit = True
            apply_full_schema(conn, "pg")
        finally:
            conn.close()
        return True, f"PostgreSQL: OK (created DB `{database}` + tables)"
    except Exception as e:
        return False, f"PostgreSQL: {e}"


__all__ = [n for n in globals() if not n.startswith('__')]
