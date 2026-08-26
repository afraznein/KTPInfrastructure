from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from scripts.prepare_lane_b_pages import (
    COMPONENT_FIELDS,
    EXPECTED_REPOSITORY,
    MANIFEST_FILES,
    PLAYER_NUMERIC_FIELDS,
    PublicationError,
    parse_run_id,
    prepare_publication,
    validate_environment_reviewers,
    validate_pages_settings,
    validate_preprod_ancestry,
    validate_publisher_event,
    validate_run_metadata,
    write_step_summary,
)


RUN_ID = 32866057356
TAG = "lane-b-preprod-series-v5-timeline-positive-20260825-1129"
SHA = "7ff4ef142df1e29c462427f99de29f4c30f9f009"
RUN_URL = f"https://github.com/{EXPECTED_REPOSITORY}/actions/runs/{RUN_ID}"
ARTIFACT_DIGEST = "sha256:" + "a" * 64
BUNDLE_COMMITS = {
    "infrastructure": SHA,
    "matchhandler": "5b3524ad150f7144250131eca4d0f4853bd797f1",
    "amxx": "825f768172544e5239bb21551ac884c6115661ac",
    "hlstatsx": "6506f25eb1dc9f1b84d3595b9aaaca3046a749db",
}
DEFAULT_SHA = "4" * 40


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_json(path: Path, value: object) -> None:
    _write(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_metadata() -> dict[str, object]:
    return {
        "schema_version": 1,
        "scope": "PUBLIC_SYNTHETIC_BOT_TEST_ONLY",
        "repository": EXPECTED_REPOSITORY,
        "source_run_id": RUN_ID,
        "source_run_url": RUN_URL,
        "source_tag": TAG,
        "infrastructure_sha": SHA,
        "run_attempt": 1,
        "workflow_id": 333974483,
        "workflow_name": "Lane B Stats E2E",
        "workflow_path": ".github/workflows/lane-b-stats-e2e.yml",
        "artifact_id": 9571031075,
        "artifact_name": f"lane-b-series-comparison-{RUN_ID}",
        "artifact_digest": ARTIFACT_DIGEST,
        "artifact_size_bytes": 277622,
    }


def _metadata() -> dict[str, object]:
    metadata = _run_metadata()
    metadata["preprod_ancestry"] = {
        "protected_ref": "refs/heads/preprod",
        "branch_protection": True,
        "source_sha": SHA,
        "preprod_sha": SHA,
        "compare_status": "identical",
        "preprod_commits_ahead": 0,
        "merge_base_sha": SHA,
        "verified_via": "GitHub branch+refs+commits+compare APIs",
    }
    metadata["publisher_event"] = validate_publisher_event(
        event_name="repository_dispatch",
        event_action="publish-lane-b-pages",
        event_ref="refs/heads/main",
        event_sha=DEFAULT_SHA,
        repository_payload=_environment_inputs()[2],
        default_ref=_environment_inputs()[3],
        default_commit=_environment_inputs()[4],
    )
    metadata["publication_approval"] = validate_environment_reviewers(*_environment_inputs())
    return metadata


def _environment_inputs() -> tuple[dict[str, object], ...]:
    environment = {
        "name": "github-pages",
        "deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True},
        "protection_rules": [{
            "id": 123,
            "type": "required_reviewers",
            "prevent_self_review": True,
            "reviewers": [{"type": "User", "reviewer": {"id": 42}}],
        }],
    }
    policies = {
        "total_count": 1,
        "branch_policies": [{"id": 456, "name": "main", "type": "branch"}],
    }
    repository = {"full_name": EXPECTED_REPOSITORY, "default_branch": "main"}
    default_ref = {"ref": "refs/heads/main", "object": {"type": "commit", "sha": DEFAULT_SHA}}
    default_commit = {"sha": DEFAULT_SHA}
    return environment, policies, repository, default_ref, default_commit


def _refresh_manifest_file(report_dir: Path, relative: str) -> None:
    manifest_path = report_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        if entry["path"] == relative:
            target = report_dir / relative
            entry["bytes"] = target.stat().st_size
            entry["sha256"] = _hash(target)
            break
    else:
        raise AssertionError(f"manifest has no {relative}")
    if relative == "report.json":
        manifest["report_file_sha256"] = _hash(report_dir / relative)
    _write_json(manifest_path, manifest)


def _player(number: int, *, name: str | None = None) -> dict[str, object]:
    row: dict[str, object] = {field: 1.0 for field in PLAYER_NUMERIC_FIELDS}
    for field in ("kills", "deaths", "assists", "team_kills", "suicides"):
        row[field] = 1
    row.update({
        "player_id": 100 + number,
        "player_name_at_match": name or f"Source Player {number}",
        "team_name": "Team 1" if number <= 6 else "Team 2",
        "rank": number,
    })
    return row


def _timeline(match_id: str) -> dict[str, object]:
    team_row = {
        "points_gained": 6.0,
        "cumulative_points": 6.0,
        "deferred_position_points": 0.0,
        "components": {field: 0.5 for field in COMPONENT_FIELDS},
    }
    return {
        "schema_version": 1,
        "match_id": match_id,
        "bin_seconds": 15.0,
        "teams": [1, 2],
        "momentum_sign": {"positive_team": 1, "negative_team": 2},
        "privacy": {
            "scope": "team_only",
            "individual_timing": "not_exported",
            "spatial_detail": "not_exported",
        },
        "components": sorted(COMPONENT_FIELDS),
        "halves": [{
            "half": 1,
            "bins": [{
                "start_time": 0.0,
                "end_time": 15.0,
                "teams": {"1": team_row, "2": dict(team_row)},
                "point_gain_differential": 0.0,
                "momentum": 0.0,
                "momentum_change": 0.0,
            }],
        }],
        "annotations": [],
        "conservation": {},
    }


def _build_report(report_dir: Path, match_id: str) -> None:
    quality = {"match_classification": {"status": "PASS", "detail": "source detail ignored"}}
    report = {
        "schema_version": 1,
        "status": "experimental_shadow",
        "publication_state": "DRAFT",
        "profile": "accumulation_v6_schema22_2s",
        "profile_status": "experimental_shadow",
        "match": {
            "match_id": match_id,
            "map_name": "dod_anzio",
            "duration_seconds": 15.0,
            "is_test_match": True,
            "source_mode": "lane_b_ephemeral_mysql",
            "scoring_iteration": "v6_schema22_2s",
        },
        "privacy": {"individual_positions": "private_not_embedded"},
        "telemetry_lifecycles": {
            "privacy": "aggregate_only_no_entity_or_position_detail",
            "objective_attempts": {
                "status": "available", "events": 4, "attempts": 2,
                "starts": 2, "completes": 1, "stops": 1,
                "orphan_terminals": 0, "open_attempts": 0,
                "stop_reasons": {"capture_stopped": 0, "context_reset": 1},
            },
            "grenade_entities": {
                "status": "available", "semantics": "entity_tracked_removed_only",
                "events": 7, "entities": 4, "tracked": 4, "removed": 3,
                "complete_lifecycles": 3, "incomplete_tracked": 1,
                "left_censored_removed": 0, "allowed_weapon_ids_only": True,
            },
        },
        "players": [_player(number) for number in range(1, 13)],
        "component_totals": {field: 1.0 for field in COMPONENT_FIELDS},
        "match_total_points": 12.0,
        "quality_gates": quality,
    }
    files: dict[str, str] = {
        "ai-request.json": "{}\n",
        "comparison.json": "{}\n",
        "comparison.md": "# Private comparison source\n",
        "facts.normalized.json": "{}\n",
        "momentum.svg": '<svg xmlns="http://www.w3.org/2000/svg"></svg>\n',
        "points-timeline.json": json.dumps(_timeline(match_id)) + "\n",
        "points-timeline.svg": '<svg xmlns="http://www.w3.org/2000/svg"></svg>\n',
        "report.html": '<!doctype html><html><body>untrusted source</body></html>\n',
        "report.json": json.dumps(report) + "\n",
        "report.md": "# Untrusted source markdown\n",
    }
    for name, content in files.items():
        _write(report_dir / name, content)
    entries = [
        {"path": name, "bytes": (report_dir / name).stat().st_size, "sha256": _hash(report_dir / name)}
        for name in sorted(MANIFEST_FILES)
    ]
    _write_json(report_dir / "manifest.json", {
        "schema_version": 1,
        "match_id": match_id,
        "facts_sha256": _hash(report_dir / "facts.normalized.json"),
        "report_file_sha256": _hash(report_dir / "report.json"),
        "publication_checkpoint": "HUMAN_REVIEW_REQUIRED",
        "publication_state": "DRAFT",
        "files": entries,
        "invariants": {
            "ai_can_publish": False,
            "raw_individual_positions_exported": False,
            "points_timeline_team_only": True,
        },
    })
    _write_json(report_dir / "report-verification.json", {
        "schema_version": 1,
        "status": "PASS",
        "checks": {
            "manifest_hashes": "PASS",
            "public_privacy": "PASS",
            "points_timeline_privacy": "PASS",
            "required_files": "PASS",
        },
        "errors": [],
    })


def _provenance() -> str:
    rows = "\n".join(
        f"| {component} | `{repository}` | `preprod` | `{BUNDLE_COMMITS[component]}` |"
        for component, repository in (
            ("infrastructure", "afraznein/KTPInfrastructure"),
            ("matchhandler", "afraznein/KTPMatchHandler"),
            ("amxx", "afraznein/KTPAMXX"),
            ("hlstatsx", "afraznein/KTPHLStatsX"),
        )
    )
    return (
        "## Exact bundle provenance\n\n"
        "| Component | Repository | Requested ref | Resolved commit |\n"
        "|---|---|---|---|\n"
        f"{rows}\n\nWorkflow context:\n"
        f"- workflow_ref: `afraznein/KTPInfrastructure/.github/workflows/lane-b-stats-e2e.yml@refs/tags/{TAG}`\n"
        f"- event_sha: `{SHA}`\n"
        f"- run_url: `{RUN_URL}`\n"
    )


def _build_series(root: Path) -> Path:
    runs = []
    _write(root / "index.html", "<html><body>source index is ignored</body></html>\n")
    _write(root / "SERIES_COMPARISON.md", "# Untrusted source comparison\n")
    for number in range(1, 6):
        match_id = f"170000000{number}-TEST"
        runs.append({
            "run": number,
            "match_id": match_id,
            "map_name": "dod_anzio",
            "verification": "PASS",
            "players": 12,
            "duration_seconds": 15.0,
            "events": {
                "assists": 0,
                "cap_break_credits": 0,
                "capture_credits": 0,
                "capture_events": 0,
                "damage_rows": 0,
                "enemy_frags": 0,
                "position_samples": 0,
            },
            "match_total_points": 12.0,
            "rating_distribution": {"minimum": 1, "q1": 2, "median": 3, "q3": 4, "maximum": 5},
            "quality_gates": {"match_classification": "PASS"},
        })
        run_root = root / f"run-{number}"
        _write(run_root / "bundle-provenance.md", _provenance())
        _write(
            run_root / "lane-b-summary.md",
            "# Lane B synthetic match report\n\n"
            "| Result | Map | Match ID | Half | Play seconds | Players | Bots |\n"
            "|---|---|---|---:|---:|---:|---:|\n"
            f"| PASS | dod_anzio | {match_id} | 1 | 360 | 12 | 12 |\n",
        )
        _build_report(run_root / "match-report", match_id)
    _write_json(root / "series-comparison.json", {
        "schema_version": 1,
        "run_count": 5,
        "all_reports_pass": True,
        "no_blocking_quality_gates": True,
        "runs": runs,
    })
    return root


def _prepare(tmp_path: Path, source: Path | None = None) -> tuple[Path, dict[str, object]]:
    source = source or _build_series(tmp_path / "source")
    output = tmp_path / "site"
    publication = prepare_publication(
        source_root=source,
        output_root=output,
        metadata=_metadata(),
        published_at="2026-08-25T20:00:00+00:00",
    )
    return output, publication


def test_valid_series_regenerates_only_minimal_aliased_public_files(tmp_path: Path) -> None:
    output, publication = _prepare(tmp_path)
    actual = {path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file()}
    assert actual == set(publication["deployed_paths"])
    assert len(actual) == 18
    assert ".nojekyll" not in actual
    assert not any(path.endswith((".svg", ".md")) for path in actual)
    assert publication["source"]["bundle_commits"] == BUNDLE_COMMITS
    combined = "\n".join(path.read_text(encoding="utf-8") for path in output.rglob("*") if path.is_file())
    assert "Source Player" not in combined
    assert "player_id" not in combined
    assert "http://" not in combined and "https://" not in combined
    index_html = (output / "index.html").read_text(encoding="utf-8")
    metadata = json.loads((output / "publication-metadata.json").read_text(encoding="utf-8"))
    assert metadata["published_at"] == "2026-08-25T20:00:00+00:00"
    assert metadata["source"]["artifact_id"] == 9571031075
    assert metadata["source"]["artifact_digest"] == ARTIFACT_DIGEST
    assert metadata["source"]["preprod_ancestry"]["branch_protection"] is True
    assert metadata["source"]["publisher_event"]["event_name"] == "repository_dispatch"
    assert metadata["source"]["publisher_event"]["publisher_sha"] == DEFAULT_SHA
    assert metadata["source"]["publication_approval"]["deployment_policy_name"] == "main"
    assert metadata["validation"] == {
        "hashed_non_metadata_file_count": 17,
        "identity_contract": "PASS",
        "link_validation": "PASS",
        "privacy_scan": "PASS",
        "public_file_count": 18,
        "result": "PASS",
    }
    assert len(metadata["payload_manifest_sha256"]) == 64
    for number in range(1, 6):
        assert f'href="run-{number}/index.html"' in index_html
        assert (output / f"run-{number}/index.html").is_file()
        report = json.loads((output / f"run-{number}/report.json").read_text())
        assert [row["alias"] for row in sorted(report["players"], key=lambda row: row["alias"])] == [
            f"Bot {index:02d}" for index in range(1, 13)
        ]
        assert report["telemetry_lifecycles"] == {
            "privacy": "aggregate_only_no_entity_or_position_detail",
            "objective_attempts": {
                "events": 4, "attempts": 2, "starts": 2, "completes": 1,
                "stops": 1, "orphan_terminals": 0, "open_attempts": 0,
                "stop_reasons": {"capture_stopped": 0, "context_reset": 1},
            },
            "grenade_entities": {
                "semantics": "entity_tracked_removed_only", "events": 7,
                "entities": 4, "tracked": 4, "removed": 3,
                "complete_lifecycles": 3, "incomplete_tracked": 1,
                "left_censored_removed": 0,
            },
        }
        assert "entity-lifecycle observation" in (
            output / f"run-{number}/index.html"
        ).read_text()


def test_telemetry_lifecycle_detail_and_forbidden_weapons_are_rejected(tmp_path: Path) -> None:
    source = _build_series(tmp_path / "source")
    report_dir = source / "run-1/match-report"
    report_path = report_dir / "report.json"
    report = json.loads(report_path.read_text())
    report["telemetry_lifecycles"]["grenade_entities"]["pos_x"] = 123
    _write_json(report_path, report)
    _refresh_manifest_file(report_dir, "report.json")
    with pytest.raises(PublicationError, match="grenade lifecycle aggregate contract"):
        _prepare(tmp_path / "detail", source)

    source = _build_series(tmp_path / "weapon-source")
    report_dir = source / "run-1/match-report"
    report_path = report_dir / "report.json"
    report = json.loads(report_path.read_text())
    report["telemetry_lifecycles"]["grenade_entities"]["allowed_weapon_ids_only"] = False
    _write_json(report_path, report)
    _refresh_manifest_file(report_dir, "report.json")
    with pytest.raises(PublicationError, match="rocket, mortar, or unknown"):
        _prepare(tmp_path / "weapon", source)


@pytest.mark.parametrize(
    ("ledger", "field", "value"),
    (
        ("objective_attempts", "events", 5),
        ("objective_attempts", "attempts", 3),
        ("objective_attempts", "starts", 1),
        ("objective_attempts", "open_attempts", 1),
        ("grenade_entities", "events", 8),
        ("grenade_entities", "entities", 5),
        ("grenade_entities", "tracked", 3),
        ("grenade_entities", "removed", 2),
        ("grenade_entities", "complete_lifecycles", 2),
    ),
)
def test_mutated_lifecycle_aggregates_are_rejected(
    tmp_path: Path, ledger: str, field: str, value: int,
) -> None:
    source = _build_series(tmp_path / f"source-{ledger}-{field}")
    report_dir = source / "run-1/match-report"
    report_path = report_dir / "report.json"
    report = json.loads(report_path.read_text())
    report["telemetry_lifecycles"][ledger][field] = value
    _write_json(report_path, report)
    _refresh_manifest_file(report_dir, "report.json")
    with pytest.raises(PublicationError, match="lifecycle aggregates are inconsistent"):
        _prepare(tmp_path / f"published-{ledger}-{field}", source)


def test_timeline_allows_only_one_aligned_deferred_reconciliation_bin(tmp_path: Path) -> None:
    source = _build_series(tmp_path / "source")
    series_path = source / "series-comparison.json"
    series = json.loads(series_path.read_text())
    series["runs"][1]["duration_seconds"] = 16.0
    _write_json(series_path, series)
    report_dir = source / "run-2/match-report"
    report_path = report_dir / "report.json"
    report = json.loads(report_path.read_text())
    report["match"]["duration_seconds"] = 16.0
    _write_json(report_path, report)
    _refresh_manifest_file(report_dir, "report.json")
    timeline_path = report_dir / "points-timeline.json"
    timeline = json.loads(timeline_path.read_text())
    template = timeline["halves"][0]["bins"][0]
    for start in (15.0, 30.0):
        row = json.loads(json.dumps(template))
        row["start_time"] = start
        row["end_time"] = start + 15.0
        for team in ("1", "2"):
            row["teams"][team]["cumulative_points"] = 6.0 + start
        timeline["halves"][0]["bins"].append(row)
    _write_json(timeline_path, timeline)
    _refresh_manifest_file(report_dir, "points-timeline.json")
    _prepare(tmp_path, source)

    row = json.loads(json.dumps(template))
    row["start_time"] = 45.0
    row["end_time"] = 60.0
    for team in ("1", "2"):
        row["teams"][team]["cumulative_points"] = 60.0
    timeline["halves"][0]["bins"].append(row)
    _write_json(timeline_path, timeline)
    _refresh_manifest_file(report_dir, "points-timeline.json")
    with pytest.raises(PublicationError, match="one deferred final bin"):
        _prepare(tmp_path / "too-long", source)


def test_malicious_source_html_and_svg_are_ignored_not_copied(tmp_path: Path) -> None:
    source = _build_series(tmp_path / "source")
    report_dir = source / "run-1/match-report"
    _write(
        report_dir / "report.html",
        '<meta http-equiv="refresh" content="0;url=https://evil.invalid"><script>alert(1)</script>'
        '<style>@import "https://evil.invalid";x{background:url(https://evil.invalid)}</style>'
        '<img srcset="https://evil.invalid 1x"><form action="https://evil.invalid"></form>',
    )
    _write(
        report_dir / "momentum.svg",
        '<svg><script>alert(1)</script><use href="https://evil.invalid/x"></use><foreignObject/></svg>',
    )
    _refresh_manifest_file(report_dir, "report.html")
    _refresh_manifest_file(report_dir, "momentum.svg")
    output, publication = _prepare(tmp_path, source)
    summary = tmp_path / "adversarial-step-summary.md"
    write_step_summary(publication, summary)
    combined = "\n".join(path.read_text(encoding="utf-8") for path in output.rglob("*") if path.is_file())
    combined += "\n" + summary.read_text(encoding="utf-8")
    for forbidden in ("evil.invalid", "<script", "<form", "srcset=", "@import", "<svg", "foreignObject"):
        assert forbidden not in combined


def test_arbitrary_source_name_and_email_are_replaced_with_alias(tmp_path: Path) -> None:
    source = _build_series(tmp_path / "source")
    report_dir = source / "run-1/match-report"
    report_path = report_dir / "report.json"
    report = json.loads(report_path.read_text())
    report["players"][0]["player_name_at_match"] = "Alice <alice@example.com> ghp_" + "A" * 36
    _write_json(report_path, report)
    _refresh_manifest_file(report_dir, "report.json")
    output, _ = _prepare(tmp_path, source)
    combined = "\n".join(path.read_text(encoding="utf-8") for path in output.rglob("*") if path.is_file())
    assert "Alice" not in combined and "example.com" not in combined and "ghp_" not in combined
    assert "Bot 01" in combined


def test_short_or_common_source_names_do_not_false_fail_identity_proof(tmp_path: Path) -> None:
    source = _build_series(tmp_path / "source")
    report_dir = source / "run-1/match-report"
    report_path = report_dir / "report.json"
    report = json.loads(report_path.read_text())
    for player, name in zip(report["players"], ("A", "Bot", "Team", "PASS")):
        player["player_name_at_match"] = name
    _write_json(report_path, report)
    _refresh_manifest_file(report_dir, "report.json")
    output, _ = _prepare(tmp_path, source)
    public_report = json.loads((output / "run-1/report.json").read_text())
    assert {row["alias"] for row in public_report["players"]} == {
        f"Bot {index:02d}" for index in range(1, 13)
    }
    assert all("player_name_at_match" not in row and "player_id" not in row for row in public_report["players"])


def test_sanitized_step_summary_contains_only_verified_public_provenance(tmp_path: Path) -> None:
    output, publication = _prepare(tmp_path)
    summary = tmp_path / "step-summary.md"
    _write(summary, "Existing summary entry\n")
    write_step_summary(publication, summary)
    text = summary.read_text(encoding="utf-8")
    assert text.startswith("Existing summary entry\n")
    for expected in (
        RUN_URL,
        TAG,
        SHA,
        "9571031075",
        ARTIFACT_DIGEST,
        "repository_dispatch",
        "publish-lane-b-pages",
        DEFAULT_SHA,
        "self-review prevention: enabled and API-verified",
        publication["payload_manifest_sha256"],
        "Output files: `18`",
        "Validation result: **PASS**",
        "Approve the protected `github-pages` environment",
    ):
        assert expected in text
    for sha in BUNDLE_COMMITS.values():
        assert sha in text
    for row in publication["runs"]:
        assert row["match_id"] in text
    assert "Source Player" not in text and "player_id" not in text

    tampered = json.loads(json.dumps(publication))
    tampered["payload_manifest_sha256"] = "0" * 64
    with pytest.raises(PublicationError, match="manifest hash disagrees"):
        write_step_summary(tampered, tmp_path / "tampered-summary.md")

    wrong_publisher = json.loads(json.dumps(publication))
    wrong_publisher["source"]["publisher_event"]["publisher_ref"] = "refs/heads/feature/unsafe"
    with pytest.raises(PublicationError, match="verified default-branch publisher"):
        write_step_summary(wrong_publisher, tmp_path / "wrong-publisher-summary.md")


@pytest.mark.parametrize(("players", "bots"), [(12, 11), (11, 11), (13, 13)])
def test_mixed_or_nonstandard_summary_roster_is_rejected(tmp_path: Path, players: int, bots: int) -> None:
    source = _build_series(tmp_path / "source")
    summary = source / "run-2/lane-b-summary.md"
    _write(
        summary,
        "| Result | Map | Match ID | Half | Play seconds | Players | Bots |\n"
        f"| PASS | dod_anzio | 1700000002-TEST | 1 | 360 | {players} | {bots} |\n",
    )
    with pytest.raises(PublicationError, match="exactly 12 bots"):
        _prepare(tmp_path, source)


def test_summary_and_report_roster_disagreement_is_rejected(tmp_path: Path) -> None:
    source = _build_series(tmp_path / "source")
    report_dir = source / "run-3/match-report"
    report_path = report_dir / "report.json"
    report = json.loads(report_path.read_text())
    report["players"].pop()
    _write_json(report_path, report)
    _refresh_manifest_file(report_dir, "report.json")
    with pytest.raises(PublicationError, match="exactly 12 bots"):
        _prepare(tmp_path, source)


def test_summary_map_and_play_window_must_match_lane_contract(tmp_path: Path) -> None:
    source = _build_series(tmp_path / "source")
    summary = source / "run-2/lane-b-summary.md"
    _write(summary, summary.read_text().replace("dod_anzio", "dod_flash"))
    with pytest.raises(PublicationError, match="summary map disagrees"):
        _prepare(tmp_path / "map", source)

    source = _build_series(tmp_path / "duration-source")
    summary = source / "run-2/lane-b-summary.md"
    _write(summary, summary.read_text().replace("| 1 | 360 | 12 | 12 |", "| 1 | 361 | 12 | 12 |"))
    with pytest.raises(PublicationError, match="play window changed"):
        _prepare(tmp_path / "duration", source)


def test_production_or_real_player_report_is_rejected(tmp_path: Path) -> None:
    source = _build_series(tmp_path / "source")
    report_dir = source / "run-4/match-report"
    report_path = report_dir / "report.json"
    report = json.loads(report_path.read_text())
    report["match"]["is_test_match"] = False
    report["match"]["source_mode"] = "production_mysql"
    _write_json(report_path, report)
    _refresh_manifest_file(report_dir, "report.json")
    with pytest.raises(PublicationError, match="production/real-player"):
        _prepare(tmp_path, source)


def test_four_repository_provenance_must_be_exact_and_identical(tmp_path: Path) -> None:
    source = _build_series(tmp_path / "source")
    provenance = source / "run-5/bundle-provenance.md"
    _write(provenance, provenance.read_text().replace(BUNDLE_COMMITS["amxx"], "1" * 40))
    with pytest.raises(PublicationError, match="differs across series runs"):
        _prepare(tmp_path, source)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("run_count", 4, "exactly five"),
        ("all_reports_pass", False, "not every report"),
        ("no_blocking_quality_gates", False, "blocking quality"),
    ],
)
def test_failed_or_incomplete_series_is_rejected(
    tmp_path: Path, field: str, value: object, message: str
) -> None:
    source = _build_series(tmp_path / "source")
    comparison_path = source / "series-comparison.json"
    comparison = json.loads(comparison_path.read_text())
    comparison[field] = value
    _write_json(comparison_path, comparison)
    with pytest.raises(PublicationError, match=message):
        _prepare(tmp_path, source)


