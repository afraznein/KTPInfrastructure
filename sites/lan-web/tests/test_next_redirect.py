"""return-to (`next=`) handling on the auth flow, and the open-redirect guard."""
from dataclasses import replace

import pytest
from fastapi.responses import RedirectResponse

from app import auth
from app.common import safe_next
from app.config import settings
from app.routes import auth_routes
from conftest import sign_in

DID = 218890328273321984


# ── the guard itself ──────────────────────────────────────────────────────
def test_same_origin_paths_pass():
    assert safe_next("/demos") == "/demos"
    assert safe_next("/lan/gallery?team=3#top") == "/lan/gallery?team=3#top"
    assert safe_next("  /me  ") == "/me"


def test_protocol_relative_rejected():
    assert safe_next("//evil.example") is None
    assert safe_next("///evil.example") is None


def test_backslash_host_rejected():
    # browsers read /\host as protocol-relative too
    assert safe_next("/\\evil.example") is None


def test_scheme_rejected():
    assert safe_next("https://evil.example/x") is None
    assert safe_next("/redirect?to=https://evil.example") is None


def test_relative_and_empty_rejected():
    assert safe_next("demos") is None
    assert safe_next("") is None
    assert safe_next(None) is None


def test_header_injection_rejected():
    assert safe_next("/demos\r\nX-Evil: 1") is None


# ── the routes ────────────────────────────────────────────────────────────
def test_logout_returns_to_next(client):
    sign_in(client, DID)
    r = client.get("/logout", params={"next": "/demos"}, follow_redirects=False)
    assert r.headers["location"] == "/demos"


def test_logout_rejects_offsite_next(client):
    for bad in ("//evil.example", "/\\evil.example", "https://evil.example"):
        r = client.get("/logout", params={"next": bad}, follow_redirects=False)
        assert r.headers["location"] == "http://testserver/"


def test_logout_without_next_still_lands_home(client):
    r = client.get("/logout", follow_redirects=False)
    assert r.headers["location"] == "http://testserver/"


@pytest.fixture
def oauth_stub(monkeypatch):
    """Stand in for Discord: /login redirects away, /auth/callback returns a profile."""
    async def authorize_redirect(request, redirect_uri, **kw):
        return RedirectResponse("https://discord.test/authorize")

    async def authorize_access_token(request):
        return {"access_token": "t"}

    class _Resp:
        def json(self):
            return {"id": str(DID), "global_name": "nein"}

    async def get(path, token=None):
        return _Resp()

    monkeypatch.setattr(auth_routes, "settings", replace(settings, discord_client_id="1"))
    monkeypatch.setattr(auth.oauth.discord, "authorize_redirect", authorize_redirect)
    monkeypatch.setattr(auth.oauth.discord, "authorize_access_token", authorize_access_token)
    monkeypatch.setattr(auth.oauth.discord, "get", get)


def test_next_survives_the_oauth_round_trip(client, oauth_stub):
    client.get("/login", params={"next": "/gallery"}, follow_redirects=False)
    r = client.get("/auth/callback", follow_redirects=False)
    assert r.headers["location"] == "/gallery"


def test_offsite_next_never_reaches_the_callback(client, oauth_stub):
    client.get("/login", params={"next": "//evil.example"}, follow_redirects=False)
    r = client.get("/auth/callback", follow_redirects=False)
    assert r.headers["location"] == "http://testserver/me"


def test_callback_without_next_lands_on_me(client, oauth_stub):
    client.get("/login", follow_redirects=False)
    r = client.get("/auth/callback", follow_redirects=False)
    assert r.headers["location"] == "http://testserver/me"


def test_next_is_consumed_not_sticky(client, oauth_stub):
    client.get("/login", params={"next": "/gallery"}, follow_redirects=False)
    client.get("/auth/callback", follow_redirects=False)
    client.get("/login", follow_redirects=False)
    r = client.get("/auth/callback", follow_redirects=False)
    assert r.headers["location"] == "http://testserver/me"
