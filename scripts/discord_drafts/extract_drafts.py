"""
Regex-based extraction of pick/ban draft records from a crawled channel cache
(see discord_relay.py). Pure pattern matching -- no LLM involved, so it's
re-runnable and its output is auditable.

Captains' draft dumps are free-typed and drifted in format across seasons:
    <:Team_Revo:ID> bans thunder
    Soul! <:Team_Soul2:ID> BANS Anzio
    revo <:Team_Revo2:ID> bans thunder
...but always as `[optional name] <emoji:TeamTag:id> (bans|picks) <map>` lines,
which is what we anchor on. Decider-map, match time, and division are looked
for with a few known phrasings and are best-effort: a record that's missing
one, or doesn't resolve to exactly 2 teams, is flagged `needs_review` rather
than silently guessed at, and still written out with its raw content so a
human can finish it by hand.

Usage:
    python extract_drafts.py <channel_id_or_cache_path> [--out-dir DIR]

Output (in --out-dir, default ./data):
    drafts.json              full structured records
    drafts.csv                one row per draft message
    drafts_actions.csv        long format, one row per pick/ban action
    drafts_needs_review.csv   subset of drafts.csv flagged for manual review
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))

ACTION_RE = re.compile(
    r"<a?:(?P<emoji>[A-Za-z0-9_]+):\d+>\s*(?P<action>bans?|banned|picks?|chooses?|chose)\s+(?P<map>[A-Za-z0-9_]+)",
    re.IGNORECASE,
)
ARROW_RE = re.compile(
    r"([A-Za-z0-9_]+)\s*(?:[-—]+>|→)\s*([A-Za-z0-9_]+)\s*(?:[-—]+>|→)\s*([A-Za-z0-9_]+)"
)
# Tried in order; each is (regex, method_name, "before"|"after"|"arrow" -- which
# group holds the map name relative to the keyword). Line-anchored/specific
# patterns come first; the loose "decider word, then whatever's next" pattern
# is last resort and end-anchored so it can't reach past the decider line into
# unrelated trailing text (e.g. "Saints decider\nTime TBD" must not capture "Time").
DECIDER_PATTERNS = [
    (ARROW_RE, "arrow_chain", "arrow"),
    (re.compile(r"(?i)\b([A-Za-z0-9_]+)\s+is\s+(?:the\s+)?decid\w*(?:\s+map)?\b"), "map_is_decider", "before"),
    (re.compile(r"(?im)^\s*([A-Za-z0-9_]+)\s+decid\w*\b"), "map_then_decider_word", "before"),
    (re.compile(r"(?i)\bdecid\w*(?:\s+map)?\s+(?:is|will\s+be)\s+([A-Za-z0-9_]+)"), "decider_is_or_willbe_map", "after"),
    (re.compile(r"(?i)\b([A-Za-z0-9_]+)\s+is\s+(?:the\s+)?tie[\s-]?breaker\b"), "tie_breaker", "before"),
    (re.compile(r"(?i)\b([A-Za-z0-9_]+)\s+is\s+(?:the\s+)?final\s+map\b"), "final_map", "before"),
    (re.compile(r"(?i)\b([A-Za-z0-9_]+)\s+remains\b"), "remains", "before"),
    (re.compile(r"(?im)^\s*([A-Za-z0-9_]+)\s+(?:3rd|third)\s+map\b"), "third_map", "before"),
    (re.compile(r"(?i)\b(?:3rd|third)\s+map\s+(?:is\s+)?([A-Za-z0-9_]+)"), "third_map_reversed", "after"),
    (re.compile(r"(?i)\b([A-Za-z0-9_]+)\s+for\s+decider\b"), "for_decider", "before"),
    (re.compile(r"(?i)\b([A-Za-z0-9_]+)\s*\(\s*decider\s*\)"), "map_paren_decider", "before"),
    (re.compile(r"(?i)\b([A-Za-z0-9_]+)\s+if\s+needed\b"), "if_needed", "before"),
    (re.compile(r"(?i)\b([A-Za-z0-9_]+)\s+leftover\b"), "leftover", "before"),
    # last resort: bare "Decider: X" / "Decider X" as its own whole line, no run-on
    (re.compile(r"(?im)^\s*decid\w*[ \t]*:?[ \t]+([A-Za-z0-9_]+)\s*$"), "decider_word_then_map_lineonly", "after"),
]
# Words a decider-pattern can accidentally grab from surrounding chatter
# (times, days, filler) that are never real map names -- reject and keep
# trying subsequent patterns rather than accept these as the decider.
MAP_STOPWORDS = {
    "time", "times", "map", "maps", "will", "start", "starts", "starting",
    "sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday",
    "like", "is", "the", "a", "an", "tbd", "est", "pm", "am", "default", "and", "or",
}
DISCORD_TS_RE = re.compile(r"<t:(\d+):[A-Za-z]>")
MATCH_LINE_RE = re.compile(r"(?im)^\s*match\s*:\s*(.+)$")
TIME_LINE_RE = re.compile(r"(?im)^\s*(?:start\s+)?time\s*[:\-]?\s*(.+)$")
DIVISION_RE = re.compile(r"^[\*\-=~\s]*([A-Za-z]{3,20})[\*\-=~\s]*$")


def find_decider(content: str):
    for regex, method, shape in DECIDER_PATTERNS:
        for m in regex.finditer(content):
            if shape == "arrow":
                candidate, order = m.group(3).lower(), [g.lower() for g in m.groups()]
            else:
                candidate, order = m.group(1).lower(), None
            if candidate in MAP_STOPWORDS:
                continue  # this match is junk (grabbed surrounding chatter) -- try the next match/pattern
            return candidate, method, order
    return None, None, None


def find_time(content: str):
    m = DISCORD_TS_RE.search(content)
    if m:
        iso = datetime.fromtimestamp(int(m.group(1)), tz=timezone.utc).isoformat()
        return content[m.start(): m.end()], iso
    m = MATCH_LINE_RE.search(content)
    if m:
        return m.group(1).strip(), None
    m = TIME_LINE_RE.search(content)
    if m:
        return m.group(1).strip(), None
    return None, None


def find_division(content: str):
    for line in content.split("\n"):
        line = line.strip()
        if not line:
            continue
        if sum(line.count(c) for c in "*-=~") < 2:
            continue
        m = DIVISION_RE.match(line)
        if m:
            return m.group(1).upper()
    return None


BARE_LINE_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{2,}$")


def _fallback_decider(content: str, actions: list[dict]):
    """Structural last-resort guesses, tried only after no keyword pattern matched."""
    # A 7-action draft (e.g. 4 bans + 3 "picks") with no explicit decider marker
    # usually means the last action itself claims the decider map.
    if len(actions) == 7:
        return actions[-1]["map"], "seventh_action"
    # A lone word on its own trailing line, after the draft lines, is often a
    # bare decider callout ("...\n\nArmory").
    lines = [l.strip() for l in content.split("\n") if l.strip()]
    if lines:
        last = lines[-1]
        if BARE_LINE_RE.match(last) and not ACTION_RE.search(last) and last.lower() not in MAP_STOPWORDS:
            return last.lower(), "trailing_bare_line"
    return None, None


def parse_draft(msg: dict) -> dict | None:
    content = msg.get("content", "")
    matches = list(ACTION_RE.finditer(content))
    if len(matches) < 2:
        return None  # not a draft dump

    actions = []
    teams_seen = []
    for i, m in enumerate(matches):
        team = m.group("emoji")
        if team not in teams_seen:
            teams_seen.append(team)
        actions.append(
            {
                "order_index": i,
                "team": team,
                "action": "ban" if m.group("action").lower().startswith("ban") else "pick",
                "map": m.group("map").lower(),
            }
        )

    decider_map, decider_method, map_order = find_decider(content)
    if decider_map is None:
        decider_map, decider_method = _fallback_decider(content, actions)
    time_raw, time_iso = find_time(content)
    division = find_division(content)
    players = msg.get("mentions", [])

    # Blocking: the draft itself (teams/actions/decider) is incomplete or
    # ambiguous -- worth a human look. Missing player @mentions is NOT
    # blocking: the message may legitimately name players as plain text
    # instead of tagging them, and the draft (teams, bans, picks, decider)
    # is still fully parsed without it -- it's just a note, not a defect.
    review_reasons = []
    if len(teams_seen) != 2:
        review_reasons.append(f"found {len(teams_seen)} teams, expected 2")
    if decider_map is None:
        review_reasons.append("no decider map found")
    notes = []
    if not players:
        notes.append("no player mentions found (players may be named as plain text)")

    return {
        "message_id": msg["id"],
        "timestamp": msg.get("timestamp"),
        "author": msg.get("author"),
        "division": division,
        "teams": teams_seen,
        "actions": actions,
        "decider_map": decider_map,
        "decider_method": decider_method,
        "map_order": map_order,
        "time_raw": time_raw,
        "time_iso": time_iso,
        "players": players,
        "needs_review": bool(review_reasons),
        "review_reasons": review_reasons,
        "notes": notes,
        "raw_content": content,
    }


def load_cache(path: str):
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def write_outputs(records: list[dict], out_dir: str):
    os.makedirs(out_dir, exist_ok=True)

    with open(os.path.join(out_dir, "drafts.json"), "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=2)

    def player_str(players):
        return ";".join(f"{p.get('username')}({p.get('id')})" for p in players)

    with open(os.path.join(out_dir, "drafts.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "message_id", "timestamp", "division", "team_a", "team_b",
                "decider_map", "decider_method", "map_order", "time_raw", "time_iso",
                "players", "needs_review", "review_reasons", "notes", "raw_content",
            ]
        )
        for r in records:
            teams = r["teams"] + [""] * (2 - len(r["teams"])) if len(r["teams"]) < 2 else r["teams"][:2]
            w.writerow(
                [
                    r["message_id"], r["timestamp"], r["division"] or "",
                    teams[0], teams[1] if len(teams) > 1 else "",
                    r["decider_map"] or "", r["decider_method"] or "",
                    ";".join(r["map_order"]) if r["map_order"] else "",
                    r["time_raw"] or "", r["time_iso"] or "",
                    player_str(r["players"]), r["needs_review"],
                    ";".join(r["review_reasons"]), ";".join(r["notes"]), r["raw_content"],
                ]
            )

    with open(os.path.join(out_dir, "drafts_actions.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["message_id", "timestamp", "division", "order_index", "team", "action", "map"])
        for r in records:
            for a in r["actions"]:
                w.writerow([r["message_id"], r["timestamp"], r["division"] or "", a["order_index"], a["team"], a["action"], a["map"]])

    needs_review = [r for r in records if r["needs_review"]]
    with open(os.path.join(out_dir, "drafts_needs_review.csv"), "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["message_id", "timestamp", "review_reasons", "raw_content"])
        for r in needs_review:
            w.writerow([r["message_id"], r["timestamp"], ";".join(r["review_reasons"]), r["raw_content"]])

    return needs_review


def _cli():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", help="channel ID (uses data/raw_<id>.jsonl) or a direct path to a JSONL cache")
    ap.add_argument("--out-dir", default=os.path.join(HERE, "data"))
    args = ap.parse_args()

    cache_path = args.source
    if not os.path.exists(cache_path):
        candidate = os.path.join(HERE, "data", f"raw_{args.source}.jsonl")
        if os.path.exists(candidate):
            cache_path = candidate
        else:
            raise SystemExit(f"no cache found at {args.source!r} or {candidate!r} -- run discord_relay.py crawl first")

    total = 0
    records = []
    for msg in load_cache(cache_path):
        total += 1
        rec = parse_draft(msg)
        if rec:
            records.append(rec)

    needs_review = write_outputs(records, args.out_dir)
    print(f"scanned {total} cached messages")
    print(f"found {len(records)} draft dumps, {len(needs_review)} flagged needs_review")
    print(f"wrote drafts.json / drafts.csv / drafts_actions.csv / drafts_needs_review.csv to {args.out_dir}")


if __name__ == "__main__":
    _cli()
