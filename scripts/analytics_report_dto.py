"""analytics-report-dto-v1: sanitize a match_analytics schema-v7 report for the website.

Whitelist-only construction — nothing is copied wholesale from the internal
report. Output carries player names (public on a stats site) and NEVER:
player_id, steam_id, event ids, wall-clock unix stamps, positional keys, or
any shadow/private block outside Tier P1 (see
WEBSITE_SHADOW_STATS_PROMOTION_HANDOVER_20260906.md §2-3; pid-only rule
applies to review artifacts, not the website).

CLI: python analytics_report_dto.py report.json [...] --out DIR
       [--accumulation accumulation-report.json]  (attach a scorer output)
Library: sanitize_report(report_dict) -> dict, assert_sanitized(dto).

Accumulation (points, points per life, impact index) comes from the separate
accumulation scorer (accumulation_v3 + momentum v5 profile). report_service
attaches its shareable part under report["accumulation"] when the scorer ran;
otherwise the DTO's ratings.accumulation block is status "unavailable" and the
website renders Unavailable, never zero.
"""
from __future__ import annotations

import argparse
import copy
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts.in_game_result import unavailable as in_game_unavailable
from scripts.kill_streaks import DEFINITION as KILL_STREAK_DEFINITION
from scripts.kill_streaks import DEFINITION_VERSION as KILL_STREAK_DEFINITION_VERSION

CONTRACT_VERSION = "analytics-report-dto-v1.11.0"  # docs/ANALYTICS_REPORT_DTO_CONTRACT.md

# hlstatsx DATETIMEs are naive league-local time: the data server runs
# America/New_York. The website column is timestamptz, which reads a naive
# literal as UTC, so an unstamped value publishes four hours early.
REPORT_SOURCE_TZ = "America/New_York"

# Key names that must never appear anywhere in a sanitized DTO (identity,
# raw event/positional keys, private blocks). Rating blocks are allowed
# since the 2026-09-06 P2 decision, labeled provisional.
FORBIDDEN_KEY_PARTS = (
    "player_id", "steam_id", "steamid", "event_id", "unix", "pos_",
    "private", "life_", "timeline", "break_reel",
)

PROVISIONAL_NOTICE = (
    "Provisional rating: uncalibrated model, recomputed as calibration "
    "matures. Published values change retroactively."
)


def _num(value):
    """Internal reports carry some numerics as strings ('1.656', '958')."""
    if value is None or isinstance(value, (int, float)):
        return value
    try:
        f = float(value)
        return int(f) if f.is_integer() else f
    except (TypeError, ValueError):
        return None


KTPR_DISPLAY_FLOOR = 50.0
KTPR_DISPLAY_CENTER = 100.0
KTPR_DISPLAY_PER_Z = 15.0

# Published alongside the ratings so a consumer can tell, without reading this
# module, which fields are already on a display scale and which are raw.
#
# This block exists because its absence caused a real outage. `parameters`
# carries the MODEL's own settings, including "normalization":
# "per_match_z_scores" — true of the internal math and of `components`, but
# NOT of the published `rating`, which ktpr_display() has already rescaled.
# A consumer that reasonably read that metadata as describing `rating`
# applied a second z-score transform on top (keep-the-prac #679/#691), which
# saturated every value to exactly 100.0 on every match page. Describe the
# published scale explicitly rather than leaving it to be inferred.
KTPR_DISPLAY_SCALE = {
    "rating": {
        "kind": "floored_index",
        "center": KTPR_DISPLAY_CENTER,
        "per_z": KTPR_DISPLAY_PER_Z,
        "floor": KTPR_DISPLAY_FLOOR,
        "note": "Already scaled for display: max(floor, center + per_z * z). "
                "Render as published; do not transform again.",
    },
    "kast_f_pct": {
        "kind": "percent",
        "note": "KAST-F in its own units: the share of flag fights where the "
                "player got a kill, got an assist, survived, or had their death "
                "traded. 0-100. Show THIS as the KAST figure. "
                "components.kast_f is the same quantity on the index below, "
                "useful only as a comparison against the match average -- it is "
                "not a percentage and reads as a nonsensical one (a KAST of 125 "
                "is +1.67 sigma, not 125%). null means not measured.",
    },
    "components": {
        "kind": "floored_index",
        "center": KTPR_DISPLAY_CENTER,
        "per_z": KTPR_DISPLAY_PER_Z,
        "floor": KTPR_DISPLAY_FLOOR,
        "note": "Same scale as rating (2026-09-14): one transform, applied "
                "once, here. Render as published; do not transform again.",
    },
}


def ktpr_display(z, *, floor: float = KTPR_DISPLAY_FLOOR,
                  center: float = KTPR_DISPLAY_CENTER,
                  per_z: float = KTPR_DISPLAY_PER_Z):
    """Map a KTPR v2 z-score rating onto a floored display scale.

    Operator ruling 2026-09-09: KTPR v2 must never show a negative number
    on the website; 50 is the floor. Internal z-score math (ktpr_v2.py,
    ktpr_season.py) is unaffected — this only shapes what ships in the DTO.

    The resulting scale is advertised in the payload as KTPR_DISPLAY_SCALE;
    keep the two in step (tests/unit/test_analytics_report_dto.py pins that
    the advertised numbers reproduce this function's output).
    """
    value = _num(z)
    if value is None:
        return None
    return round(max(floor, center + per_z * value), 2)


