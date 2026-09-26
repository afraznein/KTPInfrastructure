"""When a priced play happens, does the commentary notice, and does the reaction size track the
price? Recall and calibration for scripts/plays.py, against a within-match baseline.

WHY THE BASELINE MATTERS. The first version asked the opposite question -- of the loud moments, how
many were priced plays -- found mostly multi-kills, and concluded the signal was absent. That
measures precision, and precision on the loud cases says nothing about whether a quiet play gets
noticed. Scored the right way round on the same 25 plays, the answer is specific:

  deep collapse / spawn pressure   lift 1.77   n=3
  attempt, reached the flag        lift 1.78   n=2
  solo run-through cap             lift 0.98   n=8
  sneak cap                        lift 1.01   n=5
  cap-out denial                   median reaction ZERO, lift 0.00   n=7

A human watching registers a player bleeding into the enemy spawn, and does not register a cap-out
denial at all. That zero is the finding rather than the absence of one: low salience is why these
plays need pricing, not a reason to discount them. Class-specific language -- someone arriving
unseen, someone holding alone -- fires on 9 of 25 including 4 of the 7 silent denials, so denials
get narrated calmly rather than shouted. The sample is small: treat every number here as existence,
not rate.

  caster_recall.py [--class-only <substring>]

Output: per priced play the reaction score in its window, the same statistic over 400 random
windows in the same match as a baseline, the lift, and the class-language hits.
"""
import argparse
import csv
import json
import random
import re
import statistics
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import caster_align as align  # noqa: E402

# The cast-to-match mapping is DATA, not code, and it identifies real broadcasts, so it lives
# outside this public repo: {cast_id: {"start": <epoch>, "matches": {match_id: map_name}}}.
# scripts/caster-casts.json.example shows the shape.
CASTS_FILE = os.environ.get("KTP_CASTER_CASTS", "caster/casts.json")
OFFSET = 60.0
WIN = (-15.0, 45.0)

# Language specific to the play classes the detector prices: someone arriving where nobody expects,
# or holding a flag alone. Distinct from generic excitement, which is what kills fire.
NINJA_WORDS = ["ninja", "backcap", "back cap", "nobody home", "nobody's home", "no one home",
               "where did he come from", "they don't know", "doesn't know he's there", "sneak",
               "sneaks", "sneaking", "snuck", "all alone", "by himself", "on his own", "alone at",
               "behind them", "in behind", "cheeky", "quietly", "unnoticed", "no idea he",
               "had no idea", "out of nowhere", "hold on for dear life", "holding alone",
               "last man", "one man", "1 man", "saves the cap", "denies", "denial", "cap out",
               "capout", "full cap"]


def score_window(segs, t, lo=WIN[0], hi=WIN[1]):
    total = 0
    for s in segs:
        if not (t + lo <= s["t0"] <= t + hi):
            continue
        if align.word_hits(s["text"], align.STREAM_TALK):
            continue
        total += sum(w * align.word_hits(s["text"], words) for w, words in align.REACTIONS.items())
        total += s["text"].count("!")
    return total


def ninja_hits(segs, t, lo=WIN[0], hi=WIN[1]):
    out = []
    for s in segs:
        if t + lo <= s["t0"] <= t + hi:
            for w in NINJA_WORDS:
                if re.search(rf"\b{re.escape(w)}\b", s["text"].lower()):
                    out.append(w)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--class-only", default="")
    a = ap.parse_args()
    random.seed(7)
    rows_out, by_class = [], defaultdict(list)
    global BASE_NIN
    BASE_NIN = []

    casts = {k: (v["start"], v["matches"]) for k, v in
             json.loads(Path(CASTS_FILE).read_text(encoding="utf-8")).items()}
    for vod_id, (vod_start, matches) in casts.items():
        segs = align.load_segments(vod_id)
        for match_id, _map in matches.items():
            frags = [r for r in align.load_tsv(align.EVENTS / f"{match_id}.frags.tsv") if r["event_epoch"]]
            priced = align.load_tsv(align.EVENTS / f"{match_id}.priced.tsv")
            if not frags or not priced:
                continue
            at = lambda e: float(e) - vod_start + OFFSET
            anchor = {}
            for h in ("1", "2"):
                d = [float(r["event_epoch"]) - float(r["game_time"]) for r in frags
                     if r["half"] == h and r["game_time"]]
                if d:
                    anchor[h] = statistics.median(d)
            ep = [float(r["event_epoch"]) for r in frags]
            lo, hi = at(min(ep)), at(max(ep))
            # baseline: the same window statistic at 400 random times inside the match
            base, base_nin = [], 0
            for _ in range(400):
                rt = random.uniform(lo, hi)
                base.append(score_window(segs, rt))
                base_nin += bool(ninja_hits(segs, rt))
            b_mean = statistics.mean(base)
            b_hi = sorted(base)[int(len(base) * 0.8)]
            BASE_NIN.append(base_nin / 400)
            for r in priced:
                if r["half"] not in anchor:
                    continue
                if a.class_only and a.class_only.lower() not in r["class"].lower():
                    continue
                t = at(anchor[r["half"]] + float(r["game_t"]))
                sc = score_window(segs, t)
                nin = ninja_hits(segs, t)
                rows_out.append((match_id, r["n"], r["class"], r["who"], sc, b_mean, b_hi, nin, t))
                by_class[r["class"].split("(")[0].strip()].append((sc, b_mean, bool(nin)))

    print(f"{'match':16} {'#':>3} {'react':>5} {'base':>5} {'p80':>4} {'lift':>5}  class / ninja words")
    for m, n, cls, who, sc, bm, bh, nin, t in sorted(rows_out, key=lambda x: -x[4]):
        lift = sc / bm if bm else 0
        mark = "**" if sc >= bh else "  "
        print(f"{m:16} {n:>3} {sc:>5} {bm:>5.1f} {bh:>4} {lift:>5.2f}{mark} {cls[:34]:34} "
              f"{', '.join(sorted(set(nin))[:4])}")

    print("\n-- by class --")
    for cls, vals in sorted(by_class.items(), key=lambda kv: -len(kv[1])):
        scs = [v[0] for v in vals]
        bms = [v[1] for v in vals]
        nin = sum(1 for v in vals if v[2])
        print(f"{cls:38} n={len(vals):2}  median react {statistics.median(scs):5.1f}  "
              f"baseline {statistics.mean(bms):5.1f}  lift {statistics.median(scs)/statistics.mean(bms):4.2f}  "
              f"ninja-language on {nin}/{len(vals)}")
    scs = [r[4] for r in rows_out]
    bms = [r[5] for r in rows_out]
    above = sum(1 for r in rows_out if r[4] >= r[6])
    print(f"\nALL n={len(rows_out)}  median react {statistics.median(scs):.1f} vs baseline "
          f"{statistics.mean(bms):.1f} (lift {statistics.median(scs)/statistics.mean(bms):.2f}); "
          f"{above}/{len(rows_out)} priced rows land in the top fifth of match windows")
    hit = sum(1 for r in rows_out if r[7])
    bn = statistics.mean(BASE_NIN)
    print(f"PLAY LANGUAGE (ninja/denial/positional, not excitement): fires in {hit}/{len(rows_out)} "
          f"= {hit/len(rows_out):.0%} of priced windows vs {bn:.0%} of random windows in the same "
          f"matches — lift {(hit/len(rows_out))/bn if bn else 0:.2f}")


if __name__ == "__main__":
    main()
