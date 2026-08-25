#!/usr/bin/env python3
"""Validate and publish a bot-only Lane B five-run report bundle.

This is deliberately narrower than a general Actions-artifact publisher.  It
accepts one exact Lane B series artifact, verifies its GitHub run provenance
and report hashes, then regenerates a small public allowlist in a fresh Pages
directory. Raw reports, source HTML/SVG, database evidence, logs, player
identities, positions, and AI request payloads never enter the Pages payload.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import math
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable


EXPECTED_REPOSITORY = "afraznein/KTPInfrastructure"
EXPECTED_WORKFLOW_NAME = "Lane B Stats E2E"
EXPECTED_WORKFLOW_PATH = ".github/workflows/lane-b-stats-e2e.yml"
SERIES_TAG_PREFIX = "lane-b-preprod-series-"
RUN_COUNT = 5

TOP_SOURCE_FILES = {
    "index.html",
    "SERIES_COMPARISON.md",
    "series-comparison.json",
}
RUN_SOURCE_FILES = {
    "bundle-provenance.md",
    "lane-b-summary.md",
    "match-report/ai-request.json",
    "match-report/comparison.json",
    "match-report/comparison.md",
    "match-report/facts.normalized.json",
    "match-report/manifest.json",
    "match-report/momentum.svg",
    "match-report/points-timeline.json",
    "match-report/points-timeline.svg",
    "match-report/report-verification.json",
    "match-report/report.html",
    "match-report/report.json",
    "match-report/report.md",
}
MANIFEST_FILES = {
    "ai-request.json",
    "comparison.json",
    "comparison.md",
    "momentum.svg",
    "points-timeline.json",
    "points-timeline.svg",
    "report.html",
    "report.json",
    "report.md",
}
EXPECTED_BUNDLE_REPOSITORIES = {
    "infrastructure": "afraznein/KTPInfrastructure",
    "matchhandler": "afraznein/KTPMatchHandler",
    "amxx": "afraznein/KTPAMXX",
    "hlstatsx": "afraznein/KTPHLStatsX",
}
PLAYER_COUNT = 12
TEAM_PLAYER_COUNT = 6
EXPECTED_PLAY_SECONDS = 360
PUBLIC_PLAYER_FIELDS = {
    "alias",
    "team",
    "rank",
    "impact_index",
    "observed_seconds",
    "kills",
    "deaths",
    "assists",
    "opponent_damage",
    "total_points",
    "combat_points",
    "objective_points",
    "position_points",
    "momentum_points",
}
PLAYER_NUMERIC_FIELDS = {
    "kills",
    "deaths",
    "assists",
    "team_kills",
    "suicides",
    "opponent_damage",
    "observed_seconds",
    "combat_finisher_points",
    "combat_damage_share_points",
    "streak_points",
    "shutdown_points",
    "fast_chain_points",
    "capture_points",
    "conversion_points",
    "cap_break_points",
    "position_points",
    "momentum_points",
    "total_points",
    "points_per_minute",
    "participation_percent",
    "impact_index",
    "rank",
}
COMPONENT_FIELDS = {
    "combat_finisher_points",
    "combat_damage_share_points",
    "fallback_assist_points",
    "fallback_damage_points",
    "streak_points",
    "shutdown_points",
    "fast_chain_points",
    "capture_points",
    "conversion_points",
    "cap_break_points",
    "position_points",
    "momentum_points",
}
SERIES_EVENT_FIELDS = {
    "assists",
    "cap_break_credits",
    "capture_credits",
    "capture_events",
    "damage_rows",
    "enemy_frags",
    "position_samples",
}

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_SOURCE_BYTES = 50 * 1024 * 1024

FORBIDDEN_PUBLIC_JSON_KEYS = {
    "authid",
    "database_url",
    "dsn",
    "ip_address",
    "password",
    "passwd",
    "player_id",
    "player_name",
    "player_name_at_match",
    "player_positions",
    "pos_x",
    "pos_y",
    "pos_z",
    "raw_positions",
    "secret",
    "ssh_host",
    "source_id",
    "steam_id",
    "steamid",
    "token",
}
FORBIDDEN_PUBLIC_PATTERNS = (
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"(?:mysql|mariadb|postgres(?:ql)?)://", re.IGNORECASE),
    re.compile(r"\bKTP_TIER2_(?:SSH|DB|MYSQL|PASSWORD|TOKEN)[A-Z0-9_]*\b"),
    re.compile(r"\b(?:password|passwd|secret|token)\s*[:=]\s*[^\s,;]+", re.IGNORECASE),
    re.compile(r"\bSTEAM_[0-5]:[01]:[0-9]+\b", re.IGNORECASE),
    re.compile(r"\[U:[0-9]+:[0-9]+\]", re.IGNORECASE),
    re.compile(r"\b7656119[0-9]{10}\b"),
    re.compile(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}(?::[0-9]{1,5})?\b"),
    re.compile(r"(?:^|[\s`])(?:/opt/|/home/|[A-Za-z]:\\|root@)", re.IGNORECASE),
    re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE),
    re.compile(r"\b(?:api|access)[_-]?token\s*[:=]\s*[^\s,;]+", re.IGNORECASE),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
)
FORBIDDEN_SOURCE_PATH_PARTS = {
    "daemon",
    "database",
    "logs",
    "mysql",
    "positions",
    "prod",
    "production",
    "raw",
    "secrets",
    "sql",
    "ssh",
}
UNSAFE_HTML_PATTERNS = (
    re.compile(r"<(?:script|iframe|object|embed|base|link|form|input|button|textarea|select)\b", re.IGNORECASE),
    re.compile(r"<meta\b[^>]*http-equiv\s*=\s*[\"']?refresh", re.IGNORECASE),
    re.compile(r"\bon[a-z]+\s*=", re.IGNORECASE),
    re.compile(r"javascript\s*:", re.IGNORECASE),
    re.compile(r"\bsrcset\s*=", re.IGNORECASE),
    re.compile(r"(?:url\s*\(|@import)", re.IGNORECASE),
    re.compile(r"<foreignObject\b", re.IGNORECASE),
)


class PublicationError(ValueError):
    """A fail-closed publication validation error."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PublicationError(message)


def parse_run_id(value: str) -> int:
    _require(bool(re.fullmatch(r"[1-9][0-9]*", value)), "source_run_id must contain digits only")
    return int(value)


def _series_tag(value: Any, *, label: str) -> str:
    tag = str(value or "")
    _require(
        bool(re.fullmatch(rf"{re.escape(SERIES_TAG_PREFIX)}[A-Za-z0-9._-]{{1,200}}", tag)),
        f"{label} is not a canonical Lane B series tag",
    )
    return tag


def _repository_name(payload: Any) -> str:
    if isinstance(payload, dict):
        return str(payload.get("full_name") or "")
    return ""


def validate_run_metadata(
    run: dict[str, Any],
    workflow: dict[str, Any],
    artifacts: dict[str, Any],
    *,
    repository: str,
    run_id: int,
) -> dict[str, Any]:
    """Validate API payloads and return the small public provenance record."""

    _require(repository == EXPECTED_REPOSITORY, f"repository must be {EXPECTED_REPOSITORY}")
    _require(run.get("id") == run_id, "Actions run id does not match source_run_id")
    _require(_repository_name(run.get("repository")) == repository, "run belongs to another repository")
    _require(
        _repository_name(run.get("head_repository")) == repository,
        "run head belongs to another repository or fork",
    )
    _require(run.get("name") == EXPECTED_WORKFLOW_NAME, "run has the wrong workflow name")
    _require(run.get("path") == EXPECTED_WORKFLOW_PATH, "run has the wrong workflow path")
    _require(isinstance(run.get("workflow_id"), int) and run["workflow_id"] > 0, "run has no workflow id")
    _require(run.get("event") == "push", "only push-triggered Lane B series runs are publishable")
    _require(run.get("status") == "completed", "source run is not completed")
    _require(run.get("conclusion") == "success", "source run did not conclude successfully")
    run_attempt = run.get("run_attempt")
    _require(isinstance(run_attempt, int) and run_attempt > 0, "source run attempt is invalid")
    source_tag = _series_tag(run.get("head_branch"), label="source run tag")
    head_sha = str(run.get("head_sha") or "")
    _require(bool(re.fullmatch(r"[0-9a-f]{40}", head_sha)), "source run has an invalid head SHA")

    _require(workflow.get("id") == run["workflow_id"], "workflow API id does not match the run")
    _require(workflow.get("name") == EXPECTED_WORKFLOW_NAME, "workflow API name does not match")
    _require(workflow.get("path") == EXPECTED_WORKFLOW_PATH, "workflow API path does not match")

    expected_artifact = f"lane-b-series-comparison-{run_id}"
    candidates = [
        item
        for item in artifacts.get("artifacts", [])
        if isinstance(item, dict) and item.get("name") == expected_artifact
    ]
    _require(len(candidates) == 1, f"expected exactly one {expected_artifact} artifact")
    artifact = candidates[0]
    _require(not artifact.get("expired"), "series comparison artifact has expired")
    _require(isinstance(artifact.get("id"), int) and artifact["id"] > 0, "artifact has no valid id")
    artifact_digest = str(artifact.get("digest") or "")
    _require(
        bool(re.fullmatch(r"sha256:[0-9a-f]{64}", artifact_digest)),
        "artifact has no valid immutable digest",
    )
    _require(
        isinstance(artifact.get("size_in_bytes"), int) and 0 < artifact["size_in_bytes"] <= MAX_SOURCE_BYTES,
        "artifact size is invalid",
    )

    expected_url = f"https://github.com/{repository}/actions/runs/{run_id}"
    _require(run.get("html_url") == expected_url, "source run URL is not canonical")
    return {
        "schema_version": 1,
        "scope": "PUBLIC_SYNTHETIC_BOT_TEST_ONLY",
        "repository": repository,
        "source_run_id": run_id,
        "source_run_url": expected_url,
        "source_tag": source_tag,
        "infrastructure_sha": head_sha,
        "run_attempt": run_attempt,
        "workflow_id": run["workflow_id"],
        "workflow_name": EXPECTED_WORKFLOW_NAME,
        "workflow_path": EXPECTED_WORKFLOW_PATH,
        "artifact_id": artifact["id"],
        "artifact_name": expected_artifact,
        "artifact_digest": artifact_digest,
        "artifact_size_bytes": artifact["size_in_bytes"],
    }


