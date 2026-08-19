#!/usr/bin/env python3
"""Pure, private shadow analytics derived from persisted match events.

These metrics are exploratory. They do not write to a database, public API,
player rating, or site. Window values are emitted with every result so a later
review can reproduce the exact interpretation.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class TimelineConfig:
    multikill_seconds: float = 10.0
    trade_seconds: float = 5.0
    objective_conversion_seconds: float = 30.0

    def validate(self) -> None:
        for name, value in asdict(self).items():
            if value <= 0:
                raise ValueError(f"{name} must be greater than zero")


def _event_key(row: dict[str, Any]) -> tuple[int, float, int]:
    return (int(row.get("half") or 0), float(row["event_unix"]),
            int(row.get("event_id") or 0))


def _identity(row: dict[str, Any], prefix: str) -> dict[str, Any]:
    return {
        "player_id": row.get(f"{prefix}_id"),
        "steam_id": row.get(f"{prefix}_steam_id"),
        "name": row.get(f"{prefix}_name"),
        "team": row.get(f"{prefix}_team"),
    }


def _multikills(
    frags: list[dict[str, Any]], config: TimelineConfig
) -> list[dict[str, Any]]:
    by_player_half: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
    for frag in frags:
        by_player_half[(int(frag["half"]), int(frag["killer_id"]))].append(frag)

    result: list[dict[str, Any]] = []
    for (_half, _killer), kills in sorted(by_player_half.items()):
        kills.sort(key=_event_key)
        cluster: list[dict[str, Any]] = []
        for kill in kills:
            if cluster and float(kill["event_unix"]) - float(cluster[0]["event_unix"]) > config.multikill_seconds:
                if len(cluster) >= 2:
                    result.append(_multikill_row(cluster))
                cluster = []
            cluster.append(kill)
        if len(cluster) >= 2:
            result.append(_multikill_row(cluster))
    return sorted(result, key=lambda row: (row["half"], row["started_unix"], row["killer"]["player_id"]))


def _multikill_row(kills: list[dict[str, Any]]) -> dict[str, Any]:
    first, last = kills[0], kills[-1]
    count = len(kills)
    return {
        "classification": f"fast_{count}k",
        "half": int(first["half"]),
        "killer": _identity(first, "killer"),
        "kill_count": count,
        "started_at": first.get("event_time"),
        "ended_at": last.get("event_time"),
        "started_unix": float(first["event_unix"]),
        "ended_unix": float(last["event_unix"]),
        "elapsed_seconds": round(float(last["event_unix"]) - float(first["event_unix"]), 3),
        "victims": [_identity(row, "victim") for row in kills],
        "event_ids": [int(row.get("event_id") or 0) for row in kills],
    }


def _attach_objective_conversion(
    multikills: list[dict[str, Any]], objectives: list[dict[str, Any]],
    config: TimelineConfig,
) -> None:
    objectives = sorted(objectives, key=_event_key)
    for sequence in multikills:
        conversion = None
        killer_team = sequence["killer"].get("team")
        for event in objectives:
            delta = float(event["event_unix"]) - sequence["ended_unix"]
            if int(event["half"]) != sequence["half"] or delta < 0:
                continue
            if delta > config.objective_conversion_seconds:
                break
            if killer_team is not None and int(event.get("team") or 0) == int(killer_team):
                conversion = {
                    "converted": True,
                    "seconds_after": round(delta, 3),
                    "event_time": event.get("event_time"),
                    "team": event.get("team"),
                    "team_name": event.get("team_name"),
                    "flag_name": event.get("flag_name"),
                }
                break
        sequence["objective_conversion"] = conversion or {"converted": False}


def _trades(frags: list[dict[str, Any]], config: TimelineConfig) -> list[dict[str, Any]]:
    ordered = sorted(frags, key=_event_key)
    used_trade_events: set[int] = set()
    result: list[dict[str, Any]] = []
    for index, death in enumerate(ordered):
        victim_team = death.get("victim_team")
        if victim_team is None:
            continue
        for reply in ordered[index + 1:]:
            if int(reply["half"]) != int(death["half"]):
                if int(reply["half"]) > int(death["half"]):
                    break
                continue
            delta = float(reply["event_unix"]) - float(death["event_unix"])
            if delta > config.trade_seconds:
                break
            reply_id = int(reply.get("event_id") or 0)
            if reply_id in used_trade_events:
                continue
            if (int(reply["victim_id"]) == int(death["killer_id"])
                    and reply.get("killer_team") is not None
                    and int(reply["killer_team"]) == int(victim_team)):
                used_trade_events.add(reply_id)
                result.append({
                    "half": int(death["half"]),
                    "death_event_id": int(death.get("event_id") or 0),
                    "trade_event_id": reply_id,
                    "seconds_after": round(delta, 3),
                    "fallen_player": _identity(death, "victim"),
                    "original_killer": _identity(death, "killer"),
                    "trader": _identity(reply, "killer"),
                    "event_time": reply.get("event_time"),
                })
                break
    return result


def _opening_duels(frags: list[dict[str, Any]]) -> list[dict[str, Any]]:
    first_by_half: dict[int, dict[str, Any]] = {}
    for frag in sorted(frags, key=_event_key):
        first_by_half.setdefault(int(frag["half"]), frag)
    return [{
        "half": half,
        "event_id": int(row.get("event_id") or 0),
        "event_time": row.get("event_time"),
        "winner": _identity(row, "killer"),
        "loser": _identity(row, "victim"),
        "weapon": row.get("weapon"),
        "headshot": bool(row.get("headshot")),
    } for half, row in sorted(first_by_half.items())]


def _head_to_head(frags: list[dict[str, Any]]) -> list[dict[str, Any]]:
    names: dict[int, dict[str, Any]] = {}
    pairs: dict[tuple[int, int], dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for frag in frags:
        killer, victim = int(frag["killer_id"]), int(frag["victim_id"])
        names[killer] = _identity(frag, "killer")
        names[victim] = _identity(frag, "victim")
        pairs[tuple(sorted((killer, victim)))][killer] += 1
    rows = []
    for (a, b), kills in sorted(pairs.items()):
        rows.append({
            "player_a": names[a], "player_b": names[b],
            "a_kills": kills[a], "b_kills": kills[b],
            "a_differential": kills[a] - kills[b],
        })
    return rows


def build_shadow_timelines(
    frags: list[dict[str, Any]], objectives: list[dict[str, Any]],
    config: TimelineConfig | None = None, *, temporal_valid: bool = True,
) -> dict[str, Any]:
    config = config or TimelineConfig()
    config.validate()
    ordered = sorted(frags, key=_event_key)
    multikills = _multikills(ordered, config) if temporal_valid else []
    if temporal_valid:
        _attach_objective_conversion(multikills, objectives, config)
    return {
        "status": "available" if temporal_valid else "timed_metrics_suppressed",
        "privacy": "private_shadow_only",
        "writes": False,
        "rating_impact": False,
        "config": asdict(config),
        "limitations": [
            "Trades use roster team and time only; distance and opportunity are not inferred.",
            "Objective conversion means the next same-team flag capture, not a score or capout.",
        ],
        "fast_multikills": multikills,
        "trades": _trades(ordered, config) if temporal_valid else [],
        "opening_duels": _opening_duels(ordered),
        "head_to_head": _head_to_head(ordered),
    }
