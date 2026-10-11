"""KTPR v2 shadow blend (Tier 3, definition v1).

An HLTV-style composite: per-match z-scores of four components — attributed
flag swing, KAST-F, per-life output, and fast multikills — combined with
UNCALIBRATED weights. Shadow only: published beside nothing, ranked by
nothing, until the comparison review against the historical Excel KTPR
signs off (umbrella goal, Tier 3 gates).
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
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


def load_class_swing_offsets(path=None) -> dict[str, float]:
    """The reviewed per-class swing offsets, or an empty table.

    Deliberately NOT applied by default: a caller opts in by passing the result
    to `build_ktpr_v2_shadow`. Loading at import the way `flag_swing` does for
    map coefficients would make every unit test depend on a calibration file
    that moves weekly.

    A missing or malformed file yields {}, which is the pre-correction
    behaviour — a report must never fail to build because a calibration
    artifact is absent.
    """
    import json
    from pathlib import Path

    path = path or (Path(__file__).resolve().parents[1]
                    / "config" / "class_swing_offsets.json")
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return {str(code): float(row["offset"])
                for code, row in (payload.get("classes") or {}).items()
                if row.get("offset") is not None}
    except (OSError, ValueError, KeyError, TypeError):
        return {}


def primary_class(life_rows) -> dict[int, int]:
    """Each player's class for the match: the one he spent most lives in.

    The same rule the offsets were fitted under (coordination
    `hv_class_bias.py`, and `scripts/fit_class_swing_offsets.py`), read from the
    same `ktp_life_events.player_class` column, so the fit and its application
    cannot disagree about who counts as a sniper. A player who switches
    mid-match is attributed to his main, which per-life attribution would fix
    only if the rating were decomposed per life, and it is not.
    """
    tally: dict[int, dict[int, int]] = {}
    for row in life_rows or ():
        pid, code = row.get("player_id"), row.get("player_class")
        if pid is None or code in (None, "", "NULL"):
            continue
        try:
            pid, code = int(pid), int(code)
        except (TypeError, ValueError):
            continue
        tally.setdefault(pid, {})
        tally[pid][code] = tally[pid].get(code, 0) + 1
    return {pid: max(by.items(), key=lambda kv: kv[1])[0]
            for pid, by in tally.items() if by}


def _apply_class_swing_offsets(z, ids, class_of, offsets):
    """Lift the swing component by the player's class offset, then re-centre.

    `flag_swing` attributes flag control, and a sniper's job is to hold mid
    without standing on it, so the component reads the role as absence. Both
    sniper classes measured several standard errors below zero on swing while
    the overall rating gap was not significant (coordination
    `review/hidden-value/tools/hv_class_bias.py`, handed over 2026-10-11), and
    the deficit is attribution rather than lower contribution: within the 44
    players who played sniper in some officials and another class in others,
    sniping cost 0.568 sigma of swing while the team's win rate was unchanged.

    The offsets are deviations measured ON this component's own within-match z,
    so they subtract directly in the same units. Re-centring afterwards keeps
    the component's mean at zero, which is what `per_match_z_scores` promises:
    a consumer once read that metadata and applied a second z-transform
    (keep-the-prac #679/#691), so the claim has to stay exactly true rather
    than nearly true.

    Ordering is untouched between players of the same class and moves only
    across classes, which is the whole intent.
    """
    if "swing" not in z or not class_of or not offsets or not ids:
        return {"applied": False,
                "reason": "no swing component, no class map, or no offsets"}
    shifted, used = {}, {}
    for pid in ids:
        code = class_of.get(pid)
        offset = offsets.get(str(code)) if code is not None else None
        shifted[pid] = z["swing"][pid] - float(offset or 0.0)
        if offset:
            used[str(code)] = round(float(offset), 4)
    mean = sum(shifted.values()) / len(shifted)
    z["swing"] = {pid: value - mean for pid, value in shifted.items()}
    return {"applied": bool(used), "offsets_used": used,
            "mean_removed": round(mean, 4),
            "note": ("Swing is corrected for the player's class, then "
                     "re-centred so the component still averages zero.")}


def build_ktpr_v2_shadow(
    players: Sequence[dict[str, Any]] | None,
    flag_fight_players: Sequence[dict[str, Any]] | None,
    flag_swing_players: Sequence[dict[str, Any]] | None,
    config: KtprV2Config | None = None,
    class_of: Mapping[int, int] | None = None,
    class_swing_offsets: Mapping[str, float] | None = None,
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
    envelope["class_swing_adjustment"] = _apply_class_swing_offsets(
        z, ids, class_of, class_swing_offsets)
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
