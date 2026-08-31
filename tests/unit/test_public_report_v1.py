from __future__ import annotations

import json
import os
import threading
import time
from copy import deepcopy
from pathlib import Path

import pytest

from scripts import build_public_report_v1 as public
from scripts import validate_public_report_v1 as validate


ROOT = Path(__file__).resolve().parents[2]
INPUTS = ROOT / "tests" / "fixtures" / "public_report_v1"
PACKET = ROOT / "development_candidate" / "public-report-v1"
GOLDEN = PACKET / "fixtures" / "golden"
NEGATIVE_CASE_COUNT = 156


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def inputs():
    return (
        load(INPUTS / "internal-analytics-v3.json"),
        load(INPUTS / "readiness.json"),
        load(INPUTS / "private-points-timeline.json"),
        load(INPUTS / "private-momentum-episodes.json"),
    )


def build_all():
    analytics, readiness, timeline, episodes = inputs()
    documents = public.build_bundle_documents(
        analytics, readiness, None, timeline, episodes,
        schema_dir=PACKET / "schemas",
    )
    return (
        documents["public-report.json"],
        documents["public-timeline.json"],
        documents["momentum-episodes.json"],
    )


def build_for_match(match_id: str):
    analytics, readiness, timeline, episodes = inputs()
    analytics["match_id"] = analytics["match"]["match_id"] = match_id
    readiness["match_id"] = match_id
    timeline["match_id"] = match_id
    episodes["match_id"] = match_id
    return public.build_bundle_documents(
        analytics, readiness, None, timeline, episodes,
        schema_dir=PACKET / "schemas",
    )


def test_builder_matches_deterministic_goldens_and_cross_document_contract():
    report, timeline, episodes = build_all()
    assert report == load(GOLDEN / "public-report.json")
    assert timeline == load(GOLDEN / "public-timeline.json")
    assert episodes == load(GOLDEN / "momentum-episodes.json")
    public.validate_bundle_consistency(report, timeline, episodes)


def test_public_payloads_have_fixed_match_scoped_team_keys_and_no_provenance():
    report, timeline, episodes = build_all()
    assert [team["team_key"] for team in report["teams"]] == ["team_a", "team_b"]
    assert timeline["team_keys"] == ["team_a", "team_b"]
    assert episodes["team_keys"] == ["team_a", "team_b"]
    serialized = json.dumps([report, timeline, episodes]).casefold()
    for field in (
        '"provenance"', '"player_id"', '"steam_id"', '"database_id"',
        '"elo"', '"bradley_terry"', '"impact_rating"', '"overall_rating"',
        '"accumulated_rating"', '"rank"', '"raw_points"', '"components"',
        '"allocations"', '"ledger"', '"position_samples"',
    ):
        assert field not in serialized
    assert all(public.privacy_violations(document) == [] for document in (report, timeline, episodes))


def test_box_score_zero_null_plus_minus_and_additive_totals_are_consistent():
    report, _, _ = build_all()
    team_a, team_b = report["teams"]
    alpha, bravo = report["players"]
    assert team_a["kills"] == alpha["kills"] == 5
    assert team_b["kills"] == bravo["kills"] == 4
    assert team_a["plus_minus"] == alpha["plus_minus"] == 1
    assert team_b["plus_minus"] == bravo["plus_minus"] == -1
    assert alpha["team_kills"] == 0
    assert alpha["metric_status"]["team_kills"]["availability"] == "available"
    assert bravo["team_kills"] is None
    assert bravo["metric_status"]["team_kills"] == {
        "availability": "unavailable", "confidence": "unavailable",
        "reason_code": "not_supplied",
    }
    assert bravo["raw_accuracy"] is None
    assert bravo["metric_status"]["raw_accuracy"]["reason_code"] == "undefined_zero_denominator"
    public.validate_public_report_semantics(report)


def test_every_metric_value_status_pair_obeys_null_semantics():
    report, _, _ = build_all()
    for row in report["teams"] + report["players"]:
        for metric in public.BOX_METRICS:
            value = row[metric]
            status = row["metric_status"][metric]
            if status["availability"] == "unavailable":
                assert value is None
                assert status["confidence"] == "unavailable"
                assert status["reason_code"] not in {"none", "low_sample", "synthetic_fixture"}
            else:
                assert isinstance(value, (int, float)) and not isinstance(value, bool)
                assert status["confidence"] != "unavailable"


