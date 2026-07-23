"""Captain-driven map pick/ban veto for BO3 bracket matches."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from .. import auth, common, seeding, veto
from ..templating import templates

router = APIRouter()


def _can_act(st, ident, is_admin) -> bool:
    if not st.get("ready") or st["complete"] or not st.get("current_team"):
        return False
    if is_admin:
        return True
    return bool(ident and ident["is_captain"] and ident["team_id"] == st["current_team"])


@router.get("/veto/{mkey}", name="veto")
def veto_page(request: Request, mkey: str):
    st = veto.get_state(mkey)
    if st is None:
        raise HTTPException(404, "No such match.")
    ctx = common.base_ctx(request, "bracket")
    # Same publish gate as the bracket page — mkeys are guessable, so an
    # un-gated veto page would leak unpublished Sunday pairings.
    if not (ctx["is_admin"] or seeding.is_published("schedule_sun_published")):
        st = {"mkey": st["mkey"], "label": st["label"], "best_of": st["best_of"],
              "supported": st.get("supported", True), "ready": False}
    my_turn = _can_act(st, ctx["ident"], ctx["is_admin"])
    ctx.update(
        st=st, my_turn=my_turn,
        # whoever is waiting auto-refreshes to watch the veto fill in; the party
        # on the clock does NOT (so a refresh can't wipe a half-made selection).
        auto_refresh=(6 if (st.get("ready") and not st["complete"] and not my_turn) else None),
    )
    return templates.TemplateResponse(request, "veto.html", ctx)


@router.post("/veto/{mkey}/act", name="veto_act")
async def veto_act(request: Request, mkey: str):
    ident = auth.current_identity(request)
    is_admin = auth.is_admin(request)
    st = veto.get_state(mkey)
    if not st:
        raise HTTPException(404, "No such match.")
    # Mirror the page gate: no captain actions until the bracket is published.
    if not (is_admin or seeding.is_published("schedule_sun_published")):
        raise HTTPException(403, "The bracket isn't published yet.")
    if not _can_act(st, ident, is_admin):
        raise HTTPException(403, "It's not your turn — only the on-the-clock captain (or staff) may act.")
    su = auth.session_user(request) or {}
    by = ident["discord_id"] if ident else su.get("discord_id")
    f = await request.form()
    try:
        veto.act(mkey, by, (f.get("map") or "").strip() or None, f.get("side"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return RedirectResponse(request.url_for("veto", mkey=mkey), status_code=303)


@router.post("/admin/veto/{mkey}/reset", name="veto_reset")
def veto_reset(request: Request, mkey: str):
    auth.require_admin(request)
    veto.reset(mkey)
    return RedirectResponse(request.url_for("veto", mkey=mkey), status_code=303)
