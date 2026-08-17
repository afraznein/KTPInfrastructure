"""Closing a vote is the owner's alone, and it publishes the tally."""
from dataclasses import replace

import pytest

from app import auth, config
from conftest import sign_in

OWNER = 218890328273321984
STAFF = 111111111111111111
OPEN_A = {"id": 7, "slug": "rookies", "title": "Best Rookie", "kind": "player", "is_open": 1}
SHUT_A = {"id": 8, "slug": "carry", "title": "Carry Us, Daddy", "kind": "player", "is_open": 0}


@pytest.fixture
def owner_db(fake_db, monkeypatch):
    monkeypatch.setattr(config, "settings",
                        replace(config.settings, owner_discord_id=str(OWNER)))
    monkeypatch.setattr(auth, "settings", config.settings)
    fake_db.add("FROM lan_awards ORDER BY", [OPEN_A, SHUT_A])
    fake_db.add("SELECT id, slug, is_open FROM lan_awards WHERE id", OPEN_A)
    fake_db.add("CONCAT(p.display_name", [])
    fake_db.add("WHERE p.discord_id", None)
    fake_db.add("FROM lan_award_votes WHERE voter", [])
    fake_db.add("COUNT(*) AS n FROM lan_award_votes", {"n": 4})
    fake_db.add("FROM lan_award_votes v", [{"label": "baiko", "votes": 3}])
    return fake_db


def test_the_owner_can_close(client, owner_db):
    sign_in(client, OWNER, "nein")
    assert client.post("/api/awards/7/close").json() == {
        "ok": True, "slug": "rookies", "already_closed": False}
    assert owner_db.writes[0][0].startswith("UPDATE lan_awards SET is_open=0")


def test_another_admin_cannot_close(client, owner_db, monkeypatch):
    """Control: is_admin is not enough — closing ends it for everyone."""
    monkeypatch.setattr(auth, "is_admin", lambda r: True)
    sign_in(client, STAFF, "someone")
    assert client.post("/api/awards/7/close").status_code == 403
    assert owner_db.writes == []


def test_signed_out_cannot_close(client, owner_db):
    assert client.post("/api/awards/7/close").status_code == 403
    assert owner_db.writes == []


def test_closing_is_audited(client, owner_db):
    """One-way, and it publishes the tally — the irreversible act had no record."""
    sign_in(client, OWNER, "nein")
    client.post("/api/awards/7/close")
    # By SQL, not by index — an interleaved write would shift the position.
    rows = [p for sql, p in owner_db.writes if sql.startswith("INSERT INTO lan_admin_audit")]
    assert len(rows) == 1
    assert (rows[0][0], rows[0][2], rows[0][3], rows[0][4], rows[0][5]) == (
        OWNER, "award_close", "rookies", "1", "0")


def test_closing_twice_is_not_an_error_and_the_second_writes_nothing(client, owner_db):
    owner_db.rules.insert(0, ("SELECT id, slug, is_open FROM lan_awards WHERE id", SHUT_A))
    sign_in(client, OWNER, "nein")
    r = client.post("/api/awards/8/close")
    assert r.json()["already_closed"] is True
    assert owner_db.writes == []


def test_closing_an_unknown_award_is_404(client, owner_db):
    owner_db.rules.insert(0, ("SELECT id, slug, is_open FROM lan_awards WHERE id", None))
    sign_in(client, OWNER, "nein")
    assert client.post("/api/awards/999/close").status_code == 404


def test_results_publish_only_once_closed(client, owner_db):
    body = client.get("/api/awards").json()
    by = {a["slug"]: a for a in body["awards"]}
    assert "results" not in by["rookies"]          # still open
    assert by["carry"]["results"] == [{"label": "baiko", "votes": 3}]


def test_is_owner_is_reported_to_the_page(client, owner_db):
    assert client.get("/api/awards").json()["is_owner"] is False
    sign_in(client, OWNER, "nein")
    assert client.get("/api/awards").json()["is_owner"] is True
