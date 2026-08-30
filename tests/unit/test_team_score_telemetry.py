from __future__ import annotations

import json
import shutil
import subprocess
import sys
from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import pytest

from scripts import team_score_telemetry as score
from scripts import project_team_score


SOURCE_SERVER = "observer-a"
MANIFEST_SHA = bytes.fromhex("11" * 32)


def row(*, half=1, tick="0.25", sequence=1, allies=0, axis=0,
        allies_team=1, axis_team=2, kind="baseline", match_type=0,
        match_id="official-a") -> score.TeamScoreObservation:
    return score.TeamScoreObservation(
        match_id=match_id, match_type=match_type, half=half,
        tick_seconds=Decimal(tick), event_sequence=sequence, observed_at=None,
        allies_score=allies, axis_score=axis,
        allies_team_id=allies_team, axis_team_id=axis_team,
        map_name="dod_anzio", source_server=SOURCE_SERVER,
        manifest_content_sha256=MANIFEST_SHA, observation_kind=kind,
    )


def complete_rows() -> list[score.TeamScoreObservation]:
    return [
        row(tick="10.25"),
        row(tick="120.50", sequence=2, allies=1, kind="change"),
        row(tick="120.50", sequence=3, allies=4, kind="change"),
        row(tick="1300.75", sequence=4, allies=4, kind="final"),
        row(half=2, tick="0.20", allies=0, axis=4,
            allies_team=2, axis_team=1, kind="baseline"),
        row(half=2, tick="0.20", sequence=2, allies=2, axis=4,
            allies_team=2, axis_team=1, kind="change"),
        row(half=2, tick="1250.10", sequence=3, allies=2, axis=4,
            allies_team=2, axis_team=1, kind="final"),
    ]


def official_event(**overrides):
    value = {
        "tick": 10.25, "match_id": "official-a", "map": "dod_anzio",
        "match_type": 0, "half": 1, "plugin_sent_at": 1_787_000_000_123,
        "event": "team_score", "allies_score": 0, "axis_score": 0,
        "allies_team_slot": 1, "axis_team_slot": 2, "event_sequence": 1,
        "source": score.OFFICIAL_SOURCE, "sample_kind": "baseline",
    }
    value.update(overrides)
    return value


def lifecycle_event(*, match_id="official-a", match_type=0, half=1,
                    allies_score=0, axis_score=0, map_name="dod_anzio"):
    return {
        "event": "ktp_match_end", "match_id": match_id, "map": map_name,
        "match_type": match_type, "half": half,
        "allies_score": allies_score, "axis_score": axis_score,
    }


def write_observer(root: Path, values, *, match_id="official-a", map_name="dod_anzio",
                   match_type=0, source_server=SOURCE_SERVER, ended_at="2026-01-01T00:06:00Z",
                   metadata_overrides=None, append_lifecycle=True) -> Path:
    directory = root / match_id
    directory.mkdir(parents=True, exist_ok=True)
    values = list(values)
    if append_lifecycle:
        official = [value for value in values if value.get("event") == "team_score"
                    and value.get("source") == score.OFFICIAL_SOURCE]
        terminal_half = max((value["half"] for value in official), default=1)
        terminal_type = next(
            (value["match_type"] for value in reversed(official)
             if value["half"] == terminal_half), match_type,
        )
        final = official[-1] if official else {}
        values.append(lifecycle_event(
            match_id=match_id, match_type=terminal_type, half=terminal_half,
            allies_score=final.get("allies_score", 0), axis_score=final.get("axis_score", 0),
            map_name=map_name,
        ))
    path = directory / "events.jsonl"
    path.write_text("".join(json.dumps(value, separators=(",", ":")) + "\n"
                            for value in values), encoding="utf-8")
    metadata = {
        "matchId": match_id, "map": map_name, "matchType": match_type,
        "half": 1, "startedAt": "2026-01-01T00:00:00Z", "endedAt": ended_at,
        "eventCount": len(values), "sourceServer": source_server,
    }
    metadata.update(metadata_overrides or {})
    (directory / "metadata.json").write_text(
        json.dumps(metadata, separators=(",", ":")), encoding="utf-8",
    )
    return path


