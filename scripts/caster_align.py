"""Align a match cast's transcript to the match, and attach the commentary to every priced play.

WHY THIS EXISTS. `scripts/excursions.py` and `scripts/plays.py` price plays whose value is not in
kills or damage: a solo cap, a cap-out denial, a collapse into the enemy spawn. Nothing in the data
says whether a human watching thought those mattered, or how much. A cast does -- it is a
continuous human judgement over the same timeline -- so this attaches one to the other and the
pricing can be checked against it.

Inputs are TEXT ONLY and live outside this repo. Audio is not an input and is not kept: a
transcript is produced once and the recording is deleted. Nothing here names a caster, a stream or
a player. Stdlib only, no network.

  caster_align.py <match_id> <cast_id> --vod-start <epoch> --offset 60      # live cast
  caster_align.py <match_id> <cast_id> --vod-start <epoch> --anchor MM:SS   # delayed cast

Inputs:
  $KTP_CASTER_TEXT_DIR/v<cast_id>.json             whisper.cpp -oj output (segments, ms offsets)
  $KTP_CASTER_EVENTS_DIR/<match_id>.frags.tsv      event_epoch, game_time, half, killer, victim
  $KTP_CASTER_EVENTS_DIR/<match_id>.flag_state.tsv flag ownership changes
  $KTP_CASTER_EVENTS_DIR/<match_id>.score.tsv      objective score events
  $KTP_CASTER_EVENTS_DIR/<match_id>.priced.tsv     the priced plays for this match
  $KTP_CASTER_EVENTS_DIR/halves.tsv                match_id, half, start_epoch, end_epoch

ALIGNMENT -- two cases, both measured on real casts 2026-09-24.

  LIVE, cast while the match is played: cast_seconds = event_epoch - vod_start + offset, where
  offset is the broadcast delay. Measured at a constant +60 s across four matches and three casts,
  so --offset 60 is a sound default rather than a per-cast fit.

  DELAYED, the match re-cast later from a recording: there is no epoch relationship at all, and
  correlating spoken player names against that player's frags does NOT recover one. With ~580 frags
  over ~45 min a given player frags about once per 28 s, so at a 16 s window ~57% of mentions
  coincide at ANY offset; the best margin was 2 points out of 60, i.e. flat. What works instead is
  the HALF END: two per match, rare, and commentary marks them out loud and reads the halftime
  score. Pass --anchor MM:SS and the offset is exact. Verified by the numbers read aloud matching
  the frag table.

REACTION CHANNEL, and its honest limit. Segments are scored for reaction language and merged into
bursts; a burst with no priced play nearby looks like something the pricing missed. Measured, it
mostly is not: excitement tracks KILLS, which happen every ~20 s, while the plays priced here are
quiet by construction. Lift of priced windows over random windows in the same match was 1.02 --
nothing. The useful direction is the reverse; see caster_recall.py.
"""
import argparse
import csv
import os
import json
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path

# This repo is PUBLIC. Nothing here names a caster, a stream or a player: the transcripts, the
# cast-to-match mapping and the match exports all live outside it, under paths given by the
# environment. Defaults are relative on purpose.
VODS = Path(os.environ.get("KTP_CASTER_TEXT_DIR", "caster/text"))
EVENTS = Path(os.environ.get("KTP_CASTER_EVENTS_DIR", "caster/events"))

# engine flag_name -> words the caster uses. Unknown aliases cost anchors, they never add wrong ones.
FLAG_ALIASES = {
    "dod_lennon5_b1": {"the cliffs": ["cliffs", "cliff"], "the alley": ["alley"],
                       "the courtyard": ["courtyard", "court"], "Well": ["well"], "the street": ["street"]},
    "dod_thunder2": {},
    "dod_harrington": {},
}
GENERIC_FLAG_WORDS = ["flag", "cap", "capped", "capping", "capture", "neutral", "cap out", "capout", "backcap"]

