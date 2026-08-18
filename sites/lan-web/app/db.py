"""Thin MySQL helper — connection-per-call, fine at LAN scale.

If load ever warrants it, swap _connect() for a pool; the query helpers
keep the same signatures."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterable, Optional

import pymysql
import pymysql.cursors

from .config import settings


def _connect():
    return pymysql.connect(
        host=settings.db_host,
        port=settings.db_port,
        user=settings.db_user,
        password=settings.db_password,
        database=settings.db_name,
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
    )


@contextmanager
def get_conn():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def query_one(sql: str, params: Optional[Iterable[Any]] = None) -> Optional[dict]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params or ())
        return cur.fetchone()


def query_all(sql: str, params: Optional[Iterable[Any]] = None) -> list[dict]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params or ())
        return list(cur.fetchall())


def execute(sql: str, params: Optional[Iterable[Any]] = None) -> int:
    """Run a write; returns lastrowid."""
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, params or ())
        return cur.lastrowid


Statement = tuple[str, Optional[Iterable[Any]]]


def execute_all(statements: Iterable[Statement]) -> int:
    """Run several writes in ONE transaction; returns the first one's lastrowid.

    execute() takes a connection per call, so a mutation and the audit row
    recording it were two transactions and the second could fail alone —
    leaving a change nothing accounts for. Pair them through here instead."""
    first = None
    with get_conn() as conn, conn.cursor() as cur:
        for sql, params in statements:
            cur.execute(sql, params or ())
            if first is None:
                first = cur.lastrowid
    return first
