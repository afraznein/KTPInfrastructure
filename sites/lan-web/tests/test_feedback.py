"""Site feedback: attribution, the two bot guards, and the per-hour limit."""
import json
from dataclasses import replace

import pytest

from app import notify
from app.config import settings
from app.routes.api_routes import FEEDBACK_PER_HOUR
from conftest import sign_in

URL = "/api/feedback"
DID = 218890328273321984
GOOD = {"category": "event", "body": "the chairs were bad", "started": "45", "website": ""}


class _Resp:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def relay(monkeypatch):
    sent = {}

    def fake_urlopen(req, timeout=None):
        sent["payload"] = json.loads(req.data.decode())
        return _Resp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(notify, "settings", replace(
        settings, discord_relay_url="https://relay.test/reply", discord_relay_auth="s3cret"))
    return sent


@pytest.fixture
def fb_db(fake_db):
    fake_db.add("FROM lan_feedback", {"n": 0})
    return fake_db


def test_signed_out_is_refused(client, fb_db):
    assert client.post(URL, data=GOOD).status_code == 403


def test_signed_in_sends_and_records(client, fb_db, relay):
    sign_in(client, DID, "nein")
    assert client.post(URL, data=GOOD).json() == {"ok": True, "notified": True}
    sql, params = fb_db.writes[0]
    assert sql.startswith("INSERT INTO lan_feedback")
    assert params[0] == "event" and params[1] == "the chairs were bad"
    assert params[2] == DID and params[3] == "nein"


def test_the_sender_is_named_and_nobody_is_paged(client, fb_db, relay):
    """Feedback goes to the same channel as takedowns but must not ping — and no
    typed text may ever fire a mass mention."""
    sign_in(client, DID, "nein")
    client.post(URL, data={**GOOD, "body": "@everyone @here fix the chairs"})
    payload = relay["payload"]
    assert payload["channelId"] == settings.feedback_channel_id
    assert payload["allowed_mentions"] == {"parse": [], "users": []}
    assert "nein" in payload["content"] and str(DID) in payload["content"]


def test_honeypot_answers_ok_and_stores_nothing(client, fb_db, relay):
    sign_in(client, DID)
    assert client.post(URL, data={**GOOD, "website": "http://spam"}).json() == {"ok": True}
    assert fb_db.writes == []
    assert relay == {}          # control: the stub would have captured a post


def test_instant_submit_answers_ok_and_stores_nothing(client, fb_db, relay):
    sign_in(client, DID)
    assert client.post(URL, data={**GOOD, "started": "0"}).json() == {"ok": True}
    assert fb_db.writes == []
    assert relay == {}


def test_a_slow_human_is_not_caught_by_the_fill_guard(client, fb_db, relay):
    """Control for the two tests above — same shape, only `started` differs."""
    sign_in(client, DID)
    assert client.post(URL, data={**GOOD, "started": "3"}).json()["ok"] is True
    assert len(fb_db.writes) == 1


def test_empty_body_is_a_400(client, fb_db):
    sign_in(client, DID)
    assert client.post(URL, data={**GOOD, "body": "   "}).status_code == 400


def test_unknown_category_falls_back_rather_than_erroring(client, fb_db, relay):
    sign_in(client, DID)
    client.post(URL, data={**GOOD, "category": "'; DROP TABLE"})
    assert fb_db.writes[0][1][0] == "other"


def test_over_the_hourly_limit_is_refused_and_not_posted(client, fake_db, relay):
    fake_db.add("FROM lan_feedback", {"n": FEEDBACK_PER_HOUR})
    sign_in(client, DID)
    assert client.post(URL, data=GOOD).status_code == 429
    assert fake_db.writes == []
    assert relay == {}


def test_an_undelivered_note_is_still_recorded(client, fb_db, monkeypatch):
    """The relay being down must not lose what someone wrote."""
    monkeypatch.setattr(notify, "settings", replace(settings, discord_relay_url=""))
    sign_in(client, DID)
    assert client.post(URL, data=GOOD).json() == {"ok": True, "notified": False}
    assert fb_db.writes[0][1][5] == 0
