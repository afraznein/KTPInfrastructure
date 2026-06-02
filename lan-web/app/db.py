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
