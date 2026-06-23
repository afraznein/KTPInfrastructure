"""Sunday bracket: auto-fed view, BO3 series reporting, admin generate."""
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from .. import auth, bracket, common, db, notify, seeding
from .. import schedule as sched
from ..templating import templates

router = APIRouter()


def _champ(row):
    if not row or row["status"] != "final" or not row["winner_team_id"]:
        return None
    return row["a_name"] if row["winner_team_id"] == row["team_a_id"] else row["b_name"]


@router.get("/bracket", name="bracket")
def bracket_page(request: Request):
    ctx = common.base_ctx(request, "bracket")
    db_rows = {r["mkey"]: r for r in bracket.get_bracket()}
    # Always draw the full shape for the active team count; overlay DB data where present.
    mats = bracket.active_matches()
    slots = []
    for m in mats:
        r = db_rows.get(m["key"], {})
        slots.append({
            "mkey": m["key"], "label": m["label"], "bracket": m["bracket"], "stage": m["stage"],
            "source_a": m["a"], "source_b": m["b"],
            "a_name": r.get("a_name"), "b_name": r.get("b_name"),
            "team_a_id": r.get("team_a_id"), "team_b_id": r.get("team_b_id"),
            "score_a": r.get("score_a"), "score_b": r.get("score_b"),
            "winner_team_id": r.get("winner_team_id"), "status": r.get("status", "pending"),
            "station": r.get("station"), "map": r.get("map"),
        })
    by = {s["mkey"]: s for s in slots}

    # playoff seeds → seed chips + the bye/drop "round-1" boxes that make the
    # format a clean 4->2->1 tree the connectors can line up against.
    try:
        rank_map = {int(k): v for k, v in json.loads(seeding.get_setting("playoff_seeds") or "{}").items()}
    except Exception:
        rank_map = {}
    teamrows = {t["id"]: t for t in db.query_all("SELECT id, name FROM lan_teams")}
    seed_of = {tid: rank for rank, tid in rank_map.items()}

    # Seeding stays blind on the bracket too: while the seeding poll is open,
    # non-staff see structure only (Seed N), never which team holds which seed —
    # otherwise the locked seeds would leak the poll result during open voting.
    reveal_seeds = auth.is_admin(request) or not seeding.poll_is_open()

    def _comp(slot, side):
        tid = slot["team_%s_id" % side]
        name = slot["%s_name" % side]
        if not name or not reveal_seeds:  # unresolved, or seeding still blind — show the source
            kind, ref = slot["source_%s" % side].split(":")
            label = {"W": "Winner ", "L": "Loser ", "seed": "Seed "}[kind] + ref
            return {"name": label, "seed": None, "score": None, "win": False, "tbd": True}
        return {"name": name, "seed": seed_of.get(tid), "score": slot["score_%s" % side],
                "win": slot["winner_team_id"] == tid, "tbd": False}

    def _match(mkey):
        s = by[mkey]
        return {"top": _comp(s, "a"), "bottom": _comp(s, "b"), "slot": s,
                "best_of": bracket.BY_KEY[mkey]["best_of"],
                "label": bracket.BY_KEY[mkey]["label"],
                "time": bracket.match_time(mkey), "map": s.get("map")}

    # Group the active layout's matches by stage so the championship and
    # consolation render the same regardless of team count (10/11/12).
    by_stage: dict[str, list[str]] = {}
    for m in mats:
        by_stage.setdefault(m["stage"], []).append(m["key"])

    def _round(title, keys):
        ms = [_match(k) for k in keys]
        return {"title": title, "time": ms[0]["time"] if ms else None,
                "bo": ms[0]["best_of"] if ms else 3, "matches": ms}

    # Championship — single elim, rendered as ONE bracket: a Play-in column
    # aligned to the QF rows it feeds, then a clean QF -> SF -> Final tree.
    playin = [_match(k) for k in by_stage.get("PI", [])]
    pi_by_key = {k: _match(k) for k in by_stage.get("PI", [])}
    # For each QF (in order), the play-in match feeding it (via "W:PIx"), or None.
    # Same-index alignment lets a straight connector line up the PI box with its QF.
    playin_cells, qf_matches = [], []
    for k in by_stage.get("QF", []):
        s = by[k]
        feeder = next((pi_by_key.get(s[side].split(":", 1)[1])
                       for side in ("source_a", "source_b")
                       if s[side].startswith("W:PI")), None)
        playin_cells.append(feeder)
        mm = _match(k)
        mm["fed"] = feeder is not None
        qf_matches.append(mm)
    upper_rounds = [
        {"title": "Play-in", "bo": 1, "playin": True, "cells": playin_cells,
         "time": playin[0]["time"] if playin else None},
        {"title": "Quarterfinals", "time": qf_matches[0]["time"] if qf_matches else None,
         "bo": qf_matches[0]["best_of"] if qf_matches else 3, "matches": qf_matches},
        _round("Semifinals", by_stage.get("SF", [])),
        _round("Final", by_stage.get("F", [])),
    ]
    # Consolation / lower bracket — parallel, never feeds the championship.
    # Groups (and their depth) come from the active layout.
    consolation_rounds = [_round(g["title"], g["mkeys"]) for g in bracket.consolation_groups()]

    def _runner(row):
        if not row or row["status"] != "final" or not row["winner_team_id"]:
            return None
        return row["b_name"] if row["winner_team_id"] == row["team_a_id"] else row["a_name"]

    matches = sched.get_matches()
    ident = ctx["ident"]
    n = bracket.active_count()
    byes = 16 - n                      # main bracket is always 8
    ctx.update(
        generated=bool(db_rows),
        n_teams=n, bye_seeds=byes, playin_lo=byes + 1, playin_hi=n,
        playin=playin,
        upper_rounds=upper_rounds,
        consolation_rounds=consolation_rounds,
        champion=_champ(by.get("F")),
        runner_up=_runner(by.get("F")),
        placements=bracket.placement_order() if db_rows else [],
        group_complete=bool(matches) and all(m["status"] == "final" for m in matches),
        is_admin=auth.is_admin(request),
        my_team_id=ident["team_id"] if ident else None,
        am_captain=bool(ident and ident["is_captain"]),
        preview=seeding.get_setting("preview_banner") == "1",
        auto_refresh=60,
    )
    return templates.TemplateResponse(request, "bracket.html", ctx)


