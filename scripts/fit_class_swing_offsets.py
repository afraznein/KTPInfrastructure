#!/usr/bin/env python3
"""Fit the per-class swing offset KTPR v2 subtracts, with partial pooling.

WHY. `flag_swing` attributes flag control, and a sniper's job is to hold mid
without standing on it, so the component reads the role as absence. Measured by
coordination `review/hidden-value/tools/hv_class_bias.py` and handed to
infra-mmr-ratings on 2026-10-11: both sniper classes sit several standard
errors below zero on the swing component while the OVERALL rating gap is not
significant, because positive output partly offsets it. So the correction
belongs to the component, not to the rating.

That the deficit is ATTRIBUTION rather than lower contribution is measured, not
assumed. Within the 44 players who played sniper in some officials and another
class in others, sniping costs 0.568 sigma of swing (-5.19 SE) while the team's
win rate does not move (+0.034, +0.70 SE) -- same player, same skill, same
result for the team, lower measured swing. See
coordination `review/hidden-value/tools/hv_sniper_attribution.py`.

STRUCTURE, REUSED RATHER THAN INVENTED. `config/map_coefficients.json` publishes
`own_*` beside the shrunk value with `shrinkage_weight = n / (n + k)`, k = 20
half-games, verified identical across all three fitted maps. This mirrors that
shape. The pooled target here is ZERO, because a class offset is already a
deviation from the league mean, so the shrunk value is simply `w * own_offset`
and a thin class keeps the league value by construction -- class 2 at n=2
shrinks +0.372 to +0.058 on its own.

k IS DERIVED, NOT CHOSEN. The maps' 20 counts half-games; n here counts
match-players, so copying it would barely shrink anything. Instead the standard
empirical-Bayes ratio k = sigma^2 / tau^2, where sigma is the within-class SD of
the component and tau^2 the between-class variance of the true offsets,
estimated as the observed spread of the class means less their own sampling
noise. The shrinkage is then a property of how separated the classes measurably
are rather than a number somebody picked.

Reads via the mysql CLI, so it runs on the data server. Writes only --out.

    python3 -m scripts.fit_class_swing_offsets            # print
    python3 -m scripts.fit_class_swing_offsets --write
    python3 -m scripts.fit_class_swing_offsets --check    # CI / the weekly job
"""
from __future__ import annotations

import json
import math
import subprocess
import sys
from argparse import ArgumentParser
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "config" / "class_swing_offsets.json"
MIN_N_FOR_TAU = 10      # a class this thin informs the spread estimate badly
DEFINITION = "ktpr_class_swing_offsets_v1"
NEWLINE = "\n"


def q(sql: str) -> list[list[str]]:
    out = subprocess.run(
        ["mysql", "-N", "--batch", "--raw", "hlstatsx", "-e", sql],
        capture_output=True, text=True, check=True).stdout
    return [line.split("\t") for line in out.splitlines() if line.strip()]


def _stats(xs: list[float]) -> tuple[int, float, float]:
    n = len(xs)
    mean = sum(xs) / n
    var = sum((x - mean) ** 2 for x in xs) / (n - 1) if n > 1 else 0.0
    return n, mean, var


