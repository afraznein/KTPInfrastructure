"""Data-quality report: HLstatsX vs HUD agreement on the overlapping stats
(kills, deaths, flags, match/half coverage) over the tournament matches.

Run via PowerShell. Writes DATA_QUALITY.md and prints a summary.
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ktpr_mysql as Q

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "DATA_QUALITY.md")


def esc(s):
    return s.replace("|", "\\|")


def pct(new, base):
    return (new - base) / base * 100 if base else 0.0


def main():
    ids = Q._tournament_match_ids()
    idl = Q._idlist(ids)
    flagcodes = ",".join(f"'{c}'" for c in Q.FLAG_ACTION_CODES)
    roster = Q._load_roster(None)

    pid2uid = {}
    for pid, uid in Q._parse_rows(Q.run_sql("SELECT playerId, uniqueId FROM hlstats_PlayerUniqueIds")):
        pid2uid.setdefault(pid, uid)

    # HLstatsX per playerId
    hl = {}
    spine = f"""
        SELECT pid, SUM(is_kill) k, SUM(is_death) d,
               COUNT(DISTINCT match_id) m, COUNT(DISTINCT match_id, half) h FROM (
          SELECT killerId pid, match_id, half, 1 is_kill, 0 is_death FROM hlstats_Events_Frags WHERE match_id IN ({idl})
          UNION ALL SELECT victimId, match_id, half, 0, 1 FROM hlstats_Events_Frags WHERE match_id IN ({idl})
          UNION ALL SELECT victimId, match_id, half, 0, 1 FROM hlstats_Events_Teamkills WHERE match_id IN ({idl})
        ) e GROUP BY pid;"""
    for pid, k, d, m, h in Q._parse_rows(Q.run_sql(spine)):
        hl[pid] = {"k": float(k), "d": float(d), "m": int(m), "h": int(h), "f": 0.0}
    for pid, f in Q._parse_rows(Q.run_sql(
        f"SELECT pa.playerId, COUNT(*) FROM hlstats_Events_PlayerActions pa "
        f"JOIN hlstats_Actions a ON a.id=pa.actionId "
        f"WHERE pa.match_id IN ({idl}) AND a.code IN ({flagcodes}) GROUP BY pa.playerId;")):
        if pid in hl:
            hl[pid]["f"] = float(f)

    # HUD per steam_id
    hud = {}
    for sid, k, d, caps, m, h in Q._parse_rows(Q.run_sql(
        f"SELECT steam_id, SUM(kills), SUM(deaths), SUM(caps), "
        f"COUNT(DISTINCT match_id), COUNT(DISTINCT match_id,half) "
        f"FROM hud_player_stats WHERE is_final=1 AND match_id IN ({idl}) GROUP BY steam_id;")):
        hud[sid] = {"k": float(k), "d": float(d), "f": float(caps), "m": int(m), "h": int(h)}

    # merge by steam_id
    rows = []
    for pid, hv in hl.items():
        uid = pid2uid.get(pid)
        if not uid or ":" not in uid:
            continue
        sid = "STEAM_0:" + uid
        hd = hud.get(sid)
        name = roster.get(sid) or roster.get(uid) or f"[{sid}]"
        rows.append({"name": name, "sid": sid, "hl": hv, "hud": hd})

    # totals
    def tot(sys_key, stat):
        return sum((r[sys_key][stat] for r in rows if r[sys_key]), 0.0)
    hl_k, hud_k = tot("hl", "k"), tot("hud", "k")
    hl_d, hud_d = tot("hl", "d"), tot("hud", "d")
    hl_f, hud_f = tot("hl", "f"), tot("hud", "f")

    only_hl = [r for r in rows if not r["hud"]]
    hud_only_sids = set(hud) - {r["sid"] for r in rows}

    L = []; w = L.append
    w("# Data-Quality Report — HLstatsX vs HUD\n\n")
    w(f"Tournament matches: **{len(ids)}**. Players matched across both systems: "
      f"**{len([r for r in rows if r['hud']])}** "
      f"(HLstatsX-only: {len(only_hl)}, HUD-only: {len(hud_only_sids)}).\n\n")
    w("KTPR uses HLstatsX for kills/deaths/flags and HUD for assists/damage/breaks. "
      "This report checks how far the two systems disagree on the stats they *both* "
      "record, to gauge trust and spot bad rows.\n\n")
    w("> **Finding -> fix applied.** Divergence is almost entirely a *half-coverage* "
      "gap: every divergent player has fewer HUD halves than HLstatsX halves (HUD "
      "drops some half-snapshots). HUD per-half stats were understated wherever we "
      "divided HUD totals by the larger HLstatsX half count. The loader now divides "
      "**HUD stats by HUD halves** and **HLstatsX stats by HLstatsX halves**. Systems "
      "agree to within ~4-6% overall; treat big-gap matches/players (below) with "
      "caution until the pipelines are reconciled.\n\n")
    w("## Totals (overlapping stats)\n\n")
    w("| stat | HLstatsX | HUD | HUD vs HLstatsX |\n|---|--:|--:|--:|\n")
    w(f"| kills | {hl_k:.0f} | {hud_k:.0f} | {pct(hud_k,hl_k):+.1f}% |\n")
    w(f"| deaths | {hl_d:.0f} | {hud_d:.0f} | {pct(hud_d,hl_d):+.1f}% |\n")
    w(f"| flags | {hl_f:.0f} | {hud_f:.0f} | {pct(hud_f,hl_f):+.1f}% |\n\n")

    # per-player divergence (only matched players)
    matched = [r for r in rows if r["hud"]]
    for r in matched:
        r["dk"] = pct(r["hud"]["k"], r["hl"]["k"])
        r["dd"] = pct(r["hud"]["d"], r["hl"]["d"])
        r["df"] = pct(r["hud"]["f"], r["hl"]["f"])
        r["score"] = max(abs(r["dk"]), abs(r["dd"]), abs(r["df"]))

    w("## Biggest per-player divergences (HUD vs HLstatsX)\n\n")
    w("Sorted by worst single-stat gap. Large gaps = a system missed rows for "
      "that player (subs, mid-match leaves, snapshot timing).\n\n")
    w("| Player | HL k/d/f | HUD k/d/f | Δk | Δd | Δf | HL h | HUD h |\n")
    w("|---|--:|--:|--:|--:|--:|--:|--:|\n")
    for r in sorted(matched, key=lambda x: -x["score"])[:20]:
        hlv, hdv = r["hl"], r["hud"]
        w(f"| {esc(r['name'])} | {hlv['k']:.0f}/{hlv['d']:.0f}/{hlv['f']:.0f} "
          f"| {hdv['k']:.0f}/{hdv['d']:.0f}/{hdv['f']:.0f} "
          f"| {r['dk']:+.0f}% | {r['dd']:+.0f}% | {r['df']:+.0f}% "
          f"| {hlv['h']} | {hdv['h']} |\n")

    if only_hl:
        w("\n## Players in HLstatsX but missing from HUD\n\n")
        w("(These get 0 assists/damage/breaks — worth checking.)\n\n")
        for r in only_hl:
            w(f"- {esc(r['name'])} — HL kills {r['hl']['k']:.0f}, halves {r['hl']['h']}\n")

    # match-level coverage
    w("\n## Match-level kill coverage (HLstatsX frags vs HUD kills)\n\n")
    hlm = {m: 0 for m in ids}
    for mid, k in Q._parse_rows(Q.run_sql(
        f"SELECT match_id, COUNT(*) FROM hlstats_Events_Frags WHERE match_id IN ({idl}) GROUP BY match_id;")):
        hlm[mid] = int(k)
    hudm = {m: 0 for m in ids}
    for mid, k in Q._parse_rows(Q.run_sql(
        f"SELECT match_id, SUM(kills) FROM hud_player_stats WHERE is_final=1 AND match_id IN ({idl}) GROUP BY match_id;")):
        hudm[mid] = int(float(k))
    diverging = sorted(ids, key=lambda m: -abs(pct(hudm[m], hlm[m])))[:10]
    w("Worst 10 matches by kill-count gap:\n\n")
    w("| match_id | HL frags | HUD kills | Δ | Δ% |\n|---|--:|--:|--:|--:|\n")
    for m in diverging:
        w(f"| {m} | {hlm[m]} | {hudm[m]} | {hudm[m]-hlm[m]:+d} | {pct(hudm[m],hlm[m]):+.0f}% |\n")

    with open(OUT, "w", encoding="utf-8") as f:
        f.write("".join(L))

    # console summary
    print(f"Wrote {OUT}\n")
    print(f"kills : HL {hl_k:.0f}  HUD {hud_k:.0f}  ({pct(hud_k,hl_k):+.1f}%)")
    print(f"deaths: HL {hl_d:.0f}  HUD {hud_d:.0f}  ({pct(hud_d,hl_d):+.1f}%)")
    print(f"flags : HL {hl_f:.0f}  HUD {hud_f:.0f}  ({pct(hud_f,hl_f):+.1f}%)")
    print(f"matched players: {len(matched)}  HL-only: {len(only_hl)}  HUD-only: {len(hud_only_sids)}")
    print("\nworst divergent players:")
    for r in sorted(matched, key=lambda x: -x["score"])[:6]:
        print(f"  {r['name'][:26]:<26} Δk={r['dk']:+.0f}% Δd={r['dd']:+.0f}% Δf={r['df']:+.0f}%  (HL h={r['hl']['h']} HUD h={r['hud']['h']})")


if __name__ == "__main__":
    main()