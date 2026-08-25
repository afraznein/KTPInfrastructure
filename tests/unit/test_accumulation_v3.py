import copy
import json
import statistics
from pathlib import Path

import pytest

from scripts.accumulation_v3 import (
    build_ai_checkpoint,
    load_profile,
    render_markdown,
    score_match,
    validate_ai_response,
)
from scripts.compare_accumulation_models import compare_models, render_markdown as render_comparison
from scripts.build_automated_match_report import build_bundle


def facts():
    players = [
        {"player_id": 1, "player_name_at_match": "Alpha", "team_name": "Allies",
         "kills": 2, "deaths": 2, "assists": 1, "opponent_damage": 230,
         "team_kills": 2, "suicides": 0, "observed_seconds": 600},
        {"player_id": 2, "player_name_at_match": "Bravo", "team_name": "Allies",
         "kills": 1, "deaths": 2, "assists": 1, "opponent_damage": 270,
         "team_kills": 0, "suicides": 1, "observed_seconds": 600},
        {"player_id": 3, "player_name_at_match": "Charlie", "team_name": "Axis",
         "kills": 4, "deaths": 2, "assists": 0, "opponent_damage": 400,
         "team_kills": 0, "suicides": 0, "observed_seconds": 600},
        {"player_id": 4, "player_name_at_match": "Delta", "team_name": "Axis",
         "kills": 0, "deaths": 1, "assists": 0, "opponent_damage": 0,
         "team_kills": 0, "suicides": 0, "observed_seconds": 600},
    ]
    frags = [
        {"event_id": "e0a", "half": 1, "time": 1, "killer_id": 3,
         "victim_id": 1, "killer_team": 2, "victim_team": 1,
         "victim_life_id": "p1a"},
        {"event_id": "e0b", "half": 1, "time": 2, "killer_id": 3,
         "victim_id": 2, "killer_team": 2, "victim_team": 1,
         "victim_life_id": "p2a"},
        {"event_id": "e0c", "half": 1, "time": 3, "killer_id": 3,
         "victim_id": 1, "killer_team": 2, "victim_team": 1,
         "victim_life_id": "p1b"},
        {"event_id": "e0d", "half": 1, "time": 4, "killer_id": 3,
         "victim_id": 2, "killer_team": 2, "victim_team": 1,
         "victim_life_id": "p2b"},
        {"event_id": "e1", "half": 1, "time": 10, "killer_id": 1,
         "victim_id": 3, "killer_team": 1, "victim_team": 2,
         "victim_life_id": "p3a"},
        {"event_id": "e2", "half": 1, "time": 13, "killer_id": 1,
         "victim_id": 4, "killer_team": 1, "victim_team": 2,
         "victim_life_id": "p4a"},
        {"event_id": "e3", "half": 1, "time": 16, "killer_id": 2,
         "victim_id": 3, "killer_team": 1, "victim_team": 2,
         "victim_life_id": "p3b"},
    ]
    damage_events = []
    for event in frags[:4]:
        damage_events.append({
            "death_event_id": event["event_id"], "victim_life_id": event["victim_life_id"],
            "attacker_id": 3, "victim_id": event["victim_id"],
            "attacker_team": 2, "victim_team": 1, "damage_capped": 100,
        })
    damage_events += [
        {"death_event_id": "e1", "victim_life_id": "p3a", "attacker_id": 1,
         "victim_id": 3, "attacker_team": 1, "victim_team": 2, "damage_capped": 30},
        {"death_event_id": "e1", "victim_life_id": "p3a", "attacker_id": 2,
         "victim_id": 3, "attacker_team": 1, "victim_team": 2, "damage_capped": 70},
        {"death_event_id": "e2", "victim_life_id": "p4a", "attacker_id": 1,
         "victim_id": 4, "attacker_team": 1, "victim_team": 2, "damage_capped": 100},
        {"death_event_id": "e3", "victim_life_id": "p3b", "attacker_id": 2,
         "victim_id": 3, "attacker_team": 1, "victim_team": 2, "damage_capped": 100},
    ]
    return {
        "schema_version": 1,
        "match": {"match_id": "bounded-contract-TEST", "map_name": "dod_anzio",
                  "duration_seconds": 600},
        "players": players,
        "frags": frags,
        "damage_events": damage_events,
        "death_resets": [{"half": 1, "time": 14, "player_id": 2, "kind": "suicide"}],
        "captures": [
            {"event_id": "c-mid", "half": 1, "time": 20, "team": 1,
             "flag_name": "POINT_ANZIO_STREET", "flag_role": "middle",
             "credited_player_ids": [1, 2], "is_capout": False},
            {"event_id": "c-capout", "half": 1, "time": 25, "team": 1,
             "flag_name": "POINT_ANZIO_HILL", "flag_role": "enemy_first",
             "credited_player_ids": [1], "is_capout": True},
        ],
        "cap_breaks": [
            {"event_id": "b1", "half": 1, "time": 40, "player_id": 2,
             "time_remaining": 0.5, "contester_count": 3,
             "prevented_capout": True},
        ],
        "position_points": {"1": 10, "2": 20, "3": 5, "4": 0},
        "reliability": {
            "life_boundaries": True, "damage_events": True,
            "capture_events": True, "ownership": True, "map_topology": True,
            "break_context": True, "positions": True, "flag_positions": True,
        },
    }


