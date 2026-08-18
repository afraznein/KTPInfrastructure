"""The per-match scoreboard endpoint, its publish gate, and the key → slug
redirect.

The gate is the load-bearing part and is asserted on the served response body,
not on the parsed object: a page trusted to hide what it was sent is one
view-source away, which is the failure `DESIGN.md:51-55` names. Every absence
assertion is paired with the same assertion finding the data where it belongs —
a test reporting ABSENT for everything is broken, not passing."""
import json
import re
from dataclasses import replace
from pathlib import Path

import pytest

from app import config, match_slugs, match_stats
from conftest import sign_in

DID = 218890328273321984          # staff
OTHER = 486227681885683721        # signed in, never staff
KEY = "1785715972-KTP1"
SLUG = "sun-railroad2-nato-vs-icyhot"
PLAYER = "iH.hildebrand?"
DAMAGE = 3110

MATCH = {"match_key": KEY, "edition": "philly-2026", "day": "08-02",
         "map_name": "railroad2", "team_a": "icyHOT",
         "team_b": "North Atlantic Treaty Org", "closed": 0}


def row(half, steam, name, team, kills=10, deaths=5, hs=2, damage=DAMAGE,
        flags=1, assists=3, streak=4):
    return {"half": half, "steam_id": steam, "player_name": name, "team": team,
            "kills": kills, "deaths": deaths, "headshots": hs, "damage": damage,
            "flags": flags, "assists": assists, "best_streak": streak}


ROWS = [
    row(1, "0:1", PLAYER, "icyHOT", kills=20, deaths=10, streak=6),
    row(2, "0:1", PLAYER, "icyHOT", kills=13, deaths=8, streak=4),
    row(1, "0:2", "piff", "icyHOT", kills=25, deaths=9),
    row(1, "0:3", "dicE.sean", "North Atlantic Treaty Org", kills=30, deaths=12),
    # ⚠️ The trap: ktp_match_stats' own match total. Stored it would double
    # every figure below; the table's CHECK refuses it and the query filters it.
    row(0, "0:1", PLAYER, "icyHOT", kills=33, deaths=18),
]


@pytest.fixture
def board(fake_db):
    fake_db.flags = {}
    fake_db.admins = []
    fake_db.matches = {KEY: dict(MATCH)}
    fake_db.rows = list(ROWS)
    fake_db.add("FROM lan_admins ORDER BY added_at", lambda p: fake_db.admins)
    fake_db.add("FROM lan_settings WHERE k",
                lambda p: {"v": fake_db.flags[p[0]]} if p[0] in fake_db.flags else None)
    fake_db.add("FROM lan_matches WHERE match_key",
                lambda p: fake_db.matches.get(p[0]))
    # Filters the halves the way the real WHERE clause does. A fake that
    # ignored it would hide the doubling this endpoint exists to avoid —
    # test_the_query_reads_halves_one_and_two_only holds the real SQL to it.
    fake_db.add("FROM lan_match_scoreboard WHERE match_key",
                lambda p: sorted((r for r in fake_db.rows if r["half"] in (1, 2)),
                                 key=lambda r: (r["steam_id"], r["half"])))
    return fake_db


def as_staff(fdb, client, did=DID):
    fdb.admins = [{"discord_id": did, "label": "nein"}]
    sign_in(client, did)


def get(client, key=KEY):
    return client.get(f"/api/stats/match/{key}")


# ── the gate, on the served bytes ─────────────────────────────────────────
def test_unpublished_public_never_reads_the_scoreboard_tables(client, fake_db):
    """No fake rule for either match table is registered here, so a query that
    got past the gate would raise rather than quietly answer — the response
    being well-formed is itself the proof nothing was read."""
    fake_db.add("FROM lan_admins ORDER BY added_at", [])
    fake_db.add("FROM lan_settings WHERE k", None)
    r = get(client)
    assert r.status_code == 200
    assert r.json() == {"published": False, "match": None, "players": []}


def test_unpublished_public_body_carries_no_player_or_stat(client, board):
    r = get(client)
    assert r.json() == {"published": False, "match": None, "players": []}
    for leak in (PLAYER, "piff", "dicE.sean", "icyHOT", "railroad2", str(DAMAGE)):
        assert leak not in r.text


def test_unpublished_staff_body_does_carry_them(client, board):
    """The control: the assertions above are about the gate, not about needles
    that were never in the response."""
    as_staff(board, client)
    r = get(client)
    assert r.status_code == 200 and r.json()["is_staff"] is True
    assert PLAYER in r.text and str(DAMAGE) in r.text and "railroad2" in r.text


def test_published_public_body_carries_them_too(client, board):
    board.flags["stats_published"] = "1"
    r = get(client)
    assert r.json()["published"] is True and r.json()["is_staff"] is False
    assert PLAYER in r.text and str(DAMAGE) in r.text


def test_a_signed_in_non_staff_player_is_still_public(client, board):
    sign_in(client, OTHER)
    r = get(client)
    assert r.json() == {"published": False, "match": None, "players": []}
    assert PLAYER not in r.text


