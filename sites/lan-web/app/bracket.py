"""Sunday playoffs — single-elimination championship + a consolation lower
bracket for final standings, auto-fed from group standings.

The layout scales to the number of teams that played Saturday (10, 11, or 12).
In every case the main bracket is 8 teams (QF→SF→Final): the top seeds bye, and
the rest play a Play-in to fill the remaining QF slots. A parallel consolation
bracket plays the eliminated teams down to a complete 1..N final ranking and
never feeds back into the championship.

Slot sources: 'seed:N' = group rank N, 'W:KEY' = winner of KEY, 'L:KEY' = loser.
The active team count is frozen into lan_settings ('playoff_team_count') when the
bracket is generated; before that the page previews the shape for the current
team count (defaulting to 10)."""
from __future__ import annotations

import json

BEST_OF = 3                       # default series length
WINS_NEEDED = BEST_OF // 2 + 1    # 2 (kept for callers; report_series uses per-match best_of)


def wins_for(best_of: int) -> int:
    return best_of // 2 + 1


def _m(key, brk, stage, slot, a, b, best_of, label):
    return {"key": key, "bracket": brk, "stage": stage, "slot": slot,
            "a": a, "b": b, "best_of": best_of, "label": label}


# ── per-count layouts ────────────────────────────────────────────────────
# Each layout: ordered match list, the placement spec (place -> source), the
# consolation view groups, and per-match start times. Play-in is BO1; the
# championship and the lower-bracket rounds that give eliminated teams a real
# series are BO3; the 3/4·5/6·7/8 deciders are BO1 so the Final stands alone.

# N=10 — seeds 1-6 bye, 7-10 play in. (Verified design; do not reshuffle.)
_L10 = {
    "matches": [
        _m("PI1", "upper", "PI", 1, "seed:7", "seed:10", 1, "Play-in 1"),
        _m("PI2", "upper", "PI", 2, "seed:8", "seed:9",  1, "Play-in 2"),
        _m("QF1", "upper", "QF", 1, "seed:1", "W:PI2", 3, "Quarterfinal 1"),
        _m("QF2", "upper", "QF", 2, "seed:4", "seed:5", 3, "Quarterfinal 2"),
        _m("QF3", "upper", "QF", 3, "seed:3", "seed:6", 3, "Quarterfinal 3"),
        _m("QF4", "upper", "QF", 4, "seed:2", "W:PI1", 3, "Quarterfinal 4"),
        _m("SF1", "upper", "SF", 1, "W:QF1", "W:QF2", 3, "Semifinal 1"),
        _m("SF2", "upper", "SF", 2, "W:QF3", "W:QF4", 3, "Semifinal 2"),
        _m("F",   "upper", "F",  1, "W:SF1", "W:SF2", 3, "Final"),
        _m("P34",  "placement", "P34",  1, "L:SF1", "L:SF2", 1, "3rd / 4th place"),
        _m("LS1",  "placement", "LS",   1, "L:QF1", "L:QF4", 3, "Lower Semifinal 1"),
        _m("LS2",  "placement", "LS",   2, "L:QF2", "L:QF3", 3, "Lower Semifinal 2"),
        _m("P56",  "placement", "P56",  1, "W:LS1", "W:LS2", 1, "5th / 6th place"),
        _m("P78",  "placement", "P78",  1, "L:LS1", "L:LS2", 1, "7th / 8th place"),
        _m("P910", "placement", "P910", 1, "L:PI1", "L:PI2", 3, "9th / 10th place"),
    ],
    "placement": [(1, "W:F"), (2, "L:F"), (3, "W:P34"), (4, "L:P34"),
                  (5, "W:P56"), (6, "L:P56"), (7, "W:P78"), (8, "L:P78"),
                  (9, "W:P910"), (10, "L:P910")],
    "consolation_groups": [
        {"title": "9th / 10th · play-in losers", "mkeys": ["P910"]},
        {"title": "Lower semifinals · QF losers", "mkeys": ["LS1", "LS2"]},
        {"title": "Placement finals · 3/4 · 5/6 · 7/8", "mkeys": ["P34", "P56", "P78"]},
    ],
    "times": {
        "PI1": "11:00 AM", "PI2": "11:00 AM",
        "QF1": "12:00 PM", "QF2": "12:00 PM", "QF3": "12:00 PM", "QF4": "12:00 PM", "P910": "12:00 PM",
        "SF1": "3:30 PM", "SF2": "3:30 PM", "LS1": "3:30 PM", "LS2": "3:30 PM",
        "P34": "7:00 PM", "P56": "7:00 PM", "P78": "7:00 PM",
        "F": "8:00 PM",
    },
}