def _kast_pct(share):
    """KAST-F as a percentage, 0-100, or None if it was not measured.

    `flag_fights` suppresses kast_f entirely when the assist or trade source is
    unavailable, rather than emitting a lower number -- an absent trade feed
    would otherwise look like "never got traded", which is a real penalty
    rather than missing data. None must therefore stay None here and render as
    "not measured", not as 0%.
    """
    if share is None:
        return None
    return round(float(share) * 100.0, 1)


def _name(value):
    """Repair double-encoded UTF-8 ('SavageÂ¬' -> 'Savage¬').

    Reports generated over the SSH console path carry names that were UTF-8
    bytes re-decoded as latin-1. A strict latin-1 -> utf-8 round trip only
    succeeds on such strings, so a correct name passes through untouched.
    Server-local report generation does not need this; kept as defense.
    """
    if not isinstance(value, str):
        return value
    for codec in ("latin-1", "cp1252"):
        try:
            return value.encode(codec).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
    return value


def _instant(value):
    """Naive league-local timestamp -> ISO-8601 carrying its UTC offset.

    Stamped here, at the one point the value becomes public, so the website's
    timestamptz column and the payload copy of it cannot disagree. Idempotent:
    an already-aware value passes through, so a second reader cannot
    double-correct. Anything unparseable is returned untouched -- a malformed
    timestamp should fail its insert loudly, not arrive silently shifted.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text or text == "None":
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return text
    if parsed.tzinfo is None:
        # Per-date, so a match either side of the November DST change is
        # stamped with the offset that was actually in force.
        parsed = parsed.replace(tzinfo=ZoneInfo(REPORT_SOURCE_TZ))
    return parsed.isoformat()


def _actor(a: dict) -> dict:
    return {"name": _name(a.get("name")), "team": a.get("team")}


POINTS_PER_LIFE_DEFINITION = (
    "total_points / (deaths + halves_played): every life ends in a death "
    "except the last one of each half"
)


def _accumulation_block(report: dict, team_by_name: dict) -> dict:
    """Shareable slice of the accumulation scorer output (attached by
    report_service as report['accumulation']); fail-closed when absent."""
    acc = report.get("accumulation") or {}
    players = acc.get("players") or []
    if not players:
        return {"status": "unavailable", "players": []}
    halves = _num((report.get("match") or {}).get("halves_played")) or 0
    rows = []
    for p in players:
        name = _name(p.get("player_name_at_match"))
        total = _num(p.get("total_points"))
        deaths = _num(p.get("deaths"))
        lives = (deaths or 0) + halves
        rows.append({
            "name": name,
            "team": team_by_name.get(name),
            "total_points": total,
            "points_per_minute": _num(p.get("points_per_minute")),
            "points_per_life": (round(total / lives, 2)
                                if total is not None and lives > 0 else None),
            "impact_index": _num(p.get("impact_index")),
            "observed_seconds": _num(p.get("observed_seconds")),
            "participation_percent": _num(p.get("participation_percent")),
            "rank": _num(p.get("rank")),
        })
    impact = acc.get("impact_index") or {}
    return {
        "status": acc.get("status"),
        "publication_state": acc.get("publication_state"),
        "profile": acc.get("profile"),
        "profile_sha256": acc.get("profile_sha256"),
        "profile_status": acc.get("profile_status"),
        "schema_version": acc.get("schema_version"),
        "generated_at": str(acc.get("generated_at")) if acc.get("generated_at") else None,
        "lives_rule": POINTS_PER_LIFE_DEFINITION,
        "impact_index": {k: _num(impact.get(k)) for k in (
            "center_index", "points_per_robust_sigma", "minimum_index",
            "reference_points_per_minute", "reference_log_scale")}
        | {"range_contract": impact.get("range_contract"),
           "reference_source": impact.get("reference_source")},
        "players": rows,
    }


def sanitize_report(report: dict) -> dict:
    match = report.get("match") or {}
    st = report.get("shadow_timelines") or {}
    se = report.get("shadow_explorations") or {}
    ta = st.get("trade_analysis") or {}
    rs = se.get("recap_speed") or {}
    ktpr = se.get("ktpr_v2") or {}
    # KAST-F's natural unit is a SHARE, and publishing it only on the z-score
    # display index actively misleads: a KAST of 125 reads as "125%", which is
    # impossible for a share. Carried through in its own units alongside the
    # index so the page can show "86.5%" and keep the index as the comparison.
    # Keyed by player_id, which both blocks carry.
    _ff = ((se.get("flag_fights") or {}).get("players")) or []
    kast_share_by_pid = {r.get("player_id"): r.get("kast_f") for r in _ff
                         if r.get("kast_f") is not None}
    swing = se.get("flag_swing") or {}
    # flag_swing players carry no name; join on the internal id here so
    # only the name crosses.
    names_by_id = {p.get("player_id"): _name(p.get("player_name_at_match"))
                   for p in report.get("players") or []}
    team_by_name = {_name(p.get("player_name_at_match")): p.get("team")
                    for p in report.get("players") or []}

    dto = {
        "contract_version": CONTRACT_VERSION,
        "source": {
            "report_schema_version": report.get("schema_version"),
            "generated_at": str(report.get("generated_at")),
            "quality_status": (report.get("quality") or {}).get("status"),
        },
        "match": {
            "match_id": report.get("match_id"),
            "map_name": match.get("map_name"),
            "started_at": _instant(match.get("started_at")),
            "duration_seconds": _num(match.get("duration_seconds")),
            "halves_played": _num(match.get("halves_played")),
        },
        "teams": [
            {k: _num(t.get(k)) for k in (
                "team", "players", "kills", "deaths", "assists",
                "damage_dealt", "damage_taken", "team_damage",
                "capture_credits", "cap_breaks", "shots", "hits",
                "damage_differential", "raw_accuracy",
                "grenade_kills", "grenade_damage", "grenade_damage_taken",
                "score", "kills_per_minute", "points_per_minute")}
            | {"team_name": t.get("team_name")}
            for t in report.get("teams") or []
        ],
        "players": [
            {"name": _name(p.get("player_name_at_match")),
             "team": p.get("team"), "team_name": p.get("team_name")}
            | {k: _num(p.get(k)) for k in PLAYER_FIELDS}
            for p in report.get("players") or []
        ],
        "weapons": [
            {"name": _name(w.get("player_name_at_match")), "team": w.get("team"),
             "weapon": w.get("weapon")}
            | {k: _num(w.get(k)) for k in (
                "kills", "headshot_kills", "damage_dealt", "shots", "hits",
                "raw_accuracy")}
            for w in report.get("weapons") or []
        ],
        "duels": [
            {"killer": _name(c.get("killer_name")),
             "victim": _name(c.get("victim_name")),
             "kills": _num(c.get("kills"))}
            for c in (report.get("duel_matrix") or {}).get("cells") or []
            if c.get("cross_team")
        ],
        "trades": {
            "definitions": {
                name: {"definition_version":
                       (d or {}).get("definition_version")}
                for name, d in (st.get("definitions") or {}).items()
            },
            "events": [
                {"half": _num(t.get("half")),
                 "seconds_after": _num(t.get("seconds_after")),
                 "fallen": _actor(t.get("fallen_player") or {}),
                 "original_killer": _actor(t.get("original_killer") or {}),
                 "trader": _actor(t.get("trader") or {})}
                for t in st.get("trades") or []
            ],
            "teams": [
                {"team": _num(t.get("team")),
                 "trade_kills": _num(t.get("trade_kills")),
                 "opportunities": _num(
                     t.get("team_death_response_opportunities")),
                 "response_rate": _num(t.get("team_death_response_rate"))}
                for t in ta.get("teams") or []
            ],
        },
        "fast_multikills": [
            {"classification": m.get("classification"),
             "half": _num(m.get("half")),
             "killer": _actor(m.get("killer") or {}),
             "kill_count": _num(m.get("kill_count")),
             "elapsed_seconds": _num(m.get("elapsed_seconds")),
             "victims": [_actor(v) for v in m.get("victims") or []],
             "objective_converted":
                 bool((m.get("objective_conversion") or {}).get("converted"))}
            for m in st.get("fast_multikills") or []
        ],
        "recap_speed": {
            "definition_version": rs.get("definition_version"),
            "teams": [
                {"team": _num(t.get("team")), "recaps": _num(t.get("recaps")),
                 "median_seconds": _num(t.get("median_seconds")),
                 "mean_seconds": _num(t.get("mean_seconds"))}
                for t in rs.get("teams") or []
            ],
            "events": [
                {"half": _num(e.get("half")), "flag_name": e.get("flag_name"),
                 "team": _num(e.get("team")),
                 "seconds": _num(e.get("seconds"))}
                for e in rs.get("recaps") or []
            ],
        },
        "ratings": {
            "provisional": True,
            "notice": PROVISIONAL_NOTICE,
            "ktpr_v2": {
                "status": ktpr.get("status"),
                "definition": ktpr.get("definition"),
                "definition_version": ktpr.get("definition_version"),
                "calibration": ktpr.get("calibration"),
                "parameters": dict(ktpr.get("parameters") or {}),
                # `parameters` describes the model; `display_scale` describes
                # what the numbers below actually are. They are not the same
                # thing -- see KTPR_DISPLAY_SCALE.
                "display_scale": copy.deepcopy(KTPR_DISPLAY_SCALE),
                "components_used": list(ktpr.get("components_used") or []),
                "players": [
                    {"name": _name(p.get("player_name_at_match"))
                     or names_by_id.get(p.get("player_id")),
                     "team": p.get("team"),
                     "rating": ktpr_display(p.get("rating")),
                     "components": {k: ktpr_display(v) for k, v in
                                    (p.get("components") or {}).items()},
                     # Natural units, NOT on the display index. Render this as
                     # the KAST figure; the index belongs next to it as "vs
                     # match average", never on its own.
                     "kast_f_pct": _kast_pct(kast_share_by_pid.get(p.get("player_id")))}
                    for p in ktpr.get("players") or []
                ],
            },
            "flag_swing": {
                "status": swing.get("status"),
                "definition": swing.get("definition"),
                "definition_version": swing.get("definition_version"),
                "calibration": swing.get("calibration"),
                "parameters": dict(swing.get("parameters") or {}),
                "players": [
                    {"name": names_by_id.get(p.get("player_id")),
                     "team": p.get("team"),
                     "attributed_swing": _num(p.get("attributed_swing")),
                     "weighted_frags": _num(p.get("weighted_frags"))}
                    for p in swing.get("players") or []
                ],
            },
            "accumulation": _accumulation_block(report, team_by_name),
        },
        "lane_analytics": _positional_block(se, names_by_id),
        "spatial": _spatial_block(report),
        "in_game_result": _in_game_result_block(report),
        "key_moments": _key_moments_block(se, names_by_id),
        "progression": _progression_block(se, names_by_id),
        "plays": _plays_block(se, names_by_id),
        "capouts": _capouts_block(se),
        "player_halves": _player_halves_block(report),
        "kill_streaks": _kill_streaks_block(report),
        "weapon_sides": _weapon_sides_block(report),
        "duels_by_side": _duels_by_side_block(report),
        "player_classes": _player_classes_block(report),
    }
    _unknown_team_totals(dto["teams"], report.get("players") or [])
    dto["box_score_scale"] = _box_score_scale(dto["players"])
    assert_sanitized(dto)
    return dto


# Box-score columns whose producer postdates part of the archive. The internal
# team sum reads a None as 0, so a team of unknowns would publish a false zero.
PRODUCER_DATED_FIELDS = ("assists", "capture_credits", "cap_breaks")


def _unknown_team_totals(teams: list[dict], players: list[dict]) -> None:
    for team in teams:
        members = [p for p in players if p.get("team") == team.get("team")]
        for field in PRODUCER_DATED_FIELDS:
            if members and all(p.get(field) is None for p in members):
                team[field] = None


PLAYER_FIELDS = (
    "kills", "deaths", "assists", "headshots", "team_kills",
    "suicides", "damage_dealt", "damage_taken",
    "damage_differential", "capture_credits", "cap_breaks",
    "shots", "hits", "raw_accuracy", "kd_ratio",
    "damage_per_minute", "kills_per_minute", "damage_per_life",
    "headshot_rate", "fast_2k", "fast_3k", "fast_4k_plus",
    "best_streak", "grenade_kills", "grenade_damage",
    "grenade_damage_taken", "score", "points_per_minute",
)

# Fields where a small number is the good one. A fill bar still scales on the
# match max (the bar is "how much", not "how good"), but the match-best star
# goes to the minimum, and a consumer that renders a full bar as an
# achievement here has it backwards -- hence the flag travels in the DTO.
LOWER_IS_BETTER = frozenset({
    "deaths", "damage_taken", "team_kills", "suicides", "grenade_damage_taken",
})


def _box_score_scale(players: list[dict]) -> dict:
    """Fill-bar normalisation for players[], computed once here.

    Operator ruling 2026-09-16: the denominator is the max across ALL players
    in the match, not within the player's own team (Leetify's choice). Per
    field: `max_in_match` (the bar's denominator, so a bar is reproducible
    and auditable), `higher_is_better`, and `best` -- the names holding the
    match-best value (ties keep every name; min when lower is better). A
    consumer's `is_match_best` is "name in best". Fields with no numeric
    value in the match carry `max_in_match: null` and an empty `best`.
    """
    fields = {}
    for field in PLAYER_FIELDS:
        values = [(p["name"], p.get(field)) for p in players
                  if isinstance(p.get(field), (int, float))]
        if not values:
            fields[field] = {"max_in_match": None,
                             "higher_is_better": field not in LOWER_IS_BETTER,
                             "best": []}
            continue
        maximum = max(v for _, v in values)
        target = min(v for _, v in values) if field in LOWER_IS_BETTER else maximum
        fields[field] = {
            "max_in_match": maximum,
            "higher_is_better": field not in LOWER_IS_BETTER,
            "best": [name for name, v in values if v == target],
        }
    return {"scope": "all_players", "fields": fields}


def _progression_block(se: dict, names_by_id: dict) -> dict:
    """Public form of shadow_explorations.progression: cumulative series per
    player per half (kills, deaths, damage, cap_breaks, cap_participation)
    and per team (flag differential), as [game_time, cumulative] points.
    Names only; ids never cross."""
    pr = se.get("progression") or {}
    return {
        "status": pr.get("status") or "unavailable",
        "definition": pr.get("definition"),
        "definition_version": pr.get("definition_version"),
        "parameters": dict(pr.get("parameters") or {}),
        "metrics": list(pr.get("metrics") or []),
        "team_metrics": list(pr.get("team_metrics") or []),
        "available": dict(pr.get("available") or {}),
        "coverage": {k: _num(v) for k, v in (pr.get("coverage") or {}).items()},
        "caveats": list(pr.get("caveats") or []),
        "players": [
            {"name": names_by_id.get(row.get("player_id")),
             "team": _num(row.get("team")),
             "half": _num(row.get("half")),
             "metric": row.get("metric"),
             "points": [[_num(t), _num(v)] for t, v in row.get("points") or []]}
            for row in pr.get("players") or []
        ],
        "teams": [
            {"team": _num(row.get("team")),
             "half": _num(row.get("half")),
             "metric": row.get("metric"),
             "points": [[_num(t), _num(v)] for t, v in row.get("points") or []]}
            for row in pr.get("teams") or []
        ],
    }


IN_GAME_RESULT_HALF_FIELDS = (
    "half", "team1_points", "team2_points", "team1_cumulative",
    "team2_cumulative", "team1_side", "team2_side",
)


def _key_moments_block(se: dict, names_by_id: dict) -> dict:
    """Public form of shadow_explorations.highlight_windows.

    A coarse, derived list -- at most top_n windows, each a game-time span, a
    one-line summary, and the few players involved by name. It is not the event
    stream: the per-event ``timeline`` stays private, and this block carries no
    ids, positions, or per-kill detail. Consumers (key-moments section, HLTV
    deep links, post-match message) read this rather than re-ranking.
    """
    hw = se.get("highlight_windows") or {}
    return {
        "status": hw.get("status") or "unavailable",
        "definition": hw.get("definition"),
        "definition_version": hw.get("definition_version"),
        "parameters": dict(hw.get("parameters") or {}),
        "windows_total": _num(hw.get("windows_total")),
        "windows": [
            {
                "rank": w.get("rank"),
                "half": w.get("half"),
                "start": _num(w.get("start")),
                "end": _num(w.get("end")),
                "duration": _num(w.get("duration")),
                "peak_at": _num(w.get("peak_at")),
                "kinds": list(w.get("kinds") or []),
                "events": _num(w.get("events")),
                "swing": _num(w.get("swing")),
                "peak_delta": _num(w.get("peak_delta")),
                "score": _num(w.get("score")),
                "summary": w.get("summary"),
                "involved": [
                    {"name": _name(p.get("player_name_at_match"))
                     or names_by_id.get(p.get("player_id")),
                     "team": p.get("team"),
                     "involvement": _num(p.get("involvement"))}
                    for p in w.get("involved") or []
                ],
            }
            for w in hw.get("windows") or []
        ],
    }


def _play(p: dict, names_by_id: dict) -> dict:
    exc = p.get("excursion")
    return {
        "rank": p.get("rank"),
        "name": _name(p.get("player_name_at_match")) or names_by_id.get(p.get("player_id")),
        "team": p.get("team"),
        "side": p.get("side"),
        "half": p.get("half"),
        "start": _num(p.get("start")),
        "end": _num(p.get("end")),
        "duration": _num(p.get("duration")),
        "peak_at": _num(p.get("peak_at")),
        "value": _num(p.get("value")),
        "event_value": _num(p.get("event_value")),
        "exposure": _num(p.get("exposure")),
        "kills": _num(p.get("kills")),
        "deaths": _num(p.get("deaths")),
        "caps": _num(p.get("caps")),
        "capout_denials": _num(p.get("capout_denials")),
        "excursion": None if not exc else {
            "duration": _num(exc.get("duration")),
            "min_teammate_distance": _num(exc.get("min_teammate_distance")),
            "closest_flag": exc.get("closest_flag"),
            "closest_flag_distance": _num(exc.get("closest_flag_distance")),
        },
        "tags": list(p.get("tags") or []),
        "summary": p.get("summary"),
    }


def _capouts_block(se: dict) -> dict:
    """Public form of shadow_explorations.capouts: each completed cap-out
    (one side owning every flag at once), report-team convention. Status
    follows flag_swing's own -- capouts is a byproduct of its event stream,
    with the same availability. A report built before schema 19 has none
    and reads unavailable."""
    fs = se.get("flag_swing") or {}
    return {
        "status": fs.get("status") or "unavailable",
        "events": [
            {"half": _num(c.get("half")), "game_time": _num(c.get("game_time")),
             "team": _num(c.get("team"))}
            for c in se.get("capouts") or []
        ],
    }


def _plays_block(se: dict, names_by_id: dict) -> dict:
    """Public form of shadow_explorations.plays: each player's best two or
    three plays and the match's top three. The dunce (the worst play) stays
    in the private block by decision (2026-09-19): it names a player for
    their worst moment, and it is kept for an end-of-season reel, not the
    match page. Names only; distances and depths are aggregates, never
    coordinates. A report built before schema 18 has none and reads
    unavailable."""
    pl = se.get("plays") or {}
    return {
        "status": pl.get("status") or "unavailable",
        "definition": pl.get("definition"),
        "definition_version": pl.get("definition_version"),
        "parameters": dict(pl.get("parameters") or {}),
        "caveats": list(pl.get("caveats") or []),
        "plays_total": _num(pl.get("plays_total")),
        "match_top": [_play(p, names_by_id) for p in pl.get("match_top") or []],
        "per_player": [
            {
                "name": _name(row.get("player_name_at_match")) or names_by_id.get(row.get("player_id")),
                "team": row.get("team"),
                "plays": [_play(p, names_by_id) for p in row.get("plays") or []],
            }
            for row in pl.get("per_player") or []
        ],
    }


def _in_game_result_block(report: dict) -> dict:
    """The engine's team score (scripts/in_game_result.py), not the league
    result. A report built before schema 10 has none and reads unavailable."""
    r = report.get("in_game_result")
    if not r:
        return in_game_unavailable("not-in-report")
    winner = r.get("winner")
    return {
        "status": r.get("status"),
        "flags": list(r.get("flags") or []),
        "authority": r.get("authority"),
        "source": r.get("source"),
        "producer": r.get("producer"),
        "notice": r.get("notice"),
        "team1_score": _num(r.get("team1_score")),
        "team2_score": _num(r.get("team2_score")),
        "winner": winner if winner == "draw" else _num(winner),
        "halves": [{k: (h.get(k) if k.endswith("_side") else _num(h.get(k)))
                    for k in IN_GAME_RESULT_HALF_FIELDS}
                   for h in r.get("halves") or []],
    }


PLAYER_HALF_FIELDS = (
    "half", "duration_seconds", "kills", "deaths", "assists", "headshots",
    "team_kills", "suicides", "damage_dealt", "damage_taken", "team_damage",
    "damage_differential", "capture_credits", "cap_breaks", "shots", "hits",
    "kd_ratio", "headshot_rate", "raw_accuracy", "damage_per_minute",
    "kills_per_minute", "best_streak", "grenade_kills", "grenade_damage",
    "grenade_damage_taken", "score", "points_per_minute",
)


def _player_halves_block(report: dict) -> dict:
    """Per-half box score (scripts/player_halves.py). `team` is the match team
    number; `side` is the side played that half."""
    ph = report.get("player_halves") or {}
    return {
        "status": ph.get("status", "unavailable"),
        "reconciled": ph.get("reconciled"),
        "mismatched_columns": list(ph.get("mismatched_columns") or []),
        "rows": [
            {"name": _name(p.get("player_name_at_match")), "team": _num(p.get("team")),
             "side": _side(p.get("side"))}
            | {k: _num(p.get(k)) for k in PLAYER_HALF_FIELDS}
            for p in ph.get("rows") or []
        ],
    }


SIDES = ("Allies", "Axis")


def _side(value):
    return value if value in SIDES else None


def _not_in_report(rows_key: str = "rows") -> dict:
    return {"status": "unavailable", "flags": ["not-in-report"], rows_key: []}


KILL_STREAK_COVERAGE = (
    "ordered_frags", "recovered_frags", "unordered_frags", "kills_after_own_death",
)


def _kill_streaks_block(report: dict) -> dict:
    """kill_streak_v1 (scripts/kill_streaks.py). A report built before schema 11
    has none and reads unavailable, never zero."""
    ks = report.get("kill_streaks")
    if not ks:
        return {"definition": KILL_STREAK_DEFINITION,
                "definition_version": KILL_STREAK_DEFINITION_VERSION,
                "coverage": {k: None for k in KILL_STREAK_COVERAGE},
                "players": []} | _not_in_report()
    coverage = ks.get("coverage") or {}
    return {
        "definition": ks.get("definition"),
        "definition_version": _num(ks.get("definition_version")),
        "status": ks.get("status"),
        "flags": list(ks.get("flags") or []),
        "coverage": {k: _num(coverage.get(k)) for k in KILL_STREAK_COVERAGE},
        "rows": [
            {"name": _name(r.get("player_name_at_match")), "team": _num(r.get("team")),
             "half": _num(r.get("half")), "side": _side(r.get("side")),
             "kills": _num(r.get("kills")), "best_streak": _num(r.get("best_streak")),
             "streaks_3_plus": _num(r.get("streaks_3_plus")),
             "lower_bound": bool(r.get("lower_bound"))}
            for r in ks.get("rows") or []
        ],
        "players": [
            {"name": _name(p.get("player_name_at_match")), "team": _num(p.get("team")),
             "best_streak": _num(p.get("best_streak")),
             "by_side": {s: _num((p.get("by_side") or {}).get(s)) for s in SIDES},
             "lower_bound": bool(p.get("lower_bound"))}
            for p in ks.get("players") or []
        ],
    }


WEAPON_SIDE_FIELDS = ("kills", "headshot_kills", "shots", "hits", "damage_dealt")


def _weapon_sides_block(report: dict) -> dict:
    """Weapon totals per player per half under the side the PLAYER held, so a
    picked-up enemy weapon stays under the player's side."""
    ws = report.get("weapon_sides")
    if not ws:
        return {"reconciled": None, "mismatched_columns": [],
                "unsided_kills": None} | _not_in_report()
    return {
        "status": ws.get("status"),
        "flags": list(ws.get("flags") or []),
        "reconciled": ws.get("reconciled"),
        "mismatched_columns": list(ws.get("mismatched_columns") or []),
        "unsided_kills": _num(ws.get("unsided_kills")),
        "rows": [
            {"name": _name(r.get("player_name_at_match")), "team": _num(r.get("team")),
             "half": _num(r.get("half")), "side": _side(r.get("side")),
             "weapon": r.get("weapon")}
            | {k: _num(r.get(k)) for k in WEAPON_SIDE_FIELDS}
            for r in ws.get("rows") or []
        ],
    }