def test_missing_extra_and_manifest_escape_are_rejected(tmp_path: Path) -> None:
    source = _build_series(tmp_path / "missing")
    (source / "run-3/match-report/report.html").unlink()
    with pytest.raises(PublicationError, match="missing required files"):
        _prepare(tmp_path / "a", source)

    source = _build_series(tmp_path / "extra")
    _write(source / "run-1/secret.log", "not public\n")
    with pytest.raises(PublicationError, match="unapproved files"):
        _prepare(tmp_path / "b", source)

    source = _build_series(tmp_path / "escape")
    manifest_path = source / "run-1/match-report/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"][0]["path"] = "../outside.json"
    _write_json(manifest_path, manifest)
    with pytest.raises(PublicationError, match="path escapes"):
        _prepare(tmp_path / "c", source)


def test_symlink_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _build_series(tmp_path / "source")
    target = source / "run-4/match-report/report.md"
    outside = tmp_path / "outside.md"
    _write(outside, "outside\n")
    target.unlink()
    try:
        os.symlink(outside, target)
    except OSError:
        _write(target, "placeholder\n")
        original_is_symlink = Path.is_symlink
        monkeypatch.setattr(Path, "is_symlink", lambda self: self == target or original_is_symlink(self))
    with pytest.raises(PublicationError, match="symlink"):
        _prepare(tmp_path, source)


