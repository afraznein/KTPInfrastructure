"""Fit per-map flag_swing coefficients, and make every change reviewable.

The league plays one map a week, so a map arrives with 16-20 official halves --
too few to fit alone, and too few to ignore. This driver does three things the
league-wide fit does not:

1. LABELS COME FROM THE ENGINE (`ktp_score_events`), not the demo ledger.
   The demo stops ~45 s before a half ends (`infra-demo-tail-loss`), which can
   flip a winner: on 1789953124-DAL1 h2 the engine reads 82-74 to side 1, 30 of
   those points land in the final minute, and without them the half belongs to
   the other side -- which is what the ledger records. The engine feed is also
   the only label that reaches 12-mans and scrims.

2. PRACTICE COUNTS, BUT ONLY IF IT EARNS IT. Officials are ~1/6 of the halves
   played on the week's map. Rather than argue about whether looser play
   belongs in the fit, each candidate corpus is scored by held-out loss on
   OFFICIAL halves and the best one wins. Practice is never the thing being
   predicted; it is only ever training data.

3. THE OUTPUT IS A REVIEWED FILE. Coefficients land in
   config/map_coefficients.json with their provenance, `--check` fails when the
   committed file no longer matches the data, and the weekly job opens a pull
   request rather than committing. The diff is the review, and git history is
   how a map's play is watched over a season.

Runs on the data server as the reports user (it needs the match database):

    python3 -m scripts.fit_map_coefficients --write
    python3 -m scripts.fit_map_coefficients --check     # CI / the weekly job
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.fit_flag_swing import (PRIOR_HALVES, extract_half_samples, fit_by_map,
                                    fit_logistic, _sigmoid)
from scripts.fit_team_score_labels import load_inputs
from scripts.report_scope import OFFICIAL_MATCH_TYPES

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "config" / "map_coefficients.json"
SHADOW_TYPES = (1, 2)          # scrim, 12man -- training data only, never a target
FOLDS = 4

# Every half of any type, with the side that outscored the other on the ENGINE
# feed. Deltas are per half already, so unlike the demo ledger there is no
# cumulative close to unwind. A drawn half yields no label rather than a guess.
LABEL_SQL = """
SELECT s.match_id, s.half, m.map_name, m.match_type,
       SUM(CASE WHEN l.team = 1 THEN s.delta ELSE 0 END) AS allies_points,
       SUM(CASE WHEN l.team = 2 THEN s.delta ELSE 0 END) AS axis_points
FROM ktp_score_events s
JOIN ktp_matches m ON m.match_id = s.match_id AND m.half = s.half
JOIN (SELECT match_id, half, player_id, MIN(team) AS team
      FROM ktp_life_events GROUP BY 1, 2, 3) l
  ON l.match_id = s.match_id AND l.half = s.half AND l.player_id = s.player_id
