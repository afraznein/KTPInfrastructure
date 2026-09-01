from __future__ import annotations

from scripts import match_readiness
from scripts import verify_bot_match_telemetry


def test_bot_report_requires_test_boundary_roster_and_requested_metric():
    checks = [
        {"code": code, "level": "PASS"}
        for requirements in match_readiness.METRIC_REQUIREMENTS.values()
        for code in requirements
    ] + [
        {"code": "roster_integrity", "level": "PASS"},
        {"code": "bot_containment", "level": "PASS"},
    ]
    report = {
        "match_id": "123-KTP1-TEST",
        "checks": checks,
        "metric_eligibility": match_readiness.build_metric_eligibility(checks),
    }
    assert verify_bot_match_telemetry.verify_report(
        report, {"positional_impact": "available"}
    ) == []

    report["match_id"] = "123-KTP1"
    assert "match_id must end in -TEST" in verify_bot_match_telemetry.verify_report(report, {})


def test_bot_report_rejects_unmet_metric_expectation():
    report = {
        "match_id": "123-KTP1-TEST",
        "checks": [
            {"code": "closed_match", "level": "PASS"},
            {"code": "roster_integrity", "level": "PASS"},
            {"code": "bot_containment", "level": "PASS"},
        ],
        "metric_eligibility": {
            "contract_version": match_readiness.METRIC_ELIGIBILITY_VERSION,
            "metrics": {"combat_context": {"status": "partial"}},
        },
    }
    assert verify_bot_match_telemetry.verify_report(
        report, {"combat_context": "available"}
    ) == ["combat_context must be available (observed partial)"]
