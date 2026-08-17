"""The public JSON surface: /api/session, /api/photos, /api/demos."""
import datetime
import re

import pytest

from app import bracket, demos
from app import schedule as sched
from conftest import sign_in

DID = 218890328273321984          # a real 19-digit snowflake: a short id proves nothing
IDENT = {"player_id": 1, "discord_id": DID, "discord_name": "nein", "display_name": "nein",
         "steam_id": "STEAM_0:0:1", "is_captain": 1, "team_id": 3,
         "team_name": "Price is Right", "team_tag": "PIR", "seed": 1}

SIGNED_OUT = {"logged_in": False, "discord_id": None, "discord_name": None, "linked": False,
              "display_name": None, "team_id": None, "team_name": None,
              "is_admin": False, "is_owner": False, "matches": [], "categories": []}


@pytest.fixture
def rostered(fake_db, monkeypatch):
    fake_db.add("FROM lan_players p", IDENT)
    monkeypatch.setattr(sched, "get_matches", lambda: [
        {"id": 12, "round": 3, "team_a_id": 3, "team_b_id": 4, "a_name": "Price is Right", "b_name": "dicE"},
        {"id": 13, "round": 4, "team_a_id": 8, "team_b_id": 9, "a_name": "x", "b_name": "y"},
    ])
    monkeypatch.setattr(bracket, "get_bracket", lambda: [
        {"mkey": "QF1", "team_a_id": 5, "team_b_id": 3, "a_name": "icyHOT", "b_name": "Price is Right"},
    ])
    return fake_db


# ── /api/session ──────────────────────────────────────────────────────────
def test_session_signed_out_is_200_not_401(client, fake_db):
    r = client.get("/api/session")
    assert r.status_code == 200
    assert r.json() == SIGNED_OUT


def test_session_signed_in_but_not_rostered(client, fake_db):
    fake_db.add("FROM lan_players p", None)
    sign_in(client, DID, "nein")
    body = client.get("/api/session").json()
    assert body["logged_in"] is True
    assert body["linked"] is False
    assert body["discord_name"] == "nein"
    assert (body["display_name"], body["team_id"], body["team_name"]) == (None, None, None)
    assert body["matches"] == []


def test_session_rostered_carries_team_and_matches(client, rostered):
    sign_in(client, DID, "nein")
    body = client.get("/api/session").json()
    assert body["linked"] is True
    assert (body["display_name"], body["team_id"], body["team_name"]) == ("nein", 3, "Price is Right")
    assert body["matches"] == [
        {"value": "sat:12", "label": "Sat R3 vs dicE"},
        {"value": "bkt:QF1", "label": f"{bracket.BY_KEY['QF1']['label']} vs icyHOT"},
    ]


def test_session_discord_id_is_a_quoted_string(client, rostered):
    """Snowflakes exceed 2^53: emitted as a number they corrupt in the browser."""
    sign_in(client, DID, "nein")
    raw = client.get("/api/session").text
    assert re.search(r'"discord_id"\s*:\s*"218890328273321984"', raw)
    assert re.search(r'"discord_id"\s*:\s*\d', raw) is None
    assert client.get("/api/session").json()["discord_id"] == str(DID)


def test_session_matches_are_the_demo_attach_list(client, rostered):
    """Same source as the upload dropdown — not a second, drifting query."""
    sign_in(client, DID, "nein")
    assert client.get("/api/session").json()["matches"] == demos.team_matches(3)


# ── /api/photos ───────────────────────────────────────────────────────────
def test_photos_shape_and_no_uploader_leak(client, fake_db):
    fake_db.add("FROM lan_photos ph", [
        {"id": 7, "stored_name": "000007.jpg", "caption": "the wall of shame", "credit": "nein",
         "uploaded_at": datetime.datetime(2026, 8, 10, 18, 30)},
    ])
    r = client.get("/api/photos")
    assert r.status_code == 200
    item = r.json()[0]
    assert item["id"] == 7
    assert item["url"] == "/gallery/7/img"
    assert item["credit"] == "nein"
    assert item["uploaded_at"].startswith("2026-08-10T18:30")
    assert "uploaded_by" not in item and "uploaded_ip" not in item


def test_photos_credit_falls_back_to_the_discord_name(client, fake_db):
    fake_db.add("FROM lan_photos ph", [{"id": 8, "stored_name": "000008.jpg", "caption": None,
                                        "credit": "some_discord_name", "uploaded_at": None}])
    assert client.get("/api/photos").json()[0]["credit"] == "some_discord_name"


# ── /api/demos ────────────────────────────────────────────────────────────
def test_demos_shape_and_no_uploader_leak(client, fake_db, monkeypatch):
    # the row carries what SELECT d.* really returns, so the projection is what
    # has to withhold the uploader — not the query
    fake_db.add("FROM lan_demos d", [{
        "id": 12, "alias": "nein", "team_id": 3, "team_name": "Price is Right",
        "schedule_id": 12, "bracket_mkey": None, "original_filename": "x.dem",
        "stored_name": "000012.zip", "size_bytes": 123456, "note": "R3",
        "uploaded_by": DID, "uploaded_ip": "203.0.113.7",
        "uploaded_at": datetime.datetime(2026, 8, 10, 18, 30),
    }])
    monkeypatch.setattr(sched, "get_matches", lambda: [
        {"id": 12, "round": 3, "team_a_id": 3, "team_b_id": 4, "a_name": "A", "b_name": "B"}])
    monkeypatch.setattr(bracket, "get_bracket", lambda: [])
    r = client.get("/api/demos")
    assert r.status_code == 200
    item = r.json()[0]
    assert item["match_label"] == "Sat R3: A v B"
    assert item["download_url"] == "/demos/12/download"
    assert item["size_bytes"] == 123456
    assert "uploaded_by" not in item and "uploaded_ip" not in item
    assert str(DID) not in r.text and "203.0.113.7" not in r.text
