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

# 11 teams — 6 rounds, one seed byes each round (the seed absent from the round).
# Balanced like SCHEDULE_10: no repeat pairings, top-4 never meet before R4,
# 1v2 closes; byes fall on the rested top seeds (standings use win %, so unequal
# game counts don't skew seeding). The byes are 3,9,1,2,5,4 across R1..R6.
SCHEDULE_11 = [
    [(10, 7), (6, 2),  (4, 8),  (1, 9),  (5, 11)],
    [(10, 4), (1, 6),  (5, 3),  (11, 7), (8, 2)],
    [(10, 9), (8, 11), (2, 5),  (7, 4),  (3, 6)],
    [(10, 1), (5, 4),  (11, 6), (9, 3),  (8, 7)],
    [(10, 6), (4, 3),  (1, 7),  (11, 2), (9, 8)],
    [(10, 3), (6, 7),  (1, 2),  (5, 8),  (11, 9)],
]

# 12 teams — 6 rounds, 6 matches, everyone plays six. Same balance constraints.
SCHEDULE_12 = [
    [(2, 7),  (4, 12), (9, 8),   (11, 3), (6, 10), (1, 5)],
    [(2, 5),  (10, 1), (3, 6),   (8, 11), (12, 9), (7, 4)],
    [(2, 9),  (11, 4), (6, 7),   (1, 12), (5, 8),  (10, 3)],
    [(2, 11), (6, 9),  (1, 4),   (5, 7),  (10, 12),(3, 8)],
    [(2, 4),  (9, 7),  (11, 12), (6, 8),  (1, 3),  (5, 10)],
    [(2, 1),  (5, 6),  (10, 11), (3, 9),  (8, 4),  (12, 7)],
]

SCHEDULES = {10: SCHEDULE_10, 11: SCHEDULE_11, 12: SCHEDULE_12}


def team_count() -> int:
    """Number of registered teams (drives which group schedule is active)."""
    from . import db
    try:
        return db.query_one("SELECT COUNT(*) AS c FROM lan_teams")["c"] or 0
    except Exception:
        return 0


def active_schedule() -> list:
    """The seed-pairing schedule for the current team count (10/11/12). A 10-team
    field honors the staff-selected draw (locked/balanced/fairest); 11/12 have a
    single layout. Falls back to the 10-team layout for preview."""
    n = team_count()
    if n == 10:
        return DRAW_CHOICES[active_draw_key()]
    return SCHEDULES.get(n, SCHEDULE_10)

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
        for rnd in active_schedule()
    ]


def seeds_locked() -> bool:
    n = team_count()
    return n in SCHEDULES and len(seed_map()) >= n


# Alternative 10-team group draws surfaced for staff to weigh against the locked
# SCHEDULE_10 — both came out of an offline search over all 11,180,820 legal draws
# and obey the same two rules (no rematch, no top-four before Round 4). They are
# decision aids only: NOT in SCHEDULES, so materialize_matches() never uses them.
SCHEDULE_10_BALANCED = [  # variance 5.80 — keeps all six top-4 clashes + the 1v2 finale
    [(1, 9), (2, 7), (3, 10), (4, 5), (6, 8)],
    [(1, 5), (2, 10), (3, 6), (4, 9), (7, 8)],
    [(1, 8), (2, 6), (3, 7), (4, 10), (5, 9)],
    [(1, 4), (2, 3), (5, 8), (6, 7), (9, 10)],
    [(1, 3), (2, 4), (5, 7), (6, 9), (8, 10)],
    [(1, 2), (3, 4), (5, 6), (7, 10), (8, 9)],
]
SCHEDULE_10_FAIREST = [  # variance 1.20 — statistical floor; drops the 1v2 and 3v4 games
    [(1, 6), (2, 5), (3, 7), (4, 9), (8, 10)],
    [(1, 5), (2, 8), (3, 10), (4, 7), (6, 9)],
    [(1, 8), (2, 9), (3, 6), (4, 10), (5, 7)],
    [(1, 4), (2, 3), (5, 10), (6, 8), (7, 9)],
    [(1, 7), (2, 4), (3, 8), (5, 9), (6, 10)],
    [(1, 3), (2, 6), (4, 5), (7, 10), (8, 9)],
]

# Staff-selectable 10-team draws. materialize_matches() + the schedule preview
# both resolve through active_draw_key(); anything but these keys means 'locked'.
DRAW_CHOICES = {"locked": SCHEDULE_10, "balanced": SCHEDULE_10_BALANCED, "fairest": SCHEDULE_10_FAIREST}


