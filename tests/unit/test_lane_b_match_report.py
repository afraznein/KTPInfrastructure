import json
from decimal import Decimal
from pathlib import Path

import pytest

from scripts import team_score_telemetry as team_score
from scripts.lane_b_e2e import (check_kill_switch,
                                clean_assists_after_reenable,
                                judge_capture_context_isolation,
                                match_log_segment)
from scripts.lane_b_match_report import (
    _aggregate_team_life_timing,
    _ownership_is_reliable,
    _participation_seconds,
    _associate_damage_to_deaths,
    build_analytics_provenance,
    build_facts,
    generate_lane_b_report,
    summary_for_lane,
)
from scripts.match_analytics import evaluate_capture_authorization


def _facts() -> dict:
    players = []
    frags = []
    for player_id in range(1, 13):
        team = 1 if player_id <= 6 else 2
        victim = player_id + 6 if team == 1 else player_id - 6
        players.append({
            "player_id": player_id,
            "player_name_at_match": f"Bot {player_id}",
            "team_name": f"Team {team}",
            "kills": 1,
            "deaths": 1,
            "assists": 0,
            "opponent_damage": 100,
            "team_kills": 0,
            "suicides": 0,
            "observed_seconds": 360,
        })
        frags.append({
            "event_id": f"frag-{player_id}", "half": 1,
            "time": 20 + player_id, "killer_id": player_id,
            "victim_id": victim, "killer_team": team,
            "victim_team": 2 if team == 1 else 1,
            "victim_life_id": f"h1-p{victim}-frag-{player_id}",
        })
    empty_components = {
        "mid_defense_points": 0, "aggression_points": 0,
        "enemy_flag_hold_points": 0, "active_flag_defense_points": 0,
        "sequence_continuity_points": 0, "position_points": 0,
    }
    return {
        "schema_version": 1,
        "match": {"match_id": "lane-b-unit-TEST", "map_name": "dod_anzio",
                  "duration_seconds": 360, "source_mode": "lane_b_ephemeral_mysql"},
        "players": players, "frags": frags, "damage_events": [],
        "death_resets": [], "captures": [], "cap_breaks": [],
        "position_points": {str(pid): 0 for pid in range(1, 13)},
        "position_components": {str(pid): dict(empty_components)
                                for pid in range(1, 13)},
        "momentum_points": {str(pid): 0 for pid in range(1, 13)},
        "momentum_summary": {
            "status": "experimental_shadow", "team1": 1, "team2": 2,
            "ownership_coverage_percent": 100.0,
            "curve": [{"half": 1, "time": 0, "momentum": 0},
                      {"half": 1, "time": 360, "momentum": 0}],
            "episodes": [],
        },
        "telemetry_lifecycles": {
            "privacy": "aggregate_only_no_entity_or_position_detail",
            "objective_attempts": {
                "status": "available", "events": 0, "attempts": 0,
                "starts": 0, "completes": 0, "stops": 0,
                "orphan_terminals": 0, "open_attempts": 0,
                "stop_reasons": {"capture_stopped": 0, "context_reset": 0},
            },
            "grenade_entities": {
                "status": "available", "semantics": "entity_tracked_removed_only",
                "events": 0, "entities": 0, "tracked": 0, "removed": 0,
                "complete_lifecycles": 0, "incomplete_tracked": 0,
                "left_censored_removed": 0, "allowed_weapon_ids_only": True,
            },
        },
        "reliability": {
            "life_boundaries": True, "damage_events": False,
            "capture_events": False, "ownership": False,
            "map_topology": True, "break_context": False,
            "positions": True, "flag_positions": True,
            "life_impact": True, "life_boundaries_inferred": True,
            "momentum": True,
        },
    }


def _tsv(columns, rows):
    return "\n".join([
        "\t".join(columns),
        *("\t".join(str(row.get(column, "NULL")) for column in columns)
          for row in rows),
    ]) + "\n"


