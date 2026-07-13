"""Group-stage standings with the tiebreak ladder.

Order: wins -> head-to-head (within the tied group) -> Buchholz (sum of
opponents' wins) -> score differential -> seed. Pure function over team
rows + final match rows; unit-tested."""
from __future__ import annotations

from fractions import Fraction
from itertools import groupby


def compute_standings(teams: list[dict], matches: list[dict]) -> list[dict]:
    by_id = {t["id"]: t for t in teams}
    stat = {
        t["id"]: {"team": t, "played": 0, "wins": 0, "losses": 0, "draws": 0,
                  "pf": 0, "pa": 0, "opps": [], "results": {}}
        for t in teams
    }

    for m in matches:
        if m.get("status") != "final" or m.get("score_a") is None or m.get("score_b") is None:
            continue
        a, b = m["team_a_id"], m["team_b_id"]
        if a not in stat or b not in stat:
            continue
        sa, sb = m["score_a"], m["score_b"]
        sta, stb = stat[a], stat[b]
        sta["played"] += 1; stb["played"] += 1
        sta["pf"] += sa; sta["pa"] += sb
        stb["pf"] += sb; stb["pa"] += sa
        sta["opps"].append(b); stb["opps"].append(a)
        if sa > sb:
            sta["wins"] += 1; stb["losses"] += 1
            sta["results"][b] = "W"; stb["results"][a] = "L"
        elif sb > sa:
            stb["wins"] += 1; sta["losses"] += 1
            stb["results"][a] = "W"; sta["results"][b] = "L"
        else:
            sta["draws"] += 1; stb["draws"] += 1
            sta["results"][b] = "D"; stb["results"][a] = "D"

    for s in stat.values():
        s["diff"] = s["pf"] - s["pa"]
        s["buchholz"] = sum(stat[o]["wins"] for o in s["opps"] if o in stat)

    def seed_key(tid: int) -> int:
        sd = by_id[tid].get("seed")
        return sd if sd is not None else 999

    # Primary key is win % (exact via Fraction), so an odd field where some teams
    # play an extra group game isn't skewed by raw win count. With equal games
    # (10/12 teams) this is identical to ordering by wins.
    def win_pct(tid: int) -> Fraction:
        p = stat[tid]["played"]
        return Fraction(stat[tid]["wins"], p) if p else Fraction(0)

    ordered: list[int] = []
    ids_by_pct = sorted((t["id"] for t in teams), key=lambda t: -win_pct(t))
    for _pct, grp in groupby(ids_by_pct, key=win_pct):
        g = list(grp)
        if len(g) > 1:
            def h2h(tid, group=g):  # wins against others in this tied group
                return sum(1 for o in group if o != tid and stat[tid]["results"].get(o) == "W")
            g.sort(key=lambda tid: (-h2h(tid), -stat[tid]["buchholz"], -stat[tid]["diff"], seed_key(tid)))
        ordered.extend(g)

    return [dict(rank=i + 1, **stat[tid]) for i, tid in enumerate(ordered)]