def test_run_api_metadata_is_bound_to_digest_and_id() -> None:
    run = {
        "id": RUN_ID,
        "repository": {"full_name": EXPECTED_REPOSITORY},
        "head_repository": {"full_name": EXPECTED_REPOSITORY},
        "name": "Lane B Stats E2E",
        "path": ".github/workflows/lane-b-stats-e2e.yml",
        "workflow_id": 333974483,
        "event": "push",
        "status": "completed",
        "conclusion": "success",
        "head_branch": TAG,
        "head_sha": SHA,
        "html_url": RUN_URL,
        "run_attempt": 1,
    }
    workflow = {"id": 333974483, "name": "Lane B Stats E2E", "path": ".github/workflows/lane-b-stats-e2e.yml"}
    artifacts = {"artifacts": [{
        "id": 9571031075,
        "name": f"lane-b-series-comparison-{RUN_ID}",
        "expired": False,
        "digest": ARTIFACT_DIGEST,
        "size_in_bytes": 277622,
    }]}
    assert validate_run_metadata(
        run, workflow, artifacts, repository=EXPECTED_REPOSITORY, run_id=RUN_ID
    ) == _run_metadata()
    run["head_branch"] = TAG + "<script>"
    with pytest.raises(PublicationError, match="canonical Lane B series tag"):
        validate_run_metadata(run, workflow, artifacts, repository=EXPECTED_REPOSITORY, run_id=RUN_ID)
    run["head_branch"] = TAG
    artifacts["artifacts"][0]["digest"] = ""
    with pytest.raises(PublicationError, match="digest"):
        validate_run_metadata(run, workflow, artifacts, repository=EXPECTED_REPOSITORY, run_id=RUN_ID)