class ExtractorDb:
    def sql(self, query):
        marker = query.split("lane_b_v5_", 1)[1].split(" ", 1)[0]
        if marker == "match":
            return _tsv(
                ["match_id", "server_id", "map_name", "halves_played",
                 "observed_halves", "open_halves", "match_type",
                 "distinct_match_types", "unclassified_halves",
                 "duration_seconds"],
                [{"match_id": "extractor-TEST", "server_id": 1,
                  "map_name": "dod_anzio", "halves_played": 1,
                  "observed_halves": "1", "open_halves": 0,
                  "match_type": 3, "distinct_match_types": 1,
                  "unclassified_halves": 0, "duration_seconds": 360}],
            )
        if marker == "capture_manifests":
            return _tsv(
                ["half", "schema_version", "capabilities", "position_interval",
                 "map_revision_algorithm", "map_revision_sha256",
                 "producer_activation_epoch", "activation_receipt_epoch",
                 "match_start_epoch"],
                [{"half": 1, "schema_version": 23,
                  "capabilities": (
                      "objective_attempt,team_membership,grenade_entity,"
                      "position_state,map_revision"
                  ),
                  "position_interval": 2.0,
                  "map_revision_algorithm": "sha256",
                  "map_revision_sha256": "a" * 64,
                  "producer_activation_epoch": 1787097599,
                  "activation_receipt_epoch": 1787097601,
                  "match_start_epoch": 1787097600}],
            )
        if marker == "capture_health":
            event_types = (
                "life", "damage", "position", "frag", "assist", "break",
                "flag_state", "flag_position", "objective_attempt", "team_membership",
                "grenade_entity",
            )
            rows = []
            for event_type in event_types:
                count = (
                    4 if event_type == "objective_attempt" else
                    3 if event_type == "grenade_entity" else
                    2172 if event_type == "position" else 0
                )
                rows.append({
                    "half": 1, "event_type": event_type,
                    "attempted": count, "enqueued": count, "dropped": 0,
                    "emitted": count, "daemon_received": count,
                    "daemon_accepted": count, "daemon_rejected": 0,
                    "correlation_failure_count": 0, "sequence_gap_count": 0,
                    "duplicate_or_reordered_count": 0,
                })
            return _tsv(
                ["half", "event_type", "attempted", "enqueued", "dropped",
                 "emitted", "daemon_received", "daemon_accepted",
                 "daemon_rejected", "correlation_failure_count",
                 "sequence_gap_count", "duplicate_or_reordered_count"],
                rows,
            )
        if marker == "roster":
            return _tsv(
                ["player_id", "player_name", "team"],
                [{"player_id": pid, "player_name": f"Bot {pid}",
                  "team": 1 if pid <= 6 else 2} for pid in range(1, 13)],
            )
        if marker == "life_boundaries":
            return _tsv(
                ["half", "player_id", "boundary_kind", "reason", "team", "game_time"],
                [
                    {"half": 1, "player_id": 1, "boundary_kind": "start",
                     "reason": "context_live", "team": 1, "game_time": 0},
                    {"half": 1, "player_id": 1, "boundary_kind": "end",
                     "reason": "death", "team": 1, "game_time": 120},
                ],
            )
        if marker == "positions":
            rows = []
            for when in range(0, 361, 2):
                for pid in range(1, 13):
                    team = 1 if pid <= 6 else 2
                    rows.append({"player_id": pid, "team": team, "half": 1,
                                 "pos_x": 500 + when * 5 if team == 1 else 3500 - when * 5,
                                 "pos_y": pid * 5, "pos_z": 0,
                                 "is_alive": 1, "is_spectator": 0,
                                 "map_revision_sha256": "a" * 64,
                                 "game_time": 500 + when})
            return _tsv(
                ["player_id", "team", "half", "pos_x", "pos_y", "pos_z",
                 "is_alive", "is_spectator", "map_revision_sha256", "game_time"],
                rows,
            )
        if marker == "frags":
            return _tsv(
                ["id", "half", "killer_id", "victim_id", "game_time"],
                [{"id": pid, "half": 1, "killer_id": pid,
                  "victim_id": pid + 6 if pid <= 6 else pid - 6,
                  "game_time": 100 + pid} for pid in range(1, 13)],
            )
        if marker == "damage":
            return _tsv(
                ["id", "half", "attacker_id", "victim_id", "damage_capped", "game_time"],
                [{"id": pid, "half": 1, "attacker_id": pid,
                  "victim_id": pid + 6 if pid <= 6 else pid - 6,
                  "damage_capped": 100, "game_time": 99 + pid}
                 for pid in range(1, 13)],
            )
        if marker == "assists":
            return _tsv(["player_id", "assists"], [{"player_id": 4, "assists": 1}])
        if marker == "teamkill_resets":
            assert "killerId AS killer_id" in query
            return _tsv(
                ["id", "half", "killer_id", "player_id", "game_time"],
                [{"id": 1, "half": 1, "killer_id": 1,
                  "player_id": 2, "game_time": 150}],
            )
        if marker == "suicide_resets":
            return _tsv(
                ["id", "half", "player_id", "game_time"],
                [{"id": 1, "half": 1, "player_id": 3, "game_time": 160}],
            )
        if marker == "captures":
            return _tsv(
                ["id", "half", "player_id", "capture_team", "flag_name", "game_time"],
                [{"id": 1, "half": 1, "player_id": 1, "capture_team": "Allies",
                  "flag_name": "POINT_ANZIO_STREET", "game_time": 180}],
            )
        if marker == "breaks":
            return ""
        if marker == "flags":
            names = ["POINT_ANZIO_LAUNDRY", "POINT_ANZIO_PLAZA",
                     "POINT_ANZIO_STREET", "POINT_BRIDGE", "POINT_ANZIO_HILL"]
            return _tsv(
                ["flag_index", "flag_name", "origin_x", "origin_y"],
                [{"flag_index": index, "flag_name": name,
                  "origin_x": index * 1000, "origin_y": 0}
                 for index, name in enumerate(names)],
            )
        if marker == "flag_states":
            names = ["POINT_ANZIO_LAUNDRY", "POINT_ANZIO_PLAZA",
                     "POINT_ANZIO_STREET", "POINT_BRIDGE", "POINT_ANZIO_HILL"]
            rows = [{"id": index + 1, "half": 1, "flag_index": index,
                     "flag_name": name, "owner_team": 1 if index < 2 else 2 if index > 2 else 0,
                     "is_initial": 1, "game_time": 500}
                    for index, name in enumerate(names)]
            rows.append({"id": 6, "half": 1, "flag_index": 2,
                         "flag_name": "POINT_ANZIO_STREET", "owner_team": 1,
                         "is_initial": 0, "game_time": 681})
            return _tsv(
                ["id", "half", "flag_index", "flag_name", "owner_team",
                 "is_initial", "game_time"], rows,
            )
        if marker == "objective_attempts":
            return _tsv(
                ["server_id", "half", "attempt_id", "event_kind", "stop_reason"],
                [
                    {"server_id": 1, "half": 1, "attempt_id": 10,
                     "event_kind": "start", "stop_reason": "NULL"},
                    {"server_id": 1, "half": 1, "attempt_id": 10,
                     "event_kind": "complete", "stop_reason": "NULL"},
                    {"server_id": 1, "half": 1, "attempt_id": 11,
                     "event_kind": "start", "stop_reason": "NULL"},
                    {"server_id": 1, "half": 1, "attempt_id": 11,
                     "event_kind": "stop", "stop_reason": "context_reset"},
                ],
            )
        if marker == "grenade_entities":
            return _tsv(
                ["server_id", "half", "entindex", "serial", "entity_kind",
                 "weapon_id", "weapon_type"],
                [
                    {"server_id": 1, "half": 1, "entindex": 101, "serial": 10001,
                     "entity_kind": "tracked", "weapon_id": 13,
                     "weapon_type": "handgrenade"},
                    {"server_id": 1, "half": 1, "entindex": 101, "serial": 10001,
                     "entity_kind": "removed", "weapon_id": 13,
                     "weapon_type": "handgrenade"},
                    {"server_id": 1, "half": 1, "entindex": 102, "serial": 10002,
                     "entity_kind": "tracked", "weapon_id": 36,
                     "weapon_type": "mills_bomb"},
                ],
            )
        raise AssertionError(marker)


