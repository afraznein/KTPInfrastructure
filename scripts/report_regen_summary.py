"""Count what a report-regeneration run did, from its log, and print nothing else.

The workflow's log and job summary are public, and the pipeline's own output
names match ids and players. So the full output stays in a log on the box and
only these counts leave it: no line of the input is ever echoed.

  python3 scripts/report_regen_summary.py --label "dry run" < segment.log
"""
from __future__ import annotations

import argparse
import re
import sys

PATTERNS = {
    "pending matches": re.compile(r"^pending: (\d+) matches"),
    "would build (dry run)": re.compile(r"^dry run: would build (\d+) report"),
    "excluded by match_type": re.compile(r"^excluded by match_type filter: (\d+)"),
    "reports to sync": re.compile(r"^reports to sync: (\d+)"),
}
COUNTED = {
    "reports persisted, publishable": re.compile(r"^  \S+: persisted, publishable=True$"),
    "reports persisted, held (not publishable)": re.compile(r"^  \S+: persisted, publishable=False$"),
    "report builds FAILED": re.compile(r"^  \S+: FAILED "),
    "out-of-scope explicit ids (held back)": re.compile(r"^WARNING: "),
    "aggregates rewritten": re.compile(r"^  \S+: wrote revision \d+"),
    "aggregates unchanged": re.compile(r"^  \S+: unchanged \(revision"),
    "reports synced": re.compile(r"^  synced (?!aggregate )\S+ v\d+ r\d+$"),
    "aggregates synced": re.compile(r"^  synced aggregate "),
    "reports that would sync (dry run)": re.compile(r"^  DRY (?!aggregate )\S+ v\d+ r\d+$"),
    "aggregates that would sync (dry run)": re.compile(r"^  DRY aggregate "),
}
REVALIDATE = (
    (re.compile(r"^site revalidate: scope=\S+ ok"), "refreshed"),
    (re.compile(r"^site revalidate FAILED"), "FAILED (synced reports wait for the site's own cache turnover)"),
    (re.compile(r"^KTP_SITE_REVALIDATE_SECRET is unset"), "skipped: secret unset"),
)


def summarize(text: str) -> dict[str, object]:
    out: dict[str, object] = {}
    for line in text.splitlines():
        for key, rx in PATTERNS.items():
            m = rx.match(line)
            if m:
                out[key] = int(out.get(key, 0)) + int(m.group(1))
        for key, rx in COUNTED.items():
            if rx.match(line):
                out[key] = int(out.get(key, 0)) + 1
        for rx, state in REVALIDATE:
            if rx.match(line):
                out["site cache refresh"] = state
    return out


def render(label: str, counts: dict[str, object]) -> str:
    rows = [f"### Report regeneration: {label}", "", "| | |", "|---|---|"]
    if not counts:
        rows.append("| (no pipeline output recognised) | 0 |")
    for key, value in counts.items():
        rows.append(f"| {key} | {value} |")
    return "\n".join(rows) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--label", required=True)
    args = ap.parse_args(argv)
    sys.stdout.write(render(args.label, summarize(sys.stdin.read())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