def test_unmerged_matching_tag_commit_fails_preprod_ancestry() -> None:
    source_commit = {"sha": SHA}
    preprod_sha = "2" * 40
    preprod_branch = {"name": "preprod", "protected": True, "commit": {"sha": preprod_sha}}
    preprod_ref = {"object": {"sha": preprod_sha}}
    preprod_commit = {"sha": preprod_sha}
    valid = {
        "status": "ahead",
        "base_commit": {"sha": SHA},
        "merge_base_commit": {"sha": SHA},
        "behind_by": 0,
        "ahead_by": 3,
    }
    evidence = validate_preprod_ancestry(
        source_sha=SHA,
        preprod_branch=preprod_branch,
        preprod_ref=preprod_ref,
        source_commit=source_commit,
        preprod_commit=preprod_commit,
        comparison=valid,
    )
    assert evidence["preprod_sha"] == preprod_sha
    with pytest.raises(PublicationError, match="not protected"):
        validate_preprod_ancestry(
            source_sha=SHA,
            preprod_branch={**preprod_branch, "protected": False},
            preprod_ref=preprod_ref,
            source_commit=source_commit,
            preprod_commit=preprod_commit,
            comparison=valid,
        )
    invalid = dict(valid, status="diverged", merge_base_commit={"sha": "3" * 40})
    with pytest.raises(PublicationError, match="ancestor"):
        validate_preprod_ancestry(
            source_sha=SHA,
            preprod_branch=preprod_branch,
            preprod_ref=preprod_ref,
            source_commit=source_commit,
            preprod_commit=preprod_commit,
            comparison=invalid,
        )


