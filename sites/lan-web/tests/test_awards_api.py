"""Award voting through the JSON API the rebuilt site uses."""
import pytest

from conftest import sign_in

DID = 218890328273321984
IDENT = {"player_id": 3, "discord_id": DID, "discord_name": "nein", "display_name": "nein",
         "steam_id": None, "is_captain": 0, "team_id": 3, "team_name": "Price is Right",
         "team_tag": "PIR", "seed": 8}
ROSTER = [{"id": 1, "label": "baiko · North Atlantic Treaty Org"},
          {"id": 2, "label": "element · dicE"}]
OPEN_AWARD = {"id": 7, "slug": "rookies", "title": "Best Rookie", "kind": "player",
              "is_open": 1, "sort_order": 0}
SHUT_AWARD = {"id": 8, "slug": "carry", "title": "Carry Us, Daddy", "kind": "player",
              "is_open": 0, "sort_order": 1}


@pytest.fixture
def award_db(fake_db):
    # Needles must be unambiguous: targets() and current_identity() both read
    # "FROM lan_players p JOIN lan_teams", so match on what differs.
    fake_db.add("FROM lan_awards ORDER BY", [OPEN_AWARD, SHUT_AWARD])
    fake_db.add("CONCAT(p.display_name", ROSTER)
    fake_db.add("WHERE p.discord_id", IDENT)
    fake_db.add("FROM lan_award_votes WHERE voter", [])
    fake_db.add("COUNT(*) AS n FROM lan_award_votes", {"n": 0})
    fake_db.add("FROM lan_award_votes v", [])
    fake_db.add("SELECT is_open FROM lan_awards WHERE id", OPEN_AWARD)
    return fake_db


def test_signed_out_sees_the_ballot_but_cannot_vote(client, award_db):
    b = client.get("/api/awards").json()
    assert b["logged_in"] is False and b["can_vote"] is False
    assert [a["slug"] for a in b["awards"]] == ["rookies", "carry"]


def test_open_and_closed_are_distinguished(client, award_db):
    """Both ship, but only the closed one carries a tally — the page hides an
    open ballot's running count so it cannot sway the vote."""
    by = {a["slug"]: a for a in client.get("/api/awards").json()["awards"]}
    assert by["rookies"]["is_open"] is True and "results" not in by["rookies"]
    assert by["carry"]["is_open"] is False and "results" in by["carry"]


def test_the_whole_roster_is_selectable_not_just_a_shortlist(client, award_db):
    """A third of the published nominee names are in-game aliases that match no
    roster row, so the options must come from the roster itself."""
    assert client.get("/api/awards").json()["players"] == ROSTER


def test_a_rostered_voter_can_cast_and_it_is_recorded(client, award_db):
    sign_in(client, DID, "nein")
    r = client.post("/api/awards/vote", json={"award_id": 7, "target_id": 2})
    assert r.json() == {"ok": True, "award_id": 7, "target_id": 2}
    sql, params = award_db.writes[0]
    assert sql.startswith("INSERT INTO lan_award_votes")
    assert params == (7, DID, 2)


def test_re_voting_replaces_rather_than_adds(client, award_db):
    sign_in(client, DID, "nein")
    client.post("/api/awards/vote", json={"award_id": 7, "target_id": 2})
    assert "ON DUPLICATE KEY UPDATE" in award_db.writes[0][0]


def test_signed_out_vote_is_refused_and_writes_nothing(client, award_db):
    assert client.post("/api/awards/vote", json={"award_id": 7, "target_id": 2}).status_code == 403
    assert award_db.writes == []


def test_voting_in_a_closed_category_is_refused(client, fake_db):
    fake_db.add("WHERE p.discord_id", IDENT)
    fake_db.add("SELECT is_open FROM lan_awards WHERE id", SHUT_AWARD)
    sign_in(client, DID, "nein")
    r = client.post("/api/awards/vote", json={"award_id": 8, "target_id": 2})
    assert r.status_code == 409
    assert fake_db.writes == []


def test_a_malformed_body_is_a_400_not_a_500(client, award_db):
    sign_in(client, DID, "nein")
    for bad in [{}, {"award_id": "x", "target_id": 1}, {"award_id": 7}]:
        assert client.post("/api/awards/vote", json=bad).status_code == 400
