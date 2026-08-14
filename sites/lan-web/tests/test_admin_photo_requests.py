"""Staff queue for photo takedown requests, and the demos page after its query
helpers moved to app/demos.py."""
import datetime

import pytest

from app import bracket
from app import schedule as sched
from conftest import sign_in

DID = 218890328273321984
IDENT = {"player_id": 1, "discord_id": DID, "discord_name": "nein", "display_name": "nein",
         "steam_id": "STEAM_0:0:1", "is_captain": 1, "team_id": 3,
         "team_name": "Price is Right", "team_tag": "PIR", "seed": 1}
REQUEST = {"id": 4, "photo_id": 7, "requested_by": DID, "requested_name": "nein",
           "reason": "my kid is in frame", "requested_ip": "203.0.113.7",
           "status": "pending", "handled_by": None, "handled_at": None,
           "created_at": datetime.datetime(2026, 8, 10, 18, 30),
           "stored_name": "000007.png", "caption": "team photo"}


@pytest.fixture
def page_db(fake_db, monkeypatch):
    fake_db.add("FROM lan_settings", None)
    fake_db.add("FROM lan_players p", IDENT)
    monkeypatch.setattr(sched, "get_matches", lambda: [])
    monkeypatch.setattr(bracket, "get_bracket", lambda: [])
    return fake_db


def test_queue_is_staff_only(client, page_db):
    page_db.add("FROM lan_admins", [])
    sign_in(client, DID)
    assert client.get("/admin/photo-requests").status_code == 403


def test_queue_lists_pending_requests(client, page_db):
    page_db.add("FROM lan_admins", [{"discord_id": DID, "label": "nein"}])
    page_db.add("FROM lan_photo_removal_requests r", [REQUEST])
    sign_in(client, DID)
    r = client.get("/admin/photo-requests")
    assert r.status_code == 200
    assert "my kid is in frame" in r.text
    assert "Mark handled" in r.text


def test_marking_handled_stamps_the_actor(client, page_db):
    page_db.add("FROM lan_admins", [{"discord_id": DID, "label": "nein"}])
    sign_in(client, DID)
    r = client.post("/admin/photo-requests/handled", data={"request_id": "4"},
                    follow_redirects=False)
    assert r.status_code == 303
    sql, params = page_db.writes[0]
    assert sql.startswith("UPDATE lan_photo_removal_requests SET status='handled'")
    assert params == (DID, 4)
    assert "AND status='pending'" in sql       # marking twice can't re-stamp the actor


def test_marking_handled_is_staff_only(client, page_db):
    page_db.add("FROM lan_admins", [])
    sign_in(client, DID)
    r = client.post("/admin/photo-requests/handled", data={"request_id": "4"})
    assert r.status_code == 403
    assert page_db.writes == []


def test_demos_page_still_renders(client, page_db, monkeypatch):
    """The attach dropdown and match labels now come from app/demos.py."""
    page_db.add("FROM lan_admins", [])
    page_db.add("FROM lan_demos d", [{
        "id": 12, "alias": "nein", "team_id": 3, "team_name": "Price is Right",
        "schedule_id": 12, "bracket_mkey": None, "original_filename": "x.dem",
        "stored_name": "000012.zip", "size_bytes": 123456, "note": "R3",
        "uploaded_by": DID, "uploaded_ip": "203.0.113.7",
        "uploaded_at": datetime.datetime(2026, 8, 10, 18, 30),
    }])
    page_db.add("SELECT id, name FROM lan_teams", [{"id": 3, "name": "Price is Right"}])
    monkeypatch.setattr(sched, "get_matches", lambda: [
        {"id": 12, "round": 3, "team_a_id": 3, "team_b_id": 4, "a_name": "A", "b_name": "dicE"}])
    sign_in(client, DID)
    r = client.get("/demos")
    assert r.status_code == 200
    assert "Sat R3: A v dicE" in r.text          # resolved match label
    assert "Sat R3 vs dicE" in r.text            # the attach dropdown option