# Reaction language, weighted. Deliberately small and readable: this list is a claim about what
# "he thought that mattered" sounds like, and it gets audited by reading the bursts it produces.
REACTIONS = {
    3: ["oh my god", "oh my lord", "are you kidding", "no way", "what a play", "what a shot",
        "unbelievable", "you have got to be", "holy", "insane", "ridiculous", "incredible"],
    2: ["huge", "massive", "clutch", "saves the", "saved the", "game changer", "that's the game",
        "wow", "oh my", "amazing", "beautiful", "filthy", "nasty", "monster", "hero"],
    1: ["big", "nice", "great", "wild", "crazy", "lucky", "brutal", "oh no", "come on", "finally",
        "so good", "so close", "impressive"],
}
# A stream is not only a match: sub alerts, chat, gear and small talk fire the same words. A segment
# carrying any of these is not scored for reaction (it still shows in the window text). Measured on
# the first pass: without this, "Kev just dropped a beastly sub bomb" ranked above a real cap-out.
STREAM_TALK = ["sub", "subs", "subbed", "gifted", "gift", "chat", "donation", "donate", "tip",
               "thank you", "thanks for", "welcome", "follow", "followed", "raid", "camera", "cam",
               "mic", "headset", "audio", "stream", "streaming", "twitch", "youtube", "discord",
               "viewers", "lurk", "prime", "emote", "mods", "bits"]


def load_segments(vod_id):
    data = json.loads((VODS / f"v{vod_id}.json").read_text(encoding="utf-8"))
    return [{"t0": s["offsets"]["from"] / 1000.0, "t1": s["offsets"]["to"] / 1000.0,
             "text": s["text"].strip()} for s in data["transcription"]]


def load_tsv(path):
    if not Path(path).exists():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    for r in rows:
        for k, v in r.items():
            if v == "NULL":
                r[k] = None
    return rows


def word_hits(text, words):
    t = text.lower()
    return sum(1 for w in words if re.search(rf"\b{re.escape(w)}\b", t))


def refine_offset(segs, flag_events, vod_start, aliases, search=180, after=8.0):
    changes = [(float(e["event_epoch"]) - vod_start, e["flag_name"]) for e in flag_events
               if e["event_epoch"] and e["is_initial"] == "0"]
    mentions = []
    for s in segs:
        for name, words in aliases.items():
            if word_hits(s["text"], words):
                mentions.append((s["t0"], name))
        if word_hits(s["text"], GENERIC_FLAG_WORDS):
            mentions.append((s["t0"], None))
    if not changes or not mentions:
        return 0.0, 0
    best = (0.0, -1)
    for off10 in range(-search * 10, search * 10 + 1, 5):
        off = off10 / 10.0
        score = sum(2 if m_name == name else 1
                    for t, name in changes for m_t, m_name in mentions
                    if t + off < m_t <= t + off + after and (m_name is None or m_name == name))
        if score > best[1]:
            best = (off, score)
    return best


def handle_tokens(frags):
    """{handle token -> full roster name}. Clan tags are stripped: he says 'Brooks', not '[ o_o ] bro_Oks'."""
    out = {}
    for r in frags:
        for k in ("killer", "victim"):
            full = r[k]
            if not full:
                continue
            tail = re.split(r"[\]\|~:.\s]+", full.strip())[-1] or full
            tok = re.sub(r"[^a-z0-9]", "", tail.lower())
            tok = re.sub(r"(.)\1{2,}$", r"\1", tok)  # kroD-, Empyyyy~, reppoH: trailing runs are decoration
            if len(tok) >= 4:
                out.setdefault(tok[:6], full)
    return out


def demo_offset(segs, frags, vod_start, vod_len, step=2):
    """A demo re-cast has no epoch relation to the VOD, so the offset is found the way the idea said
    it would be: he names players constantly and frags carry time, so the lag that makes the most
    spoken names land on that player's frags is the alignment. Returns (offset, score, second_best)."""
    toks = handle_tokens(frags)
    per_tok = defaultdict(list)
    for r in frags:
        for k in ("killer", "victim"):
            if not r[k]:
                continue
            tail = re.split(r"[\]\|~:.\s]+", r[k].strip())[-1] or r[k]
            t = re.sub(r"[^a-z0-9]", "", tail.lower())
            t = re.sub(r"(.)\1{2,}$", r"\1", t)[:6]
            if t in toks:
                per_tok[t].append(float(r["event_epoch"]) - vod_start)
    mentions = []
    for s in segs:
        w = set(re.findall(r"[a-z0-9]+", s["text"].lower()))
        for tok in toks:
            if any(x.startswith(tok) or tok.startswith(x[:5]) and len(x) >= 5 for x in w):
                mentions.append((s["t0"], tok))
    if not mentions or not per_tok:
        return 0.0, 0, 0
    rel = [t for ts in per_tok.values() for t in ts]
    span = (-min(rel), vod_len - max(rel))
    scored = []
    for off in range(int(span[0]), int(span[1]) + 1, step):
        sc = sum(1 for m_t, tok in mentions
                 for ft in per_tok.get(tok, ()) if -4 <= m_t - (ft + off) <= 12)
        scored.append((sc, off))
    scored.sort(reverse=True)
    return float(scored[0][1]), scored[0][0], (scored[1][0] if len(scored) > 1 else 0)


