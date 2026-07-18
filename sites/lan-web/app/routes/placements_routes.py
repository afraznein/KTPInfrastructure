"""Final placements / awards — public podium + standings, admin publishes the
authoritative 1..N order (editor pre-filled with a best-effort suggestion)."""
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from .. import auth, common, db, placements, seeding
from ..templating import templates

router = APIRouter()


@router.get("/placements", name="placements")
def placements_page(request: Request):
    ctx = common.base_ctx(request, "placements")
    placed = placements.get_placements()
    champ = placements.bracket_champion()
    is_admin = auth.is_admin(request)

    all_teams = db.query_all("SELECT id, name, tag FROM lan_teams ORDER BY name")
    slots = []
    if is_admin:
        # current published order, else the suggestion, as one selected id per place
        sel = [p["id"] for p in placed] or placements.suggested_placements()
        slots = [(i + 1, sel[i] if i < len(sel) else None) for i in range(len(all_teams))]

    ctx.update(
        placements=placed,
        champion=champ,
        is_admin=is_admin,
        all_teams=all_teams,
        slots=slots,
        published=bool(placed),
        preview=seeding.get_setting("preview_banner") == "1",
    )
    return templates.TemplateResponse(request, "placements.html", ctx)


@router.post("/admin/placements/set", name="placements_set")
async def placements_set(request: Request):
    auth.require_admin(request)
    f = await request.form()
    if f.get("clear"):
        seeding.set_setting("final_placements", "[]")
        return RedirectResponse(request.url_for("placements"), status_code=303)
    n = db.query_one("SELECT COUNT(*) AS n FROM lan_teams")["n"]
    order, seen = [], set()
    for i in range(1, n + 1):
        raw = (f.get(f"place_{i}") or "").strip()
        if not raw.isdigit():
            continue  # allow partial publish (e.g. only top placements decided)
        tid = int(raw)
        if tid in seen:
            raise HTTPException(400, "Each team can be placed only once.")
        seen.add(tid)
        order.append(tid)
    seeding.set_setting("final_placements", json.dumps(order))
    return RedirectResponse(request.url_for("placements"), status_code=303)
