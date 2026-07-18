"""Captain map-skip poll — tally + ballot storage.

Saturday plays only 6 matches, so one map is dropped from Saturday and used as
the play-in map. Each captain casts a single ballot naming the map their team
wants skipped; the most-voted map wins. Plain plurality — no weighting (unlike
the seeding poll), since this is a single-choice vote, not a ranking."""
from __future__ import annotations

# db/settings are imported lazily inside the helpers so the pure tally below is
# importable (and unit-testable) without a MySQL driver present.


# ── the candidate pool ────────────────────────────────────────────────────
def pool_maps() -> list[str]:
    """The maps a captain may vote to skip — the configured LAN pool."""
    from . import schedule as sched
    return list(sched.COMP_MAPS)


# ── pure tally (no DB; unit-tested) ───────────────────────────────────────
def tally(ballots: dict[int, str], pool: list[str]):
    """Returns (ordered, counts).

    ballots: {voting_team_id: skip_map}. counts: {map: votes}. ordered: maps
    most-voted first, ties broken by pool order (deterministic). Votes for a map
    outside the pool are ignored."""
    counts = {m: 0 for m in pool}
    for m in ballots.values():
        if m in counts:
            counts[m] += 1
    ordered = sorted(pool, key=lambda m: (-counts[m], pool.index(m)))
    return ordered, counts


# ── persistence ───────────────────────────────────────────────────────────
def save_ballot(voting_team_id: int, skip_map: str, submitted_by: int | None = None):
    """Replaces any prior ballot for this team (one vote per team)."""
    from . import db
    db.execute(
        "INSERT INTO lan_map_skip_ballots (voting_team_id, skip_map, submitted_by) "
        "VALUES (%s, %s, %s) "
        "ON DUPLICATE KEY UPDATE skip_map=VALUES(skip_map), submitted_by=VALUES(submitted_by), "
        "submitted_at=CURRENT_TIMESTAMP",
        (voting_team_id, skip_map, submitted_by),
    )


def get_all_ballots() -> dict[int, str]:
    from . import db
    rows = db.query_all("SELECT voting_team_id, skip_map FROM lan_map_skip_ballots")
    return {r["voting_team_id"]: r["skip_map"] for r in rows}


def get_team_ballot(voting_team_id: int) -> str | None:
    from . import db
    row = db.query_one(
        "SELECT skip_map FROM lan_map_skip_ballots WHERE voting_team_id=%s",
        (voting_team_id,),
    )
    return row["skip_map"] if row else None


def compute_and_store():
    """Tally current ballots and lock the winning map into lan_settings.skip_map.
    Returns (ordered, counts). A tie resolves to pool order — staff can override
    by re-running after the tie is broken, or set skip_map directly."""
    ballots = get_all_ballots()
    ordered, counts = tally(ballots, pool_maps())
    winner = ordered[0] if ordered and counts.get(ordered[0], 0) > 0 else None
    set_setting("skip_map", winner or "")
    return ordered, counts


# ── poll state (lan_settings) — reuses the seeding settings helpers ────────
def get_setting(key: str, default=None):
    from . import seeding
    return seeding.get_setting(key, default)


def set_setting(key: str, value):
    from . import seeding
    seeding.set_setting(key, value)


def poll_is_open() -> bool:
    return get_setting("map_skip_poll_open", "0") == "1"


def locked_skip_map() -> str | None:
    return (get_setting("skip_map", "") or "").strip() or None