def window_text(segs, t, before, after):
    return " ".join(s["text"] for s in segs if s["t1"] >= t - before and s["t0"] <= t + after)


def reaction_bursts(segs, lo, hi, gap=12.0):
    """[(t_start, t_end, score, text)] for runs of reaction language inside the match window."""
    scored = []
    for s in segs:
        if not (lo <= s["t0"] <= hi):
            continue
        if word_hits(s["text"], STREAM_TALK):
            continue
        sc = sum(w * word_hits(s["text"], words) for w, words in REACTIONS.items())
        sc += s["text"].count("!")
        if sc:
            scored.append((s["t0"], s["t1"], sc, s["text"]))
    bursts = []
    for t0, t1, sc, txt in scored:
        if bursts and t0 - bursts[-1][1] <= gap:
            b = bursts[-1]
            bursts[-1] = (b[0], t1, b[2] + sc, b[3] + " " + txt)
        else:
            bursts.append((t0, t1, sc, txt))
    return bursts


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("match_id")
    ap.add_argument("vod_id")
    ap.add_argument("--vod-start", type=int, required=True)
    ap.add_argument("--offset", type=float, default=None, help="known stream delay in seconds; skips refinement")
    ap.add_argument("--window", type=float, default=20.0)
    ap.add_argument("--map", default="dod_lennon5_b1")
    ap.add_argument("--min-burst", type=int, default=4, help="reaction score a burst needs to be listed")
    ap.add_argument("--min-frags", type=int, default=2, help="frags within +-20 s for a burst to count as match talk")
    ap.add_argument("--multikill", type=int, default=2, help="frags by one killer that explain a burst as a highlight")
    ap.add_argument("--demo", action="store_true", help="re-cast from a demo: find the offset by name/frag correlation")
    ap.add_argument("--anchor", default="", help="MM:SS in the VOD of a known boundary, e.g. 26:01 = the half-1 end "
                                                 "he reads the score at; the strongest anchor for a demo re-cast")
    ap.add_argument("--anchor-what", default="h1end", choices=["h1end", "h1start", "h2end", "h2start"])
    a = ap.parse_args()

    segs = load_segments(a.vod_id)
    flags = [r for r in load_tsv(EVENTS / f"{a.match_id}.flag_state.tsv") if r["event_epoch"]]
    scores = [r for r in load_tsv(EVENTS / f"{a.match_id}.score.tsv") if r["event_epoch"]]
    frags = [r for r in load_tsv(EVENTS / f"{a.match_id}.frags.tsv") if r["event_epoch"]]
    priced = load_tsv(EVENTS / f"{a.match_id}.priced.tsv")
    aliases = FLAG_ALIASES.get(a.map, {})
    changes = [f for f in flags if f["is_initial"] == "0"]

    if a.anchor:
        mm, ss = a.anchor.split(":")
        t_vod = int(mm) * 60 + float(ss)
        halves = {(r["half"], k): int(r[f"{k}_epoch"]) for r in load_tsv(EVENTS / "halves.tsv")
                  if r["match_id"] == a.match_id for k in ("start", "end")}
        key = {"h1end": ("1", "end"), "h1start": ("1", "start"),
               "h2end": ("2", "end"), "h2start": ("2", "start")}[a.anchor_what]
        if key not in halves:
            raise SystemExit(f"no {a.anchor_what} for {a.match_id} in events/halves.tsv")
        offset = t_vod - (halves[key] - a.vod_start)
        how = f"anchored {offset:+.0f}s on {a.anchor_what} at VOD {a.anchor}"
    elif a.demo and a.offset is None:
        offset, sc, second = demo_offset(segs, frags, a.vod_start, segs[-1]["t1"])
        how = (f"demo, by name/frag correlation {offset:+.0f}s (score {sc} vs next-best {second}, "
               f"margin {sc - second})")
    elif a.offset is None:
        offset, score = refine_offset(segs, flags, a.vod_start, aliases)
        how = f"refined {offset:+.1f}s (score {score}; base-rate noisy)"
    else:
        offset, how = a.offset, f"given {a.offset:+.1f}s"
    at = lambda epoch: float(epoch) - a.vod_start + offset

    ep = [float(f["event_epoch"]) for f in frags]
    lo, hi = at(min(ep)) - 60, at(max(ep)) + 60
    print(f"# {a.match_id} ({a.map}) vs VOD {a.vod_id}: {len(segs)} segments, offset {how}")
    print(f"# match occupies VOD {int(lo)//60:02d}:{int(lo)%60:02d}–{int(hi)//60:02d}:{int(hi)%60:02d} "
          f"of {int(segs[-1]['t1'])//60} min; {len(frags)} frags, {len(changes)} flag changes, "
          f"{len(scores)} score events, {len(priced)} priced rows")

    anchor = {}
    for h in ("1", "2"):
        d = [float(r["event_epoch"]) - float(r["game_time"]) for r in frags
             if r["half"] == h and r["game_time"]]
        if d:
            anchor[h] = statistics.median(d)

    if priced:
        print("\n## Priced moments (hv_detect) and what he said")
        for r in priced:
            if r["half"] not in anchor:
                print(f"\n#{r['n']} h{r['half']} t={r['game_t']}: no epoch anchor for this half")
                continue
            t = at(anchor[r["half"]] + float(r["game_t"]))
            print(f"\n#{r['n']} [{int(t)//60:02d}:{int(t)%60:02d}] h{r['half']} game_t {r['game_t']} "
                  f"(demo seek {r['seek']}) {r['class']} — {r['who']}\n   detector: {r['detail']}")
            print("   caster -30s..+45s: " + (window_text(segs, t, 30, 45) or "(silence)"))

    # A burst only counts as being about the match if the match was doing something: a missed play
    # always has frags around it, while "my day was crazy" has none. This is what separates the
    # false-negative channel from small talk, which no word list can do on its own.
    frag_t = sorted(at(r["event_epoch"]) for r in frags)
    live = lambda t: sum(1 for ft in frag_t if abs(ft - t) <= 20) >= a.min_frags
    all_bursts = [b for b in reaction_bursts(segs, lo, hi) if b[2] >= a.min_burst]
    bursts = [b for b in all_bursts if live(b[0])]

    # He reacts hardest to multi-kills, which hv_detect ignores on purpose (kills are counted
    # elsewhere). Without subtracting them the channel is a highlight reel, not a list of plays the
    # detector missed. A burst is "explained" when one killer took >=3 frags in the 12 s before it.
    def multikill(t):
        best = Counter()
        for r in frags:
            ft = at(r["event_epoch"])
            if t - 14 <= ft <= t + 4 and r["killer"]:
                best[r["killer"]] += 1
        top = best.most_common(1)
        return top[0] if top and top[0][1] >= a.multikill else None
    priced_times = [at(anchor[r["half"]] + float(r["game_t"])) for r in priced if r["half"] in anchor]
    print(f"\n## Reaction bursts inside the match window ({len(bursts)} of {len(all_bursts)} at score "
          f">= {a.min_burst}; {len(all_bursts) - len(bursts)} dropped as talk with no frags nearby)")
    unmatched, explained = [], 0
    for t0, t1, sc, txt in bursts:
        near = min((abs(t0 - p) for p in priced_times), default=9e9)
        mk = multikill(t0)
        if near <= 45:
            tag = f"priced row {near:.0f}s away"
        elif mk:
            tag = f"multi-kill explains it ({mk[0].strip()} x{mk[1]})"
            explained += 1
        else:
            tag = "**CANDIDATE** no priced row, no multi-kill"
            unmatched.append((t0, sc, txt))
        caps = [s for s in scores if abs(at(s["event_epoch"]) - t0) <= 30]
        cap_note = (" · score: " + ", ".join(f"{(s['player_name'] or '?').strip()} +{s['delta']} {s['flag_name'] or ''}"
                                             for s in caps[:3])) if caps else ""
        print(f"\n[{int(t0)//60:02d}:{int(t0)%60:02d}] score {sc} · {tag}{cap_note}\n   {txt[:400]}")
    print(f"\n{len(unmatched)} candidates of {len(bursts)} bursts: no priced row within 45 s and no "
          f"multi-kill to explain the noise ({explained} were multi-kills)")

    quiet = 0
    for e in changes:
        t = at(e["event_epoch"])
        txt = window_text(segs, t, 5, 20)
        if not word_hits(txt, GENERIC_FLAG_WORDS + [w for ws in aliases.values() for w in ws]):
            quiet += 1
    print(f"{quiet} of {len(changes)} flag changes had no flag word within 20 s")


if __name__ == "__main__":
    main()
