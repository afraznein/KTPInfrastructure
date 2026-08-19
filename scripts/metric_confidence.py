#!/usr/bin/env python3
"""Deterministic confidence labels for match-report facts and estimates."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REPO = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO / "config/analytics/metric_confidence.json"


def load_config(path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "minimum_player_minutes", "minimum_damage_per_life_deaths",
        "minimum_headshot_rate_kills", "minimum_accuracy_shots",
        "minimum_sequence_events", "emerging_baseline_matches",
        "reviewable_baseline_matches", "established_baseline_matches",
    }
    missing = required - set(config.get("thresholds", {}))
    if missing:
        raise ValueError(f"confidence config is missing thresholds: {sorted(missing)}")
    return config


def label(level: str, reason: str, *, source_complete: bool = True,
          publishable: bool = True) -> dict[str, Any]:
    return {
        "level": level,
        "source_complete": source_complete,
        "publishable": publishable,
        "reason": reason,
    }


def exact_fact(*, available: bool, synthetic: bool) -> dict[str, Any]:
    if not available:
        return label("unavailable", "The required source was not captured.",
                     source_complete=False, publishable=False)
    if synthetic:
        return label(
            "synthetic",
            "The count is observed exactly, but bot behavior has no competitive interpretation.",
        )
    return label("descriptive", "Observed match fact; no population estimate is implied.")


def player_rate(metric_id: str, player: dict[str, Any], *, synthetic: bool,
                config: dict[str, Any]) -> dict[str, Any]:
    value = player.get(metric_id)
    if value is None:
        return label("unavailable", "The metric denominator or source is unavailable.",
                     source_complete=False, publishable=False)
    if synthetic:
        return label(
            "synthetic",
            "The value validates calculation only; bot behavior is not a competitive sample.",
        )
    thresholds = config["thresholds"]
    duration_minutes = float(player.get("duration_seconds") or 0) / 60.0
    if metric_id == "damage_per_minute":
        enough = duration_minutes >= float(thresholds["minimum_player_minutes"])
        evidence = f"{duration_minutes:.1f} observed minutes"
    elif metric_id == "damage_per_life":
        deaths = int(player.get("deaths") or 0)
        enough = deaths >= int(thresholds["minimum_damage_per_life_deaths"])
        evidence = f"{deaths} completed lives"
    elif metric_id == "headshot_rate":
        kills = int(player.get("kills") or 0)
        enough = kills >= int(thresholds["minimum_headshot_rate_kills"])
        evidence = f"{kills} kills"
    elif metric_id == "raw_accuracy":
        shots = int(player.get("shots") or 0)
        enough = shots >= int(thresholds["minimum_accuracy_shots"])
        evidence = f"{shots} shots; descriptive only because weapon mechanics bias accuracy"
    else:
        raise ValueError(f"unknown player-rate metric: {metric_id}")
    return label(
        "descriptive" if enough else "low_sample",
        f"{evidence}; {'meets' if enough else 'does not meet'} the v1 display threshold.",
    )


def sequence_metric(event_count: int, match_count: int, *, synthetic: bool,
                    config: dict[str, Any]) -> dict[str, Any]:
    if synthetic:
        return label(
            "synthetic",
            f"Observed across {match_count} bot matches; useful for pipeline validation only.",
        )
    minimum = int(config["thresholds"]["minimum_sequence_events"])
    return label(
        "descriptive" if event_count >= minimum else "low_sample",
        f"{event_count} observed events across {match_count} matches; v1 minimum is {minimum}.",
    )


def baseline(match_count: int, *, synthetic: bool,
             config: dict[str, Any]) -> dict[str, Any]:
    if synthetic:
        return label(
            "synthetic",
            f"{match_count} bot matches validate aggregation but cannot define a competitive norm.",
        )
    thresholds = config["thresholds"]
    if match_count >= int(thresholds["established_baseline_matches"]):
        return label("established", f"{match_count} human matches.")
    if match_count >= int(thresholds["reviewable_baseline_matches"]):
        return label("reviewable", f"{match_count} human matches; suitable for reviewed calibration.")
    if match_count >= int(thresholds["emerging_baseline_matches"]):
        return label("emerging", f"{match_count} human matches; directional only.")
    return label("low_sample", f"Only {match_count} human matches; do not calibrate weights.")


def position_points(*, available: bool) -> dict[str, Any]:
    if not available:
        return label("unavailable", "No shareable accumulation result was provided.",
                     source_complete=False, publishable=False)
    return label(
        "shadow_only",
        "Experimental accumulation_v2_target10 output; not KTPR and not production-calibrated.",
    )