def test_live_database_extractor_builds_private_derived_public_facts():
    facts, private = build_facts(ExtractorDb(), "extractor-TEST")
    by_id = {row["player_id"]: row for row in facts["players"]}
    assert len(by_id) == 12
    assert by_id[1]["team_kills"] == 1
    assert by_id[2]["team_kills"] == 0
    assert by_id[3]["suicides"] == 1
    assert facts["reliability"]["ownership"] is True
    assert facts["reliability"]["momentum"] is True
    assert facts["reliability"]["life_boundaries"] is True
    assert facts["reliability"]["life_boundaries_inferred"] is False
    provenance = facts["match"]["analytics_provenance"]
    assert provenance["contract_version"] == 1
    assert provenance["build_id"].startswith("tapv1-")
    assert provenance["map_revision"]["status"] == "available"
    assert provenance["lifecycle_confidence"] == "authoritative_life_boundary_events"
    assert facts["private_telemetry_quality"]["life_boundaries"] == {
        "status": "available", "rows": 2, "starts": 1,
        "death_ends": 1, "invalid_rows": 0,
    }
    assert facts["private_telemetry_quality"]["position_provenance"]["authorized"] is True
    assert provenance["map_revision"]["captured_bsp_sha256"] == "a" * 64
    assert facts["momentum_summary"]["curve"]
    assert max(row["time"] for row in facts["momentum_summary"]["curve"]) <= 360
    body = json.dumps(facts).lower()
    assert "pos_x" not in body and "steam_id" not in body
    position_timing = facts["team_position_contributions"]
    assert position_timing
    assert not any("player" in key for row in position_timing for key in row)
    assert private["position_samples"] == 2172
    assert private["grenade_entity_position_rows"] == 3
    assert facts["telemetry_lifecycles"]["objective_attempts"] == {
        "status": "available", "events": 4, "attempts": 2, "starts": 2,
        "completes": 1, "stops": 1, "orphan_terminals": 0,
        "open_attempts": 0,
        "stop_reasons": {"capture_stopped": 0, "context_reset": 1},
    }
    assert facts["telemetry_lifecycles"]["grenade_entities"]["entities"] == 2
    assert facts["telemetry_lifecycles"]["grenade_entities"]["incomplete_tracked"] == 1
    assert facts["telemetry_lifecycles"]["grenade_entities"]["allowed_weapon_ids_only"] is True


