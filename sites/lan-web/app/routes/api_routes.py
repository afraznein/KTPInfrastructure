"""JSON for the site's own front-end: session state, the gallery, the demo
archive, and the photo takedown request that queues staff work.

The three GETs are public, so each names the columns it returns — the uploader's
Discord id and IP are admin-only on the pages and must not travel with them."""
from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from .. import (admin_audit, auth, awards, common, db, demos, match_stats,
                notify, photos, seeding, stat_awards)
from ..config import settings

router = APIRouter()


@router.get("/api/session", name="api_session")
def api_session(request: Request):
    """Who is signed in and what they may attach a demo to. Always 200 — signed
    out is a state, not an error."""
    su = auth.session_user(request)
    ident = auth.current_identity(request) if su else None
    return {
        "logged_in": su is not None,
        # Snowflakes overflow JavaScript's safe-integer range, so they ship quoted.
        "discord_id": str(su["discord_id"]) if su else None,
        "discord_name": su["discord_name"] if su else None,
        "linked": ident is not None,
        "display_name": ident["display_name"] if ident else None,
        "team_id": ident["team_id"] if ident else None,
        "team_name": ident["team_name"] if ident else None,
        "is_admin": auth.is_admin(request),
        "is_owner": auth.is_owner(request),
        "matches": demos.team_matches(ident["team_id"]) if ident else [],
        # Draft/scrim/12-man demos belong to no bracket match, so they are their
        # own list rather than being mixed into the uploader's fixtures.
        "categories": demos.generic_options() if ident else [],
    }


@router.get("/api/photos", name="api_photos")
def api_photos(request: Request):
    """Gallery photos, newest first."""
    rows = db.query_all(
        "SELECT ph.id, ph.stored_name, ph.caption, ph.uploaded_at, "
        "       COALESCE(p.display_name, ph.uploaded_name) AS credit "
        "FROM lan_photos ph LEFT JOIN lan_players p ON p.discord_id = ph.uploaded_by "
        "ORDER BY ph.uploaded_at DESC, ph.id DESC"
    )
    out = []
    for r in rows:
        item = {"id": r["id"],
                "url": request.url_for("gallery_img", photo_id=r["id"]).path,
                "caption": r["caption"],
                "credit": r["credit"],
                "uploaded_at": r["uploaded_at"]}
        # Only advertised when the file is really there, so the grid never
        # points at a 404 — no thumbnail simply means it loads the original.
        if photos.has_thumb(r["stored_name"]):
            item["thumb_url"] = request.url_for("gallery_thumb", photo_id=r["id"]).path
        out.append(item)
    return out


@router.get("/api/demos", name="api_demos")
def api_demos(request: Request):
    """Uploaded demos, newest first."""
    return [
        {"id": d["id"],
         "alias": d["alias"],
         "team_name": d["team_name"],
         "match_label": d["match_label"],
         "note": d["note"],
         "size_bytes": d["size_bytes"],
         "uploaded_at": d["uploaded_at"],
         "download_url": request.url_for("demos_download", demo_id=d["id"]).path}
        for d in demos.listing()
    ]


async def _reason(request: Request) -> str:
    """The body's reason. A malformed body is a missing reason, not a 500."""
    try:
        body = await request.json()
    except Exception:
        return ""
    return (body.get("reason") or "").strip() if isinstance(body, dict) else ""


def _removal_message(request: Request, photo: dict, su: dict, reason: str) -> str:
    """Everything staff need to act without opening the database."""
    ping = (settings.photo_report_ping_user_id or "").strip()
    head = f"<@{ping}> " if ping.isdigit() else ""
    lines = [
        f"{head}\U0001f5bc\ufe0f **Photo removal request**",
        f"Photo #{photo['id']} — {request.url_for('gallery_img', photo_id=photo['id'])}",
    ]
    if photo["caption"]:
        lines.append(f"Caption: {photo['caption']}")
    lines += [
        f"From: {su['discord_name'] or 'unknown'} (discord {su['discord_id']})",
        f"Reason: {reason or '(none given)'}",
        f"When: {common.now_edt()}",
        f"Queue: {request.url_for('photo_requests')}",
    ]
    return "\n".join(lines)


