"""
Best-effort inference of which mentioned player belongs to which team.

No single draft message splits its @mentions by side -- a match between
Team_Saab and Team_SpicyButtholes just lists everyone who showed up. But
across a team's matches its actual roster keeps reappearing while the
*opponent* changes match to match, so a player who's mentioned alongside a
team's emoji far more often than not is very likely on that team. That's the
signal this uses: frequency of co-occurrence with a team tag, leave-one-out
per match so a match isn't used to help classify its own players.

Two things make the raw signal weak if used naively, both addressed here:

1. Team emoji tags churn season to season -- almost always because Discord
   auto-appends a digit when a captain re-uploads an emoji whose name already
   exists on the server (Team_Revo -> Team_Revo2 -> Team_Revo3, Team_Clinic ->
   Team_Clinic2), sometimes with a missing "Team_" prefix (Volvo / Team_Volvo)
   or a typo'd prefix (Tean_ShiftplusW). `canon_team_key()` normalizes these
   so a team's matches across seasons pool into one roster instead of each
   variant getting its own thin, separate sample.
2. Draft-dump messages are a small slice of the channel. Any other message
   that pings a known team's emoji alongside player @mentions (schedule
   chatter, "TeamA vs TeamB" announcements, etc.) is real co-occurrence
   signal too, so the corpus scanned for roster inference is the *whole*
   crawled channel cache, not just the parsed drafts -- restricted to emoji
   names that normalize to a team a draft has already confirmed exists, so
   decorative/unrelated server emotes don't leak in as fake "teams".

Also flags players mentioned in a large fraction of matches *league-wide*
(any team) as likely organizers/casters/admins rather than a specific team's
player -- e.g. whoever keeps getting @mentioned because they post the
results, not because they played.

Everything here is inference, not ground truth -- read `note` and the two
frequency columns before trusting a close or data-thin call.

Usage:
    python build_rosters.py <channel_id> [--min-freq 0.4] [--min-matches 2]

Output (in --out-dir, default ./data):
    team_tag_map.csv           canonical_team, raw_tags_merged  (audit trail for the normalization)
    team_rosters.csv           team, player, matches_with_player, team_matches_with_mentions, frequency
    drafts_players_by_team.csv message_id, team_a, team_b, player, assigned_team, freq_team_a, freq_team_b, global_frequency, note
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
GLOBAL_ORGANIZER_THRESHOLD = 0.5  # mentioned in >50% of ALL teams' matches league-wide -> probably not "on" any one team

TEAM_EMOJI_RE = re.compile(r"<a?:([A-Za-z0-9_]+):\d+>")


def canon_team_key(raw_name: str) -> str:
    """Fold season-to-season emoji-name variants onto one key: fix the
    'Tean_' typo, drop a leading 'Team_' prefix, drop a trailing digit run
    (Discord's auto-dedup suffix on a re-uploaded same-name emoji)."""
    name = re.sub(r"^Tean_", "Team_", raw_name, flags=re.IGNORECASE)
    name = re.sub(r"^Team_", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\d+$", "", name)
    return name.lower()


def load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_jsonl(path: str):
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def known_team_keys(drafts: list[dict]) -> dict[str, Counter]:
    """canonical_key -> Counter of raw tag strings seen for it, sourced only
    from confirmed drafts (>=2 parsed pick/ban actions) to keep the allowlist
    free of decorative/unrelated server emoji."""
    keys: dict[str, Counter] = defaultdict(Counter)
    for r in drafts:
        for raw in r["teams"]:
            keys[canon_team_key(raw)][raw] += 1
    return keys


def display_name(raw_counter: Counter) -> str:
    # prefer a "Team_"-prefixed variant if one exists (reads as more "official"), else the most common raw form;
    # strip the "Team_"/"Tean_" prefix itself for display (it's just a namespace convention, not part of the name)
    prefixed = [name for name in raw_counter if re.match(r"^Tea[mn]_", name, re.IGNORECASE)]
    pool = prefixed if prefixed else list(raw_counter)
    best = max(pool, key=lambda n: raw_counter[n])
    return re.sub(r"^Tea[mn]_", "", best, flags=re.IGNORECASE)


def build_widened_index(all_messages, known_keys: set[str]) -> dict[str, list[tuple[str, dict[str, str]]]]:
    """canonical_team -> [(message_id, {player_id: username}), ...] for EVERY
    cached message (not just drafts) that references a known team's emoji
    and has at least one player mention."""
    idx: dict[str, list[tuple[str, dict[str, str]]]] = defaultdict(list)
    for msg in all_messages:
        mentions = msg.get("mentions") or []
        if not mentions:
            continue
        teams_here = {canon_team_key(name) for name in TEAM_EMOJI_RE.findall(msg.get("content", ""))}
        teams_here &= known_keys
        if not teams_here:
            continue
        players = {p["id"]: p.get("username") for p in mentions if p.get("id")}
        if not players:
            continue
        for t in teams_here:
            idx[t].append((msg["id"], players))
    return idx


def global_player_frequency(team_idx: dict) -> dict[str, float]:
    """player_id -> fraction of all (team, match)-with-mentions pairs league-wide that mention them."""
    total_pairs = 0
    counts: dict[str, int] = defaultdict(int)
    for matches in team_idx.values():
        for _, players in matches:
            total_pairs += 1
            for pid in players:
                counts[pid] += 1
    return {pid: c / total_pairs for pid, c in counts.items()} if total_pairs else {}


def _team_freq_excluding(team_idx: dict, team: str, exclude_message_id: str) -> tuple[dict[str, int], int]:
    """(player_id -> match count, total matches) for a team, leaving one match out."""
    matches = [(mid, players) for mid, players in team_idx.get(team, []) if mid != exclude_message_id]
    counts: dict[str, int] = defaultdict(int)
    for _, players in matches:
        for pid in players:
            counts[pid] += 1
    return counts, len(matches)


def build_team_rosters(team_idx: dict, global_freq: dict, min_freq: float, min_matches: int) -> list[dict]:
    rosters = []
    for team, matches in team_idx.items():
        total = len(matches)
        if total < min_matches:
            continue
        counts: dict[str, int] = defaultdict(int)
        names: dict[str, str] = {}
        for _, players in matches:
            for pid, uname in players.items():
                counts[pid] += 1
                names[pid] = uname
        for pid, c in counts.items():
            if global_freq.get(pid, 0.0) >= GLOBAL_ORGANIZER_THRESHOLD:
                continue  # mentioned across most/all teams league-wide -- organizer/caster, not a roster player
            freq = c / total
            if freq >= min_freq:
                rosters.append(
                    {
                        "team": team, "player_id": pid, "username": names[pid],
                        "matches_with_player": c, "team_matches_with_mentions": total,
                        "frequency": round(freq, 3),
                    }
                )
    rosters.sort(key=lambda r: (r["team"], -r["frequency"]))
    return rosters


def classify_match_players(drafts: list[dict], team_idx: dict, global_freq: dict) -> list[dict]:
    rows = []
    for r in drafts:
        if len(r["teams"]) != 2 or not r["players"]:
            continue
        t1, t2 = (canon_team_key(t) for t in r["teams"])
        c1, tot1 = _team_freq_excluding(team_idx, t1, r["message_id"])
        c2, tot2 = _team_freq_excluding(team_idx, t2, r["message_id"])
        for p in r["players"]:
            pid = p.get("id")
            if not pid:
                continue
            f1 = (c1.get(pid, 0) / tot1) if tot1 else None
            f2 = (c2.get(pid, 0) / tot2) if tot2 else None
            gfreq = global_freq.get(pid, 0.0)

            note = ""
            assigned = ""
            if gfreq >= GLOBAL_ORGANIZER_THRESHOLD:
                note = f"mentioned in {gfreq:.0%} of all matches league-wide -- likely organizer/caster, not a team player"
            elif f1 is None and f2 is None:
                note = "insufficient match history for both teams"
            elif (f1 or 0.0) == (f2 or 0.0):
                note = "tied / ambiguous"
            else:
                assigned = t1 if (f1 or 0.0) > (f2 or 0.0) else t2

            rows.append(
                {
                    "message_id": r["message_id"], "team_a": t1, "team_b": t2,
                    "player_id": pid, "username": p.get("username"),
                    "assigned_team": assigned,
                    "freq_team_a": round(f1, 3) if f1 is not None else "",
                    "freq_team_b": round(f2, 3) if f2 is not None else "",
                    "global_frequency": round(gfreq, 3),
                    "note": note,
                }
            )
    return rows


def write_outputs(tag_map: dict[str, Counter], rosters: list[dict], player_rows: list[dict], out_dir: str):
    os.makedirs(out_dir, exist_ok=True)

    with open(os.path.join(out_dir, "team_tag_map.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["canonical_team", "raw_tags_merged"])
        for key in sorted(tag_map):
            w.writerow([key, ";".join(sorted(tag_map[key]))])

    with open(os.path.join(out_dir, "team_rosters.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["team", "player_id", "username", "matches_with_player", "team_matches_with_mentions", "frequency"])
        w.writeheader()
        w.writerows(rosters)

    with open(os.path.join(out_dir, "drafts_players_by_team.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["message_id", "team_a", "team_b", "player_id", "username", "assigned_team", "freq_team_a", "freq_team_b", "global_frequency", "note"])
        w.writeheader()
        w.writerows(player_rows)


def _cli():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("channel_id")
    ap.add_argument("--out-dir", default=os.path.join(HERE, "data"))
    ap.add_argument("--min-freq", type=float, default=0.4, help="min co-occurrence frequency to count as roster (default 0.4)")
    ap.add_argument("--min-matches", type=int, default=2, help="min matches-with-mentions a team needs before inferring its roster (default 2)")
    args = ap.parse_args()

    drafts_path = os.path.join(HERE, "data", "drafts.json")
    cache_path = os.path.join(HERE, "data", f"raw_{args.channel_id}.jsonl")
    if not os.path.exists(drafts_path):
        raise SystemExit(f"no drafts.json at {drafts_path} -- run extract_drafts.py first")
    if not os.path.exists(cache_path):
        raise SystemExit(f"no raw cache at {cache_path} -- run discord_relay.py crawl first")

    drafts = load_json(drafts_path)
    tag_map = known_team_keys(drafts)  # canonical -> Counter(raw tags)
    known_keys = set(tag_map)

    all_messages = list(load_jsonl(cache_path))
    team_idx = build_widened_index(all_messages, known_keys)
    global_freq = global_player_frequency(team_idx)
    rosters = build_team_rosters(team_idx, global_freq, args.min_freq, args.min_matches)
    player_rows = classify_match_players(drafts, team_idx, global_freq)

    write_outputs(tag_map, rosters, player_rows, args.out_dir)

    teams_with_roster = len({r["team"] for r in rosters})
    assigned = sum(1 for r in player_rows if r["assigned_team"])
    merged = sum(1 for c in tag_map.values() if len(c) > 1)
    print(f"{len(known_keys)} canonical teams ({merged} merged from multiple raw emoji tags), {len(all_messages)} messages scanned")
    print(f"{teams_with_roster} teams had enough (widened) matches to infer a roster; inferred {len(rosters)} team/player roster entries")
    print(f"classified {assigned}/{len(player_rows)} mentioned-player-in-draft rows to a side (rest: ambiguous/organizer/thin data -- see 'note')")
    print(f"wrote team_tag_map.csv / team_rosters.csv / drafts_players_by_team.csv to {args.out_dir}")


if __name__ == "__main__":
    _cli()
