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
    ("18:00 – 19:00", "Round 6 — 1v2", "round"),
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