# N=11 — seeds 1-5 bye, 6-11 play in (3 matches). The three play-in losers
# settle 9/10/11 via a 3-team mini-bracket (L:PI1 byes the 11th-place match).
_L11 = {
    "matches": [
        _m("PI1", "upper", "PI", 1, "seed:6", "seed:11", 1, "Play-in 1"),
        _m("PI2", "upper", "PI", 2, "seed:7", "seed:10", 1, "Play-in 2"),
        _m("PI3", "upper", "PI", 3, "seed:8", "seed:9",  1, "Play-in 3"),
        _m("QF1", "upper", "QF", 1, "seed:1", "W:PI3", 3, "Quarterfinal 1"),
        _m("QF2", "upper", "QF", 2, "seed:4", "seed:5", 3, "Quarterfinal 2"),
        _m("QF3", "upper", "QF", 3, "seed:2", "W:PI2", 3, "Quarterfinal 3"),
        _m("QF4", "upper", "QF", 4, "seed:3", "W:PI1", 3, "Quarterfinal 4"),
        _m("SF1", "upper", "SF", 1, "W:QF1", "W:QF2", 3, "Semifinal 1"),
        _m("SF2", "upper", "SF", 2, "W:QF3", "W:QF4", 3, "Semifinal 2"),
        _m("F",   "upper", "F",  1, "W:SF1", "W:SF2", 3, "Final"),
        _m("P34",  "placement", "P34",  1, "L:SF1", "L:SF2", 1, "3rd / 4th place"),
        _m("LS1",  "placement", "LS",   1, "L:QF1", "L:QF4", 3, "Lower Semifinal 1"),
        _m("LS2",  "placement", "LS",   2, "L:QF2", "L:QF3", 3, "Lower Semifinal 2"),
        _m("P56",  "placement", "P56",  1, "W:LS1", "W:LS2", 1, "5th / 6th place"),
        _m("P78",  "placement", "P78",  1, "L:LS1", "L:LS2", 1, "7th / 8th place"),
        _m("P11",  "placement", "P11",  1, "L:PI2", "L:PI3", 1, "11th-place match"),
        _m("P910", "placement", "P910", 1, "L:PI1", "W:P11", 3, "9th / 10th place"),
    ],
    "placement": [(1, "W:F"), (2, "L:F"), (3, "W:P34"), (4, "L:P34"),
                  (5, "W:P56"), (6, "L:P56"), (7, "W:P78"), (8, "L:P78"),
                  (9, "W:P910"), (10, "L:P910"), (11, "L:P11")],
    "consolation_groups": [
        {"title": "11th place · play-in losers", "mkeys": ["P11"]},
        {"title": "9th / 10th", "mkeys": ["P910"]},
        {"title": "Lower semifinals · QF losers", "mkeys": ["LS1", "LS2"]},
        {"title": "Placement finals · 3/4 · 5/6 · 7/8", "mkeys": ["P34", "P56", "P78"]},
    ],
    "times": {
        "PI1": "11:00 AM", "PI2": "11:00 AM", "PI3": "11:00 AM",
        "QF1": "12:00 PM", "QF2": "12:00 PM", "QF3": "12:00 PM", "QF4": "12:00 PM", "P11": "12:00 PM",
        "SF1": "3:30 PM", "SF2": "3:30 PM", "LS1": "3:30 PM", "LS2": "3:30 PM", "P910": "3:30 PM",
        "P34": "7:00 PM", "P56": "7:00 PM", "P78": "7:00 PM",
        "F": "8:00 PM",
    },
}

