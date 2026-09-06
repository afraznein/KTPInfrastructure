"""The Lane B run emits the private analytics report as advisory artifact
content: generated after the shareable v5 bundle, never able to fail the run.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / "scripts/lane_b_e2e.py").read_text(encoding="utf-8")


def test_private_analytics_report_is_emitted_into_the_artifact():
    assert 'private_dir = args.match_report_dir.parent / "private-analytics"' in SOURCE
    assert "build_private_analytics_report(" in SOURCE
    assert "render_private_analytics_markdown(private_report)" in SOURCE
    # Generated after the shareable v5 bundle so a v5 failure is already
    # recorded before the advisory block runs.
    assert SOURCE.index('failures.append(f"v5_match_report: {detail}")') < (
        SOURCE.index("build_private_analytics_report(")
    )


def test_private_analytics_failure_is_advisory_not_fatal():
    block = SOURCE[SOURCE.index("# Private shadow analytics"):
                   SOURCE.index('if args.database_dump is not None:')]
    assert '"status": "FAIL"' in block
    # No failures.append anywhere in the advisory block: a shadow report
    # must never turn a green run red.
    assert "failures.append" not in block