def fit(since: str) -> dict:
    # Class per (match, player): the one he spent most lives in. The same rule
    # `ktpr_v2.primary_class` applies at report time, read from the same
    # column, so the fit and its application cannot disagree about who counts
    # as a sniper.
    cls: dict[tuple[str, int], int] = {}
    for mid, pid, code, _n in q(
            "SELECT l.match_id, l.player_id, l.player_class, COUNT(*) n "
            "FROM ktp_life_events l JOIN ktp_matches m "
            "  ON m.match_id = l.match_id AND m.half = l.half "
            "WHERE m.match_type IN (0, 4) "
            f"  AND m.start_time >= '{since}' "
            "  AND l.player_class IS NOT NULL "
            "GROUP BY 1, 2, 3 ORDER BY 1, 2, n"):
        cls[(mid, int(pid))] = int(code)        # ordered by n, last wins

    swing: dict[int, list[float]] = defaultdict(list)
    matches: set[str] = set()
    for mid, blob in q("SELECT match_id, JSON_EXTRACT(report, "
                       "'$.shadow_explorations.ktpr_v2.players') "
                       "FROM ktp_match_reports WHERE schema_version >= 28"):
        if not blob or blob == "NULL":
            continue
        for player in json.loads(blob):
            code = cls.get((mid, int(player.get("player_id") or -1)))
            value = (player.get("components") or {}).get("swing")
            if code is None or value is None:
                continue
            swing[code].append(float(value))
            matches.add(mid)

    if not swing:
        raise SystemExit(
            "no swing components found - is any report at schema 28 or later?")

    # sigma^2: pooled within-class variance of the component. On a within-match
    # z this lands near 1, which is the sanity check that the units are right.
    num = den = 0.0
    for xs in swing.values():
        n, _mean, var = _stats(xs)
        if n > 1:
            num += var * (n - 1)
            den += n - 1
    sigma_sq = num / den if den else 1.0

    # tau^2: spread of the class means beyond their own sampling noise.
    usable = [(code, *_stats(xs)) for code, xs in swing.items()
              if len(xs) >= MIN_N_FOR_TAU]
    means = [mean for _c, _n, mean, _v in usable]
    grand = sum(means) / len(means)
    observed = (sum((m - grand) ** 2 for m in means) / (len(means) - 1)
                if len(means) > 1 else 0.0)
    noise = sum(sigma_sq / n for _c, n, _m, _v in usable) / len(usable)
    tau_sq = max(observed - noise, 0.0)
    k = (sigma_sq / tau_sq) if tau_sq > 0 else None

    classes = {}
    for code, xs in sorted(swing.items()):
        n, mean, _var = _stats(xs)
        weight = n / (n + k) if k else 0.0
        classes[str(code)] = {
            "n": n,
            "own_offset": round(mean, 4),
            "offset": round(weight * mean, 4),
            "se": round(math.sqrt(sigma_sq / n), 4),
            "shrinkage_weight": round(weight, 4),
        }

    return {
        "definition": DEFINITION,
        "fitted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "corpus_since": since,
        "scope": "official_match_types_0_4",
        "matches": len(matches),
        "pooled_target": 0.0,
        "within_class_sd": round(math.sqrt(sigma_sq), 4),
        "between_class_sd": round(math.sqrt(tau_sq), 4),
        "shrinkage_k": (round(k, 2) if k else None),
        "min_n_for_spread_estimate": MIN_N_FOR_TAU,
        "classes": classes,
    }


def main(argv: list[str] | None = None) -> int:
    ap = ArgumentParser(description="Fit per-class KTPR swing offsets.")
    ap.add_argument("--since", default="2026-09-13", help="corpus floor")
    ap.add_argument("--out", type=Path, default=CONFIG)
    ap.add_argument("--write", action="store_true",
                    help="write the fitted table to --out")
    ap.add_argument("--check", action="store_true",
                    help="exit 1 when --out differs from a fresh fit")
    args = ap.parse_args(argv)

    fitted = fit(args.since)
    body = json.dumps(fitted, indent=2, sort_keys=True) + NEWLINE

    if args.check:
        try:
            on_disk = json.loads(args.out.read_text(encoding="utf-8"))
        except OSError:
            print(f"{args.out} is absent", file=sys.stderr)
            return 1
        # `fitted_at` moves every run and says nothing about the numbers.
        def without_stamp(d):
            return {key: value for key, value in d.items()
                    if key != "fitted_at"}
        if without_stamp(on_disk) != without_stamp(fitted):
            print(f"{args.out} differs from a fresh fit", file=sys.stderr)
            return 1
        print(f"{args.out} matches a fresh fit")
        return 0

    if args.write:
        args.out.write_text(body, encoding="utf-8", newline=NEWLINE)
        print(f"wrote {args.out}")
        return 0

    sys.stdout.write(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
