"""Saturday schedule: template view, result reporting, live standings."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from .. import auth, common, db, seeding, standings
from .. import schedule as sched
from ..templating import templates

router = APIRouter()


@router.get("/schedule", name="schedule")
def schedule_page(request: Request):
    ctx = common.base_ctx(request, "schedule")
    matches = sched.get_matches()
    teams = db.query_all("SELECT id, name, tag, seed FROM lan_teams") if matches else []
    ident = ctx["ident"]
    ctx.update(
        matches=matches,
        rounds=sched.rounds_with_teams(),          # seed-slot template fallback
        timetable=sched.SATURDAY_TIMETABLE,
        seeds_locked=sched.seeds_locked(),
        standings=standings.compute_standings(teams, matches) if matches else [],
        is_admin=auth.is_admin(request),
        my_team_id=ident["team_id"] if ident else None,
        am_captain=bool(ident and ident["is_captain"]),
        preview=seeding.get_setting("preview_banner") == "1",
    )
    return templates.TemplateResponse(request, "schedule.html", ctx)


@router.post("/schedule/report", name="report_result")
async def report(request: Request):
    ident = auth.require_login(request)
    form = await request.form()
    try:
        match_id = int(form["match_id"]); sa = int(form["score_a"]); sb = int(form["score_b"])
    except (KeyError, ValueError):
        raise HTTPException(400, "Match id and both scores required.")
    if sa < 0 or sb < 0:
        raise HTTPException(400, "Scores must be non-negative.")
    m = db.query_one("SELECT team_a_id, team_b_id FROM lan_schedule WHERE id=%s", (match_id,))
    if not m:
        raise HTTPException(404, "No such match.")
    can = auth.is_admin(request) or (
        ident["is_captain"] and ident["team_id"] in (m["team_a_id"], m["team_b_id"])
    )
    if not can:
        raise HTTPException(403, "Only a captain of one of the two teams (or staff) may report.")
    sched.report_result(match_id, sa, sb, ident["discord_id"])
    return RedirectResponse(url=request.url_for("schedule"), status_code=303)


@router.post("/admin/schedule/generate", name="schedule_generate")
def generate(request: Request):
    auth.require_admin(request)
    try:
        sched.materialize_matches()
    except ValueError as e:
        raise HTTPException(400, str(e))
    return RedirectResponse(url=request.url_for("schedule"), status_code=303)