def test_publisher_event_must_be_exact_and_at_live_default_branch_tip() -> None:
    _, _, repository, default_ref, default_commit = _environment_inputs()
    common = {
        "repository_payload": repository,
        "default_ref": default_ref,
        "default_commit": default_commit,
    }
    repository_dispatch = validate_publisher_event(
        event_name="repository_dispatch",
        event_action="publish-lane-b-pages",
        event_ref="refs/heads/main",
        event_sha=DEFAULT_SHA,
        **common,
    )
    assert repository_dispatch["publisher_sha"] == DEFAULT_SHA
    workflow_run = validate_publisher_event(
        event_name="workflow_run",
        event_action="completed",
        event_ref="refs/heads/main",
        event_sha=DEFAULT_SHA,
        **common,
    )
    assert workflow_run["event_action"] == "completed"


@pytest.mark.parametrize(
    ("event_name", "event_action", "event_ref", "event_sha", "message"),
    [
        ("workflow_dispatch", "", "refs/heads/main", DEFAULT_SHA, "event type"),
        ("repository_dispatch", "other", "refs/heads/main", DEFAULT_SHA, "event action"),
        ("repository_dispatch", "publish-lane-b-pages", "refs/tags/main", DEFAULT_SHA, "default branch ref"),
        (
            "repository_dispatch",
            "publish-lane-b-pages",
            "refs/heads/feature/public-pages",
            DEFAULT_SHA,
            "default branch ref",
        ),
        ("repository_dispatch", "publish-lane-b-pages", "refs/heads/main", "5" * 40, "live default-branch tip"),
    ],
)
def test_non_default_or_wrong_publisher_event_fails_closed(
    event_name: str, event_action: str, event_ref: str, event_sha: str, message: str
) -> None:
    _, _, repository, default_ref, default_commit = _environment_inputs()
    with pytest.raises(PublicationError, match=message):
        validate_publisher_event(
            event_name=event_name,
            event_action=event_action,
            event_ref=event_ref,
            event_sha=event_sha,
            repository_payload=repository,
            default_ref=default_ref,
            default_commit=default_commit,
        )