def _duels_by_side_block(report: dict) -> dict:
    """duels[] split by the killer's side; cross-team cells only, as in duels[]."""
    ds = report.get("duels_by_side")
    if not ds:
        return {"reconciled": None, "unsided_kills": None} | _not_in_report("cells")
    return {
        "status": ds.get("status"),
        "flags": list(ds.get("flags") or []),
        "reconciled": ds.get("reconciled"),
        "unsided_kills": _num(ds.get("unsided_kills")),
        "cells": [
            {"killer": _name(c.get("killer_name")), "victim": _name(c.get("victim_name")),
             "killer_side": _side(c.get("killer_side")), "kills": _num(c.get("kills"))}
            for c in ds.get("cells") or []
            if c.get("cross_team")
        ],
    }


PLAYER_CLASS_FIELDS = ("lives", "kills", "deaths", "headshot_kills")
PLAYER_CLASS_COVERAGE = (
    "lives", "lives_mapped", "kills_classed", "kills_unclassed",
    "deaths_classed", "deaths_unclassed",
)


def _player_classes_block(report: dict) -> dict:
    """Per-class rows from the class read at spawn. No accuracy: shots carry no
    class or time at the source."""
    pc = report.get("player_classes")
    if not pc:
        return {"coverage": {k: None for k in PLAYER_CLASS_COVERAGE}
                | {"unmapped_class_ids": []}} | _not_in_report()
    coverage = pc.get("coverage") or {}
    return {
        "status": pc.get("status"),
        "flags": list(pc.get("flags") or []),
        "coverage": {k: _num(coverage.get(k)) for k in PLAYER_CLASS_COVERAGE}
        | {"unmapped_class_ids": [_num(c) for c in coverage.get("unmapped_class_ids") or []]},
        "rows": [
            {"name": _name(r.get("player_name_at_match")), "team": _num(r.get("team")),
             "half": _num(r.get("half")), "side": _side(r.get("side")),
             "class_id": _num(r.get("class_id")), "class_code": r.get("class_code"),
             "class_name": r.get("class_name")}
            | {k: _num(r.get(k)) for k in PLAYER_CLASS_FIELDS}
            for r in pc.get("rows") or []
        ],
    }


