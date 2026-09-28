"""Interrupted captures: the flag someone was taking, and the player who stopped them.

Every other class in this pipeline is anchored on a capture that COMPLETED. An
interruption is the one that did not: a player stood on a flag, got most of the
way, and someone killed them off it. It is invisible in the box score (no
capture, no objective points) and invisible in the flag log (ownership never
changed), which is exactly the shape of value this workstream exists to find.

MEASURED BEFORE BUILT (coordination: infra-hidden-value-plays, 2026-09-28).
Asked forward from the event, the way a preventive class must be -- P(the
capturing side caps out within 120 s) against that side's chance at a random
moment in the same half, over 54 official halves and 231 interruptions:

    all 231       0.91
    peak >= 25%   0.64   (n=45)
    peak >= 50%   0.38   (n=22)
    peak >= 75%   0.00   (n=10)
    peak < 25%    0.99   (n=186, the control)

The further a capture had got, the more stopping it suppresses the cap-out, and
interruptions of captures that barely started sit exactly at chance. Dose
response with a flat control is why this class was built and the excursion
class was not: no tightening of that one ever beat chance.

The high bands are thin -- 1 of 22 and 0 of 10 -- so the TREND carries the
claim and no single band is significant on its own. This module therefore
reports evidence and never a price: `suppression_band` names which measured
band a row falls in, and the ledger in `infra-mmr-ratings` decides what a band
is worth once more weeks land.

Private. Positions never enter here; it reads the attempt feed, the frag feed
and the life feed, all of which are already in the report.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

DEFINITION = "interruptions_v1"
DEFINITION_VERSION = 1

# Bands as measured, lowest first. `lift` is P(the capturing side still caps
# out) relative to chance: below 1.0 means the interruption suppressed it.
SUPPRESSION_BANDS: tuple[tuple[str, int, float, int], ...] = (
    ("negligible", 0, 0.99, 186),
    ("partial", 25, 0.64, 45),
    ("substantial", 50, 0.38, 22),
    ("decisive", 75, 0.00, 10),
)


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
    """The measured band this interruption falls in, with its evidence.

    Named rather than priced: the sample behind the top bands is thin, and a
    consumer that wants a number should read `measured_lift` knowing `n`.
    """
    peak = peak_progress or 0
    name, floor, lift, n = SUPPRESSION_BANDS[0]
    for candidate in SUPPRESSION_BANDS:
        if peak >= candidate[1]:
            name, floor, lift, n = candidate
    return {"band": name, "peak_progress_floor": floor,
            "measured_lift": lift, "measured_n": n}


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
            "Bands are measured on 54 official halves; the top two rest on "
            "n=22 and n=10, so the trend carries the claim and no band is "
            "significant alone. Evidence only -- this module prices nothing.",
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
