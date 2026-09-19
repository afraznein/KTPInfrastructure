"""Generate KTPR_LAN_COMPARISON.md — old vs current vs new KTPR over the whole LAN.

Usage (must run via PowerShell so Windows ssh-agent auth works):
    python make_report.py
"""
import os, sys, math
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ktpr_engine as E
import ktpr_mysql as Q

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "KTPR_LAN_COMPARISON.md")


def ranks(vals):
    order = sorted([(i, v) for i, v in enumerate(vals) if v is not None], key=lambda t: -t[1])
    return {i: rank for rank, (i, v) in enumerate(order, 1)}


def fmt(x, nd=2):
    return f"{x:.{nd}f}" if x is not None else "-"


def esc(s):
    """Escape Markdown table delimiters in free text (names contain literal '|')."""
    return s.replace("|", "\\|")


def main():
    players = Q.load_players_from_mysql()  # whole LAN, roster names
    pO = E.load_params("old"); pC = E.load_params("current"); pN = E.load_params("new")
    old = E.compute_ktpr(players, pO)
    cur = E.compute_ktpr(players, pC)
    new = E.compute_ktpr(players, pN)
    rO, rC, rN = ranks(old), ranks(cur), ranks(new)

    # --- transparency: the medians the multiplicative formulas normalize against ---
    def medians(p):
        thr = E._participation_threshold(players, p)
        regs = [pl for pl in players if pl.matches >= thr and pl.name]
        return {
            "threshold": thr,
            "n_regulars": len(regs),
            "K": E._median([pl.kills_half for pl in regs]),
            "D": E._median([pl.deaths_half for pl in regs]),
            "O": E._median([pl.flags_half for pl in regs]),
            "Dmg": E._median([pl.damage_half for pl in regs]),
            "Br": E._median([pl.breaks_half for pl in regs]),
        }
    mC = medians(pC)

    total_matches = max((int(pl.matches) for pl in players), default=0)
    L = []
    w = L.append

    # ---------------------------------------------------------------- header
    w("# KTPR Comparison — Philly LAN 2026 (tournament)\n")
    w("Old vs Current vs New KTPR over the **Sat+Sun `match_type=0` tournament "
      "matches** (55 matches; Friday's for-fun games and warmups excluded), "
      "aggregated per player from `hud_player_stats`. Names from `roster.csv`.\n")
    w(f"- **Players:** {len([p for p in players if p.name])}  ·  "
      f"**Max matches by any player:** {total_matches}\n")
    w("- **Source of truth for the math:** [ktpr_engine.py](ktpr_engine.py); "
      "all weights in [weights.toml](weights.toml). Scope in `ktpr_mysql.py`.\n")
    w("- **Note:** old/current are the Excel formulas (multiplicative); **new** is "
      "the redesigned team-contribution formula (see §New). Old/current were tuned "
      "on season-long gold data, so read them for the *relative* picture.\n")

    # ---------------------------------------------------------------- the shared skeleton
    w("\n---\n\n## How the Excel KTPR works (old & current)\n")
    w("The two Excel formulas are **multiplicative** — a core skill term, scaled "
      "up for objectives and down for dying, times a constant. (**New** uses a "
      "different, additive team-contribution structure — see §New.)\n")
    w("```\nKTPR = SCALE\n"
      "     x [ min(K/D, 1.1) x (Kills/Half / median_regulars(Kills/Half)) ]   # core\n"
      "     x ( 1 + flag_bonus )                                              # objectives\n"
      "     x ( 1 - death_penalty )                                           # dying\n```\n")
    w("- **Regular player** = played >= `MAX(floor, 0.66 x max_matches)` matches; "
      "medians are taken over regulars so casuals don't skew the baseline.\n")
    w("- **flag_bonus** = `log(flags/half + 1)/log(25)` + a relative term vs the "
      "median, capped.\n")
    w("- **death_penalty** = how far deaths/half exceed the median, scaled & capped "
      "(below-median dying becomes a small bonus).\n")
    w(f"\n**Baselines used here (current profile, over {mC['n_regulars']} regulars, "
      f"threshold = {mC['threshold']:.2f} matches):** "
      f"median Kills/Half = {mC['K']:.2f}, Deaths/Half = {mC['D']:.2f}, "
      f"Flags/Half = {mC['O']:.2f}, Damage/Half = {mC['Dmg']:.0f}, "
      f"Breaks/Half = {mC['Br']:.2f}.\n")

    # ---------------------------------------------------------------- per-formula knobs
    def knob_table(name, p, extra=""):
        w(f"\n### {name}\n")
        w("| knob | value | meaning |\n|---|---|---|\n")
        w(f"| SCALE | {p.scale} | final multiplier |\n")
        w(f"| K/D cap | {p.kd_cap} | ceiling on the skill ratio |\n")
        w(f"| flag weight (regular / non) | {p.flag_w_regular} / {p.flag_w_nonregular} | relative-flag reward |\n")
        w(f"| flag cap | {p.flag_cap} | max objective bonus |\n")
        w(f"| death weight / cap | {p.death_w} / {p.death_cap} | death penalty |\n")
        w(f"| participation floor | {p.part_floor} | floor on the regular threshold |\n")
        if extra:
            w(extra)

    w("\n---\n\n## The three calculations\n")
    knob_table("Old KTPR", pO)
    knob_table("Current KTPR", pC)
    w("\n### New KTPR (team-contribution formula)\n")
    w("A different shape from old/current: a **weighted average of normalized "
      "contributions** (1.0 = average tournament player), so support stats can "
      "substitute for kills and one-dimensional fraggers normalize toward the "
      "middle. Judged **within each role** (Rifle/Sniper/Heavy/SMG).\n\n")
    w("| knob | value | meaning |\n|---|---|---|\n")
    w(f"| scale | {pN.scale} | average player scores ~1.0 |\n")
    w(f"| kill_exp | {pN.kill_exp} | <1 = diminishing returns on kill volume |\n")
    w(f"| tw_kill / tw_kd | {pN.tw_kill} / {pN.tw_kd} | kill volume vs K/D efficiency |\n")
    w(f"| tw_assist / tw_damage | {pN.tw_assist} / {pN.tw_damage} | assist & damage contribution |\n")
    w(f"| tw_flag / tw_break | {pN.tw_flag} / {pN.tw_break} | objective contribution (breaks valued high) |\n")
    w(f"| dmg_interaction / assist_interaction | {pN.dmg_interaction} / {pN.assist_interaction} | how much low kills amplify the damage & assist terms |\n")
    w(f"| ratio_floor / ratio_cap | {pN.ratio_floor} / {pN.ratio_cap} | one weak/strong stat can't drag/spike too far |\n")
    w(f"| class_normalize | {pN.class_normalize} | compare each player to their own role's median |\n")
    w(f"| role_weights | {pN.role_weights} | per-role final multiplier |\n")

    # ---------------------------------------------------------------- worked example
    top_i = min(range(len(players)), key=lambda i: rN.get(i, 1e9))
    tp = players[top_i]
    capped_kd = min(tp.kd_ratio, pC.kd_cap)
    core = capped_kd * (tp.kills_half / (mC["K"] or 1))
    w("\n---\n\n## Worked example — #1 by New KTPR: "
      f"**{tp.name}**\n")
    w(f"Raw per-half: K/D={tp.kd_ratio:.2f}, Kills/Half={tp.kills_half:.2f}, "
      f"Deaths/Half={tp.deaths_half:.2f}, Assists/Half={tp.assists_half:.2f}, "
      f"Damage/Half={tp.damage_half:.0f}, Flags/Half={tp.flags_half:.2f}, "
      f"Breaks/Half={tp.breaks_half:.2f} over {int(tp.matches)} matches.\n\n")
    w(f"- **Excel core** = min({tp.kd_ratio:.2f}, 1.1) x ({tp.kills_half:.2f} / "
      f"{mC['K']:.2f}) = {capped_kd:.2f} x {tp.kills_half/(mC['K'] or 1):.2f} "
      f"= **{core:.3f}**\n")
    w(f"- **Old** = core x flag/death factors x {pO.scale} = **{fmt(old[top_i])}**\n")
    w(f"- **Current** = core x (lower flag reward) x {pC.scale} = **{fmt(cur[top_i])}**\n")
    w(f"- **New (team)** = weighted average of their kill/K-D/assist/damage/flag/break "
      f"contributions vs the **{tp.role}** median, x death adjust = **{fmt(new[top_i])}** "
      f"(a different structure — see §New).\n")

    # ---------------------------------------------------------------- main table
    styles = E.classify_styles(players, pN)
    w("\n---\n\n## Full ranked comparison (sorted by New KTPR)\n")
    w("`Δ` = rank change Current→New (＋ = moved up under New). **Style** = KTPR "
      "quality tier + playstyle (profile vs global median).\n\n")
    def kda(pl):
        return (pl.kills_half + pl.assists_half) / pl.deaths_half if pl.deaths_half else pl.kills_half + pl.assists_half

    w("| # | Player | role | M | K/D | KDA | K/H | D/H | A/H | Dmg/H | Fl/H | Br/H "
      "| Old | Cur | **New** | Δ | Style |\n")
    w("|--:|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|\n")
    order = sorted([i for i in range(len(players)) if players[i].name and new[i] is not None],
                   key=lambda i: -new[i])
    for i in order:
        pl = players[i]
        d = (rC.get(i) - rN.get(i)) if (rC.get(i) and rN.get(i)) else 0
        dstr = f"+{d}" if d > 0 else (str(d) if d < 0 else "0")
        w(f"| {rN.get(i)} | {esc(pl.name)} | {pl.role} | {int(pl.matches)} | {pl.kd_ratio:.2f} | {kda(pl):.2f} | "
          f"{pl.kills_half:.1f} | {pl.deaths_half:.1f} | {pl.assists_half:.1f} | "
          f"{pl.damage_half:.0f} | {pl.flags_half:.1f} | {pl.breaks_half:.1f} | "
          f"{fmt(old[i])} | {fmt(cur[i])} | **{fmt(new[i])}** | {dstr} | {styles[i]} |\n")

    # ---------------------------------------------------------------- movers
    w("\n---\n\n## Biggest movers, Current → New\n")
    movers = sorted(
        [(players[i].name, rC.get(i), rN.get(i), rC.get(i) - rN.get(i))
         for i in range(len(players)) if players[i].name and rC.get(i) and rN.get(i)],
        key=lambda t: -abs(t[3]))
    w("| Player | Cur rank | New rank | Δ | why |\n|---|--:|--:|--:|---|\n")
    for name, rc, rn, d in movers[:12]:
        why = "rewarded by assists/damage/breaks" if d > 0 else "leaned on kills/flags the new stats discount"
        w(f"| {esc(name)} | {rc} | {rn} | {'+' if d>0 else ''}{d} | {why} |\n")

    w("\n---\n\n*Regenerate anytime: `python make_report.py` (via PowerShell). "
      "Tune weights in `weights.toml` and re-run to see rankings shift.*\n")

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("".join(L))
    print(f"Wrote {OUT}  ({len(order)} players ranked)")


if __name__ == "__main__":
    main()