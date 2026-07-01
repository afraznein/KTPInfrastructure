"""Captain map-skip poll + public results + admin controls.

Each captain casts one ballot naming the map to skip on Saturday; the most-voted
map is dropped from the Saturday rotation and used as the play-in map."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from .. import auth, common, db, mapskip, seeding
from ..templating import templates

router = APIRouter()


def _teams_by_id() -> dict[int, dict]:
    return {t["id"]: t for t in db.query_all("SELECT id, name, tag FROM lan_teams ORDER BY name")}


@router.get("/mappoll", name="mappoll")
def mappoll_form(request: Request):
    ident = auth.require_captain(request)
    teams = _teams_by_id()
    ctx = common.base_ctx(request, "mapskip")
    ctx.update(
        my_team=teams.get(ident["team_id"]),
        pool=mapskip.pool_maps(),
        current=mapskip.get_team_ballot(ident["team_id"]),
        poll_open=mapskip.poll_is_open(),
    )
    return templates.TemplateResponse(request, "mappoll.html", ctx)


@router.post("/mappoll")
async def mappoll_submit(request: Request):
    ident = auth.require_captain(request)
    if not mapskip.poll_is_open():
        raise HTTPException(403, "The map-skip poll is closed.")
    form = await request.form()
    skip_map = (form.get("skip_map") or "").strip()
    if skip_map not in mapskip.pool_maps():
        raise HTTPException(400, "Pick one map from the pool.")
    mapskip.save_ballot(ident["team_id"], skip_map, submitted_by=ident["discord_id"])
    return RedirectResponse(url=request.url_for("mapskip"), status_code=303)


@router.get("/mapskip", name="mapskip")
def mapskip_page(request: Request):
    teams = _teams_by_id()
    all_ballots = mapskip.get_all_ballots()
    poll_open = mapskip.poll_is_open()
    published = seeding.is_published("map_skip_results_published")
    ident = auth.current_identity(request)
    # Blind poll: the tally and ballots stay hidden while voting is open from
    # anyone on a competing team — staff-captains included — so no one peeks
    # before their team votes. After it closes they stay staff-only until an
    # admin publishes the result.
    show_results = seeding.reveal_poll_results(
        auth.is_admin(request), poll_open, published, viewer_on_team=bool(ident and ident["team_id"]))
    ordered, counts = mapskip.tally(all_ballots, mapskip.pool_maps())
    ctx = common.base_ctx(request, "mapskip")
    ctx.update(
        teams=teams,
        ballots=all_ballots if show_results else {},
        submitted=sorted(all_ballots.keys()) if show_results else [],
        submitted_count=len(all_ballots),
        # When blind, fall back to pool order (not vote-count order) so the
        # leading map isn't even implied by ordering; tally/counts are withheld.
        ordered=ordered if show_results else mapskip.pool_maps(),
        counts=counts if show_results else {},
        total=sum(counts.values()) if show_results else 0,
        poll_open=poll_open,
        locked=mapskip.locked_skip_map(),
        show_results=show_results,
        published=published,
        is_admin=auth.is_admin(request),
    )
    return templates.TemplateResponse(request, "mapskip.html", ctx)


# ── admin controls (staff only) ──────────────────────────────────────────
@router.post("/admin/mappoll/open")
def mappoll_open(request: Request):
    auth.require_admin(request)
    mapskip.set_setting("map_skip_poll_open", "1")
    return RedirectResponse(url=request.url_for("mapskip"), status_code=303)


@router.post("/admin/mappoll/close")
def mappoll_close(request: Request):
    auth.require_admin(request)
    mapskip.set_setting("map_skip_poll_open", "0")
    return RedirectResponse(url=request.url_for("mapskip"), status_code=303)


@router.post("/admin/mappoll/compute")
def mappoll_compute(request: Request):
    auth.require_admin(request)
    mapskip.compute_and_store()
    return RedirectResponse(url=request.url_for("mapskip"), status_code=303)
