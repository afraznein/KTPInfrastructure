"""Post-event awards — one ballot per voter per category, players or teams.

Results stay hidden from the public until a category is closed (so live tallies
don't sway voting); staff always see them."""
from __future__ import annotations

from . import db


def all_awards() -> list[dict]:
    return db.query_all("SELECT * FROM lan_awards ORDER BY sort_order, id")


def targets(kind: str) -> list[dict]:
    """Selectable options for a category: players (id+label) or teams."""
    if kind == "team":
        return db.query_all("SELECT id, name AS label FROM lan_teams ORDER BY name")
    return db.query_all(
        "SELECT p.id, CONCAT(p.display_name, ' · ', t.name) AS label "
        "FROM lan_players p JOIN lan_teams t ON t.id = p.team_id "
        "ORDER BY t.name, p.display_name"
    )


def my_votes(voter) -> dict[int, int]:
    """award_id -> target_id this voter has chosen."""
    if not voter:
        return {}
    return {r["award_id"]: r["target_id"]
            for r in db.query_all("SELECT award_id, target_id FROM lan_award_votes WHERE voter=%s", (voter,))}


def cast_vote(award_id: int, voter, target_id: int) -> None:
    aw = db.query_one("SELECT is_open FROM lan_awards WHERE id=%s", (award_id,))
    if not aw:
        raise ValueError("No such award.")
    if not aw["is_open"]:
        raise ValueError("Voting for this award is closed.")
    db.execute(
        "INSERT INTO lan_award_votes (award_id, voter, target_id) VALUES (%s,%s,%s) "
        "ON DUPLICATE KEY UPDATE target_id=VALUES(target_id), created_at=CURRENT_TIMESTAMP",
        (award_id, voter, target_id),
    )


def results(award: dict) -> list[dict]:
    """Ranked tally for one award: [{label, votes}], highest first."""
    if award["kind"] == "team":
        join = "JOIN lan_teams x ON x.id = v.target_id"
        label = "x.name"
    else:
        join = "JOIN lan_players x ON x.id = v.target_id"
        label = "x.display_name"
    return db.query_all(
        f"SELECT {label} AS label, COUNT(*) AS votes FROM lan_award_votes v {join} "
        "WHERE v.award_id=%s GROUP BY v.target_id ORDER BY votes DESC, label",
        (award["id"],),
    )


def total_votes(award_id: int) -> int:
    r = db.query_one("SELECT COUNT(*) AS n FROM lan_award_votes WHERE award_id=%s", (award_id,))
    return r["n"] if r else 0
