"""Sunday bracket: auto-fed view, BO3 series reporting, admin generate."""
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
    by_key = {s["mkey"]: s for s in slots}
    matches = sched.get_matches()
    ident = ctx["ident"]
    ctx.update(
        generated=bool(db_rows),
        upper=[s for s in slots if s["bracket"] == "upper"],
        lower=[s for s in slots if s["bracket"] == "lower"],
        champion=_champ(by_key.get("F")),
        lower_champion=_champ(by_key.get("LF")),
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
