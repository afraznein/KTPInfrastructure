#!/usr/bin/env python3
"""Apply lan-web SQL migrations idempotently.

Each file in migrations/*.sql runs once; applied filenames are recorded in
lan_schema_migrations so re-runs are no-ops. Statements are split on ';'
(safe here — migrations are pure DDL with no semicolons in data)."""
from __future__ import annotations

import sys
from pathlib import Path

import pymysql

from app.config import settings

MIG_DIR = Path(__file__).resolve().parent / "migrations"

TRACK_TABLE = """
CREATE TABLE IF NOT EXISTS lan_schema_migrations (
  filename   VARCHAR(255) NOT NULL PRIMARY KEY,
  applied_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
"""


def connect():
    return pymysql.connect(
        host=settings.db_host, port=settings.db_port,
        user=settings.db_user, password=settings.db_password,
        database=settings.db_name, charset="utf8mb4", autocommit=True,
    )


def main() -> int:
    conn = connect()
    with conn.cursor() as cur:
        cur.execute(TRACK_TABLE)
        cur.execute("SELECT filename FROM lan_schema_migrations")
        applied = {row[0] for row in cur.fetchall()}

    pending = [f for f in sorted(MIG_DIR.glob("*.sql")) if f.name not in applied]
    if not pending:
        print("No pending migrations.")
        return 0

    for f in pending:
        print(f"Applying {f.name} ...")
        statements = [s.strip() for s in f.read_text(encoding="utf-8").split(";") if s.strip()]
        with conn.cursor() as cur:
            for stmt in statements:
                cur.execute(stmt)
            cur.execute("INSERT INTO lan_schema_migrations (filename) VALUES (%s)", (f.name,))
        print(f"  OK ({len(statements)} statements)")

    print(f"Applied {len(pending)} migration(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
