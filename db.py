"""PostgreSQL connection pool and migration runner for the Data Factory.

Connection settings come from the root .env (loaded by the caller). The DB runs
in Docker (docker-compose.yml) bound to 127.0.0.1:5433.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

ROOT = Path(__file__).resolve().parent
MIGRATIONS = ROOT / "db" / "migrations"

_pool: ThreadedConnectionPool | None = None


def dsn() -> str:
    host = os.getenv("POSTGRES_HOST", "127.0.0.1")
    port = os.getenv("POSTGRES_PORT", "5433")
    user = os.getenv("POSTGRES_USER", "factory")
    password = os.getenv("POSTGRES_PASSWORD", "factory_dev_pw")
    database = os.getenv("POSTGRES_DB", "datafactory")
    return f"host={host} port={port} user={user} password={password} dbname={database}"


def pool() -> ThreadedConnectionPool:
    global _pool
    if _pool is None:
        _pool = ThreadedConnectionPool(1, 10, dsn())
    return _pool


@contextmanager
def connect(dict_rows: bool = True):
    """Yield a connection from the pool; commit on success, rollback on error."""
    conn = pool().getconn()
    try:
        conn.cursor_factory = RealDictCursor if dict_rows else None
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool().putconn(conn)


def run_migrations() -> list[str]:
    """Apply every *.sql under db/migrations in order. Files are idempotent."""
    applied: list[str] = []
    files = sorted(MIGRATIONS.glob("*.sql"))
    with connect(dict_rows=False) as conn:
        with conn.cursor() as cur:
            for sql_file in files:
                cur.execute(sql_file.read_text(encoding="utf-8"))
                applied.append(sql_file.name)
    return applied


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv(ROOT / ".env")
    print("Applying migrations:", run_migrations())
    with connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT email, role, active FROM users ORDER BY id")
            for row in cur.fetchall():
                print(" seeded user:", dict(row))