@router.post("/bracket/report", name="bracket_report")
async def report(request: Request):
    ident = auth.require_login(request)
    form = await request.form()
    mkey = form.get("mkey", "")
    try:
        sa = int(form["score_a"]); sb = int(form["score_b"])
    except (KeyError, ValueError):
        raise HTTPException(400, "Both series scores required.")
    if sa < 0 or sb < 0:
        raise HTTPException(400, "Scores must be non-negative.")
    row = db.query_one("SELECT team_a_id, team_b_id FROM lan_bracket WHERE mkey=%s", (mkey,))
    if not row:
        raise HTTPException(404, "No such bracket match.")
    can = auth.is_admin(request) or (
        ident["is_captain"] and ident["team_id"] in (row["team_a_id"], row["team_b_id"])
    )
    if not can:
        raise HTTPException(403, "Only a captain of one of the two teams (or staff) may report.")
    try:
        bracket.report_series(mkey, sa, sb, actor=ident["discord_id"])
    except ValueError as e:
        raise HTTPException(400, str(e))
    return RedirectResponse(url=request.url_for("bracket"), status_code=303)


@router.post("/admin/bracket/generate", name="bracket_generate")
def generate(request: Request):
    auth.require_admin(request)
    try:
        bracket.generate_bracket()
    except ValueError as e:
        raise HTTPException(400, str(e))
    return RedirectResponse(url=request.url_for("bracket"), status_code=303)


@router.post("/admin/bracket/station", name="bracket_set_station")
async def set_station(request: Request):
    auth.require_admin(request)
    f = await request.form()
    mkey = f.get("mkey", "")
    if not db.query_one("SELECT 1 FROM lan_bracket WHERE mkey=%s", (mkey,)):
        raise HTTPException(404, "No such bracket match.")
    raw = (f.get("station") or "").strip()
    station = int(raw) if raw.isdigit() and 1 <= int(raw) <= 6 else None
    bracket.set_station(mkey, station)
    if station:
        row = db.query_one(
            "SELECT b.team_a_id, b.team_b_id, ta.name a, tb.name b FROM lan_bracket b "
            "LEFT JOIN lan_teams ta ON ta.id=b.team_a_id LEFT JOIN lan_teams tb ON tb.id=b.team_b_id WHERE b.mkey=%s",
            (mkey,),
        )
        if row and row["team_a_id"] and row["team_b_id"]:
            label = bracket.BY_KEY.get(mkey, {}).get("label", mkey)
            notify.notify_captains(
                [row["team_a_id"], row["team_b_id"]],
                f"\U0001f3ae You're up — {label}: **{row['a']}** vs **{row['b']}** on **Server {station}**. Report to your station.",
            )
    return RedirectResponse(url=request.url_for("bracket"), status_code=303)