@router.post("/api/photos/{photo_id}/removal-request", name="photo_removal_request")
async def photo_removal_request(request: Request, photo_id: int):
    """Ask staff to take a photo down. Any signed-in Discord account may ask;
    the same person asking again for the same photo inside a day is refused so
    staff aren't re-pinged.

    The row is written before the Discord post and the post can't fail the
    request — `notified` is what separates delivered from merely recorded."""
    su = auth.session_user(request)
    if not su:
        raise HTTPException(403, "Sign in with Discord to request a removal.")
    photo = db.query_one("SELECT id, caption FROM lan_photos WHERE id=%s", (photo_id,))
    if not photo:
        raise HTTPException(404, "No such photo.")
    if db.query_one(
        "SELECT id FROM lan_photo_removal_requests WHERE photo_id=%s AND requested_by=%s "
        "AND created_at > NOW() - INTERVAL 1 DAY LIMIT 1",
        (photo_id, su["discord_id"]),
    ):
        raise HTTPException(429, "You've already asked us to take this photo down — staff have it.")
    reason = (await _reason(request))[:500]
    db.execute(
        "INSERT INTO lan_photo_removal_requests "
        "(photo_id, requested_by, requested_name, reason, requested_ip) VALUES (%s,%s,%s,%s,%s)",
        (photo_id, su["discord_id"], (su["discord_name"] or "")[:64] or None,
         reason or None, common.client_ip(request)),
    )
    notified = await run_in_threadpool(
        notify.post_relay,
        settings.photo_report_channel_id,
        _removal_message(request, photo, su, reason),
        settings.photo_report_ping_user_id,
    )
    return {"ok": True, "notified": notified}


@router.get("/api/awards", name="api_awards")
def api_awards(request: Request):
    """Open ballots, the whole roster to pick from, and this voter's choices.

    The roster is returned once rather than per award: every voted category is
    player-kind, and the site's published shortlists are an argued starting
    point, not the selectable set — a third of those names are in-game aliases
    that resolve to no roster row, so restricting the options to them would
    drop real people from the ballot without saying so."""
    ident = auth.current_identity(request)
    mine = awards.my_votes(ident["discord_id"]) if ident else {}
    master = auth.is_master_admin(request)
    # One roster count for the whole response rather than one per category.
    eligible = awards.eligible_voters() if master else None
    out = []
    for a in awards.all_awards():
        row = {"id": a["id"], "slug": a["slug"], "title": a["title"],
               "kind": a["kind"], "is_open": bool(a["is_open"]),
               "my_vote": mine.get(a["id"])}
        # A tally while voting is live would sway it, so results publish only
        # once the category is closed — the same rule the staff page uses.
        if not a["is_open"]:
            row["results"] = awards.results(a)
            row["total"] = awards.total_votes(a["id"])
        elif master:
            # Turnout, never standings: masters are themselves rostered voters,
            # so a running order would sway the vote it is meant to measure.
            # Everyone else is sent no count at all, not one the page hides.
            row["turnout"] = awards.turnout(a["id"], eligible)
        out.append(row)
    return {
        "logged_in": auth.session_user(request) is not None,
        "can_vote": ident is not None,
        "is_owner": auth.is_owner(request),
        "players": awards.targets("player"),
        "awards": out,
    }


@router.post("/api/awards/{award_id}/close", name="api_award_close")
def api_award_close(request: Request, award_id: int):
    """End voting in one category. Owner only, and one-way from here — results
    publish the moment it closes, so reopening is a staff-page decision."""
    auth.require_owner(request)
    aw = db.query_one("SELECT id, slug, is_open FROM lan_awards WHERE id=%s", (award_id,))
    if not aw:
        raise HTTPException(404, "No such award.")
    if not aw["is_open"]:
        return {"ok": True, "slug": aw["slug"], "already_closed": True}
    db.execute("UPDATE lan_awards SET is_open=0 WHERE id=%s AND is_open=1", (award_id,))
    return {"ok": True, "slug": aw["slug"], "already_closed": False}


