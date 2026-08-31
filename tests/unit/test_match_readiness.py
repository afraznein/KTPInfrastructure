from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import match_readiness


ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "tests/e2e_stats/fixtures/regression-2026-08-14-anzio-5match"
GOLDEN = json.loads((CORPUS / "readiness-golden.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("fixture_name", sorted(GOLDEN["matches"]))
def test_five_match_anzio_readiness_golden(fixture_name):
    """Lock the aggregate source facts for every committed Anzio match."""
    expected = GOLDEN["matches"][fixture_name]
    fixture = CORPUS / fixture_name / "hlstatsx-fixture.sql.gz"
    report = match_readiness.validate_fixture(fixture)

    assert report["match_id"] == expected["match_id"]
    assert report["status"] == expected["status"]
    for key in (
        "event_players", "frags", "coordinate_frags", "damage_events",
        "position_samples", "capture_credits", "unique_capture_events",
        "assists", "cap_breaks",
    ):
        assert report["inventory"][key] == expected[key]

    # These are legacy fixtures, so their limitations must stay visible rather
    # than being repaired or interpreted as real zeroes by the reporter.
    warning_codes = {
        check["code"] for check in report["checks"] if check["level"] == "WARN"
    }
    assert {
        "roster_source_missing", "position_sampling_interval",
        "statsme_coverage", "statsme2_coverage", "flag_ownership_coverage",
        "schema23_position_provenance",
    } <= warning_codes


def test_readiness_payload_excludes_player_identity_and_coordinates():
    report = match_readiness.validate_fixture(
        CORPUS / "match-1/hlstatsx-fixture.sql.gz"
    )
    assert match_readiness.public_payload_is_safe(report) == []
    serialized = json.dumps(report).lower()
    for forbidden in (
        "steam_id", "player_name", "player_id", "killer_id", "victim_id",
        "pos_x", "pos_y", "pos_z",
    ):
        assert forbidden not in serialized


def test_metric_eligibility_distinguishes_complete_partial_and_unavailable():
    checks = [
        {"code": code, "level": "PASS"}
        for requirements in match_readiness.METRIC_REQUIREMENTS.values()
        for code in requirements
    ]
    eligibility = match_readiness.build_metric_eligibility(checks)
    assert eligibility["contract_version"] == 1
    assert {item["status"] for item in eligibility["metrics"].values()} == {"available"}

    checks = [
        {**item, "level": "WARN" if item["code"] == "position_sampling_interval" else item["level"]}
        for item in checks
    ]
    eligibility = match_readiness.build_metric_eligibility(checks)
    assert eligibility["metrics"]["positional_impact"]["status"] == "partial"

    checks = [
        {**item, "level": "FAIL" if item["code"] == "frags_present" else item["level"]}
        for item in checks
    ]
    eligibility = match_readiness.build_metric_eligibility(checks)
    assert eligibility["metrics"]["combat_context"]["status"] == "unavailable"
    assert eligibility["metrics"]["combat_context"]["blocking_checks"] == ["frags_present"]


def test_privacy_guard_normalizes_camel_case_and_snake_case_keys():
    assert match_readiness.public_payload_is_safe({
        "killerId": 1,
        "nested": [{"steam_id": "private"}, {"posVictimX": 12}],
    }) == [
        "report.killerId",
        "report.nested[0].steam_id",
        "report.nested[1].posVictimX",
    ]


def test_cli_warn_is_nonblocking_but_strict_warn_fails(tmp_path):
    fixture = CORPUS / "match-4/hlstatsx-fixture.sql.gz"
    assert match_readiness.main([
        str(fixture), "--output-dir", str(tmp_path / "normal")
    ]) == 0
    assert match_readiness.main([
        str(fixture), "--output-dir", str(tmp_path / "strict"), "--strict"
    ]) == 1
    assert (tmp_path / "normal/MATCH_READINESS.md").is_file()
    assert (tmp_path / "normal/match-readiness.json").is_file()


def test_multiple_match_ids_require_explicit_selection(tmp_path):
    fixture = tmp_path / "two.sql"
    fixture.write_text(
        "INSERT INTO `ktp_matches` (`id`, `match_id`) VALUES (1,'one-TEST');\n"
        "INSERT INTO `ktp_matches` (`id`, `match_id`) VALUES (2,'two-TEST');\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="pass --match-id"):
        match_readiness.validate_fixture(fixture)


def test_damage_same_second_duplicates_are_warning_not_ingest_failure():
    report = match_readiness.validate_fixture(
        CORPUS / "match-1/hlstatsx-fixture.sql.gz"
    )
    duplicate = next(check for check in report["checks"]
                     if check["code"] == "duplicate_damage")
    assert duplicate["level"] == "WARN"
    assert duplicate["evidence"]["duplicates"] > 0