def test_live_report_fails_position_reliability_closed_on_state_mismatch():
    class InvalidPositionStateDb(ExtractorDb):
        def sql(self, query):
            result = super().sql(query)
            if "lane_b_v5_positions" not in query:
                return result
            lines = result.splitlines()
            columns = lines[0].split("\t")
            spectator_index = columns.index("is_spectator")
            values = lines[1].split("\t")
            values[spectator_index] = "1"
            lines[1] = "\t".join(values)
            return "\n".join(lines) + "\n"

    facts, _private = build_facts(InvalidPositionStateDb(), "extractor-TEST")
    quality = facts["private_telemetry_quality"]["position_provenance"]
    assert quality["authorized"] is False
    assert quality["invalid_state_rows"] == 1
    assert facts["reliability"]["positions"] is False
    assert facts["reliability"]["life_impact"] is False


def test_analytics_provenance_build_id_changes_with_contract_inputs(tmp_path):
    root = Path(__file__).resolve().parents[2]
    profile = root / "config/analytics/accumulation_v6_schema22_2s.toml"
    objectives = root / "config/analytics/map_objectives.toml"
    catalog = root / "config/analytics/spatial_maps"
    baseline = build_analytics_provenance(
        map_name="dod_anzio", profile_path=profile, objectives_path=objectives,
        spatial_catalog_dir=catalog, flag_position_source="live_database",
    )
    adapter_changed = build_analytics_provenance(
        map_name="dod_anzio", profile_path=profile, objectives_path=objectives,
        spatial_catalog_dir=catalog, flag_position_source="live_database",
        adapter_version="lane_b_ephemeral_mysql_v2",
    )
    assert baseline["build_id"] != adapter_changed["build_id"]

    no_catalog = build_analytics_provenance(
        map_name="dod_anzio", profile_path=profile, objectives_path=objectives,
        spatial_catalog_dir=tmp_path, flag_position_source="live_database",
    )
    assert no_catalog["map_revision"] == {
        "map_name": "dod_anzio", "status": "unavailable",
        "catalog_status": "unavailable", "catalog_sha256": None,
        "captured_status": "unavailable", "captured_bsp_sha256": None,
    }
    assert baseline["build_id"] != no_catalog["build_id"]


def test_live_report_rejects_crossed_allowed_grenade_id_type_pair():
    class CrossedPairDb(ExtractorDb):
        def sql(self, query):
            if "lane_b_v5_grenade_entities" in query:
                return _tsv(
                    ["server_id", "half", "entindex", "serial", "entity_kind",
                     "weapon_id", "weapon_type"],
                    [{"server_id": 1, "half": 1, "entindex": 101,
                      "serial": 10001, "entity_kind": "tracked",
                      "weapon_id": 13, "weapon_type": "stickgrenade"}],
                )
            return super().sql(query)

    facts, _ = build_facts(CrossedPairDb(), "extractor-TEST")
    assert facts["telemetry_lifecycles"]["grenade_entities"][
        "allowed_weapon_ids_only"
    ] is False


def test_damage_rows_are_bounded_to_the_victims_next_death():
    frags = [
        {"event_id": "frag-10", "half": 1, "time": 20,
         "killer_id": 7, "victim_id": 1},
        {"event_id": "frag-11", "half": 1, "time": 40,
         "killer_id": 8, "victim_id": 1},
    ]
    damage = [
        {"half": 1, "time": 10, "attacker_id": 7, "victim_id": 1,
         "damage_capped": 60},
        {"half": 1, "time": 30, "attacker_id": 8, "victim_id": 1,
         "damage_capped": 80},
    ]
    result = _associate_damage_to_deaths(
        damage, frags, {(1, 1): 1, (1, 7): 2, (1, 8): 2}
    )
    assert [row["death_event_id"] for row in result] == ["frag-10", "frag-11"]
    assert [row["victim_life_id"] for row in result] == [
        "h1-p1-frag-10", "h1-p1-frag-11",
    ]


def test_private_distinct_life_end_times_collapse_to_one_team_bin():
    private_lives = [
        {"half": 1, "player_id": 1, "end_time": 10.125,
         "awarded_components": {"aggression_points": 10}},
        {"half": 1, "player_id": 2, "end_time": 13.875,
         "awarded_components": {"mid_defense_points": 20}},
    ]
    life_points = {
        1: {"position_points": 10},
        2: {"position_points": 20},
    }
    public = _aggregate_team_life_timing(
        private_lives, life_points, {1: 1, 2: 1}, {1: 60}
    )
    assert public == [{
        "half": 1, "bin_end": 60, "team": 1, "points": 30.0,
        "timing": "privacy_deferred_reconciliation",
    }]
    body = json.dumps(public)
    assert "10.125" not in body and "13.875" not in body
    assert "player" not in body and "end_time" not in body and "contributor" not in body


