"""Captain seeding poll + public results + admin controls."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from .. import auth, common, db, seeding
from ..templating import templates

router = APIRouter()


def _teams_by_id() -> dict[int, dict]:
    return {t["id"]: t for t in db.query_all("SELECT id, name, tag, seed FROM lan_teams ORDER BY name")}


@router.get("/poll", name="poll")
def poll_form(request: Request):
    ident = auth.require_captain(request)
    teams = _teams_by_id()
    others = [t for t in teams.values() if t["id"] != ident["team_id"]]
    ctx = common.base_ctx(request, "seeds")
    ctx.update(
        my_team=teams.get(ident["team_id"]),
        others=others,
        current=seeding.get_team_ballot(ident["team_id"]),
        n=len(others),
        poll_open=seeding.poll_is_open(),
    )
    return templates.TemplateResponse(request, "poll.html", ctx)


@router.post("/poll")
async def poll_submit(request: Request):
    ident = auth.require_captain(request)
    if not seeding.poll_is_open():
        raise HTTPException(403, "The seeding poll is closed.")
    form = await request.form()
    ranks = {int(k[5:]): int(v) for k, v in form.items() if k.startswith("rank_") and v}
    others = [t["id"] for t in db.query_all("SELECT id FROM lan_teams") if t["id"] != ident["team_id"]]
    # must rank every other team exactly once with a clean 1..N permutation
    if set(ranks) != set(others) or sorted(ranks.values()) != list(range(1, len(others) + 1)):
        raise HTTPException(400, "Rank every other team exactly once, 1..N with no repeats.")
    seeding.save_ballot(ident["team_id"], ranks, submitted_by=ident["discord_id"])
    return RedirectResponse(url=request.url_for("seeds"), status_code=303)


@router.get("/seeds", name="seeds")
def seeds_page(request: Request):
    teams = _teams_by_id()
    all_ballots = seeding.get_all_ballots()
    poll_open = seeding.poll_is_open()
    published = seeding.is_published("seeding_results_published")
    ident = auth.current_identity(request)
    # Blind poll: standings and ballots stay hidden while voting is open from
    # anyone on a competing team — staff-captains included — so no one peeks
    # before their team votes. After it closes they stay staff-only until an
    # admin publishes the result.
    show_results = seeding.reveal_poll_results(
        auth.is_admin(request), poll_open, published, viewer_on_team=bool(ident and ident["team_id"]))
    if show_results and all_ballots:
        standing, score, weight = seeding.compute_seeds(all_ballots, list(teams.keys()))
    else:
        standing, score, weight = [], {}, {}
    ctx = common.base_ctx(request, "seeds")
    ctx.update(
        teams=teams,
        standing=standing,
        score=score,
        ballots=all_ballots if show_results else {},
        submitted=sorted(all_ballots.keys()) if show_results else [],
        submitted_count=len(all_ballots),
        poll_open=poll_open,
        show_results=show_results,
        published=published,
        is_admin=auth.is_admin(request),
    )
    return templates.TemplateResponse(request, "seeds.html", ctx)


# ── admin controls (staff only) ──────────────────────────────────────────
@router.post("/admin/poll/open")
def poll_open(request: Request):
    auth.require_admin(request)
    seeding.set_setting("poll_open", "1")
    return RedirectResponse(url=request.url_for("seeds"), status_code=303)


@router.post("/admin/poll/close")
def poll_close(request: Request):
    auth.require_admin(request)
    seeding.set_setting("poll_open", "0")
    return RedirectResponse(url=request.url_for("seeds"), status_code=303)


@router.post("/admin/poll/compute")
def poll_compute(request: Request):
    auth.require_admin(request)
    seeding.compute_and_store()
    return RedirectResponse(url=request.url_for("seeds"), status_code=303)
