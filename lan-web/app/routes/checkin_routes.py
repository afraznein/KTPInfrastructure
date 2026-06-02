"""LAN-day check-in. Players self-check-in via Discord login; captains confirm
the team. Public board shows who's present."""
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from .. import auth, common, db
from ..templating import templates

router = APIRouter()


@router.get("/checkin", name="checkin")
def checkin_page(request: Request):
    teams = db.query_all("SELECT id, name, tag, checked_in_at FROM lan_teams ORDER BY name")
    for t in teams:
        roster = db.query_all(
            "SELECT display_name, is_captain, checked_in_at FROM lan_players "
            "WHERE team_id=%s ORDER BY is_captain DESC, display_name",
            (t["id"],),
        )
        t["roster"] = roster
        t["present"] = sum(1 for p in roster if p["checked_in_at"])
        t["total"] = len(roster)
    ctx = common.base_ctx(request, "checkin")
    ctx["teams"] = teams
    return templates.TemplateResponse(request, "checkin.html", ctx)


@router.post("/checkin/me")
def checkin_me(request: Request):
    ident = auth.require_login(request)
    db.execute("UPDATE lan_players SET checked_in_at=NOW() WHERE id=%s", (ident["player_id"],))
    return RedirectResponse(request.url_for("checkin"), status_code=303)


@router.post("/checkin/team")
def checkin_team(request: Request):
    ident = auth.require_captain(request)
    db.execute("UPDATE lan_teams SET checked_in_at=NOW() WHERE id=%s", (ident["team_id"],))
    db.execute(
        "UPDATE lan_players SET checked_in_at=NOW() WHERE id=%s AND checked_in_at IS NULL",
        (ident["player_id"],),
    )
    return RedirectResponse(request.url_for("checkin"), status_code=303)
