"""Brinks: the moment a side is one flag from a cap-out, and who put it there.

The win-probability model pays for flags by where they move P(win), and that
curve is flattening exactly where the round is about to end. On anzio, taking
the fourth of five flags prices at +0.126 and taking the fifth at +0.102 -- so
the THREAT of a cap-out, which is what turns the enemy team around and buys
space, is worth nothing while the completion is worth something. Drew's case,
from his own anzio half (2026-10-04, 1791141012-NY2): he reached the brink three
times, was the credited capper each time, and the report paid him +0.24, +0.18
and +0.16 as if they were ordinary flags.

MEASURED BEFORE BUILT, against the fair comparison -- the same sides taking one
fewer flag, not a random moment, because at a random moment a side is often
already below half and "collapsed" is true before anything happens:

    sample                  n      cap-out follows   collapsed   flags at +90s
    reached N-1 (brink)     963         26.1%          43.0%         2.56
    reached N-2 (one short) 1942        13.4%          46.0%         2.49

So the upside is real and large: reaching the brink roughly DOUBLES the chance
of a cap-out inside 90 s (1.58x against a random moment, 1.95x against stopping
one flag short). That is the threat earning its keep.

THE OVEREXTENSION DEBIT IS NOT PRICED, DELIBERATELY. Drew asked for one: a side
that reaches the brink and then loses ground should be punished a little. At the
TEAM level the data says the opposite -- collapse runs 43.0% after a brink
against 46.0% after stopping one short, and the side ends the window holding
MORE flags. There is nothing to debit there. The PLAYER-level version may well
be real (his own push ended with him dead on the enemy's last flag, a cost to
him and not to his team), but that is the excursion-exposure question, and the
excursion class beat chance at no tightening whatsoever. So the debit waits for
a measurement that supports a number rather than being invented at the size
that feels right.

Private. Reads the flag-state feed and the capture-credit feed, both already in
the report.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

DEFINITION = "brinks_v1"
DEFINITION_VERSION = 1

# Measured on 76 official halves since 2026-09-13 (hv_brink.py). `fair` is the
# same sides reaching one flag FEWER -- the comparison that answers "was
# pushing worth it", where a random moment answers a different question.
MEASURED = {
    "window_seconds": 90.0,
    "brink": {"n": 963, "converts": 0.261, "collapses": 0.430, "flags_at_end": 2.56},
    "fair": {"n": 1942, "converts": 0.134, "collapses": 0.460, "flags_at_end": 2.49},
    "convert_lift_vs_fair": 1.95,
    "convert_lift_vs_random": 1.58,
    "collapse_lift_vs_fair": 0.93,
}


@dataclass(frozen=True)
class BrinkConfig:
    window_seconds: float = 90.0     # the horizon the conversion rate was measured over
    credit_tolerance: float = 3.0    # a credit this close to the transition took the flag

    def validate(self) -> None:
        if self.window_seconds <= 0 or self.credit_tolerance <= 0:
            raise ValueError("window_seconds and credit_tolerance must be positive")


def _i(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _f(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_brinks(
    flag_states: Sequence[dict[str, Any]] | None,
    capture_credits: Sequence[dict[str, Any]] | None = None,
    config: BrinkConfig | None = None,
    *,
    source_status: str = "available",
) -> dict[str, Any]:
    """Every moment a side first reached one flag short of a cap-out.

    `rows`: half, game_time, side, flags_held, flag_count, flag (the one that
    brought them there), credited (who took it), converted (cap-out inside the
    window), flags_at_window_end, collapsed, and the measured conversion rate
    for this situation.
    """
    cfg = config or BrinkConfig()
    cfg.validate()
    envelope: dict[str, Any] = {
        "definition": DEFINITION,
        "definition_version": DEFINITION_VERSION,
        "parameters": asdict(cfg),
        "measured": MEASURED,
        "status": "available",
        "visibility": "private_shadow_only",
        "writes": False,
        "rating_effect": False,
        "caveats": [
            "Upside only. Reaching the brink converts at 26.1% against 13.4% "
            "for the same sides taking one flag fewer, so the threat is worth "
            "paying for. The overextension debit drew asked for is NOT here: "
            "at team level a brink makes collapse LESS likely (43.0% vs "
            "46.0%), so there is nothing to debit, and the player-level cost "
            "belongs to excursion exposure, which has never beaten chance. "
            "This block prices nothing.",
        ],
        "rows": [],
        "by_half": {},
    }
    if source_status != "available" or not flag_states:
        envelope["status"] = "unavailable"
        envelope["caveats"].append("flag ownership feed missing.")
        return envelope

    # Credits indexed by (half, flag) so the capper can be named at a transition.
    credits: dict[tuple[int, str], list[tuple[float, int]]] = {}
    for row in capture_credits or []:
        half, flag = _i(row.get("half")), row.get("flag_name")
        at, pid = _f(row.get("game_time")), _i(row.get("player_id"))
        if half is None or flag is None or at is None or pid is None:
            continue
        credits.setdefault((half, str(flag)), []).append((at, pid))

    by_half: dict[int, list[tuple[float, str, int, bool]]] = {}
    for row in flag_states:
        half, flag = _i(row.get("half")), row.get("flag_name")
        at, owner = _f(row.get("game_time")), _i(row.get("owner_team"))
        if half is None or flag is None or at is None or owner is None:
            continue
        by_half.setdefault(half, []).append(
            (at, str(flag), owner, bool(row.get("is_initial"))))

    for half, events in sorted(by_half.items()):
        events.sort(key=lambda e: e[0])
        flag_count = len({flag for _at, flag, _o, _init in events})
        if flag_count < 3:
            continue        # a cap-out on two flags is not a brink, it is the cap
        initial = {flag: owner for _at, flag, owner, init in events if init}
        owners = dict(initial)
        # The walk has to be replayed twice -- once to find the brinks, once to
        # read each one's forward window -- so keep the whole state series.
        series: list[tuple[float, dict[int, int], str, int]] = []
        for at, flag, owner, init in events:
            if init:
                continue
            owners[flag] = owner
            held = {side: sum(1 for v in owners.values() if v == side)
                    for side in (1, 2)}
            series.append((at, dict(held), flag, owner))

        # A brink is REACHED FROM BELOW. A side that merely loses a flag from a
        # cap-out, or that starts the half holding all but one, has not pushed
        # to anything -- it is being pushed. Seeded from the initial ownership
        # so the opening transition cannot read as the defending side arriving
        # at a threat it never made.
        previous = {side: sum(1 for v in initial.values() if v == side)
                    for side in (1, 2)}
        for index, (at, held, flag, _owner) in enumerate(series):
            for side in (1, 2):
                reached = (held[side] == flag_count - 1
                           and previous[side] < flag_count - 1)
                if reached:
                    converted = False
                    end_held = held[side]
                    for later_at, later_held, _f2, _o2 in series[index + 1:]:
                        if later_at - at > cfg.window_seconds:
                            break
                        if later_held[side] == flag_count:
                            converted = True
                        end_held = later_held[side]
                    credited = [pid for credit_at, pid
                                in credits.get((half, flag), ())
                                if abs(credit_at - at) <= cfg.credit_tolerance]
                    envelope["rows"].append({
                        "half": half,
                        "game_time": round(at, 2),
                        "side": side,
                        "flag": flag,
                        "flags_held": held[side],
                        "flag_count": flag_count,
                        "credited": credited,
                        "converted": converted,
                        "flags_at_window_end": end_held,
                        "collapsed": end_held <= flag_count // 2,
                        "measured_convert_rate": MEASURED["brink"]["converts"],
                        "measured_convert_lift_vs_fair":
                            MEASURED["convert_lift_vs_fair"],
                    })
            previous = dict(held)

    stats: dict[str, dict[str, int]] = {}
    for row in envelope["rows"]:
        stat = stats.setdefault(str(row["half"]),
                                {"brinks": 0, "converted": 0, "attributed": 0})
        stat["brinks"] += 1
        stat["converted"] += bool(row["converted"])
        stat["attributed"] += bool(row["credited"])
    envelope["by_half"] = stats
    return envelope