@pytest.fixture
def scored():
    return score_match(facts(), load_profile())


def by_id(report):
    return {player["player_id"]: player for player in report["players"]}


def test_each_death_has_one_bounded_combat_budget(scored):
    assert scored["quality_gates"]["bounded_combat"]["status"] == "PASS"
    assert scored["component_totals"]["combat_finisher_points"] == 420.0
    assert scored["component_totals"]["combat_damage_share_points"] == 280.0
    assert (
        scored["component_totals"]["combat_finisher_points"]
        + scored["component_totals"]["combat_damage_share_points"]
    ) == 7 * 100
    players = by_id(scored)
    # Alpha finished the 30/70 shared kill: 60 finisher + 12 damage share.
    assert players[1]["combat_finisher_points"] == 120.0
    assert players[1]["combat_damage_share_points"] == 52.0
    assert players[2]["combat_damage_share_points"] == 68.0


def test_teamkills_suicides_and_deaths_never_subtract(scored):
    assert scored["descriptive_only"] == {
        "team_kills": 2, "suicides": 1, "penalty_points": 0.0,
    }
    assert all(
        player[key] >= 0
        for player in scored["players"]
        for key in (
            "combat_finisher_points", "streak_points", "shutdown_points",
            "fast_chain_points", "capture_points", "conversion_points",
            "cap_break_points", "position_points",
        )
    )


def test_progressive_streak_shutdown_and_maximal_fast_chains(scored):
    players = by_id(scored)
    assert players[3]["streak_points"] == 36.0  # +6, +12, +18
    assert players[1]["streak_points"] == 6.0
    assert players[1]["shutdown_points"] == 5.0  # ended Charlie's 4k
    assert players[3]["fast_chain_points"] == 45.0
    assert players[1]["fast_chain_points"] == 10.0
    chains = scored["events"]["fast_chains"]
    assert sorted(chain["kills"] for chain in chains) == [2, 4]
    assert len(chains) == 2  # no overlapping 2k + 3k awards


def test_unique_capture_pool_is_split_not_multiplied(scored):
    players = by_id(scored)
    assert players[1]["capture_points"] == 150.0
    assert players[2]["capture_points"] == 50.0
    assert scored["component_totals"]["capture_points"] == 200.0


def test_capout_supersedes_mid_and_conversion_is_shared(scored):
    conversions = {
        event["capture_event_id"]: event for event in scored["events"]["conversions"]
    }
    assert conversions["c-mid"]["awarded"] == 0.0
    assert conversions["c-capout"]["awarded"] == 150.0
    assert conversions["c-capout"]["qualifying_deaths"] == 3
    assert conversions["c-capout"]["team_push"] is True
    assert sum(conversions["c-capout"]["allocations"].values()) == pytest.approx(150, abs=0.02)
    assert scored["component_totals"]["conversion_points"] == 150.0


def test_contextual_break_is_positive_and_bounded(scored):
    event = scored["events"]["cap_breaks"][0]
    assert event["components"] == {
        "base": 25.0, "urgency": 29.17, "contesters": 20.0, "last_flag": 20.0,
    }
    assert event["points"] == 94.17
    assert event["points"] <= 100


def test_missing_life_and_ownership_evidence_selects_safe_fallback():
    source = facts()
    source["reliability"].update({
        "life_boundaries": False, "ownership": False,
        "map_topology": False, "break_context": False,
    })
    report = score_match(source, load_profile())
    players = by_id(report)
    assert report["quality_gates"]["bounded_combat"]["status"] == "WARN"
    assert report["quality_gates"]["capout_context"]["status"] == "DISABLED"
    assert report["quality_gates"]["mid_context"]["status"] == "DISABLED"
    assert players[1]["combat_finisher_points"] == 200.0
    assert players[1]["fallback_assist_points"] == 50.0
    assert players[1]["fallback_damage_points"] == 4.6
    assert report["events"]["cap_breaks"][0]["points"] == 25.0
    assert all(event["outcome"] == "flag" for event in report["events"]["objectives"])


def test_position_is_derived_only_and_reliability_gated(scored):
    assert by_id(scored)[2]["position_points"] == 20.0
    source = facts()
    source["reliability"]["flag_positions"] = False
    report = score_match(source, load_profile())
    assert report["quality_gates"]["position"]["status"] == "DISABLED"
    assert report["component_totals"]["position_points"] == 0.0


