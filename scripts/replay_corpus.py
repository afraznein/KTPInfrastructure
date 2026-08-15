#!/usr/bin/env python3
"""Replay the stored match logs and check the daemon still produces the same rows.

## What this is for

Lane B's live run needs a game server, bots, and twenty minutes. This needs a
file. The corpus is three real 20-minute KTP-shaped matches captured on
2026-08-10 — two halves each, sides swapped, at bot skill 3/5/7 — and replaying
one rebuilds its database in seconds.

Because the input is fixed, the output is **exact**. That makes this a
regression test rather than a probe: any change to `hlstats.pl`, to the action
seeds, to the schema, or to the harness that alters what gets recorded shows up
as a number that moved. The live lane cannot do that — bot AI decides how much
happens, so its assertions have to be shaped around uncertainty.

The two complement each other:

| | live lane | corpus replay |
|---|---|---|
| proves | the whole chain, bots included | the daemon leg, exactly |
| runtime | ~20 min + a game server | seconds, no server |
| determinism | none | total |
| catches | "capture stopped emitting" | "the daemon started dropping rows" |

## Updating the baseline

`--update` rewrites `expected.json`. Do that **only** when a change was
intended, and say in the commit what moved and why. A baseline updated to make
a test pass is a test deleted with extra steps.
"""

from __future__ import annotations

import argparse
import gzip
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_HERE = Path(__file__).resolve().parent
CORPUS = _HERE.parent / "tests/e2e_stats/corpus"
EXPECTED = CORPUS / "expected.json"

# What is compared. Deliberately the counts a regression would move, not the
# whole report: eventTime, ids and the daemon's own timing vary per run and
# comparing them would make the check fail for reasons nobody cares about.
#
# Action counts are scoped by code. The shared schema seeds standard DoD
# actions too, so whole-table PA/PPA totals can legitimately change without
# changing the assist or cap_break behavior this corpus protects.
_COMPARED = (
    ("emitted", "kills"), ("emitted", "assist"), ("emitted", "cap_break"),
    ("emitted", "suicide"),
    ("rows", "frags"), ("rows", "players"), ("rows", "suicides"),
    ("rows", "assist", "ppa"), ("rows", "cap_break", "pa"),
)


def _dig(d: dict, path: tuple):
    for k in path:
        d = d.get(k) if isinstance(d, dict) else None
        if d is None:
            return None
    return d


def replay_one(log_gz: Path, *, hlstats: Path, schema: list[Path],
               seeds: list[Path], workdir: Path) -> dict:
    """Run one corpus log through the real replay script."""
    plain = workdir / log_gz.name.replace(".gz", "")
    with gzip.open(log_gz, "rb") as fh, plain.open("wb") as out:
        shutil.copyfileobj(fh, out)

    report = workdir / f"{log_gz.stem}.json"
    argv = [sys.executable, "-u", str(_HERE / "replay_daemon.py"),
            "--log", str(plain), "--hlstats", str(hlstats),
            "--schema", *[str(p) for p in schema],
            "--no-assert", "--out", str(report)]
    if seeds:
        argv += ["--seed", *[str(p) for p in seeds]]
    r = subprocess.run(argv, capture_output=True, text=True)
    if not report.is_file():
        raise SystemExit(
            f"replay produced no report for {log_gz.name}:\n"
            f"{r.stdout[-2000:]}\n{r.stderr[-2000:]}")
    return json.loads(report.read_text())


def compare(name: str, got: dict, want: dict) -> list[str]:
    diffs = []
    for path in _COMPARED:
        g, w = _dig(got, path), _dig(want, path)
        if g != w:
            diffs.append(f"{name}: {'.'.join(path)} {w} -> {g}")
    return diffs


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--hlstats", type=Path, required=True)
    ap.add_argument("--schema", type=Path, nargs="+", required=True)
    ap.add_argument("--seed", type=Path, nargs="*", default=[])
    ap.add_argument("--update", action="store_true",
                    help="rewrite expected.json — only for an INTENDED change")
    args = ap.parse_args()

    logs = sorted(CORPUS.glob("*.log.gz"))
    if not logs:
        raise SystemExit(f"no corpus logs under {CORPUS}")

    expected = json.loads(EXPECTED.read_text()) if EXPECTED.is_file() else {}
    results, diffs = {}, []

    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        for log in logs:
            print(f"replaying {log.name} ...", flush=True)
            got = replay_one(log, hlstats=args.hlstats, schema=list(args.schema),
                             seeds=list(args.seed), workdir=work)
            results[log.name] = {
                "emitted": got["emitted"],
                "rows": {k: got["rows"][k] for k in
                         ("frags", "players", "suicides",
                          "assist", "cap_break")},
                "carried": {c["code"]: c["status"] for c in got.get("carried", [])},
            }
            summary = results[log.name]
            print(f"  emitted={summary['emitted']}")
            print(f"  rows={summary['rows']}")
            if log.name in expected:
                diffs += compare(log.name, got, expected[log.name])
            elif not args.update:
                diffs.append(f"{log.name}: no baseline — run with --update")

    if args.update:
        EXPECTED.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
        print(f"\nwrote baseline for {len(results)} log(s) to {EXPECTED}")
        return 0

    if diffs:
        print(f"\n=== {len(diffs)} DIFFERENCE(S) FROM BASELINE ===")
        for d in diffs:
            print("  " + d)
        print("\nThe corpus is fixed input, so these numbers only move when "
              "behaviour changed. Work out which change did it before touching "
              "expected.json.")
        return 1

    print(f"\nall {len(results)} corpus log(s) match the baseline")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
