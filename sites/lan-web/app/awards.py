"""Post-event awards — one ballot per voter per category, players or teams.

Results stay hidden from the public until a category is closed (so live tallies
don't sway voting); staff always see them.

Not stat_awards.py, and the /awards page it serves is not the generated awards
board: this is the players' ballot over lan_awards, that is the staff-decided
board over lan_award_*, rendered only by the static site from
GET /api/awards/candidates. Editing this template to fix the board is the
mistake the shared word invites."""
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


def eligible_voters() -> int | None:
    """The denominator turnout reads against: people who could vote at all.

    Casting needs a Discord account linked to a roster row, so an unlinked
    player is not eligible. None when nothing is linked — a denominator of zero
    would read as an answer rather than as no answer."""
    r = db.query_one("SELECT COUNT(*) AS n FROM lan_players WHERE discord_id IS NOT NULL")
    return (int(r["n"]) if r else 0) or None


def turnout(award_id: int, eligible: int | None) -> dict:
    """How many voted, never who is winning — safe to show while a vote is live.

    One ballot per voter per category is the table's primary key, so the ballot
    count is already a headcount and there is no third number to carry."""
    return {"ballots": total_votes(award_id), "eligible": eligible}
