from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/publish-lane-b-pages.yml"
HELPER = ROOT / "scripts/prepare_lane_b_pages.py"
DOC = ROOT / "docs/LANE_B_PUBLIC_PAGES.md"


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_workflow_has_default_branch_repository_dispatch_and_exact_lane_b_completion_triggers() -> None:
    workflow = _text()
    assert "workflow_dispatch" not in workflow
    assert "repository_dispatch:" in workflow
    assert "types: [publish-lane-b-pages]" in workflow
    assert "workflow_run:" in workflow
    assert 'workflows: ["Lane B Stats E2E"]' in workflow
    assert "types: [completed]" in workflow
    assert "github.event_name == 'repository_dispatch'" in workflow
    assert "github.event.action == 'publish-lane-b-pages'" in workflow
    assert "github.event.client_payload.source_run_id" in workflow
    assert "inputs.source_run_id" not in workflow
    assert '--run-id "$SOURCE_RUN_ID"' in workflow
    assert "source_run_id must contain digits only" in HELPER.read_text(encoding="utf-8")


def test_publisher_event_context_is_passed_to_both_source_validations() -> None:
    workflow = _text()
    for argument in (
        '--publisher-event-name "$PUBLISHER_EVENT_NAME"',
        '--publisher-event-action "$PUBLISHER_EVENT_ACTION"',
        '--publisher-ref "$PUBLISHER_REF"',
        '--publisher-sha "$PUBLISHER_SHA"',
    ):
        assert workflow.count(argument) == 2
    assert "PUBLISHER_EVENT_NAME: ${{ github.event_name }}" in workflow
    assert "PUBLISHER_EVENT_ACTION: ${{ github.event.action }}" in workflow
    assert "PUBLISHER_REF: ${{ github.ref }}" in workflow
    assert "PUBLISHER_SHA: ${{ github.sha }}" in workflow


def test_automatic_publication_is_same_repo_series_only_and_opt_in() -> None:
    workflow = _text()
    for guard in (
        "github.event.workflow_run.conclusion == 'success'",
        "github.event.workflow_run.event == 'push'",
        "github.event.workflow_run.head_repository.full_name == github.repository",
        "startsWith(github.event.workflow_run.head_branch, 'lane-b-preprod-series-')",
        "vars.KTP_LANE_B_PAGES_ENABLED == 'true'",
    ):
        assert guard in workflow
    assert "cancel-in-progress: false" in workflow


def test_only_the_exact_cross_run_comparison_artifact_is_downloaded() -> None:
    workflow = _text()
    assert "artifact-ids: ${{ steps.source.outputs.artifact_id }}" in workflow
    assert "name: lane-b-series-comparison-" not in workflow
    assert "repository: ${{ github.repository }}" in workflow
    assert "run-id: ${{ env.SOURCE_RUN_ID }}" in workflow
    assert "github-token: ${{ github.token }}" in workflow
    assert "lane-b-reports-" not in workflow
    assert workflow.count("actions/download-artifact@") == 1
    assert workflow.count("prepare_lane_b_pages.py validate-run") == 2
    assert "--expected-metadata build/lane-b-pages-source.json" in workflow
    assert "source_artifact_id: ${{ steps.source.outputs.artifact_id }}" in workflow
    assert "source_artifact_digest: ${{ steps.source.outputs.artifact_digest }}" in workflow


def test_prepare_and_deploy_permissions_are_split() -> None:
    workflow = _text()
    prepare = workflow[workflow.index("  prepare:"):workflow.index("  deploy:")]
    deploy = workflow[workflow.index("  deploy:"):]
    assert "actions: read" in prepare
    assert "contents: read" in prepare
    assert "pages:" not in prepare
    assert "id-token:" not in prepare
    assert "needs: prepare" in deploy
    assert "contents: read" in deploy
    assert "pages: write" in deploy
    assert "id-token: write" in deploy
    assert "name: github-pages" in deploy
    assert "url: ${{ steps.deployment.outputs.page_url }}" in deploy
    assert "path: build/lane-b-pages-public" in prepare
    artifact_name = "github-pages-${{ github.run_id }}-${{ github.run_attempt }}"
    assert f"PAGES_ARTIFACT_NAME: {artifact_name}" in prepare
    assert "pages_artifact_name: ${{ steps.pages_artifact.outputs.name }}" in prepare
    assert "name: ${{ steps.pages_artifact.outputs.name }}" in prepare
    assert "artifact_name: ${{ needs.prepare.outputs.pages_artifact_name }}" in deploy
    assert f"artifact_name: {artifact_name}" not in deploy
    assert "retention-days: 14" in prepare
    assert ".nojekyll" not in workflow


