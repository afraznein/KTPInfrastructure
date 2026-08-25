from __future__ import annotations

from datetime import datetime, timezone

from scripts import canary_evidence


def test_log_inspection_distinguishes_missing_clean_and_errors(tmp_path):
    assert canary_evidence.inspect_logs([])["status"] == "not_provided"
    clean = tmp_path / "clean.log"
    clean.write_text(
        "ordinary match output\nKTP_HEALTH sql_failed=0 sql_retried=0 unresolved_actions=0\n",
        encoding="utf-8",
    )
    assert canary_evidence.inspect_logs([clean])["status"] == "clean"
    bad = tmp_path / "bad.log"
    bad.write_text("DBD::mysql execute failed\nunknown action assist\n", encoding="utf-8")
    report = canary_evidence.inspect_logs([bad])
    assert report["status"] == "errors_found"
    assert report["sql_errors"]["count"] == 1
    assert report["unresolved_actions"]["count"] == 1

    health = tmp_path / "health.log"
    health.write_text(
        "KTP_HEALTH sql_failed=2 sql_retried=1 unresolved_actions=3\n",
        encoding="utf-8",
    )
    report = canary_evidence.inspect_logs([health])
    assert report["sql_errors"]["count"] == 1
    assert report["unresolved_actions"]["count"] == 1


def test_match_type_consistency_fails_closed():
    assert not canary_evidence.classification_evidence([])["consistent"]
    mixed = canary_evidence.classification_evidence([
        {"half": 1, "match_type": 1}, {"half": 2, "match_type": 2},
    ])
    assert mixed["match_type"] is None
    assert mixed["consistent"] is False


def test_ownership_requires_one_zero_time_baseline_per_flag_and_half():
    valid = canary_evidence.ownership_evidence([
        {"half": 1, "flag_index": 0, "is_initial": 1, "game_time": "0.00", "owner_team": 0},
        {"half": 1, "flag_index": 0, "is_initial": 0, "game_time": "5.00", "owner_team": 1},
    ])
    assert valid["baseline_ok"] is True
    assert valid["transition_count"] == 1
    invalid = canary_evidence.ownership_evidence([
        {"half": 1, "flag_index": 0, "is_initial": 0, "game_time": "5.00", "owner_team": 9},
    ])
    assert invalid["baseline_ok"] is False
    assert invalid["invalid_owner_count"] == 1


def test_retention_reports_test_match_eligibility_without_mutation():
    classification = canary_evidence.classification_evidence([
        {"half": 1, "match_type": 0, "start_time": "2026-07-01 00:00:00",
         "end_time": "2026-07-01 01:00:00"},
    ])
    result = canary_evidence.retention_evidence(
        "lane-b-TEST", classification, days=14,
        as_of=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )
    assert result["purge_class"] is True
    assert result["eligible_now"] is True


def test_draft_is_retained():
    classification = canary_evidence.classification_evidence([
        {"half": 1, "match_type": 3, "start_time": "2020-01-01 00:00:00",
         "end_time": "2020-01-01 01:00:00"},
    ])
    result = canary_evidence.retention_evidence(
        "old-draft", classification, days=14,
        as_of=datetime(2026, 8, 1, tzinfo=timezone.utc),
    )
    assert result["purge_class"] is False
    assert result["eligible_now"] is False