# N=12 — seeds 1-4 bye, 5-12 play in (4 matches). The four play-in losers run a
# clean lower play-in bracket mirroring the QF losers, settling 9/10 and 11/12.
_L12 = {
    "matches": [
        _m("PI1", "upper", "PI", 1, "seed:5", "seed:12", 1, "Play-in 1"),
        _m("PI2", "upper", "PI", 2, "seed:6", "seed:11", 1, "Play-in 2"),
        _m("PI3", "upper", "PI", 3, "seed:7", "seed:10", 1, "Play-in 3"),
        _m("PI4", "upper", "PI", 4, "seed:8", "seed:9",  1, "Play-in 4"),
        _m("QF1", "upper", "QF", 1, "seed:1", "W:PI4", 3, "Quarterfinal 1"),
        _m("QF2", "upper", "QF", 2, "seed:4", "W:PI1", 3, "Quarterfinal 2"),
        _m("QF3", "upper", "QF", 3, "seed:2", "W:PI3", 3, "Quarterfinal 3"),
        _m("QF4", "upper", "QF", 4, "seed:3", "W:PI2", 3, "Quarterfinal 4"),
        _m("SF1", "upper", "SF", 1, "W:QF1", "W:QF2", 3, "Semifinal 1"),
        _m("SF2", "upper", "SF", 2, "W:QF3", "W:QF4", 3, "Semifinal 2"),
        _m("F",   "upper", "F",  1, "W:SF1", "W:SF2", 3, "Final"),
        _m("P34",   "placement", "P34",   1, "L:SF1", "L:SF2", 1, "3rd / 4th place"),
        _m("LS1",   "placement", "LS",    1, "L:QF1", "L:QF4", 3, "Lower Semifinal 1"),
        _m("LS2",   "placement", "LS",    2, "L:QF2", "L:QF3", 3, "Lower Semifinal 2"),
        _m("P56",   "placement", "P56",   1, "W:LS1", "W:LS2", 1, "5th / 6th place"),
        _m("P78",   "placement", "P78",   1, "L:LS1", "L:LS2", 1, "7th / 8th place"),
        _m("LPI1",  "placement", "LPI",   1, "L:PI1", "L:PI4", 3, "Lower Play-in 1"),
        _m("LPI2",  "placement", "LPI",   2, "L:PI2", "L:PI3", 3, "Lower Play-in 2"),
        _m("P910",  "placement", "P910",  1, "W:LPI1", "W:LPI2", 3, "9th / 10th place"),
        _m("P1112", "placement", "P1112", 1, "L:LPI1", "L:LPI2", 1, "11th / 12th place"),
    ],
    "placement": [(1, "W:F"), (2, "L:F"), (3, "W:P34"), (4, "L:P34"),
                  (5, "W:P56"), (6, "L:P56"), (7, "W:P78"), (8, "L:P78"),
                  (9, "W:P910"), (10, "L:P910"), (11, "W:P1112"), (12, "L:P1112")],
    "consolation_groups": [
        {"title": "Lower play-in · 9th–12th", "mkeys": ["LPI1", "LPI2"]},
        {"title": "9/10 · 11/12", "mkeys": ["P910", "P1112"]},
        {"title": "Lower semifinals · QF losers", "mkeys": ["LS1", "LS2"]},
        {"title": "Placement finals · 3/4 · 5/6 · 7/8", "mkeys": ["P34", "P56", "P78"]},
    ],
    "times": {
        "PI1": "11:00 AM", "PI2": "11:00 AM", "PI3": "11:00 AM", "PI4": "11:00 AM",
        "QF1": "12:00 PM", "QF2": "12:00 PM", "QF3": "12:00 PM", "QF4": "12:00 PM",
        "LPI1": "12:00 PM", "LPI2": "12:00 PM",
        "SF1": "3:30 PM", "SF2": "3:30 PM", "LS1": "3:30 PM", "LS2": "3:30 PM",
        "P910": "3:30 PM", "P1112": "3:30 PM",
        "P34": "7:00 PM", "P56": "7:00 PM", "P78": "7:00 PM",
        "F": "8:00 PM",
    },
}

LAYOUTS = {10: _L10, 11: _L11, 12: _L12}

# get_bracket() orders rows by this stage sequence (covers every layout).
STAGE_ORDER = ["PI", "QF", "SF", "F", "P34", "LS", "P56", "P78", "LPI", "P11", "P910", "P1112"]

# Merged key->meta across all layouts, for label/best_of lookups by callers that
# don't care which count is active (labels/best_of are consistent per key).
BY_KEY = {}
for _lay in LAYOUTS.values():
    for _mm in _lay["matches"]:
        BY_KEY.setdefault(_mm["key"], _mm)

BRACKET = _L10["matches"]   # default shape; resolve_slots falls back to this


# ── active-count plumbing ────────────────────────────────────────────────
def active_count() -> int:
    """Frozen playoff team count, or a preview from the current team count."""
    from . import db, seeding
    raw = seeding.get_setting("playoff_team_count")
    if raw:
        try:
            n = int(raw)
            if 10 <= n <= 12:
                return n
        except ValueError:
            pass
    try:
        c = db.query_one("SELECT COUNT(*) AS c FROM lan_teams")["c"] or 0
    except Exception:
        return 10
    return 10 if c < 10 else 12 if c > 12 else c


def active_layout() -> dict:
    return LAYOUTS[active_count()]


def active_matches() -> list[dict]:
    return active_layout()["matches"]


def active_by_key() -> dict[str, dict]:
    return {m["key"]: m for m in active_matches()}


def consolation_groups() -> list[dict]:
    return active_layout()["consolation_groups"]