@router.post("/api/awards/vote", name="api_award_vote")
async def api_award_vote(request: Request):
    """One vote per voter per category; re-voting replaces the previous choice."""
    ident = auth.current_identity(request)
    if not ident:
        raise HTTPException(403, "Voting is for players on a roster — sign in with the "
                                 "Discord account staff linked to your roster entry.")
    try:
        body = await request.json()
        award_id, target_id = int(body["award_id"]), int(body["target_id"])
    except Exception:
        raise HTTPException(400, "Pick a category and a player.")
    try:
        awards.cast_vote(award_id, ident["discord_id"], target_id)
    except ValueError as e:
        raise HTTPException(409, str(e))
    return {"ok": True, "award_id": award_id, "target_id": target_id}


async def _json_body(request: Request) -> dict:
    """The request body as a dict. A malformed one is an empty body, which the
    caller then rejects as a missing field rather than a 500."""
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


def _field(body: dict, key: str, limit: int) -> str:
    return str(body.get(key) or "").strip()[:limit]


def _flag(body: dict, key: str) -> bool:
    """A JSON bool, or the string a form-ish client sends instead — bool("false")
    is True, and an untick that silently ticks is the wrong way to be wrong."""
    v = body.get(key)
    if isinstance(v, str):
        return v.strip().lower() not in ("", "0", "false", "no", "off")
    return bool(v)


@router.get("/api/awards/candidates", name="api_award_candidates")
def api_award_candidates(request: Request, edition: str = "", match: str = ""):
    """The generated award board: who won what, and by how much.

    An unpublished board answers with no award data at all — not data the page
    is trusted to hide. The gate is checked before anything is read, so an
    unpublished dataset is never one view-source away. Staff see every
    candidate the build produced, published or not.

    A per-match request rides `stats_published`, because those records are a
    readout of the scoreboard they sit under on the same page and the two must
    never disagree about being visible. The weekend board is unchanged: it
    waits for the tick and for `awards_published`."""
    staff = auth.is_admin(request)
    match_key = (match or "").strip()
    published = seeding.is_published(
        "stats_published" if match_key else "awards_published")
    if not (staff or published):
        return {"published": False, "awards": []}
    edition = (edition or "").strip()
    if not edition:
        raise HTTPException(400, "An edition is required.")
    master = staff and auth.is_master_admin(request)
    return {
        "published": published,
        "is_staff": staff,
        "edition": edition,
        "awards": stat_awards.board(edition, match_key, staff=staff,
                                    voter=request.session.get(auth.SESSION_ID),
                                    master=master),
    }


@router.get("/api/stats/match/{match_key}", name="api_match_stats")
def api_match_stats(request: Request, match_key: str):
    """One match's scoreboard, per player, per half and totalled.

    Per-match pages are static shells that fetch this, which is the whole
    reason they can be gated: an unpublished board is not baked into fifty-odd
    files. Unpublished answers with no rows at all — the gate is checked before
    anything is read, so the dataset is never one view-source away. Staff see
    it whatever the flag says.

    A key no match owns is a 404. A match with an empty scoreboard is a 200
    with no players, and the page has to say something different about each."""
    staff = auth.is_admin(request)
    published = seeding.is_published("stats_published")
    if not (staff or published):
        return {"published": False, "match": None, "players": []}
    m = match_stats.match(match_key.strip())
    if not m:
        raise HTTPException(404, "No such match.")
    players = match_stats.scoreboard(m)
    return {
        "published": published,
        "is_staff": staff,
        "match": match_stats.header(m, players),
        "players": players,
        "sources": match_stats.SOURCES,
    }


@router.post("/api/awards/staff-vote", name="api_award_staff_vote")
async def api_award_staff_vote(request: Request):
    """Nominate an award, or withdraw the nomination. Any staff member.

    Its own path rather than /api/awards/vote, which is the players' live
    ballot on a different table entirely."""
    actor = auth.require_admin(request)
    body = await _json_body(request)
    edition = _field(body, "edition", 32)
    slug = _field(body, "slug", 48)
    if not edition or not slug:
        raise HTTPException(400, "An edition and an award slug are required.")
    match_key = _field(body, "match_key", 64)
    voted = _flag(body, "voted")
    if not stat_awards.award_type(slug):
        raise HTTPException(404, "No such award.")
    was = stat_awards.vote_state(edition, slug, match_key, actor)
    stat_awards.set_vote(edition, slug, match_key, voted, actor)
    admin_audit.log_request(request, "award_staff_vote",
                            stat_awards.ref(edition, slug, match_key),
                            int(was), int(voted))
    return {"ok": True, "voted": voted}