WHERE m.start_time >= '{since}' AND l.team IN (1, 2)
GROUP BY 1, 2, 3, 4
"""


def half_winners(rows: list[dict[str, Any]]) -> dict[tuple[str, int], dict[str, Any]]:
    out: dict[tuple[str, int], dict[str, Any]] = {}
    for row in rows:
        allies, axis = int(row["allies_points"]), int(row["axis_points"])
        if allies == axis:
            continue
        out[(str(row["match_id"]), int(row["half"]))] = {
            "winner": 1 if allies > axis else 2,
            "map_name": str(row["map_name"]),
            "match_type": int(row["match_type"]),
        }
    return out


def held_out_loss(official: dict[str, list[list[tuple[float, float, int]]]],
                  practice: dict[str, list[list[tuple[float, float, int]]]],
                  *, folds: int = FOLDS, prior_halves: float = PRIOR_HALVES,
                  iterations: int = 400) -> float:
    """Loss on held-out OFFICIAL halves, with `practice` always in training.

    Folds run over official halves only: practice is never scored, because a
    model that predicts scrims well but officials badly is the wrong model.
    """
    total, n = 0.0, 0
    for map_name, halves in official.items():
        if len(halves) < folds:
            continue
        for fold in range(folds):
            test = [s for i, h in enumerate(halves) if i % folds == fold for s in h]
            train = {map_name: [h for i, h in enumerate(halves) if i % folds != fold]}
            for other, other_halves in official.items():
                if other != map_name:
                    train[other] = list(other_halves)
            for other, other_halves in practice.items():
                train.setdefault(other, []).extend(other_halves)
            if not test or not any(train.values()):
                continue
            _pooled, fits = fit_by_map(train, prior_halves=prior_halves,
                                       iterations=iterations)
            fit = next((f for f in fits if f.map_name == map_name), None)
            if fit is None:
                continue
            for flag_term, alive_term, label in test:
                p = min(max(_sigmoid(fit.flag_coefficient * flag_term
                                     + fit.alive_coefficient * alive_term),
                            1e-12), 1.0 - 1e-12)
                total -= label * math.log(p) + (1 - label) * math.log(1.0 - p)
                n += 1
    return total / n if n else float("inf")


def build(collect, since: str, *, prior_halves: float = PRIOR_HALVES,
          score=None) -> dict[str, Any]:
    """Fit every candidate corpus, keep the one that predicts officials best.

    `score` is the held-out scorer; injectable so the selection rule can be
    tested without standing up a corpus that demonstrates a statistical
    effect, which is a different thing from testing the rule.
    """
    score = score or held_out_loss
    official, practice = collect()
    if not official:
        raise SystemExit("no labelled official halves -- refusing to write a table")

    candidates = {
        "officials_only": {},
        "officials_plus_12man": {m: [h for h, t in hs if t == 2]
                                 for m, hs in practice.items()},
        "officials_plus_all_practice": {m: [h for h, _t in hs]
                                        for m, hs in practice.items()},
    }
    scored = {}
    for name, extra in candidates.items():
        extra = {m: hs for m, hs in extra.items() if hs}
        scored[name] = {
            "held_out_loss_on_officials": round(
                score(official, extra, prior_halves=prior_halves), 6),
            "extra_halves": sum(len(hs) for hs in extra.values()),
        }
    # Tie-break toward LESS data, not more: if practice does not measurably
    # improve the prediction of official halves, it does not go in. Ordered
    # least-inclusive first, and a difference under EPSILON is a tie.
    EPSILON = 1e-4
    order = ["officials_only", "officials_plus_12man", "officials_plus_all_practice"]
    best = order[0]
    for name in order[1:]:
        if (scored[name]["held_out_loss_on_officials"]
                < scored[best]["held_out_loss_on_officials"] - EPSILON):
            best = name

    chosen_extra = {m: hs for m, hs in candidates[best].items() if hs}
    training = {m: list(hs) for m, hs in official.items()}
    for m, hs in chosen_extra.items():
        training.setdefault(m, []).extend(hs)
    pooled, fits = fit_by_map(training, prior_halves=prior_halves)

    return {
        "definition": "flag_swing_map_coefficients_v1",
        "fitted_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "corpus_since": since,
        "label_source": "ktp_score_events (engine feed; see module docstring)",
        "prior_halves": prior_halves,
        "corpus_selected": best,
        "corpus_candidates": scored,
        "pooled": {"flag_coefficient": round(pooled.flag_coefficient, 4),
                   "alive_coefficient": round(pooled.alive_coefficient, 4),
                   "halves": pooled.halves, "samples": pooled.samples,
                   "log_loss": pooled.log_loss},
        "maps": {f.map_name: {
            "flag_coefficient": round(f.flag_coefficient, 4),
            "alive_coefficient": round(f.alive_coefficient, 4),
            "own_flag_coefficient": round(f.own_flag_coefficient, 4),
            "own_alive_coefficient": round(f.own_alive_coefficient, 4),
            "official_halves": len(official.get(f.map_name, [])),
            "training_halves": f.halves,
            "samples": f.samples,
            "shrinkage_weight": f.weight,
            "log_loss": f.log_loss,
        } for f in fits},
    }


def coefficients(payload: dict[str, Any]) -> dict[str, list[float]]:
    return {name: [row["flag_coefficient"], row["alive_coefficient"]]
            for name, row in sorted(payload.get("maps", {}).items())}


def diff(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """What a reviewer needs to see: which map moved, and by how much."""
    before, after = coefficients(old), coefficients(new)
    lines = []
    for name in sorted(set(before) | set(after)):
        b, a = before.get(name), after.get(name)
        if b is None:
            lines.append(f"  + {name:<20} flag {a[0]:.4f}  alive {a[1]:.4f}  (new)")
        elif a is None:
            lines.append(f"  - {name:<20} was flag {b[0]:.4f}  alive {b[1]:.4f}")
        elif b != a:
            lines.append(f"  ~ {name:<20} flag {b[0]:.4f} -> {a[0]:.4f}   "
                         f"alive {b[1]:.4f} -> {a[1]:.4f}")
    return lines


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", type=Path, default=REPO)
    ap.add_argument("--since", default="2026-09-13", help="corpus floor (season start)")
    ap.add_argument("--out", type=Path, default=CONFIG)
    ap.add_argument("--prior-halves", type=float, default=PRIOR_HALVES)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="refit and write the table")
    mode.add_argument("--check", action="store_true",
                      help="refit and fail if the committed table no longer matches")
    args = ap.parse_args(argv)

    from scripts.report_service import LocalMysql, load_match_analytics  # Linux-only
    ma = load_match_analytics(args.repo)
    db = LocalMysql()
    sources = ma.source_capabilities(db)

    def collect():
        labels = half_winners(ma.tsv_rows(db.sql(LABEL_SQL.format(since=args.since))))
        official: dict[str, list] = defaultdict(list)
        practice: dict[str, list] = defaultdict(list)
        cache: dict[str, Any] = {}
        for (match_id, half), meta in sorted(labels.items()):
            if match_id not in cache:
                cache[match_id] = load_inputs(ma, db, match_id, sources)
            inputs = cache[match_id]
            if not inputs or not inputs["flag_states"] or not inputs["roster"]:
                continue
            samples = extract_half_samples(
                inputs["flag_states"], inputs["frags"], inputs["life_boundaries"],
                inputs["roster"], half, meta["winner"],
                initial_owners=ma.load_spawn_ownership(
                    ma.DEFAULT_SPAWN_OWNERSHIP, meta["map_name"]))
            if not samples:
                continue
            if meta["match_type"] in OFFICIAL_MATCH_TYPES:
                official[meta["map_name"]].append(samples)
            elif meta["match_type"] in SHADOW_TYPES:
                practice[meta["map_name"]].append((samples, meta["match_type"]))
        return dict(official), dict(practice)

    payload = build(collect, args.since, prior_halves=args.prior_halves)
    old = json.loads(args.out.read_text(encoding="utf-8")) if args.out.exists() else {}
    changes = diff(old, payload)

    print(f"corpus chosen: {payload['corpus_selected']}")
    for name, row in sorted(payload["corpus_candidates"].items()):
        print(f"  {name:<28} held-out loss on officials "
              f"{row['held_out_loss_on_officials']:.6f}  (+{row['extra_halves']} halves)")
    print("changes:" if changes else "changes: none")
    for line in changes:
        print(line)

    if args.check:
        if changes:
            print("\nthe committed table no longer matches the data. Run --write, "
                  "open a pull request, and have the diff reviewed.", file=sys.stderr)
            return 1
        return 0

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
