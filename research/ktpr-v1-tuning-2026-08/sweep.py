"""Sensitivity sweep for the team KTPR: vary one knob at a time (others at the
weights.toml baseline) and show how the board + anchor players move.

Run via PowerShell (one DB load, then all-in-memory). Writes SENSITIVITY_SWEEP.md.
"""
import os, sys
from dataclasses import replace
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ktpr_engine as E
import ktpr_mysql as Q

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "SENSITIVITY_SWEEP.md")

ANCHORS = ["hildebrand", "TillJim", "nicholson", "billbsod", "piff", "s i k <3"]
SWEEPS = [
    ("kill_exp",           [0.5, 0.6, 0.7, 0.8, 0.9, 1.0]),
    ("tw_kd",              [1.0, 1.3, 1.6, 2.0, 2.5]),
    ("tw_break",           [0.4, 0.6, 0.8, 1.0, 1.2]),
    ("tw_flag",            [0.4, 0.6, 0.8, 1.0]),
    ("tw_assist",          [0.4, 0.7, 1.0, 1.3]),
    ("dmg_interaction",    [0.0, 0.3, 0.6, 0.9]),
    ("assist_interaction", [0.0, 0.3, 0.6, 0.9]),
    ("ratio_floor",        [0.40, 0.55, 0.70]),
]
ROLE_HEAVY = [1.00, 1.05, 1.10, 1.15]


def ranks(vals):
    order = sorted([i for i, v in enumerate(vals) if v is not None], key=lambda i: -vals[i])
    return {i: r for r, i in enumerate(order, 1)}


def spearman(r1, r2):
    common = set(r1) & set(r2)
    n = len(common)
    if n < 2:
        return 1.0
    d2 = sum((r1[i] - r2[i]) ** 2 for i in common)
    return 1 - 6 * d2 / (n * (n * n - 1))


def main():
    players = Q.load_players_from_mysql()
    base = E.load_params("new")
    base_ranks = ranks(E.compute_ktpr(players, base))

    def anchor_idx(sub):
        for i, p in enumerate(players):
            if sub.lower() in p.name.lower():
                return i
        return None
    anchors = [(a, anchor_idx(a)) for a in ANCHORS]
    anchors = [(a, i) for a, i in anchors if i is not None]

    def top_names(vals, k=6):
        order = sorted([i for i, v in enumerate(vals) if v is not None], key=lambda i: -vals[i])
        return ", ".join(players[i].name.split()[0][:12] for i in order[:k])

    L = []; w = L.append
    w("# KTPR Team-Formula — Sensitivity Sweep\n\n")
    w("Each section varies ONE knob; all others stay at the `weights.toml` "
      "baseline. **ρ** = Spearman rank-correlation vs the baseline board (1.0 = "
      "identical order). Columns show each anchor player's **rank** at that "
      "setting. `*` marks the current baseline value.\n\n")
    w(f"Anchors: {', '.join(a for a, _ in anchors)}\n")

    def section(knob, values, apply_fn, base_val):
        w(f"\n## `{knob}`\n\n")
        hdr = "| value | ρ | " + " | ".join(a for a, _ in anchors) + " | top 5 |\n"
        w(hdr)
        w("|" + "---|" * (3 + len(anchors)) + "\n")
        for v in values:
            p = apply_fn(v)
            vals = E.compute_ktpr(players, p)
            rk = ranks(vals)
            rho = spearman(base_ranks, rk)
            mark = " *" if abs(v - base_val) < 1e-9 else ""
            arank = " | ".join(str(rk.get(i, "-")) for _, i in anchors)
            top = ", ".join(players[i].name.split()[0][:10]
                            for i in sorted([j for j, x in enumerate(vals) if x is not None],
                                            key=lambda j: -vals[j])[:5])
            w(f"| {v}{mark} | {rho:.2f} | {arank} | {top} |\n")

    for knob, values in SWEEPS:
        section(knob, values, lambda v, k=knob: replace(base, **{k: v}), getattr(base, knob))

    # role weight: Heavy multiplier
    def heavy_apply(v):
        rw = {"Rifle": 1.0, "Sniper": 1.0, "Heavy": v, "SMG": 1.0}
        return replace(base, role_weights=rw)
    section("role_weights.Heavy", ROLE_HEAVY, heavy_apply, 1.0)

    # class_normalize on/off (special: bool)
    w("\n## `class_normalize` (within-role normalization)\n\n")
    w("| value | ρ | " + " | ".join(a for a, _ in anchors) + " | top 5 |\n")
    w("|" + "---|" * (3 + len(anchors)) + "\n")
    for v in (True, False):
        p = replace(base, class_normalize=v)
        vals = E.compute_ktpr(players, p)
        rk = ranks(vals)
        arank = " | ".join(str(rk.get(i, "-")) for _, i in anchors)
        top = ", ".join(players[i].name.split()[0][:10]
                        for i in sorted([j for j, x in enumerate(vals) if x is not None],
                                        key=lambda j: -vals[j])[:5])
        w(f"| {v} | {spearman(base_ranks, rk):.2f} | {arank} | {top} |\n")

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("".join(L))
    print(f"Wrote {OUT}")
    print("anchors:", ", ".join(f"{a}(#{base_ranks.get(i,'-')})" for a, i in anchors))


if __name__ == "__main__":
    main()