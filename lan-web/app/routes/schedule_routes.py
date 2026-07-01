"""Saturday schedule: template view, result reporting, live standings."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from .. import auth, common, db, notify, seeding, standings
from .. import schedule as sched
from ..templating import templates

router = APIRouter()


@router.get("/schedule", name="schedule")
def schedule_page(request: Request):
    ctx = common.base_ctx(request, "schedule")
    matches = sched.get_matches()
    teams = db.query_all("SELECT id, name, tag, seed FROM lan_teams") if matches else []
    ident = ctx["ident"]
    n = sched.team_count() or 10
    ctx.update(
        matches=matches,
        rounds=sched.rounds_with_teams(),          # seed-slot template fallback
        timetable=sched.SATURDAY_TIMETABLE,
        comp_maps=sched.COMP_MAPS,
        n_teams=n, bye_seeds=16 - n if 10 <= n <= 12 else 6,
        seeds_locked=sched.seeds_locked(),
        standings=standings.compute_standings(teams, matches) if matches else [],
        is_admin=auth.is_admin(request),
        # Generated matches/standings stay staff-only until an admin publishes.
        schedule_sat_published=seeding.is_published("schedule_sat_published"),
        show_schedule=seeding.reveal_schedule(
            auth.is_admin(request), seeding.is_published("schedule_sat_published")),
        my_team_id=ident["team_id"] if ident else None,
        am_captain=bool(ident and ident["is_captain"]),
        preview=seeding.get_setting("preview_banner") == "1",
        auto_refresh=60,
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


@router.post("/admin/schedule/station", name="schedule_set_station")
async def set_station(request: Request):
    auth.require_admin(request)
    f = await request.form()
    try:
        match_id = int(f["match_id"])
    except (KeyError, ValueError):
        raise HTTPException(400, "match id required")
    raw = (f.get("station") or "").strip()
    station = int(raw) if raw.isdigit() and 1 <= int(raw) <= 6 else None
    sched.set_station(match_id, station)
    if station:  # ping both captains: you're up on Server N
        m = db.query_one(
            "SELECT m.round, m.team_a_id, m.team_b_id, ta.name a, tb.name b FROM lan_schedule m "
            "JOIN lan_teams ta ON ta.id=m.team_a_id JOIN lan_teams tb ON tb.id=m.team_b_id WHERE m.id=%s",
            (match_id,),
        )
        if m:
            notify.notify_captains(
                [m["team_a_id"], m["team_b_id"]],
                f"\U0001f3ae You're up — Round {m['round']}: **{m['a']}** vs **{m['b']}** on **Server {station}**. Report to your station.",
            )
    return RedirectResponse(url=request.url_for("schedule"), status_code=303)


@router.post("/admin/schedule/round-map", name="schedule_set_round_map")
async def set_round_map(request: Request):
    auth.require_admin(request)
    f = await request.form()
    try:
        rnd = int(f["round"])
    except (KeyError, ValueError):
        raise HTTPException(400, "round required")
    sched.set_round_map(rnd, (f.get("map") or "").strip()[:48] or None)
    return RedirectResponse(url=request.url_for("schedule"), status_code=303)
