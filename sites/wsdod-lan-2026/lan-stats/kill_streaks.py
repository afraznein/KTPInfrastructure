"""Kill streaks, rebuilt from the frag log — the one implementation.

Shared because there were nearly two: build_stats.py needs a player's best
streak of the day and what it was made with, build_awards.py needs the best of
a single match for On A Tear. Two copies of a walk this fiddly drift, and the
first copy already did — the HUD's own `best_streak` column disagrees with the
frag log for a sixth of the field, because it counts teamkills and suicides as
kills and does not reset on every death.

The frag log is the authority. A streak cannot survive a death and does not
carry across the halftime side swap, so each half is walked on its own.
"""

from __future__ import annotations

from collections import Counter
from typing import NamedTuple

# DoD weapon codes as the league says them aloud. Butt-strokes collapse to one
# label because "garandbutt" and "k43butt" are the same act with a different
# rifle, and nobody reads a streak line wanting to know which.
WEAPON_LABELS = {
    "kar": "K98", "scopedkar": "scoped K98", "k43": "K43",
    "garand": "Garand", "spring": "Springfield", "m1carbine": "Carbine",
    "bar": "BAR", "mp44": "STG44", "mp40": "MP40", "thompson": "Thompson",
    "luger": "Luger", "colt": "Colt",
    "grenade": "grenade", "grenade2": "stick grenade",
    "garandbutt": "rifle butt", "k43butt": "rifle butt",
    "spade": "spade", "amerknife": "knife", "bayonet": "bayonet",
}


class Run(NamedTuple):
    """One streak: how long, what with, and where it started.

    `seq` is the position of the run's first kill in the log, which is what
    breaks a tie between two runs of the same length — the earlier one is the
    one a player is credited with.
    """

    length: int
    weapons: Counter
    seq: int


def label_guns(weapons) -> list[str]:
    """{'scopedkar': 12, 'luger': 1} -> ['12 scoped K98', '1 Luger'].

    Unknown codes render as themselves rather than vanishing, so a weapon the
    map pack adds shows up as a question instead of a silently short list.
    """
    named = Counter()
    for code, n in weapons.items():
        named[WEAPON_LABELS.get(code, code)] += n
    return ["%d %s" % (n, label)
            for label, n in sorted(named.items(), key=lambda kv: (-kv[1], kv[0]))]


def best_runs(rows) -> dict[tuple, Run]:
    """Best streak per (match_id, half, player), from frag rows in log order.

    `rows` yields (match_id, half, killer, victim, weapon) with players already
    reduced to canonical SteamIDs. Order is the caller's job and must be the
    log's own — ordering by timestamp instead loses ties within a second, and
    ordering by tick is wrong outright because tick resets mid-half.

    A suicide is not a kill but still ends the streak, which is why the reset
    runs for every row rather than only for the ones that scored.
    """
    best: dict[tuple, Run] = {}
    current: dict[tuple, list] = {}
    for seq, (match_id, half, killer, victim, weapon) in enumerate(rows):
        if killer != victim:
            key = (match_id, half, killer)
            run = current.get(key)
            if run is None:
                run = current[key] = [0, Counter(), seq]
            run[0] += 1
            run[1][weapon] += 1
            previous = best.get(key)
            if previous is None or run[0] > previous.length:
                best[key] = Run(run[0], Counter(run[1]), run[2])
        current.pop((match_id, half, victim), None)
    return best


def best_by(runs, group) -> dict[tuple, tuple]:
    """Fold per-half runs up to a coarser key — a match, or a day.

    `group` maps (match_id, half, steam) to the key wanted. Ties go to the
    earlier run, so a player's credited streak is the first time they did it
    rather than whichever the dictionary happened to yield last.
    """
    out: dict[tuple, tuple] = {}
    for (match_id, half, steam), run in runs.items():
        key = group(match_id, half, steam)
        best = out.get(key)
        if best is None or (run.length, -run.seq) > (best[1].length, -best[1].seq):
            out[key] = ((match_id, half), run)
    return out