DEPTH_UNITS = {
    "mean_depth": "lane_fraction_own_end_0_enemy_end_1",
    "depth_sd": "lane_fraction",
    "lateral_mean": "world_units",
}


def _positional_block(se: dict, names_by_id: dict) -> dict:
    """Positional shadow (WEBSITE_POSITIONAL_ANALYTICS_PLAN_20260906 §2):
    team-level control curve (GREEN), per-player overextension scalars
    (GREEN), per-player depth profile scalars (aggregate, identity-attached —
    user sign-off recorded in the plan). No coordinates cross.

    depth_profiles units: mean_depth and depth_sd are fractions of the lane,
    the polyline through the map's flag origins in flag order, with 0 at the
    player's own end and 1 at the enemy end for that half. Each sample is
    clamped to [0, 1], so a player behind their last flag reads 0, not less.
    lateral_mean is the mean perpendicular distance from that line in world
    units."""
    mc = se.get("map_control") or {}
    dp = se.get("depth_profiles") or {}
    ov = se.get("overextension") or {}

    def envelope(block: dict) -> dict:
        return {"status": block.get("status", "unavailable"),
                "definition": block.get("definition"),
                "definition_version": block.get("definition_version"),
                "caveats": list(block.get("caveats") or [])}

    params = mc.get("parameters") or {}
    return {
        "provisional": True,
        "notice": PROVISIONAL_NOTICE,
        "parameters": {k: params.get(k) for k in (
            "bin_seconds", "frontline_quantile", "ahead_margin",
            "min_side_samples_per_bin")},
        "map_control": envelope(mc) | {
            "orientation_by_half": dict(mc.get("orientation_by_half") or {}),
            "halves": {h: [[_num(t), _num(f)] for t, f in curve]
                       for h, curve in (mc.get("halves") or {}).items()},
            "mean_control_team1": _num(mc.get("mean_control_team1")),
            "bins": dict(mc.get("bins") or {}),
        },
        "depth_profiles": envelope(dp) | {"units": dict(DEPTH_UNITS), "players": [
            {"name": _name(p.get("player_name_at_match"))
             or names_by_id.get(p.get("player_id")),
             "team": p.get("team"), "samples": _num(p.get("samples")),
             "mean_depth": _num(p.get("mean_depth")),
             "depth_sd": _num(p.get("depth_sd")),
             "lateral_mean": _num(p.get("lateral_mean"))}
            for p in dp.get("players") or []]},
        "overextension": envelope(ov) | {
            "frags": dict(ov.get("frags") or {}),
            "players": [
                {"name": _name(p.get("player_name_at_match"))
                 or names_by_id.get(p.get("player_id")),
                 "team": p.get("team")}
                | {k: _num(p.get(k)) for k in (
                    "kills_located", "kills_ahead", "deaths_located",
                    "deaths_ahead", "kill_ahead_rate", "death_ahead_rate")}
                for p in ov.get("players") or []]},
    }


