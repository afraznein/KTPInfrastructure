"""Photo takedown requests: gating, the 24h rate limit, and the relay payload."""
import json
import urllib.error
from dataclasses import replace

import pytest

from app import notify
from app.config import settings
from conftest import sign_in

DID = 218890328273321984
OTHER = 987654321098765432
PHOTO = {"id": 7, "caption": "team photo"}
URL = "/api/photos/7/removal-request"


class _Resp:
    """Minimal stand-in for what urlopen hands back."""

    def __init__(self, body):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


def _stub_relay(monkeypatch, body=b'{"id":"1234"}', error=None):
    sent = {}

    def fake_urlopen(req, timeout=None):
        sent["url"] = req.full_url
        sent["headers"] = {k.lower(): v for k, v in req.headers.items()}
        sent["payload"] = json.loads(req.data.decode())
        if error is not None:
            raise error
        return _Resp(body)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(notify, "settings", replace(
        settings, discord_relay_url="https://relay.test/reply", discord_relay_auth="s3cret"))
    return sent


@pytest.fixture
def relay(monkeypatch):
    """Capture what would have gone to the relay, without going anywhere."""
    return _stub_relay(monkeypatch)


@pytest.fixture
def photo_db(fake_db):
    fake_db.add("FROM lan_photos WHERE id", PHOTO)
    fake_db.add("FROM lan_photo_removal_requests", None)
    return fake_db


def test_signed_out_is_refused(client, photo_db):
    assert client.post(URL, json={"reason": "that's me"}).status_code == 403


def test_unknown_photo_is_404(client, fake_db):
    fake_db.add("FROM lan_photos WHERE id", None)
    sign_in(client, DID)
    assert client.post("/api/photos/999/removal-request", json={"reason": "x"}).status_code == 404


def test_roster_linkage_is_not_required(client, photo_db, relay):
    """Signed in is enough — the subject of a photo need not be on a team."""
    sign_in(client, OTHER, "someone")
    r = client.post(URL, json={"reason": "I'm in this one"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "notified": True}


def test_request_is_recorded_before_it_is_announced(client, photo_db, relay):
    sign_in(client, DID, "nein")
    client.post(URL, json={"reason": "please take it down"})
    sql, params = photo_db.writes[0]
    assert sql.startswith("INSERT INTO lan_photo_removal_requests")
    assert params[0] == 7 and params[1] == DID and params[2] == "nein"
    assert params[3] == "please take it down"


def test_relay_post_carries_auth_and_the_photo(client, photo_db, relay):
    sign_in(client, DID, "nein")
    client.post(URL, json={"reason": "please take it down"})
    assert relay["url"] == "https://relay.test/reply"          # already ends in /reply
    assert relay["headers"]["x-relay-auth"] == "s3cret"
    content = relay["payload"]["content"]
    # camelCase: the relay 400s a snake_case key, which reads as a silent no-post.
    assert relay["payload"]["channelId"] == settings.photo_report_channel_id
    assert "channel_id" not in relay["payload"]
    assert "/gallery/7/img" in content                          # staff can open the image
    assert "team photo" in content and "nein" in content and str(DID) in content
    assert "please take it down" in content


def test_reason_can_never_fire_a_mass_ping(client, photo_db, relay):
    sign_in(client, DID, "nein")
    client.post(URL, json={"reason": "@everyone @here look at this"})
    mentions = relay["payload"]["allowed_mentions"]
    assert mentions["parse"] == []
    assert mentions["users"] == [settings.photo_report_ping_user_id]
    assert "@everyone" in relay["payload"]["content"]           # the text is posted as written


def test_payload_pins_parse_empty_regardless_of_ping():
    for ping in ("218890328273321984", "", "not-an-id"):
        m = notify.relay_payload("1", "@everyone", ping)["allowed_mentions"]
        assert m["parse"] == []
        assert m["users"] == ([ping] if ping.isdigit() else [])


def test_repeat_from_the_same_person_is_refused_and_not_announced(client, fake_db, relay):
    fake_db.add("FROM lan_photos WHERE id", PHOTO)
    fake_db.add("FROM lan_photo_removal_requests",
                lambda p: {"id": 1} if p[1] == DID else None)
    sign_in(client, DID, "nein")
    r = client.post(URL, json={"reason": "again"})
    assert r.status_code == 429
    assert fake_db.writes == [] and relay == {}


def test_a_different_person_may_still_ask(client, fake_db, relay):
    fake_db.add("FROM lan_photos WHERE id", PHOTO)
    fake_db.add("FROM lan_photo_removal_requests",
                lambda p: {"id": 1} if p[1] == DID else None)
    sign_in(client, OTHER, "someone")
    assert client.post(URL, json={"reason": "me too"}).status_code == 200
    assert len(fake_db.writes) == 1


def test_relay_failure_still_records_the_request(client, photo_db, monkeypatch):
    def boom(req, timeout=None):
        raise OSError("relay down")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    monkeypatch.setattr(notify, "settings", replace(settings, discord_relay_url="https://relay.test/reply"))
    sign_in(client, DID, "nein")
    r = client.post(URL, json={"reason": "x"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "notified": False}
    assert len(photo_db.writes) == 1


def test_discord_refusal_is_not_notified_but_is_still_recorded(client, photo_db, monkeypatch):
    """The relay forwards Discord's status, so a wrong channel id arrives as a
    4xx. The request must survive it — an unsent ping is not a lost report."""
    _stub_relay(monkeypatch, error=urllib.error.HTTPError(
        "https://relay.test/reply", 400, "Bad Request", {}, None))
    sign_in(client, DID, "nein")
    r = client.post(URL, json={"reason": "x"})
    assert r.json() == {"ok": True, "notified": False}
    assert len(photo_db.writes) == 1


def test_relay_timeout_is_not_notified(client, photo_db, monkeypatch):
    _stub_relay(monkeypatch, error=TimeoutError("timed out"))
    sign_in(client, DID, "nein")
    assert client.post(URL, json={"reason": "x"}).json() == {"ok": True, "notified": False}


def test_unconfigured_relay_reports_not_notified(client, photo_db, monkeypatch):
    monkeypatch.setattr(notify, "settings", replace(settings, discord_relay_url=""))
    sign_in(client, DID, "nein")
    assert client.post(URL, json={"reason": "x"}).json() == {"ok": True, "notified": False}


def test_missing_body_is_a_missing_reason_not_a_500(client, photo_db, relay):
    sign_in(client, DID, "nein")
    r = client.post(URL, content=b"not json", headers={"Content-Type": "application/json"})
    assert r.status_code == 200
    assert photo_db.writes[0][1][3] is None


def test_reason_is_bounded(client, photo_db, relay):
    sign_in(client, DID, "nein")
    client.post(URL, json={"reason": "x" * 900})
    assert len(photo_db.writes[0][1][3]) == 500
