"""Plays: each player's biggest moments, the match's top three, and the dunce.

A report stage over ``shadow_explorations.flag_swing.timeline`` (every priced
kill, death and cap, with the cappers credited) joined to
``shadow_explorations.excursions`` (solo runs behind the enemy's lines, from
positions). highlight_windows answers "what were the big moments of the
match"; this answers "what did each player do that mattered, and what was
the single worst decision".

A play is one player's events within MERGE_GAP of each other, signed from
that player's side: kills and credited caps count for them, their own deaths
against them. An excursion becomes a play too -- merged with whatever events
fall inside it, and charged an exposure cost for the time the team spent a
man down (the static ledger approximation: absence_rate per minute, the one-
man-down delta of flag_swing's own baseline). That is what lets a wasted deep
run with no events be the dunce: a plain death in a fight costs one delta, a
lost minute plus that death costs more.

Values are flag_swing_v1 deltas: uncalibrated, comparative. The deposit/payout
ledger (scripts/mmr/momentum.py) and the counterfactual denial term are the
intended upgrade; the shape here does not change when they land, only the
numbers. Private block; the public DTO re-keys to names.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

from scripts.flag_swing import sides_by_half

DEFINITION = "plays_v1"
DEFINITION_VERSION = 1


@dataclass(frozen=True)
class PlaysConfig:
    merge_gap: float = 12.0          # seconds between a player's events that still share a play
    excursion_slack: float = 6.0     # events this close to an excursion's edges belong to it
    absence_rate: float = 0.04       # exposure per minute alone behind the lines (sigmoid(-1/6) - 0.5)
    per_player: int = 3
    match_top: int = 3
    dunce_floor: float = -0.05       # a non-excursion play must cost at least this to be the dunce
    sneak_seconds: float = 20.0      # excursion length that makes a cap a "sneak" rather than a run-through
    attempt_distance: float = 600.0  # closest approach that makes a capless excursion an attempt
    ahead_units: float = 1200.0      # teammate gap at a rear touch that means the capper was out in front
    brink_tolerance: float = 3.0     # a cap this close to a brink is the cap that reached it

    def validate(self) -> None:
        if self.merge_gap <= 0 or self.per_player < 1 or self.match_top < 1:
            raise ValueError("merge_gap must be positive and per_player/match_top >= 1")


def _f(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _i(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _contributions(timeline: Sequence[dict[str, Any]], side_of, roster_ids: set[int]) -> dict[tuple[int, int], list[dict]]:
    """(half, player) -> that player's signed events, in time order."""
    out: dict[tuple[int, int], list[dict]] = {}

    def add(half: int, pid: int, t: float, kind: str, value: float, **extra: Any) -> None:
        out.setdefault((half, pid), []).append({"t": t, "kind": kind, "value": value, **extra})

    for e in timeline:
        half, t, delta = _i(e.get("half")), _f(e.get("game_time")), _f(e.get("delta"))
        if half is None or t is None or delta is None:
            continue
        if e.get("kind") == "frag":
            killer, victim = _i(e.get("killer_id")), _i(e.get("victim_id"))
            if killer in roster_ids:
                sign = 1.0 if side_of(half, killer) == 1 else -1.0
                add(half, killer, t, "kill", delta * sign, victim=victim)
            if victim in roster_ids:
                sign = 1.0 if side_of(half, victim) == 1 else -1.0
                add(half, victim, t, "death", delta * sign, killer=killer)
        elif e.get("kind") == "flag":
            credited = [pid for pid in (e.get("credited") or []) if pid in roster_ids]
            if not credited:
                continue
            # A round-ending cap realises the round instead of shifting it,
            # so it is worth what was still outstanding (flag_swing's
            # terminal_value), not the flag-control move. Split across the
            # cappers: three players on the flag share what one player
            # closing it alone keeps.
            terminal = _f(e.get("terminal_value")) if e.get("capout_completed") else None
            share = (terminal if terminal is not None else delta) / len(credited)
            for pid in credited:
                sign = 1.0 if side_of(half, pid) == 1 else -1.0
                add(half, pid, t, "cap",
                    share if terminal is not None else share * sign,
                    flag_index=_i(e.get("flag_index")),
                    capout_denied=bool(e.get("capout_denied")),
                    capout_completed=bool(e.get("capout_completed")))
    for seq in out.values():
        seq.sort(key=lambda c: c["t"])
    return out


def _cluster(events: Sequence[dict], gap: float) -> list[list[dict]]:
    groups: list[list[dict]] = []
    for e in events:
        if groups and e["t"] - groups[-1][-1]["t"] <= gap:
            groups[-1].append(e)
        else:
            groups.append([e])
    return groups