def test_points_per_minute_and_markdown_are_automatable(scored):
    assert by_id(scored)[1]["points_per_minute"] == pytest.approx(
        by_id(scored)[1]["total_points"] / 10, abs=0.01
    )
    markdown = render_markdown(scored)
    assert "No penalties are applied" in markdown
    assert "Reliability gates" in markdown
    assert "Private" not in markdown


def test_partial_appearance_is_visible_but_does_not_move_match_reference():
    source = facts()
    source["match"]["duration_seconds"] = 1200
    for player in source["players"]:
        player["observed_seconds"] = 1200
    source["players"][-1]["observed_seconds"] = 400
    profile = load_profile(Path("config/analytics/accumulation_v5_momentum.toml"))
    report = score_match(source, profile)
    full_rates = [
        row["points_per_minute"] for row in report["players"]
        if row["observed_seconds"] >= 600
    ]
    assert report["impact_index"]["reference_minimum_observed_seconds"] == 600
    assert report["impact_index"]["reference_points_per_minute"] == pytest.approx(
        statistics.median(full_rates), abs=0.01
    )
    partial = by_id(report)[4]
    assert partial["observed_seconds"] == 400
    assert partial["participation_percent"] == pytest.approx(33.33, abs=0.01)
    assert partial["impact_index"] is not None


def test_ai_checkpoint_is_hash_bound_advisory_and_cannot_change_scores(scored):
    request = build_ai_checkpoint(scored)
    response = {
        "input_sha256": request["input_sha256"],
        "summary": "A coordinated push converted late in the half.",
        "storylines": [{"title": "Push", "evidence_event_ids": ["c-capout"]}],
        "anomalies": [],
        "calibration_questions": ["Is the capout pool too large?"],
        "publication_recommendation": "review",
    }
    validate_ai_response(request, response)
    tampered = copy.deepcopy(response)
    tampered["total_points"] = 999999
    with pytest.raises(ValueError, match="versioned contract"):
        validate_ai_response(request, tampered)
    stale = copy.deepcopy(response)
    stale["input_sha256"] = "stale"
    with pytest.raises(ValueError, match="input hash"):
        validate_ai_response(request, stale)
    unknown = copy.deepcopy(response)
    unknown["storylines"][0]["evidence_event_ids"] = ["invented-event"]
    with pytest.raises(ValueError, match="unknown event ID"):
        validate_ai_response(request, unknown)
    # The request is portable JSON and contains no raw positional structures.
    body = json.dumps(request)
    assert "heatmap" not in body and "coordinates" not in body


def test_comparison_keeps_all_three_models_reproducible():
    comparison = compare_models(facts(), load_profile())
    models = {model["name"]: model for model in comparison["models"]}
    assert set(models) == {"legacy_v2", "damped_no_penalty", "bounded_v3"}
    assert models["legacy_v2"]["component_totals"]["penalty_points"] == -250.0
    assert models["damped_no_penalty"]["component_totals"]["penalty_points"] == 0.0
    assert models["damped_no_penalty"]["component_totals"]["damage_points"] == 18.0
    assert "Bounded v3 rank" in render_comparison(comparison)


def test_automated_bundle_keeps_ai_separate_and_requires_human_review(tmp_path):
    output = tmp_path / "bundle"
    manifest = build_bundle(facts(), load_profile(), output)
    assert manifest["publication_state"] == "DRAFT"
    assert manifest["publication_checkpoint"] == "HUMAN_REVIEW_REQUIRED"
    assert manifest["ai_status"] == "PENDING_OPTIONAL"
    assert {path.name for path in output.iterdir()} == {
        "report.json", "report.md", "report.html", "comparison.json", "comparison.md",
        "ai-request.json", "manifest.json",
    }
    stored = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert len(stored["profile_sha256"]) == 64
    assert stored["invariants"]["ai_can_change_scores"] is False
    assert stored["invariants"]["raw_individual_positions_exported"] is False


def test_blocking_ai_anomaly_holds_bundle_without_mutating_report(tmp_path):
    baseline = tmp_path / "baseline"
    reviewed = tmp_path / "reviewed"
    first = build_bundle(facts(), load_profile(), baseline)
    request = json.loads((baseline / "ai-request.json").read_text(encoding="utf-8"))
    response = {
        "input_sha256": request["input_sha256"],
        "summary": "Ownership evidence may be inconsistent.",
        "storylines": [],
        "anomalies": [{"severity": "block", "detail": "Review ownership.",
                       "evidence_event_ids": ["c-capout"]}],
        "calibration_questions": [],
        "publication_recommendation": "hold",
    }
    second = build_bundle(facts(), load_profile(), reviewed, response)
    assert second["publication_checkpoint"] == "HOLD"
    assert second["ai_status"] == "VALIDATED_HOLD"
    assert first["deterministic_report_sha256"] == second["deterministic_report_sha256"]
