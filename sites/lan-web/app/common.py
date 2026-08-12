"""Shared request and template-context helpers."""
from __future__ import annotations

import datetime

from fastapi import Request

from . import auth


def now_edt() -> str:
    dt = datetime.datetime.now(tz=datetime.timezone(datetime.timedelta(hours=-4)))
    return dt.strftime("%d %b %Y / %H:%M EDT").upper()


def client_ip(request: Request) -> str | None:
    """Real client IP, trusting nginx's forwarded headers (the app binds to
    127.0.0.1 behind the proxy, so request.client.host alone is useless)."""
    for h in ("x-forwarded-for", "x-real-ip"):
        v = request.headers.get(h)
        if v:
            return v.split(",")[0].strip()[:45]
    return request.client.host if request.client else None


def wants_json(request: Request) -> bool:
    """An ordinary form post gets its 303; a fetch() that asked for JSON gets JSON."""
    return "application/json" in (request.headers.get("accept") or "")


def safe_next(raw: str | None) -> str | None:
    """A caller-supplied return path, or None if it isn't plainly same-origin.

    Anything a browser could read as another origin — '//host', '/\\host', a
    scheme — is rejected outright rather than patched up."""
    v = (raw or "").strip()
    if not v.startswith("/") or v[1:2] in ("/", "\\"):
        return None
    if "://" in v or "\r" in v or "\n" in v:
        return None
    return v


def home_url(request) -> str:
    """Where "home" is, for a post-logout style redirect.

    Not url_for("index"): that route is the LAN briefing, which moves to /lan
    once LAN_SITE_AT_ROOT is set — logging out would then land on the briefing
    rather than the front page. The site root is home in both modes."""
    return str(request.base_url)


def base_ctx(request: Request, active: str = "") -> dict:
    """Vars every page needs. `request` is passed positionally to
    TemplateResponse, so it is intentionally NOT included here."""
    from . import seeding
    try:
        announcement = (seeding.get_setting("announcement") or "").strip()
    except Exception:
        announcement = ""  # never let a settings hiccup take the page down
    return {
        "active_page": active,
        "last_updated": now_edt(),
        "session_user": auth.session_user(request),
        "ident": auth.current_identity(request),
        "is_admin": auth.is_admin(request),
        "announcement": announcement,
        "auto_refresh": None,  # live pages set seconds; suppressed for admins (mid-edit)
    }