def test_publishing_the_awards_does_not_publish_the_stats(client, board):
    board.flags["awards_published"] = "1"
    assert get(client).json() == {"published": False, "match": None, "players": []}


# ── existence: 404 is a different answer from an empty board ──────────────
def test_an_unknown_match_key_is_a_404_for_staff(client, board):
    as_staff(board, client)
    assert get(client, "no-such-match").status_code == 404


def test_an_unknown_match_key_is_a_404_when_published(client, board):
    board.flags["stats_published"] = "1"
    assert get(client, "no-such-match").status_code == 404


def test_a_match_with_no_rows_is_a_200_that_names_the_match(client, board):
    """Not a 404 and not an empty 200 — the page has to be able to say "this
    match logged nothing" rather than "no such match"."""
    board.rows = []
    as_staff(board, client)
    b = get(client).json()
    assert b["players"] == []
    assert b["match"]["key"] == KEY and b["match"]["halves"] == []


def test_an_unpublished_public_request_cannot_tell_the_two_apart(client, board):
    """Which is the point of checking the gate first: the 404 would otherwise
    enumerate which match keys exist."""
    assert get(client, "no-such-match").json() == {
        "published": False, "match": None, "players": []}


# ── halves 1 and 2 only ───────────────────────────────────────────────────
def test_the_query_reads_halves_one_and_two_only():
    """Half 0 is ktp_match_stats' own match total. The fake above filters the
    same way, so this is what holds the real SQL to it."""
    flat = " ".join(match_stats.ROWS_SQL.split())
    assert "half IN (1,2)" in flat


def test_the_table_refuses_a_half_zero_row():
    """Belt to the query's braces: the storage cannot hold the trap either."""
    sql = (Path(__file__).resolve().parents[1] / "migrations" /
           "0018_match_scoreboard.sql").read_text(encoding="utf-8")
    assert "CHECK (half IN (1, 2))" in sql


def test_a_total_is_the_halves_summed_and_not_the_stored_total(client, board):
    as_staff(board, client)
    p = {x["steam_id"]: x for x in get(client).json()["players"]}["0:1"]
    assert [h["half"] for h in p["halves"]] == [1, 2]
    assert p["total"]["kills"] == 33 and p["total"]["deaths"] == 18
    assert p["total"]["damage"] == 2 * DAMAGE
    assert p["total"]["assists"] == 6 and p["total"]["flags"] == 2


def test_a_best_streak_is_the_better_half_not_the_two_added(client, board):
    """Summed streaks would be a run nobody actually had."""
    as_staff(board, client)
    p = {x["steam_id"]: x for x in get(client).json()["players"]}["0:1"]
    assert [h["best_streak"] for h in p["halves"]] == [6, 4]
    assert p["total"]["best_streak"] == 6


def test_the_halves_a_match_recorded_are_reported(client, board):
    """An abandoned match says [1] rather than printing a blank second half."""
    board.rows = [r for r in ROWS if r["half"] != 2]
    as_staff(board, client)
    assert get(client).json()["match"]["halves"] == [1]


# ── the numbers ───────────────────────────────────────────────────────────
def test_kd_matches_the_reading_the_weekend_board_takes():
    assert match_stats.kd(20, 10) == 2.0
    assert match_stats.kd(7, 0) == 7.0        # nobody died: the kill count itself
    assert match_stats.kd(0, 0) == 0.0
    assert match_stats.kd(10, 3) == pytest.approx(3.333)


def test_kd_is_computed_per_half_as_well_as_on_the_total(client, board):
    as_staff(board, client)
    p = {x["steam_id"]: x for x in get(client).json()["players"]}["0:1"]
    assert [h["kd"] for h in p["halves"]] == [2.0, 1.625]
    assert p["total"]["kd"] == pytest.approx(1.833)


def test_both_teams_are_returned_home_side_first_best_fragger_first(client, board):
    as_staff(board, client)
    players = get(client).json()["players"]
    assert [p["who"] for p in players] == [PLAYER, "piff", "dicE.sean"]
    assert [p["team"] for p in players] == [
        "icyHOT", "icyHOT", "North Atlantic Treaty Org"]


def test_a_player_on_neither_named_side_still_appears(client, board):
    """A scoreboard is the wrong place to silently drop a row."""
    board.rows = ROWS + [row(1, "0:9", "spectator?", "Some Other Club", kills=1)]
    as_staff(board, client)
    players = get(client).json()["players"]
    assert players[-1]["who"] == "spectator?"


def test_the_header_carries_what_the_page_cannot_bake(client, board):
    as_staff(board, client)
    m = get(client).json()["match"]
    assert m["key"] == KEY and m["edition"] == "philly-2026"
    assert m["teams"] == ["icyHOT", "North Atlantic Treaty Org"]
    assert m["day"] == "08-02" and m["map"] == "railroad2"
    assert m["closed"] is False      # logging died before the match could close


# ── provenance: HLStatsX first, HUD only where it has no equivalent ───────
BUILD_AWARDS = (Path(__file__).resolve().parents[2] / "wsdod-lan-2026" /
                "lan-stats" / "build_awards.py")