def validate_preprod_ancestry(
    *,
    source_sha: str,
    preprod_branch: dict[str, Any],
    preprod_ref: dict[str, Any],
    source_commit: dict[str, Any],
    preprod_commit: dict[str, Any],
    comparison: dict[str, Any],
) -> dict[str, Any]:
    """Prove the tested tag commit is already in the live protected preprod branch."""

    ref_object = preprod_ref.get("object")
    _require(isinstance(ref_object, dict), "preprod ref has no object")
    preprod_sha = str(ref_object.get("sha") or "")
    _require(bool(re.fullmatch(r"[0-9a-f]{40}", preprod_sha)), "preprod ref SHA is invalid")
    branch_commit = preprod_branch.get("commit")
    _require(preprod_branch.get("name") == "preprod", "preprod branch API returned the wrong branch")
    _require(preprod_branch.get("protected") is True, "preprod branch is not protected")
    _require(
        isinstance(branch_commit, dict) and branch_commit.get("sha") == preprod_sha,
        "preprod branch API disagrees with the live ref",
    )
    _require(source_commit.get("sha") == source_sha, "source commit API did not resolve the tested SHA")
    _require(preprod_commit.get("sha") == preprod_sha, "preprod commit API disagrees with the live ref")
    _require(comparison.get("status") in {"ahead", "identical"}, "source is not an ancestor of preprod")
    base_commit = comparison.get("base_commit")
    merge_base = comparison.get("merge_base_commit")
    _require(isinstance(base_commit, dict) and base_commit.get("sha") == source_sha, "compare base is not source")
    _require(isinstance(merge_base, dict) and merge_base.get("sha") == source_sha, "source is not preprod ancestry")
    _require(comparison.get("behind_by") == 0, "comparison reports preprod behind the source")
    ahead_by = comparison.get("ahead_by")
    _require(isinstance(ahead_by, int) and ahead_by >= 0, "comparison ahead count is invalid")
    return {
        "protected_ref": "refs/heads/preprod",
        "branch_protection": True,
        "source_sha": source_sha,
        "preprod_sha": preprod_sha,
        "compare_status": comparison["status"],
        "preprod_commits_ahead": ahead_by,
        "merge_base_sha": source_sha,
        "verified_via": "GitHub branch+refs+commits+compare APIs",
    }


def validate_publisher_event(
    *,
    event_name: str,
    event_action: str,
    event_ref: str,
    event_sha: str,
    repository_payload: dict[str, Any],
    default_ref: dict[str, Any],
    default_commit: dict[str, Any],
) -> dict[str, Any]:
    """Prove the publisher itself is the live default-branch workflow."""

    _require(
        repository_payload.get("full_name") == EXPECTED_REPOSITORY,
        "repository API response does not match the publisher repository",
    )
    default_branch = str(repository_payload.get("default_branch") or "")
    _require(
        bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,254}", default_branch))
        and ".." not in default_branch
        and not default_branch.endswith(("/", ".lock")),
        "repository default branch is invalid",
    )
    expected_ref = f"refs/heads/{default_branch}"
    ref_object = default_ref.get("object")
    _require(default_ref.get("ref") == expected_ref, "default-branch ref API returned the wrong ref")
    _require(isinstance(ref_object, dict) and ref_object.get("type") == "commit", "default ref is not a commit")
    default_sha = str(ref_object.get("sha") or "") if isinstance(ref_object, dict) else ""
    _require(bool(re.fullmatch(r"[0-9a-f]{40}", default_sha)), "default-branch SHA is invalid")
    _require(default_commit.get("sha") == default_sha, "default-branch commit API disagrees with its ref")

    expected_actions = {
        "repository_dispatch": "publish-lane-b-pages",
        "workflow_run": "completed",
    }
    _require(event_name in expected_actions, "publisher event type is forbidden")
    _require(event_action == expected_actions[event_name], "publisher event action is forbidden")
    _require(event_ref == expected_ref, "publisher event did not run on the default branch ref")
    _require(bool(re.fullmatch(r"[0-9a-f]{40}", event_sha)), "publisher event SHA is invalid")
    _require(event_sha == default_sha, "publisher event SHA is not the live default-branch tip")
    return {
        "event_name": event_name,
        "event_action": event_action,
        "default_branch": default_branch,
        "publisher_ref": expected_ref,
        "publisher_sha": default_sha,
        "verified_via": "GitHub event context+repository+default-ref+commit APIs",
    }


def validate_environment_reviewers(
    payload: dict[str, Any],
    policies: dict[str, Any],
    repository_payload: dict[str, Any],
    default_ref: dict[str, Any],
    default_commit: dict[str, Any],
) -> dict[str, Any]:
    """Require reviewers and an exact default-branch-only deployment policy."""

    _require(payload.get("name") == "github-pages", "github-pages environment is missing")
    _require(
        repository_payload.get("full_name") == EXPECTED_REPOSITORY,
        "repository API response does not match the publisher repository",
    )
    default_branch = str(repository_payload.get("default_branch") or "")
    _require(
        bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,254}", default_branch))
        and ".." not in default_branch
        and not default_branch.endswith(("/", ".lock")),
        "repository default branch is invalid",
    )
    ref_object = default_ref.get("object")
    _require(
        default_ref.get("ref") == f"refs/heads/{default_branch}",
        "default-branch ref API returned the wrong ref",
    )
    _require(isinstance(ref_object, dict) and ref_object.get("type") == "commit", "default ref is not a commit")
    default_sha = str(ref_object.get("sha") or "") if isinstance(ref_object, dict) else ""
    _require(bool(re.fullmatch(r"[0-9a-f]{40}", default_sha)), "default-branch SHA is invalid")
    _require(default_commit.get("sha") == default_sha, "default-branch commit API disagrees with its ref")

    deployment = payload.get("deployment_branch_policy")
    _require(isinstance(deployment, dict), "github-pages deployment branch policy is missing")
    _require(deployment.get("protected_branches") is False, "protected-branches deployment mode is forbidden")
    _require(deployment.get("custom_branch_policies") is True, "custom deployment branch policies are required")

    branch_policies = policies.get("branch_policies")
    _require(policies.get("total_count") == 1, "github-pages must have exactly one deployment branch policy")
    _require(isinstance(branch_policies, list) and len(branch_policies) == 1, "deployment policy list is incomplete")
    policy = branch_policies[0]
    _require(isinstance(policy, dict), "github-pages deployment policy is malformed")
    _require(policy.get("type") == "branch", "github-pages deployment policy must target a branch, not a tag")
    _require(policy.get("name") == default_branch, "deployment policy must exactly equal the default branch")
    _require(isinstance(policy.get("id"), int) and policy["id"] > 0, "deployment policy id is invalid")

    rules = payload.get("protection_rules")
    _require(isinstance(rules, list), "github-pages protection rules are missing")
    reviewer_rules = [rule for rule in rules if isinstance(rule, dict) and rule.get("type") == "required_reviewers"]
    _require(len(reviewer_rules) == 1, "github-pages must have exactly one required-reviewers rule")
    rule = reviewer_rules[0]
    reviewers = rule.get("reviewers")
    _require(isinstance(reviewers, list), "required-reviewers rule has no reviewer list")
    valid_reviewers = [
        row for row in reviewers
        if isinstance(row, dict)
        and row.get("type") in {"User", "Team"}
        and isinstance(row.get("reviewer"), dict)
        and isinstance(row["reviewer"].get("id"), int)
        and row["reviewer"]["id"] > 0
    ]
    _require(len(valid_reviewers) == len(reviewers), "required-reviewers rule contains an invalid reviewer")
    reviewer_count = len(valid_reviewers)
    _require(reviewer_count >= 1, "github-pages must enforce at least one required reviewer")
    rule_id = rule.get("id")
    _require(isinstance(rule_id, int) and rule_id > 0, "required-reviewers rule id is invalid")
    _require(
        rule.get("prevent_self_review") is True,
        "github-pages required-reviewers rule must positively prevent self-review",
    )
    return {
        "environment": "github-pages",
        "required_reviewer_count": reviewer_count,
        "required_reviewer_rule_ids": [rule_id],
        "prevent_self_review": True,
        "default_branch": default_branch,
        "default_branch_sha": default_sha,
        "protected_branches": False,
        "custom_branch_policies": True,
        "deployment_policy_count": 1,
        "deployment_policy_id": policy["id"],
        "deployment_policy_name": default_branch,
        "deployment_policy_type": "branch",
        "verified_via": "GitHub repository+refs+commits+environments+deployment-policy APIs",
    }