def placement_spec() -> list[tuple]:
    return active_layout()["placement"]


def match_time(mkey: str):
    """Scheduled start time for a bracket match, or None if unknown."""
    return active_layout()["times"].get(mkey)


# ── pure resolution (no DB; unit-tested) ─────────────────────────────────
def resolve_slots(rank_map: dict[int, int], outcomes: dict[str, tuple],
                  matches: list[dict] | None = None) -> dict[str, tuple]:
    """{rank: team_id} + {mkey: (winner_id, loser_id)} -> {mkey: (a_id, b_id)}.

    A side is None until its source resolves (upstream match undecided).
    `matches` defaults to the 10-team layout so the pure unit tests stay 2-arg."""
    matches = matches if matches is not None else BRACKET

    def side(src):
        if not src:
            return None
        kind, ref = src.split(":")
        if kind == "seed":
            return rank_map.get(int(ref))
        if ref in outcomes:
            w, l = outcomes[ref]
            return w if kind == "W" else l
        return None

    return {m["key"]: (side(m["a"]), side(m["b"])) for m in matches}


# ── DB-backed lifecycle ──────────────────────────────────────────────────
def _rank_map_from_standings():
    from . import db, standings
    from . import schedule as sched
    teams = db.query_all("SELECT id, name, tag, seed FROM lan_teams")
    matches = sched.get_matches()
    incomplete = (not matches) or any(m["status"] != "final" for m in matches)
    st = standings.compute_standings(teams, matches) if matches else []
    return {r["rank"]: r["team"]["id"] for r in st}, incomplete


def _stored_rank_map() -> dict[int, int]:
    from . import seeding
    raw = seeding.get_setting("playoff_seeds")
    return {int(k): v for k, v in json.loads(raw).items()} if raw else {}


def generate_bracket():
    """Freeze the playoff seeding from final standings and lay out the bracket
    for however many teams played Saturday (10, 11, or 12)."""
    from . import db, seeding
    rank_map, incomplete = _rank_map_from_standings()
    n = len(rank_map)
    if not 10 <= n <= 12:
        raise ValueError("Need 10–12 ranked teams — generate and play the group stage first.")
    if incomplete:
        raise ValueError("Group stage isn't complete — every Saturday match must be final first.")
    layout = LAYOUTS[n]
    seeding.set_setting("playoff_seeds", json.dumps(rank_map))
    seeding.set_setting("playoff_team_count", n)
    slots = resolve_slots(rank_map, {}, layout["matches"])
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM lan_bracket")
        for m in layout["matches"]:
            a, b = slots[m["key"]]
            cur.execute(
                "INSERT INTO lan_bracket (bracket, mkey, stage, slot, source_a, source_b, "
                "team_a_id, team_b_id, status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'pending')",
                (m["bracket"], m["key"], m["stage"], m["slot"], m["a"], m["b"], a, b),
            )


def regenerate_bracket():
    """Re-freeze seeding from current standings (e.g. after an audit-undo fixed a
    Saturday score). Regenerating wipes lan_bracket, so refuse once any series
    carries a reported result — mirrors materialize_matches' guard."""
    from . import db
    played = db.query_one(
        "SELECT COUNT(*) AS c FROM lan_bracket WHERE status='final' "
        "OR score_a IS NOT NULL OR score_b IS NOT NULL OR winner_team_id IS NOT NULL")
    if played and played["c"]:
        raise ValueError(
            "Playoff series already have reported results — regenerating would erase them. "
            "Undo the series results first if you truly mean to rebuild the bracket.")
    generate_bracket()


def get_bracket() -> list[dict]:
    from . import db
    field = ",".join("'%s'" % s for s in STAGE_ORDER)
    try:
        return db.query_all(
            f"""
            SELECT b.*, ta.name AS a_name, ta.tag AS a_tag, tb.name AS b_name, tb.tag AS b_tag
            FROM lan_bracket b
            LEFT JOIN lan_teams ta ON ta.id = b.team_a_id
            LEFT JOIN lan_teams tb ON tb.id = b.team_b_id
            ORDER BY FIELD(b.bracket,'upper','placement'),
                     FIELD(b.stage,{field}), b.slot
            """
        )
    except Exception:
        return []


def bracket_exists() -> bool:
    return len(get_bracket()) > 0


