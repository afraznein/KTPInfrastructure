"""Staff action log — who ticked, retitled or promoted what.

Separate from audit.py, which records match-result changes and can undo them.
Nothing here is reversible; it exists so an operator decision has a record."""
from __future__ import annotations

from . import db


def stmt(actor, actor_name, action: str, target=None, old=None, new=None):
    """The insert as an unexecuted (sql, params), so a caller can run it in the
    same transaction as the mutation it records. Truncates to the column widths
    rather than letting a long label fail the insert and lose the record."""
    return (
        "INSERT INTO lan_admin_audit (actor, actor_name, action, target, old_value, new_value) "
        "VALUES (%s,%s,%s,%s,%s,%s)",
        (int(actor),
         str(actor_name)[:96] if actor_name else None,
         action[:48],
         str(target)[:160] if target else None,
         None if old is None else str(old),
         None if new is None else str(new)),
    )


def stmt_request(request, action: str, target=None, old=None, new=None):
    """Same, attributed to whoever is signed in on this request."""
    from .auth import SESSION_ID, SESSION_NAME
    return stmt(request.session.get(SESSION_ID), request.session.get(SESSION_NAME),
                action, target, old, new)


def log(actor, actor_name, action: str, target=None, old=None, new=None) -> None:
    """One row per staff decision, on its own. Prefer pairing stmt_request()
    with the mutation through db.execute_all() — this commits separately, so
    the mutation can land without it."""
    db.execute(*stmt(actor, actor_name, action, target, old, new))


def log_request(request, action: str, target=None, old=None, new=None) -> None:
    db.execute(*stmt_request(request, action, target, old, new))


def _filter(action: str = "", target: str = "") -> tuple[str, list]:
    """(WHERE clause, params) for the two questions this log gets asked: what
    happened to one thing, and every instance of one kind of decision.

    target is a prefix match, with LIKE's own wildcards escaped — a '%' typed
    into the filter box would otherwise match everything and read as no filter."""
    clauses, params = [], []
    if action:
        clauses.append("action=%s")
        params.append(action[:48])
    if target:
        esc = target[:160].replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
        clauses.append("target LIKE %s")
        params.append(esc + "%")
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def recent(limit: int = 50, offset: int = 0, action: str = "", target: str = "") -> list[dict]:
    where, params = _filter(action, target)
    return db.query_all(
        "SELECT id, actor, actor_name, action, target, old_value, new_value, at "
        f"FROM lan_admin_audit{where} ORDER BY id DESC LIMIT %s OFFSET %s",
        (*params, int(limit), int(offset)),
    )


def count(action: str = "", target: str = "") -> int:
    where, params = _filter(action, target)
    r = db.query_one(f"SELECT COUNT(*) AS n FROM lan_admin_audit{where}", tuple(params))
    return int(r["n"]) if r else 0


def action_counts() -> list[dict]:
    """Every action present, and how many. `action` is VARCHAR on purpose, so
    the filter's options come from the data rather than a constant that drifts."""
    return db.query_all(
        "SELECT action, COUNT(*) AS n FROM lan_admin_audit GROUP BY action ORDER BY action")
