#!/usr/bin/env python3
"""Positional/"holding" baseline: how far into enemy territory is typical.

Ad-hoc exploration script (not part of the test suite), same shape as
composite_v2.py. Answers the operator's original framing: "if they are
pushed close to the [enemy] one and holding it that's further than the
average, they should get points for that -- we would need a process for
having a baseline for this on each map, possible over time once we start
collecting positional stats." This is that process's first cut.

## The metric

For every ktp_position_samples row, find the nearest flag that was
ENEMY-OWNED at that exact moment (not "at match end", not "the flag's
final owner" -- owned by the other team at the sample's own event_time),
and take the player's distance to it. Averaged per player, that is roughly
"how deep into contested/enemy territory did this player typically
position themselves" -- lower distance means further forward.

## Where ownership comes from

There is no captured "who started with this flag" fact -- KTPAMXX never
emits one (see NEXT_PHASES.md; a controlpoints_init()-time ownership
marker, mirroring ksc_emit_flag_position's one-shot-per-map-load pattern,
would close this gap but does not exist yet). Ownership is therefore
reconstructed ENTIRELY from ktp_flag_captures: whoever captured a flag
owns it from that event_time until the next capture of the same flag.
Before a flag's first capture in a match, its owner is UNKNOWN, not
guessed -- samples exclude that flag from consideration rather than
assume a starting side. On a short match where a flag never gets
captured at all (this session's real Lane B run only ever contested 2 of
`dod_anzio`'s 5 points), that flag contributes nothing to the baseline at
any point in the match. This is a real, current limitation, not a bug --
it means today's baseline is built from less data than the position
samples alone would suggest, and gets better both with more matches AND
with an eventual initial-ownership marker.

## Why this is a baseline, not a score

One match is not a baseline -- it is one data point pretending to be a
distribution. This script reports the honest sample count alongside every
number for exactly that reason, same as composite_v2.py's flag-weight
confidence note. Nothing here should be read as a finished per-player
"holding" stat; it is the accumulation mechanism the operator asked for,
run once against what exists today.

Usage (inside ktp-lane-b:dev, tests/ and scripts/ mounted):
    scripts/positional_baseline.py <fixture.sql> [<fixture2.sql> ...]

Multiple fixtures accumulate into one baseline -- this is meant to be
re-run as more matches land, not per-match.

## KNOWN BLOCKER (2026-08-14, not yet fixed)

Every fixture produced by a Lane B run so far -- including
regression-2026-08-13-run4-flagcaps, the one this script was validated
against -- has ZERO ktp_flag_positions rows. KTP_FLAG_POSITION (the
one-per-map-load marker ksc_emit_flag_position emits from the
controlpoints_init() DODX forward) never appears anywhere in the captured
game log, even though: the forward is real and correctly declared
(plugins/include/dodx.inc:729 and dodfun.inc:92 in KTPAMXX), the handler
code is present in the compiled plugin, and the plugin finished loading
(per the log's own "[KTP AMX] Loaded 11 plugin(s) during precache"
line) BEFORE DODX's own BSP/objectives parse completed -- so a simple
load-order miss doesn't obviously explain it either. Root cause not yet
isolated; needs real investigation on the KTPAMXX side (a likely next
step: confirm whether controlpoints_init fires at all under
ReHLDS-extension-mode + KTP_LANE_B_FAKECLIENTS, independent of this
script, before assuming the fix is here).

Without flag positions this script cannot compute anything -- there is
nothing to measure distance to. `main()` will run and report the
`no ktp_flag_positions rows -- skipping` line for every fixture until
this is fixed. Logic below (ownership reconstruction, per-sample nearest-
enemy-flag distance, baseline aggregation) is otherwise complete and was
exercised structurally, just never against real (name, x, y) rows.
"""

from __future__ import annotations

import subprocess
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.e2e_stats.ephemeral_mysql import EphemeralMysql  # noqa: E402


def _tsv_rows(s: str):
    if not s.strip():
        return
    for line in s.strip("\n").split("\n")[1:]:  # skip header
        yield line.split("\t")


def load_fixture(db, fixture: Path) -> None:
    argv = [db.client, "--no-defaults", f"--socket={db.socket_path}",
            "-u", "root", db.database]
    with fixture.open("rb") as fh:
        subprocess.run(argv, stdin=fh, check=True)


def build_ownership_timeline(db) -> dict[str, list[tuple[str, str]]]:
    """flag_name -> [(event_time, team), ...] sorted ascending."""
    rows = db.sql("""
        SELECT flag_name, event_time, team
        FROM ktp_flag_captures
        WHERE flag_name IS NOT NULL AND team IS NOT NULL
        ORDER BY flag_name, event_time
    """)
    timeline: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for flag, event_time, team in _tsv_rows(rows):
        timeline[flag].append((event_time, team))
    return timeline


