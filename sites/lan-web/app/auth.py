"""Discord OAuth + session identity.

Two distinct states, kept separate on purpose:
  - session_user(): authenticated via Discord (we know their snowflake)
  - current_identity(): that Discord account is linked to a LAN roster row
A user can be the first without the second (logged in, but not yet drafted)."""
from __future__ import annotations

from typing import Optional

from authlib.integrations.starlette_client import OAuth
from fastapi import HTTPException, Request

from . import db
from .config import settings

oauth = OAuth()
oauth.register(
    name="discord",
    client_id=settings.discord_client_id,
    client_secret=settings.discord_client_secret,
    access_token_url="https://discord.com/api/oauth2/token",
    authorize_url="https://discord.com/api/oauth2/authorize",
    api_base_url="https://discord.com/api/",
    client_kwargs={
        "scope": "identify",
        "token_endpoint_auth_method": "client_secret_post",
    },
)

SESSION_ID = "discord_id"
SESSION_NAME = "discord_name"


def session_user(request: Request) -> Optional[dict]:
    """Whoever is signed in via Discord, regardless of roster linkage."""
    did = request.session.get(SESSION_ID)
    if not did:
        return None
    return {"discord_id": did, "discord_name": request.session.get(SESSION_NAME)}


def current_identity(request: Request) -> Optional[dict]:
    """The LAN roster record tied to the signed-in Discord account, or None."""
    did = request.session.get(SESSION_ID)
    if not did:
        return None
    return db.query_one(
        """
        SELECT p.id AS player_id, p.discord_id, p.discord_name, p.display_name,
               p.steam_id, p.is_captain, p.team_id,
               t.name AS team_name, t.tag AS team_tag, t.seed
        FROM lan_players p
        JOIN lan_teams t ON t.id = p.team_id
        WHERE p.discord_id = %s
        """,
        (did,),
    )


def require_login(request: Request) -> dict:
    ident = current_identity(request)
    if not ident:
        raise HTTPException(status_code=401, detail="Linked Discord login required")
    return ident


def require_captain(request: Request) -> dict:
    ident = require_login(request)
    if not ident["is_captain"]:
        raise HTTPException(status_code=403, detail="Team captain only")
    return ident


def list_db_admins() -> list[dict]:
    """Web-granted admins (lan_admins). Empty if the table isn't there yet
    (pre-migration), so admin checks degrade to env-only rather than 500."""
    try:
        return db.query_all(
            "SELECT discord_id, label, added_by, added_at FROM lan_admins ORDER BY added_at"
        )
    except Exception:
        return []


def db_admin_ids() -> set:
    return {int(r["discord_id"]) for r in list_db_admins()}


def is_admin(request: Request) -> bool:
    """Admin if the signed-in Discord id is a config bootstrap admin (env) or
    has been granted access from the staff page (lan_admins)."""
    did = request.session.get(SESSION_ID)
    if did is None:
        return False
    if int(did) in settings.admin_discord_ids:
        return True
    return int(did) in db_admin_ids()


def require_admin(request: Request) -> int:
    if not is_admin(request):
        raise HTTPException(status_code=403, detail="LAN staff only")
    return request.session.get(SESSION_ID)