def test_every_action_is_pinned_to_a_full_reviewed_commit() -> None:
    workflow = _text()
    uses = re.findall(r"^\s*uses:\s*([^\s]+)\s*$", workflow, re.MULTILINE)
    assert uses
    assert all(re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+@[0-9a-f]{40}", item) for item in uses)
    assert set(item.split("@")[0] for item in uses) == {
        "actions/checkout",
        "actions/download-artifact",
        "actions/upload-pages-artifact",
        "actions/deploy-pages",
    }
    for release in (
        "# actions/checkout v7.0.1",
        "# actions/download-artifact v8.0.1",
        "# actions/upload-pages-artifact v5.0.0",
        "# actions/deploy-pages v5.0.0",
    ):
        assert release in workflow


def test_workflow_has_no_fleet_database_or_broad_secret_access() -> None:
    workflow = _text()
    assert "secrets." not in workflow
    assert "packages:" not in workflow
    for token in ("KTP_TIER2_", "SSH_HOST", "SSH_KEY", "DB_PASSWORD", "MYSQL_PASSWORD"):
        assert token not in workflow
    assert "PUBLIC_SYNTHETIC_BOT_TEST_ONLY" not in workflow  # scope is enforced by the helper
    assert "synthetic" in workflow.lower()
    assert "bot" in workflow.lower()


def test_helper_enforces_preprod_ancestry_and_required_pages_reviewer() -> None:
    helper = HELPER.read_text(encoding="utf-8")
    for api_path in (
        "/git/ref/heads/preprod",
        "/branches/preprod",
        "/commits/{source_sha}",
        "/commits/{preprod_sha}",
        "/compare/{source_sha}...{preprod_sha}",
        "/environments/github-pages",
        "/environments/github-pages/deployment-branch-policies?per_page=100",
    ):
        assert api_path in helper
    assert 'comparison.get("status") in {"ahead", "identical"}' in helper
    assert 'rule.get("type") == "required_reviewers"' in helper
    assert "reviewer_count >= 1" in helper
    assert 'policy.get("type") == "branch"' in helper
    assert 'policy.get("name") == default_branch' in helper
    assert 'deployment.get("protected_branches") is False' in helper
    assert 'deployment.get("custom_branch_policies") is True' in helper
    assert 'rule.get("prevent_self_review") is True' in helper
    assert 'event_ref == expected_ref' in helper
    assert 'event_sha == default_sha' in helper


def test_workflow_writes_only_the_trusted_sanitized_step_summary() -> None:
    workflow = _text()
    assert "prepare_lane_b_pages.py write-summary" in workflow
    assert "--publication build/lane-b-pages-public/publication-metadata.json" in workflow
    assert '--output "$GITHUB_STEP_SUMMARY"' in workflow
    assert "lane-b-summary.md" not in workflow
    assert "report.json" not in workflow


def test_workflow_and_docs_keep_publication_bot_only_and_approval_gated() -> None:
    combined = _text() + "\n" + DOC.read_text(encoding="utf-8")
    assert "PUBLIC_SYNTHETIC_BOT_TEST_ONLY" in HELPER.read_text(encoding="utf-8")
    assert "Production and real-player" in combined
    assert "mandatory" in combined.lower()
    assert "required reviewer" in combined.lower()
    assert "default-branch-only" in combined.lower()
    assert "prevent self-review" in combined.lower()
    assert "rerun failed jobs" in combined.lower()
    assert "full rerun" in combined.lower()
    assert "latest-wins" in combined.lower()
    assert "30-day" in combined
    assert "gh api -X POST repos/afraznein/KTPInfrastructure/dispatches" in combined
    assert "client_payload[source_run_id]=32866057356" in combined
    assert "HTTP 204" in combined