def projection_context(rows, *, match_type=None, terminal_half=None,
                       match_id="official-a", map_name="dod_anzio"):
    rows = list(rows)
    return score.ProjectionContext(
        match_id=match_id, map_name=map_name,
        match_type=(rows[0].match_type if match_type is None and rows else match_type),
        source_server=SOURCE_SERVER,
        terminal_half=(max(row.half for row in rows) if terminal_half is None and rows
                       else terminal_half),
        event_count=len(rows) + 1, official_row_count=len(rows),
        retained_row_count=len({row.order_key for row in rows}),
        events_file_sha256=bytes.fromhex("22" * 32),
        metadata_file_sha256=bytes.fromhex("33" * 32),
        manifest_content_sha256=MANIFEST_SHA,
        observer_closed=True, settled=True, lifecycle_complete=True,
        database_context_valid=True,
    )


def project(rows, **kwargs):
    rows = list(rows)
    context = kwargs.pop("context", projection_context(rows))
    return score.project_official_score(rows, context=context, **kwargs)


def timeline(result):
    return result.dto["objectiveScoreTimeline"]


def test_two_halves_sort_after_out_of_order_arrival_and_restart_half_clock():
    result = project(list(reversed(complete_rows())))
    projected = timeline(result)
    assert projected["quality"] == {"status": "complete", "flags": []}
    assert [half["half"] for half in projected["halves"]] == [1, 2]
    assert [point["halfTimeSeconds"] for point in projected["halves"][0]["points"]] == [
        0, 110.25, 110.25, 1290.5,
    ]
    assert [point["halfTimeSeconds"] for point in projected["halves"][1]["points"]] == [
        0, 0, 1249.9,
    ]


def test_side_swap_carryover_maps_every_row_to_stable_neutral_teams():
    projected = timeline(project(complete_rows()))
    h1_final = projected["halves"][0]["points"][-1]
    h2_open = projected["halves"][1]["points"][0]
    assert (h1_final["team1Score"], h1_final["team2Score"]) == (4, 0)
    assert (h2_open["team1Score"], h2_open["team2Score"]) == (4, 0)
    assert projected["teams"] == [
        {"id": "team-1", "label": "Team 1"},
        {"id": "team-2", "label": "Team 2"},
    ]


def test_every_point_has_both_scores_and_same_tick_uses_sequence():
    points = timeline(project(complete_rows()))["halves"][0]["points"]
    assert all({"team1Score", "team2Score"} <= set(point) for point in points)
    assert [(point["team1Score"], point["observationKind"]) for point in points[1:3]] == [
        (1, "change"), (4, "change"),
    ]


def test_multi_point_capout_jump_is_retained_without_interpolation():
    points = timeline(project(complete_rows()))["halves"][0]["points"]
    assert [point["team1Score"] for point in points] == [0, 1, 4, 4]
    assert len(points) == 4


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda rows: [replace(r, observation_kind="change") if r.half == 1 and r.event_sequence == 1 else r for r in rows], "missing-half-start"),
        (lambda rows: [r for r in rows if not (r.half == 2 and r.observation_kind == "final")], "missing-half-final"),
        (lambda rows: [replace(r, allies_score=0) if r.half == 1 and r.event_sequence == 4 else r for r in rows], "score-regression"),
        (lambda rows: rows + [replace(rows[1], allies_score=99)], "conflicting-order-key"),
        (lambda rows: [replace(r, allies_team_id=1, axis_team_id=1) if r.half == 2 else r for r in rows], "side-mapping-unknown"),
    ],
)
def test_missing_boundaries_regression_conflict_and_unknown_mapping_fail_closed(mutate, expected):
    rows = mutate(complete_rows())
    projected = timeline(project(rows))
    assert projected["quality"]["status"] == "unavailable"
    assert expected in projected["quality"]["flags"]
    assert projected["halves"] == []


@pytest.mark.parametrize(
    ("malformed", "expected"),
    [
        (replace(row(), tick_seconds=Decimal("NaN")), "incomplete-stream"),
        (row(half=3), "incomplete-stream"),
        (replace(row(), allies_team_id=True), "side-mapping-unknown"),
    ],
)
def test_malformed_in_memory_order_and_mapping_fields_fail_closed(malformed, expected):
    projected = timeline(project([malformed]))
    assert projected["quality"]["status"] == "unavailable"
    assert expected in projected["quality"]["flags"]
    assert projected["halves"] == []


def test_sequence_gap_is_explicit_partial_but_sequence_tie_fails_closed():
    gap = [replace(r, event_sequence=r.event_sequence + 1)
           if r.half == 1 and r.event_sequence >= 2 else r
           for r in complete_rows()]
    gap_result = timeline(project(gap))
    assert gap_result["quality"]["status"] == "partial"
    assert gap_result["quality"]["flags"] == ["sequence-gap"]

    tied = complete_rows()
    tied[2] = replace(tied[2], tick_seconds=Decimal("121.0"), event_sequence=2)
    tied_result = timeline(project(tied))
    assert tied_result["quality"]["status"] == "unavailable"
    assert "sequence-tie" in tied_result["quality"]["flags"]


