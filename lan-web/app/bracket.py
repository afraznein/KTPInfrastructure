"""Sunday playoffs — bracket auto-fed from final group standings (Format C).

Two brackets run in parallel and reunite in a Grand Final:
- Upper (standings 1-6): seeds 1-2 bye to the SF, 3-6 into QFs; QF losers drop
  into the lower bracket. Crowns the upper champion (Upper Final winner).
- Lower (7-10 + the two QF losers): single-elim, crowns the lower champion.
- Grand Final: upper champ vs lower champ, BO5, no bracket reset.
- Placement matches (3/4, 5/6, 7/8, 9/10) decide each tied tier off to the side.

Series default BO3 (first to 2); the Grand Final is BO5. 'seed:N' = group rank N,
'W:KEY' = winner of KEY, 'L:KEY' = loser of KEY."""
from __future__ import annotations

import json

BEST_OF = 3                       # default series length
WINS_NEEDED = BEST_OF // 2 + 1    # 2 (kept for callers; report_series uses per-match best_of)


def wins_for(best_of: int) -> int:
    return best_of // 2 + 1


# Each slot: source 'seed:N' (standings rank), 'W:KEY' (winner of), 'L:KEY' (loser of).
BRACKET = [
    {"key": "QF1",  "bracket": "upper", "stage": "QF",  "slot": 1, "a": "seed:3", "b": "seed:6",  "best_of": 3, "label": "Quarterfinal 1"},
    {"key": "QF2",  "bracket": "upper", "stage": "QF",  "slot": 2, "a": "seed:4", "b": "seed:5",  "best_of": 3, "label": "Quarterfinal 2"},
    {"key": "SF1",  "bracket": "upper", "stage": "SF",  "slot": 1, "a": "seed:1", "b": "W:QF2",   "best_of": 3, "label": "Semifinal 1"},
    {"key": "SF2",  "bracket": "upper", "stage": "SF",  "slot": 2, "a": "seed:2", "b": "W:QF1",   "best_of": 3, "label": "Semifinal 2"},
    {"key": "F",    "bracket": "upper", "stage": "F",   "slot": 1, "a": "W:SF1", "b": "W:SF2",    "best_of": 3, "label": "Upper Final"},
    {"key": "PA",   "bracket": "lower", "stage": "PI",  "slot": 1, "a": "seed:7", "b": "seed:10", "best_of": 3, "label": "Play-in A"},
    {"key": "PB",   "bracket": "lower", "stage": "PI",  "slot": 2, "a": "seed:8", "b": "seed:9",  "best_of": 3, "label": "Play-in B"},
    {"key": "LSF1", "bracket": "lower", "stage": "LSF", "slot": 1, "a": "L:QF2", "b": "W:PA",     "best_of": 3, "label": "Lower Semifinal 1"},
    {"key": "LSF2", "bracket": "lower", "stage": "LSF", "slot": 2, "a": "L:QF1", "b": "W:PB",     "best_of": 3, "label": "Lower Semifinal 2"},
    {"key": "LF",   "bracket": "lower", "stage": "LF",  "slot": 1, "a": "W:LSF1", "b": "W:LSF2",  "best_of": 3, "label": "Lower Final"},
    {"key": "GF",   "bracket": "grand", "stage": "GF",  "slot": 1, "a": "W:F",   "b": "W:LF",     "best_of": 5, "label": "Grand Final"},
    {"key": "P34",  "bracket": "placement", "stage": "P34",  "slot": 1, "a": "L:F",    "b": "L:LF",    "best_of": 3, "label": "3rd / 4th place"},
    {"key": "P56",  "bracket": "placement", "stage": "P56",  "slot": 1, "a": "L:SF1",  "b": "L:SF2",   "best_of": 3, "label": "5th / 6th place"},
    {"key": "P78",  "bracket": "placement", "stage": "P78",  "slot": 1, "a": "L:LSF1", "b": "L:LSF2",  "best_of": 3, "label": "7th / 8th place"},
    {"key": "P910", "bracket": "placement", "stage": "P910", "slot": 1, "a": "L:PA",   "b": "L:PB",    "best_of": 3, "label": "9th / 10th place"},
]
BY_KEY = {m["key"]: m for m in BRACKET}


# ── pure resolution (no DB; unit-tested) ─────────────────────────────────
def resolve_slots(rank_map: dict[int, int], outcomes: dict[str, tuple]) -> dict[str, tuple]:
    """{rank: team_id} + {mkey: (winner_id, loser_id)} -> {mkey: (a_id, b_id)}.

    A side is None until its source resolves (upstream match undecided)."""
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

    return {m["key"]: (side(m["a"]), side(m["b"])) for m in BRACKET}


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
    """Freeze the playoff seeding from final standings and lay out the bracket."""
    from . import db, seeding
    rank_map, incomplete = _rank_map_from_standings()
    if len(rank_map) < 10:
        raise ValueError("Need 10 ranked teams — generate and play the group stage first.")
    if incomplete:
        raise ValueError("Group stage isn't complete — every Saturday match must be final first.")
    seeding.set_setting("playoff_seeds", json.dumps(rank_map))
    slots = resolve_slots(rank_map, {})
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM lan_bracket")
        for m in BRACKET:
            a, b = slots[m["key"]]
            cur.execute(
                "INSERT INTO lan_bracket (bracket, mkey, stage, slot, source_a, source_b, "
                "team_a_id, team_b_id, status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'pending')",
                (m["bracket"], m["key"], m["stage"], m["slot"], m["a"], m["b"], a, b),
            )


def get_bracket() -> list[dict]:
    from . import db
    try:
        return db.query_all(
            """
            SELECT b.*, ta.name AS a_name, ta.tag AS a_tag, tb.name AS b_name, tb.tag AS b_tag
            FROM lan_bracket b
            LEFT JOIN lan_teams ta ON ta.id = b.team_a_id
            LEFT JOIN lan_teams tb ON tb.id = b.team_b_id
            ORDER BY FIELD(b.bracket,'upper','lower','grand','placement'),
                     FIELD(b.stage,'QF','SF','F','PI','LSF','LF','GF','P34','P56','P78','P910'), b.slot
            """
        )
    except Exception:
        return []


def bracket_exists() -> bool:
    return len(get_bracket()) > 0


def report_series(mkey: str, sa: int, sb: int):
    from . import db
    row = db.query_one("SELECT team_a_id, team_b_id FROM lan_bracket WHERE mkey=%s", (mkey,))
    if not row:
        raise ValueError("No such bracket match.")
    if row["team_a_id"] is None or row["team_b_id"] is None:
        raise ValueError("Both teams for this match aren't determined yet.")
    best_of = BY_KEY.get(mkey, {}).get("best_of", BEST_OF)
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
    resolve_dependents()


def resolve_dependents():
    """Re-fill W:/L: slots from current final outcomes. Idempotent."""
    from . import db
    rows = {r["mkey"]: r for r in db.query_all("SELECT * FROM lan_bracket")}
    outcomes = {}
    for k, r in rows.items():
        if r["status"] == "final" and r["winner_team_id"]:
            w = r["winner_team_id"]
            l = r["team_a_id"] if w == r["team_b_id"] else r["team_b_id"]
            outcomes[k] = (w, l)
    slots = resolve_slots(_stored_rank_map(), outcomes)
    with db.get_conn() as conn, conn.cursor() as cur:
        for k, (a, b) in slots.items():
            r = rows.get(k)
            if r and (r["team_a_id"] != a or r["team_b_id"] != b):
                cur.execute("UPDATE lan_bracket SET team_a_id=%s, team_b_id=%s WHERE mkey=%s", (a, b, k))