def owner_at(timeline: list[tuple[str, str]], t: str) -> str | None:
    """Last capture at or before t, or None if t precedes the first capture."""
    owner = None
    for event_time, team in timeline:
        if event_time <= t:
            owner = team
        else:
            break
    return owner


def main() -> int:
    fixtures = [Path(p) for p in sys.argv[1:]]
    if not fixtures:
        print(__doc__)
        return 2

    # name -> list of per-sample advancement distances (float, map units)
    player_distances: dict[str, list[float]] = defaultdict(list)
    map_distances: dict[str, list[float]] = defaultdict(list)
    samples_total = 0
    samples_no_known_enemy_flag = 0

    with EphemeralMysql.start(keep=False) as db:
        for fixture in fixtures:
            load_fixture(db, fixture)

            act_map = next(iter(_tsv_rows(db.sql(
                "SELECT act_map FROM hlstats_Servers LIMIT 1"))), ["unknown"])[0]

            flags = {name: (float(x), float(y)) for name, x, y in _tsv_rows(db.sql("""
                SELECT flag_name, origin_x, origin_y FROM ktp_flag_positions
                WHERE map_name = '""" + act_map + """'
            """))}
            if not flags:
                print(f"  {fixture.name} ({act_map}): no ktp_flag_positions rows -- skipping")
                continue

            timeline = build_ownership_timeline(db)

            samples = db.sql("""
                SELECT pn.name, ps.team, ps.pos_x, ps.pos_y, ps.event_time
                FROM ktp_position_samples ps
                JOIN hlstats_PlayerNames pn ON pn.playerId = ps.player_id
                WHERE ps.half > 0
            """)
            fixture_samples = 0
            fixture_excluded = 0
            for name, team, x, y, event_time in _tsv_rows(samples):
                samples_total += 1
                fixture_samples += 1
                px, py = float(x), float(y)
                best = None
                for flag, (fx, fy) in flags.items():
                    owner = owner_at(timeline.get(flag, []), event_time)
                    if owner is None or owner == team:
                        continue  # unknown or own-team: not "enemy territory"
                    d = ((px - fx) ** 2 + (py - fy) ** 2) ** 0.5
                    if best is None or d < best:
                        best = d
                if best is None:
                    samples_no_known_enemy_flag += 1
                    fixture_excluded += 1
                    continue
                player_distances[name].append(best)
                map_distances[act_map].append(best)

            print(f"  {fixture.name} ({act_map}): {fixture_samples} position samples, "
                  f"{fixture_excluded} excluded (no known-enemy flag at that moment)")

    print()
    print(f"=== overall: {samples_total} samples, "
          f"{samples_no_known_enemy_flag} excluded ({samples_no_known_enemy_flag * 100 // max(samples_total, 1)}%) ===")
    print()

    for map_name, dists in sorted(map_distances.items()):
        print(f"=== baseline: {map_name} (n={len(dists)}) ===")
        if len(dists) < 30:
            print(f"  NOTE: n={len(dists)} is not enough samples for a trustworthy baseline "
                  "(one short match, and only the flags that got captured at all "
                  "contribute any data point before their first capture is unknown "
                  "territory). Treat everything below as a first data point, not a "
                  "settled number -- it will move as more matches accumulate.")
        print(f"  mean={mean(dists):.0f}  median={median(dists):.0f}  "
              f"min={min(dists):.0f}  max={max(dists):.0f}  (map units)")
        print()

    if len(map_distances) == 1:
        (map_name, dists), = map_distances.items()
        baseline_mean = mean(dists)
        print(f"=== per-player advancement vs {map_name} baseline (lower avg distance = more forward) ===")
        rows = []
        for name, pdists in player_distances.items():
            pmean = mean(pdists)
            rows.append((name, len(pdists), pmean, baseline_mean - pmean))
        rows.sort(key=lambda r: -r[3])
        print(f"{'name':<12}{'n':>5}{'avg_dist':>10}{'vs_baseline':>14}")
        for name, n, pmean, delta in rows:
            sign = "+" if delta >= 0 else ""
            print(f"{name:<12}{n:>5}{pmean:>10.0f}{sign}{delta:>13.0f}")
        print()
        print("  vs_baseline positive = held closer to enemy-owned flags than the map "
              "average (more forward); negative = further back than average. Not a "
              "score, not weighted into composite_v2.py yet -- this is the raw signal "
              "the operator asked to start accumulating, not a finished feature.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
