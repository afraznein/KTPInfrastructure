#!/usr/bin/env python3
"""Verify a captured local bot-match fixture against the telemetry contract.

This consumes an exported SQL fixture after the test match has ended. It does
not start Docker, contact a server, or treat the local bot stack as production
evidence.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import match_readiness


def verify_report(report: dict[str, Any], requirements: dict[str, str]) -> list[str]:
    """Return contract violations for one completed local bot-match report."""
    errors: list[str] = []
    if not str(report.get("match_id", "")).endswith("-TEST"):
        errors.append("match_id must end in -TEST")
    levels = {item["code"]: item["level"] for item in report.get("checks", [])}
    for code in ("closed_match", "roster_integrity", "bot_containment"):
        if levels.get(code) != "PASS":
            errors.append(f"{code} must be PASS (observed {levels.get(code, 'MISSING')})")
    eligibility = report.get("metric_eligibility", {})
    if eligibility.get("contract_version") != match_readiness.METRIC_ELIGIBILITY_VERSION:
        errors.append("metric eligibility contract version is missing or unsupported")
        return errors
    metrics = eligibility.get("metrics", {})
    for metric, expected in requirements.items():
        actual = metrics.get(metric, {}).get("status")
        if actual != expected:
            errors.append(f"{metric} must be {expected} (observed {actual or 'MISSING'})")
    return errors


def parse_requirement(value: str) -> tuple[str, str]:
    metric, separator, status = value.partition("=")
    if not separator or status not in {"available", "partial", "unavailable"}:
        raise argparse.ArgumentTypeError("requirements use metric=available|partial|unavailable")
    return metric, status


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("--match-id")
    parser.add_argument("--require", action="append", type=parse_requirement, default=[], metavar="METRIC=STATUS")
    args = parser.parse_args(argv)
    try:
        report = match_readiness.validate_fixture(args.fixture, args.match_id)
    except (FileNotFoundError, OSError, ValueError) as exc:
        print(f"bot-match-telemetry: {exc}", file=sys.stderr)
        return 2
    errors = verify_report(report, dict(args.require))
    if errors:
        print("Bot-match telemetry: FAIL")
        for error in errors:
            print(f"  - {error}")
        return 1
    statuses = {
        metric: value["status"]
        for metric, value in report["metric_eligibility"]["metrics"].items()
    }
    print("Bot-match telemetry: PASS")
    print(json.dumps({"match_id": report["match_id"], "metric_eligibility": statuses}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
