"""Award voting through the JSON API the rebuilt site uses.

Turnout is the second load-bearing gate here. A master admin may see how many
have voted; nobody may see who is winning while a category is open, and nobody
below master may see either — withheld by not being sent, and tested on the
serialised body with a positive control."""
import re

import pytest

from conftest import sign_in

DID = 218890328273321984          # also in the master-admin fallback list
STAFF = 486227681885683721        # staff, never master
IDENT = {"player_id": 3, "discord_id": DID, "discord_name": "nein", "display_name": "nein",
         "steam_id": None, "is_captain": 0, "team_id": 3, "team_name": "Price is Right",
         "team_tag": "PIR", "seed": 8}
ROSTER = [{"id": 1, "label": "baiko · North Atlantic Treaty Org"},
          {"id": 2, "label": "element · dicE"}]
OPEN_AWARD = {"id": 7, "slug": "rookies", "title": "Best Rookie", "kind": "player",
              "is_open": 1, "sort_order": 0}
SHUT_AWARD = {"id": 8, "slug": "carry", "title": "Carry Us, Daddy", "kind": "player",
              "is_open": 0, "sort_order": 1}
TALLY = [{"label": "element", "votes": 4}]
# Every name the turnout figure travels under, so a rename can't slip past the
# withholding test.
TURNOUT_IN_BODY = re.compile(r'"(turnout|ballots|eligible)"')


@pytest.fixture
def award_db(fake_db):
    fake_db.admins = []                     # lan_admins rows
    fake_db.ballots = {7: 9, 8: 4}          # award id -> votes cast
    fake_db.linked = 34                     # roster rows with a Discord account
    fake_db.tallied = []                    # award ids results() was read for

    # Needles must be unambiguous: targets() and current_identity() both read
    # "FROM lan_players p JOIN lan_teams", so match on what differs.
    fake_db.add("FROM lan_awards ORDER BY", [OPEN_AWARD, SHUT_AWARD])
    fake_db.add("FROM lan_admins ORDER BY added_at", lambda p: fake_db.admins)
    fake_db.add("CONCAT(p.display_name", ROSTER)
    fake_db.add("WHERE p.discord_id", IDENT)
    fake_db.add("FROM lan_award_votes WHERE voter", [])
    fake_db.add("COUNT(*) AS n FROM lan_award_votes",
                lambda p: {"n": fake_db.ballots.get(p[0], 0)})
    fake_db.add("COUNT(*) AS n FROM lan_players WHERE discord_id IS NOT NULL",
                lambda p: {"n": fake_db.linked})
    # Records which awards were ranked at all: an open category must not even
    # be queried, which is a stronger claim than the field being absent.
    fake_db.add("FROM lan_award_votes v",
                lambda p: (fake_db.tallied.append(p[0]), TALLY)[1])
    fake_db.add("SELECT is_open FROM lan_awards WHERE id", OPEN_AWARD)
    return fake_db


def as_staff(fdb, client, did):
    fdb.admins = [{"discord_id": did, "label": "staff"}]
    sign_in(client, did)


def open_award(body):
    return [a for a in body["awards"] if a["slug"] == "rookies"][0]


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


# ── turnout: how many voted, never who is winning ─────────────────────────
def test_a_master_sees_turnout_on_an_open_category(client, award_db):
    """The control for the withholding test below: an assertion that finds
    nothing proves nothing unless it finds it when a master asks."""
    as_staff(award_db, client, DID)
    r = client.get("/api/awards")
    assert TURNOUT_IN_BODY.search(r.text) is not None
    assert open_award(r.json())["turnout"] == {"ballots": 9, "eligible": 34}


def test_a_non_master_staff_body_carries_no_turnout_anywhere(client, award_db):
    """Withheld by not being sent, not by being sent and hidden — a page merely
    trusted not to render it is one view-source away."""
    as_staff(award_db, client, STAFF)
    r = client.get("/api/awards")
    assert TURNOUT_IN_BODY.search(r.text) is None


def test_a_signed_out_reader_and_a_plain_voter_get_no_turnout_either(client, award_db):
    assert TURNOUT_IN_BODY.search(client.get("/api/awards").text) is None
    sign_in(client, STAFF, "someone")       # rostered, not staff at all
    assert TURNOUT_IN_BODY.search(client.get("/api/awards").text) is None


def test_an_open_category_is_never_ranked_for_anyone_master_included(client, award_db):
    """Turnout is a headcount. Reading the standings would sway the vote it is
    measuring, and the three masters are themselves rostered voters — so the
    ranking query must not run at all, which is stronger than a missing field."""
    for did in (None, STAFF, DID):
        award_db.tallied.clear()
        if did:
            as_staff(award_db, client, did)
        body = client.get("/api/awards").json()
        assert "results" not in open_award(body)
        assert award_db.tallied == [SHUT_AWARD["id"]]


def test_a_closed_category_still_carries_its_result_and_total(client, award_db):
    """Closing publishes for everyone, master or not — unchanged by turnout."""
    as_staff(award_db, client, STAFF)
    shut = [a for a in client.get("/api/awards").json()["awards"] if a["slug"] == "carry"][0]
    assert shut["results"] == TALLY and shut["total"] == 4
    assert "turnout" not in shut


def test_an_unlinked_roster_gives_no_denominator_rather_than_zero(client, award_db):
    """"9 of 0" would read as an answer; None says there isn't one."""
    award_db.linked = 0
    as_staff(award_db, client, DID)
    assert open_award(client.get("/api/awards").json())["turnout"] == {
        "ballots": 9, "eligible": None}


def test_a_master_id_who_is_not_staff_sees_no_turnout(client, award_db):
    """Master is staff *plus*, so revoking staff revokes the figure with it."""
    sign_in(client, DID, "nein")            # on the master list, not in lan_admins
    assert TURNOUT_IN_BODY.search(client.get("/api/awards").text) is None