def test_low_sample_requires_a_value_and_closed_reason_code():
    analytics, _, _, _ = inputs()
    analytics["match_id"] = analytics["match"]["match_id"] = "human-example"
    analytics["match"]["is_test_match"] = 0
    analytics["players"][0]["confidence"] = {
        "raw_accuracy": {"level": "low_sample", "reason": "STEAM_1:0:99 G:\\private"}
    }
    report = public.build_public_report(analytics)
    assert report["players"][0]["metric_status"]["raw_accuracy"] == {
        "availability": "low_sample", "confidence": "low_sample",
        "reason_code": "low_sample",
    }
    assert "STEAM" not in json.dumps(report) and "private" not in json.dumps(report).casefold()


def test_upstream_readiness_prose_is_never_copied():
    analytics, readiness, _, _ = inputs()
    readiness["checks"] = [{
        "level": "WARN", "code": "internal",
        "message": "STEAM_1:0:9 at G:\\private\\report.json",
    }]
    report = public.build_public_report(analytics, readiness)
    assert report["quality"] == {"analytics_status": "PASS", "readiness_status": "WARN"}
    serialized = json.dumps(report)
    assert "STEAM" not in serialized and "G:\\" not in serialized


@pytest.mark.parametrize("unsafe", [
    "STEAM_1:0:1234", "76561198000000000", "dod_76561198000000000",
    "Player76561198000000000", "steamid-abc", "player_id=abc",
    "actor-id=abc", "https://private.example/1", "G:\\private\\one.json",
    "source schema 3", "source_schema_3", "source-schema", "ProvenanceData",
    "audit_player_key_deadbeef", "hmac_identity_deadbeef", "elo_rating_1500",
    "overall-rating-120", "bradley_terry_rating", "posx_123",
    "position_sample_12", "coordinates_12",
])
def test_non_display_sensitive_strings_fail_closed(unsafe):
    analytics, _, _, _ = inputs()
    analytics["match"]["map_name"] = unsafe
    with pytest.raises(public.PublicContractError):
        public.build_public_report(analytics)


def test_display_names_have_separate_validation_and_are_not_html_interpreted_here():
    analytics, _, _, _ = inputs()
    analytics["players"][0]["player_name_at_match"] = "Alpha <script>"
    report = public.build_public_report(analytics)
    assert report["players"][0]["name"] == "Alpha <script>"
    analytics["players"][0]["player_name_at_match"] = "STEAM_1:0:1234"
    with pytest.raises(public.PublicContractError, match="display name"):
        public.build_public_report(analytics)


@pytest.mark.parametrize("name", [
    "Player76561198000000000", "source_schema_3", "actor-id=abc",
    "audit_player_key_deadbeef", "hmac_identity_deadbeef", "elo_rating_1500",
    "posx_123",
])
def test_display_names_reject_normalized_or_embedded_sensitive_values(name):
    analytics, _, _, _ = inputs()
    analytics["players"][0]["player_name_at_match"] = name
    with pytest.raises(public.PublicContractError, match="display name"):
        public.build_public_report(analytics)


