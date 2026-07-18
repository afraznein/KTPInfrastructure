"""Discord OAuth login/callback/logout + the signed-in dossier."""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from .. import auth, common
from ..config import settings
from ..templating import templates

router = APIRouter()


@router.get("/login", name="login")
async def login(request: Request):
    if not settings.discord_client_id:
        raise HTTPException(503, "Discord OAuth not configured (set DISCORD_CLIENT_ID/SECRET).")
    redirect_uri = settings.discord_redirect_uri or str(request.url_for("auth_callback"))
    return await auth.oauth.discord.authorize_redirect(request, redirect_uri)


@router.get("/auth/callback", name="auth_callback")
async def auth_callback(request: Request):
    token = await auth.oauth.discord.authorize_access_token(request)
    resp = await auth.oauth.discord.get("users/@me", token=token)
    profile = resp.json()
    request.session[auth.SESSION_ID] = int(profile["id"])
    request.session[auth.SESSION_NAME] = profile.get("global_name") or profile.get("username")
    return RedirectResponse(url=request.url_for("me_page"))


@router.get("/logout", name="logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url=request.url_for("index"))


@router.get("/me", name="me_page")
def me(request: Request):
    return templates.TemplateResponse(request, "me.html", common.base_ctx(request, ""))
