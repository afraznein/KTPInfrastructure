"""voice_taunts.py: the join fan-out collapse, the per-second spam collapse, and the per-match
denominator, with no database.

The first night's data had one speaker press voice_negative nine times in one logged second
after one kill. Counted raw that is nine taunts; it is one. And a double kill inside the
lookback gives one press two candidate victims; the nearer kill is the target.
"""
from __future__ import annotations

import importlib.util
import pathlib

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "voice_taunts.py"
spec = importlib.util.spec_from_file_location("voice_taunts", SCRIPT)
vt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vt)


def row(pid, t, spk=1, code="voice_negative", vic="", vic_name="", weapon="", secs="",
        mid="M1", mtype=0, spk_name="meu"):
    return [str(pid), t, mid, str(mtype), code, str(spk), spk_name, str(vic), vic_name, weapon, str(secs)]


def test_nearest_kill_wins_the_fanout():
    rows = [row(10, "2026-10-22 18:23:19", vic=7, vic_name="j3", weapon="garand", secs=4),
            row(10, "2026-10-22 18:23:19", vic=8, vic_name="RaiveN", weapon="mp40", secs=9)]
    (p,) = vt.nearest(rows)
    assert (p["victim"], p["secs"], p["weapon"]) == ("j3", 4, "garand")


def test_press_with_no_kill_behind_it_is_kept_as_a_press_not_a_taunt():
    (p,) = vt.nearest([row(11, "2026-10-22 18:00:00")])
    assert p["secs"] is None and p["victim"] is None
    assert not vt.is_taunt(p, 5)


def test_nine_presses_in_one_second_are_one_taunt():
    rows = [row(100 + i, "2026-10-22 18:23:19", vic=7, vic_name="j3", secs=4) for i in range(9)]
    events = vt.distinct(vt.nearest(rows))
    assert len(events) == 1 and events[0]["presses"] == 9
    board = vt.leaderboard(events, {(1, 0): 3}, vt.OFFICIAL, window=5)
    assert board[0]["taunts"] == 1 and board[0]["presses"] == 9


def test_window_is_a_cut_on_the_stored_delta():
    rows = [row(1, "2026-10-22 16:01:10", vic=7, vic_name="s", secs=4),
            row(2, "2026-10-22 16:15:50", vic=7, vic_name="s", secs=2),
            row(3, "2026-10-22 16:16:25", vic=7, vic_name="s", secs=5)]
    events = vt.distinct(vt.nearest(rows))
    assert sum(vt.is_taunt(e, 2) for e in events) == 1
    assert sum(vt.is_taunt(e, 5) for e in events) == 3


def test_per_match_uses_matches_played_not_matches_with_a_taunt():
    rows = [row(1, "2026-10-22 18:00:00", vic=7, vic_name="j3", secs=2, mid="M1"),
            row(2, "2026-10-22 19:00:00", vic=7, vic_name="j3", secs=2, mid="M2")]
    events = vt.distinct(vt.nearest(rows))
    (r,) = vt.leaderboard(events, {(1, 0): 4}, vt.OFFICIAL, window=5)
    assert (r["taunts"], r["matches"], r["matches_with"], r["per_match"]) == (2, 4, 2, 0.5)
    (r,) = vt.leaderboard(events, {}, vt.OFFICIAL, window=5)
    assert r["per_match"] is None   # no denominator is shown as —, never divided


def test_official_board_excludes_scrims_and_all_board_includes_them():
    rows = [row(1, "2026-10-22 18:00:00", vic=7, vic_name="j3", secs=2, mid="M1", mtype=0),
            row(2, "2026-10-22 19:00:00", vic=7, vic_name="j3", secs=2, mid="M2", mtype=1, spk=2, spk_name="cope")]
    events = vt.distinct(vt.nearest(rows))
    assert [r["speaker"] for r in vt.leaderboard(events, {}, vt.OFFICIAL, 5)] == ["meu"]
    assert sorted(r["speaker"] for r in vt.leaderboard(events, {}, (0, 1), 5)) == ["cope", "meu"]


def test_report_renders_every_section_and_escapes_pipes():
    rows = [row(1, "2026-10-22 18:00:00", vic=7, vic_name="j|3", secs=2, spk_name="me|u")]
    events = vt.distinct(vt.nearest(rows))
    text = vt.report(events, {(1, 0): 2}, 5, 25, "2026-09-13", "now")
    for h in ("## Official matches", "## All match types", "## Most taunted", "## Per speaker", "## Shape"):
        assert h in text
    assert "me\\|u" in text and "j\\|3" in text
    assert "| 1 | me\\|u | 1 | 1 | 2 | 0.50 | 1 | j\\|3 | negative |" in text


def test_empty_report_does_not_divide_by_zero():
    text = vt.report([], {}, 5, 25, "2026-09-13", "now")
    assert "No voice commands" in text


# -- league names ------------------------------------------------------------------------


def test_league_alias_replaces_in_game_name_and_unknown_player_keeps_theirs():
    rows = [row(1, "2026-10-22 18:00:00", spk=168, spk_name="cope ~ omeName",
                vic=6, vic_name="shreddies?", secs=2)]
    events = vt.distinct(vt.nearest(rows))
    index = vt.build_alias_index(
        players=[{"id": 10, "alias": "cope"}, {"id": 11, "alias": "  "}],
        player_steam=[{"player_id": 10, "steam_id64": 76561197960265728 + 2 * 5 + 1},   # 1:5
                      {"player_id": 11, "steam_id64": 76561197960265728 + 2 * 7}])      # 0:7, blank alias
    assert index == {"1:5": "cope"}
    n = vt.resolve_names(events, {168: {"1:5"}, 6: {"0:7"}}, index)
    assert n == 1
    assert events[0]["speaker"] == "cope" and events[0]["victim"] == "shreddies?"


def test_former_steam_id_still_resolves():
    index = vt.build_alias_index([{"id": 1, "alias": "brombo"}],
                                 [{"player_id": 1, "steam_id64": 76561197960265728 + 9},
                                  {"player_id": 1, "steam_id64": 76561197960265728 + 11}])
    assert index == {"1:4": "brombo", "1:5": "brombo"}
    assert vt.steam64_to_hlstats("garbage") is None


def test_missing_credentials_is_a_note_not_a_failure(monkeypatch):
    monkeypatch.delenv("KTP_SUPABASE_URL", raising=False)
    monkeypatch.delenv("KTP_SUPABASE_SECRET_KEY", raising=False)
    index, problem = vt.fetch_alias_index()
    assert index == {} and "not set" in problem


# -- the per-match denominator only counts matches that could have recorded a voice line -----


def test_matches_before_the_voice_plugin_are_not_a_denominator():
    manifests = [["M_old", "1.27.2"], ["M_new", "1.30.0"], ["M_new", "1.27.2"], ["M_odd", "1.28.0-witness"]]
    capable = vt.voice_capable_matches(manifests)
    assert capable == {"M_new", "M_odd"}          # one capable half is enough; 1.28.0 itself qualifies
    played = [["1", "2", "M_old"], ["1", "2", "M_new"], ["1", "2", "M_new"], ["1", "1", "M_odd"], ["2", "2", "M_old"]]
    assert vt.matches_played(played, capable) == {(1, 2): 1, (1, 1): 1}
    assert vt.version_tuple("1.30.0") > vt.MIN_PRODUCER > vt.version_tuple("1.27.2")