def active_draw_key() -> str:
    """Which 10-team draw staff have set active ('locked' default)."""
    from . import seeding
    k = seeding.get_setting("active_draw", "locked")
    return k if k in DRAW_CHOICES else "locked"


def _draw_stats(rounds):
    """SoS spread + marquee facts for one seed-pairing draw (seeds 1..10)."""
    opp = {s: [] for s in range(1, 11)}
    for rnd in rounds:
        for a, b in rnd:
            opp[a].append(b); opp[b].append(a)
    sos = {s: sum(opp[s]) for s in range(1, 11)}
    mean = sum(sos.values()) / 10
    top4 = (1, 2, 3, 4)
    clashes = sum(1 for a in top4 for b in top4 if a < b and b in opp[a])
    return {
        "variance": sum((v - mean) ** 2 for v in sos.values()) / 10,
        "min": min(sos.values()), "max": max(sos.values()),
        "top4_clashes": clashes, "has_1v2": 2 in opp[1],
    }


def schedule_options():
    """The locked draw plus the two search alternatives, teams overlaid, for the
    staff schedule-decision panel. None unless a 10-team field with seeds locked."""
    if team_count() != 10:
        return None
    smap = seed_map()
    if len(smap) < 10:
        return None
    times = round_times()
    active = active_draw_key()
    defs = [
        ("locked", "Locked draw",
         "Every headline game is played and no company draws a slate worse than 37.",
         SCHEDULE_10),
        ("balanced", "Balanced draw",
         "Same marquee shape as the locked draw — all six top-seed clashes, 1 v 2 closing — with "
         "tighter variance, but it hands one company a 38 slate, the harshest in any option.",
         SCHEDULE_10_BALANCED),
        ("fairest", "Fairest draw",
         "The statistical floor — provably the most even draw of all. The cost: the top-two (1 v 2) and "
         "the three-vs-four games never happen.",
         SCHEDULE_10_FAIREST),
    ]
    out = []
    for key, title, note, rounds in defs:
        out.append({
            "key": key, "title": title, "current": key == active, "note": note,
            "stats": _draw_stats(rounds),
            "rounds": [
                {"n": i, "time": times.get(i), "matches": [
                    {"a": smap[a], "b": smap[b], "top4": a < 5 and b < 5}
                    for a, b in rnd]}
                for i, rnd in enumerate(rounds, 1)
            ],
        })
    return out


def _sos_domain():
    """The true SoS scale: hardest possible slate (the six lowest other seeds) to
    easiest (the six highest). Comes out 21..45, centred on the fixed mean of 33.

    The bar chart anchors to THIS, not to the observed min/max. Min-max normalising
    pins the toughest slate at 100% and the easiest at 0% however tight the real
    band is — so a 30..37 spread (i.e. ten near-identical slates) renders as a
    full-width chasm, and would do so even for a perfectly even draw. Anchoring to
    the real scale lets the bars show what's actually true: everyone lands near 33.
    """
    lo, hi = [], []
    for s in range(1, 11):
        others = [x for x in range(1, 11) if x != s]
        lo.append(sum(sorted(others)[:6]))
        hi.append(sum(sorted(others)[-6:]))
    return min(lo), max(hi)


def strength_of_schedule():
    """Per-seed strength of schedule for the 10-team group draw, teams overlaid.

    SoS = the sum of a seed's six opponents' seed numbers (lower = a tougher
    slate). Returns None unless the field is exactly ten with every seed locked:
    the fairness-audit figures published beside this are derived for the 10-team
    draw only. Cheap — pure arithmetic over the fixed pairing table."""
    if team_count() != 10:
        return None
    smap = seed_map()
    if len(smap) < 10:
        return None
    opp = {s: [] for s in range(1, 11)}
    for rnd in active_schedule():
        for a, b in rnd:
            opp[a].append(b); opp[b].append(a)
    rows = [{"seed": s, "team": smap[s], "opponents": sorted(opp[s]), "sos": sum(opp[s])}
            for s in range(1, 11)]
    vals = [r["sos"] for r in rows]
    mean = sum(vals) / len(vals)
    dom_min, dom_max = _sos_domain()
    stats = _draw_stats(active_schedule())
    return {
        "rows": rows,
        "mean": mean,
        "variance": sum((v - mean) ** 2 for v in vals) / len(vals),
        "min": min(vals), "max": max(vals),
        # True scale for the bars — see _sos_domain.
        "dom_min": dom_min, "dom_max": dom_max,
        # Marquee facts about the ACTIVE draw, so the published assessment can be
        # stated from this draw's own numbers instead of by comparison with the
        # alternatives (which are staff-only and must never be published).
        "top4_clashes": stats["top4_clashes"],
        "has_1v2": stats["has_1v2"],
        "active_draw": active_draw_key(),
    }


