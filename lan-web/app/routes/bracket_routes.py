"""Sunday bracket: auto-fed view, BO3 series reporting, admin generate."""
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from .. import auth, bracket, common, db, seeding
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
    # Always draw the full shape from the BRACKET constant; overlay DB data where present.
    slots = []
    for m in bracket.BRACKET:
        r = db_rows.get(m["key"], {})
        slots.append({
            "mkey": m["key"], "label": m["label"], "bracket": m["bracket"], "stage": m["stage"],
            "source_a": m["a"], "source_b": m["b"],
            "a_name": r.get("a_name"), "b_name": r.get("b_name"),
            "team_a_id": r.get("team_a_id"), "team_b_id": r.get("team_b_id"),
            "score_a": r.get("score_a"), "score_b": r.get("score_b"),
            "winner_team_id": r.get("winner_team_id"), "status": r.get("status", "pending"),
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

    def _comp(slot, side):
        tid = slot["team_%s_id" % side]
        name = slot["%s_name" % side]
        if not name:  # unresolved — show the source (Seed 3 / Winner QF2 / Loser QF1)
            kind, ref = slot["source_%s" % side].split(":")
            label = {"W": "Winner ", "L": "Loser ", "seed": "Seed "}[kind] + ref
            return {"name": label, "seed": None, "score": None, "win": False, "tbd": True}
        return {"name": name, "seed": seed_of.get(tid), "score": slot["score_%s" % side],
                "win": slot["winner_team_id"] == tid, "tbd": False}

    def _match(mkey):
        s = by[mkey]
        return {"top": _comp(s, "a"), "bottom": _comp(s, "b"), "slot": s}

    def _adv(team_id, label, bottom):
        if team_id and team_id in teamrows:
            top = {"name": teamrows[team_id]["name"], "seed": seed_of.get(team_id), "score": None, "win": True, "tbd": False}
        else:
            top = {"name": label, "seed": None, "score": None, "win": False, "tbd": True}
        return {"top": top, "bottom": {"name": bottom, "seed": None, "score": None, "win": False, "tbd": True}, "slot": None}

    def _loser(mkey):
        q = by[mkey]
        if q["status"] == "final" and q["winner_team_id"]:
            return q["team_a_id"] if q["winner_team_id"] == q["team_b_id"] else q["team_b_id"]
        return None

    upper_rounds = [
        {"title": "Quarterfinals", "matches": [_adv(rank_map.get(1), "Seed 1", "BYE"), _match("QF2"),
                                               _match("QF1"), _adv(rank_map.get(2), "Seed 2", "BYE")]},
        {"title": "Semifinals", "matches": [_match("SF1"), _match("SF2")]},
        {"title": "Final", "matches": [_match("F")]},
    ]
    lower_rounds = [
        {"title": "Play-ins", "matches": [_adv(_loser("QF2"), "Loser QF2", "↓ dropped"), _match("PA"),
                                          _match("PB"), _adv(_loser("QF1"), "Loser QF1", "↓ dropped")]},
        {"title": "Lower Semifinals", "matches": [_match("LSF1"), _match("LSF2")]},
        {"title": "Lower Final", "matches": [_match("LF")]},
    ]

    matches = sched.get_matches()
    ident = ctx["ident"]
    ctx.update(
        generated=bool(db_rows),
        upper_rounds=upper_rounds,
        lower_rounds=lower_rounds,
        champion=_champ(by.get("F")),
        lower_champion=_champ(by.get("LF")),
        group_complete=bool(matches) and all(m["status"] == "final" for m in matches),
        is_admin=auth.is_admin(request),
        my_team_id=ident["team_id"] if ident else None,
        am_captain=bool(ident and ident["is_captain"]),
        preview=seeding.get_setting("preview_banner") == "1",
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
        bracket.report_series(mkey, sa, sb)
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