def test_required_pages_reviewer_and_exact_default_branch_policy_are_mandatory() -> None:
    inputs = _environment_inputs()
    evidence = validate_environment_reviewers(*inputs)
    assert evidence["required_reviewer_count"] == 1
    assert evidence["prevent_self_review"] is True
    assert evidence["default_branch"] == "main"
    assert evidence["default_branch_sha"] == DEFAULT_SHA
    assert evidence["deployment_policy_count"] == 1
    assert evidence["deployment_policy_name"] == "main"
    assert evidence["deployment_policy_type"] == "branch"

    environment, policies, repository, default_ref, default_commit = inputs
    no_reviewers = {**environment, "protection_rules": []}
    with pytest.raises(PublicationError, match="required-reviewers"):
        validate_environment_reviewers(no_reviewers, policies, repository, default_ref, default_commit)

    self_review = json.loads(json.dumps(environment))
    self_review["protection_rules"][0]["prevent_self_review"] = False
    with pytest.raises(PublicationError, match="prevent self-review"):
        validate_environment_reviewers(self_review, policies, repository, default_ref, default_commit)

    for absent_or_null in (None, "absent"):
        no_positive_evidence = json.loads(json.dumps(environment))
        if absent_or_null == "absent":
            del no_positive_evidence["protection_rules"][0]["prevent_self_review"]
        else:
            no_positive_evidence["protection_rules"][0]["prevent_self_review"] = None
        with pytest.raises(PublicationError, match="prevent self-review"):
            validate_environment_reviewers(
                no_positive_evidence, policies, repository, default_ref, default_commit
            )


