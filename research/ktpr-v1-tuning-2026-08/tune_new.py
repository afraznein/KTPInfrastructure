"""Tuning view for the 'team' new-KTPR: current vs new, with archetype tags.

Run via PowerShell (needs DB). Writes NEW_KTPR_TUNING.md and prints a summary.
Edit weights.toml [profiles.new] and re-run to see the effect.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ktpr_engine as E
import ktpr_mysql as Q

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "NEW_KTPR_TUNING.md")


def ranks(vals):
    order = sorted([(i, v) for i, v in enumerate(vals) if v is not None], key=lambda t: -t[1])
    return {i: r for r, (i, v) in enumerate(order, 1)}


def esc(s):
    return s.replace("|", "\\|")


def main():
    players = Q.load_players_from_mysql()
    pC, pN = E.load_params("current"), E.load_params("new")
    cur = E.compute_ktpr(players, pC)
    new = E.compute_ktpr(players, pN)
    rC, rN = ranks(cur), ranks(new)

    # baselines to tag archetypes
    thr = E._participation_threshold(players, pN)
    regs = [pl for pl in players if pl.matches >= thr and pl.name] or [pl for pl in players if pl.name]
    med = lambda f: (E._median([f(pl) for pl in regs]) or 1.0)
    mK, mA, mD, mF, mB = med(lambda p: p.kills_half), med(lambda p: p.assists_half), \
        med(lambda p: p.damage_half), med(lambda p: p.flags_half), med(lambda p: p.breaks_half)

    styles = E.classify_styles(players, pN)

    L = []; w = L.append
    w("# New KTPR (team formula) — tuning view\n\n")
    w("Weighted average of contributions; 1.0 = average LAN player. "
      "Levers in `weights.toml [profiles.new]`. Δ = rank change Current→New. "
      "**Style** = quality tier (KTPR %ile) + playstyle (profile vs global median).\n\n")
    def kda(pl):
        return (pl.kills_half + pl.assists_half) / pl.deaths_half if pl.deaths_half else pl.kills_half + pl.assists_half

    w("| # | Player | role | K/D | KDA | K/H | A/H | Dmg/H | Fl/H | Br/H | Cur | **New** | Δ | style |\n")
    w("|--:|---|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|---|\n")
    order = sorted([i for i in range(len(players)) if players[i].name and new[i] is not None],
                   key=lambda i: -new[i])
    for i in order:
        pl = players[i]
        d = (rC.get(i) - rN.get(i)) if (rC.get(i) and rN.get(i)) else 0
        dstr = f"+{d}" if d > 0 else (str(d) if d < 0 else "0")
        w(f"| {rN[i]} | {esc(pl.name)} | {pl.role} | {pl.kd_ratio:.2f} | {kda(pl):.2f} | "
          f"{pl.kills_half:.1f} | {pl.assists_half:.1f} | {pl.damage_half:.0f} | {pl.flags_half:.1f} | "
          f"{pl.breaks_half:.1f} | {cur[i]:.2f} | **{new[i]:.2f}** | {dstr} | {styles[i]} |\n")
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("".join(L))

    # console summary
    print(f"Wrote {OUT}\n")
    print(f"baselines/half: kills={mK:.1f} assists={mA:.1f} damage={mD:.0f} flags={mF:.1f} breaks={mB:.2f}\n")
    # d = cur_rank - new_rank ; positive = rose (better), negative = fell
    movers = sorted([(players[i].name, styles[i], rC.get(i), rN.get(i), rC.get(i)-rN.get(i))
                     for i in order if rC.get(i) and rN.get(i)], key=lambda t: t[4])
    print("BIGGEST RISERS under new (team) formula:")
    for name, arc, rc, rn, d in movers[-6:][::-1]:
        print(f"  +{d:<3} {name[:26]:<26} [{arc}]  cur#{rc} -> new#{rn}")
    print("\nBIGGEST FALLERS (normalized down):")
    for name, arc, rc, rn, d in movers[:6]:
        print(f"  {d:<4} {name[:26]:<26} [{arc}]  cur#{rc} -> new#{rn}")

    # top player per role (sanity: elite in each class should surface)
    print("\nTOP OF EACH CLASS (new KTPR):")
    seen = set()
    for i in order:
        r = players[i].role
        if r not in seen:
            seen.add(r)
            print(f"  {r:<7} #{rN[i]:<3} {players[i].name[:30]}  (new {new[i]:.2f})")


if __name__ == "__main__":
    main()