"""Flag-fight shadow exploration (Tier 2, definition v1).

Segments a match into flag fights — one objective-attempt window per
(half, attempt_id) — and computes the round-shaped stats on them: opening
kills, per-fight kills/deaths/assists, traded deaths, and KAST-F (the
share of fights where a player killed, assisted, survived, or was traded).

Private shadow only: no database writes, no public API output, no rating
impact. All membership uses the producer clock (half + game_time), the
same domain the objective-attempt ledger records, so daemon receipt delay
cannot move an event across a window boundary.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from typing import Any

_SOURCE_NAMES = ("objective_attempts", "frags", "assists", "basic_trades")

_TERMINAL_KINDS = {"complete", "stop"}


@dataclass
class FlagFightConfig:
    """Membership padding around the attempt window, producer seconds.

    Opening kills routinely precede the attempt-start marker (the point is
    cleared before anyone stands on it), so the frag membership window
    opens pre_window_seconds early and closes post_window_seconds late.
    """

    pre_window_seconds: float = 10.0
    post_window_seconds: float = 5.0

    def validate(self) -> None:
        if self.pre_window_seconds < 0 or self.post_window_seconds < 0:
            raise ValueError("flag-fight window padding must be >= 0")


def _rows(rows: Sequence[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return list(rows) if rows else []


def _availability(
    source_available: bool | Mapping[str, bool],
    supplied: Mapping[str, Sequence[dict[str, Any]] | None],
) -> dict[str, bool]:
    if isinstance(source_available, Mapping):
        return {name: bool(source_available.get(name, supplied[name] is not None))
                for name in _SOURCE_NAMES}
    return {name: bool(source_available) for name in _SOURCE_NAMES}


def _game_time(row: Mapping[str, Any]) -> float | None:
    value = row.get("game_time")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _build_windows(
    attempts: Sequence[dict[str, Any]], config: FlagFightConfig
) -> tuple[list[dict[str, Any]], int]:
    """One window per (half, attempt_id): start row through last terminal row."""
    grouped: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for row in attempts:
        half = _int_or_none(row.get("half"))
        attempt_id = _int_or_none(row.get("attempt_id"))
        if half is None or half <= 0 or attempt_id is None:
            continue
        grouped.setdefault((half, attempt_id), []).append(row)

    windows: list[dict[str, Any]] = []
    incomplete = 0
    for (half, attempt_id), rows in sorted(grouped.items()):
        starts = [r for r in rows if str(r.get("event_kind")) == "start"]
        terminals = [r for r in rows
                     if str(r.get("event_kind")) in _TERMINAL_KINDS]
        start_times = sorted(t for r in starts if (t := _game_time(r)) is not None)
        end_times = sorted(t for r in terminals if (t := _game_time(r)) is not None)
        if not start_times or not end_times or end_times[-1] < start_times[0]:
            incomplete += 1
            continue
        start_row = starts[0]
        captured = any(str(r.get("event_kind")) == "complete" for r in terminals)
        stop_reasons = sorted({str(r.get("stop_reason"))
                               for r in terminals
                               if str(r.get("event_kind")) == "stop"
                               and r.get("stop_reason") is not None})
        started, ended = start_times[0], end_times[-1]
        windows.append({
            "half": half,
            "attempt_id": attempt_id,
            "flag_index": _int_or_none(start_row.get("flag_index")),
            "flag_name": start_row.get("flag_name"),
            "capturing_team": _int_or_none(start_row.get("capturing_team")),
            "started_game_time": started,
            "ended_game_time": ended,
            "duration_seconds": round(ended - started, 3),
            "outcome": "capture" if captured else "stop",
            "stop_reasons": stop_reasons,
            "membership_start": started - config.pre_window_seconds,
            "membership_end": ended + config.post_window_seconds,
            "opening": None,
            "frag_event_ids": [],
        })
    return windows, incomplete


def _frag_sort_key(row: Mapping[str, Any]) -> tuple[float, float]:
    game_time = _game_time(row)
    try:
        unix = float(row.get("event_unix") or 0.0)
    except (TypeError, ValueError):
        unix = 0.0
    return (game_time if game_time is not None else 0.0, unix)


def _identity(row: Mapping[str, Any], role: str) -> dict[str, Any]:
    return {
        "player_id": _int_or_none(row.get(f"{role}_id")),
        "player_name": row.get(f"{role}_name"),
        "team": _int_or_none(row.get(f"{role}_team")),
    }


def build_flag_fight_shadow(
    objective_attempts: Sequence[dict[str, Any]] | None,
    frags: Sequence[dict[str, Any]] | None,
    assist_timeline: Sequence[dict[str, Any]] | None,
    basic_trades: Sequence[dict[str, Any]] | None,
    roster_player_ids: Sequence[int] | None = None,
    config: FlagFightConfig | None = None,
    *,
    source_available: bool | Mapping[str, bool] = True,
    temporal_valid: bool = True,
) -> dict[str, Any]:
    """Aggregate flag-fight windows and per-player fight stats.

    ``frags`` must be the producer-clock frag context feed (rows carry
    ``game_time``); rows without a usable half or game_time are excluded
    and counted rather than silently guessed into a window.  A missing
    frag or attempt source suppresses everything; missing assists or
    trades suppress only KAST-F, because treating an absent component as
    zero contribution would understate coverage.
    """
    config = config or FlagFightConfig()
    config.validate()
    supplied = {
        "objective_attempts": objective_attempts,
        "frags": frags,
        "assists": assist_timeline,
        "basic_trades": basic_trades,
    }
    available = _availability(source_available, supplied)
    materialized = {name: _rows(rows) for name, rows in supplied.items()}

    envelope: dict[str, Any] = {
        "definition": "flag_fight_windows_v1",
        "definition_version": 1,
        "parameters": {
            **asdict(config),
            "window_unit": "objective_attempt",
            "clock": "producer_game_time",
            "survival_component": True,
            "covered_if_any": ["kill", "assist", "survived", "death_was_traded"],
            "opening": "first_frag_in_membership_window",
            "overlapping_windows": "events_may_count_in_each",
        },
        "status": "available",
        "source_coverage": {
            name: {
                "available": available[name],
                "rows_received": (len(materialized[name])
                                  if supplied[name] is not None else None),
            }
            for name in _SOURCE_NAMES
        },
        "visibility": "private_shadow_only",
        "writes": False,
        "rating_effect": False,
        "caveats": [],
        "windows": [],
        "players": [],
        "summary": {},
    }

    if not temporal_valid:
        envelope["status"] = "timed_metrics_suppressed"
        envelope["caveats"].append(
            "Replay timing is compressed; fight windows need real producer clocks.")
        return envelope
    if not available["objective_attempts"] or not available["frags"]:
        envelope["status"] = "unavailable"
        envelope["caveats"].append(
            "Objective-attempt and producer-clock frag feeds are both required.")
        return envelope

    windows, incomplete = _build_windows(
        materialized["objective_attempts"], config)
    envelope["summary"]["attempts_without_closed_window"] = incomplete
    if not windows:
        envelope["status"] = "no_fight_windows"
        return envelope

    usable_frags: list[dict[str, Any]] = []
    frags_excluded = 0
    for row in materialized["frags"]:
        half = _int_or_none(row.get("half"))
        if half is None or half <= 0 or _game_time(row) is None:
            frags_excluded += 1
            continue
        usable_frags.append(row)
    envelope["summary"]["frags_excluded_missing_clock"] = frags_excluded

    kast_available = available["assists"] and available["basic_trades"]
    if not kast_available:
        envelope["caveats"].append(
            "KAST-F suppressed: assist or trade source unavailable.")

    traded_death_ids = {
        _int_or_none(row.get("death_event_id"))
        for row in materialized["basic_trades"]
    } - {None}

    roster = sorted({int(pid) for pid in (roster_player_ids or [])})
    per_player: dict[int, dict[str, Any]] = {
        pid: {
            "player_id": pid, "fights": 0, "fights_covered": 0,
            "kills": 0, "deaths": 0, "assists": 0, "deaths_traded": 0,
            "openings_won": 0, "openings_lost": 0,
        }
        for pid in roster
    }

    captures = 0
    for window in windows:
        half = window["half"]
        in_window = [
            row for row in usable_frags
            if _int_or_none(row.get("half")) == half
            and window["membership_start"] <= _game_time(row)
            <= window["membership_end"]
        ]
        in_window.sort(key=_frag_sort_key)
        window["frag_event_ids"] = [
            _int_or_none(row.get("event_id")) for row in in_window]
        assists_in_window = [
            row for row in materialized["assists"]
            if _int_or_none(row.get("half")) == half
            and (t := _game_time(row)) is not None
            and window["membership_start"] <= t <= window["membership_end"]
        ] if available["assists"] else []
        if in_window:
            opening = in_window[0]
            window["opening"] = {
                "event_id": _int_or_none(opening.get("event_id")),
                "game_time": _game_time(opening),
                "killer": _identity(opening, "killer"),
                "victim": _identity(opening, "victim"),
                "weapon": opening.get("weapon"),
                "won_by_capturing_team": (
                    _int_or_none(opening.get("killer_team"))
                    == window["capturing_team"]
                    if window["capturing_team"] is not None else None
                ),
            }
        if window["outcome"] == "capture":
            captures += 1

        killed_by: dict[int, int] = {}
        died: dict[int, list[int | None]] = {}
        assisted: set[int] = set()
        for row in in_window:
            killer = _int_or_none(row.get("killer_id"))
            victim = _int_or_none(row.get("victim_id"))
            if killer is not None:
                killed_by[killer] = killed_by.get(killer, 0) + 1
            if victim is not None:
                died.setdefault(victim, []).append(
                    _int_or_none(row.get("event_id")))
        for row in assists_in_window:
            assister = _int_or_none(row.get("assister_id"))
            if assister is not None:
                assisted.add(assister)

        for pid, stats in per_player.items():
            stats["fights"] += 1
            kills = killed_by.get(pid, 0)
            death_ids = died.get(pid, [])
            stats["kills"] += kills
            stats["deaths"] += len(death_ids)
            traded = any(eid in traded_death_ids for eid in death_ids)
            if traded:
                stats["deaths_traded"] += 1
            if pid in assisted:
                stats["assists"] += 1
            if kast_available and (
                kills > 0 or pid in assisted or not death_ids or traded
            ):
                stats["fights_covered"] += 1
        if window["opening"] is not None:
            opener = window["opening"]["killer"]["player_id"]
            fallen = window["opening"]["victim"]["player_id"]
            if opener in per_player:
                per_player[opener]["openings_won"] += 1
            if fallen in per_player:
                per_player[fallen]["openings_lost"] += 1

    for stats in per_player.values():
        stats["kast_f"] = (
            round(stats["fights_covered"] / stats["fights"], 4)
            if kast_available and stats["fights"] else None
        )
        if not kast_available:
            stats["fights_covered"] = None

    envelope["windows"] = windows
    envelope["players"] = [per_player[pid] for pid in roster]
    envelope["summary"].update({
        "fight_windows": len(windows),
        "captures": captures,
        "stops": len(windows) - captures,
        "openings_observed": sum(
            1 for w in windows if w["opening"] is not None),
    })
    return envelope