@pytest.mark.parametrize("player_count", [1, 2])
def test_sparse_position_bins_never_reveal_the_original_bin(player_count):
    lives = [
        {"half": 1, "player_id": player_id, "end_time": 10 + player_id / 10,
         "awarded_components": {"aggression_points": 10}}
        for player_id in range(1, player_count + 1)
    ]
    totals = {player_id: {"position_points": 10}
              for player_id in range(1, player_count + 1)}
    public = _aggregate_team_life_timing(
        lives, totals, {player_id: 1 for player_id in totals}, {1: 90}
    )
    assert public == [{
        "half": 1, "bin_end": 90, "team": 1,
        "points": 10.0 * player_count,
        "timing": "privacy_deferred_reconciliation",
    }]


def test_three_distinct_position_contributors_may_keep_the_team_bin():
    lives = [
        {"half": 1, "player_id": player_id, "end_time": 10 + player_id / 10,
         "awarded_components": {"aggression_points": 10}}
        for player_id in range(1, 4)
    ]
    totals = {player_id: {"position_points": 10} for player_id in range(1, 4)}
    public = _aggregate_team_life_timing(
        lives, totals, {1: 1, 2: 1, 3: 1}, {1: 90}
    )
    assert public == [{
        "half": 1, "bin_end": 15.0, "team": 1, "points": 30.0,
        "timing": "team_bin",
    }]


def test_multiple_sparse_bins_pool_exactly_at_half_reconciliation():
    lives = [
        {"half": 1, "player_id": 1, "end_time": 10,
         "awarded_components": {"aggression_points": 10}},
        {"half": 1, "player_id": 2, "end_time": 25,
         "awarded_components": {"mid_defense_points": 20}},
    ]
    public = _aggregate_team_life_timing(
        lives, {1: {"position_points": 10}, 2: {"position_points": 20}},
        {1: 1, 2: 1}, {1: 120},
    )
    assert sum(row["points"] for row in public) == 30
    assert public == [{
        "half": 1, "bin_end": 120, "team": 1, "points": 30.0,
        "timing": "privacy_deferred_reconciliation",
    }]


def test_live_extractor_bundle_is_generated_verified_and_summarized(tmp_path: Path):
    result = generate_lane_b_report(ExtractorDb(), "extractor-TEST", tmp_path)
    assert result["verification"]["status"] == "PASS"
    assert len(result["report"]["players"]) == 12
    ratings = [row["impact_index"] for row in result["report"]["players"]]
    assert all(value is not None for value in ratings)
    assert min(ratings) <= 100 <= max(ratings)
    assert result["verification"]["private_derivation"]["retained"] is False
    assert json.loads((tmp_path / "report-verification.json").read_text())["status"] == "PASS"
    assert {"facts.normalized.json", "report.json", "report.md", "report.html",
            "manifest.json", "momentum.svg", "points-timeline.json",
            "points-timeline.svg"} <= {
        path.name for path in tmp_path.iterdir()
    }
    assert "KTP accumulated match report" in (tmp_path / "report.html").read_text()
    assert "points-timeline.svg" in (tmp_path / "report.html").read_text()
    assert result["verification"]["checks"]["points_timeline_conservation"] == "PASS"
    manifest_files = {row["path"] for row in result["manifest"]["files"]}
    assert {"points-timeline.json", "points-timeline.svg"} <= manifest_files
    summary = summary_for_lane(result)
    assert summary["status"] == "PASS"
    assert len(summary["players"]) == 12


def _schema22_health(*, frag_rejections: int = 0) -> list[dict]:
    rows = []
    for event_type in (
        "life", "damage", "position", "frag", "assist", "break",
        "flag_state", "flag_position", "objective_attempt", "team_membership",
        "grenade_entity",
    ):
        attempted = ((4 if frag_rejections else 6)
                     if event_type == "frag" else 0)
        rejected = frag_rejections if event_type == "frag" else 0
        rows.append({
            "half": 1, "event_type": event_type,
            "attempted": attempted, "enqueued": attempted, "dropped": 0,
            "emitted": attempted, "daemon_received": attempted,
            "daemon_accepted": attempted - rejected,
            "daemon_rejected": rejected,
            "correlation_failure_count": rejected,
            "sequence_gap_count": 0, "duplicate_or_reordered_count": 0,
        })
    return rows


