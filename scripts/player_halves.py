"""Per-half player box scores, checked against the match totals they split.

Rows come from sql/analytics/player_half_fact.sql: one per (player, closed
half), from the same event tables as the match-total box score. `team` is the
report's match team number (ktp_match_players.team, the side the player held
in the last half they played), not the side they played in that half; the
side per half is in_game_result.halves[].
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Iterable, Sequence

ADDITIVE = (
    "kills", "deaths", "assists", "headshots", "team_kills", "suicides",
    "damage_dealt", "damage_taken", "team_damage", "capture_credits",
    "cap_breaks", "shots", "hits",
)
DAMAGE = ("damage_dealt", "damage_taken", "team_damage")


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def unavailable() -> dict[str, Any]:
    return {"status": "unavailable", "reconciled": None,
            "mismatched_columns": [], "rows": []}


def build_player_halves(
    rows: Iterable[dict[str, Any]] | None,
    players: Sequence[dict[str, Any]],
    *,
    per_hit_damage: bool,
    temporal_valid: bool,
) -> dict[str, Any]:
    if rows is None:
        return unavailable()
    rows = list(rows)
    if not rows:
        return unavailable()
    # Legacy damage is not per hit, so it has no half to split by.
    checked = tuple(c for c in ADDITIVE if per_hit_damage or c not in DAMAGE)
    sums: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    out = []
    for r in rows:
        pid = _int(r.get("player_id"))
        # None is a producer that did not exist yet; keep it apart from 0.
        values: dict[str, int | None] = {
            c: None if r.get(c) is None else _int(r.get(c)) for c in ADDITIVE}
        for c in ADDITIVE:
            sums[pid][c] += values[c] or 0
        # A roster member with no samples and no events in a half did not play it.
        if not _int(r.get("position_samples")) and not any(values.values()):
            continue
        if not per_hit_damage:
            for c in DAMAGE:
                values[c] = None
        duration = _int(r.get("duration_seconds"))
        kills, deaths = values["kills"] or 0, values["deaths"] or 0
        dealt, taken = values["damage_dealt"], values["damage_taken"]
        per_minute = temporal_valid and duration > 0
        # score and the grenade columns are not reconciled against the match
        # total here: ktp_match_stats' half=0 row is the daemon's own
        # pre-summed total (see player_match_fact.sql), not derived by
        # summing these half rows the way the ADDITIVE columns are, so a
        # mismatch would not mean the same thing a kills/damage one does.
        score = _int(r.get("score"))
        out.append({
            "player_id": pid,
            "player_name_at_match": r.get("player_name_at_match"),
            "team": _int(r.get("team")),
            "half": _int(r.get("half")),
            "duration_seconds": duration,
            **values,
            "damage_differential": (dealt - taken
                                    if dealt is not None and taken is not None else None),
            "kd_ratio": round(kills / deaths, 3) if deaths else None,
            "headshot_rate": (round((values["headshots"] or 0) / kills, 3)
                              if kills else None),
            "raw_accuracy": (round((values["hits"] or 0) / values["shots"], 3)
                             if values["shots"] else None),
            "damage_per_minute": (round(dealt * 60.0 / duration, 2)
                                  if per_minute and dealt is not None else None),
            "kills_per_minute": (round(kills * 60.0 / duration, 3)
                                 if per_minute else None),
            "score": score,
            "points_per_minute": (round(score * 60.0 / duration, 3)
                                  if per_minute else None),
            "grenade_kills": _int(r.get("grenade_kills")),
            "grenade_damage": _int(r.get("grenade_damage")) if per_hit_damage else None,
            "grenade_damage_taken": (_int(r.get("grenade_damage_taken"))
                                     if per_hit_damage else None),
        })
    mismatched = sorted({
        c for p in players for c in checked
        if _int(p.get(c)) != sums[_int(p.get("player_id"))][c]
    })
    return {"status": "available", "reconciled": not mismatched,
            "mismatched_columns": mismatched, "rows": out}
