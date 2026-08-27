"""Versioned SQL migrations for the jacob schema.

Plain numbered .sql files in db/migrations/, applied in order, each inside its
own transaction, recorded in jacob.schema_migrations. The same files run
unchanged against any environment's Postgres.

    python -m rag.ingest.migrate            # apply pending
    python -m rag.ingest.migrate --status   # show applied vs pending
"""
from __future__ import annotations

import sys
from pathlib import Path

import psycopg

import config

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent.parent / "db" / "migrations"


def _bootstrap(conn: psycopg.Connection) -> None:
    conn.execute("CREATE SCHEMA IF NOT EXISTS jacob")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS jacob.schema_migrations ("
        " version TEXT PRIMARY KEY,"
        " applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )


def main() -> None:
    status_only = "--status" in sys.argv
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    with psycopg.connect(config.DB_DSN) as conn:
        _bootstrap(conn)
        applied = {r[0] for r in conn.execute("SELECT version FROM jacob.schema_migrations")}
        for path in files:
            version = path.stem
            if version in applied:
                print(f"applied  {version}")
                continue
            if status_only:
                print(f"pending  {version}")
                continue
            with conn.transaction():
                conn.execute(path.read_text(encoding="utf-8"))
                conn.execute(
                    "INSERT INTO jacob.schema_migrations (version) VALUES (%s)", (version,)
                )
            print(f"applying {version} ✓")


if __name__ == "__main__":
    main()
