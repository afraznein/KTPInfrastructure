"""Interrupted captures: the flag someone was taking, and the player who stopped them.

Every other class in this pipeline is anchored on a capture that COMPLETED. An
interruption is the one that did not: a player stood on a flag, got most of the
way, and someone killed them off it. It is invisible in the box score (no
capture, no objective points) and invisible in the flag log (ownership never
changed), which is exactly the shape of value this workstream exists to find.

MEASURED BEFORE BUILT, THEN REPLICATED (coordination:
infra-hidden-value-plays, 2026-09-28 and 2026-10-02). Asked forward from the
event, the way a preventive class must be: P(the capturing side caps out
within 120 s) against that side's chance at a random moment in the same half.

The direction holds on independent data. Officials gave a steep dose-response
on a thin sample; 12-mans reproduce the SHAPE on five times the events --
every band below chance, monotone in progress, the control nearest chance --
but at a far milder magnitude. Officials' 0.38 and 0.00 rested on n=22 and
n=10, and one more league week regressed them to 0.85 and 0.83: they were
noise, and the larger sample was right. The honest estimate is a modest ~0.8
in the strong bands. Scrims show no effect at all, with the control more
suppressed than the strong bands. Full table in SUPPRESSION_BANDS.

That replication is why this class was built and the excursion class was not:
no tightening of that one ever beat chance, in any sample.

This module reports evidence and never a price. A row names its band and
carries EVERY corpus's measurement, because they disagree and one number would
hide it; `PRICING_CORPUS` names which to price on and the ledger in
`infra-mmr-ratings` decides what that is worth.

Private. Positions never enter here; it reads the attempt feed, the frag feed
and the life feed, all of which are already in the report.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

DEFINITION = "interruptions_v1"
DEFINITION_VERSION = 2

# Bands as measured, lowest first, with EVERY corpus they were measured on --
# because they do not agree, and a single number here would hide that.
#
# `lift` is P(the capturing side still caps out within 120 s) relative to that
# side's chance at a random moment in the same half. Below 1.0 means the
# interruption suppressed the cap-out.
#
#   band         officials        12-mans          scrims
#   negligible   0.94 (n=223)     0.97 (n=923)     0.82 (n=667)
#   partial      0.99 (n=133)     0.82 (n=188)     0.99 (n=203)
#   substantial  0.85 (n=77)      0.74 (n=118)     0.89 (n=117)
#   decisive     0.83 (n=32)      0.71 (n=59)      1.06 (n=56)
#
# The DIRECTION replicates on 12-mans -- every band below chance, monotone in
# progress, control nearest chance -- on five times the events. The MAGNITUDE
# did not, and the officials column above is the proof: measured first on 54
# halves it read 0.64 / 0.38 / 0.00 with n=45/22/10, and after one more league
# week (76 halves, n=133/77/32) it regressed to 0.99 / 0.85 / 0.83 -- onto the
# 12-man magnitudes, which is what pricing on the larger sample was for. The
# honest estimate is a modest ~0.8 in the strong bands.
# Scrims show no effect at all, with the control MORE suppressed than the
# strong bands, i.e. the pattern inverted; that is either looser play not
# following up a stopped capture, or noise, and these samples cannot tell the
# two apart.
#
# The apparent ordering across match types is NOT real (checked 2026-10-02 by
# holding the map fixed, which is the only way to separate a match-type effect
# from map mix -- officials play one map a week while practice sprawls across
# many, and cap-out rates differ ~12x by map). On harrington, the one map all
# three types share, the strong-band lift reads 0.76 official / 0.35 12-man /
# 1.16 scrim: the three types in the WRONG order for the pooled story. Across
# eight map-by-type cells the lift ranges 0.35 to 1.92, and every one of them
# sits within 1.3 sigma of what a single pooled suppression of ~0.80 predicts,
# bar one cell at 2.1 which is what testing eight cells buys you.
#
# So one number fits everything we have. Do NOT build per-map or per-type
# interruption pricing: at 20-120 events a cell there is no signal to fit, and
# this is not in tension with the per-map flag COEFFICIENTS, which are fit on
# thousands of samples a map.
#
# Price on the 12-man column, the largest clean sample, and treat officials as
# the optimistic bound until official weeks accumulate. Re-measure with
# review/hidden-value/tools/hv_interrupt.py, which takes the match types as its
# third argument and `--by-map` for the per-map cut.
SUPPRESSION_BANDS: tuple[tuple[str, int, dict[str, tuple[float, int]]], ...] = (
    ("negligible", 0, {"official": (0.94, 223), "twelve_man": (0.97, 923),
                       "scrim": (0.82, 667)}),
    ("partial", 25, {"official": (0.99, 133), "twelve_man": (0.82, 188),
                     "scrim": (0.99, 203)}),
    ("substantial", 50, {"official": (0.85, 77), "twelve_man": (0.74, 118),
                         "scrim": (0.89, 117)}),
    ("decisive", 75, {"official": (0.83, 32), "twelve_man": (0.71, 59),
                      "scrim": (1.06, 56)}),
)

# Which corpus a consumer should price on, and why: the largest sample whose
# dose-response holds. Still the 12-man column after the 2026-10-05 re-measure --
# officials converged onto it but are NOT monotone (control 0.94 sits below
# partial 0.99), so they do not yet hold the shape on their own.
PRICING_CORPUS = "twelve_man"


@dataclass(frozen=True)
class InterruptionConfig:
    credit_window_seconds: float = 4.0   # a kill this long before the stop stopped it
    min_peak_progress: int = 0           # keep everything; bands carry the meaning

    def validate(self) -> None:
        if self.credit_window_seconds <= 0:
            raise ValueError("credit_window_seconds must be positive")


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


def band_for(peak_progress: int | None) -> dict[str, Any]:
    """The measured band this interruption falls in, with ALL its evidence.

    Named rather than priced, and deliberately not reducible to one number:
    the three corpora disagree on magnitude (see SUPPRESSION_BANDS), so a row
    carries every measurement and names which one to price on. A consumer that
    reads `measured_lift` alone would take officials' 0.00 for "a decisive
    interruption always prevents the cap-out", which five times more data
    contradicts.
    """
    peak = peak_progress or 0
    name, floor, measured = SUPPRESSION_BANDS[0]
    for candidate in SUPPRESSION_BANDS:
        if peak >= candidate[1]:
            name, floor, measured = candidate
    lift, n = measured[PRICING_CORPUS]
    return {
        "band": name,
        "peak_progress_floor": floor,
        "measured_lift": lift,              # from PRICING_CORPUS, not officials
        "measured_n": n,
        "measured_corpus": PRICING_CORPUS,
        "measured_all_corpora": {corpus: {"lift": value, "n": count}
                                 for corpus, (value, count) in sorted(measured.items())},
    }


def build_interruptions(
    attempt_rows: Sequence[dict[str, Any]] | None,
    frags: Sequence[dict[str, Any]] | None,
    life_boundaries: Sequence[dict[str, Any]] | None,
    config: InterruptionConfig | None = None,
    *,
    source_status: str = "available",
) -> dict[str, Any]:
    """Captures that were begun and stopped, with who stopped them.

    `rows`: half, game_time, flag, capturing_team, defending_team,
    peak_progress, attackers_in_zone, defenders_in_zone, credited (defenders
    who killed a capturing-side player inside the credit window), and the
    measured suppression band.
    """
    cfg = config or InterruptionConfig()
    cfg.validate()
    envelope: dict[str, Any] = {
        "definition": DEFINITION,
        "definition_version": DEFINITION_VERSION,
        "parameters": asdict(cfg),
        "status": "available",
        "visibility": "private_shadow_only",
        "writes": False,
        "rating_effect": False,
        "caveats": [
            "Band lifts come from the 12-man corpus, the largest sample whose "
            "dose-response holds (negligible 0.97 -> decisive 0.71 over 1,111 "
            "events). The direction replicated from officials; the MAGNITUDE "
            "did not -- officials' 0.38 and 0.00 on n=22 and n=10 were "
            "small-sample noise. Scrims show no effect at all. Every "
            "measurement is on the row as measured_all_corpora; this module "
            "prices nothing.",
        ],
        "rows": [],
        "by_band": {},
    }
    if source_status != "available" or not attempt_rows:
        envelope["status"] = "unavailable"
        envelope["caveats"].append("objective attempt feed missing.")
        return envelope

    # A frag's side comes from the life feed for THAT half: a player's roster
    # team is the side held in the last half they appeared in, which puts a
    # half-time leaver on the wrong team (see scripts/roster_teams.py).
    sides: dict[tuple[int, int], int] = {}
    for row in life_boundaries or []:
        half, pid, team = _i(row.get("half")), _i(row.get("player_id")), _i(row.get("team"))
        if half is not None and pid is not None and team in (1, 2):
            sides.setdefault((half, pid), team)

    kills: dict[int, list[tuple[float, int, int]]] = {}
    for row in frags or []:
        half, at = _i(row.get("half")), _f(row.get("game_time"))
        killer, victim = _i(row.get("killer_id")), _i(row.get("victim_id"))
        if half is None or at is None or killer is None or victim is None:
            continue
        kills.setdefault(half, []).append((at, killer, victim))
    for half in kills:
        kills[half].sort()

    for row in attempt_rows:
        if str(row.get("event_kind")) != "stop":
            continue
        if str(row.get("stop_reason")) != "capture_stopped":
            continue
        half, at = _i(row.get("half")), _f(row.get("game_time"))
        capturing = _i(row.get("capturing_team"))
        if half is None or at is None or capturing not in (1, 2):
            continue
        peak = _i(row.get("peak_progress")) or 0
        if peak < cfg.min_peak_progress:
            continue
        defending = 2 if capturing == 1 else 1

        # Whoever killed a capturing-side player in the seconds before the
        # stop is who stopped it. Several defenders can share one stop; a stop
        # with nobody credited is real too (the capper walked off, or died to
        # something the frag feed does not carry) and is kept, unattributed.
        credited: list[int] = []
        for kill_at, killer, victim in kills.get(half, ()):
            if kill_at > at:
                break
            if at - kill_at > cfg.credit_window_seconds:
                continue
            if (sides.get((half, victim)) == capturing
                    and sides.get((half, killer)) == defending
                    and killer not in credited):
                credited.append(killer)

        entry = {
            "half": half,
            "game_time": round(at, 2),
            "flag": row.get("flag_name"),
            "capturing_team": capturing,
            "defending_team": defending,
            "peak_progress": peak,
            "attackers_in_zone": _i(row.get("allies_in_zone") if capturing == 1
                                    else row.get("axis_in_zone")),
            "defenders_in_zone": _i(row.get("axis_in_zone") if capturing == 1
                                    else row.get("allies_in_zone")),
            "credited": credited,
            **band_for(peak),
        }
        envelope["rows"].append(entry)

    by_band: dict[str, dict[str, int]] = {}
    for entry in envelope["rows"]:
        stat = by_band.setdefault(entry["band"], {"events": 0, "attributed": 0})
        stat["events"] += 1
        stat["attributed"] += bool(entry["credited"])
    envelope["by_band"] = by_band
    return envelope
