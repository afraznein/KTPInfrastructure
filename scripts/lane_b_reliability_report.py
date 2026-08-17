#!/usr/bin/env python3
"""Aggregate repeated Lane B JSON reports into a promotion-readiness report."""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path


STATS = (
    ("kills", "frags"),
    ("assist", "assist"),
    ("cap_break", "cap_break"),
    ("suicide", "suicides"),
    ("damage", None),
    ("flag_capture", "flag_captures"),
    ("flag_position", "flag_positions"),
    ("position_sample", "position_samples"),
)

ALLOWED_GAPS = (
    "statsme:",
    "1 known all-bot SQL artifact(s):",
)


def _verdict(report: dict, code: str) -> dict:
    return next((item for item in report.get("carried", [])
                 if item.get("code") == code), {})


def _scenario(report: dict, name: str) -> dict:
    return next((item for item in report.get("break_scenarios", [])
                 if item.get("name") == name), {})


def judge(report: dict) -> list[str]:
    problems = list(report.get("failures") or [])
    problems += [gap for gap in report.get("coverage_gaps") or []
                 if not gap.startswith(ALLOWED_GAPS)]

    required = (
        "assist", "cap_break", "suicide", "headshot", "damage_ledger",
        "flag_captures", "flag_positions", "position_samples",
        "capture_buffer_drops", "projectile_killer_not_assister",
        "match_players", "match_frags_tagged", "match_half_set",
        "match_context_cleared", "match_stats_reconciled", "kill_switch",
    )
    for code in required:
        verdict = _verdict(report, code)
        if verdict.get("status") != "ok":
            problems.append(
                f"{code}: {verdict.get('status', 'missing')} — "
                f"{verdict.get('detail', 'no verdict')}")

    walkoff = _scenario(report, "negative_voluntary_walkoff")
    if walkoff.get("status") != "ok":
        problems.append(
            "negative_voluntary_walkoff: "
            f"{walkoff.get('status', 'missing')} — "
            f"{walkoff.get('detail', 'no verdict')}")

    if report.get("sql_errors"):
        problems.append(f"{len(report['sql_errors'])} real SQL error(s)")
    if (report.get("rows") or {}).get("match_players") != 16:
        problems.append(
            f"match roster has {(report.get('rows') or {}).get('match_players')} rows, expected 16")
    return problems


def load_reports(root: Path) -> list[tuple[Path, dict]]:
    paths = sorted(root.rglob("lane-b-e2e.json"))
    return [(path, json.loads(path.read_text(encoding="utf-8"))) for path in paths]


def render(reports: list[tuple[Path, dict]], *, expected: int) -> str:
    rows = []
    all_problems: list[tuple[int, str]] = []
    for index, (path, report) in enumerate(reports, 1):
        problems = judge(report)
        all_problems.extend((index, problem) for problem in problems)
        emitted = report.get("emitted") or {}
        stored = report.get("rows") or {}
        rows.append({
            "run": index,
            "source": str(path),
            "status": "PASS" if not problems else "FAIL",
            "kills": emitted.get("kills", 0),
            "assists": emitted.get("assist", 0),
            "breaks": emitted.get("cap_break", 0),
            "damage": emitted.get("damage", 0),
            "captures": emitted.get("flag_capture", 0),
            "positions": emitted.get("position_sample", 0),
            "roster": stored.get("match_players", 0),
            "walkoff": _scenario(report, "negative_voluntary_walkoff").get("status", "missing"),
            "context": _verdict(report, "match_context_cleared").get("status", "missing"),
        })

    count_ok = len(reports) == expected
    ready = count_ok and not all_problems
    out = [
        "# Lane B preprod reliability series",
        "",
        f"**Promotion verdict: {'READY' if ready else 'NOT READY'}**",
        "",
        f"Reports found: {len(reports)}; expected: {expected}.",
        "",
        "| Run | Result | Kills | Assists | Breaks | Damage | Captures | Position samples | Roster | Walkoff | Context clear |",
        "|---:|---|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for row in rows:
        out.append(
            f"| {row['run']} | {row['status']} | {row['kills']} | {row['assists']} "
            f"| {row['breaks']} | {row['damage']} | {row['captures']} "
            f"| {row['positions']} | {row['roster']} | {row['walkoff']} "
            f"| {row['context']} |")

    out += ["", "## Cross-run ranges", "",
            "| Metric | Minimum | Maximum | Mean |", "|---|---:|---:|---:|"]
    for key, label in (("kills", "Kills"), ("assists", "Assists"),
                       ("breaks", "Cap breaks"), ("damage", "Damage events"),
                       ("captures", "Flag captures"),
                       ("positions", "Position samples")):
        values = [row[key] for row in rows]
        if values:
            out.append(f"| {label} | {min(values)} | {max(values)} | "
                       f"{statistics.mean(values):.1f} |")

    out += ["", "## Readiness gates", ""]
    if not count_ok:
        out.append(f"- FAIL: found {len(reports)} reports; expected {expected}.")
    if all_problems:
        for index, problem in all_problems:
            out.append(f"- Run {index}: {problem}")
    if count_ok and not all_problems:
        out.append("- PASS: every required assertion passed in every run.")
        out.append("- PASS: all five 16-player match rosters were complete.")
        out.append("- PASS: voluntary walkoff and post-match context clearing passed in every run.")
        out.append("- PASS: no real SQL errors or capture-buffer drops were reported.")

    out += ["", "## Deferred", "",
            "- Statsme remains human-client-only because `dod_stats_flush` deliberately skips bots."]
    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--expected", type=int, default=5)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()

    reports = load_reports(args.root)
    body = render(reports, expected=args.expected)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(body, encoding="utf-8")
    print(body, end="")
    return 0 if len(reports) == args.expected and all(not judge(r) for _, r in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