def test_breakdrive_diagnostics_are_isolated_from_v6_report_authorization(
        tmp_path: Path):
    manifest = [{
        "half": 1, "schema_version": 22,
        "capabilities": "objective_attempt,grenade_entity",
        "position_interval": 2.0,
    }]
    report_health_rows = _schema22_health()
    diagnostic_health_rows = _schema22_health(frag_rejections=3)
    report_authorization = evaluate_capture_authorization(
        {1}, manifest, report_health_rows
    )
    diagnostic_authorization = evaluate_capture_authorization(
        {1}, manifest, diagnostic_health_rows
    )
    report_frag = next(
        row for row in report_health_rows if row["event_type"] == "frag"
    )
    diagnostic_frag = next(
        row for row in diagnostic_health_rows if row["event_type"] == "frag"
    )

    verdict = judge_capture_context_isolation(
        report_match_id="clean-TEST",
        diagnostic_match_id="breakdrive-diagnostic-TEST",
        expected_frag_diagnostics=3,
        report_frag=report_frag,
        diagnostic_frag=diagnostic_frag,
        report_health={"status": "ok"},
        diagnostic_health={"status": "ok"},
        report_authorization=report_authorization,
        diagnostic_authorization=diagnostic_authorization,
    )

    assert verdict["status"] == "ok"
    assert report_frag["daemon_rejected"] == 0
    assert report_frag["correlation_failure_count"] == 0
    assert report_authorization["authorized"] is True
    assert diagnostic_frag["daemon_rejected"] == 3
    assert diagnostic_frag["correlation_failure_count"] == 3
    assert diagnostic_frag["daemon_accepted"] == 1
    assert verdict["checks"]["diagnostic_frag_accepted"] is True
    assert diagnostic_authorization["authorized"] is False
    assert any(
        "frag counters do not reconcile" in error
        for error in diagnostic_authorization["errors"]
    )

    generated = generate_lane_b_report(ExtractorDb(), "extractor-TEST", tmp_path)
    assert generated["facts"]["match"]["scoring_iteration"] == "v6_schema22_2s"
    assert generated["facts"]["match"]["capture_authorization"][
        "authorized"
    ] is True
    assert generated["verification"]["status"] == "PASS"


def test_breakdrive_isolation_reconciles_the_actual_staged_diagnostics():
    """A temporarily unavailable stage must not invent a third death."""
    report_authorization = {"authorized": True, "errors": []}
    diagnostic_authorization = {
        "authorized": False,
        "errors": ["half 1 frag counters do not reconcile"],
    }
    verdict = judge_capture_context_isolation(
        report_match_id="clean-TEST",
        diagnostic_match_id="breakdrive-diagnostic-TEST",
        expected_frag_diagnostics=2,
        report_frag={"daemon_rejected": 0, "correlation_failure_count": 0},
        diagnostic_frag={
            "daemon_accepted": 1,
            "daemon_rejected": 2,
            "correlation_failure_count": 2,
        },
        report_health={"status": "ok"},
        diagnostic_health={"status": "ok"},
        report_authorization=report_authorization,
        diagnostic_authorization=diagnostic_authorization,
    )

    assert verdict["status"] == "ok"
    assert verdict["checks"]["has_intentional_diagnostics"] is True
    assert verdict["checks"]["diagnostic_frag_exact"] is True


@pytest.mark.parametrize("accepted", (0, 2, 6))
def test_breakdrive_isolation_requires_exactly_one_accepted_diagnostic_frag(
        accepted: int):
    report_authorization = {"authorized": True, "errors": []}
    diagnostic_authorization = {
        "authorized": False,
        "errors": ["half 1 frag counters do not reconcile"],
    }
    verdict = judge_capture_context_isolation(
        report_match_id="clean-TEST",
        diagnostic_match_id="breakdrive-diagnostic-TEST",
        expected_frag_diagnostics=3,
        report_frag={"daemon_rejected": 0, "correlation_failure_count": 0},
        diagnostic_frag={
            "daemon_accepted": accepted,
            "daemon_rejected": 3,
            "correlation_failure_count": 3,
        },
        report_health={"status": "ok"},
        diagnostic_health={"status": "ok"},
        report_authorization=report_authorization,
        diagnostic_authorization=diagnostic_authorization,
    )

    assert verdict["status"] == "pipeline"
    assert verdict["checks"]["diagnostic_frag_exact"] is True
    assert verdict["checks"]["diagnostic_frag_accepted"] is False


@pytest.mark.parametrize("latency", (0, 1, 2, 3))
def test_schema22_manifest_activation_receipt_latency_is_authorized(
        latency: int):
    manifest = [{
        "half": 1, "schema_version": 22,
        "capabilities": "objective_attempt,grenade_entity",
        "position_interval": 2.0,
        "match_start_epoch": 100,
        "producer_activation_epoch": 99,
        "activation_receipt_epoch": 100 + latency,
    }]

    authorization = evaluate_capture_authorization(
        {1}, manifest, _schema22_health(), require_activation=True
    )

    assert authorization["authorized"] is True


