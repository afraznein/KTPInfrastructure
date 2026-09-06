"""Objective-control shadow stats: team recap speed (definition v1).

Recap speed measures how quickly a team retakes a flag it lost: for each
flag, the producer-clock seconds between an ownership change away from the
team and the next change back to it, within one half. Private shadow only:
no writes, no rating impact.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def _game_time(row: dict[str, Any]) -> float | None:
    value = row.get("game_time")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_recap_speed(
    flag_states: Sequence[dict[str, Any]] | None,
    *,
    source_available: bool = True,
    temporal_valid: bool = True,
) -> dict[str, Any]:
    """Per-team recap intervals from the flag-state ownership timeline.

    Only completed loss->retake pairs inside one half count; a flag still
    lost at half end is censored, never guessed. Virgin/neutral owners end
    a hold but never start one.
    """
    envelope: dict[str, Any] = {
        "definition": "recap_speed_v1",
        "definition_version": 1,
        "parameters": {
            "clock": "producer_game_time",
            "pair": "ownership_change_away_then_back_same_half_same_flag",
            "open_at_half_end": "censored",
        },
        "status": "available",
        "visibility": "private_shadow_only",
        "writes": False,
        "rating_effect": False,
        "caveats": [],
        "teams": [],
        "recaps": [],
    }
    if not temporal_valid:
        envelope["status"] = "timed_metrics_suppressed"
        envelope["caveats"].append(
            "Replay timing is compressed; recap intervals need real clocks.")
        return envelope
    if not source_available or flag_states is None:
        envelope["status"] = "unavailable"
        envelope["caveats"].append("Flag-state timeline unavailable.")
        return envelope

    usable = [row for row in flag_states
              if row.get("half") and _game_time(row) is not None
              and row.get("flag_index") is not None]
    usable.sort(key=lambda r: (int(r["half"]), int(r["flag_index"]),
                               _game_time(r)))
    lost_since: dict[tuple[int, int, int], float] = {}
    owner_now: dict[tuple[int, int], int | None] = {}
    recaps: list[dict[str, Any]] = []
    for row in usable:
        half = int(row["half"])
        flag = int(row["flag_index"])
        owner = row.get("owner_team")
        owner = int(owner) if owner is not None else None
        at = _game_time(row)
        previous = owner_now.get((half, flag))
        owner_now[(half, flag)] = owner
        if bool(row.get("is_initial")):
            continue
        if previous in (1, 2) and owner != previous:
            lost_since.setdefault((half, flag, previous), at)
        if owner in (1, 2):
            key = (half, flag, owner)
            if key in lost_since:
                lost_at = lost_since.pop(key)
                recaps.append({
                    "half": half, "flag_index": flag,
                    "flag_name": row.get("flag_name"),
                    "team": owner,
                    "lost_at": lost_at,
                    "retaken_at": at,
                    "seconds": round(at - lost_at, 3),
                })
    envelope["recaps"] = recaps
    by_team: dict[int, list[float]] = {}
    for recap in recaps:
        by_team.setdefault(recap["team"], []).append(recap["seconds"])
    for team in sorted(by_team):
        seconds = sorted(by_team[team])
        mid = len(seconds) // 2
        median = (seconds[mid] if len(seconds) % 2
                  else (seconds[mid - 1] + seconds[mid]) / 2.0)
        envelope["teams"].append({
            "team": team,
            "recaps": len(seconds),
            "median_seconds": round(median, 3),
            "mean_seconds": round(sum(seconds) / len(seconds), 3),
        })
    envelope["censored_open_losses"] = len(lost_since)
    return envelope
