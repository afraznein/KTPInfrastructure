"""Staff action log — who ticked, retitled or promoted what.

Separate from audit.py, which records match-result changes and can undo them.
Nothing here is reversible; it exists so an operator decision has a record."""
from __future__ import annotations

from . import db


def log(actor, actor_name, action: str, target=None, old=None, new=None) -> None:
    """One row per staff decision. Truncates to the column widths rather than
    letting a long label fail the insert and lose the record."""
    db.execute(
        "INSERT INTO lan_admin_audit (actor, actor_name, action, target, old_value, new_value) "
        "VALUES (%s,%s,%s,%s,%s,%s)",
        (int(actor),
         str(actor_name)[:96] if actor_name else None,
         action[:48],
         str(target)[:160] if target else None,
         None if old is None else str(old),
         None if new is None else str(new)),
    )


def log_request(request, action: str, target=None, old=None, new=None) -> None:
    """Same, attributed to whoever is signed in on this request."""
    from .auth import SESSION_ID, SESSION_NAME
    log(request.session.get(SESSION_ID), request.session.get(SESSION_NAME),
        action, target, old, new)


def recent(limit: int = 50, offset: int = 0) -> list[dict]:
    return db.query_all(
        "SELECT id, actor, actor_name, action, target, old_value, new_value, at "
        "FROM lan_admin_audit ORDER BY id DESC LIMIT %s OFFSET %s",
        (int(limit), int(offset)),
    )


def count() -> int:
    r = db.query_one("SELECT COUNT(*) AS n FROM lan_admin_audit")
    return int(r["n"]) if r else 0
