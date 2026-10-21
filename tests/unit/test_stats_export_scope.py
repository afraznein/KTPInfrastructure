"""Offline tests for scripts/ktp-stats-export.py's scope and resend guard.

Two defects this covers, both seen in production on 2026-09-12: the 48-hour
window carried every match type, so pracc and 12-man play reached the site as
results; and nothing recorded what had been sent, so the same 26 matches were
re-POSTed every ten minutes for the endpoint to answer "unchanged".
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "ktp-stats-export.py"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("_ktp_stats_export", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class _Db:
    """Captures the SQL instead of running it."""

    def __init__(self):
        self.sql = []

    def json_rows(self, sql):
        self.sql.append(sql)
        return []


def test_official_types_match_the_report_pipeline(mod):
    """The duplicate constant must not drift from its canonical copy."""
    sys.path.insert(0, str(REPO))
    from scripts.report_scope import OFFICIAL_MATCH_TYPES
    assert mod.OFFICIAL_MATCH_TYPES == OFFICIAL_MATCH_TYPES


def test_window_is_league_play_only(mod):
    db = _Db()
    mod.fetch_matches(db, 48, None)
    where = db.sql[0]
    assert "match_type in (0, 4)" in where
    assert "interval 48 hour" in where


def test_explicit_match_id_ignores_the_type_filter(mod):
    """An operator asking for one match by id means that match, whatever it is.

    Narrowed from "match_type is absent": the type is now SELECTED on this
    path, which is the point -- the site refuses a scrim recovered by hand.
    What must stay absent is the type PREDICATE.
    """
    db = _Db()
    mod.fetch_matches(db, 48, "1.3-6776-NY1")
    types = ", ".join(str(t) for t in mod.OFFICIAL_MATCH_TYPES)
    assert f"match_type in ({types})" not in db.sql[0]
    assert "1.3-6776-NY1" in db.sql[0]
    # Positive control: the window path is where that predicate belongs, so an
    # assertion that cannot fail is not what the line above is doing.
    window = _Db()
    mod.fetch_matches(window, 48, None)
    assert f"match_type in ({types})" in window.sql[0]


def test_both_paths_select_the_match_type(mod):
    """The window path filters on type; the --match-id path does not, so the
    site's gate is the only thing standing between a scrim recovered by hand
    and a league fixture. It cannot gate on a field nobody sends."""
    for match_id in (None, "1.3-6776-NY1"):
        db = _Db()
        mod.fetch_matches(db, 48, match_id)
        assert "'matchType', mtype" in db.sql[0]


def test_a_half_disagreement_resolves_to_the_non_official_type(mod):
    """ktp_matches is per half, so a match can carry two types -- a half typed
    by mistake and corrected. The site fails to an admin queue, so the safe
    pick is the non-official one; measured against nine half sets in MySQL,
    including (1,0) -> 1 and (2,4) -> 2.
    """
    db = _Db()
    mod.fetch_matches(db, 48, None)
    sql = db.sql[0]
    # Built from the constant, not from a remembered "0, 4": the fail-safe arm
    # and the window predicate have to name the same set or the gate drifts.
    types = ", ".join(str(t) for t in mod.OFFICIAL_MATCH_TYPES)
    assert f"case when match_type not in ({types})" in sql
    # ...and that arm is the coalesce's FIRST, so an official half cannot
    # outvote a non-official one. Swapping the arms inverts the gate.
    assert sql.index("not in") < sql.index("min(match_type)) mtype")


def test_digest_is_stable_and_content_sensitive(mod):
    a = {"gameMatchId": "m1", "players": [{"k": 1}]}
    assert mod.payload_digest(a) == mod.payload_digest(dict(a))
    assert mod.payload_digest(a) != mod.payload_digest(
        {"gameMatchId": "m1", "players": [{"k": 2}]})


def test_state_round_trips(mod, tmp_path, monkeypatch):
    path = tmp_path / "nested" / "sent.json"
    monkeypatch.setattr(mod, "STATE_PATH", str(path))
    mod.save_sent({"m1": "abc"})
    assert mod.load_sent() == {"m1": "abc"}


def test_unreadable_state_is_empty_not_an_error(mod, tmp_path, monkeypatch):
    """A missing or corrupt file costs a redundant POST, never a lost match."""
    path = tmp_path / "sent.json"
    monkeypatch.setattr(mod, "STATE_PATH", str(path))
    assert mod.load_sent() == {}
    path.write_text("{ not json", encoding="utf-8")
    assert mod.load_sent() == {}
    path.write_text('["a list"]', encoding="utf-8")
    assert mod.load_sent() == {}


def test_unwritable_state_warns_and_does_not_raise(mod, tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "STATE_PATH", str(tmp_path / "sent.json"))
    monkeypatch.setattr(mod.os, "replace",
                        lambda *a: (_ for _ in ()).throw(OSError("read-only")))
    mod.save_sent({"m1": "abc"})  # must not raise


def test_state_file_is_json_object_keyed_by_match(mod, tmp_path, monkeypatch):
    path = tmp_path / "sent.json"
    monkeypatch.setattr(mod, "STATE_PATH", str(path))
    mod.save_sent({"1.3-6776-NY1": "deadbeef"})
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "1.3-6776-NY1": "deadbeef"}


class _ScriptedDb:
    """Answers each query by what it asks for, so build_match can run offline."""

    def __init__(self, *, roster, box, events, points):
        self.roster, self.box, self.events, self.points = roster, box, events, points
        self.sql = []

    def json_rows(self, sql):
        self.sql.append(sql)
        if "ktp_match_players" in sql:
            return self.roster
        if "ktp_match_stats" in sql:
            return self.box
        if "hlstats_Events_Teamkills" in sql:
            return self.events
        if "ktp_flag_captures" in sql:
            return self.points
        return []


def _build(mod, *, match_type=0, **kw):
    db = _ScriptedDb(**kw)
    match = {"gameMatchId": "m-1", "serverId": 1, "mapName": "dod_donner",
             "startedAt": 0, "endedAt": 1, "halfCount": 2,
             "matchType": match_type}
    return db, mod.build_match(db, match, True)


def test_kills_and_deaths_come_from_the_events_not_dodx_counter(mod):
    """dodx's ktp_match_stats row disagrees with the scoreboard three ways.

    Measured against both captains' screenshots of 1789348403-ATL2, 36 cells:
    kills wrong on the player who took two kills before the restart, deaths
    wrong on six of twelve (it misses teamkill deaths and suicides), and score
    short on eight (the savedScore undercount). The event tables reproduce all
    24 player rows exactly.
    """
    db, match = _build(
        mod,
        roster=[{"steamId": "0:1", "playerName": "p", "team": 1, "playerId": 7}],
        box=[{"playerId": 7, "kills": 59, "deaths": 42, "headshots": 3,
              "teamKills": 0, "suicides": 0, "damage": 100, "score": 8}],
        events=[{"playerId": 7, "kills": 57, "deaths": 42}],
        points=[{"playerId": 7, "flags": 9}],
    )
    line = match["players"][0]
    assert (line["kills"], line["deaths"]) == (57, 42)
    # The rest of dodx's row still rides along; only the two rendered columns
    # were wrong, and `score` keeps its documented undercount.
    assert line["headshots"] == 3 and line["score"] == 8


def test_flags_ships_objective_POINTS_not_a_count_of_capture_rows(mod):
    """A 2-point flag taken by three players is three rows and six points.

    This is the defect the stats review opened with: 6 on the match page
    against 24 on the screenshot.
    """
    db, match = _build(
        mod,
        roster=[{"steamId": "0:1", "playerName": "p", "team": 1, "playerId": 7}],
        box=[{"playerId": 7, "kills": 1, "deaths": 1}],
        events=[{"playerId": 7, "kills": 1, "deaths": 1}],
        points=[{"playerId": 7, "flags": 9}],
    )
    assert match["players"][0]["flags"] == 9
    sql = " ".join(db.sql)
    assert "points_for_cap" in sql
    # An unobserved flag value is still a capture, and 1 is the answer this
    # shipped before -- never a dropped row.
    assert "coalesce(fp.points_for_cap, 1)" in sql
    assert "hlstats_Events_PlayerActions" not in sql


def test_a_player_with_no_captures_reads_zero_not_missing(mod):
    _, match = _build(
        mod,
        roster=[{"steamId": "0:1", "playerName": "p", "team": 1, "playerId": 7}],
        box=[{"playerId": 7, "kills": 1, "deaths": 1}],
        events=[{"playerId": 7, "kills": 1, "deaths": 1}],
        points=[],
    )
    assert match["players"][0]["flags"] == 0


def test_the_built_payload_carries_the_match_type(mod):
    """Threaded through build_match, not just selected. An untyped match sends
    an explicit null rather than dropping the key -- the site reads absence and
    null the same way ("allowed"), and a dropped key hides which it was."""
    # Fresh dicts per case: fetch_scoreboard_totals pops `playerId` out of the
    # rows it is handed, so a shared fixture survives exactly one call.
    def fresh():
        return dict(
            roster=[{"steamId": "0:1", "playerName": "p", "team": 1,
                     "playerId": 7}],
            box=[{"playerId": 7, "kills": 1, "deaths": 1}],
            events=[{"playerId": 7, "kills": 1, "deaths": 1}],
            points=[])

    for sent in (0, 1, 2, 4, None):
        _, match = _build(mod, match_type=sent, **fresh())
        # 0 is the OFFICIAL type and the one a truthiness test silently drops,
        # so assert the key is present as well as its value.
        assert "matchType" in match
        assert match["matchType"] == sent


def test_every_counted_event_is_scoped_to_the_restart(mod):
    db = _ScriptedDb(roster=[], box=[], events=[], points=[])
    mod.fetch_scoreboard_totals(db, "m-1")
    mod.fetch_objective_points(db, "m-1")
    for sql in db.sql:
        # The producer's own answer wins; the spawn burst carries every half
        # recorded before the plugin stamped it.
        assert "round_live = 1" in sql
        assert "having count(*) >= 8" in sql
        assert "coalesce(s.gt, b.gt) gt" in sql
    kills_deaths = db.sql[0]
    # Deaths are frags + teamkills + suicides: disjoint sources, so they add.
    for table in ("hlstats_Events_Frags", "hlstats_Events_Teamkills",
                  "hlstats_Events_Suicides"):
        assert table in kills_deaths
    # NULL-safe: `NULL >= x` is NULL, and a naive predicate drops those rows
    # without a word -- it cost two real mid-round kills the first time.
    assert "f.game_time is null and f.eventTime >= w.et" in kills_deaths
