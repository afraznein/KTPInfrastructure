"""Shared template context helpers."""
from __future__ import annotations

import datetime

from fastapi import Request

from . import auth


def now_edt() -> str:
    dt = datetime.datetime.now(tz=datetime.timezone(datetime.timedelta(hours=-4)))
    return dt.strftime("%d %b %Y / %H:%M EDT").upper()


def base_ctx(request: Request, active: str = "") -> dict:
    """Vars every page needs. `request` is passed positionally to
    TemplateResponse, so it is intentionally NOT included here."""
    return {
        "active_page": active,
        "last_updated": now_edt(),
        "session_user": auth.session_user(request),
        "ident": auth.current_identity(request),
        "is_admin": auth.is_admin(request),
    }