SPATIAL_PARAMETERS = (
    "grid_size", "lane_grid_size", "sample_seconds", "cell_minimum_seconds",
    "window_seconds", "window_cell_minimum_seconds",
    "hotspot_minimum_events", "hotspot_minimum_contributors",
    "lane_minimum_occurrences", "lane_minimum_contributors", "lattice",
)
OCCUPANCY_FIELDS = ("col", "row", "samples", "seconds", "team1_samples", "team2_samples", "control")


def _spatial_block(report: dict) -> dict:
    """Map layers (spatial_layers_v2): occupancy/control cells (whole match,
    per half, per time window), unattributed kill/death hotspot cells,
    thresholded recurring lanes, flag origins — and, by the operator's
    2026-09-09 ruling, per-frag kill paths with attacker/victim names when the
    producer published them. Coordinates are world units. The producer's
    `private_frag_vectors` (paths held back when the publish flag is off) is
    never copied."""
    sp = report.get("spatial_layers") or {}
    layers = sp.get("layers") or {}
    params = sp.get("parameters") or {}

    def cell_rows(rows, fields: tuple) -> list:
        return [{k: _num(c.get(k)) for k in fields} for c in rows or []]

    def cells(name: str, fields: tuple) -> list:
        return cell_rows((layers.get(name) or {}).get("cells"), fields)

    def endpoint(e: dict) -> dict:
        return {k: _num(e.get(k)) for k in ("col", "row", "x", "y")}

    halves = {
        str(h): {"start": _num(v.get("start")), "end": _num(v.get("end")),
                 "cells": cell_rows(v.get("cells"), OCCUPANCY_FIELDS)}
        for h, v in (layers.get("halves") or {}).items()
    }
    windows = layers.get("windows") or {}
    frag_layer = layers.get("frag_vectors") or {}
    paths = [
        {"half": _num(v.get("half")), "game_time": _num(v.get("game_time")),
         "attacker": _actor(v.get("attacker") or {}), "victim": _actor(v.get("victim") or {}),
         "origin": {k: _num((v.get("origin") or {}).get(k)) for k in ("x", "y")},
         "destination": {k: _num((v.get("destination") or {}).get(k)) for k in ("x", "y")},
         "weapon": v.get("weapon"), "headshot": bool(v.get("headshot")),
         "distance": _num(v.get("distance")), "angle_degrees": _num(v.get("angle_degrees"))}
        for v in (frag_layer.get("vectors") or []) if frag_layer.get("published")
    ]

    return {
        "halves": halves,
        "windows": {
            "window_seconds": _num(windows.get("window_seconds")),
            "minimum_seconds": _num(windows.get("minimum_seconds")),
            "columns": list(windows.get("columns") or []),
            "rows": [[_num(x) for x in row] for row in windows.get("rows") or []],
        },
        "kill_paths": {"published": bool(frag_layer.get("published")), "vectors": paths},
        "status": sp.get("status", "unavailable"),
        "definition": sp.get("definition"),
        "definition_version": sp.get("definition_version"),
        "caveats": list(sp.get("caveats") or []),
        "provisional": True,
        "notice": PROVISIONAL_NOTICE,
        "parameters": {k: params.get(k) for k in SPATIAL_PARAMETERS},
        "lattice": (dict(sp.get("lattice")) if sp.get("lattice") else None),
        "flags": [
            {"flag_index": _num(f.get("flag_index")), "flag_name": f.get("flag_name"),
             "x": _num(f.get("x")), "y": _num(f.get("y")),
             "col": _num(f.get("col")), "row": _num(f.get("row"))}
            for f in sp.get("flags") or []
        ],
        "coverage": {k: _num(v) for k, v in (sp.get("coverage") or {}).items()},
        "occupancy": cells("occupancy", OCCUPANCY_FIELDS),
        "kill_hotspots": cells("kill_hotspots", ("col", "row", "kills")),
        "death_hotspots": cells("death_hotspots", ("col", "row", "deaths")),
        "recurring_lanes": [
            {"origin": endpoint(v.get("origin") or {}),
             "destination": endpoint(v.get("destination") or {}),
             "count": _num(v.get("count")),
             "mean_distance": _num(v.get("mean_distance")),
             "mean_angle_degrees": _num(v.get("mean_angle_degrees")),
             "headshot_rate": _num(v.get("headshot_rate"))}
            for v in (layers.get("recurring_lanes") or {}).get("vectors") or []
        ],
    }


