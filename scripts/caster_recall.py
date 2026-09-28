"""When a priced play happens, does the commentary notice, and does the reaction size track the
price? Recall and calibration for scripts/plays.py, against a within-match baseline.

WHY THE BASELINE MATTERS. The first version asked the opposite question -- of the loud moments, how
many were priced plays -- found mostly multi-kills, and concluded the signal was absent. That
measures precision, and precision on the loud cases says nothing about whether a quiet play gets
noticed. Scored the right way round on the same 25 plays, the answer is specific:

  cap-out denial                   lift 0.00   n=10   (median reaction exactly zero)
  solo run-through cap             lift 1.10   n=9
  deep collapse / spawn pressure   lift 1.06   n=6    (was 1.77 at n=3 -- retracted)
  attempt, reached the flag        lift 0.00   n=6    (was 1.78 at n=2 -- retracted)
  sneak cap                        lift 1.01   n=5

The denial zero has held across both samples and is now on n=10: a human watching does not register
these at all, which is why they need pricing rather than discounting. The two classes that looked
strong at n=3 and n=2 did NOT survive reaching n=6 -- which is the whole argument for --record, since
a number nobody wrote down cannot be seen to move. CLASS-SPECIFIC LANGUAGE IS ALSO A DEAD END, measured 2026-09-27. Phrases like "on his own",
"quietly" or "in behind" looked discriminating in-sample (9 of 36 priced windows against a 16%
baseline, lift 1.56) -- but those phrases were chosen by looking at the same 36 windows they were
then scored on, which is circular. Evaluated leave-one-cast-out (choose the phrases on four casts,
score them on the fifth), the list fires on 0% of held-out priced windows against a 10% baseline:
lift 0.00. The apparently strong phrases were single occurrences; only "cap out" clears selection
at all, and it does not generalise. `ninja_hits` is kept because printing what was said around a
play is useful for reading, NOT because it is a signal. Treat every number here as existence, not
rate.

  caster_recall.py [--class-only <substring>]
  caster_recall.py --record <path.tsv>    append this run's per-class lift and report what moved

WHY --record EXISTS. The stopping rule for this work is "when the numbers stop moving", not a
sample size -- with only cast matches to draw on, a target n could be a season away. A stopping
rule like that is worthless from memory: nobody can say whether a lift of 1.7 is where it has sat
for three weeks or where it landed this morning. So every run appends a row per class, and the run
prints the movement since the previous recording and whether the stability condition holds.

Output: per priced play the reaction score in its window, the same statistic over 400 random
windows in the same match as a baseline, the lift, and the class-language hits.
"""
import argparse
import csv
import json
import random
import re
import statistics
import csv as _csv
import datetime as _dt
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
    ap.add_argument("--record", default="", help="append this run's per-class lift to this TSV")
    ap.add_argument("--stable-delta", type=float, default=0.15,
                    help="a class counts as settled when its lift moves less than this between runs")
    a = ap.parse_args()
    random.seed(7)
    rows_out, by_class = [], defaultdict(list)
    global BASE_NIN
    BASE_NIN = []

    # Keys beginning with _ are store configuration (_consent, _channels), not casts.
    casts = {k: (v["start"], v["matches"]) for k, v in
             json.loads(Path(CASTS_FILE).read_text(encoding="utf-8")).items()
             if not k.startswith("_") and v.get("matches")}
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
    current = {}
    for cls, vals in sorted(by_class.items(), key=lambda kv: -len(kv[1])):
        scs = [v[0] for v in vals]
        bms = [v[1] for v in vals]
        nin = sum(1 for v in vals if v[2])
        current[cls] = (len(vals), statistics.median(scs), statistics.mean(bms),
                        statistics.median(scs) / statistics.mean(bms) if statistics.mean(bms) else 0.0)
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

    if a.record:
        record_history(a.record, current, a.stable_delta)


WEIGHTED = ("cap-out denial", "solo run-through cap", "deep collapse")


def record_history(path, current, stable_delta):
    """Append one row per class, then say what moved since the last recording.

    The file is append-only on purpose: a history you can rewrite cannot answer "has this
    settled". Columns: run date, class, n, median reaction, baseline, lift."""
    p = Path(path)
    prev = {}
    if p.exists():
        with p.open(encoding="utf-8", newline="") as f:
            for row in _csv.DictReader(f, delimiter="\t"):
                prev[row["class"]] = (row["run"], float(row["lift"]), int(row["n"]))
    else:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("run\tclass\tn\tmedian_react\tbaseline\tlift\n", encoding="utf-8", newline="\n")

    today = _dt.date.today().isoformat()
    with p.open("a", encoding="utf-8", newline="\n") as f:
        for cls, (n, med, base, lift) in sorted(current.items()):
            f.write(f"{today}\t{cls}\t{n}\t{med:.2f}\t{base:.2f}\t{lift:.3f}\n")
    print(f"\n-- recorded to {p} --")

    if not prev:
        print("first recording: nothing to compare against yet")
        return
    settled = []
    for cls, (n, med, base, lift) in sorted(current.items()):
        was_run, was_lift, was_n = prev.get(cls, (None, None, None))
        if was_lift is None:
            print(f"{cls:38} new class this run (lift {lift:.2f}, n={n})")
            continue
        moved = lift - was_lift
        crossed = (was_lift - 1.0) * (lift - 1.0) < 0
        ok = abs(moved) < stable_delta and not crossed
        note = "settled" if ok else ("CROSSED 1.0" if crossed else f"moved {moved:+.2f}")
        print(f"{cls:38} lift {was_lift:.2f} -> {lift:.2f} ({was_run} -> {today}, n {was_n}->{n})  {note}")
        if cls in WEIGHTED:
            settled.append(ok)
    if settled:
        print("\nSTABILITY, the three weighted classes: "
              + ("all settled since the previous run — a verdict can be declared"
                 if all(settled) and len(settled) == len(WEIGHTED)
                 else f"{sum(settled)}/{len(WEIGHTED)} settled — keep going"))


if __name__ == "__main__":
    main()
