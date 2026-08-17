from __future__ import annotations

from scripts import match_analytics as analytics


def _players(match_id: str = "phase-a-TEST"):
    return [
        {
            "match_id": match_id,
            "player_id": i,
            "steam_id": f"BOT:{i}" if match_id.endswith("-TEST") else f"0:{i}",
            "player_name_at_match": f"Player {i}",
            "team": 1 if i <= 6 else 2,
            "kills": 1,
            "deaths": 1,
            "assists": 0,
            "headshots": 0,
            "team_kills": 0,
            "suicides": 0,
            "damage_dealt": 100,
            "damage_taken": 100,
            "team_damage": 0,
            "self_damage": 0,
            "capture_credits": 0,
            "cap_breaks": 0,
            "shots": 10,
            "hits": 3,
            "position_samples": 20,
        }
        for i in range(1, 13)
    ]


def _inventory():
    return {
        "roster_players": 12,
        "distinct_roster_players": 12,
        "invalid_half_frags": 0,
        "invalid_half_damage": 0,
        "cached_player_totals": 12,
        "cached_kills": 12,
        "cached_deaths": 12,
        "damage_events": 20,
        "statsme_rows": 12,
        "statsme2_rows": 12,
        "statsme_hits": 36,
        "located_hits": 36,
        "capture_credits": 1,
        "unique_capture_events": 1,
        "position_samples": 240,
    }


def test_sql_literal_escapes_operator_value():
    assert analytics.sql_literal("a'b\\c") == "'a''b\\\\c'"


def test_all_checked_in_queries_are_read_only():
    for path in analytics.SQL_DIR.glob("*.sql"):
        query = analytics.read_query(path.name, "phase-a-TEST")
        first_token = query.lstrip().split(None, 1)[0].lower()
        assert first_token in {"--", "select", "with"}
        lowered = query.lower()
        assert "{{match_id}}" not in lowered
        for mutating in (" insert ", " update ", " delete ", " replace ", " drop ", " alter "):
            assert mutating not in f" {lowered} "


def test_tsv_rows_coerces_numbers_and_nulls():
    rows = analytics.tsv_rows("player_id\tkd_ratio\tplayer_name_at_match\n7\tNULL\tFox\n")
    assert rows == [{"player_id": 7, "kd_ratio": None, "player_name_at_match": "Fox"}]


def test_quality_passes_complete_current_test_shape():
    match = {"open_halves": 0}
    result = analytics.evaluate_quality(
        "phase-a-TEST", match, _players(), _inventory()
    )
    assert result["status"] == "PASS"
    assert all(item["level"] == "PASS" for item in result["checks"])


def test_quality_warns_for_missing_optional_weapon_capture():
    inventory = _inventory()
    inventory.update({"statsme_rows": 0, "statsme2_rows": 0})
    result = analytics.evaluate_quality(
        "phase-a-TEST", {"open_halves": 0}, _players(), inventory
    )
    assert result["status"] == "WARN"
    codes = {item["code"] for item in result["checks"] if item["level"] == "WARN"}
    assert {"statsme_coverage", "hitbox_coverage"} <= codes


def test_quality_fails_if_bot_identity_enters_real_match():
    players = _players("real-match")
    players[0]["steam_id"] = "BOT:escaped"
    result = analytics.evaluate_quality(
        "real-match", {"open_halves": 0}, players, _inventory()
    )
    assert result["status"] == "FAIL"
    containment = next(c for c in result["checks"] if c["code"] == "bot_containment")
    assert containment["level"] == "FAIL"


def test_public_player_rows_remove_individual_position_coverage():
    public = analytics.public_players(_players())
    assert len(public) == 12
    assert all("position_samples" not in player for player in public)


def test_markdown_states_positional_privacy_without_player_locations():
    report = {
        "match_id": "phase-a-TEST",
        "match": {"map_name": "dod_anzio", "halves_played": 1, "duration_seconds": 600},
        "quality": {"status": "PASS", "checks": []},
        "players": analytics.public_players(_players()[:1]),
        "weapons": [],
        "capture_credits": [],
        "capture_events": [],
    }
    rendered = analytics.render_markdown(report)
    assert "Raw player positions" in rendered
    assert "position_samples" not in rendered
    assert "pos_x" not in rendered