@pytest.mark.parametrize("unsafe", [
    "HMACPlayerKeydeadbeef", "AuditIdentitydeadbeef", "Elo1500", "Rating1500",
    "Position12", "Coordinates12", "Route12", "Cell12",
    "Clan-HMACPlayerKeydeadbeef", "Clan-Elo1500", "Map-Rating1500",
    "Map-Position12", "Map-Coordinates12", "Map-Route12", "Map-Cell12",
    "ClanHMACPlayerKeydeadbeef", "ClanElo1500", "MapRating1500",
    "MapPosition12", "MapCoordinates12", "MapRoute12", "MapCell12",
    "DevelopmentElo1500", "GoldenElo1500", "MelodyElo1500",
    "OperatingRating1500", "OppositionPosition12",
    "ClanHMACIdentitydeadbeef", "ClanEloScore1500", "MapRatingValue1500",
    "MapPositionSamples12", "MapCoordinateData12", "MapRouteData12",
    "MapCellKey12",
    "HMACAuditKeydeadbeef", "HMACAuditdeadbeef",
    "HMACAuditIdentitydeadbeef", "HMACAuditPlayerKeydeadbeef",
    "EloRank1500", "EloRanks1500", "EloRanked1500", "EloRanking1500",
    "HMACAuditIDdeadbeef", "EloPlayerRank1500", "EloPlayerRanks1500",
    "EloPlayerRanked1500", "EloPlayerRanking1500",
    "HMACAuditPrivateKeydeadbeef", "HMACAuditDigestdeadbeef",
    "HMACAuditSignaturedeadbeef",
])
def test_concatenated_sensitive_public_boundary_terms_fail_all_string_guards(unsafe):
    assert public.sensitive_string_reason(unsafe)
    with pytest.raises(public.PublicContractError, match="display name"):
        public.safe_display_name(unsafe, label="test")
    analytics, _, _, _ = inputs()
    analytics["match"]["map_name"] = unsafe
    with pytest.raises(public.PublicContractError):
        public.build_public_report(analytics)


@pytest.mark.parametrize("key", [
    "source_schema", "internal_player_id_copy", "hmac_audit_identity",
    "elo_rating_copy", "position_sample_copy",
])
def test_deep_privacy_rejects_normalized_embedded_restricted_keys(key):
    assert public.sensitive_key_reason(key)
    assert public.privacy_violations({"outer": {key: "safe"}}) == [f"public.outer.{key}"]


def test_ordinary_safe_map_and_display_names_remain_allowed():
    for map_name in (
        "dod_anzio", "dod_harrington", "dod_aleutian2_test3",
        "packet-stale-lock-TEST",
    ):
        assert public.sensitive_string_reason(map_name) is None
    for display_name in (
        "Melody Makers", "Operating Crew", "Opposition Blue", "Penelope",
        "Eloise", "Melodic Crew", "Cellophane", "Cellar Door",
        "Celebrating Crew", "Migrating Birds", "Developmental Team", "Router",
    ):
        assert public.safe_display_name(display_name, label="test") == display_name
        analytics, _, _, _ = inputs()
        analytics["players"][0]["player_name_at_match"] = display_name
        assert public.build_public_report(analytics)["players"][0]["name"] == display_name


def test_team_mapping_is_explicit_complete_and_never_inferred_from_integers():
    analytics, _, timeline, _ = inputs()
    analytics["match"]["public_teams"][0]["side_by_half"].pop()
    with pytest.raises(public.PublicContractError, match="every played half"):
        public.build_public_report(analytics)
    timeline["teams"] = [1, 2]
    with pytest.raises(public.PublicContractError, match="team_a"):
        public.build_public_timeline(timeline)

    analytics, _, _, _ = inputs()
    analytics["match"]["public_teams"][1]["side_by_half"][0]["side"] = "allies"
    with pytest.raises(public.PublicContractError, match="same known side"):
        public.build_public_report(analytics)

    analytics, _, _, _ = inputs()
    analytics["match"]["public_teams"][0]["side_by_half"][0]["half"] = True
    with pytest.raises(public.PublicContractError, match="boolean"):
        public.build_public_report(analytics)


@pytest.mark.parametrize("field,value", [
    ("halves_played", 11), ("halves_played", 0),
    ("duration_seconds", -1), ("duration_seconds", 21_600.01),
])
def test_report_match_numeric_domains_fail_closed(field, value):
    analytics, _, _, _ = inputs()
    analytics["match"][field] = value
    with pytest.raises(public.PublicContractError, match=field):
        public.build_public_report(analytics)


@pytest.mark.parametrize("field,value", [
    ("kills", -1), ("kills", 1_000_001),
    ("damage_dealt", 1_000_001), ("raw_accuracy", 1.01),
])
def test_box_metric_numeric_domains_fail_closed(field, value):
    analytics, _, _, _ = inputs()
    analytics["players"][0][field] = value
    with pytest.raises(public.PublicContractError, match=field):
        public.build_public_report(analytics)


