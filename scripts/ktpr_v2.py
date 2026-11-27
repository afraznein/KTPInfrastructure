"""KTPR v2 shadow blend (Tier 3, definition v2).

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
    # Divisor floor for the per-minute count components. A rate over a
    # minute of play is noise, so a 60 s cameo is divided as if he played
    # this long -- floored, not excluded: he still played. Same 300 s the
    # accumulation impact index gates on (accumulation_v3).
    minimum_observed_seconds: float = 300.0

    def validate(self) -> None:
        weights = (self.swing_weight, self.kast_weight,
                   self.output_weight, self.multikill_weight)
        if any(w < 0 for w in weights) or not any(weights):
            raise ValueError("KTPR v2 weights must be >= 0 and not all zero")
        if not self.minimum_observed_seconds > 0:
            raise ValueError("KTPR v2 minimum_observed_seconds must be > 0")


def _observed_minutes(ids, box, floor_seconds) -> dict[int, float] | None:
    """Each player's divisor for the count components, or None.

    Operator ruling 2026-11-27: a sub who played one half must not rate as
    half a player, and an overtime match must not inflate everyone's counts.
    `multikill` and `swing` are raw counts, so they grow with time played;
    `output` and `kast_f` are already rates and are left alone.

    None when no player in the match has an observed time (a match before
    position samples, or a legacy archive): the counts stay raw, exactly as
    definition v1 rated them -- dividing by a guessed constant would change
    nothing but the claim.

    A player with no observed time in a match where others have one is
    divided by the full match (his row's `duration_seconds`, else the longest
    observed player). That is the largest divisor he could have, so an
    unmeasured player can never be inflated by the normalisation.
    """
    known = {pid: float(box[pid]["observed_seconds"]) for pid in ids
             if box[pid].get("observed_seconds") is not None}
    if not known:
        return None
    longest = max(known.values())
    minutes = {}
    for pid in ids:
        seconds = known.get(pid)
        if seconds is None:
            seconds = float(box[pid].get("duration_seconds") or 0) or longest
        minutes[pid] = max(seconds, floor_seconds) / 60.0
    return minutes


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


def class_shares(life_rows) -> dict[int, dict[int, float]]:
    """Each player's share of his lives per class, from `player_class`.

    NOT the single class he played most. Picking a primary looked like the
    simple honest choice and it is wrong for the player it matters most to:
    measured over S10, one player has lives in EIGHT classes and played more
    than one in 37 of his 39 matches. Collapsing that match to "rifleman"
    applies a ~0 offset to someone who spent a third of it sniping, so the
    correction would systematically under-serve exactly the flex players whose
    contribution the rating already struggles to see — and it was a flex
    player's rating that raised this in the first place.

    A share-weighted offset is also continuous, so a player drifting between
    roles across a season stops jumping between corrections.

    Read from the same `ktp_life_events.player_class` column the offsets were
    fitted on (coordination `hv_class_bias.py`,
    `scripts/fit_class_swing_offsets.py`), so the fit and its application
    cannot disagree about who was sniping. The fit still scores a match-player
    under his majority class, which is the right unit there: it is estimating
    what the class does to the component, not what a mixed match does to a
    player.
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
    shares: dict[int, dict[int, float]] = {}
    for pid, by in tally.items():
        lives = sum(by.values())
        if lives:
            shares[pid] = {code: n / lives for code, n in by.items()}
    return shares


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
        # Share-weighted: a player who split the match across roles gets the
        # blend he actually played, not whichever class happened to lead.
        correction = 0.0
        for code, share in (class_of.get(pid) or {}).items():
            offset = offsets.get(str(code))
            if offset:
                correction += float(share) * float(offset)
                used[str(code)] = round(float(offset), 4)
        shifted[pid] = z["swing"][pid] - correction
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
    class_of: Mapping[int, Mapping[int, float]] | None = None,
    class_swing_offsets: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    """Blend the merged per-player components into one shadow rating.

    A component whose source is missing for the match is dropped and its
    weight redistributed over the rest — a missing feed must not read as a
    zero performance. If every component is missing, the blend is
    unavailable.

    `multikill` and `swing` are divided by each player's observed minutes
    (`players[].observed_seconds`) before z-scoring -- see _observed_minutes
    for the unknown-time and floor rules. z-scores are scale-invariant, so a
    match where everyone was observed equally rates exactly as v1 did.
    """
    config = config or KtprV2Config()
    config.validate()
    envelope: dict[str, Any] = {
        "definition": "ktpr_v2_blend_v1",
        "definition_version": 2,
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
    minutes = _observed_minutes(ids, box, config.minimum_observed_seconds)
    envelope["parameters"]["count_components_per"] = (
        "observed_minute" if minutes else "match_no_observed_time")

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
                               + 4.0 * float(row.get("fast_4k_plus") or 0)
                               ) / (minutes[pid] if minutes else 1.0)
    if multikills:
        components["multikill"] = multikills
    if flag_fight_players:
        kast = {int(p["player_id"]): float(p["kast_f"])
                for p in flag_fight_players
                if p.get("kast_f") is not None}
        if kast:
            components["kast_f"] = kast
    if flag_swing_players:
        # A swing row outside the box score is never z-scored, so its
        # missing divisor is moot.
        swing = {int(p["player_id"]): float(p["attributed_swing"])
                 / (minutes or {}).get(int(p["player_id"]), 1.0)
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
    if minutes and envelope["class_swing_adjustment"]["applied"]:
        envelope["caveats"].append(
            "Class swing offsets were fitted on per-match swing (definition "
            "v1); this match's swing is per observed minute. Refit owed once "
            "reports regenerate at the per-minute definition.")
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