def test_missing_regular_half_fails_closed_against_terminal_context():
    rows = [
        row(half=2, kind="baseline"),
        row(half=2, tick="10", sequence=2, kind="final"),
    ]
    projected = timeline(project(
        rows, context=projection_context(rows, match_type=0, terminal_half=2),
    ))
    assert projected["quality"]["status"] == "unavailable"
    assert "incomplete-stream" in projected["quality"]["flags"]


def test_explicit_ot_rounds_keep_actual_identifiers_and_authoritative_mapping():
    rows = [
        row(allies=0, axis=0, kind="baseline"),
        row(tick="60", sequence=2, allies=5, axis=4, kind="final"),
        row(half=2, allies=4, axis=5, allies_team=2, axis_team=1, kind="baseline"),
        row(half=2, tick="60", sequence=2, allies=4, axis=5,
            allies_team=2, axis_team=1, kind="final"),
        row(half=101, match_type=4, allies=5, axis=4, kind="baseline"),
        row(half=101, match_type=4, tick="60", sequence=2, allies=6, axis=4, kind="final"),
        row(half=102, match_type=4, allies=4, axis=6,
            allies_team=2, axis_team=1, kind="baseline"),
        row(half=102, match_type=4, tick="60", sequence=2, allies=5, axis=6,
            allies_team=2, axis_team=1, kind="final"),
    ]
    projected = timeline(project(
        rows, context=projection_context(rows, match_type=0, terminal_half=102),
    ))
    assert projected["quality"]["status"] == "complete"
    assert [half["half"] for half in projected["halves"]] == [1, 2, 101, 102]
    assert projected["halves"][-1]["points"][-1]["team1Score"] == 6
    assert projected["halves"][-1]["points"][-1]["team2Score"] == 5


def test_swapped_match_end_only_adds_flag_and_never_overwrites_authoritative_final():
    result = project(
        complete_rows(), match_end={"allies_score": 4, "axis_score": 2}
    )
    projected = timeline(result)
    assert projected["quality"] == {
        "status": "partial", "flags": ["match-end-disagreement"],
    }
    final = projected["halves"][-1]["points"][-1]
    assert (final["team1Score"], final["team2Score"]) == (4, 2)


def test_consecutive_final_suffix_publishes_only_last_changed_final():
    rows = [
        row(tick="10"),
        row(tick="100", sequence=2, allies=1, kind="change"),
        row(tick="200", sequence=3, allies=1, kind="final"),
        row(tick="201", sequence=4, allies=2, kind="final"),
    ]
    result = project(rows, context=projection_context(rows, terminal_half=1))
    points = timeline(result)["halves"][0]["points"]
    assert [point["observationKind"] for point in points] == ["baseline", "change", "final"]
    assert points[-1]["team1Score"] == 2
    assert points[-1]["halfTimeSeconds"] == 191


def test_descending_consecutive_final_is_a_raw_regression_before_normalization():
    rows = [
        row(tick="10"),
        row(tick="100", sequence=2, allies=5, kind="change"),
        row(tick="200", sequence=3, allies=5, kind="final"),
        row(tick="201", sequence=4, allies=4, kind="final"),
    ]
    projected = timeline(project(
        rows, context=projection_context(rows, terminal_half=1),
    ))
    assert projected["quality"]["status"] == "unavailable"
    assert "score-regression" in projected["quality"]["flags"]
    assert projected["halves"] == []


@pytest.mark.parametrize("unexpected_half", [3, 100])
def test_unexpected_lifecycle_half_fails_closed(unexpected_half):
    rows = [
        row(kind="baseline"), row(tick="10", sequence=2, kind="final"),
        row(half=unexpected_half, kind="baseline"),
        row(half=unexpected_half, tick="10", sequence=2, kind="final"),
    ]
    projected = timeline(project(
        rows, context=projection_context(rows, match_type=0, terminal_half=unexpected_half),
    ))
    assert projected["quality"]["status"] == "unavailable"
    assert "incomplete-stream" in projected["quality"]["flags"]


