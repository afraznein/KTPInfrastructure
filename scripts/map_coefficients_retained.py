"""The floor under config/map_coefficients.json: every map ever fitted keeps a row.

The weekly refit (scripts/ktp-map-coefficients-refit.sh) rewrites the live table
wholesale, so a map whose halves fall out of the training window simply leaves it,
and flag_swing then prices that map on the hardcoded league prior. The retained
table holds the LAST fitted row each such map had, with the commit it came from,
and flag_swing reads it only for a map the live table (and its carry-forward) lacks.

The retained rows are derived from git history of the live table, never typed by
hand, so the source of every number can be checked out and read.

    python3 -m scripts.map_coefficients_retained --check   # CI; exit 1 on a gap
    python3 -m scripts.map_coefficients_retained --write   # add the missing rows

`--check` fails when a map that some committed version of the live table fitted
is in neither the live table nor the retained one. That is the state a refit
that drops a map leaves behind, so the refit's own pull request goes red until
`--write` is run on its branch. Existing retained rows are never rewritten: a row
is replaced only by the live table taking the map back, which makes it inert.

Exit 0 clean (or written), 1 a gap under `--check`, 2 could not run. A shallow
clone cannot see the history this reads, so it exits 2 rather than pass.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
LIVE = "config/map_coefficients.json"
RETAINED = "config/map_coefficients_retained.json"
DEFINITION = "flag_swing_map_coefficients_retained_v1"

# Copied from the source row so a reader can judge it without checking out the commit.
CARRIED_FIELDS = ("flag_coefficient", "alive_coefficient", "official_halves",
                  "training_halves", "shrinkage_weight")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args], check=True,
                          capture_output=True, text=True, encoding="utf-8").stdout


def history(repo: Path = REPO) -> list[tuple[str, dict[str, Any]]]:
    """(commit, payload) for every committed version of the live table, oldest first."""
    if _git(repo, "rev-parse", "--is-shallow-repository").strip() == "true":
        raise RuntimeError("shallow clone: the live table's history is not here")
    commits = _git(repo, "log", "--format=%H", "--reverse", "--", LIVE).split()
    return [(c, json.loads(_git(repo, "show", f"{c}:{LIVE}"))) for c in commits]


def last_fitted(versions: list[tuple[str, dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    """Each map's most recent fitted row across history, with where it came from."""
    out: dict[str, dict[str, Any]] = {}
    for commit, payload in versions:
        for name, row in (payload.get("maps") or {}).items():
            carried = {k: row[k] for k in CARRIED_FIELDS if k in row}
            carried.update(retained_from_commit=commit,
                           retained_from_fitted_at=payload.get("fitted_at"),
                           retained_from_corpus=payload.get("corpus_selected"))
            out[name] = carried
    return out


def gaps(live: dict[str, Any], retained: dict[str, Any],
         fitted: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Maps history fitted that neither table now covers."""
    return {name: row for name, row in sorted(fitted.items())
            if name not in live and name not in retained}


def _read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    ap.add_argument("--repo", type=Path, default=REPO)
    args = ap.parse_args(argv)
    try:
        fitted = last_fitted(history(args.repo))
        live = _read(args.repo / LIVE).get("maps") or {}
        payload = _read(args.repo / RETAINED)
    except (RuntimeError, subprocess.CalledProcessError, OSError, ValueError) as exc:
        print(f"map_coefficients_retained: cannot run: {exc}", file=sys.stderr)
        return 2
    if not fitted:
        print("map_coefficients_retained: no history of the live table found",
              file=sys.stderr)
        return 2
    retained = payload.get("maps") or {}
    missing = gaps(live, retained, fitted)
    for name, row in missing.items():
        print(f"GAP {name}: fitted at {row['retained_from_commit'][:12]}, now in "
              f"neither {LIVE} nor {RETAINED} -- it prices on the league prior")
    if not missing:
        print(f"OK: {len(fitted)} maps ever fitted; {len(live)} live, "
              f"{sum(1 for m in retained if m not in live)} retained")
        return 0
    if args.check:
        print("Run `python3 -m scripts.map_coefficients_retained --write` and commit "
              f"{RETAINED} with the refit.")
        return 1
    payload.setdefault("definition", DEFINITION)
    payload["maps"] = dict(sorted({**retained, **missing}.items()))
    (args.repo / RETAINED).write_bytes(
        (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    print(f"wrote {len(missing)} row(s) to {RETAINED}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
