#!/usr/bin/env python3
"""Nightly markdown: who taunts whom. A voice-menu command or hand signal sent within --window
seconds after the speaker's own kill, with the victim named.

Players asked for voice-command counts; drew asked which of them are taunts. KTPHLStatsX
migration 045 + stats_logging 1.28.0 (shipped inside 1.30.0) land every voice-menu press as a
`hlstats_Events_PlayerActions` row with `match_id`, so this is a read over two tables:

  press      one PlayerActions row, code `voice_*` or `signal_*` (hand signals, migration 048,
             stats_logging 1.32.0), inside a tracked match
  taunt      a press whose nearest own kill (`hlstats_Events_Frags.killerId` = speaker) is
             <= --window seconds before it; the victim of that kill is the target
  distinct   presses by one speaker in one logged second collapse to one -- the key is
             spammed (9 presses in one second was measured on the first night) while DoD plays
             the sound once per cooldown. Leaderboards count distinct taunts and show two press
             columns: key presses DURING taunts, and the speaker's peak presses in any one
             second across all their commands (spam), so a held or mashed key stands out --
             drew asked, 2026-10-24, after Jonski read as "1 taunt, 18 presses"
  per match  distinct taunts / matches the speaker appeared in (`ktp_match_players`) WHERE the
             server was running a plugin that captures voice commands (capture manifest
             `producer_version` >= 1.28.0; drew's correction 2026-10-23 -- the first cut divided
             by every match of the season and read as 0.11 per match for a player whose ten
             taunts all came in the two matches that could have recorded one)

Names are the league's where the league knows the player: the website's `ktp.player.alias`,
joined through `ktp.player_steam.steam_id64` to the hlstatsx steam id -- the same index
`report_sync.py` applies to match reports (drew's ruling 2026-10-23). A player the website does
not know keeps the alias they played under. The index comes from PostgREST with the credentials
in `/etc/ktp/reports.env` (`KTP_SUPABASE_URL`, `KTP_SUPABASE_SECRET_KEY`); without them, or if
the fetch fails, the report still runs on in-game names and says so in its header.

Two leaderboards: official matches only (match_type 0/4) and every tracked type. Then the
most-taunted players, and one section per speaker listing their victims -- the "search" in a
markdown file is Ctrl-F on the speaker's name.

Hidden by construction: the report is a file on the data server (`--out`), published to the
PRIVATE coordination repo. `--website` also upserts the same numbers (snapshot(), one JSON row per
day) into `ktp.voice_taunt_snapshot`, which only KTP admins can read: keep-the-prac's
/admin/voice-taunts renders it (drew, 2026-10-30). Never a public table.

MySQL is read-only over the local socket, no credentials, same as weekly_outliers.py.

    voice_taunts.py --out /var/lib/ktp-voice-taunts/latest.md [--tsv presses.tsv]
                    [--since 2026-09-13] [--window 5] [--top 25] [--no-aliases] [--website]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import subprocess
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone

TYPE_NAME = {0: "official", 1: "scrim", 2: "12man", 3: "draft", 4: "official", 5: "draft"}
OFFICIAL = (0, 4)
# Nearest own kill is searched this far back; --window then decides what counts. Wider than
# any sensible window on purpose, so the TSV keeps the delta and the cut can move later
# without a new query.
LOOKBACK = 10
# stats_logging 1.28.0 is the first producer that emits voice-command lines; a match whose
# capture manifest names an older producer could not have recorded one and is not a
# denominator for "per match".
MIN_PRODUCER = (1, 28, 0)
# Canonical copy: scripts/player_alias.py (steam64_to_hlstats). Duplicated because this file
# deploys standalone to /usr/local/bin with no package to import from. Keep the two in step.
STEAM64_BASE = 76561197960265728
PAGE_SIZE = 1000
MAX_PAGES = 100


def q(sql: str, db: str) -> list[list[str]]:
    proc = subprocess.run(["mysql", "-N", "--batch", "--raw", "--default-character-set=utf8mb4",
                           db, "-e", sql], capture_output=True, text=True)
    if proc.returncode:
        raise SystemExit(f"mysql failed ({proc.returncode}): "
                         f"{proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else 'no stderr'}")
    return [line.split("\t") for line in proc.stdout.splitlines() if line]


def presses_sql(since: str) -> str:
    # One row per (press, candidate own kill in the lookback); Python keeps the nearest.
    # LEFT JOIN so a press with no kill behind it is still a press (the denominator for
    # "share of voice commands that are taunts").
    return f"""