def test_ot_half_gap_fails_closed():
    rows = [
        row(), row(tick="10", sequence=2, kind="final"),
        row(half=2), row(half=2, tick="10", sequence=2, kind="final"),
        row(half=102, match_type=4),
        row(half=102, match_type=4, tick="10", sequence=2, kind="final"),
    ]
    projected = timeline(project(
        rows, context=projection_context(rows, match_type=0, terminal_half=102),
    ))
    assert projected["quality"]["status"] == "unavailable"
    assert "incomplete-stream" in projected["quality"]["flags"]


@pytest.mark.parametrize(
    "field",
    ["observer_closed", "settled", "lifecycle_complete", "database_context_valid"],
)
def test_completion_requires_every_closed_settled_manifest_lifecycle_gate(field):
    rows = complete_rows()
    context = replace(projection_context(rows), **{field: False})
    projected = timeline(project(rows, context=context))
    assert projected["quality"]["status"] == "unavailable"
    assert projected["halves"] == []


def test_public_dto_has_exact_team_only_keys_and_no_internal_provenance():
    result = project(complete_rows())
    projected = timeline(result)
    assert set(projected) == {
        "source", "sourceVersion", "scoringScope", "carryOver",
        "teams", "halves", "quality",
    }
    assert set(projected["halves"][0]["points"][0]) == {
        "halfTimeSeconds", "team1Score", "team2Score", "observationKind",
    }
    assert score.privacy_violations(result.dto) == []
    serialized = result.canonical_json.decode().lower()
    for forbidden in ("official-a", "match_id", "server", "player", "steam",
                      "event_sequence", "observed_at", "raw_event"):
        assert forbidden not in serialized


def test_projection_canonical_json_and_digest_are_identical_on_rerun():
    first = project(complete_rows())
    second = project(list(complete_rows()))
    assert first.canonical_json == second.canonical_json
    assert first.sha256 == second.sha256
    assert first.release_metadata == second.release_metadata
    assert first.release_metadata["immutable"] is True
    assert first.release_metadata["releaseId"] == f"objective-score-v1-{first.sha256}"
    assert json.loads(first.canonical_json) == first.dto


def test_private_binding_requires_exact_analytics_match_and_digest_then_strips_it():
    result = project(complete_rows())
    digest = "ab" * 32
    bound = score.bind_projection_to_analytics(
        result, analytics_match_id="official-a", analytics_map_name="dod_anzio",
        analytics_facts_sha256=digest,
    )
    public = score.validate_private_projection_binding(
        bound, analytics_match_id="official-a", analytics_map_name="dod_anzio",
        analytics_facts_sha256=digest,
    )
    assert public == result.dto
    assert "official-a" not in json.dumps(public)
    assert digest not in json.dumps(public)
    with pytest.raises(ValueError, match="foreign analytics facts"):
        score.validate_private_projection_binding(
            bound, analytics_match_id="official-a", analytics_map_name="dod_anzio",
            analytics_facts_sha256="cd" * 32,
        )
    with pytest.raises(ValueError, match="foreign match"):
        score.bind_projection_to_analytics(
            result, analytics_match_id="other", analytics_map_name="dod_anzio",
            analytics_facts_sha256=digest,
        )


def test_public_projection_validator_rejects_forged_regression_and_carryover():
    regression = json.loads(project(complete_rows()).canonical_json)
    regression["objectiveScoreTimeline"]["halves"][0]["points"][2]["team1Score"] = 0
    with pytest.raises(ValueError, match="cannot regress"):
        score.validate_public_projection(regression)

    carryover = json.loads(project(complete_rows()).canonical_json)
    carryover["objectiveScoreTimeline"]["halves"][1]["points"][0]["team1Score"] = 3
    with pytest.raises(ValueError, match="does not carry over"):
        score.validate_public_projection(carryover)


def test_public_projection_validator_rejects_fatal_flag_as_partial():
    forged = json.loads(project(complete_rows()).canonical_json)
    forged["objectiveScoreTimeline"]["quality"] = {
        "status": "partial", "flags": ["score-regression"],
    }
    with pytest.raises(ValueError, match="fatal quality flag"):
        score.validate_public_projection(forged)


def test_denver_fixture_is_explicitly_unavailable_and_contains_no_inferred_points():
    path = Path(__file__).parents[1] / "fixtures" / "team_score" / "denver-objective-score-unavailable.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    projected = value["objectiveScoreTimeline"]
    assert projected["quality"]["status"] == "unavailable"
    assert projected["quality"]["flags"] == ["incomplete-stream"]
    assert projected["halves"] == []
    assert "capture" not in json.dumps(value).lower()
    assert "ktpr" not in json.dumps(value).lower()


