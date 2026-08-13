"""Replay witness.jsonl through the capture code's assist rule.

Distinguishes "the capture code is broken" from "the scenario never occurred".
The rule, from ksc_on_death() in ktp_stats_capture.inc:

    for each player a != killer:
        if g_kscDmgTaken[victim][a] >= KSC_ASSIST_DAMAGE_MIN (50)
        and a is connected and a is on the ENEMY team of the victim
            -> emit an assist

Damage accumulates per (victim, attacker) and is cleared on the victim's death
and respawn. Team is not in the witness rows, so this reports both the strict
count (excluding same-slot self-damage) and the team-agnostic upper bound —
if even the upper bound is zero, no assist was possible and the capture code
emitting nothing is correct behaviour.
"""
import json
import sys
from collections import defaultdict

PATH = sys.argv[1] if len(sys.argv) > 1 else "witness.jsonl"
MIN = 50

dmg = defaultdict(lambda: defaultdict(int))
deaths = 0
would_assist = 0
multi_attacker_deaths = 0
best = []

for line in open(PATH, encoding="utf-8", errors="replace"):
    try:
        row = json.loads(line)
    except ValueError:
        continue
    ev, a = row.get("event"), row.get("args", {})

    if ev == "dod_client_damage":
        att, vic, d = a.get("attacker"), a.get("victim"), a.get("damage", 0)
        if att and vic and att != vic:          # ignore self/world damage
            dmg[vic][att] += d

    elif ev == "dod_client_death":
        killer, victim = a.get("killer"), a.get("victim")
        deaths += 1
        contributors = {k: v for k, v in dmg[victim].items() if k != killer}
        if contributors:
            multi_attacker_deaths += 1
        qualifying = {k: v for k, v in contributors.items() if v >= MIN}
        if qualifying:
            would_assist += len(qualifying)
            best.append((victim, killer, qualifying))
        dmg[victim].clear()

    elif ev == "dod_client_spawn":
        dmg[a.get("id")].clear()

print(f"deaths observed:                      {deaths}")
print(f"deaths with a non-killer contributor: {multi_attacker_deaths}")
print(f"assists the rule would emit (>={MIN}):  {would_assist}")
print()
if best:
    print("qualifying cases (victim, killer, {assister: damage}):")
    for v, k, q in best[:10]:
        print(f"  victim={v} killer={k} {q}")
else:
    print("No death had a non-killer attacker at >=50 accumulated damage.")
    print("=> zero assists is CORRECT behaviour for this sample, not a bug.")

# What would a lower threshold have produced? Tells us how close we were.
for thresh in (40, 30, 20, 10, 1):
    dmg2 = defaultdict(lambda: defaultdict(int))
    n = 0
    for line in open(PATH, encoding="utf-8", errors="replace"):
        try:
            row = json.loads(line)
        except ValueError:
            continue
        ev, a = row.get("event"), row.get("args", {})
        if ev == "dod_client_damage":
            att, vic, d = a.get("attacker"), a.get("victim"), a.get("damage", 0)
            if att and vic and att != vic:
                dmg2[vic][att] += d
        elif ev == "dod_client_death":
            killer, victim = a.get("killer"), a.get("victim")
            n += sum(1 for k, v in dmg2[victim].items() if k != killer and v >= thresh)
            dmg2[victim].clear()
        elif ev == "dod_client_spawn":
            dmg2[a.get("id")].clear()
    print(f"  at threshold {thresh:>3}: {n} assist(s)")