def test_timeline_reconciliation_is_half_end_only_and_conserves_both_equations():
    _, timeline, _ = build_all()
    half = timeline["halves"][0]
    assert sum(row["teams"]["team_a"]["points_gained"] for row in half["bins"]) == 45
    assert all(set(row["teams"]["team_a"]) == {"points_gained", "cumulative_points"} for row in half["bins"])
    assert half["half_end_annotations"] == [
        {"team_key": "team_a", "kind": "untimed_reconciliation"},
        {"team_key": "team_b", "kind": "untimed_reconciliation"},
    ]
    team_a = half["conservation"]["teams"][0]
    assert team_a["timed_total"] == team_a["timed_gain_sum"] == 45
    assert team_a["reconciled_total"] == team_a["timed_total"] + team_a["untimed_reconciliation_delta"] == 50
    assert team_a["timed_difference"] == team_a["reconciled_difference"] == 0
    assert team_a["status"] == "pass"


def test_missing_timeline_totals_stay_null_and_downgrade_coverage_and_conservation():
    _, _, source, _ = inputs()
    source["halves"][0]["bins"][1]["teams"]["team_a"]["cumulative_timed_points"] = None
    timeline = public.build_public_timeline(source)
    last = timeline["halves"][0]["bins"][1]
    assert last["teams"]["team_a"]["cumulative_points"] is None
    assert last["coverage"] == {"status": "partial", "reason_code": "missing_totals"}
    assert timeline["coverage"] == {"status": "partial", "reason_code": "partial_input"}
    conservation = timeline["halves"][0]["conservation"]["teams"][0]
    assert conservation["status"] == "unavailable"
    assert conservation["reason_code"] == "missing_totals"


def test_timeline_recurrence_resets_at_half_and_rejects_bad_intermediate_values():
    _, _, source, _ = inputs()
    source["halves"][0]["bins"][1]["teams"]["team_a"]["cumulative_timed_points"] = 46
    with pytest.raises(public.PublicContractError, match="cumulative_points recurrence"):
        public.build_public_timeline(source)

    _, _, source, _ = inputs()
    source["halves"][0]["bins"][1]["momentum_change"] = -10
    with pytest.raises(public.PublicContractError, match="momentum_change recurrence"):
        public.build_public_timeline(source)

    _, _, source, _ = inputs()
    source["halves"][0]["bins"][0]["teams"]["team_a"]["timed_points_gained"] = None
    with pytest.raises(public.PublicContractError, match="cannot resume"):
        public.build_public_timeline(source)

    _, _, source, _ = inputs()
    second_half = deepcopy(source["halves"][0])
    second_half["half"] = 2
    source["halves_played"] = 2
    source["halves"].append(second_half)
    timeline = public.build_public_timeline(source)
    assert [
        half["bins"][0]["teams"]["team_a"]["cumulative_points"]
        for half in timeline["halves"]
    ] == [45.0, 45.0]


@pytest.mark.parametrize(
    "path,reason",
    [
        (("teams", "team_a", "cumulative_timed_points"), "missing_totals"),
        (("momentum",), "missing_momentum"),
        (("momentum_change",), "missing_momentum"),
    ],
)
def test_builder_and_validator_reject_recurrence_resumption_after_null_member(path, reason):
    _, _, source, _ = inputs()
    source_bin = source["halves"][0]["bins"][0]
    target = source_bin
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = None
    with pytest.raises(public.PublicContractError, match="cannot resume"):
        public.build_public_timeline(source)

    _, timeline, _ = build_all()
    public_bin = timeline["halves"][0]["bins"][0]
    target = public_bin
    public_path = tuple(
        "cumulative_points" if key == "cumulative_timed_points" else key
        for key in path
    )
    for key in public_path[:-1]:
        target = target[key]
    target[public_path[-1]] = None
    public_bin["coverage"] = {"status": "partial", "reason_code": reason}
    with pytest.raises(public.PublicContractError, match="cannot resume"):
        public.validate_public_timeline_semantics(timeline)


