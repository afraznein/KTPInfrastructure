"""Station board data access. Table-missing returns empty (pre-migration safe)."""
from __future__ import annotations


def get_stations() -> list[dict]:
    from . import db
    try:
        return db.query_all("SELECT * FROM lan_stations ORDER BY sort_order, id")
    except Exception:
        return []