def test_jsonl_parser_requires_exact_official_schema_and_classifies_retention(tmp_path):
    path = write_observer(tmp_path, [
        {"event": "player_score", "score": 2},
        {"event": "team_score", "allies_score": 0, "axis_score": 0},
        official_event(match_type=1),
    ], match_type=1)
    test_path = write_observer(tmp_path, [
        official_event(match_id="lane-TEST"),
    ], match_id="lane-TEST")
    parsed = score.read_event_files(
        [path, test_path], source_server_roots={SOURCE_SERVER: tmp_path},
    )
    assert parsed.input_lines == 6
    assert parsed.ignored_events == 3
    assert parsed.ignored_legacy_team_scores == 1
    assert [r.tick_seconds for r in parsed.observations] == [Decimal("10.25")] * 2
    assert [r.retention_class for r in parsed.observations] == [
        "ephemeral-14d", "ephemeral-14d",
    ]
    assert all(r.observed_at == "2026-08-17 20:53:20.123" for r in parsed.observations)


@pytest.mark.parametrize(
    "override",
    [
        {"allies_score": True},
        {"event_sequence": 1.0},
        {"half": 3},
        {"allies_team_slot": 1, "axis_team_slot": 1},
        {"unexpected": 1},
    ],
)
def test_jsonl_parser_rejects_claimed_official_schema_drift(tmp_path, override):
    path = write_observer(tmp_path, [official_event(**override)])
    with pytest.raises(score.JsonlValidationError):
        score.read_event_files(
            [path], source_server_roots={SOURCE_SERVER: path.parent.parent},
        )


def test_settlement_gate_blocks_active_or_fresh_metadata(tmp_path):
    active = write_observer(
        tmp_path / "active", [official_event()], ended_at=None,
    )
    with pytest.raises(score.JsonlValidationError, match="active source"):
        score.read_event_files(
            [active], source_server_roots={SOURCE_SERVER: active.parent.parent},
        )
    path = write_observer(
        tmp_path / "fresh", [official_event()], ended_at="2026-08-29T12:00:00Z",
    )
    with pytest.raises(score.JsonlValidationError, match="settlement window"):
        score.read_event_files(
            [path], settlement_seconds=30, now=1_788_004_810,
            source_server_roots={SOURCE_SERVER: path.parent.parent},
        )


@pytest.mark.parametrize(
    ("metadata_overrides", "allowed", "message"),
    [
        ({"eventCount": 99}, [SOURCE_SERVER], "eventCount"),
        ({"sourceServer": "untrusted-copy"}, [SOURCE_SERVER], "allowlisted"),
        ({"matchId": "foreign-match"}, [SOURCE_SERVER], "parent directory"),
        ({"map": "dod_caen"}, [SOURCE_SERVER], "does not match"),
    ],
)
def test_metadata_ownership_count_context_and_source_mismatch_fail_closed(
    tmp_path, metadata_overrides, allowed, message,
):
    path = write_observer(
        tmp_path, [official_event()], metadata_overrides=metadata_overrides,
    )
    with pytest.raises(score.JsonlValidationError, match=message):
        score.read_event_files(
            [path], source_server_roots={name: path.parent.parent for name in allowed},
        )


def test_adjacent_metadata_is_mandatory_and_copied_or_renamed_tree_is_rejected(tmp_path):
    missing = write_observer(tmp_path / "missing", [official_event()])
    missing.with_name("metadata.json").unlink()
    with pytest.raises(score.JsonlValidationError, match="metadata.json is required"):
        score.read_event_files(
            [missing], source_server_roots={SOURCE_SERVER: missing.parent.parent},
        )

    original = write_observer(tmp_path / "source", [official_event()])
    copied_dir = tmp_path / "copy" / "official-a"
    shutil.copytree(original.parent, copied_dir)
    with pytest.raises(score.JsonlValidationError, match="path is not owned"):
        score.read_event_files(
            [copied_dir / "events.jsonl"],
            source_server_roots={SOURCE_SERVER: original.parent.parent},
        )


@pytest.mark.parametrize("mutate_metadata", [False, True])
def test_stat_read_restat_rejects_event_or_metadata_append_race(tmp_path, mutate_metadata):
    path = write_observer(tmp_path, [official_event()])

    def mutate(events_path, metadata_path):
        target = metadata_path if mutate_metadata else events_path
        target.write_bytes(target.read_bytes() + b" ")

    with pytest.raises(score.JsonlValidationError, match="changed while being read"):
        score.read_event_files(
            [path], source_server_roots={SOURCE_SERVER: path.parent.parent},
            _after_read_hook=mutate,
        )


