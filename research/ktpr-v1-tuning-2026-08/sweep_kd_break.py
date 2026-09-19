"""Deeper sweep: 5 variations of the top-15 driven by (tw_kd, tw_break).

These two are the master fragger<->objective dials. Each variation holds every
other weight at the weights.toml baseline and only changes tw_kd / tw_break.
Run via PowerShell. Writes SWEEP_KD_BREAK.md.
"""
import os, sys
from dataclasses import replace
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ktpr_engine as E
import ktpr_mysql as Q

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "SWEEP_KD_BREAK.md")

# (label, tw_kd, tw_break, one-line philosophy)
VARIATIONS = [
    ("V1 — Fragger-focused",   2.5, 0.4, "Efficiency (K/D) dominates; objectives barely count. Rewards clean fraggers."),
    ("V2 — Baseline (current)", 1.6, 0.8, "The current weights.toml settings."),
    ("V3 — Objective-focused", 1.0, 1.2, "Breaks/objectives heavily rewarded; efficiency de-emphasized. Rewards utility players."),
    ("V4 — Both matter",        2.2, 1.2, "Reward BOTH elite efficiency AND objective work; punishes one-dimensional stat-padders."),
    ("V5 — Flat/volume",        1.0, 0.4, "Both dials low; score leans on kill volume, damage, assists, flags."),
]


def esc(s):
    return s.replace("|", "\\|")


def main():
    players = Q.load_players_from_mysql()
    base = E.load_params("new")

    def board(p):
        vals = E.compute_ktpr(players, p)
        order = sorted([i for i, v in enumerate(vals) if v is not None], key=lambda i: -vals[i])
        return vals, order

    base_vals, base_order = board(base)
    base_rank = {i: r for r, i in enumerate(base_order, 1)}

    L = []; w = L.append
    w("# KTPR Sweep — `tw_kd` x `tw_break` (5 variations)\n\n")
    w("The two master dials: **`tw_kd`** rewards fragging efficiency (K/D), "
      "**`tw_break`** rewards objective/utility (cap-breaks). Each table is the "
      "top 15 under that pairing; every other weight stays at baseline. "
      "`Δ` = rank move vs **V2 (current baseline)**.\n")

    for label, kd, br, desc in VARIATIONS:
        p = replace(base, tw_kd=kd, tw_break=br)
        vals, order = board(p)
        w(f"\n## {label} — `tw_kd={kd}`, `tw_break={br}`\n\n")
        w(f"*{desc}*\n\n")
        w("| # | Player | role | K/D | K/H | Fl/H | Br/H | KTPR | Δ vs V2 |\n")
        w("|--:|---|---|--:|--:|--:|--:|--:|--:|\n")
        for rank, i in enumerate(order[:15], 1):
            pl = players[i]
            bv = base_rank.get(i)
            d = (bv - rank) if bv else 0
            dstr = f"+{d}" if d > 0 else (str(d) if d < 0 else "0")
            w(f"| {rank} | {esc(pl.name)} | {pl.role} | {pl.kd_ratio:.2f} | "
              f"{pl.kills_half:.1f} | {pl.flags_half:.1f} | {pl.breaks_half:.2f} | "
              f"{vals[i]:.2f} | {dstr} |\n")

    w("\n---\n\n## How to read this\n")
    w("- **V1→V3** traces the fragger→objective axis: watch snipers/efficient "
      "fraggers fall and break/flag specialists rise as you move down.\n")
    w("- **V4** is the 'complete player' setting — you need both efficiency and "
      "objectives to top it; pure one-trick players slip.\n")
    w("- To adopt any variation, set its `tw_kd` / `tw_break` in `weights.toml` "
      "`[profiles.new]` and re-run `tune_new.py`.\n")

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("".join(L))
    print(f"Wrote {OUT}")
    for label, kd, br, _ in VARIATIONS:
        p = replace(base, tw_kd=kd, tw_break=br)
        vals, order = board(p)
        top3 = ", ".join(players[i].name.split()[0][:12] for i in order[:3])
        print(f"  {label:<26} kd={kd} br={br}  top3: {top3}")


if __name__ == "__main__":
    main()