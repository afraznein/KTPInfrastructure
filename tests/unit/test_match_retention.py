from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[2] / "scripts" / "ktp-match-retention.py"
SPEC = importlib.util.spec_from_file_location("ktp_match_retention", SCRIPT)
assert SPEC and SPEC.loader
retention = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(retention)


def test_allowlist_retains_official_and_draft_types():
    assert retention.should_purge(1, "scrim-id")
    assert retention.should_purge(2, "12man-id")
    assert retention.should_purge(0, "12345-TEST")
    for match_type in (0, 3, 4, 5, None):
        assert not retention.should_purge(match_type, "permanent-id")


def test_candidate_sql_is_aged_and_fail_closed():
    sql = retention.candidate_sql(14)
    assert "INTERVAL 14 DAY" in sql
    assert "MIN(match_type) IN (1, 2)" in sql
    assert "COUNT(match_type) = COUNT(*)" in sql
    assert "MAX(match_type) = MIN(match_type)" in sql
    assert "RIGHT(match_id, 5) = '-TEST'" in sql
    assert "MAX(COALESCE(end_time, start_time))" in sql
    assert "match_type IN (0" not in sql


def test_apply_deletes_children_before_match_metadata():
    sql = retention.build_sql(14, apply=True)
    assert "ktp_life_events" in retention.MATCH_TABLES
    assert "DELETE t FROM `ktp_life_events`" in sql
    assert "ktp_assist_events" in retention.MATCH_TABLES
    assert "DELETE t FROM `ktp_assist_events`" in sql
    last_child = max(sql.index(f"DELETE t FROM `{table}`") for table in retention.MATCH_TABLES)
    parent = sql.index("DELETE t FROM `ktp_matches`")
    assert last_child < parent
    assert "GET_LOCK('ktp_match_retention'" in sql


def test_dry_run_contains_no_delete():
    assert "DELETE " not in retention.build_sql(14, apply=False)