# ── materialized matches (after seeds lock) ──────────────────────────────
def get_matches() -> list[dict]:
    """lan_schedule rows joined with team names, ordered by round. [] if none/down."""
    from . import db
    try:
        return db.query_all(
            """
            SELECT m.id, m.round, m.station, m.`map` AS map, m.status,
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
    """Insert lan_schedule rows from the active schedule, mapping seed->team.
    Requires a 10/11/12-team field with every seed assigned (byes create no row)."""
    from . import db
    n = team_count()
    if n not in SCHEDULES:
        raise ValueError("Saturday supports 10–12 teams — adjust the field first.")
    smap = seed_map()
    if len(smap) < n:
        raise ValueError("Seeds are not locked — cannot generate matches.")
    # Regenerating wipes lan_schedule. Refuse once any match carries a reported
    # result, so a late draw change can't silently erase played games.
    played = db.query_one(
        "SELECT COUNT(*) AS c FROM lan_schedule WHERE status='final' "
        "OR score_a IS NOT NULL OR score_b IS NOT NULL OR winner_team_id IS NOT NULL")
    if played and played["c"]:
        raise ValueError(
            "Matches already have reported results — regenerating would erase them. "
            "Clear the results first if you truly mean to rebuild the schedule.")
    schedule = active_schedule()
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM lan_schedule")
        for rnd_i, rnd in enumerate(schedule, 1):
            for a, b in rnd:
                cur.execute(
                    "INSERT INTO lan_schedule (round, team_a_id, team_b_id, status) "
                    "VALUES (%s, %s, %s, 'pending')",
                    (rnd_i, smap[a]["id"], smap[b]["id"]),
                )


def report_result(match_id: int, score_a: int, score_b: int, reporter_discord_id: int | None):
    from . import audit, db
    m = db.query_one(
        "SELECT team_a_id, team_b_id, score_a, score_b, winner_team_id, status "
        "FROM lan_schedule WHERE id=%s", (match_id,)
    )
    if not m:
        raise ValueError("No such match.")
    winner = m["team_a_id"] if score_a > score_b else m["team_b_id"] if score_b > score_a else None
    db.execute(
        "UPDATE lan_schedule SET score_a=%s, score_b=%s, winner_team_id=%s, status='final', "
        "reported_by=%s, reported_at=NOW() WHERE id=%s",
        (score_a, score_b, winner, reporter_discord_id, match_id),
    )
    audit.log("schedule", match_id, "edit" if m["status"] == "final" else "report",
              {"a": m["score_a"], "b": m["score_b"], "winner": m["winner_team_id"], "status": m["status"]},
              {"a": score_a, "b": score_b, "winner": winner, "status": "final"},
              reporter_discord_id)


def round_times() -> dict[int, str]:
    """Group round number -> its timetable slot label."""
    times, n = {}, 0
    for label_time, _label, kind in SATURDAY_TIMETABLE:
        if kind == "round":
            n += 1
            times[n] = label_time
    return times


def team_schedule(team_id: int) -> list[dict]:
    """This team's Saturday matches, normalized to us/opponent, in round order."""
    times = round_times()
    out = []
    for m in get_matches():
        if team_id not in (m["team_a_id"], m["team_b_id"]):
            continue
        us_a = m["team_a_id"] == team_id
        result = None
        if m["status"] == "final" and m["winner_team_id"]:
            result = "W" if m["winner_team_id"] == team_id else "L"
        out.append({
            "round": m["round"], "time": times.get(m["round"]),
            "opponent": m["b_name"] if us_a else m["a_name"],
            "opp_tag": m["b_tag"] if us_a else m["a_tag"],
            "our_score": m["score_a"] if us_a else m["score_b"],
            "opp_score": m["score_b"] if us_a else m["score_a"],
            "result": result, "station": m["station"], "map": m["map"], "status": m["status"],
        })
    out.sort(key=lambda r: r["round"])
    return out


def set_station(match_id: int, station):
    """Admin: assign (or clear) the server/station number for a Saturday match."""
    from . import db
    db.execute("UPDATE lan_schedule SET station=%s WHERE id=%s", (station, match_id))


def set_round_map(round_no: int, mapname):
    """Admin: set (or clear) the map for every match in a Saturday round —
    each round is one map for all five matches."""
    from . import db
    db.execute("UPDATE lan_schedule SET `map`=%s WHERE round=%s", (mapname, round_no))


# LAN 2026 map pool — drives the map-picker datalist (free text still allowed).
COMP_MAPS = [
    "Harrington", "Lennon", "Anzio", "Saints",
    "Thunder2", "Railroad2", "Armory",
]