def test_the_stat_sources_are_the_build_s_own(client, board):
    """The generator's PROVENANCE dict is the source of truth for which side of
    the HLStatsX/HUD line each figure came from. Read back out of it, so a
    change there fails here rather than leaving the page citing the wrong one."""
    if not BUILD_AWARDS.is_file():
        pytest.skip(f"no generator at {BUILD_AWARDS}")
    src = BUILD_AWARDS.read_text(encoding="utf-8")
    block = src.split("PROVENANCE = {", 1)[1].split("\n}", 1)[0]
    theirs = dict(re.findall(r'"([a-z_0-9]+)":\s*((?:"[^"]*"\s*)+)', block))
    assert "kills" in theirs and "assists" in theirs      # control: it parsed
    ours = dict(match_stats.SOURCES, damage_dealt=match_stats.SOURCES["damage"])
    for stat in ("kills", "deaths", "kd", "headshots", "damage_dealt", "flags",
                 "assists", "best_streak"):
        want = "".join(re.findall(r'"([^"]*)"', theirs[stat]))
        assert ours[stat] == want, stat


def test_the_sources_ship_with_the_board(client, board):
    as_staff(board, client)
    assert get(client).json()["sources"]["assists"].startswith("HUD")
    assert get(client).json()["sources"]["kills"] == "Match record."


# ── the raw-key redirect ──────────────────────────────────────────────────
@pytest.fixture
def slugs(tmp_path, monkeypatch):
    """Points the setting at a written map, and hands back a writer for it."""
    path = tmp_path / "match-slugs.json"

    def write(payload):
        path.write_text(json.dumps(payload), encoding="utf-8")
        match_slugs._cache = (None, {})
        return path

    monkeypatch.setattr(config, "settings",
                        replace(config.settings, match_slugs_path=str(path)))
    match_slugs._cache = (None, {})
    return write


def test_a_raw_key_redirects_to_its_frozen_slug(client, slugs):
    slugs({KEY: SLUG})
    r = client.get(f"/match/{KEY}", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == f"/match/{SLUG}/"


def test_a_key_the_map_does_not_hold_is_a_404(client, slugs):
    slugs({KEY: SLUG})
    assert client.get("/match/1785613505-KTP4", follow_redirects=False).status_code == 404


def test_a_missing_map_404s_rather_than_crashing(client, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "settings",
                        replace(config.settings,
                                match_slugs_path=str(tmp_path / "not-written-yet.json")))
    match_slugs._cache = (None, {})
    assert client.get(f"/match/{KEY}", follow_redirects=False).status_code == 404


def test_a_malformed_map_404s_rather_than_crashing(client, slugs):
    path = slugs({KEY: SLUG})
    path.write_text("{not json", encoding="utf-8")
    match_slugs._cache = (None, {})
    assert client.get(f"/match/{KEY}", follow_redirects=False).status_code == 404


def test_a_slug_without_its_trailing_slash_reaches_the_page(client, slugs):
    """This route sits above the static mount, so a pasted /match/<slug> would
    otherwise 404 on the way to a page that exists."""
    slugs({KEY: SLUG})
    r = client.get(f"/match/{SLUG}", follow_redirects=False)
    assert r.status_code == 302 and r.headers["location"] == f"/match/{SLUG}/"


@pytest.mark.parametrize("payload", [
    {KEY: SLUG},
    {KEY: {"slug": SLUG, "day": "Sun"}},
    {"matches": {KEY: SLUG}},
    {"slugs": {KEY: {"slug": SLUG}}},
    [{"match_key": KEY, "slug": SLUG}],
    [{"key": KEY, "slug": SLUG}],
])
def test_the_map_is_read_in_whatever_shape_it_was_written(client, slugs, payload):
    """The freeze is generated elsewhere and its layout is not this app's to
    choose; guessing one shape would 404 exactly like a missing file."""
    slugs(payload)
    r = client.get(f"/match/{KEY}", follow_redirects=False)
    assert r.status_code == 302, payload
    assert r.headers["location"] == f"/match/{SLUG}/"


def test_a_regenerated_map_is_picked_up_without_a_restart(client, slugs):
    slugs({KEY: SLUG})
    assert client.get(f"/match/{KEY}", follow_redirects=False).status_code == 302
    slugs({"1785613505-KTP4": "sat-anzio-dice-vs-nosoul"})
    assert client.get(f"/match/{KEY}", follow_redirects=False).status_code == 404


def test_the_redirect_keeps_the_prefix_it_is_served_under(client, slugs):
    """Behind nginx at /lan the app never sees that prefix inbound, so a bare
    path in Location sends the reader to the wrong host root."""
    from app.routes import match_routes
    slugs({KEY: SLUG})
    assert client.get(f"/match/{KEY}", follow_redirects=False
                      ).headers["location"] == f"/match/{SLUG}/"
    mounted = type("Request", (), {"scope": {"root_path": "/lan"}})()
    assert match_routes.match_key_redirect(mounted, KEY).headers["location"] == \
        f"/lan/match/{SLUG}/"


# ── the endpoint must not swallow the app ─────────────────────────────────
def test_the_rest_of_the_api_is_unaffected(client, board):
    assert client.get("/api/session").status_code == 200
