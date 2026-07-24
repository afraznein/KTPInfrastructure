"""Public, no-auth pages."""
import json
import urllib.request

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from .. import auth, bracket as bkt
from .. import common, db, ics, seeding
from .. import schedule as sched
from ..templating import templates

router = APIRouter()

# Public HLTV relay targets (frp tunnel on the data server) — order = LAN 1..5.
# The names must match the hostnames the HUD overlay reports.
_WATCH_SERVERS = [
    ("KTP LAN 1", "74.91.112.242:28020"),
    ("KTP LAN 2", "74.91.112.242:28021"),
    ("KTP LAN 3", "74.91.112.242:28022"),
    ("KTP LAN 4", "74.91.112.242:28023"),
    ("KTP LAN 5", "74.91.112.242:28024"),
]


@router.get("/health")
def health():
    return {"status": "ok"}


def _ics(text: str, filename: str) -> Response:
    return Response(
        content=text, media_type="text/calendar; charset=utf-8",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@router.get("/schedule.ics", name="schedule_ics")
def schedule_ics():
    return _ics(ics.schedule_feed(), "wsdod-lan-2026.ics")


@router.get("/team/{team_id}.ics", name="team_ics")
def team_ics(team_id: int):
    team = db.query_one("SELECT id, name FROM lan_teams WHERE id=%s", (team_id,))
    if not team:
        raise HTTPException(404, "No such team.")
    return _ics(ics.team_feed(team_id, team["name"]), f"wsdod-lan-{team_id}.ics")


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


@router.get("/team/{team_id}", name="team")
def team_detail(request: Request, team_id: int):
    team = db.query_one("SELECT * FROM lan_teams WHERE id=%s", (team_id,))
    if not team:
        raise HTTPException(404, "No such team.")
    players = db.query_all(
        "SELECT display_name, is_captain FROM lan_players WHERE team_id=%s "
        "ORDER BY is_captain DESC, display_name",
        (team_id,),
    )
    saturday = sched.team_schedule(team_id)
    sunday = bkt.team_bracket(team_id)
    # Per-team match lists follow the same publish gate as the full schedule/
    # bracket pages: staff-only until an admin publishes. Hidden ones become a
    # "pending publish" note rather than exposing pairings.
    is_admin = auth.is_admin(request)
    sat_hidden = bool(saturday) and not seeding.reveal_schedule(
        is_admin, seeding.is_published("schedule_sat_published"))
    sun_hidden = bool(sunday) and not seeding.reveal_schedule(
        is_admin, seeding.is_published("schedule_sun_published"))
    if sat_hidden:
        saturday = []
    if sun_hidden:
        sunday = []
    ctx = common.base_ctx(request, "teams")
    ctx.update(
        team=team,
        players=players,
        saturday=saturday,
        sunday=sunday,
        sat_hidden=sat_hidden,
        sun_hidden=sun_hidden,
        wins=sum(1 for m in saturday if m["result"] == "W"),
        losses=sum(1 for m in saturday if m["result"] == "L"),
    )
    return templates.TemplateResponse(request, "team.html", ctx)


@router.get("/rules", name="rules")
def rules(request: Request):
    return templates.TemplateResponse(request, "rules.html", common.base_ctx(request, "rules"))


@router.get("/watch", name="watch")
def watch(request: Request):
    ctx = common.base_ctx(request, "watch")
    try:
        ctx["twitch_channel"] = (seeding.get_setting("twitch_channel") or "").strip()
    except Exception:
        ctx["twitch_channel"] = ""
    return templates.TemplateResponse(request, "watch.html", ctx)


@router.get("/watch/servers.json", name="watch_servers")
def watch_servers():
    """Live field-feed status for the watch page. Reads the HUD overlay backend
    through the local frp tunnel; falls back to offline-per-server so the board
    never breaks."""
    live: dict[str, dict] = {}
    try:
        with urllib.request.urlopen("http://127.0.0.1:28080/api/servers", timeout=4) as r:
            for s in json.loads(r.read()).get("servers", []):
                if s.get("hostname"):
                    live[s["hostname"]] = s
    except Exception:
        pass
    servers = []
    for name, connect in _WATCH_SERVERS:
        s = live.get(name)
        servers.append({
            "name": name,
            "connect": connect,
            "online": bool(s.get("online")) if s else False,
            "players": int(s.get("players") or 0) if s else 0,
        })
    return {"servers": servers, "ok": bool(live)}
