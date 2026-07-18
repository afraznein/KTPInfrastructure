"""Result change log + undo for Saturday matches and Sunday series.

Every report/edit captures the prior score state so staff can see who changed
what and roll a disputed result back to its previous value."""
from __future__ import annotations

from . import db


def log(scope: str, ref, action: str, prev: dict, new: dict, actor) -> None:
    """Record a result change. prev/new are {a, b, winner, status} snapshots."""
    db.execute(
        "INSERT INTO lan_result_audit "
        "(scope, ref, action, prev_a, prev_b, prev_winner, prev_status, "
        " new_a, new_b, new_winner, new_status, actor) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (scope, str(ref), action,
         prev.get("a"), prev.get("b"), prev.get("winner"), prev.get("status"),
         new.get("a"), new.get("b"), new.get("winner"), new.get("status"), actor),
    )


def recent(limit: int = 200) -> list[dict]:
    return db.query_all(
        "SELECT * FROM lan_result_audit ORDER BY id DESC LIMIT %s", (int(limit),)
    )


def undo(audit_id: int, actor) -> None:
    """Restore the match/series to the prior state captured in this audit row.

    Logs the reversal as its own 'undo' entry; for bracket undos, re-resolves
    downstream slots so dependent matches reflect the rollback."""
    a = db.query_one("SELECT * FROM lan_result_audit WHERE id=%s", (audit_id,))
    if not a:
        raise ValueError("No such audit entry.")
    status = a["prev_status"] or "pending"
    if a["scope"] == "schedule":
        cur = db.query_one(
            "SELECT score_a, score_b, winner_team_id, status FROM lan_schedule WHERE id=%s", (a["ref"],)
        )
        if not cur:
            raise ValueError("That match no longer exists.")
        db.execute(
            "UPDATE lan_schedule SET score_a=%s, score_b=%s, winner_team_id=%s, status=%s WHERE id=%s",
            (a["prev_a"], a["prev_b"], a["prev_winner"], status, a["ref"]),
        )
    else:
        cur = db.query_one(
            "SELECT score_a, score_b, winner_team_id, status FROM lan_bracket WHERE mkey=%s", (a["ref"],)
        )
        if not cur:
            raise ValueError("That series no longer exists.")
        db.execute(
            "UPDATE lan_bracket SET score_a=%s, score_b=%s, winner_team_id=%s, status=%s WHERE mkey=%s",
            (a["prev_a"], a["prev_b"], a["prev_winner"], status, a["ref"]),
        )
        from . import bracket
        bracket.resolve_dependents()
    log(a["scope"], a["ref"], "undo",
        {"a": cur["score_a"], "b": cur["score_b"], "winner": cur["winner_team_id"], "status": cur["status"]},
        {"a": a["prev_a"], "b": a["prev_b"], "winner": a["prev_winner"], "status": status},
        actor)
