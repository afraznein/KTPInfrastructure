"""Staff-only admin: roster management + event-control hub.

Browser equivalent of tools/lan_admin.py — create teams, add/remove players,
set captains, link Discord IDs. All routes require_admin."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool

from .. import (admin_audit, audit, auth, bracket, common, db, mapskip, notify,
                parse, seeding)
from .. import schedule as sched
from ..config import settings
from ..templating import templates

router = APIRouter()


def _norm_steam(raw: str) -> str | None:
    """Store Steam IDs in the STEAM_universe:Y:Z form the AC tables use.

    60 of 62 rows were typed bare and one carried a trailing backtick, so a
    verbatim join to ktp_ac_players matched 2. Prepends to whatever was entered
    rather than composing a prefix -- the AC side is not uniformly STEAM_0, and
    inventing the universe digit would point the row at a different account.
    """
    s = (raw or "").strip().strip("`'\"")
    if not s:
        return None
    if s.upper().startswith("STEAM_"):
        return "STEAM_" + s[6:]
    return "STEAM_" + s if s.count(":") == 2 else s


def _player_note(display, steam, discord) -> str:
    """One readable line of what a roster row holds, for the audit log. The
    Discord id is in it because rewriting one silently re-attributes every
    grant that took its label from the roster."""
    return f"{display or '?'} / {steam or '-'} / discord {discord or '-'}"


def _staff_view(me: int) -> tuple[list[dict], list[dict]]:
    """Returns (current admins, promotable players).

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
    master_ids = set(settings.master_admin_discord_ids)
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
            # Masters alone can tick an award onto the public board, and the row
            # looked identical to ordinary staff. Env-only, so there is nothing
            # to grant here — it is reported, not editable.
            "is_master": did in master_ids,
            # Only the when; who granted it is a bare snowflake here and a named
            # actor in the staff action log.
            "granted_at": row.get("added_at") if row else None,
            "is_self": did == me,
            "removable": (not is_env) and did != me,
            # A config admin who also has a table row: the row does nothing,
            # and /staff/remove refuses env ids, so nothing else can clear it.
            "stale_row": is_env and did in db_rows,
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
        map_skip_poll_open=mapskip.poll_is_open(),
        skip_map=mapskip.locked_skip_map(),
        seeds_locked=sched.seeds_locked(),
        matches_generated=sched.matches_exist(),
        bracket_generated=bracket.bracket_exists(),
        admins=admins,
        admin_candidates=admin_candidates,
        announcement=seeding.get_setting("announcement") or "",
        crosspost_configured=bool(settings.discord_webhook_url),
        crosspost_result=request.query_params.get("dw"),
        seeding_published=seeding.is_published("seeding_results_published"),
        map_skip_published=seeding.is_published("map_skip_results_published"),
        schedule_sat_published=seeding.is_published("schedule_sat_published"),
        schedule_sun_published=seeding.is_published("schedule_sun_published"),
        stats_published=seeding.is_published("stats_published"),
        awards_published=seeding.is_published("awards_published"),
    )
    return templates.TemplateResponse(request, "admin.html", ctx)


@router.post("/admin/publish", name="admin_publish")
async def admin_publish(request: Request):
    """Toggle a public-reveal gate (seeding/map-skip results, Sat/Sun schedule).
    Reversible: publish to reveal, unpublish to pull it back. Redirects to the
    page the button was on (validated to a local path) so staff stay in place."""
    auth.require_admin(request)
    f = await request.form()
    flag = (f.get("flag") or "").strip()
    if flag not in seeding.PUBLISH_FLAGS:
        raise HTTPException(400, "Unknown publish target.")
    was = seeding.is_published(flag)
    now = bool(f.get("publish"))
    stmts = [seeding.set_setting_stmt(flag, "1" if now else "0")]
    # Every individual award tick is logged; "made the whole board public" is the
    # larger act and was the one with no record. The read is not atomic with the
    # write, so simultaneous posts can still each log the same flip.
    if now != was:
        stmts.append(admin_audit.stmt_request(request, "publish_flag", flag, int(was), int(now)))
    db.execute_all(stmts)
    target = common.safe_next(f.get("next")) or str(request.url_for("admin"))
    return RedirectResponse(target, status_code=303)