def _tags(kills: int, deaths: int, caps: int, denials: int, exc: dict | None,
          cfg: PlaysConfig, completions: int = 0, touch: dict | None = None) -> list[str]:
    tags: list[str] = []
    if completions:
        tags.append("cap-out")
    if denials:
        tags.append("cap-out denial")
    if exc and caps:
        tags.append("sneak cap" if exc["duration"] >= cfg.sneak_seconds else "solo cap")
    elif caps and touch and (touch.get("teammate_gap") or 0) > cfg.ahead_units:
        # No window formed -- he went in with the team and finished ahead of
        # it. Same result as a ninja, different shape (see excursions.py).
        tags.append("fast push")
    elif caps:
        tags.append("cap")
    if kills >= 3:
        tags.append(f"{kills}k")
    if exc and not caps:
        if kills >= 2:
            tags.append("collapse")
        elif exc.get("closest_flag_distance") is not None and exc["closest_flag_distance"] <= cfg.attempt_distance:
            tags.append("attempt")
        elif not kills:
            tags.append("loiter")
    if deaths and not kills and not caps:
        tags.append("died for nothing" if exc else "death")
    return tags


def _summary(name: str, kills: int, deaths: int, caps: int, denials: int, exc: dict | None, tags: list[str]) -> str:
    parts: list[str] = []
    if exc:
        parts.append(f"{exc['duration']:.0f} s alone behind the lines")
    elif "fast push" in tags:
        parts.append("pushed past the team to the flag")
    if caps:
        note = (" (capped out)" if "cap-out" in tags else
                " (cap-out denied)" if denials else "")
        parts.append(f"{caps} cap{'s' if caps > 1 else ''}" + note)
    if kills:
        parts.append(f"{kills} kill{'s' if kills > 1 else ''}")
    if deaths:
        parts.append("died")
    body = ", ".join(parts) or "no events"
    return f"{name}: {body}"


