"""Staff-only admin: roster management + event-control hub.

Browser equivalent of tools/lan_admin.py — create teams, add/remove players,
set captains, link Discord IDs. All routes require_admin."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from .. import auth, bracket, common, db, seeding
from .. import schedule as sched
from ..templating import templates

router = APIRouter()


@router.get("/admin", name="admin")
def admin_home(request: Request):
    auth.require_admin(request)
    teams = db.query_all("SELECT id, name, tag, seed FROM lan_teams ORDER BY COALESCE(seed, 999), name")
    for t in teams:
        t["players"] = db.query_all(
            "SELECT id, display_name, discord_id, steam_id, is_captain "
            "FROM lan_players WHERE team_id=%s ORDER BY is_captain DESC, display_name",
            (t["id"],),
        )
    ctx = common.base_ctx(request, "admin")
    ctx.update(
        teams=teams,
        total_players=sum(len(t["players"]) for t in teams),
        poll_open=seeding.poll_is_open(),
        seeds_locked=sched.seeds_locked(),
        matches_generated=sched.matches_exist(),
        bracket_generated=bracket.bracket_exists(),
    )
    return templates.TemplateResponse(request, "admin.html", ctx)


@router.post("/admin/team/add", name="admin_team_add")
async def team_add(request: Request):
    auth.require_admin(request)
    f = await request.form()
    name = (f.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Team name required.")
    tag = (f.get("tag") or "").strip() or None
    try:
        db.execute("INSERT INTO lan_teams (name, tag) VALUES (%s, %s)", (name, tag))
    except Exception:
        raise HTTPException(400, f"Could not add team (name {name!r} may already exist).")
    return RedirectResponse(request.url_for("admin"), status_code=303)


@router.post("/admin/team/delete", name="admin_team_delete")
async def team_delete(request: Request):
    auth.require_admin(request)
    f = await request.form()
    db.execute("DELETE FROM lan_teams WHERE id=%s", (int(f["team_id"]),))  # players cascade
    return RedirectResponse(request.url_for("admin"), status_code=303)


@router.post("/admin/player/add", name="admin_player_add")
async def player_add(request: Request):
    auth.require_admin(request)
    f = await request.form()
    team_id = int(f["team_id"])
    display = (f.get("display_name") or "").strip()
    if not display:
        raise HTTPException(400, "Player display name required.")
    raw_discord = (f.get("discord_id") or "").strip()
    discord = int(raw_discord) if raw_discord.isdigit() else None
    steam = (f.get("steam_id") or "").strip() or None
    is_cap = 1 if f.get("is_captain") else 0
    try:
        if is_cap:  # one captain per team
            db.execute("UPDATE lan_players SET is_captain=0 WHERE team_id=%s", (team_id,))
        db.execute(
            "INSERT INTO lan_players (team_id, display_name, discord_id, steam_id, is_captain) "
            "VALUES (%s, %s, %s, %s, %s)",
            (team_id, display, discord, steam, is_cap),
        )
    except Exception:
        raise HTTPException(400, "Could not add player (that Discord ID may already be linked elsewhere).")
    return RedirectResponse(request.url_for("admin"), status_code=303)


@router.post("/admin/player/delete", name="admin_player_delete")
async def player_delete(request: Request):
    auth.require_admin(request)
    f = await request.form()
    db.execute("DELETE FROM lan_players WHERE id=%s", (int(f["player_id"]),))
    return RedirectResponse(request.url_for("admin"), status_code=303)


@router.post("/admin/player/captain", name="admin_player_captain")
async def player_captain(request: Request):
    auth.require_admin(request)
    f = await request.form()
    team_id = int(f["team_id"])
    db.execute("UPDATE lan_players SET is_captain=0 WHERE team_id=%s", (team_id,))
    db.execute("UPDATE lan_players SET is_captain=1 WHERE id=%s", (int(f["player_id"]),))
    return RedirectResponse(request.url_for("admin"), status_code=303)