def test_arbitrary_match_type_progression_and_mixed_map_fail_closed(tmp_path):
    wrong_type = write_observer(
        tmp_path / "type", [official_event(match_type=3)], match_type=0,
    )
    with pytest.raises(score.JsonlValidationError, match="progression"):
        score.read_event_files(
            [wrong_type], source_server_roots={SOURCE_SERVER: wrong_type.parent.parent},
        )
    wrong_map = write_observer(
        tmp_path / "map", [official_event(map="dod_caen")], map_name="dod_anzio",
    )
    with pytest.raises(score.JsonlValidationError, match="map does not match"):
        score.read_event_files(
            [wrong_map], source_server_roots={SOURCE_SERVER: wrong_map.parent.parent},
        )


def test_import_sql_preserves_decimal_and_has_idempotent_conflict_choreography(tmp_path):
    original = official_event(tick=10.125)
    duplicate = dict(original)
    conflict = dict(original, allies_score=9)
    path = write_observer(tmp_path, [original, duplicate, conflict])
    parsed = score.read_event_files(
        [path], source_server_roots={SOURCE_SERVER: path.parent.parent},
    )
    sql = score.build_import_sql(parsed)
    assert "10.125" in sql
    assert "engine_tick" not in sql
    assert "ktp_team_score_ingest_conflicts" in sql
    assert "raw_event_sha256" in sql
    assert "input_count" in sql
    assert "ON DUPLICATE KEY UPDATE" not in sql


def test_projector_snapshot_uses_shared_lock_one_consistent_transaction():
    class CapturingMysql(score.MysqlCli):
        def __init__(self):
            super().__init__(database="test")
            self.sql = ""

        def execute(self, sql):
            self.sql = sql
            return "KTP_SCORE_LOCK\t1\nKTP_SCORE_AUDIT\t0\nKTP_SCORE_RELEASE\t1\n"

    mysql = CapturingMysql()
    snapshot = mysql.fetch_match("official-a")
    assert snapshot.rows == ()
    assert f"GET_LOCK('{score.LEDGER_LOCK}',30)" in mysql.sql
    assert "START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY" in mysql.sql
    assert mysql.sql.index("KTP_SCORE_MANIFEST") < mysql.sql.index("KTP_SCORE_ROW")
    assert mysql.sql.index("KTP_SCORE_ROW") < mysql.sql.index("KTP_SCORE_CONFLICT")
    assert mysql.sql.index("KTP_SCORE_CONFLICT") < mysql.sql.index("KTP_SCORE_AUDIT")
    assert mysql.sql.index("KTP_SCORE_AUDIT") < mysql.sql.index("KTP_SCORE_CONTEXT")
    assert mysql.sql.index("KTP_SCORE_CONTEXT") < mysql.sql.index("COMMIT")
    assert f"RELEASE_LOCK('{score.LEDGER_LOCK}')" in mysql.sql


def test_retention_classifier_matches_scheduled_policy():
    assert score.retention_class(1, "scrim") == "ephemeral-14d"
    assert score.retention_class(2, "12man") == "ephemeral-14d"
    assert score.retention_class(0, "live-TEST") == "ephemeral-14d"
    for match_type in (0, 3, 4, 5):
        assert score.retention_class(match_type, "official") == "retained"


def test_validate_only_cli_reports_counts_without_mysql(tmp_path):
    path = write_observer(tmp_path, [official_event()])
    root = Path(__file__).resolve().parents[2]
    proc = subprocess.run(
        [sys.executable, str(root / "scripts" / "import_team_score_events.py"),
         "--source-server-root", f"{SOURCE_SERVER}={path.parent.parent}",
         "--validate-only", str(path)],
        cwd=root, capture_output=True, text=True, check=False,
    )
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["officialRows"] == 1
    assert result["inserted"] == 0
    assert result["conflictKeys"] == 0


def test_projector_release_files_are_immutable_and_idempotent(tmp_path):
    path = tmp_path / "release.json"
    project_team_score._write_immutable(path, b"first")
    project_team_score._write_immutable(path, b"first")
    assert path.read_bytes() == b"first"
    with pytest.raises(ValueError, match="immutable release path"):
        project_team_score._write_immutable(path, b"correction")
    assert path.read_bytes() == b"first"
