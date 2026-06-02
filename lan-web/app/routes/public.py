"""Public, no-auth pages."""
from fastapi import APIRouter, Request

from .. import common, db
from .. import schedule as sched
from ..templating import templates

router = APIRouter()


@router.get("/health")
def health():
    return {"status": "ok"}


def get_rosters() -> list[dict]:
    """All teams with their rosters, ordered by seed then name."""
    teams = db.query_all("SELECT * FROM lan_teams ORDER BY COALESCE(seed, 999), name")
    for t in teams:
        t["players"] = db.query_all(
            "SELECT display_name, is_captain FROM lan_players "
            "WHERE team_id=%s ORDER BY is_captain DESC, display_name",
            (t["id"],),
        )
    return teams


@router.get("/", name="index")
def index(request: Request):
    ctx = common.base_ctx(request, "briefing")
    try:
        ctx["team_count"] = db.query_one("SELECT COUNT(*) AS n FROM lan_teams")["n"]
    except Exception:
        ctx["team_count"] = 0  # home stays up even if the DB is briefly down
    return templates.TemplateResponse(request, "index.html", ctx)


@router.get("/teams", name="teams")
def teams(request: Request):
    rosters = get_rosters()
    ctx = common.base_ctx(request, "teams")
    ctx["teams"] = rosters
    ctx["team_count"] = len(rosters)
    ctx["total_players"] = sum(len(t["players"]) for t in rosters)
    return templates.TemplateResponse(request, "teams.html", ctx)


@router.get("/schedule", name="schedule")
def schedule(request: Request):
    ctx = common.base_ctx(request, "schedule")
    ctx["rounds"] = sched.rounds_with_teams()
    ctx["timetable"] = sched.SATURDAY_TIMETABLE
    ctx["seeds_locked"] = sched.seeds_locked()
    return templates.TemplateResponse(request, "schedule.html", ctx)


@router.get("/bracket", name="bracket")
def bracket(request: Request):
    return templates.TemplateResponse(request, "bracket.html", common.base_ctx(request, "bracket"))


@router.get("/rules", name="rules")
def rules(request: Request):
    return templates.TemplateResponse(request, "rules.html", common.base_ctx(request, "rules"))