@pytest.mark.parametrize("receipt", (99, 104, None))
def test_schema22_manifest_activation_receipt_outside_policy_is_unauthorized(
        receipt: int | None):
    manifest = [{
        "half": 1, "schema_version": 22,
        "capabilities": "objective_attempt,grenade_entity",
        "position_interval": 2.0,
        "match_start_epoch": 100,
        "producer_activation_epoch": 99,
        "activation_receipt_epoch": receipt,
    }]

    authorization = evaluate_capture_authorization(
        {1}, manifest, _schema22_health(), require_activation=True
    )

    assert authorization["authorized"] is False
    assert any("manifest activation" in error
               for error in authorization["errors"])


def test_schema22_missing_producer_activation_epoch_is_unauthorized():
    manifest = [{
        "half": 1, "schema_version": 22,
        "capabilities": "objective_attempt,grenade_entity",
        "position_interval": 2.0,
        "match_start_epoch": 100,
        "producer_activation_epoch": None,
        "activation_receipt_epoch": 100,
    }]

    authorization = evaluate_capture_authorization(
        {1}, manifest, _schema22_health(), require_activation=True
    )

    assert authorization["authorized"] is False
    assert any("producer activation" in error
               for error in authorization["errors"])


def test_schema22_never_confirmed_without_manifest_is_not_authorized():
    authorization = evaluate_capture_authorization(
        {1}, [], _schema22_health(), require_activation=True
    )

    assert authorization["authorized"] is False
    assert any("manifest half set/count" in error
               for error in authorization["errors"])


def test_match_log_segments_keep_breakdrive_markers_out_of_clean_context():
    clean_start = (
        'L 08/25/2026 - 10:00:00: KTP_MATCH_START '
        '(matchid "clean-TEST") (half "1st")'
    )
    clean_end = (
        'L 08/25/2026 - 10:06:00: KTP_MATCH_END '
        '(matchid "clean-TEST") (status "test")'
    )
    diagnostic_start = (
        'L 08/25/2026 - 10:06:05: KTP_MATCH_START '
        '(matchid "diagnostic-TEST") (half "1st")'
    )
    diagnostic_end = (
        'L 08/25/2026 - 10:07:00: KTP_MATCH_END '
        '(matchid "diagnostic-TEST") (status "test")'
    )
    synthetic = (
        '[KTPBreakDrive.amxx] [BD] kill flag=1 capteam=2 mode=far '
        'victim=9 vname=GLaDOS killer=1 kname=Leon dist=1000 '
        'count_before=2 owner_before=1'
    )
    log = "\n".join([
        clean_start, '"A" triggered "frag_context"', clean_end,
        '"A" triggered "weaponstats"', diagnostic_start, synthetic,
        diagnostic_end,
    ])

    clean = match_log_segment(log, "clean-TEST")
    diagnostic = match_log_segment(log, "diagnostic-TEST")

    assert synthetic not in clean
    assert 'triggered "weaponstats"' in clean
    assert synthetic in diagnostic


def test_diagnostic_assist_cannot_fake_clean_kill_switch_recovery():
    report = {
        "assists_before_match": 4,
        "assists_at_clean_match_end": 4,
        # The diagnostic match later raises the global total to five, but that
        # value is intentionally absent from the clean recovery calculation.
        "emitted": {"assist": 5},
    }

    clean_assists = clean_assists_after_reenable(report)
    verdict = check_kill_switch(
        {"kills_while_off": 2, "assists_while_off": 0},
        assists_after_on=clean_assists,
    )

    assert clean_assists == 0
    assert verdict["status"] == "not_exercised"


def test_clean_post_enable_assist_still_proves_kill_switch_recovery():
    report = {
        "assists_before_match": 4,
        "assists_at_clean_match_end": 5,
        "emitted": {"assist": 6},
    }

    clean_assists = clean_assists_after_reenable(report)
    verdict = check_kill_switch(
        {"kills_while_off": 2, "assists_while_off": 0},
        assists_after_on=clean_assists,
    )

    assert clean_assists == 1
    assert verdict["status"] == "ok"


def test_bundle_verifier_rejects_public_positional_data(monkeypatch, tmp_path: Path):
    facts = _facts()
    monkeypatch.setattr(
        "scripts.lane_b_match_report.build_facts",
        lambda *args, **kwargs: (facts, {"retained": False}),
    )
    from scripts import lane_b_match_report

    original = lane_b_match_report.build_bundle

    def leaking_bundle(input_facts, profile, output_dir, **kwargs):
        manifest = original(input_facts, profile, output_dir, **kwargs)
        path = output_dir / "report.json"
        report = json.loads(path.read_text())
        report["players"][0]["pos_x"] = 123
        path.write_text(json.dumps(report), encoding="utf-8")
        return manifest

    monkeypatch.setattr(lane_b_match_report, "build_bundle", leaking_bundle)
    with pytest.raises(ValueError, match="public report contains private keys"):
        generate_lane_b_report(object(), facts["match"]["match_id"], tmp_path)


