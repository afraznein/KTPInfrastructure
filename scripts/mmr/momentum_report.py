"""Fit the momentum curves on everything we have and show what the ledger says.

Rerun after `momentum_fetch.py` each week. Writes momentum_report.md:
  1. corpus (matches, multikills, caps, capouts -- capouts per map, because
     thunder rarely capouts and lennon/harrington do)
  2. lag-lift tables for cap and capout with the fitted A, lam, half-life
  3. rho evidence (does a cap that followed a multikill lead on to a capout
     more often than one that did not)
  4. per-player momentum credit over the S10 officials, and season totals

Everything is fitted on officials + 12mans together: 12mans carry the
capout fit until enough officials exist. The officials-only lift table is
printed beside it so the two can be compared as the season fills in.

Objective values are scoreboard points where a map has a scoring fit
(demo-labelled halves via --labels, the #434 backfill SQL), else 1 per cap
and 1 per capout.

Usage:
    python momentum_report.py --labels G:/GIT/KTP/ktp_highlights/evidence/observations-s10-official-20260913.sql
"""
from __future__ import annotations

import argparse
import math
from collections import Counter, defaultdict
from pathlib import Path

import demo_labels as D
import momentum as M

HERE = Path(__file__).resolve().parent
OUT = HERE / "momentum_report.md"


def lift_table(rows):
    lines = ["| lag (s) | n | hits | P(after mk) | matched base | lift |", "|---|---|---|---|---|---|"]
    for r in rows:
        lo, hi = r["bin"]
        lines.append(f"| {lo}-{hi} | {r['n']} | {r['hits']} | {r['p']:.3f} | {r['base']:.3f} | {r['lift']:.2f} |")
    return "\n".join(lines)