@router.post("/api/awards/select", name="api_award_select")
async def api_award_select(request: Request):
    """Tick an award onto the public board, or take it back off.

    Master admins only — a staff nomination is a vote, not a publish."""
    actor = auth.require_master_admin(request)
    body = await _json_body(request)
    edition = _field(body, "edition", 32)
    slug = _field(body, "slug", 48)
    if not edition or not slug:
        raise HTTPException(400, "An edition and an award slug are required.")
    match_key = _field(body, "match_key", 64)
    selected = _flag(body, "selected")
    if not stat_awards.award_type(slug):
        raise HTTPException(404, "No such award.")
    was = stat_awards.selection_state(edition, slug, match_key)
    stat_awards.set_selected(edition, slug, match_key, selected, actor)
    admin_audit.log_request(request, "award_select", stat_awards.ref(edition, slug, match_key),
                            int(was), int(selected))
    return {"ok": True, "selected": selected}


@router.post("/api/awards/rename", name="api_award_rename")
async def api_award_rename(request: Request):
    """Retitle an award for good. The override lives on the award type, not the
    edition, so every future event inherits it — that is the whole point.
    Sending an empty title clears it back to the generated default."""
    actor = auth.require_admin(request)
    body = await _json_body(request)
    slug = _field(body, "slug", 48)
    if not slug:
        raise HTTPException(400, "An award slug is required.")
    t = stat_awards.award_type(slug)
    if not t:
        raise HTTPException(404, "No such award.")
    title = _field(body, "title", 96) or None
    sting = _field(body, "sting", 255) or None
    was = stat_awards.override_note(t["title"], t["sting"])  # captured before the write
    stat_awards.rename(slug, title, sting, actor)
    admin_audit.log_request(request, "award_rename", slug, was,
                            stat_awards.override_note(title, sting))
    return {"ok": True, "slug": slug, "is_renamed": title is not None,
            "title": title or t["default_title"],
            "sting": sting or t["default_sting"]}


_CATEGORIES = {"event": "The event", "site": "This site",
               "next": "Next year", "other": "Something else"}
FEEDBACK_PER_HOUR = 5
_MIN_FILL_SECONDS = 3


def _feedback_message(su: dict, category: str, body: str) -> str:
    """No operator ping — feedback is read, not paged."""
    return "\n".join([
        f"\U0001f4dd **Feedback — {_CATEGORIES[category]}**",
        f"From: {su['discord_name'] or 'unknown'} (discord {su['discord_id']})",
        f"When: {common.now_edt()}",
        "",
        body,
    ])


@router.post("/api/feedback", name="api_feedback")
async def api_feedback(request: Request):
    """Site feedback, attributed to the sender's Discord account.

    A tripped honeypot or an instantly-submitted form answers 200 and stores
    nothing — telling a bot which guard caught it only teaches it."""
    su = auth.session_user(request)
    if not su:
        raise HTTPException(403, "Sign in with Discord to send feedback.")
    form = await request.form()
    if (form.get("website") or "").strip():
        return {"ok": True}
    try:
        opened = int(form.get("started") or 0)
    except ValueError:
        opened = 0
    if opened < _MIN_FILL_SECONDS:
        return {"ok": True}
    body = (form.get("body") or "").strip()[:2000]
    if not body:
        raise HTTPException(400, "Nothing written.")
    category = form.get("category") if form.get("category") in _CATEGORIES else "other"
    recent = db.query_one(
        "SELECT COUNT(*) AS n FROM lan_feedback "
        "WHERE sent_by=%s AND created_at > NOW() - INTERVAL 1 HOUR",
        (su["discord_id"],),
    )
    if recent and recent["n"] >= FEEDBACK_PER_HOUR:
        raise HTTPException(429, "That's a few too many for one hour — try again later.")
    notified = await run_in_threadpool(
        notify.post_relay, settings.feedback_channel_id,
        _feedback_message(su, category, body), "",
    )
    db.execute(
        "INSERT INTO lan_feedback (category, body, sent_by, sent_name, sent_ip, notified) "
        "VALUES (%s,%s,%s,%s,%s,%s)",
        (category, body, su["discord_id"], (su["discord_name"] or "")[:64] or None,
         common.client_ip(request), 1 if notified else 0),
    )
    return {"ok": True, "notified": notified}
