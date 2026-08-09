#!/usr/bin/env python3
"""Point the day boards' damage column (dm) at HLStatsX, in the embedded data.

The #lan-data block in design/prototype.html is the day boards' data and has no
committed generator — it was embedded from lan-stats.json by hand. Its dm field
originally carried damage_hud; the operator decision of 2026-08 is that damage
comes from the match record (ktp_match_stats, halves 1+2), which lan-stats.json
carries as damage_hlstatsx on both the per-day and per-map rows. This rewrites
dm from that field, per-day and per-map, joined by player name within a day
(verified 61/61 and 600/600 unique at the swap). Idempotent.

    python embed_damage.py           # rewrite dm in the page's #lan-data
    python embed_damage.py --check   # exit 1 if any dm disagrees
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
STATS = os.path.join(HERE, "lan-stats.json")
PAGE = os.path.normpath(os.path.join(HERE, "..", "design", "prototype.html"))
BLOCK = re.compile(r'(<script id="lan-data" type="application/json">)(.*?)(</script>)', re.S)


def main() -> int:
    stats = json.load(open(STATS, encoding="utf-8"))
    page = open(PAGE, encoding="utf-8").read()
    m = BLOCK.search(page)
    if not m:
        print(f"#lan-data block not found in {PAGE}")
        return 2
    data = json.loads(m.group(2))

    changed = 0
    for day in data["days"]:
        src = stats["days"][day["key"]]
        by_name = {p["name"]: p for p in src["players"]}
        for p in day["players"]:
            want = by_name[p["n"]]["damage_hlstatsx"]
            if p["dm"] != want:
                p["dm"] = want
                changed += 1
        for mp, rows in day["maps"].items():
            src_rows = {p["name"]: p for p in src["maps"][mp]}
            for p in rows:
                want = src_rows[p["n"]]["damage_hlstatsx"]
                if p["dm"] != want:
                    p["dm"] = want
                    changed += 1

    if "--check" in sys.argv:
        if changed:
            print(f"#lan-data dm is STALE ({changed} rows) — re-run embed_damage.py")
            return 1
        print("#lan-data dm is current")
        return 0

    if not changed:
        print("no change")
        return 0
    # same encoding the block already uses — verified byte-identical round-trip
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    new = page[:m.start(2)] + blob + page[m.end(2):]
    with open(PAGE, "w", encoding="utf-8", newline="") as f:
        f.write(new)
    print(f"rewrote {changed} dm values in {PAGE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