@pytest.mark.parametrize("mutation,match", [
    (("bin_seconds", 301), "bin_seconds"),
    (("bin_seconds", 0), "bin_seconds"),
    (("halves_played", 11), "halves_played"),
])
def test_timeline_top_numeric_domains_fail_closed(mutation, match):
    _, _, source, _ = inputs()
    field, value = mutation
    source[field] = value
    with pytest.raises(public.PublicContractError, match=match):
        public.build_public_timeline(source)


def test_timeline_half_rejects_boolean_numeric_alias():
    _, _, source, _ = inputs()
    source["halves"][0]["half"] = True
    with pytest.raises(public.PublicContractError, match="boolean"):
        public.build_public_timeline(source)


@pytest.mark.parametrize("path,value,match", [
    (("start_time",), -1, "start_time"),
    (("end_time",), 21_600.01, "end_time"),
    (("momentum",), 1_000_001, "momentum"),
    (("teams", "team_a", "timed_points_gained"), 1_000_000_001, "timed_points_gained"),
])
def test_timeline_bin_numeric_domains_fail_closed(path, value, match):
    _, _, source, _ = inputs()
    target = source["halves"][0]["bins"][0]
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(public.PublicContractError, match=match):
        public.build_public_timeline(source)


def test_complete_intervals_are_contiguous_and_only_final_bin_may_be_shorter():
    _, _, source, _ = inputs()
    source["halves"][0]["bins"][0]["end_time"] = 14
    with pytest.raises(public.PublicContractError, match="explicit partial"):
        public.build_public_timeline(source)

    _, _, source, _ = inputs()
    source["halves"][0]["bins"][1]["end_time"] = 29
    timeline = public.build_public_timeline(source)
    assert timeline["halves"][0]["bins"][1]["coverage"] == {
        "status": "available", "reason_code": "complete",
    }

    _, _, source, _ = inputs()
    source["halves"][0]["bins"][0]["end_time"] = 14
    source["halves"][0]["bins"][0]["coverage"] = {
        "status": "partial", "reason_code": "irregular_interval",
    }
    source["halves"][0]["bins"][1]["coverage"] = {
        "status": "partial", "reason_code": "irregular_interval",
    }
    timeline = public.build_public_timeline(source)
    assert timeline["coverage"] == {
        "status": "partial", "reason_code": "irregular_interval",
    }


def test_bad_reconciliation_is_fail_not_pass():
    _, _, source, _ = inputs()
    source["halves"][0]["reconciled_total_by_team"]["team_a"] = 999
    timeline = public.build_public_timeline(source)
    conservation = timeline["halves"][0]["conservation"]["teams"][0]
    assert conservation["status"] == "fail"
    assert conservation["reason_code"] == "equation_mismatch"
    assert conservation["reconciled_difference"] == 949


def test_empty_timeline_has_explicit_unavailable_coverage():
    _, _, source, _ = inputs()
    source["halves"] = []
    timeline = public.build_public_timeline(source)
    assert timeline["halves"] == []
    assert timeline["coverage"] == {"status": "unavailable", "reason_code": "no_bins"}


@pytest.mark.parametrize("source_index,label", [
    (0, "analytics box score"), (1, "readiness report"),
    (2, "private timeline"), (3, "private momentum episodes"),
])
def test_all_private_input_versions_are_checked(source_index, label):
    sources = list(inputs())
    sources[source_index]["schema_version"] = 999
    with pytest.raises(public.PublicContractError, match=label):
        public.build_bundle_documents(
            sources[0], sources[1], None, sources[2], sources[3],
            schema_dir=PACKET / "schemas",
        )


def test_momentum_is_canonically_sorted_stably_identified_and_has_closed_coverage():
    _, _, _, source = inputs()
    second = deepcopy(source["episodes"][0])
    second.update({
        "start_time": 20, "end_time": 25, "start_momentum": 8.5,
        "end_momentum": 6.5, "swing": -2, "contribution": {"value": -2},
        "team_key": "team_b", "reason_codes": ["cap_break"], "clip_ref": None,
    })
    forward = public.sanitize_momentum_episodes(
        [second, source["episodes"][0]], match_id=source["match_id"],
        halves_played=source["halves_played"],
    )
    reverse = public.sanitize_momentum_episodes(
        [source["episodes"][0], second], match_id=source["match_id"],
        halves_played=source["halves_played"],
    )
    assert forward == reverse
    assert [row["start_time"] for row in forward["episodes"]] == [0, 20]
    assert len({row["episode_id"] for row in forward["episodes"]}) == 2
    empty = public.sanitize_momentum_episodes(
        [], match_id=source["match_id"], halves_played=source["halves_played"]
    )
    assert empty["coverage"] == {"status": "unavailable", "reason_code": "no_episodes"}