@pytest.mark.parametrize(
    ("environment_update", "policies_update", "message"),
    [
        (
            {"deployment_branch_policy": {"protected_branches": True, "custom_branch_policies": False}},
            {},
            "protected-branches",
        ),
        (
            {"deployment_branch_policy": None},
            {},
            "deployment branch policy is missing",
        ),
        ({}, {"total_count": 0, "branch_policies": []}, "exactly one"),
        (
            {},
            {
                "total_count": 2,
                "branch_policies": [
                    {"id": 456, "name": "main", "type": "branch"},
                    {"id": 457, "name": "release/*", "type": "branch"},
                ],
            },
            "exactly one",
        ),
        (
            {},
            {"total_count": 1, "branch_policies": [{"id": 456, "name": "*", "type": "branch"}]},
            "exactly equal",
        ),
        (
            {},
            {"total_count": 1, "branch_policies": [{"id": 456, "name": "main", "type": "tag"}]},
            "target a branch",
        ),
    ],
)
def test_broad_missing_wildcard_extra_or_tag_pages_policies_fail_closed(
    environment_update: dict[str, object], policies_update: dict[str, object], message: str
) -> None:
    environment, policies, repository, default_ref, default_commit = _environment_inputs()
    environment = {**environment, **environment_update}
    policies = {**policies, **policies_update}
    with pytest.raises(PublicationError, match=message):
        validate_environment_reviewers(environment, policies, repository, default_ref, default_commit)


def test_tag_named_main_or_wrong_default_branch_ref_fails_environment_proof() -> None:
    environment, policies, repository, default_ref, default_commit = _environment_inputs()
    tag_ref = {**default_ref, "ref": "refs/tags/main"}
    with pytest.raises(PublicationError, match="wrong ref"):
        validate_environment_reviewers(environment, policies, repository, tag_ref, default_commit)
    feature_ref = {**default_ref, "ref": "refs/heads/feature/public-pages"}
    with pytest.raises(PublicationError, match="wrong ref"):
        validate_environment_reviewers(environment, policies, repository, feature_ref, default_commit)


def test_numeric_run_id_and_pages_source_are_strict() -> None:
    assert parse_run_id(str(RUN_ID)) == RUN_ID
    for value in ("", "0", "-1", "1.0", "12x", " 12"):
        with pytest.raises(PublicationError):
            parse_run_id(value)
    validate_pages_settings({"build_type": "workflow"})
    with pytest.raises(PublicationError, match="GitHub Actions"):
        validate_pages_settings({"build_type": "legacy"})