SELECT pa.id, pa.eventTime, pa.match_id, m.match_type, a.code,
       pa.playerId, sp.lastName,
       IFNULL(f.victimId, ''), IFNULL(vp.lastName, ''), IFNULL(f.weapon, ''),
       IFNULL(TIMESTAMPDIFF(SECOND, f.eventTime, pa.eventTime), '')
FROM hlstats_Events_PlayerActions pa
JOIN hlstats_Actions a ON a.id = pa.actionId AND (a.code LIKE 'voice\\\\_%' OR a.code LIKE 'voicemenu\\\\_%' OR a.code LIKE 'signal\\\\_%')
JOIN (SELECT match_id, MIN(match_type) AS match_type, MIN(start_time) AS start_time
      FROM ktp_matches GROUP BY match_id) m ON m.match_id = pa.match_id
JOIN hlstats_Players sp ON sp.playerId = pa.playerId
LEFT JOIN hlstats_Events_Frags f
       ON f.killerId = pa.playerId
      AND f.eventTime BETWEEN pa.eventTime - INTERVAL {LOOKBACK} SECOND AND pa.eventTime
LEFT JOIN hlstats_Players vp ON vp.playerId = f.victimId
WHERE m.start_time >= '{since}' AND m.match_type IS NOT NULL
ORDER BY pa.eventTime, pa.id"""


def played_sql(since: str) -> str:
    return f"""
SELECT DISTINCT mp.player_id, m.match_type, mp.match_id
FROM ktp_match_players mp
JOIN (SELECT match_id, MIN(match_type) AS match_type, MIN(start_time) AS start_time
      FROM ktp_matches GROUP BY match_id) m ON m.match_id = mp.match_id
WHERE m.start_time >= '{since}' AND m.match_type IS NOT NULL"""


def manifests_sql(since: str) -> str:
    return f"""
SELECT DISTINCT cm.match_id, cm.producer_version
FROM ktp_capture_manifests cm
JOIN (SELECT match_id, MIN(start_time) AS start_time FROM ktp_matches GROUP BY match_id) m
  ON m.match_id = cm.match_id
