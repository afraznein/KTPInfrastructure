"""KTPR v2 shadow blend (Tier 3, definition v1).

An HLTV-style composite: per-match z-scores of four components — attributed
flag swing, KAST-F, per-life output, and fast multikills — combined with
UNCALIBRATED weights. Shadow only: published beside nothing, ranked by
nothing, until the comparison review against the historical Excel KTPR
signs off (umbrella goal, Tier 3 gates).
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class KtprV2Config:
    swing_weight: float = 0.4
    kast_weight: float = 0.25
    output_weight: float = 0.25
    multikill_weight: float = 0.1

    def validate(self) -> None:
        weights = (self.swing_weight, self.kast_weight,
                   self.output_weight, self.multikill_weight)
        if any(w < 0 for w in weights) or not any(weights):
            raise ValueError("KTPR v2 weights must be >= 0 and not all zero")


def _z_scores(values: dict[int, float]) -> dict[int, float]:
    if not values:
        return {}
    mean = sum(values.values()) / len(values)
    variance = sum((v - mean) ** 2 for v in values.values()) / len(values)
    spread = variance ** 0.5
    if spread < 1e-9:
        return {pid: 0.0 for pid in values}
    return {pid: (v - mean) / spread for pid, v in values.items()}


def build_ktpr_v2_shadow(
    players: Sequence[dict[str, Any]] | None,
    flag_fight_players: Sequence[dict[str, Any]] | None,
    flag_swing_players: Sequence[dict[str, Any]] | None,
    config: KtprV2Config | None = None,
) -> dict[str, Any]:
    """Blend the merged per-player components into one shadow rating.

    A component whose source is missing for the match is dropped and its
    weight redistributed over the rest — a missing feed must not read as a
    zero performance. If every component is missing, the blend is
    unavailable.
    """
    config = config or KtprV2Config()
    config.validate()
    envelope: dict[str, Any] = {
        "definition": "ktpr_v2_blend_v1",
        "definition_version": 1,
        "parameters": {**asdict(config),
                       "normalization": "per_match_z_scores"},
        "status": "available",
        "calibration": "uncalibrated_baseline",
        "visibility": "private_shadow_only",
        "writes": False,
        "rating_effect": False,
        "caveats": [
            "Weights are uncalibrated priors; compare against historical "
            "KTPR before any adoption decision.",
        ],
        "players": [],
        "components_used": [],
    }
    if not players:
        envelope["status"] = "unavailable"
        return envelope

    ids = [int(p["player_id"]) for p in players]
    box = {int(p["player_id"]): p for p in players}

    components: dict[str, dict[int, float]] = {}
    output = {}
    for pid in ids:
        row = box[pid]
        per_life = row.get("damage_per_life")
        kd = row.get("kd_ratio")
        if per_life is not None or kd is not None:
            output[pid] = (float(per_life or 0.0) / 100.0) + float(kd or 0.0)
    if output:
        components["output"] = output
    multikills = {}
    for pid in ids:
        row = box[pid]
        if "fast_2k" in row:
            multikills[pid] = (float(row.get("fast_2k") or 0)
                               + 2.0 * float(row.get("fast_3k") or 0)
                               + 4.0 * float(row.get("fast_4k_plus") or 0))
    if multikills:
        components["multikill"] = multikills
    if flag_fight_players:
        kast = {int(p["player_id"]): float(p["kast_f"])
                for p in flag_fight_players
                if p.get("kast_f") is not None}
        if kast:
            components["kast_f"] = kast
    if flag_swing_players:
        swing = {int(p["player_id"]): float(p["attributed_swing"])
                 for p in flag_swing_players
                 if p.get("attributed_swing") is not None}
        if swing:
            components["swing"] = swing

    weight_of = {"swing": config.swing_weight, "kast_f": config.kast_weight,
                 "output": config.output_weight,
                 "multikill": config.multikill_weight}
    used = [name for name in weight_of if name in components]
    if not used:
        envelope["status"] = "unavailable"
        envelope["caveats"].append("No component source was available.")
        return envelope
    total_weight = sum(weight_of[name] for name in used)
    z = {name: _z_scores({pid: components[name].get(pid, 0.0)
                          for pid in ids})
         for name in used}
    envelope["components_used"] = sorted(used)
    envelope["players"] = [
        {
            "player_id": pid,
            "player_name_at_match": box[pid].get("player_name_at_match"),
            "team": box[pid].get("team"),
            "rating": round(sum(
                weight_of[name] * z[name][pid] for name in used
            ) / total_weight, 4),
            "components": {name: round(z[name][pid], 4) for name in used},
        }
        for pid in ids
    ]
    envelope["players"].sort(key=lambda p: -p["rating"])
    return envelope