def _api_json(url: str, token: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2026-03-10",
            "User-Agent": "ktp-lane-b-pages-validator",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        raise PublicationError(f"GitHub API request failed ({exc.code}): {url}") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise PublicationError(f"GitHub API request failed: {url}: {exc}") from exc
    _require(isinstance(payload, dict), f"GitHub API returned a non-object for {url}")
    return payload


def fetch_and_validate_run(
    *,
    api_url: str,
    repository: str,
    run_id: int,
    token: str,
    publisher_event_name: str,
    publisher_event_action: str,
    publisher_ref: str,
    publisher_sha: str,
) -> dict[str, Any]:
    base = f"{api_url.rstrip('/')}/repos/{repository}"
    repository_payload = _api_json(base, token)
    run = _api_json(f"{base}/actions/runs/{run_id}", token)
    workflow_id = run.get("workflow_id")
    _require(isinstance(workflow_id, int) and workflow_id > 0, "source run has no workflow id")
    workflow = _api_json(f"{base}/actions/workflows/{workflow_id}", token)
    artifacts = _api_json(f"{base}/actions/runs/{run_id}/artifacts?per_page=100", token)
    metadata = validate_run_metadata(run, workflow, artifacts, repository=repository, run_id=run_id)
    source_sha = metadata["infrastructure_sha"]
    preprod_branch = _api_json(f"{base}/branches/preprod", token)
    preprod_ref = _api_json(f"{base}/git/ref/heads/preprod", token)
    preprod_sha = str((preprod_ref.get("object") or {}).get("sha") or "")
    _require(bool(re.fullmatch(r"[0-9a-f]{40}", preprod_sha)), "preprod ref API returned an invalid SHA")
    source_commit = _api_json(f"{base}/commits/{source_sha}", token)
    preprod_commit = _api_json(f"{base}/commits/{preprod_sha}", token)
    comparison = _api_json(f"{base}/compare/{source_sha}...{preprod_sha}", token)
    default_branch = str(repository_payload.get("default_branch") or "")
    _require(bool(default_branch), "repository API returned no default branch")
    encoded_default_branch = urllib.parse.quote(default_branch, safe="")
    default_ref = _api_json(f"{base}/git/ref/heads/{encoded_default_branch}", token)
    default_sha = str((default_ref.get("object") or {}).get("sha") or "")
    _require(bool(re.fullmatch(r"[0-9a-f]{40}", default_sha)), "default-branch ref API returned an invalid SHA")
    default_commit = _api_json(f"{base}/commits/{default_sha}", token)
    metadata["publisher_event"] = validate_publisher_event(
        event_name=publisher_event_name,
        event_action=publisher_event_action,
        event_ref=publisher_ref,
        event_sha=publisher_sha,
        repository_payload=repository_payload,
        default_ref=default_ref,
        default_commit=default_commit,
    )
    try:
        environment = _api_json(f"{base}/environments/github-pages", token)
        policies = _api_json(
            f"{base}/environments/github-pages/deployment-branch-policies?per_page=100",
            token,
        )
    except PublicationError as exc:
        raise PublicationError(
            "github-pages must enforce reviewer approval and one custom default-branch-only deployment policy"
        ) from exc
    metadata["preprod_ancestry"] = validate_preprod_ancestry(
        source_sha=source_sha,
        preprod_branch=preprod_branch,
        preprod_ref=preprod_ref,
        source_commit=source_commit,
        preprod_commit=preprod_commit,
        comparison=comparison,
    )
    metadata["publication_approval"] = validate_environment_reviewers(
        environment,
        policies,
        repository_payload,
        default_ref,
        default_commit,
    )
    return metadata


def validate_pages_settings(payload: dict[str, Any]) -> None:
    _require(payload.get("build_type") == "workflow", "GitHub Pages source must be set to GitHub Actions")


def fetch_and_validate_pages_settings(*, api_url: str, repository: str, token: str) -> None:
    url = f"{api_url.rstrip('/')}/repos/{repository}/pages"
    try:
        payload = _api_json(url, token)
    except PublicationError as exc:
        raise PublicationError(
            "GitHub Pages is unavailable. Enable Pages with GitHub Actions as the source, "
            "then configure the github-pages environment/reviewer before publishing."
        ) from exc
    validate_pages_settings(payload)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PublicationError(f"invalid JSON: {path}") from exc
    _require(isinstance(value, dict), f"JSON root must be an object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _expected_source_files() -> set[str]:
    expected = set(TOP_SOURCE_FILES)
    for run in range(1, RUN_COUNT + 1):
        expected.update(f"run-{run}/{name}" for name in RUN_SOURCE_FILES)
    return expected


def _safe_relative_path(path: str, *, label: str) -> PurePosixPath:
    candidate = PurePosixPath(path)
    _require(not candidate.is_absolute(), f"{label} path is absolute: {path}")
    _require(path == candidate.as_posix(), f"{label} path is not canonical: {path}")
    _require(all(part not in {"", ".", ".."} for part in candidate.parts), f"{label} path escapes: {path}")
    return candidate


def audit_source_tree(root: Path) -> None:
    _require(root.is_dir(), f"series artifact directory does not exist: {root}")
    actual: set[str] = set()
    total_bytes = 0
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        for directory in directories:
            path = current_path / directory
            _require(not path.is_symlink(), f"source artifact contains a symlink: {path}")
        for filename in files:
            path = current_path / filename
            _require(not path.is_symlink(), f"source artifact contains a symlink: {path}")
            _require(path.is_file(), f"source artifact contains a non-file: {path}")
            relative = path.relative_to(root).as_posix()
            _safe_relative_path(relative, label="artifact")
            size = path.stat().st_size
            _require(size <= MAX_FILE_BYTES, f"source artifact file is too large: {relative}")
            total_bytes += size
            actual.add(relative)
    _require(total_bytes <= MAX_SOURCE_BYTES, "source artifact is too large")
    expected = _expected_source_files()
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    _require(not missing, "source artifact is missing required files: " + ", ".join(missing))
    _require(not extra, "source artifact contains unapproved files: " + ", ".join(extra))


def _validate_json_keys(value: Any, *, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = str(key).strip().lower()
            _require(normalized not in FORBIDDEN_PUBLIC_JSON_KEYS, f"forbidden public JSON key at {path}: {key}")
            _validate_json_keys(child, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_json_keys(child, path=f"{path}[{index}]")


def _validate_public_text(path: Path) -> None:
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise PublicationError(f"public asset is not UTF-8 text: {path}") from exc
    for pattern in FORBIDDEN_PUBLIC_PATTERNS:
        _require(not pattern.search(text), f"public asset matches forbidden secret/data pattern: {path}")
    lower_parts = {part.lower() for part in path.parts}
    _require(not lower_parts.intersection(FORBIDDEN_SOURCE_PATH_PARTS), f"forbidden public path: {path}")
    if path.suffix == ".json":
        _validate_json_keys(_load_json(path))


def _verify_manifest(report_dir: Path) -> dict[str, Any]:
    manifest = _load_json(report_dir / "manifest.json")
    _require(manifest.get("schema_version") == 1, "unsupported report manifest schema")
    _require(str(manifest.get("match_id") or "").endswith("-TEST"), "report is not a test match")
    _require(manifest.get("publication_state") == "DRAFT", "report was not generated as a draft")
    _require(
        manifest.get("publication_checkpoint") == "HUMAN_REVIEW_REQUIRED",
        "report bypassed the human-review checkpoint",
    )
    invariants = manifest.get("invariants")
    _require(isinstance(invariants, dict), "manifest invariants are missing")
    _require(invariants.get("ai_can_publish") is False, "AI publication invariant is unsafe")
    _require(invariants.get("raw_individual_positions_exported") is False, "raw positions were exported")
    _require(invariants.get("points_timeline_team_only") is True, "timeline is not team-only")

    entries = manifest.get("files")
    _require(isinstance(entries, list), "manifest file list is missing")
    seen: set[str] = set()
    for entry in entries:
        _require(isinstance(entry, dict), "manifest file entry is invalid")
        relative = str(entry.get("path") or "")
        candidate = _safe_relative_path(relative, label="manifest")
        _require(len(candidate.parts) == 1, f"manifest file must stay in match-report: {relative}")
        _require(relative not in seen, f"duplicate manifest file: {relative}")
        seen.add(relative)
        target = report_dir / relative
        _require(target.is_file() and not target.is_symlink(), f"manifest file is missing or unsafe: {relative}")
        _require(target.stat().st_size == entry.get("bytes"), f"manifest byte count mismatch: {relative}")
        _require(_sha256(target) == entry.get("sha256"), f"manifest hash mismatch: {relative}")
    _require(seen == MANIFEST_FILES, "manifest file allowlist does not match the expected report contract")
    facts = report_dir / "facts.normalized.json"
    _require(_sha256(facts) == manifest.get("facts_sha256"), "normalized facts hash mismatch")
    _require(_sha256(report_dir / "report.json") == manifest.get("report_file_sha256"), "report hash mismatch")
    return manifest


def _number(
    value: Any,
    *,
    label: str,
    minimum: float = 0.0,
    maximum: float = 1_000_000_000.0,
    integer: bool = False,
) -> int | float:
    if integer:
        _require(not isinstance(value, bool) and isinstance(value, int), f"{label} is not an integer")
        _require(minimum <= value <= maximum, f"{label} is outside the public numeric bounds")
        return value
    _require(not isinstance(value, bool) and isinstance(value, (int, float)), f"{label} is not numeric")
    number = float(value)
    _require(math.isfinite(number), f"{label} is not finite")
    _require(minimum <= number <= maximum, f"{label} is outside the public numeric bounds")
    return round(number, 4)


def _safe_match_id(value: Any, *, label: str) -> str:
    match_id = str(value or "")
    _require(bool(re.fullmatch(r"[0-9]{6,20}-TEST", match_id)), f"{label} is not a Lane B test match id")
    return match_id


def _safe_map_name(value: Any, *, label: str) -> str:
    map_name = str(value or "")
    _require(bool(re.fullmatch(r"[a-z0-9_]{1,64}", map_name)), f"{label} is invalid")
    return map_name


def _quality_gate_statuses(value: Any, *, label: str) -> dict[str, str]:
    _require(isinstance(value, dict) and value, f"{label} are missing")
    result: dict[str, str] = {}
    for key, row in value.items():
        _require(bool(re.fullmatch(r"[a-z][a-z0-9_]{0,63}", str(key))), f"{label} key is invalid")
        status = row.get("status") if isinstance(row, dict) else row
        _require(status in {"PASS", "WARN", "DISABLED"}, f"{label}.{key} has an unsafe status")
        result[str(key)] = str(status)
    return dict(sorted(result.items()))


def _validate_series_run(row: dict[str, Any], *, number: int) -> dict[str, Any]:
    _require(row.get("run") == number, f"series run {number} has the wrong index")
    match_id = _safe_match_id(row.get("match_id"), label=f"series run {number} match id")
    _require(row.get("verification") == "PASS", f"series run {number} did not verify")
    _require(
        _number(row.get("players"), label="series players", integer=True) == PLAYER_COUNT,
        "series is not 12-player Lane B",
    )
    events = row.get("events")
    _require(isinstance(events, dict) and set(events) == SERIES_EVENT_FIELDS, "series event contract changed")
    public_events = {
        key: _number(events[key], label=f"series events.{key}", integer=True)
        for key in sorted(SERIES_EVENT_FIELDS)
    }
    ratings = row.get("rating_distribution")
    _require(
        isinstance(ratings, dict) and set(ratings) == {"minimum", "q1", "median", "q3", "maximum"},
        "series rating distribution contract changed",
    )
    public_ratings = {
        key: _number(ratings[key], label=f"series ratings.{key}", maximum=10_000)
        for key in ("minimum", "q1", "median", "q3", "maximum")
    }
    _require(
        list(public_ratings.values()) == sorted(public_ratings.values()),
        "series rating distribution is not ordered",
    )
    return {
        "run": number,
        "match_id": match_id,
        "map_name": _safe_map_name(row.get("map_name"), label="series map"),
        "duration_seconds": _number(row.get("duration_seconds"), label="series duration", maximum=86_400),
        "players": PLAYER_COUNT,
        "events": public_events,
        "match_total_points": _number(row.get("match_total_points"), label="series match points"),
        "rating_distribution": public_ratings,
        "quality_gates": _quality_gate_statuses(row.get("quality_gates"), label="series quality gates"),
    }


def _validate_public_players(players: Any) -> list[dict[str, Any]]:
    _require(isinstance(players, list) and len(players) == PLAYER_COUNT, "report must contain exactly 12 bots")
    ids: set[int] = set()
    source_rows: list[dict[str, Any]] = []
    team_counts = {"Team 1": 0, "Team 2": 0}
    for index, player in enumerate(players, 1):
        _require(isinstance(player, dict), f"report player {index} is invalid")
        player_id = _number(
            player.get("player_id"), label="source player id", minimum=1, maximum=2**63 - 1, integer=True
        )
        _require(player_id not in ids, "report player ids are not unique")
        ids.add(player_id)
        source_name = str(player.get("player_name_at_match") or "")
        _require(0 < len(source_name) <= 128, "source bot name is invalid")
        team = str(player.get("team_name") or "")
        _require(team in team_counts, "report player has an unexpected team")
        team_counts[team] += 1
        validated: dict[str, int | float] = {}
        for field in PLAYER_NUMERIC_FIELDS:
            integer = field in {"kills", "deaths", "assists", "team_kills", "suicides", "rank"}
            maximum = 100_000 if integer else 1_000_000_000
            if field == "participation_percent":
                maximum = 100
            elif field == "observed_seconds":
                maximum = 86_400
            elif field == "impact_index":
                maximum = 10_000
            validated[field] = _number(
                player.get(field), label=f"player.{field}", maximum=maximum, integer=integer
            )
        source_rows.append({"source_id": player_id, "team": team, **validated})
    _require(
        team_counts == {"Team 1": TEAM_PLAYER_COUNT, "Team 2": TEAM_PLAYER_COUNT},
        "Lane B roster is not 6v6",
    )
    aliases = {player_id: f"Bot {number:02d}" for number, player_id in enumerate(sorted(ids), 1)}
    ranks = [int(row["rank"]) for row in source_rows]
    _require(sorted(ranks) == list(range(1, PLAYER_COUNT + 1)), "report player ranks are not 1 through 12")
    public = []
    for row in sorted(source_rows, key=lambda item: int(item["rank"])):
        public.append({
            "alias": aliases[int(row["source_id"])],
            "team": row["team"],
            "rank": row["rank"],
            "impact_index": row["impact_index"],
            "observed_seconds": row["observed_seconds"],
            "kills": row["kills"],
            "deaths": row["deaths"],
            "assists": row["assists"],
            "opponent_damage": row["opponent_damage"],
            "total_points": row["total_points"],
            "combat_points": round(
                float(row["combat_finisher_points"]) + float(row["combat_damage_share_points"]), 4
            ),
            "objective_points": round(
                float(row["capture_points"]) + float(row["conversion_points"]) + float(row["cap_break_points"]), 4
            ),
            "position_points": row["position_points"],
            "momentum_points": row["momentum_points"],
        })
    return public


def _validate_timeline(
    timeline: dict[str, Any], *, expected_match_id: str, duration_seconds: float
) -> dict[str, Any]:
    _require(timeline.get("schema_version") == 1, "unsupported timeline schema")
    _require(timeline.get("match_id") == expected_match_id, "timeline match id disagrees")
    _require(timeline.get("teams") == [1, 2], "timeline teams changed")
    _require(set(timeline.get("components") or []) == COMPONENT_FIELDS, "timeline component contract changed")
    privacy = timeline.get("privacy")
    _require(isinstance(privacy, dict), "timeline privacy contract is missing")
    _require(privacy.get("scope") == "team_only", "timeline is not team-only")
    _require(privacy.get("individual_timing") == "not_exported", "timeline exposes individual timing")
    _require(privacy.get("spatial_detail") == "not_exported", "timeline exposes spatial detail")
    bin_seconds = _number(timeline.get("bin_seconds"), label="timeline bin seconds", minimum=1, maximum=300)
    halves = timeline.get("halves")
    _require(isinstance(halves, list) and len(halves) == 1, "public Lane B series must contain one half")
    half = halves[0]
    _require(isinstance(half, dict) and half.get("half") == 1, "timeline half contract changed")
    bins = half.get("bins")
    _require(isinstance(bins, list) and 1 <= len(bins) <= 10_000, "timeline bins are invalid")
    public_bins = []
    previous_end = 0.0
    previous_cumulative = {"1": 0.0, "2": 0.0}
    # The report contract may place privacy-deferred position reconciliation in
    # one additional aligned bin after the first bin boundary at/after play end.
    latest_allowed_end = math.ceil(duration_seconds / float(bin_seconds)) * float(bin_seconds)
    latest_allowed_end += float(bin_seconds)
    for index, row in enumerate(bins):
        _require(isinstance(row, dict), f"timeline bin {index} is invalid")
        start = _number(row.get("start_time"), label="timeline start", maximum=86_400)
        end = _number(row.get("end_time"), label="timeline end", maximum=86_400)
        _require(start == previous_end and end > start, "timeline bins are not contiguous")
        _require(end <= latest_allowed_end + 0.01, "timeline extends beyond one deferred final bin")
        teams = row.get("teams")
        _require(isinstance(teams, dict) and set(teams) == {"1", "2"}, "timeline team rows changed")
        output = {"start_time": start, "end_time": end}
        for team in ("1", "2"):
            team_row = teams[team]
            _require(isinstance(team_row, dict), "timeline team row is invalid")
            components = team_row.get("components")
            _require(
                isinstance(components, dict) and set(components) == COMPONENT_FIELDS,
                "timeline components changed",
            )
            for key, value in components.items():
                _number(value, label=f"timeline component {key}")
            gained = _number(team_row.get("points_gained"), label="timeline points gained")
            cumulative = _number(team_row.get("cumulative_points"), label="timeline cumulative")
            _require(cumulative + 0.01 >= previous_cumulative[team], "timeline cumulative points decreased")
            previous_cumulative[team] = float(cumulative)
            output[f"team_{team}_points_gained"] = gained
            output[f"team_{team}_cumulative_points"] = cumulative
        output["momentum"] = _number(
            row.get("momentum"), label="timeline momentum", minimum=-100, maximum=100
        )
        public_bins.append(output)
        previous_end = float(end)
    return {
        "schema_version": 1,
        "scope": "PUBLIC_SYNTHETIC_BOT_TEST_ONLY_TEAM_AGGREGATES",
        "match_id": expected_match_id,
        "bin_seconds": bin_seconds,
        "half": 1,
        "bins": public_bins,
    }


def _verify_report(
    report_dir: Path, *, series_run: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    expected_match_id = series_run["match_id"]
    manifest = _verify_manifest(report_dir)
    _require(manifest["match_id"] == expected_match_id, "manifest match id disagrees with the series")
    verification = _load_json(report_dir / "report-verification.json")
    _require(verification.get("schema_version") == 1, "unsupported report verification schema")
    _require(verification.get("status") == "PASS", "report verification did not pass")
    _require(verification.get("errors") == [], "report verification contains errors")
    checks = verification.get("checks")
    _require(isinstance(checks, dict) and checks, "report verification checks are missing")
    _require(all(value == "PASS" for value in checks.values()), "one or more report verification checks failed")
    for required in ("manifest_hashes", "public_privacy", "points_timeline_privacy", "required_files"):
        _require(checks.get(required) == "PASS", f"required verification check did not pass: {required}")

    report = _load_json(report_dir / "report.json")
    _require(report.get("schema_version") == 1, "unsupported report schema")
    _require(report.get("status") == "experimental_shadow", "report is not experimental shadow output")
    _require(report.get("publication_state") == "DRAFT", "report is not a draft")
    _require(report.get("profile") == "accumulation_v5_momentum", "unexpected scoring profile")
    _require(report.get("profile_status") == "experimental_shadow", "profile status is not experimental")
    match = report.get("match")
    _require(isinstance(match, dict), "report match metadata is missing")
    _require(match.get("match_id") == expected_match_id, "report match id disagrees with the series")
    _require(match.get("is_test_match") is True, "production/real-player report is forbidden")
    _require(match.get("source_mode") == "lane_b_ephemeral_mysql", "report was not produced by Lane B")
    _require(match.get("scoring_iteration") == "v5_team_momentum", "report scoring iteration changed")
    _require(match.get("map_name") == series_run["map_name"], "report map disagrees with the series")
    duration = _number(match.get("duration_seconds"), label="report duration", maximum=86_400)
    _require(abs(float(duration) - float(series_run["duration_seconds"])) <= 0.01, "report duration disagrees")
    privacy = report.get("privacy")
    _require(isinstance(privacy, dict), "report privacy contract is missing")
    _require(privacy.get("individual_positions") == "private_not_embedded", "individual positions are embedded")
    players = _validate_public_players(report.get("players"))
    components = report.get("component_totals")
    _require(isinstance(components, dict) and set(components) == COMPONENT_FIELDS, "component total contract changed")
    public_components = {
        key: _number(components[key], label=f"component total {key}") for key in sorted(COMPONENT_FIELDS)
    }
    total_points = _number(report.get("match_total_points"), label="report match total")
    _require(abs(float(total_points) - float(series_run["match_total_points"])) <= 0.1, "report points disagree")
    report_gates = _quality_gate_statuses(report.get("quality_gates"), label="report quality gates")
    _require(report_gates == series_run["quality_gates"], "report quality gates disagree with the series")
    public_report = {
        "schema_version": 1,
        "scope": "PUBLIC_SYNTHETIC_BOT_TEST_ONLY_ALIASED",
        "match": {
            "match_id": expected_match_id,
            "map_name": series_run["map_name"],
            "duration_seconds": duration,
            "players": PLAYER_COUNT,
            "bots": PLAYER_COUNT,
            "profile": "accumulation_v5_momentum",
        },
        "players": players,
        "events": series_run["events"],
        "component_totals": public_components,
        "match_total_points": total_points,
        "quality_gates": report_gates,
    }
    public_timeline = _validate_timeline(
        _load_json(report_dir / "points-timeline.json"),
        expected_match_id=expected_match_id,
        duration_seconds=float(duration),
    )
    return public_report, public_timeline


def _validate_bot_summary(path: Path, *, match_id: str, map_name: str) -> tuple[int, int]:
    rows = [line for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("| PASS |")]
    _require(len(rows) == 1, "Lane B summary must contain exactly one PASS match row")
    cells = [cell.strip() for cell in rows[0].strip("|").split("|")]
    _require(len(cells) == 7, "Lane B summary match row has an unexpected shape")
    _require(cells[1] == map_name, "Lane B summary map disagrees with the series")
    _require(cells[2] == match_id, "Lane B summary match id disagrees with the series")
    try:
        half, play_seconds = int(cells[3]), int(cells[4])
        players, bots = int(cells[5]), int(cells[6])
    except ValueError as exc:
        raise PublicationError("Lane B summary numeric values are invalid") from exc
    _require(half == 1, "Lane B summary is not the expected single half")
    _require(play_seconds == EXPECTED_PLAY_SECONDS, "Lane B summary play window changed")
    _require(players == PLAYER_COUNT and bots == PLAYER_COUNT, "public publication requires exactly 12 bots")
    return players, bots


def _validate_provenance(path: Path, metadata: dict[str, Any]) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    rows = re.findall(
        r"^\| ([a-z]+) \| `([^`]+)` \| `([^`]+)` \| `([0-9a-f]{40})` \|$",
        text,
        re.MULTILINE,
    )
    _require(len(rows) == 4, "bundle provenance must contain exactly four canonical repository rows")
    commits: dict[str, str] = {}
    for component, repository, requested_ref, commit in rows:
        _require(component in EXPECTED_BUNDLE_REPOSITORIES, f"unexpected provenance component: {component}")
        _require(component not in commits, f"duplicate provenance component: {component}")
        _require(repository == EXPECTED_BUNDLE_REPOSITORIES[component], f"wrong repository for {component}")
        _require(requested_ref == "preprod", f"{component} was not resolved from preprod")
        commits[component] = commit
    _require(set(commits) == set(EXPECTED_BUNDLE_REPOSITORIES), "bundle provenance component set is incomplete")
    _require(commits["infrastructure"] == metadata["infrastructure_sha"], "bundle SHA disagrees with source run")
    expected_ref = (
        f"- workflow_ref: `afraznein/KTPInfrastructure/{EXPECTED_WORKFLOW_PATH}"
        f"@refs/tags/{metadata['source_tag']}`"
    )
    _require(expected_ref in text, "bundle workflow ref disagrees with source run")
    _require(f"- event_sha: `{metadata['infrastructure_sha']}`" in text, "bundle event SHA disagrees")
    _require(f"- run_url: `{metadata['source_run_url']}`" in text, "bundle run URL disagrees")
    return commits


def _validate_metadata(metadata: dict[str, Any]) -> None:
    required = {
        "schema_version": 1,
        "scope": "PUBLIC_SYNTHETIC_BOT_TEST_ONLY",
        "repository": EXPECTED_REPOSITORY,
        "workflow_name": EXPECTED_WORKFLOW_NAME,
        "workflow_path": EXPECTED_WORKFLOW_PATH,
    }
    for key, value in required.items():
        _require(metadata.get(key) == value, f"source metadata has invalid {key}")
    parse_run_id(str(metadata.get("source_run_id") or ""))
    _series_tag(metadata.get("source_tag"), label="metadata tag")
    _require(
        bool(re.fullmatch(r"[0-9a-f]{40}", str(metadata.get("infrastructure_sha") or ""))),
        "metadata SHA is invalid",
    )
    _require(
        isinstance(metadata.get("run_attempt"), int) and metadata["run_attempt"] > 0,
        "metadata run attempt is invalid",
    )
    _require(
        isinstance(metadata.get("workflow_id"), int) and metadata["workflow_id"] > 0,
        "metadata workflow id is invalid",
    )
    expected_url = f"https://github.com/{EXPECTED_REPOSITORY}/actions/runs/{metadata['source_run_id']}"
    _require(metadata.get("source_run_url") == expected_url, "metadata source URL is invalid")
    _require(
        metadata.get("artifact_name") == f"lane-b-series-comparison-{metadata['source_run_id']}",
        "metadata artifact name is invalid",
    )
    _require(isinstance(metadata.get("artifact_id"), int) and metadata["artifact_id"] > 0, "metadata artifact id is invalid")
    _require(
        bool(re.fullmatch(r"sha256:[0-9a-f]{64}", str(metadata.get("artifact_digest") or ""))),
        "metadata artifact digest is invalid",
    )
    _require(
        isinstance(metadata.get("artifact_size_bytes"), int)
        and 0 < metadata["artifact_size_bytes"] <= MAX_SOURCE_BYTES,
        "metadata artifact size is invalid",
    )
    ancestry = metadata.get("preprod_ancestry")
    _require(isinstance(ancestry, dict), "verified preprod ancestry is missing")
    _require(ancestry.get("protected_ref") == "refs/heads/preprod", "wrong protected ancestry ref")
    _require(ancestry.get("branch_protection") is True, "preprod branch protection is not verified")
    _require(ancestry.get("source_sha") == metadata["infrastructure_sha"], "ancestry source SHA disagrees")
    _require(ancestry.get("merge_base_sha") == metadata["infrastructure_sha"], "ancestry merge base disagrees")
    _require(ancestry.get("compare_status") in {"ahead", "identical"}, "preprod ancestry is not verified")
    _require(
        bool(re.fullmatch(r"[0-9a-f]{40}", str(ancestry.get("preprod_sha") or ""))),
        "preprod SHA is invalid",
    )
    approval = metadata.get("publication_approval")
    _require(isinstance(approval, dict), "publication approval evidence is missing")
    _require(approval.get("environment") == "github-pages", "approval environment is wrong")
    _require(
        isinstance(approval.get("required_reviewer_count"), int)
        and approval["required_reviewer_count"] >= 1,
        "at least one required Pages reviewer is mandatory",
    )
    _require(approval.get("protected_branches") is False, "protected-branches deployment mode is forbidden")
    _require(approval.get("custom_branch_policies") is True, "custom deployment branch policy is not verified")
    default_branch = str(approval.get("default_branch") or "")
    _require(
        bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,254}", default_branch)),
        "approval default branch is invalid",
    )
    _require(
        bool(re.fullmatch(r"[0-9a-f]{40}", str(approval.get("default_branch_sha") or ""))),
        "approval default-branch SHA is invalid",
    )
    _require(approval.get("deployment_policy_count") == 1, "exactly one Pages deployment policy is required")
    _require(approval.get("deployment_policy_type") == "branch", "Pages deployment policy is not branch-only")
    _require(
        approval.get("deployment_policy_name") == default_branch,
        "Pages deployment policy does not equal the default branch",
    )
    _require(
        isinstance(approval.get("deployment_policy_id"), int) and approval["deployment_policy_id"] > 0,
        "Pages deployment policy id is invalid",
    )
    _require(approval.get("prevent_self_review") is True, "Pages self-review prevention is not verified")
    publisher = metadata.get("publisher_event")
    _require(isinstance(publisher, dict), "publisher event evidence is missing")
    _require(
        set(publisher) == {
            "event_name",
            "event_action",
            "default_branch",
            "publisher_ref",
            "publisher_sha",
            "verified_via",
        },
        "publisher event evidence schema is invalid",
    )
    expected_actions = {"repository_dispatch": "publish-lane-b-pages", "workflow_run": "completed"}
    publisher_event_name = str(publisher.get("event_name") or "")
    _require(publisher_event_name in expected_actions, "publisher event type is forbidden")
    _require(
        publisher.get("event_action") == expected_actions[publisher_event_name],
        "publisher event action is forbidden",
    )
    _require(
        publisher.get("default_branch") == default_branch
        and publisher.get("publisher_ref") == f"refs/heads/{default_branch}"
        and publisher.get("publisher_sha") == approval["default_branch_sha"],
        "publisher event is not the verified live default-branch publisher",
    )
    _require(
        publisher.get("verified_via") == "GitHub event context+repository+default-ref+commit APIs",
        "publisher event API evidence is invalid",
    )


def _render_index(series: dict[str, Any], metadata: dict[str, Any], published_at: str) -> str:
    links = "\n".join(
        f'<li><a href="run-{number}/index.html">Bot match run {number}</a></li>'
        for number in range(1, RUN_COUNT + 1)
    )
    source_tag = html.escape(metadata["source_tag"])
    source_sha = html.escape(metadata["infrastructure_sha"])
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>KTP Lane B public bot-test reports</title>
<style>
body{{font:16px/1.5 system-ui,sans-serif;max-width:1000px;margin:2rem auto;padding:0 1rem;color:#172033}}
.notice{{border:2px solid #a05a00;background:#fff6df;padding:1rem;border-radius:.5rem}}
code{{overflow-wrap:anywhere}}a{{color:#0759b6}}
</style></head><body>
<h1>KTP Lane B five-match bot-test report</h1>
<div class="notice"><strong>Public synthetic bot test only.</strong> This site contains no production,
real-player, database, server-log, credential, or raw player-position data.</div>
<p>All five sanitized reports passed verification and had no blocking quality gates.</p>
<ul>{links}</ul>
<h2>Publication provenance</h2>
<ul>
<li>Source Actions run ID: <code>{metadata['source_run_id']}</code></li>
<li>Series tag: <code>{source_tag}</code></li>
<li>Infrastructure SHA: <code>{source_sha}</code></li>
<li>Published UTC: <code>{html.escape(published_at)}</code></li>
</ul>
<p><a href="series-summary.json">sanitized comparison data (JSON)</a> &middot;
<a href="publication-metadata.json">publication manifest (JSON)</a></p>
</body></html>
"""


def _render_run_report(run_number: int, report: dict[str, Any], timeline: dict[str, Any]) -> str:
    match = report["match"]
    player_rows = "\n".join(
        "<tr>"
        f"<td>{player['rank']}</td><td>{html.escape(player['alias'])}</td><td>{html.escape(player['team'])}</td>"
        f"<td>{player['impact_index']:.2f}</td><td>{player['kills']}/{player['deaths']}/{player['assists']}</td>"
        f"<td>{player['opponent_damage']:.0f}</td><td>{player['total_points']:.2f}</td>"
        f"<td>{player['combat_points']:.2f}</td><td>{player['objective_points']:.2f}</td>"
        f"<td>{player['position_points']:.2f}</td><td>{player['momentum_points']:.2f}</td>"
        "</tr>"
        for player in report["players"]
    )
    component_rows = "\n".join(
        f"<tr><td>{html.escape(key.replace('_', ' ').title())}</td><td>{value:.2f}</td></tr>"
        for key, value in report["component_totals"].items()
    )
    gate_rows = "\n".join(
        f"<tr><td>{html.escape(key.replace('_', ' ').title())}</td><td>{status}</td></tr>"
        for key, status in report["quality_gates"].items()
    )
    sample_bins = [
        row for index, row in enumerate(timeline["bins"])
        if index % 5 == 0 or index == len(timeline["bins"]) - 1
    ]
    timeline_rows = "\n".join(
        "<tr>"
        f"<td>{row['start_time']:.0f}-{row['end_time']:.0f}</td>"
        f"<td>{row['team_1_cumulative_points']:.2f}</td>"
        f"<td>{row['team_2_cumulative_points']:.2f}</td>"
        f"<td>{row['momentum']:.2f}</td></tr>"
        for row in sample_bins
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lane B bot match run {run_number}</title>
<style>
body{{font:15px/1.45 system-ui,sans-serif;max-width:1200px;margin:2rem auto;padding:0 1rem;color:#172033}}
.notice{{border:2px solid #a05a00;background:#fff6df;padding:1rem;border-radius:.5rem}}
table{{border-collapse:collapse;width:100%;margin:1rem 0}}th,td{{border:1px solid #ccd4dc;padding:.4rem;text-align:left}}
th{{background:#eef2f5}}code{{overflow-wrap:anywhere}}a{{color:#0759b6}}
</style></head><body>
<p><a href="../index.html">Back to five-run summary</a></p>
<h1>Lane B bot match run {run_number}</h1>
<div class="notice"><strong>Synthetic bots only.</strong> Source identities were removed and deterministically
replaced with Bot 01 through Bot 12. No source HTML, SVG, names, identifiers, or individual positions are present.</div>
<ul><li>Match: <code>{html.escape(match['match_id'])}</code></li>
<li>Map: <code>{html.escape(match['map_name'])}</code></li>
<li>Duration: {match['duration_seconds']:.2f} seconds</li><li>Verification: PASS</li></ul>
<h2>Aliased scoreboard</h2>
<table><thead><tr><th>Rank</th><th>Bot</th><th>Team</th><th>Rating</th><th>K/D/A</th><th>Damage</th>
<th>Total</th><th>Combat</th><th>Objectives</th><th>Position</th><th>Momentum</th></tr></thead>
<tbody>{player_rows}</tbody></table>
<h2>Component totals</h2><table><thead><tr><th>Component</th><th>Points</th></tr></thead><tbody>{component_rows}</tbody></table>
<h2>Quality gates</h2><table><thead><tr><th>Gate</th><th>Status</th></tr></thead><tbody>{gate_rows}</tbody></table>
<h2>Team-only timeline sample</h2><p>Every fifth validated 15-second bin plus the final bin is shown.</p>
<table><thead><tr><th>Seconds</th><th>Team 1 cumulative</th><th>Team 2 cumulative</th><th>Momentum</th></tr></thead>
<tbody>{timeline_rows}</tbody></table>
<p><a href="report.json">sanitized aliased report JSON</a> &middot; <a href="timeline.json">team-only timeline JSON</a></p>
</body></html>
"""


def _publication_file_records(output_root: Path) -> list[dict[str, Any]]:
    records = []
    for path in sorted(output_root.rglob("*")):
        if path.is_file() and path.name != "publication-metadata.json":
            records.append({
                "path": path.relative_to(output_root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            })
    return records


def _payload_manifest_sha256(records: list[dict[str, Any]]) -> str:
    canonical = json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _validate_links(output_root: Path) -> None:
    resolved_root = output_root.resolve()
    for html_path in output_root.rglob("*.html"):
        content = html_path.read_text(encoding="utf-8")
        for pattern in UNSAFE_HTML_PATTERNS:
            _require(not pattern.search(content), f"generated HTML contains active content: {html_path}")
        for target in re.findall(r"(?:href|src)=[\"']([^\"']+)[\"']", content, re.IGNORECASE):
            _require(not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", target), "external URL is forbidden")
            _require(not target.startswith(("//", "#")), "external or fragment-only link is forbidden")
            _require(not target.startswith(("/", "\\")), f"absolute local link is not allowed: {target}")
            candidate = PurePosixPath(target)
            _require(target == candidate.as_posix(), f"HTML link is not canonical: {target}")
            _require(all(part not in {"", "."} for part in candidate.parts), f"HTML link is invalid: {target}")
            resolved = html_path.parent.joinpath(*candidate.parts).resolve()
            try:
                resolved.relative_to(resolved_root)
            except ValueError as exc:
                raise PublicationError(f"public HTML link escapes the output root: {target}") from exc
            _require(resolved.is_file(), f"public HTML link target is missing: {html_path}: {target}")


def _validate_public_identity_contract(output_root: Path) -> None:
    expected_aliases = {f"Bot {number:02d}" for number in range(1, PLAYER_COUNT + 1)}
    for number in range(1, RUN_COUNT + 1):
        report = _load_json(output_root / f"run-{number}/report.json")
        players = report.get("players")
        _require(isinstance(players, list) and len(players) == PLAYER_COUNT, "public report roster changed")
        aliases: set[str] = set()
        team_counts = {"Team 1": 0, "Team 2": 0}
        for player in players:
            _require(isinstance(player, dict), "public player row is malformed")
            _require(set(player) == PUBLIC_PLAYER_FIELDS, "public player field allowlist changed")
            alias = str(player.get("alias") or "")
            _require(alias in expected_aliases, "public player alias is invalid")
            aliases.add(alias)
            team = str(player.get("team") or "")
            _require(team in team_counts, "public player team is invalid")
            team_counts[team] += 1
        _require(aliases == expected_aliases, "public report does not contain exactly Bot 01 through Bot 12")
        _require(team_counts == {"Team 1": 6, "Team 2": 6}, "public aliased roster is not 6v6")
        report_html = (output_root / f"run-{number}/index.html").read_text(encoding="utf-8")
        for alias in expected_aliases:
            _require(
                report_html.count(f"<td>{html.escape(alias)}</td>") == 1,
                f"generated report HTML does not contain exactly one scoreboard row for {alias}",
            )


def prepare_publication(
    *,
    source_root: Path,
    output_root: Path,
    metadata: dict[str, Any],
    published_at: str | None = None,
) -> dict[str, Any]:
    _validate_metadata(metadata)
    audit_source_tree(source_root)
    series = _load_json(source_root / "series-comparison.json")
    _require(series.get("run_count") == RUN_COUNT, "series comparison must contain exactly five runs")
    _require(series.get("all_reports_pass") is True, "not every report passed")
    _require(series.get("no_blocking_quality_gates") is True, "series has blocking quality gates")
    runs = series.get("runs")
    _require(isinstance(runs, list), "series run list is missing")
    _require(len(runs) == RUN_COUNT, "series must be run-1 through run-5 exactly")

    public_series_runs: list[dict[str, Any]] = []
    public_reports: list[dict[str, Any]] = []
    public_timelines: list[dict[str, Any]] = []
    bundle_commits: dict[str, str] | None = None
    for number, row in enumerate(runs, 1):
        _require(isinstance(row, dict), f"series run {number} is invalid")
        public_series_run = _validate_series_run(row, number=number)
        run_root = source_root / f"run-{number}"
        players, bots = _validate_bot_summary(
            run_root / "lane-b-summary.md",
            match_id=public_series_run["match_id"],
            map_name=public_series_run["map_name"],
        )
        _require(players == public_series_run["players"] and bots == PLAYER_COUNT, "summary roster disagrees")
        current_commits = _validate_provenance(run_root / "bundle-provenance.md", metadata)
        if bundle_commits is None:
            bundle_commits = current_commits
        else:
            _require(current_commits == bundle_commits, "four-repository provenance differs across series runs")
        public_report, public_timeline = _verify_report(
            run_root / "match-report", series_run=public_series_run
        )
        _require(len(public_report["players"]) == players, "report roster disagrees with Lane B summary")
        public_series_runs.append(public_series_run)
        public_reports.append(public_report)
        public_timelines.append(public_timeline)

    _require(bundle_commits is not None, "bundle provenance is missing")
    _require(
        len({row["match_id"] for row in public_series_runs}) == RUN_COUNT,
        "series contains duplicate match ids",
    )

    if output_root.exists():
        _require(output_root.is_dir(), "Pages output path is not a directory")
        _require(not any(output_root.iterdir()), "Pages output directory must be empty")
    else:
        output_root.mkdir(parents=True)

    timestamp = published_at or datetime.now(timezone.utc).isoformat()
    try:
        parsed_timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PublicationError("publication timestamp is not ISO-8601") from exc
    _require(parsed_timestamp.tzinfo is not None, "publication timestamp must include a timezone")
    timestamp = parsed_timestamp.astimezone(timezone.utc).isoformat()
    public_series = {
        "schema_version": 1,
        "scope": "PUBLIC_SYNTHETIC_BOT_TEST_ONLY_ALIASED",
        "run_count": RUN_COUNT,
        "all_reports_pass": True,
        "no_blocking_quality_gates": True,
        "bundle_commits": bundle_commits,
        "runs": public_series_runs,
    }
    (output_root / "index.html").write_text(_render_index(public_series, metadata, timestamp), encoding="utf-8")
    _write_json(output_root / "series-summary.json", public_series)
    for number, (report, timeline) in enumerate(zip(public_reports, public_timelines), 1):
        run_output = output_root / f"run-{number}"
        run_output.mkdir(parents=True)
        (run_output / "index.html").write_text(
            _render_run_report(number, report, timeline), encoding="utf-8"
        )
        _write_json(run_output / "report.json", report)
        _write_json(run_output / "timeline.json", timeline)

    public_source = {
        "repository": metadata["repository"],
        "source_run_id": metadata["source_run_id"],
        "source_tag": metadata["source_tag"],
        "infrastructure_sha": metadata["infrastructure_sha"],
        "run_attempt": metadata["run_attempt"],
        "artifact_id": metadata["artifact_id"],
        "artifact_digest": metadata["artifact_digest"],
        "artifact_size_bytes": metadata["artifact_size_bytes"],
        "preprod_ancestry": metadata["preprod_ancestry"],
        "publisher_event": metadata["publisher_event"],
        "publication_approval": metadata["publication_approval"],
        "bundle_commits": bundle_commits,
    }
    expected_paths = {"index.html", "series-summary.json", "publication-metadata.json"}
    for number in range(1, RUN_COUNT + 1):
        expected_paths.update({
            f"run-{number}/index.html",
            f"run-{number}/report.json",
            f"run-{number}/timeline.json",
        })

    public_files = _publication_file_records(output_root)
    publication = {
        "schema_version": 1,
        "scope": "PUBLIC_SYNTHETIC_BOT_TEST_ONLY",
        "notice": "No production, real-player, database, log, credential, or raw player-position data.",
        "published_at": timestamp,
        "source": public_source,
        "run_count": RUN_COUNT,
        "all_reports_pass": True,
        "no_blocking_quality_gates": True,
        "runs": [
            {"run": row["run"], "match_id": row["match_id"], "verification": "PASS"}
            for row in public_series_runs
        ],
        "public_files": public_files,
        "payload_manifest_sha256": _payload_manifest_sha256(public_files),
        "deployed_paths": sorted(expected_paths),
        "validation": {
            "result": "PASS",
            "public_file_count": len(expected_paths),
            "hashed_non_metadata_file_count": len(public_files),
            "identity_contract": "PASS",
            "link_validation": "PASS",
            "privacy_scan": "PASS",
        },
        "source_data_policy": "All public HTML and JSON were regenerated; no source HTML, SVG, names, or ids copied.",
    }
    metadata_path = output_root / "publication-metadata.json"
    metadata_path.write_text(json.dumps(publication, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    actual_paths = {
        path.relative_to(output_root).as_posix() for path in output_root.rglob("*") if path.is_file()
    }
    _require(actual_paths == expected_paths, "generated Pages payload differs from the public allowlist")
    for path in output_root.rglob("*"):
        if path.is_file():
            _validate_public_text(path)
    _validate_links(output_root)
    _validate_public_identity_contract(output_root)
    return publication


def _token() -> str:
    token = os.environ.get("GITHUB_TOKEN", "")
    _require(bool(token), "GITHUB_TOKEN is required")
    return token


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _append_github_output(path: Path, metadata: dict[str, Any]) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"artifact_id={metadata['artifact_id']}\n")
        handle.write(f"artifact_digest={metadata['artifact_digest']}\n")
        handle.write(f"source_run_id={metadata['source_run_id']}\n")


def _validate_summary_publication(publication: dict[str, Any]) -> dict[str, Any]:
    _require(publication.get("schema_version") == 1, "summary publication schema is invalid")
    _require(
        publication.get("scope") == "PUBLIC_SYNTHETIC_BOT_TEST_ONLY",
        "summary publication scope is invalid",
    )
    _require(publication.get("run_count") == RUN_COUNT, "summary publication run count is invalid")
    _require(publication.get("all_reports_pass") is True, "summary publication reports did not all pass")
    _require(
        publication.get("no_blocking_quality_gates") is True,
        "summary publication has a blocking quality gate",
    )
    source = publication.get("source")
    _require(isinstance(source, dict), "summary publication source is missing")
    _require(source.get("repository") == EXPECTED_REPOSITORY, "summary source repository is invalid")
    source_run_id = parse_run_id(str(source.get("source_run_id") or ""))
    source_tag = _series_tag(source.get("source_tag"), label="summary source tag")
    source_sha = str(source.get("infrastructure_sha") or "")
    _require(bool(re.fullmatch(r"[0-9a-f]{40}", source_sha)), "summary source SHA is invalid")
    artifact_id = source.get("artifact_id")
    _require(isinstance(artifact_id, int) and artifact_id > 0, "summary artifact id is invalid")
    artifact_digest = str(source.get("artifact_digest") or "")
    _require(bool(re.fullmatch(r"sha256:[0-9a-f]{64}", artifact_digest)), "summary artifact digest is invalid")
    ancestry = source.get("preprod_ancestry")
    _require(isinstance(ancestry, dict), "summary preprod ancestry is missing")
    _require(ancestry.get("source_sha") == source_sha, "summary ancestry source SHA disagrees")
    preprod_sha = str(ancestry.get("preprod_sha") or "")
    _require(bool(re.fullmatch(r"[0-9a-f]{40}", preprod_sha)), "summary preprod SHA is invalid")
    _require(ancestry.get("merge_base_sha") == source_sha, "summary source is not verified preprod ancestry")
    _require(ancestry.get("compare_status") in {"ahead", "identical"}, "summary preprod ancestry is invalid")
    bundle = source.get("bundle_commits")
    _require(isinstance(bundle, dict) and set(bundle) == set(EXPECTED_BUNDLE_REPOSITORIES), "summary bundle is invalid")
    for component, sha in bundle.items():
        _require(bool(re.fullmatch(r"[0-9a-f]{40}", str(sha))), f"summary {component} SHA is invalid")
    _require(bundle["infrastructure"] == source_sha, "summary Infrastructure SHA disagrees")
    approval = source.get("publication_approval")
    _require(isinstance(approval, dict), "summary approval evidence is missing")
    default_branch = str(approval.get("default_branch") or "")
    _require(
        bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,254}", default_branch))
        and ".." not in default_branch
        and not default_branch.endswith(("/", ".lock")),
        "summary default branch is invalid",
    )
    _require(
        bool(re.fullmatch(r"[0-9a-f]{40}", str(approval.get("default_branch_sha") or ""))),
        "summary default-branch SHA is invalid",
    )
    _require(
        isinstance(approval.get("required_reviewer_count"), int)
        and approval["required_reviewer_count"] >= 1
        and approval.get("custom_branch_policies") is True
        and approval.get("protected_branches") is False
        and approval.get("deployment_policy_type") == "branch"
        and approval.get("deployment_policy_name") == default_branch
        and approval.get("prevent_self_review") is True,
        "summary approval policy is invalid",
    )
    publisher = source.get("publisher_event")
    _require(isinstance(publisher, dict), "summary publisher event evidence is missing")
    _require(
        set(publisher) == {
            "event_name",
            "event_action",
            "default_branch",
            "publisher_ref",
            "publisher_sha",
            "verified_via",
        },
        "summary publisher event evidence schema is invalid",
    )
    expected_actions = {"repository_dispatch": "publish-lane-b-pages", "workflow_run": "completed"}
    publisher_event_name = str(publisher.get("event_name") or "")
    _require(publisher_event_name in expected_actions, "summary publisher event type is forbidden")
    _require(
        publisher.get("event_action") == expected_actions[publisher_event_name]
        and publisher.get("default_branch") == default_branch
        and publisher.get("publisher_ref") == f"refs/heads/{default_branch}"
        and publisher.get("publisher_sha") == approval["default_branch_sha"],
        "summary publisher event is not the verified default-branch publisher",
    )
    _require(
        publisher.get("verified_via") == "GitHub event context+repository+default-ref+commit APIs",
        "summary publisher event API evidence is invalid",
    )
    runs = publication.get("runs")
    _require(isinstance(runs, list) and len(runs) == RUN_COUNT, "summary run list is invalid")
    public_runs = []
    for number, row in enumerate(runs, 1):
        _require(isinstance(row, dict) and row.get("run") == number, "summary run index is invalid")
        _require(row.get("verification") == "PASS", "summary run did not pass")
        public_runs.append({
            "run": number,
            "match_id": _safe_match_id(row.get("match_id"), label="summary match id"),
            "verification": "PASS",
        })
    records = publication.get("public_files")
    _require(isinstance(records, list) and len(records) == 17, "summary public file manifest is invalid")
    for record in records:
        _require(isinstance(record, dict), "summary public file record is malformed")
        _safe_relative_path(str(record.get("path") or ""), label="summary public file")
        _require(isinstance(record.get("bytes"), int) and record["bytes"] >= 0, "summary public file size is invalid")
        _require(bool(re.fullmatch(r"[0-9a-f]{64}", str(record.get("sha256") or ""))), "summary file hash is invalid")
    payload_hash = str(publication.get("payload_manifest_sha256") or "")
    _require(payload_hash == _payload_manifest_sha256(records), "summary payload manifest hash disagrees")
    validation = publication.get("validation")
    _require(
        isinstance(validation, dict)
        and validation.get("result") == "PASS"
        and validation.get("public_file_count") == 18
        and validation.get("hashed_non_metadata_file_count") == 17
        and validation.get("identity_contract") == "PASS"
        and validation.get("link_validation") == "PASS"
        and validation.get("privacy_scan") == "PASS",
        "summary validation result is incomplete",
    )
    return {
        "source_run_id": source_run_id,
        "source_run_url": f"https://github.com/{EXPECTED_REPOSITORY}/actions/runs/{source_run_id}",
        "source_tag": source_tag,
        "source_sha": source_sha,
        "artifact_id": artifact_id,
        "artifact_digest": artifact_digest,
        "preprod_sha": preprod_sha,
        "compare_status": ancestry["compare_status"],
        "bundle_commits": bundle,
        "runs": public_runs,
        "payload_manifest_sha256": payload_hash,
        "public_file_count": validation["public_file_count"],
        "approval": approval,
        "publisher": publisher,
    }


def write_step_summary(publication: dict[str, Any], output_path: Path) -> None:
    data = _validate_summary_publication(publication)
    _require(not output_path.is_symlink(), "step-summary output must not be a symlink")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    bundle_rows = "\n".join(
        f"| {component} | `{EXPECTED_BUNDLE_REPOSITORIES[component]}` | `{data['bundle_commits'][component]}` |"
        for component in ("infrastructure", "matchhandler", "amxx", "hlstatsx")
    )
    run_rows = "\n".join(
        f"| {row['run']} | `{row['match_id']}` | {row['verification']} |" for row in data["runs"]
    )
    approval = data["approval"]
    publisher = data["publisher"]
    markdown = f"""## Lane B public bot-test publication: PASS

Synthetic bot tests only. No production or real-player data is included.

- Source Actions run: [{data['source_run_id']}]({data['source_run_url']})
- Publisher event: `{publisher['event_name']}` / `{publisher['event_action']}` on `{publisher['publisher_ref']}` at `{publisher['publisher_sha']}`
- Series tag: `{data['source_tag']}`
- Tested Infrastructure SHA: `{data['source_sha']}`
- Immutable comparison artifact: id `{data['artifact_id']}`, digest `{data['artifact_digest']}`
- Verified preprod ancestry: `{data['compare_status']}` at preprod `{data['preprod_sha']}`
- Pages deployment policy: exact default branch `{approval['default_branch']}` only
- Required reviewers: {approval['required_reviewer_count']}; self-review prevention: enabled and API-verified

### Exact bundle commits

| Component | Repository | Commit |
|---|---|---|
{bundle_rows}

### Five aliased bot matches

| Run | Match ID | Validation |
|---:|---|---|
{run_rows}

### Prepared payload

- Validation result: **PASS**
- Output files: `{data['public_file_count']}`
- Non-self-referential payload manifest SHA-256: `{data['payload_manifest_sha256']}`

Approve the protected `github-pages` environment deployment only after confirming this bot-only provenance.
"""
    with output_path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(markdown)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate-run", help="validate source run via GitHub API")
    validate.add_argument("--api-url", default=os.environ.get("GITHUB_API_URL", "https://api.github.com"))
    validate.add_argument("--repository", required=True)
    validate.add_argument("--run-id", required=True)
    validate.add_argument("--publisher-event-name", required=True)
    validate.add_argument("--publisher-event-action", required=True)
    validate.add_argument("--publisher-ref", required=True)
    validate.add_argument("--publisher-sha", required=True)
    validate.add_argument("--output", required=True, type=Path)
    validate.add_argument("--expected-metadata", type=Path)
    validate.add_argument("--github-output", type=Path)

    pages = subparsers.add_parser("validate-pages", help="require Pages to use GitHub Actions")
    pages.add_argument("--api-url", default=os.environ.get("GITHUB_API_URL", "https://api.github.com"))
    pages.add_argument("--repository", required=True)

    prepare = subparsers.add_parser("prepare", help="validate and build the public Pages directory")
    prepare.add_argument("--source", required=True, type=Path)
    prepare.add_argument("--output", required=True, type=Path)
    prepare.add_argument("--source-metadata", required=True, type=Path)
    prepare.add_argument("--published-at")

    summary = subparsers.add_parser("write-summary", help="append a sanitized GitHub Actions step summary")
    summary.add_argument("--publication", required=True, type=Path)
    summary.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "validate-run":
            run_id = parse_run_id(args.run_id)
            metadata = fetch_and_validate_run(
                api_url=args.api_url,
                repository=args.repository,
                run_id=run_id,
                token=_token(),
                publisher_event_name=args.publisher_event_name,
                publisher_event_action=args.publisher_event_action,
                publisher_ref=args.publisher_ref,
                publisher_sha=args.publisher_sha,
            )
            if args.expected_metadata:
                expected = _load_json(args.expected_metadata)
                _require(metadata == expected, "source run/artifact metadata changed after download")
            _write_json(args.output, metadata)
            if args.github_output:
                _append_github_output(args.github_output, metadata)
            print(f"Validated Lane B source run {run_id} and {metadata['artifact_name']}")
        elif args.command == "validate-pages":
            fetch_and_validate_pages_settings(
                api_url=args.api_url,
                repository=args.repository,
                token=_token(),
            )
            print("GitHub Pages is enabled with GitHub Actions as its source")
        elif args.command == "prepare":
            metadata = _load_json(args.source_metadata)
            publication = prepare_publication(
                source_root=args.source,
                output_root=args.output,
                metadata=metadata,
                published_at=args.published_at,
            )
            print(
                f"Prepared {len(publication['public_files']) + 1} bot-only Pages files "
                f"from run {publication['source']['source_run_id']}"
            )
        else:
            publication = _load_json(args.publication)
            write_step_summary(publication, args.output)
            print(f"Appended sanitized Lane B publication summary to {args.output}")
    except PublicationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