WHERE m.start_time >= '{since}'"""


def version_tuple(v: str) -> tuple[int, ...]:
    out = []
    for part in v.strip().split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        if not digits:
            break
        out.append(int(digits))
    return tuple(out)


def voice_capable_matches(manifest_rows: list[list[str]]) -> set[str]:
    """Matches where at least one half ran a producer that emits voice lines."""
    return {mid for mid, ver in manifest_rows if version_tuple(ver) >= MIN_PRODUCER}


def matches_played(played_rows: list[list[str]], capable: set[str]) -> dict[tuple[int, int], int]:
    """(player_id, match_type) -> matches appeared in that could have recorded a voice command."""
    seen: dict[tuple[int, int], set[str]] = defaultdict(set)
    for pid, mtype, mid in played_rows:
        if mid in capable:
            seen[(int(pid), int(mtype))].add(mid)
    return {k: len(v) for k, v in seen.items()}


STEAM_SQL = "SELECT playerId, uniqueId FROM hlstats_PlayerUniqueIds WHERE game = 'dod'"


# --- league names ------------------------------------------------------------------

def steam64_to_hlstats(steam_id64) -> str | None:
    """76561198000000000 -> '0:20000136'. None when unparseable."""
    try:
        n = int(steam_id64) - STEAM64_BASE
    except (TypeError, ValueError):
        return None
    return f"{n % 2}:{n // 2}" if n >= 0 else None


def build_alias_index(players: list[dict], player_steam: list[dict]) -> dict[str, str]:
    """hlstatsx steam id -> website alias. Former steam ids kept: the match still belongs to them."""
    alias_of = {p["id"]: p.get("alias") for p in players}
    index: dict[str, str] = {}
    for row in player_steam:
        key = steam64_to_hlstats(row.get("steam_id64"))
        alias = alias_of.get(row.get("player_id"))
        if key and alias and str(alias).strip():
            index[key] = str(alias).strip()
    return index


def postgrest_all(path: str) -> list[dict]:
    """Every row at `path`, paged; stop on an empty page, never a short one (report_sync's rule)."""
    base = os.environ["KTP_SUPABASE_URL"].rstrip("/")
    key = os.environ["KTP_SUPABASE_SECRET_KEY"]
    joiner = "&" if "?" in path else "?"
    rows: list[dict] = []
    offset = 0
    for _ in range(MAX_PAGES):
        req = urllib.request.Request(
            f"{base}{path}{joiner}offset={offset}&limit={PAGE_SIZE}",
            headers={"apikey": key, "Authorization": f"Bearer {key}", "Accept-Profile": "ktp"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            page = json.loads(resp.read().decode("utf-8"))
        if not page:
            return rows
        rows.extend(page)
        offset += len(page)
    raise RuntimeError(f"{path}: still returning rows after {MAX_PAGES} pages")


def fetch_alias_index() -> tuple[dict[str, str], str | None]:
    """(index, problem). An empty index with a reason is a report on in-game names, not a failure."""
    if not os.environ.get("KTP_SUPABASE_URL") or not os.environ.get("KTP_SUPABASE_SECRET_KEY"):
        return {}, "KTP_SUPABASE_URL / KTP_SUPABASE_SECRET_KEY not set"
    try:
        return build_alias_index(postgrest_all("/rest/v1/player?select=id,alias"),
                                 postgrest_all("/rest/v1/player_steam?select=player_id,steam_id64")), None
    except (urllib.error.URLError, OSError, RuntimeError, ValueError) as exc:
        return {}, f"website unreachable: {exc}"


def resolve_names(events: list[dict], steam_of: dict[int, set[str]], alias_index: dict[str, str]) -> int:
    """League alias where any of the player's steam ids is known; else the in-game name stays.
    Returns how many distinct players were resolved."""
    def league(pid):
        for sid in sorted(steam_of.get(pid, ())):
            if sid in alias_index:
                return alias_index[sid]
        return None
    resolved: set[int] = set()
    for e in events:
        for id_key, name_key in (("speaker_id", "speaker"), ("victim_id", "victim")):
            pid = e.get(id_key)
            if pid is None:
                continue
            name = league(pid)
            if name:
                e[name_key] = name
                resolved.add(pid)
    return len(resolved)


# --- shaping --------------------------------------------------------------------------

def nearest(rows: list[list[str]]) -> list[dict]:
    """Collapse the join fan-out: one dict per press, carrying its nearest own kill (or none)."""
    by_press: dict[str, dict] = {}
    for pid, t, mid, mtype, code, spk, spk_name, vic, vic_name, weapon, secs in rows:
        d = by_press.setdefault(pid, {
            "press_id": pid, "time": t, "match_id": mid, "match_type": int(mtype), "code": code,
            "speaker_id": int(spk), "speaker": spk_name, "victim_id": None, "victim": None,
            "weapon": None, "secs": None})
        if secs != "" and (d["secs"] is None or int(secs) < d["secs"]):
            d.update(victim_id=int(vic), victim=vic_name, weapon=weapon, secs=int(secs))
    return list(by_press.values())


def distinct(presses: list[dict]) -> list[dict]:
    """Same speaker, same code, same logged second = one event; `presses` counts the spam."""
    out: dict[tuple, dict] = {}
    for p in presses:
        k = (p["speaker_id"], p["time"], p["code"])
        if k not in out:
            out[k] = dict(p, presses=0)
        out[k]["presses"] += 1
        if p["secs"] is not None and (out[k]["secs"] is None or p["secs"] < out[k]["secs"]):
            out[k].update(victim_id=p["victim_id"], victim=p["victim"], weapon=p["weapon"], secs=p["secs"])
    return list(out.values())


def command_of(code: str) -> tuple[str, str]:
    """(command, via): `voicemenu_negative` and `voice_negative` are the same command, sent two ways.
    via = "menu" for a voice-menu pick (stats_logging 1.33.0, migration 049), "bound" for a bound key,
    "signal" for a hand signal (DoD's signal menu is client-side and always sends the command)."""
    if code.startswith("voicemenu_"):
        return "voice_" + code[len("voicemenu_"):], "menu"
    return code, ("signal" if code.startswith("signal_") else "bound")


def is_taunt(e: dict, window: int) -> bool:
    return e["secs"] is not None and e["secs"] <= window


def leaderboard(events: list[dict], played: dict[tuple[int, int], int], types: tuple[int, ...],
                window: int) -> list[dict]:
    taunts = [e for e in events if e["match_type"] in types and is_taunt(e, window)]
    by_spk: dict[int, dict] = {}
    for e in taunts:
        s = by_spk.setdefault(e["speaker_id"], {
            "speaker_id": e["speaker_id"], "speaker": e["speaker"], "taunts": 0, "presses": 0,
            "victims": defaultdict(int), "codes": defaultdict(int), "matches_with": set(), "menu": 0})
        s["taunts"] += 1
        s["presses"] += e["presses"]
        s["victims"][e["victim"]] += 1
        s["codes"][command_of(e["code"])[0]] += 1
        s["menu"] += command_of(e["code"])[1] == "menu"
        s["matches_with"].add(e["match_id"])
        s["speaker"] = e["speaker"]  # latest name wins
    # Peak presses in one logged second, over EVERY command the speaker sent in scope, not only
    # taunts: the 37-press burst that produced Jonski's single taunt was mostly outside it.
    peak: dict[int, int] = defaultdict(int)
    for e in events:
        if e["match_type"] in types:
            peak[e["speaker_id"]] = max(peak[e["speaker_id"]], e["presses"])
    rows = []
    for s in by_spk.values():
        n = sum(played.get((s["speaker_id"], t), 0) for t in types)
        rows.append({
            "speaker": s["speaker"], "taunts": s["taunts"], "presses": s["presses"],
            "peak": peak[s["speaker_id"]], "menu": s["menu"],
            "matches": n, "matches_with": len(s["matches_with"]),
            "per_match": (s["taunts"] / n) if n else None,
            # Spread vs intensity (drew, 2026-10-24): 12 taunts in one match and one taunt in each
            # of twelve read the same per match; these two tell them apart.
            "share": (len(s["matches_with"]) / n) if n else None,
            "per_taunting": s["taunts"] / len(s["matches_with"]),
            "top_victim": max(s["victims"].items(), key=lambda kv: (kv[1], kv[0]))[0],
            "top_code": max(s["codes"].items(), key=lambda kv: (kv[1], kv[0]))[0],
        })
    # Rank floor (drew, 2026-10-28): one match with 3 taunts must not outrank 69 over 15, so a speaker
    # needs at least half the median match count of this board's speakers to be ranked; the rest follow, unranked.
    median = statistics.median(r["matches"] for r in rows) if rows else 0
    floor = max(1, math.ceil(median / 2))
    for r in rows:
        r["ranked"], r["floor"], r["median"] = r["matches"] >= floor, floor, median
    rows.sort(key=lambda r: (not r["ranked"], -(r["per_match"] or 0), -r["taunts"], r["speaker"]))
    return rows


def fmt(v, nd=2):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.{nd}f}"
    return str(v)


def pct(v) -> str:
    return "—" if v is None else f"{round(100 * v)}%"


def esc(s: str) -> str:
    return s.replace("|", "\\|")


def snapshot(events: list[dict], played: dict[tuple[int, int], int], window: int,
             since: str, generated: str, names_note: str = "") -> dict:
    """Everything the report shows, as data. The markdown renders it and the website's admin page
    stores it as-is (ktp.voice_taunt_snapshot), so the two can never disagree."""
    all_types = tuple(sorted({e["match_type"] for e in events}))
    taunts = [e for e in events if is_taunt(e, window)]
    boards = []
    for key, title, types in (("official", "Official matches", OFFICIAL), ("all", "All match types", all_types)):
        rows = leaderboard(events, played, types, window)
        boards.append({"key": key, "title": title, "types": sorted({TYPE_NAME[t] for t in types}),
                       "floor": rows[0]["floor"] if rows else None, "median": rows[0]["median"] if rows else None,
                       "rows": [{k: v for k, v in r.items() if k not in ("floor", "median")} for r in rows]})
    victims: dict[str, dict] = {}
    for e in taunts:
        v = victims.setdefault(e["victim"], {"n": 0, "by": defaultdict(int)})
        v["n"] += 1
        v["by"][e["speaker"]] += 1
    by_spk: dict[str, list[dict]] = defaultdict(list)
    for e in taunts:
        by_spk[e["speaker"]].append(e)
    speakers = []
    for spk, es in sorted(by_spk.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        per: dict[str, dict] = {}
        for e in es:
            v = per.setdefault(e["victim"], {"n": 0, "codes": defaultdict(int), "menu": defaultdict(int), "weapons": defaultdict(int), "last": ""})
            v["n"] += 1
            cmd, via = command_of(e["code"])
            v["codes"][cmd] += 1
            v["menu"][cmd] += via == "menu"
            v["weapons"][e["weapon"]] += 1
            v["last"] = max(v["last"], e["time"])
        speakers.append({"speaker": spk, "taunts": len(es), "presses": sum(e["presses"] for e in es), "victims": [
            {"victim": name, "n": v["n"], "last": v["last"],
             "codes": [[c, n, v["menu"][c]] for c, n in sorted(v["codes"].items(), key=lambda kv: -kv[1])],
             "weapons": [[w, n] for w, n in sorted(v["weapons"].items(), key=lambda kv: -kv[1])]}
            for name, v in sorted(per.items(), key=lambda kv: (-kv[1]["n"], kv[0]))]})
    codes: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    for e in events:
        cmd, via = command_of(e["code"])
        c = codes[cmd]
        c[0] += 1
        c[1] += via != "menu"
        c[2] += via == "menu"
        c[3] += is_taunt(e, window)
    hist: dict[str, int] = defaultdict(int)
    for e in events:
        hist["none within %d s" % LOOKBACK if e["secs"] is None else str(e["secs"])] += 1
    return {
        "generated": generated, "since": since, "window": window, "names_note": names_note,
        "presses": sum(e["presses"] for e in events), "distinct": len(events), "taunts": len(taunts),
        "boards": boards,
        "victims": [{"victim": name, "n": v["n"], "by": sorted(v["by"].items(), key=lambda kv: (-kv[1], kv[0]))}
                    for name, v in sorted(victims.items(), key=lambda kv: (-kv[1]["n"], kv[0]))],
        "speakers": speakers,
        "shape": [{"type": TYPE_NAME[t], "code": t,
                   "presses": sum(e["presses"] for e in events if e["match_type"] == t),
                   "distinct": sum(1 for e in events if e["match_type"] == t),
                   "taunts": sum(1 for e in events if e["match_type"] == t and is_taunt(e, window))}
                  for t in all_types],
        "commands": [{"command": c, "distinct": n, "bound": b, "menu": m, "taunts": t}
                     for c, (n, b, m, t) in sorted(codes.items(), key=lambda kv: -kv[1][0])],
        "delays": [[k, hist[k]] for k in sorted(hist, key=lambda k: (k.startswith("none"), int(k) if k.isdigit() else 0))],
    }


def report(events: list[dict], played: dict[tuple[int, int], int], window: int, top: int,
           since: str, generated: str, names_note: str = "") -> str:
    return render(snapshot(events, played, window, since, generated, names_note), top)


def render(S: dict, top: int) -> str:
    window, generated, since = S["window"], S["generated"], S["since"]
    L = ["# Voice taunts", "",
         f"Generated {generated}. Tracked matches since {since}, every type. "
         f"{S['presses']} voice/signal presses = {S['distinct']} distinct commands; "
         f"{S['taunts']} of those came within {window} s of the speaker's own kill "
         f"({100 * S['taunts'] / S['distinct']:.0f}%)." if S["distinct"] else
         f"Generated {generated}. No voice commands in tracked matches since {since}.", "",
         f"A taunt = a voice command or hand signal <= {window} s after the speaker's own kill; the victim of that "
         "kill is the target. Presses by one speaker in one second count once (the key is spammed; "
         "DoD plays the sound once per cooldown). Key presses (during taunts) = raw presses inside those taunt "
         "seconds; spam = the most presses the speaker sent in any one second, taunt or not. "
         "Via voice menu = how many of those taunts were picked from DoD's voice menu rather than a bound key "
         "(recorded from stats_logging 1.33.0; earlier menu picks were never logged). "
         "% of matches taunted = matches with a taunt / voice-capable matches; taunts per taunting match = "
         "taunts / matches with a taunt, so one heavy match and steady taunting no longer look alike. "
         "Per match = taunts / matches the speaker appeared in "
         "on a server whose plugin captures voice commands (stats_logging >= 1.28.0, live fleet-wide since "
         "2026-10-22); earlier matches could not have recorded one and are not counted. "
         + (S["names_note"] or "Names: league alias where the website knows the player, else the in-game alias."),
         ""]
    for b in S["boards"]:
        rows = b["rows"]
        L += [f"## {b['title']} — top {min(top, len(rows))} of {len(rows)} speakers "
              f"(sorted by per match; types {', '.join(b['types'])})", ""]
        if not rows:
            L += ["none", ""]
            continue
        L += [f"Ranked: speakers with at least {b['floor']} voice-capable matches (half the median of "
              f"{b['median']:g}); fewer than that are listed after, unranked (#  -).", ""]
        L += ["| # | speaker | taunts | key presses (during taunts) | spam (peak presses / s) | matches (voice-capable) | matches with a taunt | % of matches taunted | per match | taunts per taunting match | favourite target | favourite command | via voice menu |",
              "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
        for i, r in enumerate(rows[:top], 1):
            L.append(f"| {i if r['ranked'] else '-'} | {esc(r['speaker'])} | {r['taunts']} | {r['presses']} | {r['peak']} | {r['matches']} "
                     f"| {r['matches_with']} | {pct(r['share'])} | {fmt(r['per_match'])} | {fmt(r['per_taunting'])} "
                     f"| {esc(r['top_victim'])} | {r['top_code']} | {r['menu']} of {r['taunts']} |")
        L.append("")
    victims = S["victims"]
    L += [f"## Most taunted — top {min(top, len(victims))} of {len(victims)}", ""]
    if victims:
        L += ["| # | victim | taunts received | from |", "|---|---|---|---|"]
        for i, v in enumerate(victims[:top], 1):
            by = ", ".join(f"{esc(s)} {n}" for s, n in v["by"][:4])
            L.append(f"| {i} | {esc(v['victim'])} | {v['n']} | {by} |")
    else:
        L.append("none")
    L.append("")
    L += ["## Per speaker (Ctrl-F a name)", ""]
    for sp in S["speakers"]:
        L += [f"### {esc(sp['speaker'])} — {sp['taunts']} taunts, {sp['presses']} key presses during taunts", "",
              "| victim | taunts | commands | weapons | last |", "|---|---|---|---|---|"]
        for v in sp["victims"]:
            codes = ", ".join(f"{c} {n}" + (f" (menu {m})" if m else "") for c, n, m in v["codes"])
            weapons = ", ".join(f"{w} {n}" for w, n in v["weapons"][:3])
            L.append(f"| {esc(v['victim'])} | {v['n']} | {codes} | {weapons} | {v['last']} |")
        L.append("")
    L += ["## Shape", "", "| | presses | distinct | taunts |", "|---|---|---|---|"]
    for t in S["shape"]:
        L.append(f"| {t['type']} ({t['code']}) | {t['presses']} | {t['distinct']} | {t['taunts']} |")
    L += ["", "| command | distinct | bound key | voice menu | taunts |", "|---|---|---|---|---|"]
    for c in S["commands"]:
        L.append(f"| {c['command']} | {c['distinct']} | {c['bound']} | {c['menu']} | {c['taunts']} |")
    L += ["", "| seconds after own kill | distinct voice commands |", "|---|---|"]
    for k, n in S["delays"]:
        L.append(f"| {k} | {n} |")
    return "\n".join(L) + "\n"


def publish_snapshot(S: dict, day: str) -> None:
    """Upsert tonight's snapshot into ktp.voice_taunt_snapshot, which only KTP admins can read on the
    website. Keyed by date: a rerun replaces the day, and a retry after a lost reply is safe."""
    base = os.environ["KTP_SUPABASE_URL"].rstrip("/")
    key = os.environ["KTP_SUPABASE_SECRET_KEY"]
    req = urllib.request.Request(
        f"{base}/rest/v1/voice_taunt_snapshot?on_conflict=snapshot_date", method="POST",
        data=json.dumps({"snapshot_date": day, "payload": S}).encode("utf-8"),
        headers={"apikey": key, "Authorization": f"Bearer {key}", "Content-Profile": "ktp",
                 "Content-Type": "application/json", "Prefer": "resolution=merge-duplicates,return=minimal"})
    with urllib.request.urlopen(req, timeout=60):
        pass


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", default="hlstatsx")
    ap.add_argument("--since", default="2026-09-13", help="season floor; matches starting before it are ignored")
    ap.add_argument("--window", type=int, default=5, help="seconds after the speaker's own kill that make a voice command a taunt")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--out", help="write the markdown here instead of stdout")
    ap.add_argument("--tsv", help="also dump every distinct voice command with its nearest-kill delta")
    ap.add_argument("--no-aliases", action="store_true", help="skip the website lookup; in-game names only")
    ap.add_argument("--website", action="store_true",
                    help="also upsert the snapshot into ktp.voice_taunt_snapshot (the admin page reads it)")
    a = ap.parse_args()
    if a.window > LOOKBACK:
        raise SystemExit(f"--window {a.window} exceeds the {LOOKBACK} s lookback the query carries")

    rc = 0
    events = distinct(nearest(q(presses_sql(a.since), a.db)))
    capable = voice_capable_matches(q(manifests_sql(a.since), a.db))
    played = matches_played(q(played_sql(a.since), a.db), capable)
    names_note = ""
    if a.no_aliases:
        names_note = "Names: in-game aliases (--no-aliases)."
    else:
        index, problem = fetch_alias_index()
        if problem:
            names_note = f"Names: in-game aliases only — league lookup skipped ({problem})."
            print(f"warning: {problem}; in-game names used", file=sys.stderr)
        else:
            steam_of: dict[int, set[str]] = defaultdict(set)
            for pid, sid in q(STEAM_SQL, a.db):
                steam_of[int(pid)].add(sid)
            players = {e["speaker_id"] for e in events} | {e["victim_id"] for e in events if e["victim_id"] is not None}
            n = resolve_names(events, steam_of, index)
            names_note = (f"Names: league alias for {n} of {len(players)} players the website knows "
                          f"({len(index)} linked steam ids); the rest keep the alias they played under.")
    now = datetime.now(timezone.utc)
    generated = now.strftime("%Y-%m-%d %H:%M UTC")
    snap = snapshot(events, played, a.window, a.since, generated, names_note)
    text = render(snap, a.top)
    if a.website:
        # A failed upsert must not cost the night's markdown: write it anyway, exit 3 (website only)
        # so the unit still publishes the files and then fails, which fires the alert.
        try:
            publish_snapshot(snap, now.strftime("%Y-%m-%d"))
            print(f"website: ktp.voice_taunt_snapshot upserted for {now:%Y-%m-%d}")
        except (KeyError, urllib.error.URLError, TimeoutError) as exc:
            print(f"website: snapshot NOT published ({exc!r})", file=sys.stderr)
            rc = 3
    if a.out:
        with open(a.out, "w", encoding="utf-8") as fh:
            fh.write(text)
        taunts = sum(1 for e in events if is_taunt(e, a.window))
        print(f"voice taunts: {len(events)} distinct voice commands, {taunts} taunts within {a.window} s, "
              f"{len({e['speaker_id'] for e in events})} speakers; report: {a.out}")
    else:
        sys.stdout.write(text)
    if a.tsv:
        cols = ["time", "match_id", "match_type", "code", "speaker_id", "speaker", "presses",
                "secs", "victim_id", "victim", "weapon"]
        with open(a.tsv, "w", encoding="utf-8") as fh:
            fh.write("\t".join(cols) + "\n")
            for e in sorted(events, key=lambda e: e["time"]):
                fh.write("\t".join("" if e.get(c) is None else str(e.get(c)) for c in cols) + "\n")
    return rc


if __name__ == "__main__":
    sys.exit(main())