@router.post("/admin/announce", name="admin_announce")
async def admin_announce(request: Request):
    """Set or clear the site-wide broadcast strip shown on every page, and
    cross-post it to Discord unless staff untick the box.

    Only new or edited text posts — staff re-save this form routinely, and a
    live event is the worst place to double-ping a role. Clearing never posts.
    The skip is reported back, never silent: staff must be able to tell a ping
    from a no-op. Read-then-compare is not atomic, so a genuine double-submit
    can still double-post; the form disables its buttons to make that unlikely."""
    auth.require_admin(request)
    f = await request.form()
    text = (f.get("announcement") or "").strip()[:240].strip()
    previous = (seeding.get_setting("announcement") or "").strip()
    stmts = [seeding.set_setting_stmt("announcement", text)]
    # The strip is on every page, so setting or clearing it is a site-wide act.
    # A re-save of the same words is not a decision and gets no row.
    if text != previous:
        stmts.append(admin_audit.stmt_request(request, "announce", "announcement",
                                              previous or None, text or None))
    db.execute_all(stmts)
    target = str(request.url_for("admin"))
    if text and f.get("crosspost"):
        if text == previous:
            target += "?dw=skip"
        else:
            # post_announcement does blocking urllib I/O — keep it off the event loop.
            ok = await run_in_threadpool(notify.post_announcement, text)
            target += "?dw=ok" if ok else "?dw=fail"
    return RedirectResponse(target, status_code=303)


@router.get("/admin/audit", name="audit_log")
def audit_view(request: Request):
    auth.require_admin(request)
    rows = audit.recent(200)
    sched_lbl = {str(m["id"]): f"R{m['round']}: {m['a_name']} v {m['b_name']}" for m in sched.get_matches()}
    brk_lbl = {}
    for r in bracket.get_bracket():
        lbl = bracket.BY_KEY.get(r["mkey"], {}).get("label", r["mkey"])
        brk_lbl[r["mkey"]] = f"{lbl}: {r.get('a_name') or '?'} v {r.get('b_name') or '?'}"
    team_names = {t["id"]: t["name"] for t in db.query_all("SELECT id, name FROM lan_teams")}
    ids = {int(r["actor"]) for r in rows if r["actor"]}
    actor_names = {}
    if ids:
        ph = ",".join(["%s"] * len(ids))
        for p in db.query_all(f"SELECT discord_id, display_name FROM lan_players WHERE discord_id IN ({ph})", tuple(ids)):
            actor_names[int(p["discord_id"])] = p["display_name"]
    for r in rows:
        r["label"] = sched_lbl.get(r["ref"]) if r["scope"] == "schedule" else brk_lbl.get(r["ref"], r["ref"])
        r["actor_name"] = actor_names.get(int(r["actor"])) if r["actor"] else None
        r["prev_winner_name"] = team_names.get(r["prev_winner"])
        r["new_winner_name"] = team_names.get(r["new_winner"])
    ctx = common.base_ctx(request, "admin")
    ctx["rows"] = rows
    return templates.TemplateResponse(request, "audit.html", ctx)


@router.post("/admin/audit/undo", name="audit_undo")
async def audit_undo(request: Request):
    me = auth.require_admin(request)
    f = await request.form()
    try:
        audit.undo(int(f["audit_id"]), int(me))
    except (KeyError, ValueError) as e:
        raise HTTPException(400, str(e))
    return RedirectResponse(request.url_for("audit_log"), status_code=303)


AUDIT_PAGE = 50


