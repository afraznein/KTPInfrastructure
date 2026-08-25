#!/usr/bin/env python3
"""Pure private-shadow prototypes for FPS-inspired match statistics.

The helpers in this module deliberately accept already-selected row mappings.
They do no database or filesystem work, and they return aggregates only.  In
particular, the sampled-position helper never returns coordinates, timestamps,
per-flag histories, heatmap cells, or an ordered player path.

These are exploratory descriptions, not KTPR inputs.  Every returned report
states its source coverage, definition parameters, confidence, visibility, and
rating effect so a caller cannot silently promote a partial calculation.
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Iterable, Mapping


__all__ = [
    "EngagementDistanceConfig",
    "ObjectivePressureConfig",
    "build_objective_pressure_shadow",
    "build_weapon_engagement_shadow",
]


@dataclass(frozen=True)
class ObjectivePressureConfig:
    """Parameters for sampled, two-dimensional objective proximity."""

    sample_seconds: float = 5.0
    objective_radius_units: float = 512.0
    contest_radius_units: float = 768.0
    simultaneous_tolerance_seconds: float = 1.0
    minimum_distinct_snapshots: int = 3
    minimum_player_samples: int = 3
    maximum_sample_gap_seconds: float = 15.0
    minimum_expected_coverage_fraction: float = 0.5
    expected_live_seconds: float | None = None


@dataclass(frozen=True)
class EngagementDistanceConfig:
    """Parameters for three-dimensional kill-time separation profiles.

    Each distance-band upper bound is exclusive.  The final ``None`` band is
    unbounded, so a kill exactly 512 units away is in ``medium``, not ``close``.
    """

    distance_bands: tuple[tuple[str, float | None], ...] = (
        ("close", 512.0),
        ("medium", 1024.0),
        ("long", 2048.0),
        ("very_long", None),
    )
    maximum_distance_units: float = 20_000.0
    minimum_profile_kills: int = 10
    exclude_self_kills: bool = True
    exclude_same_team_kills: bool = True


def _finite_number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _integer(value: Any) -> int | None:
    number = _finite_number(value)
    if number is None or not number.is_integer():
        return None
    return int(number)


def _team(value: Any) -> int | None:
    if isinstance(value, str):
        named = {"allies": 1, "axis": 2}.get(value.strip().lower())
        if named is not None:
            return named
    candidate = _integer(value)
    return candidate if candidate in (1, 2) else None


def _first(row: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        if name in row:
            return row[name]
    return None


def _name(row: Mapping[str, Any], *names: str) -> str | None:
    value = _first(row, *names)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _fraction(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def _rounded(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 3) or 0.0


def _truth(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes"}:
            return True
        if normalized in {"0", "false", "no"}:
            return False
        return None
    number = _integer(value)
    if number in (0, 1):
        return bool(number)
    return None


def _validate_objective_config(config: ObjectivePressureConfig) -> None:
    for label, value in (
        ("sample_seconds", config.sample_seconds),
        ("objective_radius_units", config.objective_radius_units),
        ("contest_radius_units", config.contest_radius_units),
        ("simultaneous_tolerance_seconds", config.simultaneous_tolerance_seconds),
    ):
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"{label} must be a finite value greater than zero")
    if config.minimum_distinct_snapshots <= 1:
        raise ValueError("minimum_distinct_snapshots must be greater than one")
    if config.minimum_player_samples <= 1:
        raise ValueError("minimum_player_samples must be greater than one")
    if (
        not math.isfinite(config.maximum_sample_gap_seconds)
        or config.maximum_sample_gap_seconds < config.sample_seconds
    ):
        raise ValueError(
            "maximum_sample_gap_seconds must be finite and at least sample_seconds"
        )
    if (
        not math.isfinite(config.minimum_expected_coverage_fraction)
        or not 0 < config.minimum_expected_coverage_fraction <= 1
    ):
        raise ValueError(
            "minimum_expected_coverage_fraction must be in the interval (0, 1]"
        )
    if config.expected_live_seconds is not None and (
        not math.isfinite(config.expected_live_seconds)
        or config.expected_live_seconds <= 0
    ):
        raise ValueError("expected_live_seconds must be finite and greater than zero")


def _objective_state() -> dict[str, Any]:
    return {
        "sample_count": 0,
        "near_count": 0,
        "nearest_distances": [],
        "near_distances": [],
        "friendly_count": 0,
        "neutral_count": 0,
        "enemy_count": 0,
        "unknown_count": 0,
        "contested_count": 0,
        "teams": set(),
    }


def _objective_summary(state: Mapping[str, Any], sample_seconds: float) -> dict[str, Any]:
    sample_count = int(state["sample_count"])
    near_count = int(state["near_count"])
    nearest = state["nearest_distances"]
    near = state["near_distances"]
    resolved = (
        int(state["friendly_count"])
        + int(state["neutral_count"])
        + int(state["enemy_count"])
    )
    return {
        "eligible_samples": sample_count,
        "nominal_observed_seconds": _rounded(sample_count * sample_seconds),
        "near_objective_samples": near_count,
        "near_objective_seconds": _rounded(near_count * sample_seconds),
        "proximity_share": _fraction(near_count, sample_count),
        "mean_nearest_objective_distance_units": (
            _rounded(sum(nearest) / len(nearest)) if nearest else None
        ),
        "mean_distance_while_near_units": (
            _rounded(sum(near) / len(near)) if near else None
        ),
        "friendly_owned_proximity_seconds": _rounded(
            int(state["friendly_count"]) * sample_seconds
        ),
        "neutral_proximity_seconds": _rounded(
            int(state["neutral_count"]) * sample_seconds
        ),
        "enemy_owned_pressure_seconds": _rounded(
            int(state["enemy_count"]) * sample_seconds
        ),
        "unknown_ownership_proximity_seconds": _rounded(
            int(state["unknown_count"]) * sample_seconds
        ),
        "ownership_context_coverage": _fraction(resolved, near_count),
        "sampled_contest_seconds": _rounded(
            int(state["contested_count"]) * sample_seconds
        ),
    }


def _sample_temporal_coverage(
    samples: Iterable[Mapping[str, Any]],
    config: ObjectivePressureConfig,
) -> dict[str, Any]:
    """Summarize cadence coverage without returning any sample timestamp."""
    times_by_half: dict[int, set[float]] = defaultdict(set)
    for sample in samples:
        # Millisecond normalization avoids treating harmless SQL float
        # representation differences as separate broadcasts.
        times_by_half[int(sample["half"])].add(round(float(sample["game_time"]), 3))

    ordered_by_half = {
        half: sorted(times) for half, times in times_by_half.items()
    }
    gaps = [
        later - earlier
        for times in ordered_by_half.values()
        for earlier, later in zip(times, times[1:])
    ]
    distinct = sum(len(times) for times in ordered_by_half.values())
    nominal_seconds = distinct * config.sample_seconds
    observed_span = sum(
        (times[-1] - times[0]) + config.sample_seconds
        for times in ordered_by_half.values()
        if times
    )
    expected_fraction = (
        min(nominal_seconds / config.expected_live_seconds, 1.0)
        if config.expected_live_seconds is not None else None
    )
    maximum_gap = max(gaps) if gaps else None
    return {
        "halves_observed": len(ordered_by_half),
        "distinct_snapshot_count": distinct,
        "nominal_snapshot_seconds": _rounded(nominal_seconds),
        "observed_span_seconds": _rounded(observed_span),
        "maximum_observed_gap_seconds": _rounded(maximum_gap),
        "expected_live_seconds": config.expected_live_seconds,
        "expected_coverage_fraction": (
            round(expected_fraction, 4) if expected_fraction is not None else None
        ),
        "minimum_distinct_snapshots": config.minimum_distinct_snapshots,
        "maximum_allowed_gap_seconds": config.maximum_sample_gap_seconds,
        "minimum_expected_coverage_fraction": (
            config.minimum_expected_coverage_fraction
        ),
        "snapshot_minimum_met": distinct >= config.minimum_distinct_snapshots,
        "gap_requirement_met": (
            maximum_gap is not None
            and maximum_gap <= config.maximum_sample_gap_seconds
        ),
        "expected_coverage_requirement_met": (
            expected_fraction is None
            or expected_fraction >= config.minimum_expected_coverage_fraction
        ),
    }


def build_objective_pressure_shadow(
    position_rows: Iterable[Mapping[str, Any]],
    flag_rows: Iterable[Mapping[str, Any]],
    ownership_rows: Iterable[Mapping[str, Any]],
    config: ObjectivePressureConfig | None = None,
) -> dict[str, Any]:
    """Aggregate sampled objective proximity without returning a player path.

    Required position fields are ``player_id``, ``team``, ``half``, ``pos_x``,
    ``pos_y``, and ``game_time``.  Flag rows require ``flag_index``,
    ``origin_x``, and ``origin_y``.  Ownership rows use ``half``,
    ``flag_index``, ``owner_team``, ``game_time``, and preferably
    ``is_initial``.  Player name fields are optional.

    Proximity is two-dimensional because the captured flag origin has no Z
    coordinate.  Returned seconds are the nominal sample cadence multiplied by
    observed alive samples; they are not exact continuous objective time.
    """

    config = config or ObjectivePressureConfig()
    _validate_objective_config(config)
    positions = list(position_rows)
    flags_input = list(flag_rows)
    ownership_input = list(ownership_rows)

    flags: dict[int, tuple[float, float]] = {}
    invalid_flags = 0
    duplicate_flags = 0
    for row in flags_input:
        if not isinstance(row, Mapping):
            invalid_flags += 1
            continue
        index = _integer(row.get("flag_index"))
        x = _finite_number(row.get("origin_x"))
        y = _finite_number(row.get("origin_y"))
        if index is None or index < 0 or x is None or y is None:
            invalid_flags += 1
            continue
        if index in flags:
            duplicate_flags += 1
            continue
        flags[index] = (x, y)

    timelines: dict[tuple[int, int], list[tuple[float, int]]] = defaultdict(list)
    explicit_baselines: set[tuple[int, int]] = set()
    valid_ownership = 0
    irrelevant_ownership = 0
    invalid_ownership = 0
    for row in ownership_input:
        if not isinstance(row, Mapping):
            invalid_ownership += 1
            continue
        half = _integer(row.get("half"))
        index = _integer(row.get("flag_index"))
        owner = _integer(row.get("owner_team"))
        game_time = _finite_number(row.get("game_time"))
        if (
            half is None
            or half <= 0
            or index is None
            or index < 0
            or owner not in (0, 1, 2)
            or game_time is None
            or game_time < 0
        ):
            invalid_ownership += 1
            continue
        valid_ownership += 1
        if index not in flags:
            irrelevant_ownership += 1
            continue
        key = (half, index)
        timelines[key].append((game_time, owner))
        if _truth(row.get("is_initial")) is True and game_time == 0:
            explicit_baselines.add(key)
    for timeline in timelines.values():
        timeline.sort()

    classified: list[dict[str, Any]] = []
    valid_positions = 0
    invalid_positions = 0
    duplicate_position_samples = 0
    seen_position_samples: set[tuple[Any, int, float]] = set()
    sample_halves: set[int] = set()
    player_names: dict[Any, str] = {}
    for row in positions:
        if not isinstance(row, Mapping):
            invalid_positions += 1
            continue
        player_id = row.get("player_id")
        try:
            hash(player_id)
        except (TypeError, ValueError):
            player_id = None
        team = _team(row.get("team"))
        half = _integer(row.get("half"))
        x = _finite_number(row.get("pos_x"))
        y = _finite_number(row.get("pos_y"))
        game_time = _finite_number(row.get("game_time"))
        if (
            player_id is None
            or team is None
            or half is None
            or half <= 0
            or x is None
            or y is None
            or game_time is None
            or game_time < 0
        ):
            invalid_positions += 1
            continue
        valid_positions += 1
        sample_key = (player_id, half, round(game_time, 3))
        if sample_key in seen_position_samples:
            duplicate_position_samples += 1
            continue
        seen_position_samples.add(sample_key)
        sample_halves.add(half)
        observed_name = _name(
            row, "player_name_at_match", "player_name", "name"
        )
        if observed_name is not None:
            player_names.setdefault(player_id, observed_name)
        if not flags:
            continue
        nearest_index, (flag_x, flag_y) = min(
            flags.items(),
            key=lambda item: math.hypot(x - item[1][0], y - item[1][1]),
        )
        distance = math.hypot(x - flag_x, y - flag_y)
        classified.append({
            "player_id": player_id,
            "team": team,
            "half": half,
            "game_time": game_time,
            "x": x,
            "y": y,
            "flag_index": nearest_index,
            "distance": distance,
            "near": distance <= config.objective_radius_units,
            "contested": False,
        })

    # Position broadcasts normally give every alive player essentially the
    # same game_time.  The explicit tolerance avoids pretending rows several
    # seconds apart are simultaneous, while adjacent buckets avoid an edge at
    # an exact quantization boundary.
    contest_buckets: dict[tuple[int, int, int], list[dict[str, Any]]] = defaultdict(list)
    tolerance = config.simultaneous_tolerance_seconds
    for sample in classified:
        if not sample["near"]:
            continue
        bucket = math.floor(sample["game_time"] / tolerance)
        contest_buckets[(sample["half"], sample["flag_index"], bucket)].append(sample)
    for sample in classified:
        if not sample["near"]:
            continue
        bucket = math.floor(sample["game_time"] / tolerance)
        for candidate_bucket in (bucket - 1, bucket, bucket + 1):
            candidates = contest_buckets.get(
                (sample["half"], sample["flag_index"], candidate_bucket), []
            )
            if any(
                other["team"] != sample["team"]
                and abs(other["game_time"] - sample["game_time"]) <= tolerance
                and math.hypot(other["x"] - sample["x"], other["y"] - sample["y"])
                <= config.contest_radius_units
                for other in candidates
            ):
                sample["contested"] = True
                break

    def owner_at(half: int, flag_index: int, game_time: float) -> int | None:
        timeline = timelines.get((half, flag_index), [])
        if not timeline:
            return None
        offset = bisect_right(timeline, (game_time, 3)) - 1
        return timeline[offset][1] if offset >= 0 else None

    aggregate = _objective_state()
    by_player: dict[Any, dict[str, Any]] = defaultdict(_objective_state)
    for sample in classified:
        states = (aggregate, by_player[sample["player_id"]])
        for state in states:
            state["sample_count"] += 1
            state["nearest_distances"].append(sample["distance"])
            state["teams"].add(sample["team"])
        if not sample["near"]:
            continue
        owner = owner_at(sample["half"], sample["flag_index"], sample["game_time"])
        category = (
            "unknown_count" if owner is None
            else "neutral_count" if owner == 0
            else "friendly_count" if owner == sample["team"]
            else "enemy_count"
        )
        for state in states:
            state["near_count"] += 1
            state["near_distances"].append(sample["distance"])
            state[category] += 1
            if sample["contested"]:
                state["contested_count"] += 1

    players_output = []
    for player_id, state in sorted(by_player.items(), key=lambda item: str(item[0])):
        player_temporal = _sample_temporal_coverage(
            (
                sample for sample in classified
                if sample["player_id"] == player_id
            ),
            config,
        )
        player_temporal.update({
            "minimum_player_samples": config.minimum_player_samples,
            "player_sample_minimum_met": (
                int(state["sample_count"]) >= config.minimum_player_samples
            ),
        })
        players_output.append({
            "player_id": player_id,
            "player_name_at_match": player_names.get(player_id),
            "teams_observed": sorted(state["teams"]),
            "sample_coverage": player_temporal,
            **_objective_summary(state, config.sample_seconds),
        })

    expected_baseline_keys = {
        (half, flag_index) for half in sample_halves for flag_index in flags
    }
    observed_baselines = len(explicit_baselines.intersection(expected_baseline_keys))
    expected_baselines = len(expected_baseline_keys)
    baseline_coverage = _fraction(observed_baselines, expected_baselines)
    aggregate_summary = _objective_summary(aggregate, config.sample_seconds)
    ownership_resolution = aggregate_summary["ownership_context_coverage"]
    position_row_coverage = _fraction(valid_positions, len(positions))
    temporal_coverage = _sample_temporal_coverage(classified, config)
    player_sample_counts = Counter(
        sample["player_id"] for sample in classified
    )
    players_meeting_minimum = sum(
        count >= config.minimum_player_samples
        for count in player_sample_counts.values()
    )
    player_minimum_fraction = _fraction(
        players_meeting_minimum, len(player_sample_counts)
    )
    temporal_coverage.update({
        "minimum_player_samples": config.minimum_player_samples,
        "players_observed": len(player_sample_counts),
        "players_meeting_minimum_samples": players_meeting_minimum,
        "players_meeting_minimum_fraction": player_minimum_fraction,
    })

    if not classified:
        confidence_level = "unavailable"
        status = "unavailable"
    elif (
        position_row_coverage is not None
        and position_row_coverage >= 0.8
        and baseline_coverage == 1.0
        and ownership_resolution in (None, 1.0)
        and duplicate_flags == 0
        and duplicate_position_samples == 0
        and temporal_coverage["snapshot_minimum_met"]
        and temporal_coverage["gap_requirement_met"]
        and temporal_coverage["expected_coverage_requirement_met"]
        and player_minimum_fraction == 1.0
    ):
        confidence_level = "medium"
        status = "available"
    else:
        confidence_level = "low"
        status = "partial"

    caveats = [
        "Samples cover connected, alive players only; deaths and respawn gaps are not observed.",
        "Nominal seconds equal sample count times the configured cadence, not exact continuous objective time.",
        "Aggregate seconds are player-seconds; two players sampled for five seconds contribute ten aggregate player-seconds.",
        "Flag proximity is a two-dimensional radius around a point, not the map's capture volume, route distance, or line of sight.",
        "Sampled contest means opposing sampled players were simultaneously near the same flag and each other; it is not an engine contest event.",
        "Enemy-owned proximity is descriptive pressure, not proof that a capture or other outcome was caused.",
        "Player teams come from each sample; per-half roster history should still be normalized before public comparisons.",
        "No coordinates, timestamps, per-flag histories, heatmaps, or ordered player paths are returned.",
    ]
    if baseline_coverage != 1.0:
        caveats.append(
            "Ownership baselines are incomplete; unresolved near-objective samples remain unknown rather than being guessed."
        )
    if (
        invalid_positions or duplicate_position_samples or invalid_flags
        or invalid_ownership or duplicate_flags
    ):
        caveats.append(
            "Malformed or ambiguous source rows were excluded and are counted in source_coverage."
        )
    if not (
        temporal_coverage["snapshot_minimum_met"]
        and temporal_coverage["gap_requirement_met"]
        and temporal_coverage["expected_coverage_requirement_met"]
        and player_minimum_fraction == 1.0
    ):
        caveats.append(
            "Temporal sample coverage is below the configured minimum; aggregates remain exploratory and confidence is low."
        )

    return {
        "metric": "sampled_objective_pressure",
        "definition_version": 2,
        "status": status,
        "unit": "nominal_sampled_player_seconds",
        "parameters": {
            "sample_seconds": config.sample_seconds,
            "objective_radius_units": config.objective_radius_units,
            "distance_dimension": "2d_xy",
            "contest_radius_units": config.contest_radius_units,
            "simultaneous_tolerance_seconds": config.simultaneous_tolerance_seconds,
            "minimum_distinct_snapshots": config.minimum_distinct_snapshots,
            "minimum_player_samples": config.minimum_player_samples,
            "maximum_sample_gap_seconds": config.maximum_sample_gap_seconds,
            "minimum_expected_coverage_fraction": (
                config.minimum_expected_coverage_fraction
            ),
            "expected_live_seconds": config.expected_live_seconds,
        },
        "source_coverage": {
            "position_samples": {
                "present": bool(positions),
                "rows_received": len(positions),
                "valid_rows": valid_positions,
                "invalid_rows": invalid_positions,
                "unique_valid_samples": len(classified),
                "duplicate_player_snapshots": duplicate_position_samples,
                "valid_fraction": position_row_coverage,
                "temporal": temporal_coverage,
            },
            "flag_positions": {
                "present": bool(flags),
                "rows_received": len(flags_input),
                "valid_unique_flags": len(flags),
                "invalid_rows": invalid_flags,
                "duplicate_rows": duplicate_flags,
            },
            "flag_ownership": {
                "present": bool(ownership_input),
                "rows_received": len(ownership_input),
                "valid_rows": valid_ownership,
                "invalid_rows": invalid_ownership,
                "rows_for_unknown_flags": irrelevant_ownership,
                "expected_initial_baselines": expected_baselines,
                "observed_initial_baselines": observed_baselines,
                "initial_baseline_fraction": baseline_coverage,
                "near_sample_resolution_fraction": ownership_resolution,
            },
        },
        "confidence": {
            "level": confidence_level,
            "proximity": "medium" if classified else "unavailable",
            "ownership_context": (
                "medium"
                if baseline_coverage == 1.0 and ownership_resolution in (None, 1.0)
                else "low" if ownership_input else "unavailable"
            ),
            "sampled_contest": "low" if classified else "unavailable",
            "basis": "Exact persisted samples feed an approximate, alive-only spatial classification.",
        },
        "visibility": "private_shadow_only",
        "rating_effect": False,
        "raw_paths_returned": False,
        "raw_timelines_included": False,
        "summary": aggregate_summary,
        "players": players_output,
        "caveats": caveats,
    }


def _validate_engagement_config(config: EngagementDistanceConfig) -> None:
    if (
        not math.isfinite(config.maximum_distance_units)
        or config.maximum_distance_units <= 0
    ):
        raise ValueError("maximum_distance_units must be finite and greater than zero")
    if config.minimum_profile_kills <= 0:
        raise ValueError("minimum_profile_kills must be greater than zero")
    if not config.distance_bands:
        raise ValueError("distance_bands must not be empty")
    prior = 0.0
    labels: set[str] = set()
    for index, (label, upper) in enumerate(config.distance_bands):
        if not label or label in labels:
            raise ValueError("distance band labels must be non-empty and unique")
        labels.add(label)
        if upper is None:
            if index != len(config.distance_bands) - 1:
                raise ValueError("only the final distance band may be unbounded")
            continue
        if not math.isfinite(upper) or upper <= prior:
            raise ValueError("distance band upper bounds must be finite and increasing")
        prior = upper
    if config.distance_bands[-1][1] is not None:
        raise ValueError("the final distance band must be unbounded")


def _triplet(
    row: Mapping[str, Any], alternatives: tuple[tuple[str, str, str], ...]
) -> tuple[float, float, float] | None:
    for names in alternatives:
        if not all(name in row for name in names):
            continue
        values = tuple(_finite_number(row[name]) for name in names)
        if all(value is not None for value in values):
            return values  # type: ignore[return-value]
    return None


def _engagement_state() -> dict[str, Any]:
    return {
        "kills_observed": 0,
        "distances": [],
        "teams": set(),
        "headshot_context": 0,
        "headshot_kills": 0,
        "scope_context": 0,
        "scoped_kills": 0,
        "prone_context": 0,
        "prone_kills": 0,
        "marker_true": 0,
        "marker_false": 0,
        "marker_absent": 0,
        "eligible_marker_true": 0,
        "eligible_marker_absent": 0,
    }


def _percentile(sorted_values: list[float], percentile: float) -> float | None:
    if not sorted_values:
        return None
    position = (len(sorted_values) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    weight = position - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def _profile_confidence(
    state: Mapping[str, Any], config: EngagementDistanceConfig
) -> str:
    eligible = len(state["distances"])
    observed = int(state["kills_observed"])
    if eligible == 0:
        return "unavailable"
    coverage = eligible / observed if observed else 0.0
    marked = int(state["eligible_marker_true"])
    provenance = marked / eligible if eligible else 0.0
    if (
        eligible >= config.minimum_profile_kills
        and coverage >= 0.8
        and provenance >= 0.8
    ):
        # Medium is deliberately the ceiling: distances describe successful
        # kills, not every engagement opportunity or role effectiveness.
        return "medium"
    return "low"


def _render_engagement_profile(
    state: Mapping[str, Any], config: EngagementDistanceConfig
) -> dict[str, Any]:
    distances = sorted(state["distances"])
    observed = int(state["kills_observed"])
    eligible = len(distances)
    band_counts = {label: 0 for label, _ in config.distance_bands}
    for distance in distances:
        for label, upper in config.distance_bands:
            if upper is None or distance < upper:
                band_counts[label] += 1
                break
    bands = {
        label: {
            "kills": count,
            "share": _fraction(count, eligible),
        }
        for label, count in band_counts.items()
    }
    headshot_context = int(state["headshot_context"])
    scope_context = int(state["scope_context"])
    prone_context = int(state["prone_context"])
    return {
        "kills_observed": observed,
        "separation_eligible_kills": eligible,
        "separation_coverage_fraction": _fraction(eligible, observed),
        "mean_kill_time_separation_units": (
            _rounded(sum(distances) / eligible) if eligible else None
        ),
        "median_kill_time_separation_units": _rounded(_percentile(distances, 0.5)),
        "p25_kill_time_separation_units": _rounded(_percentile(distances, 0.25)),
        "p75_kill_time_separation_units": _rounded(_percentile(distances, 0.75)),
        "minimum_kill_time_separation_units": (
            _rounded(distances[0]) if distances else None
        ),
        "maximum_kill_time_separation_units": (
            _rounded(distances[-1]) if distances else None
        ),
        "separation_bands": bands,
        "headshot_context_kills": headshot_context,
        "headshot_kills": int(state["headshot_kills"]),
        "headshot_rate": _fraction(int(state["headshot_kills"]), headshot_context),
        "scope_context_kills": scope_context,
        "scoped_kills": int(state["scoped_kills"]),
        "scoped_kill_rate": _fraction(int(state["scoped_kills"]), scope_context),
        "prone_context_kills": prone_context,
        "prone_kills": int(state["prone_kills"]),
        "prone_kill_rate": _fraction(int(state["prone_kills"]), prone_context),
        "frag_context_marker": {
            "recorded": int(state["marker_true"]),
            "not_recorded": int(state["marker_false"]),
            "not_selected": int(state["marker_absent"]),
            "distance_eligible_recorded": int(state["eligible_marker_true"]),
            "distance_eligible_not_selected": int(state["eligible_marker_absent"]),
        },
        "profile_confidence": _profile_confidence(state, config),
    }


def build_weapon_engagement_shadow(
    frag_rows: Iterable[Mapping[str, Any]],
    config: EngagementDistanceConfig | None = None,
) -> dict[str, Any]:
    """Build aggregate weapon and player/weapon kill-time separation profiles.

    The canonical HLStatsX coordinate fields are ``pos_x/y/z`` for the killer
    and ``pos_victim_x/y/z`` for the victim.  Descriptive
    ``killer_pos_*``/``victim_pos_*`` aliases are also accepted.  A present,
    false ``frag_context_recorded`` marker disqualifies distance, preventing
    legacy default coordinates from looking like a real zero-distance kill.
    Rows without the marker may be explored if coordinates were explicitly
    selected, but their provenance and profile confidence remain lower.
    """

    config = config or EngagementDistanceConfig()
    _validate_engagement_config(config)
    rows = list(frag_rows)
    aggregate = _engagement_state()
    by_weapon: dict[str, dict[str, Any]] = defaultdict(_engagement_state)
    by_player_weapon: dict[tuple[Any, str], dict[str, Any]] = defaultdict(
        _engagement_state
    )
    player_names: dict[Any, str] = {}

    excluded_self = 0
    excluded_same_team = 0
    missing_weapon = 0
    invalid_rows = 0
    producer_context_invalid = 0
    coordinate_complete = 0
    coordinate_missing = 0
    context_marker_false = 0
    out_of_range = 0
    identified_kills = 0
    eligible_kills = 0
    marked_rows = 0
    unmarked_rows = 0

    killer_alternatives = (
        ("pos_x", "pos_y", "pos_z"),
        ("killer_pos_x", "killer_pos_y", "killer_pos_z"),
    )
    victim_alternatives = (
        ("pos_victim_x", "pos_victim_y", "pos_victim_z"),
        ("victim_pos_x", "victim_pos_y", "victim_pos_z"),
    )

    for row in rows:
        if not isinstance(row, Mapping):
            invalid_rows += 1
            continue
        # SQL-selected enriched rows expose these keys even when a buffered
        # legacy/mismatched marker only matched the stored receipt context.
        # In that case the query deliberately emits a NULL selected half so
        # coverage remains visible without admitting the row as target-match
        # kill evidence. Standalone callers without producer keys retain the
        # compatibility behavior exercised by the unit tests below.
        has_producer_contract = any(
            key in row for key in (
                "producer_match_id", "producer_half", "game_time", "event_epoch"
            )
        )
        if has_producer_contract:
            selected_half = _integer(row.get("half"))
            producer_half = _integer(row.get("producer_half"))
            game_time = _finite_number(row.get("game_time"))
            event_epoch = _integer(row.get("event_epoch"))
            if (
                _name(row, "producer_match_id") is None
                or selected_half is None
                or selected_half <= 0
                or producer_half != selected_half
                or game_time is None
                or game_time < 0
                or event_epoch is None
                or event_epoch <= 0
            ):
                invalid_rows += 1
                producer_context_invalid += 1
                continue
        killer_id = _first(row, "killer_id", "killerId", "player_id")
        victim_id = _first(row, "victim_id", "victimId")
        if (
            config.exclude_self_kills
            and killer_id is not None
            and victim_id is not None
            and str(killer_id) == str(victim_id)
        ):
            excluded_self += 1
            continue
        killer_team = _team(_first(row, "killer_team", "team"))
        victim_team = _team(row.get("victim_team"))
        if (
            config.exclude_same_team_kills
            and killer_team is not None
            and victim_team is not None
            and killer_team == victim_team
        ):
            excluded_same_team += 1
            continue
        weapon = _name(row, "weapon")
        if weapon is None:
            missing_weapon += 1
            continue

        try:
            hash(killer_id)
        except (TypeError, ValueError):
            killer_id = None
        states = [aggregate, by_weapon[weapon]]
        if killer_id is not None:
            identified_kills += 1
            states.append(by_player_weapon[(killer_id, weapon)])
            observed_name = _name(
                row, "killer_name", "player_name_at_match", "player_name"
            )
            if observed_name is not None:
                player_names.setdefault(killer_id, observed_name)

        marker_present = "frag_context_recorded" in row
        marker = _truth(row.get("frag_context_recorded")) if marker_present else None
        for state in states:
            state["kills_observed"] += 1
            if killer_team is not None:
                state["teams"].add(killer_team)
            if "headshot" in row and _truth(row.get("headshot")) is not None:
                state["headshot_context"] += 1
                if _truth(row.get("headshot")):
                    state["headshot_kills"] += 1
            scope_value = _first(row, "k_scope", "killer_scoped")
            scope_present = "k_scope" in row or "killer_scoped" in row
            if scope_present and _truth(scope_value) is not None:
                state["scope_context"] += 1
                if _truth(scope_value):
                    state["scoped_kills"] += 1
            prone_value = _first(row, "k_prone", "killer_prone")
            prone_present = "k_prone" in row or "killer_prone" in row
            prone = _integer(prone_value) if prone_present else None
            if prone is not None and prone >= 0:
                state["prone_context"] += 1
                if prone > 0:
                    state["prone_kills"] += 1
            if marker_present and marker is True:
                state["marker_true"] += 1
            elif marker_present:
                state["marker_false"] += 1
            else:
                state["marker_absent"] += 1

        if marker_present:
            marked_rows += 1
        else:
            unmarked_rows += 1
        if marker_present and marker is not True:
            context_marker_false += 1
            continue

        killer_position = _triplet(row, killer_alternatives)
        victim_position = _triplet(row, victim_alternatives)
        if killer_position is None or victim_position is None:
            coordinate_missing += 1
            continue
        coordinate_complete += 1
        distance = math.dist(killer_position, victim_position)
        if distance > config.maximum_distance_units:
            out_of_range += 1
            continue
        eligible_kills += 1
        for state in states:
            state["distances"].append(distance)
            if marker_present:
                state["eligible_marker_true"] += 1
            else:
                state["eligible_marker_absent"] += 1

    weapon_profiles = [
        {
            "weapon": weapon,
            "teams_observed": sorted(state["teams"]),
            **_render_engagement_profile(state, config),
        }
        for weapon, state in sorted(by_weapon.items())
    ]
    player_weapon_profiles = [
        {
            "player_id": player_id,
            "player_name_at_match": player_names.get(player_id),
            "teams_observed": sorted(state["teams"]),
            "weapon": weapon,
            **_render_engagement_profile(state, config),
        }
        for (player_id, weapon), state in sorted(
            by_player_weapon.items(), key=lambda item: (str(item[0][0]), item[0][1])
        )
    ]
    aggregate_profile = _render_engagement_profile(aggregate, config)
    observed = int(aggregate["kills_observed"])
    if eligible_kills == 0:
        status = "unavailable"
    elif (
        eligible_kills == observed
        and context_marker_false == 0
        and unmarked_rows == 0
        and invalid_rows == 0
    ):
        status = "available"
    else:
        status = "partial"

    caveats = [
        "Separation describes killer-to-victim endpoints when the kill was recorded; it does not include misses, nonlethal damage, sight opportunities, or failed engagements.",
        "For delayed grenades or projectiles, kill-time separation is not firing-origin distance, projectile travel distance, or engagement range.",
        "Straight-line three-dimensional map units are not route distance, meters, or proof of line of sight.",
        "Weapon profiles should be compared within map, side, role, and sample-size context rather than treated as an effectiveness leaderboard.",
        "Per-hit damage has no coordinates, so damage cannot be assigned to these distance bands.",
        "Scope and prone fields describe state at the kill; clip/ammo can describe the currently held weapon rather than the projectile that caused a delayed kill.",
        "Low-volume profiles are retained with low confidence instead of being hidden or promoted into a rating.",
        "No kill coordinates, victim locations, timestamps, or ordered paths are returned.",
    ]
    if unmarked_rows:
        caveats.append(
            "Some coordinate rows lacked frag_context_recorded provenance; they are accepted for exploration but lower confidence."
        )
    if context_marker_false:
        caveats.append(
            "Rows explicitly lacking recorded frag context were excluded so legacy default coordinates are not treated as evidence."
        )
    if producer_context_invalid:
        caveats.append(
            "Rows with legacy or mismatched producer match/half/clock context were excluded and lower aggregate confidence."
        )

    lower = 0.0
    bands_parameter = []
    for label, upper in config.distance_bands:
        bands_parameter.append({
            "label": label,
            "lower_inclusive_units": lower,
            "upper_exclusive_units": upper,
        })
        if upper is not None:
            lower = upper

    return {
        "metric": "weapon_kill_time_player_separation",
        "definition_version": 2,
        "status": status,
        "unit": "goldsrc_map_units",
        "parameters": {
            "measurement": "killer_victim_separation_at_kill_event",
            "distance_dimension": "3d_euclidean_kill_endpoints",
            "separation_bands": bands_parameter,
            "maximum_distance_units": config.maximum_distance_units,
            "minimum_profile_kills": config.minimum_profile_kills,
            "exclude_self_kills": config.exclude_self_kills,
            "exclude_same_team_kills": config.exclude_same_team_kills,
        },
        "source_coverage": {
            "frags": {
                "present": bool(rows),
                "rows_received": len(rows),
                "invalid_rows": invalid_rows,
                "producer_context_invalid_rows": producer_context_invalid,
                "qualified_weapon_kills": observed,
                "missing_weapon_rows": missing_weapon,
                "excluded_self_kills": excluded_self,
                "excluded_same_team_kills": excluded_same_team,
            },
            "frag_context": {
                "rows_with_marker": marked_rows,
                "rows_without_marker": unmarked_rows,
                "marker_false_rows": context_marker_false,
                "coordinate_complete_rows": coordinate_complete,
                "coordinate_missing_rows": coordinate_missing,
                "distance_out_of_range_rows": out_of_range,
                "separation_eligible_kills": eligible_kills,
                "separation_coverage_fraction": _fraction(eligible_kills, observed),
            },
            "player_identity": {
                "identified_kills": identified_kills,
                "identified_fraction": _fraction(identified_kills, observed),
            },
        },
        "confidence": {
            "level": (
                "low" if producer_context_invalid
                else aggregate_profile["profile_confidence"]
            ),
            "measurement_ceiling": "medium",
            "basis": "Persisted kill endpoints measure player separation at the kill event, but successful kills are a selected subset of engagement opportunities.",
        },
        "visibility": "private_shadow_only",
        "rating_effect": False,
        "raw_paths_returned": False,
        "raw_timelines_included": False,
        "summary": aggregate_profile,
        "weapon_profiles": weapon_profiles,
        "player_weapon_profiles": player_weapon_profiles,
        "caveats": caveats,
    }