def fit_scoring_by_map(labels, objs, mmap, min_halves=12):
    """{map: coef} from demo-labelled halves, one fit per map with enough of them."""
    samples = defaultdict(list)
    for mid, L in labels.items():
        if mid not in mmap:
            continue
        for half in (1, 2):
            for side_name, team in (("allies", 1), ("axis", 2)):
                pts = L["halves"][half][L["sides"][half][side_name]]
                samples[mmap[mid]].append((M.scoring_features(objs, mid, half, team), pts))
    out = {}
    for mp, rows in samples.items():
        if len(rows) >= min_halves:
            out[mp] = M.fit_scoring(rows) + (len(rows),)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", help="demo team-score backfill SQL (#434); enables per-map scoring")
    args = ap.parse_args()
    frags, flags, caps, lives, matches, players = (
        M.read(n) for n in ("frags", "flags", "captures", "lives", "matches", "players"))
    mtype = {r["match_id"]: r["match_type"] for r in matches}
    mmap = {r["match_id"]: r["map_name"] for r in matches}
    name = {}
    for r in players:
        name[int(r["player_id"])] = r["player_name"]

    side = M.sides(lives)
    mk = M.multikills(frags, side)
    ob = M.objectives(flags, caps)
    spans = M.half_spans(mk, ob)
    official = lambda e: mtype.get(e["match"]) == "0"  # noqa: E731

    # --- fit
    curves, tables = {}, {}
    for kind in ("cap", "capout"):
        rows = M.lag_lift(mk, ob, spans, kind=kind)
        A, lam = M.fit_lift(rows)
        curves[kind] = (A, lam)
        tables[kind] = rows
    p_with, p_without, n_with, n_without = M.conditional_lift(mk, ob)
    ratio = p_with / p_without if p_without else float("nan")
    rho = max(0.0, 1.0 - 1.0 / ratio) if ratio == ratio and ratio > 0 else 0.0

    mko, obo = [m for m in mk if official(m)], [o for o in ob if official(o)]
    off_rows = {k: M.lag_lift(mko, obo, M.half_spans(mko, obo), kind=k) for k in ("cap", "capout")}

    # --- scoring: price objectives in points where a map has labelled halves
    fits = {}
    if args.labels:
        labels = D.labels(D.read_backfill_sql(args.labels))
        fits = fit_scoring_by_map(labels, ob, mmap)
    scoring = {mp: coef for mp, (coef, _, _) in fits.items()}
    for e in ob:
        e["map"] = mmap.get(e["match"])

    # --- ledger
    got = M.credit(mk + ob, curves, rho, scoring=scoring)

    lines = ["# Momentum credit report", ""]
    lines += ["Deposit/payout ledger over multikills, caps and capouts. Curves fitted on",
              "officials + 12mans; officials-only shown for comparison.", ""]
    if fits:
        lines += ["Credit units: scoreboard points, from a per-map fit on demo-labelled halves",
                  "(points = cap·caps + hold3·s + hold4·s + capout·capouts; a cap owns the hold",
                  "until the next ownership change):", ""]
        for mp, (coef, r2, n) in sorted(fits.items()):
            lines.append(f"- {mp} (n={n} team-halves, R²={r2:.3f}): " +
                         ", ".join(f"{k}={v:.2f}" for k, v in coef.items()))
        lines += ["", f"Maps without a fit pay {M.CAP_VALUE} per cap and {M.CAPOUT_VALUE} per capout.", ""]
    else:
        lines += [f"Credit units: one flag cap = {M.CAP_VALUE}, a capout pays {M.CAPOUT_VALUE} on top "
                  "(no --labels given, so no scoreboard fit).", ""]

    # 1 corpus
    halves = Counter(mtype[m] for m, _ in side)
    lines += ["## Corpus", "",
              f"- halves with events: {sum(halves.values())} (official {halves.get('0', 0)}, 12man {halves.get('1', 0)})",
              f"- multikills (>= {M.MULTIKILL_MIN} kills, gap <= {M.MULTIKILL_GAP:.0f}s): {len(mk)} "
              f"({dict(sorted(Counter(m['n'] for m in mk).items()))})",
              f"- caps: {sum(1 for o in ob if o['kind'] == 'cap')} "
              f"(capper known for {sum(1 for o in ob if o['kind'] == 'cap' and o['players'])}); "
              f"capouts: {sum(1 for o in ob if o['kind'] == 'capout')}", "",
              "Capouts per map (halves with events / capouts):", ""]
    per_map = defaultdict(lambda: [0, 0])
    for (m, h) in side:
        per_map[mmap[m]][0] += 1
    for o in ob:
        if o["kind"] == "capout":
            per_map[mmap[o["match"]]][1] += 1
    for mp, (hs, cs) in sorted(per_map.items(), key=lambda kv: -kv[1][1]):
        lines.append(f"- {mp}: {hs} halves, {cs} capouts ({cs / hs:.2f}/half)")
    lines.append("")

    # 2 lifts
    for kind in ("cap", "capout"):
        A, lam = curves[kind]
        hl = math.log(2) / lam if lam > 0 else float("inf")
        lines += [f"## Lift after a multikill: {kind}", "",
                  f"Fitted lift(d) = 1 + {A:.2f}·exp(−{lam:.4f}·d); half-life {hl:.0f}s. "
                  f"Attributable share at d=0: {M.attributable(0, A, lam):.2f}, at 30s: "
                  f"{M.attributable(30, A, lam):.2f}, at 60s: {M.attributable(60, A, lam):.2f}.", "",
                  "All matches:", "", lift_table(tables[kind]), "",
                  f"Officials only ({len(mko)} multikills):", "", lift_table(off_rows[kind]), ""]

    # 3 rho
    lines += ["## Chain (rho)", "",
              f"A cap that followed a multikill (within 60s) led to a capout within 120s "
              f"{p_with:.3f} of the time (n={n_with}); a cap that did not: {p_without:.3f} (n={n_without}). "
              f"Ratio {ratio:.2f} → rho = {rho:.2f} (share of a payout a cap forwards upstream).", ""]

    # 4 officials per player
    lines += ["## S10 officials: momentum credit per player", "",
              "`momentum` is value received as a depositor (what this adds over plain cap credit); "
              "`direct` is the capper's own share; `mk` is multikills.", ""]
    season = defaultdict(lambda: {"momentum": 0.0, "direct": 0.0, "mk": 0, "matches": set()})
    for match in sorted({m for m, _ in side if mtype[m] == "0"}):
        rows = defaultdict(lambda: {"momentum": 0.0, "direct": 0.0, "mk": 0})
        for half in (1, 2):
            for pid, v in got.get((match, half), {}).items():
                rows[pid]["momentum"] += v["momentum"]
                rows[pid]["direct"] += v["total"] - v["momentum"]
        for m in mk:
            if m["match"] == match:
                rows[m["player"]]["mk"] += 1
        lines += [f"### {match} ({mmap[match]})", "", "| player | mk | momentum | direct |", "|---|---|---|---|"]
        for pid, v in sorted(rows.items(), key=lambda kv: -kv[1]["momentum"])[:8]:
            lines.append(f"| {name.get(pid, pid)} | {v['mk']} | {v['momentum']:.2f} | {v['direct']:.2f} |")
            s = season[pid]
            s["momentum"] += v["momentum"]; s["direct"] += v["direct"]; s["mk"] += v["mk"]; s["matches"].add(match)
        for pid, v in rows.items():
            if pid not in [p for p, _ in sorted(rows.items(), key=lambda kv: -kv[1]["momentum"])[:8]]:
                s = season[pid]
                s["momentum"] += v["momentum"]; s["direct"] += v["direct"]; s["mk"] += v["mk"]; s["matches"].add(match)
        lines.append("")

    lines += ["### Season to date (officials), top 20 by momentum", "",
              "| player | matches | mk | momentum | direct |", "|---|---|---|---|---|"]
    for pid, s in sorted(season.items(), key=lambda kv: -kv[1]["momentum"])[:20]:
        lines.append(f"| {name.get(pid, pid)} | {len(s['matches'])} | {s['mk']} | {s['momentum']:.2f} | {s['direct']:.2f} |")
    lines.append("")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {OUT}")
    print(f"curves {curves}  rho {rho:.2f}")


if __name__ == "__main__":
    main()