@pytest.mark.parametrize("field,value,match", [
    ("end_time", -1, "end_time"),
    ("swing", 99, "swing"),
    ("clip_ref", "https://vod.example/1", "clip_ref"),
    ("clip_ref", "STEAM_1:0:1234", "clip_ref"),
])
def test_momentum_invalid_time_swing_and_clip_fail_closed(field, value, match):
    _, _, _, source = inputs()
    source["episodes"][0][field] = value
    with pytest.raises(public.PublicContractError, match=match):
        public.sanitize_momentum_episodes(
            source["episodes"], match_id=source["match_id"],
            halves_played=source["halves_played"],
        )


@pytest.mark.parametrize("clip", [
    "clip_A1b2c3d4e5f60718293a4b5c6d7e8f90",
    "clip_76561198000000000123456789012345",
    "clip_a1b2c3",
])
def test_clip_token_requires_exact_lowercase_opaque_32_hex_body(clip):
    _, _, _, source = inputs()
    source["episodes"][0]["clip_ref"] = clip
    with pytest.raises(public.PublicContractError, match="clip_ref"):
        public.sanitize_momentum_episodes(
            source["episodes"], match_id=source["match_id"],
            halves_played=source["halves_played"],
        )


@pytest.mark.parametrize("field,value", [
    ("half", 11), ("start_time", 21_600.01),
    ("start_momentum", -1_000_001), ("end_momentum", 1_000_001),
])
def test_momentum_numeric_domains_fail_closed(field, value):
    _, _, _, source = inputs()
    source["halves_played"] = 10
    source["episodes"][0][field] = value
    with pytest.raises(public.PublicContractError):
        public.sanitize_momentum_episodes(
            source["episodes"], match_id=source["match_id"],
            halves_played=source["halves_played"],
        )


def test_private_scoring_is_version_checked_but_never_exported():
    analytics, readiness, timeline, episodes = inputs()
    private = {
        "schema_version": 1, "match_id": analytics["match_id"],
        "players": [{"player_id": 1, "elo": 1600, "total_points": 9000}],
    }
    documents = public.build_bundle_documents(
        analytics, readiness, private, timeline, episodes,
        schema_dir=PACKET / "schemas",
    )
    serialized = json.dumps(documents)
    assert "1600" not in serialized and "9000" not in serialized
    private["schema_version"] = 999
    with pytest.raises(public.PublicContractError, match="private scoring report"):
        public.build_bundle_documents(
            analytics, readiness, private, timeline, episodes,
            schema_dir=PACKET / "schemas",
        )


def test_atomic_publish_replaces_complete_directory_without_mixing(tmp_path):
    report, timeline, episodes = build_all()
    documents = {
        "public-report.json": report, "public-timeline.json": timeline,
        "momentum-episodes.json": episodes,
    }
    output = tmp_path / "bundle"
    public.publish_bundle_atomic(output, documents, replace=False)
    stale = output / "stale-other-match.json"
    stale.write_text("{}", encoding="utf-8")
    with pytest.raises(public.PublicContractError, match="not one complete"):
        public.publish_bundle_atomic(output, documents, replace=True)
    stale.unlink()
    public.publish_bundle_atomic(output, documents, replace=True)
    assert {path.name for path in output.iterdir()} == set(documents)
    with pytest.raises(FileExistsError):
        public.publish_bundle_atomic(output, documents, replace=False)


