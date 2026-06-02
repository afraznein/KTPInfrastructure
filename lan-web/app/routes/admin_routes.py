"""Staff-only admin: roster management + event-control hub.

Browser equivalent of tools/lan_admin.py — create teams, add/remove players,
set captains, link Discord IDs. All routes require_admin."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from .. import auth, bracket, common, db, seeding
from .. import schedule as sched
from ..config import settings
from ..templating import templates

router = APIRouter()


def _staff_view(me: int) -> tuple[list[dict], list[dict]]:
    """Returns (current admins, promotable operators).

    Admins merge env bootstrap ids with web-granted rows; labels resolve from
    the roster where a Discord id is linked. Config admins are never removable;
    you can't revoke yourself (so you can't lock yourself out)."""
    roster = {
        int(p["discord_id"]): p
        for p in db.query_all(
            "SELECT p.discord_id, p.display_name, t.name AS team "
            "FROM lan_players p JOIN lan_teams t ON t.id = p.team_id "
            "WHERE p.discord_id IS NOT NULL"
        )
    }
    db_rows = {int(r["discord_id"]): r for r in auth.list_db_admins()}
    env_ids = set(settings.admin_discord_ids)
    admins = []
    for did in sorted(env_ids | set(db_rows)):
        rp = roster.get(did)
        row = db_rows.get(did)
        label = (row and row.get("label")) or (rp and rp["display_name"]) or None
        is_env = did in env_ids
        admins.append({
            "discord_id": did,
            "label": label,
            "team": rp["team"] if rp else None,
            "source": "config" if is_env else "web",
            "is_self": did == me,
            "removable": (not is_env) and did != me,
        })
    taken = env_ids | set(db_rows)
    candidates = [
        {"discord_id": did, "display_name": p["display_name"], "team": p["team"]}
        for did, p in sorted(roster.items(), key=lambda kv: (kv[1]["team"] or "", kv[1]["display_name"]))
        if did not in taken
    ]
    return admins, candidates


@router.get("/admin", name="admin")
def admin_home(request: Request):
    me = auth.require_admin(request)
    teams = db.query_all("SELECT id, name, tag, seed FROM lan_teams ORDER BY COALESCE(seed, 999), name")
    for t in teams:
        t["players"] = db.query_all(
            "SELECT id, display_name, discord_id, steam_id, is_captain "
            "FROM lan_players WHERE team_id=%s ORDER BY is_captain DESC, display_name",
            (t["id"],),
        )
    admins, admin_candidates = _staff_view(int(me))
    ctx = common.base_ctx(request, "admin")
    ctx.update(
        teams=teams,
        total_players=sum(len(t["players"]) for t in teams),
        poll_open=seeding.poll_is_open(),
        seeds_locked=sched.seeds_locked(),
        matches_generated=sched.matches_exist(),
        bracket_generated=bracket.bracket_exists(),
        admins=admins,
        admin_candidates=admin_candidates,
    )
    return templates.TemplateResponse(request, "admin.html", ctx)


@router.post("/admin/staff/add", name="admin_grant")
async def admin_grant(request: Request):
    granter = auth.require_admin(request)
    f = await request.form()
    raw = (f.get("discord_id") or "").strip()
    if not raw.isdigit():
        raise HTTPException(400, "A numeric Discord ID is required.")
    did = int(raw)
    label = (f.get("label") or "").strip() or None
    if not label:  # fall back to the roster alias, if this id is on a team
        rp = db.query_one("SELECT display_name FROM lan_players WHERE discord_id=%s LIMIT 1", (did,))
        label = rp["display_name"] if rp else None
    db.execute(
        "INSERT INTO lan_admins (discord_id, label, added_by) VALUES (%s, %s, %s) "
        "ON DUPLICATE KEY UPDATE label = COALESCE(VALUES(label), label)",
        (did, label, int(granter)),
    )
    return RedirectResponse(request.url_for("admin"), status_code=303)


@router.post("/admin/staff/remove", name="admin_revoke")
async def admin_revoke(request: Request):
    me = auth.require_admin(request)
    f = await request.form()
    did = int(f["discord_id"])
    if did == int(me):
        raise HTTPException(400, "You can't revoke your own staff access.")
    # Config (env) admins aren't in this table, so this can't touch them.
    db.execute("DELETE FROM lan_admins WHERE discord_id=%s", (did,))
    return RedirectResponse(request.url_for("admin"), status_code=303)


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


@router.post("/admin/team/edit", name="admin_team_edit")
async def team_edit(request: Request):
    auth.require_admin(request)
    f = await request.form()
    team_id = int(f["team_id"])
    name = (f.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Team name required.")
    tag = (f.get("tag") or "").strip() or None
    try:
        db.execute("UPDATE lan_teams SET name=%s, tag=%s WHERE id=%s", (name, tag, team_id))
    except Exception:
        raise HTTPException(400, f"Could not rename (name {name!r} may already be taken).")
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
        raise HTTPException(400, "Player alias required.")
    steam = (f.get("steam_id") or "").strip()
    if not steam:
        raise HTTPException(400, "Player Steam ID required.")
    raw_discord = (f.get("discord_id") or "").strip()
    discord = int(raw_discord) if raw_discord.isdigit() else None
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
