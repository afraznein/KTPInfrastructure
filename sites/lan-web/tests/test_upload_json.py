"""Upload endpoints answer JSON when asked, and keep their redirect otherwise."""
import zipfile
from dataclasses import replace

import pytest

from app.config import settings
from app.routes import demo_routes, extras_routes
from conftest import sign_in

DID = 218890328273321984
IDENT = {"player_id": 1, "discord_id": DID, "discord_name": "nein", "display_name": "nein",
         "steam_id": "STEAM_0:0:1", "is_captain": 1, "team_id": 3,
         "team_name": "Price is Right", "team_tag": "PIR", "seed": 1}
JSON = {"Accept": "application/json"}


@pytest.fixture
def demo_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(demo_routes, "settings", replace(settings, demo_dir=str(tmp_path)))
    return tmp_path


@pytest.fixture
def photo_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(extras_routes, "settings", replace(settings, photo_dir=str(tmp_path)))
    return tmp_path


def test_demo_upload_returns_json_when_asked(client, fake_db, demo_dir):
    fake_db.add("FROM lan_players p", IDENT)
    sign_in(client, DID)
    r = client.post("/demos/upload", files={"file": ("m.dem", b"demo bytes")},
                    data={"note": "R3"}, headers=JSON)
    assert r.status_code == 200
    assert r.json() == {"ok": True, "id": 1}
    stored = demo_dir / "000001.zip"
    assert zipfile.ZipFile(stored).read("m.dem") == b"demo bytes"   # still zipped server-side


def test_demo_upload_still_redirects_a_form_post(client, fake_db, demo_dir):
    fake_db.add("FROM lan_players p", IDENT)
    sign_in(client, DID)
    r = client.post("/demos/upload", files={"file": ("m.dem", b"demo bytes")},
                    follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "http://testserver/demos"


def test_demo_upload_still_needs_roster_linkage(client, fake_db, demo_dir):
    fake_db.add("FROM lan_players p", None)
    sign_in(client, DID)
    r = client.post("/demos/upload", files={"file": ("m.dem", b"x")}, headers=JSON)
    assert r.status_code == 403
    assert "detail" in r.json()                                    # a JSON error, not an HTML page


def test_demo_upload_error_is_json_not_html(client, fake_db, demo_dir):
    fake_db.add("FROM lan_players p", IDENT)
    sign_in(client, DID)
    r = client.post("/demos/upload", files={"file": ("m.dem", b"")}, headers=JSON)
    assert r.status_code == 400
    assert r.headers["content-type"].startswith("application/json")


def test_photo_upload_returns_json_when_asked(client, fake_db, photo_dir):
    sign_in(client, DID)
    r = client.post("/gallery/upload", files={"file": ("shot.png", b"\x89PNG fake")},
                    data={"caption": "hi"}, headers=JSON)
    assert r.status_code == 200
    assert r.json() == {"ok": True, "id": 1}
    assert (photo_dir / "000001.png").read_bytes() == b"\x89PNG fake"


def test_photo_upload_still_redirects_a_form_post(client, fake_db, photo_dir):
    sign_in(client, DID)
    r = client.post("/gallery/upload", files={"file": ("shot.png", b"x")}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "http://testserver/gallery"


def test_photo_upload_needs_only_a_signed_in_discord(client, fake_db, photo_dir):
    """No roster row is consulted at all — the fake DB would raise if one were."""
    sign_in(client, 111222333444555666, "spectator")
    assert client.post("/gallery/upload", files={"file": ("s.jpg", b"x")}, headers=JSON).json()["ok"]


def test_photo_upload_signed_out_is_refused(client, fake_db, photo_dir):
    r = client.post("/gallery/upload", files={"file": ("s.jpg", b"x")}, headers=JSON)
    assert r.status_code == 403


def test_photo_upload_rejects_a_non_image(client, fake_db, photo_dir):
    sign_in(client, DID)
    assert client.post("/gallery/upload", files={"file": ("x.exe", b"MZ")}, headers=JSON).status_code == 400