def test_bundle_build_failure_happens_before_existing_output_is_touched(tmp_path):
    analytics, readiness, timeline, episodes = inputs()
    output = tmp_path / "bundle"
    output.mkdir()
    sentinel = output / "sentinel.txt"
    sentinel.write_text("unchanged", encoding="utf-8")
    timeline["match_id"] = "other-match"
    with pytest.raises(public.PublicContractError, match="different match IDs"):
        public.build_bundle_documents(
            analytics, readiness, None, timeline, episodes,
            schema_dir=PACKET / "schemas",
        )
    assert sentinel.read_text(encoding="utf-8") == "unchanged"


def test_cross_document_halves_episode_bounds_duration_and_versions_fail_closed():
    report, timeline, episodes = build_all()
    broken = deepcopy(episodes)
    broken["episodes"][0]["half"] = 99
    with pytest.raises(public.PublicContractError, match="absent from the timeline"):
        public.validate_bundle_consistency(report, timeline, broken)

    broken = deepcopy(episodes)
    broken["episodes"][0]["end_time"] = 31
    with pytest.raises(public.PublicContractError, match="outside its timeline half"):
        public.validate_bundle_consistency(report, timeline, broken)

    broken_report = deepcopy(report)
    broken_report["match"]["duration_seconds"] = 31
    with pytest.raises(public.PublicContractError, match="duration"):
        public.validate_bundle_consistency(broken_report, timeline, episodes)

    broken = deepcopy(timeline)
    broken["contract_version"] = "1.1.0"
    with pytest.raises(public.PublicContractError, match="contract versions"):
        public.validate_bundle_consistency(report, broken, episodes)


