"""Saturday group stage — the fixed, seed-balanced 6-round schedule.

Pairings are by SEED (1..10), not team. This is the balanced schedule verified
in design: round-1 fold, top-4 seeds never meet before round 4, 1v2 closes the
day, strength-of-schedule variance ~6.6. Team names overlay once seeds lock;
until then the page shows seed slots, so it generates fine before the poll."""
from __future__ import annotations

# Each round: (seedA, seedB) pairs. Verified 10-team balanced schedule.
SCHEDULE_10 = [
    [(1, 9), (2, 10), (3, 6), (4, 8), (5, 7)],
    [(1, 5), (2, 8),  (3, 7), (4, 10), (6, 9)],
    [(1, 7), (2, 5),  (3, 10), (4, 6), (8, 9)],
    [(1, 4), (2, 3),  (5, 6), (7, 9),  (8, 10)],
    [(1, 3), (2, 4),  (5, 8), (6, 7),  (9, 10)],
    [(1, 2), (3, 4),  (5, 9), (6, 8),  (7, 10)],
]

# Saturday timetable — (time, label, kind). kind: 'round' | 'break'.
# 11:00 start, 1-hour match blocks, two 1-hour food breaks; 1v2 closes.
SATURDAY_TIMETABLE = [
    ("11:00 – 12:00", "Round 1", "round"),
    ("12:00 – 13:00", "Round 2", "round"),
    ("13:00 – 14:00", "Food break #1", "break"),
    ("14:00 – 15:00", "Round 3", "round"),
    ("15:00 – 16:00", "Round 4", "round"),
    ("16:00 – 17:00", "Food break #2", "break"),
    ("17:00 – 18:00", "Round 5", "round"),
    ("18:00 – 19:00", "Round 6", "round"),
]


def seed_map() -> dict[int, dict]:
    """seed number -> team row, for teams that have a seed assigned.

    Resilient: returns {} if the DB is unreachable so the template still renders."""
    from . import db
    try:
        rows = db.query_all("SELECT id, name, tag, seed FROM lan_teams WHERE seed IS NOT NULL")
    except Exception:
        return {}
    return {r["seed"]: r for r in rows}


def rounds_with_teams():
    """Schedule with team rows overlaid where seeds are assigned.

    Each match: {a_seed, b_seed, a_team, b_team} (team None if seed unfilled)."""
    smap = seed_map()
    return [
        [
            {"a_seed": a, "b_seed": b, "a_team": smap.get(a), "b_team": smap.get(b)}
            for (a, b) in rnd
        ]
        for rnd in SCHEDULE_10
    ]


def seeds_locked() -> bool:
    return len(seed_map()) >= 10


# ── materialized matches (after seeds lock) ──────────────────────────────
def get_matches() -> list[dict]:
    """lan_schedule rows joined with team names, ordered by round. [] if none/down."""
    from . import db
    try:
        return db.query_all(
            """
            SELECT m.id, m.round, m.station, m.status,
                   m.team_a_id, m.team_b_id, m.score_a, m.score_b, m.winner_team_id,
                   ta.name AS a_name, ta.tag AS a_tag, ta.seed AS a_seed,
                   tb.name AS b_name, tb.tag AS b_tag, tb.seed AS b_seed
            FROM lan_schedule m
            JOIN lan_teams ta ON ta.id = m.team_a_id
            JOIN lan_teams tb ON tb.id = m.team_b_id
            ORDER BY m.round, m.id
            """
        )
    except Exception:
        return []


def matches_exist() -> bool:
    return len(get_matches()) > 0


def materialize_matches():
    """Insert lan_schedule rows from SCHEDULE_10, mapping seed->team. Requires all 10 seeds."""
    from . import db
    smap = seed_map()
    if len(smap) < 10:
        raise ValueError("Seeds are not locked — cannot generate matches.")
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM lan_schedule")
        for rnd_i, rnd in enumerate(SCHEDULE_10, 1):
            for a, b in rnd:
                cur.execute(
                    "INSERT INTO lan_schedule (round, team_a_id, team_b_id, status) "
                    "VALUES (%s, %s, %s, 'pending')",
                    (rnd_i, smap[a]["id"], smap[b]["id"]),
                )


def report_result(match_id: int, score_a: int, score_b: int, reporter_discord_id: int | None):
    from . import db
    m = db.query_one("SELECT team_a_id, team_b_id FROM lan_schedule WHERE id=%s", (match_id,))
    if not m:
        raise ValueError("No such match.")
    winner = m["team_a_id"] if score_a > score_b else m["team_b_id"] if score_b > score_a else None
    db.execute(
        "UPDATE lan_schedule SET score_a=%s, score_b=%s, winner_team_id=%s, status='final', "
        "reported_by=%s, reported_at=NOW() WHERE id=%s",
        (score_a, score_b, winner, reporter_discord_id, match_id),
    )