def report_series(mkey: str, sa: int, sb: int, actor=None):
    from . import audit, db
    row = db.query_one(
        "SELECT team_a_id, team_b_id, score_a, score_b, winner_team_id, status "
        "FROM lan_bracket WHERE mkey=%s", (mkey,)
    )
    if not row:
        raise ValueError("No such bracket match.")
    if row["team_a_id"] is None or row["team_b_id"] is None:
        raise ValueError("Both teams for this match aren't determined yet.")
    best_of = active_by_key().get(mkey, {}).get("best_of", BEST_OF)
    need = wins_for(best_of)
    if sa > need or sb > need:
        raise ValueError(f"Best-of-{best_of}: a side can win at most {need}.")
    winner, status = None, "pending"
    if sa >= need or sb >= need:
        winner = row["team_a_id"] if sa > sb else row["team_b_id"] if sb > sa else None
        status = "final" if winner else "live"
    elif sa or sb:
        status = "live"
    db.execute(
        "UPDATE lan_bracket SET score_a=%s, score_b=%s, winner_team_id=%s, status=%s WHERE mkey=%s",
        (sa, sb, winner, status, mkey),
    )
    audit.log("bracket", mkey, "edit" if row["status"] == "final" else "report",
              {"a": row["score_a"], "b": row["score_b"], "winner": row["winner_team_id"], "status": row["status"]},
              {"a": sa, "b": sb, "winner": winner, "status": status}, actor)
    resolve_dependents()


def _final_outcomes(rows: dict[str, dict]) -> dict[str, tuple]:
    """{mkey: (winner_id, loser_id)} for matches decided so far."""
    outcomes = {}
    for k, r in rows.items():
        if r["status"] == "final" and r["winner_team_id"]:
            w = r["winner_team_id"]
            l = r["team_a_id"] if w == r["team_b_id"] else r["team_b_id"]
            outcomes[k] = (w, l)
    return outcomes


def resolve_dependents():
    """Re-fill W:/L: slots from current final outcomes. Idempotent."""
    from . import db
    rows = {r["mkey"]: r for r in db.query_all("SELECT * FROM lan_bracket")}
    slots = resolve_slots(_stored_rank_map(), _final_outcomes(rows), active_matches())
    with db.get_conn() as conn, conn.cursor() as cur:
        for k, (a, b) in slots.items():
            r = rows.get(k)
            if r and (r["team_a_id"] != a or r["team_b_id"] != b):
                cur.execute("UPDATE lan_bracket SET team_a_id=%s, team_b_id=%s WHERE mkey=%s", (a, b, k))


def placement_order() -> list[dict]:
    """The active placement spec resolved against final outcomes:
    [{place, team_id, name}] with team_id None where the tier is undecided."""
    from . import db
    rows = {r["mkey"]: r for r in get_bracket()}
    outcomes = _final_outcomes(rows)
    rank_map = _stored_rank_map()
    names = {}
    for r in rows.values():
        if r["team_a_id"]:
            names[r["team_a_id"]] = r["a_name"]
        if r["team_b_id"]:
            names[r["team_b_id"]] = r["b_name"]

    def side(src):
        kind, ref = src.split(":")
        if kind == "seed":
            return rank_map.get(int(ref))
        if ref in outcomes:
            w, l = outcomes[ref]
            return w if kind == "W" else l
        return None

    return [{"place": pl, "team_id": (t := side(src)), "name": names.get(t)}
            for pl, src in placement_spec()]


def team_bracket(team_id: int) -> list[dict]:
    """This team's Sunday bracket/placement matches, normalized to us/opponent.
    Already in bracket->stage order from get_bracket()."""
    by = active_by_key()
    out = []
    for r in get_bracket():
        if team_id not in (r["team_a_id"], r["team_b_id"]):
            continue
        us_a = r["team_a_id"] == team_id
        m = by.get(r["mkey"], {})
        result = None
        if r["status"] == "final" and r["winner_team_id"]:
            result = "W" if r["winner_team_id"] == team_id else "L"
        out.append({
            "label": m.get("label", r["mkey"]),
            "best_of": m.get("best_of", BEST_OF),
            "opponent": r["b_name"] if us_a else r["a_name"],
            "our_score": r["score_a"] if us_a else r["score_b"],
            "opp_score": r["score_b"] if us_a else r["score_a"],
            "result": result, "station": r["station"], "map": r.get("map"),
            "time": match_time(r["mkey"]), "status": r["status"],
        })
    return out


def set_station(mkey: str, station):
    """Admin: assign (or clear) the server/station number for a bracket match."""
    from . import db
    db.execute("UPDATE lan_bracket SET station=%s WHERE mkey=%s", (station, mkey))


def set_map(mkey: str, mapname):
    """Set (or clear) the map(s) for a bracket series — written by the veto on
    completion."""
    from . import db
    db.execute("UPDATE lan_bracket SET `map`=%s WHERE mkey=%s", (mapname, mkey))