def test_concurrent_publishers_serialize_without_mixing_or_residue(tmp_path):
    documents_a = build_for_match("concurrent-a-TEST")
    documents_b = build_for_match("concurrent-b-TEST")
    output = tmp_path / "bundle"
    first_holds_lock = threading.Event()
    release_first = threading.Event()
    errors: list[BaseException] = []

    def hold_first() -> None:
        first_holds_lock.set()
        if not release_first.wait(timeout=5):
            raise RuntimeError("test failed to release first publisher")

    def publish(documents, *, replace, hook=None):
        try:
            public.publish_bundle_atomic(
                output, documents, replace=replace, lock_wait_seconds=5,
                lock_hold_hook=hook,
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    first = threading.Thread(
        target=publish, args=(documents_a,), kwargs={"replace": False, "hook": hold_first}
    )
    second = threading.Thread(
        target=publish, args=(documents_b,), kwargs={"replace": True}
    )
    first.start()
    assert first_holds_lock.wait(timeout=5)
    second.start()
    release_first.set()
    first.join(timeout=10)
    second.join(timeout=10)
    assert not first.is_alive() and not second.is_alive()
    assert errors == []
    final = {path.name: load(path) for path in output.iterdir()}
    assert final == documents_b
    leftovers = [
        path.name for path in tmp_path.iterdir()
        if path != output and path.name.startswith(".bundle.")
    ]
    assert leftovers == []


def test_stale_lock_is_quarantined_reclaimed_and_fully_cleaned(tmp_path):
    documents = build_for_match("stale-reclaim-TEST")
    output = tmp_path / "bundle"
    lock_dir = tmp_path / ".bundle.publish.lock"
    lock_dir.mkdir()
    (lock_dir / "owner.json").write_text(
        json.dumps({"owner_token": "crashed"}) + "\n", encoding="utf-8"
    )
    old = time.time() - public.MIN_STALE_LOCK_SECONDS - 10
    os.utime(lock_dir, (old, old))
    public.publish_bundle_atomic(
        output, documents, replace=False,
        stale_lock_seconds=public.MIN_STALE_LOCK_SECONDS,
        lock_wait_seconds=1,
    )
    assert {path.name for path in output.iterdir()} == set(documents)
    assert [path.name for path in tmp_path.iterdir() if path != output] == []


def test_crash_between_backup_and_install_restores_old_bundle_and_cleans_residue(tmp_path):
    old_documents = build_for_match("crash-recovery-old-TEST")
    next_documents = build_for_match("crash-recovery-next-TEST")
    output = tmp_path / "bundle"
    public.publish_bundle_atomic(output, old_documents, replace=False)

    backup = tmp_path / ".bundle.old-crashed"
    output.rename(backup)
    temporary = tmp_path / ".bundle.tmp-crashed"
    temporary.mkdir()
    for name, document in next_documents.items():
        (temporary / name).write_text(
            json.dumps(document, indent=2) + "\n", encoding="utf-8"
        )
    orphan_quarantine = tmp_path / ".bundle.stale-lock-orphan"
    orphan_quarantine.mkdir()
    lock_dir = tmp_path / ".bundle.publish.lock"
    lock_dir.mkdir()
    (lock_dir / "owner.json").write_text(
        json.dumps({"owner_token": "crashed"}) + "\n", encoding="utf-8"
    )
    old = time.time() - public.MIN_STALE_LOCK_SECONDS - 10
    os.utime(lock_dir, (old, old))

    with pytest.raises(FileExistsError):
        public.publish_bundle_atomic(
            output, next_documents, replace=False,
            stale_lock_seconds=public.MIN_STALE_LOCK_SECONDS,
            lock_wait_seconds=1,
        )

    assert {path.name: load(path) for path in output.iterdir()} == old_documents
    assert [path.name for path in tmp_path.iterdir()] == ["bundle"]


@pytest.mark.parametrize("threshold", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_stale_threshold_never_steals_a_live_lock(tmp_path, threshold):
    documents = build_for_match("nonfinite-lock-TEST")
    output = tmp_path / "bundle"
    lock_dir = tmp_path / ".bundle.publish.lock"
    lock_dir.mkdir()
    owner = {"owner_token": "live-owner"}
    owner_file = lock_dir / "owner.json"
    owner_file.write_text(json.dumps(owner) + "\n", encoding="utf-8")
    original_mtime = lock_dir.stat().st_mtime_ns

    with pytest.raises(public.PublicContractError, match="finite and at least 300"):
        public.publish_bundle_atomic(
            output, documents, replace=False,
            stale_lock_seconds=threshold, lock_wait_seconds=0,
        )

    assert json.loads(owner_file.read_text(encoding="utf-8")) == owner
    assert lock_dir.stat().st_mtime_ns == original_mtime


def test_lock_thresholds_are_bounded(tmp_path):
    documents = build_for_match("lock-bounds-TEST")
    with pytest.raises(public.PublicContractError, match="at least 300"):
        public.publish_bundle_atomic(
            tmp_path / "too-fresh", documents, replace=False,
            stale_lock_seconds=299, lock_wait_seconds=0,
        )
    with pytest.raises(public.PublicContractError, match="between 0 and 3600"):
        public.publish_bundle_atomic(
            tmp_path / "too-long", documents, replace=False,
            lock_wait_seconds=3601,
        )


def test_packet_schemas_semantics_cross_document_and_all_negative_cases_validate():
    pytest.importorskip("jsonschema")
    result = validate.validate_packet(PACKET)
    assert result["status"] == "PASS"
    assert len(result["positive"]) == 3
    assert result["cross_document"]["status"] == "PASS"
    assert len(result["negative"]) == NEGATIVE_CASE_COUNT
    assert all(row["status"] == "PASS" for row in result["negative"])


def test_public_schema_is_strict_and_contains_no_provenance_field():
    pytest.importorskip("jsonschema")
    schema = load(PACKET / "schemas" / "public-report-v1.schema.json")
    assert schema["additionalProperties"] is False
    assert "provenance" not in schema["properties"]
    report, _, _ = build_all()
    malformed = deepcopy(report)
    malformed["players"][0]["overall_rating"] = 120
    validator = validate.validator_for(PACKET / "schemas" / "public-report-v1.schema.json")
    assert list(validator.iter_errors(malformed))


def test_every_public_payload_and_schema_uses_full_contract_version_1_2_0():
    report, timeline, episodes = build_all()
    assert {item["contract_version"] for item in (report, timeline, episodes)} == {"1.2.0"}
    for name in (
        "public-report-v1.schema.json", "public-timeline-v1.schema.json",
        "momentumEpisode-v1.schema.json",
    ):
        schema = load(PACKET / "schemas" / name)
        assert "/1.2.0/" in schema["$id"]
        assert schema["properties"]["contract_version"] == {"const": "1.2.0"}
