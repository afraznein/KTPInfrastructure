"""'Now Playing' station board — public view (connect gated to logged-in,
password to admins) + inline admin CRUD on the same page."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from .. import auth, common, db, seeding, stations
from ..templating import templates

router = APIRouter()

STATUSES = ("idle", "live", "done")


@router.get("/stations", name="stations")
def stations_page(request: Request):
    ctx = common.base_ctx(request, "stations")
    ctx.update(
        stations=stations.get_stations(),
        statuses=STATUSES,
        logged_in=ctx["session_user"] is not None,
        is_admin=auth.is_admin(request),
        preview=seeding.get_setting("preview_banner") == "1",
    )
    return templates.TemplateResponse(request, "stations.html", ctx)


def _fields(f):
    status = (f.get("status") or "idle").strip()
    return (
        (f.get("label") or "").strip(),
        (f.get("connect") or "").strip() or None,
        (f.get("password") or "").strip() or None,
        (f.get("now_playing") or "").strip() or None,
        status if status in STATUSES else "idle",
        int(f.get("sort_order") or 0),
    )


@router.post("/admin/station/add", name="station_add")
async def station_add(request: Request):
    auth.require_admin(request)
    label, connect, password, now_playing, status, sort_order = _fields(await request.form())
    if not label:
        raise HTTPException(400, "Station label required.")
    db.execute(
        "INSERT INTO lan_stations (label, connect, password, now_playing, status, sort_order) "
        "VALUES (%s,%s,%s,%s,%s,%s)",
        (label, connect, password, now_playing, status, sort_order),
    )
    return RedirectResponse(request.url_for("stations"), status_code=303)


@router.post("/admin/station/edit", name="station_edit")
async def station_edit(request: Request):
    auth.require_admin(request)
    f = await request.form()
    sid = int(f["station_id"])
    label, connect, password, now_playing, status, sort_order = _fields(f)
    if not label:
        raise HTTPException(400, "Station label required.")
    db.execute(
        "UPDATE lan_stations SET label=%s, connect=%s, password=%s, now_playing=%s, status=%s, sort_order=%s WHERE id=%s",
        (label, connect, password, now_playing, status, sort_order, sid),
    )
    return RedirectResponse(request.url_for("stations"), status_code=303)


@router.post("/admin/station/delete", name="station_delete")
async def station_delete(request: Request):
    auth.require_admin(request)
    f = await request.form()
    db.execute("DELETE FROM lan_stations WHERE id=%s", (int(f["station_id"]),))
    return RedirectResponse(request.url_for("stations"), status_code=303)