def _complete_objective_score(match_id="lane-b-unit-TEST"):
    manifest = bytes.fromhex("44" * 32)
    rows = [
        team_score.TeamScoreObservation(
            match_id=match_id, map_name="dod_anzio", match_type=0, half=1,
            tick_seconds=Decimal("10.25"), event_sequence=1, observed_at=None,
            allies_score=0, axis_score=0, allies_team_id=1, axis_team_id=2,
            source_server="lane-b-score-fixture", observation_kind="baseline",
            manifest_content_sha256=manifest,
        ),
        team_score.TeamScoreObservation(
            match_id=match_id, map_name="dod_anzio", match_type=0, half=1,
            tick_seconds=Decimal("360.5"), event_sequence=2, observed_at=None,
            allies_score=1, axis_score=0, allies_team_id=1, axis_team_id=2,
            source_server="lane-b-score-fixture", observation_kind="final",
            manifest_content_sha256=manifest,
        ),
    ]
    context = team_score.ProjectionContext(
        match_id=match_id, map_name="dod_anzio", match_type=0,
        source_server="lane-b-score-fixture", terminal_half=1,
        event_count=3, official_row_count=2, retained_row_count=2,
        events_file_sha256=bytes.fromhex("55" * 32),
        metadata_file_sha256=bytes.fromhex("66" * 32),
        manifest_content_sha256=manifest, observer_closed=True, settled=True,
        lifecycle_complete=True, database_context_valid=True,
    )
    return team_score.project_official_score(rows, context=context)


def test_score_enabled_lane_b_attaches_available_verified_public_artifact(monkeypatch, tmp_path):
    facts = _facts()
    monkeypatch.setattr(
        "scripts.lane_b_match_report.build_facts",
        lambda *args, **kwargs: (facts, {"retained": False}),
    )
    generated = generate_lane_b_report(
        object(), facts["match"]["match_id"], tmp_path,
        objective_score_result=_complete_objective_score(),
        objective_score_required=True,
    )
    assert generated["verification"]["checks"]["objective_score"] == "PASS"
    assert generated["report"]["objectiveScoreTimeline"]["quality"]["status"] == "complete"
    artifact = json.loads((tmp_path / "objective-score-timeline.json").read_text())
    assert artifact["objectiveScoreTimeline"]["teams"] == [
        {"id": "team-1", "label": "Team 1"},
        {"id": "team-2", "label": "Team 2"},
    ]
    assert "selectedMatchId" not in json.dumps(generated["report"])


def test_lane_b_report_rejects_foreign_private_score_binding(monkeypatch, tmp_path):
    facts = _facts()
    monkeypatch.setattr(
        "scripts.lane_b_match_report.build_facts",
        lambda *args, **kwargs: (facts, {"retained": False}),
    )
    with pytest.raises(ValueError, match="foreign match"):
        generate_lane_b_report(
            object(), facts["match"]["match_id"], tmp_path,
            objective_score_result=_complete_objective_score("foreign-TEST"),
            objective_score_required=True,
        )


def test_participation_windows_handle_a_mid_match_substitution():
    samples = [
        {"player_id": 1, "half": 1, "game_time": when}
        for when in (0, 5, 10, 15)
    ] + [
        {"player_id": 2, "half": 1, "game_time": when}
        for when in (20, 25, 30)
    ] + [
        {"player_id": 2, "half": 2, "game_time": when}
        for when in (0, 5, 10)
    ]
    observed = _participation_seconds(samples, 60)
    assert observed == {1: 20.0, 2: 30.0}


def test_ownership_requires_a_two_team_partition_in_every_half():
    flags = [
        {"flag_name": "left"}, {"flag_name": "mid"}, {"flag_name": "right"},
    ]
    incomplete = [
        {"id": index + 1, "half": 1, "flag_name": name,
         "owner_team": 0, "is_initial": 1, "game_time": 0}
        for index, name in enumerate(("left", "mid", "right"))
    ] + [
        {"id": 4, "half": 1, "flag_name": "mid",
         "owner_team": 1, "is_initial": 0, "game_time": 10},
    ]
    assert not _ownership_is_reliable(incomplete, flags, {1})
    complete = incomplete + [
        {"id": 5, "half": 1, "flag_name": "left",
         "owner_team": 1, "is_initial": 0, "game_time": 20},
        {"id": 6, "half": 1, "flag_name": "right",
         "owner_team": 2, "is_initial": 0, "game_time": 20},
    ]
    assert _ownership_is_reliable(complete, flags, {1})