def build_plays(
    timeline: Sequence[dict[str, Any]] | None,
    roster: Sequence[dict[str, Any]] | None,
    life_boundaries: Sequence[dict[str, Any]] | None,
    excursions: Sequence[dict[str, Any]] | None = None,
    config: PlaysConfig | None = None,
    touches: Sequence[dict[str, Any]] | None = None,
    brinks: Sequence[dict[str, Any]] | None = None,
    *,
    source_status: str | None = "available",
) -> dict[str, Any]:
    cfg = config or PlaysConfig()
    cfg.validate()
    # A cap that leaves the enemy one flag from losing the round is not an
    # ordinary cap: measured over 963 of them, the side converts a cap-out
    # within 90 s 26.1% of the time against 13.4% for the same sides taking
    # one flag fewer. The swing model cannot see that -- its curve flattens
    # exactly there -- so the play is TAGGED and left at its measured value.
    # Pricing the threat belongs to infra-mmr-ratings, which has the ledger;
    # inventing a number here would put an unfitted figure in a public block.
    brink_times: dict[tuple[int, int], list[float]] = {}
    for row in brinks or []:
        at = _f(row.get("game_time"))
        half_of = _i(row.get("half"))
        if at is None or half_of is None:
            continue
        for pid_ in row.get("credited") or []:
            key = (half_of, _i(pid_))
            if key[1] is not None:
                brink_times.setdefault(key, []).append(at)
    envelope: dict[str, Any] = {
        "definition": DEFINITION,
        "definition_version": DEFINITION_VERSION,
        "parameters": {**asdict(cfg), "valuer": "flag_swing_v1", "clock": "producer_game_time"},
        "status": "available",
        "visibility": "private_shadow_only",
        "writes": False,
        "rating_effect": False,
        "caveats": [
            "Values are flag_swing_v1 deltas plus a flat exposure cost for time alone behind "
            "the lines: uncalibrated, comparative. The momentum ledger and counterfactual "
            "denial pricing replace the numbers, not the shape.",
            "A `cap-out` play is worth flag_swing's `terminal_value` (the probability "
            "still outstanding when it was taken), split across the credited cappers, "
            "not the flag-control delta. It is NOT yet redistributed to the teammates "
            "who set the round up -- a player who cleared the way and died just before "
            "the touch currently gets nothing from it. That split is the momentum "
            "ledger's fitted job (scripts/mmr/momentum.py); this block feeds it.",
        ],
        "match_top": [],
        "per_player": [],
        "dunce": None,
        "plays_total": 0,
    }
    if source_status != "available" or not timeline:
        envelope["status"] = "unavailable"
        envelope["caveats"].append("flag_swing timeline unavailable; nothing to value.")
        return envelope

    names = {int(p["player_id"]): str(p.get("player_name_at_match") or f"player {p['player_id']}")
             for p in roster or [] if p.get("player_id") is not None}
    teams = {int(p["player_id"]): _i(p.get("team")) for p in roster or [] if p.get("player_id") is not None}
    sides = sides_by_half(life_boundaries)

    def side_of(half: int, pid: int) -> int | None:
        return sides.get(half, {}).get(pid, teams.get(pid))

    contributions = _contributions(timeline, side_of, set(names))
    touch_by_key: dict[tuple[int, int], list[dict]] = {}
    for row in touches or []:
        half, pid = _i(row.get("half")), _i(row.get("player_id"))
        if half is not None and pid in names:
            touch_by_key.setdefault((half, pid), []).append(row)

    exc_by_key: dict[tuple[int, int], list[dict]] = {}
    for row in excursions or []:
        half, pid = _i(row.get("half")), _i(row.get("player_id"))
        if half is not None and pid in names and _f(row.get("start")) is not None:
            exc_by_key.setdefault((half, pid), []).append(row)

    plays: list[dict[str, Any]] = []
    for pid in names:
        for half in sorted({h for h, p in contributions if p == pid} | {h for h, p in exc_by_key if p == pid}):
            groups = _cluster(contributions.get((half, pid), []), cfg.merge_gap)
            used = [False] * len(groups)
            items: list[tuple[dict | None, list[dict]]] = []
            for exc in sorted(exc_by_key.get((half, pid), []), key=lambda r: _f(r["start"]) or 0):
                lo, hi = (_f(exc["start"]) or 0) - cfg.excursion_slack, (_f(exc["end"]) or 0) + cfg.excursion_slack
                merged: list[dict] = []
                for gi, g in enumerate(groups):
                    if not used[gi] and g[0]["t"] <= hi and g[-1]["t"] >= lo:
                        merged.extend(g)
                        used[gi] = True
                items.append((exc, sorted(merged, key=lambda c: c["t"])))
            items.extend((None, g) for gi, g in enumerate(groups) if not used[gi])

            for exc, events in items:
                kills = sum(1 for e in events if e["kind"] == "kill")
                deaths = sum(1 for e in events if e["kind"] == "death")
                caps = sum(1 for e in events if e["kind"] == "cap")
                denials = sum(1 for e in events if e["kind"] == "cap" and e.get("capout_denied"))
                completions = sum(1 for e in events if e["kind"] == "cap" and e.get("capout_completed"))
                event_value = sum(e["value"] for e in events)
                exposure = 0.0
                exc_info = None
                if exc:
                    duration = _f(exc.get("duration")) or 0.0
                    exposure = -cfg.absence_rate * duration / 60.0
                    exc_info = {
                        "duration": round(duration, 1),
                        "min_teammate_distance": exc.get("min_teammate_distance"),
                        "closest_flag": exc.get("closest_flag"),
                        "closest_flag_distance": exc.get("closest_flag_distance"),
                    }
                times = [e["t"] for e in events] + ([_f(exc["start"]), _f(exc["end"])] if exc else [])
                start, end = min(times), max(times)
                peak = max(events, key=lambda e: abs(e["value"]))["t"] if events else start
                cap_times = [e["t"] for e in events if e["kind"] == "cap"]
                touch = next((t for t in touch_by_key.get((half, pid), [])
                              if any(abs((_f(t.get("game_time")) or 0) - ct) <= 3 for ct in cap_times)), None)
                tags = _tags(kills, deaths, caps, denials, exc_info, cfg, completions, touch)
                reached_brink = any(
                    abs(bt - ct) <= cfg.brink_tolerance
                    for bt in brink_times.get((half, pid), ())
                    for ct in cap_times)
                if reached_brink and "cap-out" not in tags:
                    # Not on a completed cap-out: there the round is over and
                    # the threat is moot. This marks the ones that did not land.
                    tags = tags + ["brink"]
                plays.append({
                    "half": half, "player_id": pid, "player_name_at_match": names[pid],
                    "team": teams.get(pid), "side": side_of(half, pid),
                    "start": round(start, 2), "end": round(end, 2),
                    "duration": round(end - start, 2), "peak_at": round(peak, 2),
                    "value": round(event_value + exposure, 4),
                    "event_value": round(event_value, 4),
                    "exposure": round(exposure, 4),
                    "kills": kills, "deaths": deaths, "caps": caps, "capout_denials": denials,
                    "capout_completions": completions,
                    "teammate_gap_at_touch": (touch or {}).get("teammate_gap"),
                    "excursion": exc_info,
                    "tags": tags,
                    "summary": _summary(names[pid], kills, deaths, caps, denials, exc_info, tags)
                                + (" — put them one flag from a cap-out" if "brink" in tags else ""),
                })

    plays.sort(key=lambda p: (-p["value"], p["half"], p["start"]))
    envelope["plays_total"] = len(plays)
    positive = [p for p in plays if p["value"] > 0]
    envelope["match_top"] = [dict(p, rank=i + 1) for i, p in enumerate(positive[: cfg.match_top])]
    per_player = []
    for pid in sorted(names):
        mine = [p for p in plays if p["player_id"] == pid and p["value"] > 0][: cfg.per_player]
        per_player.append({
            "player_id": pid, "player_name_at_match": names[pid], "team": teams.get(pid),
            "plays": [dict(p, rank=i + 1) for i, p in enumerate(mine)],
        })
    envelope["per_player"] = per_player

    # The dunce is a decision, not a death: the worst excursion that took a
    # flag off nobody. A plain death only qualifies as a fallback when it
    # cost more than the floor (last man down with the round on the line).
    wasted = [p for p in plays if p["excursion"] and not p["caps"] and p["value"] < 0]
    if wasted:
        envelope["dunce"] = dict(min(wasted, key=lambda p: (p["value"], p["half"], p["start"])))
    else:
        costly = [p for p in plays if p["value"] <= cfg.dunce_floor]
        if costly:
            envelope["dunce"] = dict(min(costly, key=lambda p: (p["value"], p["half"], p["start"])))
    return envelope