def _walk_keys(node, path=""):
    if isinstance(node, dict):
        for k, v in node.items():
            yield f"{path}.{k}", k
            yield from _walk_keys(v, f"{path}.{k}")
    elif isinstance(node, list):
        for item in node:
            yield from _walk_keys(item, path + "[]")


def assert_sanitized(dto: dict) -> None:
    for path, key in _walk_keys(dto):
        lowered = key.lower()
        for part in FORBIDDEN_KEY_PARTS:
            if part in lowered:
                raise ValueError(f"forbidden key {key!r} at {path}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("reports", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--accumulation", type=Path, default=None,
                    help="accumulation scorer report.json to attach "
                         "(single-report runs)")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for src in args.reports:
        report = json.loads(src.read_text(encoding="utf-8"))
        if args.accumulation:
            acc = json.loads(args.accumulation.read_text(encoding="utf-8"))
            # The scorer bundle keeps the profile hash in its manifest;
            # report_service computes it directly when it runs the scorer.
            manifest = args.accumulation.with_name("manifest.json")
            if not acc.get("profile_sha256") and manifest.exists():
                acc["profile_sha256"] = json.loads(
                    manifest.read_text(encoding="utf-8")).get("profile_sha256")
            report["accumulation"] = acc
        dto = sanitize_report(report)
        dest = args.out / f"public-{src.name}"
        dest.write_text(json.dumps(dto, ensure_ascii=False, indent=1),
                        encoding="utf-8")
        print(f"{dest} ({dest.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