@router.get("/admin/audit-log", name="admin_audit_log")
def admin_audit_log(request: Request, page: int = 1, action: str = "", target: str = ""):
    """Staff decisions — award ticks, retitles, staff grants — newest first.

    Filterable because it is not evenly interesting: one weekend of award ticks
    buries every staff grant, so the rare decisions are the ones that fall off
    the first page.

    A different record from /admin/audit, which is match results and carries an
    undo; nothing here is reversible, so it is read-only by design."""
    auth.require_admin(request)
    page = max(1, page)
    action = (action or "").strip()[:48]
    target = (target or "").strip()[:160]
    total = admin_audit.count(action, target)
    ctx = common.base_ctx(request, "admin")
    ctx.update(
        rows=admin_audit.recent(AUDIT_PAGE, (page - 1) * AUDIT_PAGE, action, target),
        page=page,
        pages=max(1, -(-total // AUDIT_PAGE)),
        total=total,
        action_counts=admin_audit.action_counts(),
        f_action=action,
        f_target=target,
        filtered=bool(action or target),
    )
    return templates.TemplateResponse(request, "admin_audit.html", ctx)


@router.get("/admin/photo-requests", name="photo_requests")
def photo_requests(request: Request):
    """Photo takedown queue — pending first, handled kept for the record."""
    auth.require_admin(request)
    rows = db.query_all(
        "SELECT r.*, ph.stored_name, ph.caption "
        "FROM lan_photo_removal_requests r LEFT JOIN lan_photos ph ON ph.id = r.photo_id "
        "ORDER BY r.status = 'handled', r.created_at DESC"
    )
    ctx = common.base_ctx(request, "admin")
    ctx["rows"] = rows
    ctx["pending"] = sum(1 for r in rows if r["status"] == "pending")
    return templates.TemplateResponse(request, "photo_requests.html", ctx)


@router.post("/admin/photo-requests/handled", name="photo_request_handled")
async def photo_request_handled(request: Request):
    me = auth.require_admin(request)
    f = await request.form()
    req_id = parse.as_int(f.get("request_id"))
    if req_id is None:
        raise HTTPException(400, "A request id is required.")
    # Closing a takedown request is a decision about someone else's photo, so it
    # gets a record. Re-posting the button on one already handled changes
    # nothing and must not log that it did.
    if not db.query_one(
        "SELECT id FROM lan_photo_removal_requests WHERE id=%s AND status='pending'",
        (req_id,),
    ):
        return RedirectResponse(request.url_for("photo_requests"), status_code=303)
    db.execute_all([
        ("UPDATE lan_photo_removal_requests SET status='handled', handled_by=%s, "
         "handled_at=NOW() WHERE id=%s AND status='pending'", (int(me), req_id)),
        admin_audit.stmt_request(request, "photo_request_handled", f"request:{req_id}",
                                 "pending", "handled"),
    ])
    return RedirectResponse(request.url_for("photo_requests"), status_code=303)


@router.post("/admin/staff/add", name="admin_grant")
async def admin_grant(request: Request):
    granter = auth.require_admin(request)
    f = await request.form()
    did = parse.snowflake(f.get("discord_id"))
    if did is None:
        raise HTTPException(400, "A numeric Discord ID is required.")
    # A row for an env admin grants nothing and cannot be revoked here, so
    # creating one only leaves something stuck in the table.
    if did in settings.admin_discord_ids:
        raise HTTPException(400, "Already staff from the server environment — "
                                 "there is nothing to grant here.")
    label = (f.get("label") or "").strip() or None
    if not label:  # fall back to the roster alias, if this id is on a team
        rp = db.query_one("SELECT display_name FROM lan_players WHERE discord_id=%s LIMIT 1", (did,))
        label = rp["display_name"] if rp else None
    db.execute_all([
        ("INSERT INTO lan_admins (discord_id, label, added_by) VALUES (%s, %s, %s) "
         "ON DUPLICATE KEY UPDATE label = COALESCE(VALUES(label), label)",
         (did, label, int(granter))),
        admin_audit.stmt_request(request, "staff_add", did, None, label),
    ])
    return RedirectResponse(request.url_for("admin"), status_code=303)


@router.post("/admin/staff/remove", name="admin_revoke")
async def admin_revoke(request: Request):
    me = auth.require_admin(request)
    f = await request.form()
    did = parse.snowflake(f.get("discord_id"))
    if did is None:
        raise HTTPException(400, "A numeric Discord ID is required.")
    if did == int(me):
        raise HTTPException(400, "You can't revoke your own staff access.")
    # Config (env) admins aren't in this table, so the DELETE could never touch
    # them — but it also could not say so, and audited the refusal as a
    # revocation. Refuse loudly instead; the lockout guard is unchanged.
    if did in settings.admin_discord_ids:
        raise HTTPException(400, "Config admins are set in the server environment "
                                 "and can't be revoked here.")
    prior = db.query_one("SELECT label FROM lan_admins WHERE discord_id=%s", (did,))
    if prior is None:  # nothing to revoke; an audit row here asserts a change that never happened
        return RedirectResponse(request.url_for("admin"), status_code=303)
    db.execute_all([
        ("DELETE FROM lan_admins WHERE discord_id=%s", (did,)),
        admin_audit.stmt_request(request, "staff_remove", did, prior["label"], None),
    ])
    return RedirectResponse(request.url_for("admin"), status_code=303)


@router.post("/admin/staff/clear-row", name="admin_clear_stale_row")
async def admin_clear_stale_row(request: Request):
    """Delete a lan_admins row belonging to someone who is ALSO a config admin.

    Not a revocation and it must not read as one — the env grant is what makes
    them staff and is untouched. The row is a leftover from before their id went
    into LAN_ADMIN_DISCORD_IDS; /staff/remove refuses env ids outright, so
    without this there is no way to clear it."""
    auth.require_admin(request)
    f = await request.form()
    did = parse.snowflake(f.get("discord_id"))
    if did is None:
        raise HTTPException(400, "A numeric Discord ID is required.")
    if did not in settings.admin_discord_ids:
        raise HTTPException(400, "That id is not a config admin — Revoke is the "
                                 "control for a web grant.")
    prior = db.query_one("SELECT label FROM lan_admins WHERE discord_id=%s", (did,))
    if prior is None:  # nothing there; a row here would assert a delete that never ran
        return RedirectResponse(request.url_for("admin"), status_code=303)
    db.execute_all([
        ("DELETE FROM lan_admins WHERE discord_id=%s", (did,)),
        admin_audit.stmt_request(request, "staff_row_clear", did, prior["label"], None),
    ])
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
    steam = _norm_steam(f.get("steam_id"))
    if not steam:
        raise HTTPException(400, "Player Steam ID required.")
    discord = parse.snowflake(f.get("discord_id"))
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


@router.post("/admin/player/edit", name="admin_player_edit")
async def player_edit(request: Request):
    """Edit an existing player's alias / Steam ID / Discord link."""
    auth.require_admin(request)
    f = await request.form()
    pid = parse.as_int(f.get("player_id"))
    if pid is None:
        raise HTTPException(400, "A player id is required.")
    display = (f.get("display_name") or "").strip()
    if not display:
        raise HTTPException(400, "Player alias required.")
    steam = _norm_steam(f.get("steam_id"))
    discord = parse.snowflake(f.get("discord_id"))
    prior = db.query_one(
        "SELECT display_name, steam_id, discord_id FROM lan_players WHERE id=%s", (pid,))
    before = _player_note(prior["display_name"], prior["steam_id"],
                          prior["discord_id"]) if prior else None
    after = _player_note(display, steam, discord)
    stmts = [("UPDATE lan_players SET display_name=%s, steam_id=%s, discord_id=%s WHERE id=%s",
              (display, steam, discord, pid))]
    if before is not None and before != after:
        stmts.append(admin_audit.stmt_request(request, "player_edit", f"player:{pid}",
                                              before, after))
    try:
        db.execute_all(stmts)
    except Exception:
        raise HTTPException(400, "Could not save (that Discord ID may already be linked elsewhere).")
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
