"""Translate engine-side (Allies/Axis) team labels to report-team convention.

`ktp_match_players.team` is the roster slot a player held in the LAST half
they played (`scripts/in_game_result.py`'s own docstring: "report team 1 is
whichever stream slot played Allies in the terminal half"). Every box-score
and rating field in the internal report -- `players[].team`, `teams[].team`,
in-game result -- uses that convention. Three shadow pipelines do not:
`positional_shadow.py`'s `map_control` (from live `position_sample.team`),
`flag_swing.py`'s flag ownership (`owner_team`), and this repo's own
`progression.py` team-level series -- all fixed at engine side, 1 = Allies
/ 2 = Axis, for the whole match.

Because DoD swaps Allies/Axis at halftime, "report team 1" is GUARANTEED to
be the opposite engine side in half 1 of every two-half match. The two
conventions only agree in the terminal half. A curve or series carrying
engine-side labels under a `"team": 1/2` key that a consumer reasonably
reads as report-team convention (every other `"team"` field in the report
means that) is silently backwards in half 1 -- this was the actual bug
behind a reported "inverted momentum graph" (2026-09-20,
KTPInfrastructure workstream infra-half-side-correction).

This module is a TRANSLATION LAYER over `flag_swing.sides_by_half`, not a
second side-resolution algorithm: `report_team1_engine_side` is the only
place that decides which engine side report team 1 played each half, and
it is built directly on `sides_by_half`'s own per-(half, player) answer
plus the roster. A half `sides_by_half` cannot resolve (two sides in one
half, or no life-boundary rows at all) is a half nothing downstream can
correctly translate either -- every function here drops that half from
its output rather than guessing, matching the report's own "absence, not
zero" rule.
"""
from __future__ import annotations

from typing import Any, Sequence

from scripts.flag_swing import sides_by_half


def _int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def report_team1_engine_side(
    life_boundaries: Sequence[dict[str, Any]] | None,
    roster: Sequence[dict[str, Any]] | None,
) -> dict[int, int]:
    """half -> the engine side (1 Allies / 2 Axis) report team 1 played.

    Resolved from whichever roster members are report team 1
    (`ktp_match_players.team == 1`) and the engine side `sides_by_half`
    gives them that half. A half is present only when every such player
    agrees -- a genuine disagreement (a mid-half team swap collection could
    not see, a data defect) drops the half rather than picking a side.
    """
    report_team = {
        pid: team
        for p in roster or []
        if (pid := _int_or_none(p.get("player_id"))) is not None
        and (team := _int_or_none(p.get("team"))) in (1, 2)
    }
    out: dict[int, int] = {}
    for half, pid_sides in sides_by_half(life_boundaries).items():
        engine_sides = {
            engine_side
            for pid, engine_side in pid_sides.items()
            if report_team.get(pid) == 1
        }
        if len(engine_sides) == 1:
            out[half] = next(iter(engine_sides))
    return out


def _flip_arc_label(label: Any) -> Any:
    if label == "team1_at_arc0":
        return "team2_at_arc0"
    if label == "team2_at_arc0":
        return "team1_at_arc0"
    return label


def translate_map_control(
    map_control: dict[str, Any], team1_engine_side: dict[int, int],
) -> None:
    """Mutate `map_control` in place from engine to report-team convention.

    Each half's curve is team-1(engine)-coordinates: 1.0 = deep in engine
    team 2's end. When report team 1 played the OTHER engine side that
    half, the curve mirrors (``1 - f``) so it reads as report-team-1's
    control instead, and `orientation_by_half`'s label flips with it so the
    two stay consistent. `mean_control_team1` is recomputed from the
    (now per-half-correct) translated points -- averaging engine-Allies
    means across two halves that belong to DIFFERENT report teams was never
    a meaningful number; the translated mean is.
    """
    halves = map_control.get("halves") or {}
    orientation = map_control.get("orientation_by_half") or {}
    translated_halves: dict[str, list] = {}
    translated_orientation: dict[str, Any] = {}
    curve_values: list[float] = []
    dropped: list[int] = []
    for key, curve in halves.items():
        half = _int_or_none(key)
        engine_side = team1_engine_side.get(half) if half is not None else None
        if engine_side is None:
            dropped.append(half if half is not None else key)
            continue
        mirror = engine_side != 1
        points = [[t, (round(1.0 - f, 4) if mirror and f is not None else f)] for t, f in curve]
        translated_halves[key] = points
        curve_values.extend(v for _, v in points if v is not None)
        label = orientation.get(key)
        translated_orientation[key] = _flip_arc_label(label) if mirror else label
    map_control["halves"] = translated_halves
    map_control["orientation_by_half"] = translated_orientation
    map_control["mean_control_team1"] = (
        round(sum(curve_values) / len(curve_values), 4) if curve_values else None
    )
    if dropped:
        caveats = list(map_control.get("caveats") or [])
        caveats.append(
            "Half(s) " + ", ".join(str(h) for h in dropped)
            + " could not be resolved to a report team (no single engine "
              "side for every report-team-1 player that half) and are "
              "omitted rather than mislabeled."
        )
        map_control["caveats"] = caveats


def translate_team_series(
    rows: Sequence[dict[str, Any]], team1_engine_side: dict[int, int],
) -> tuple[list[dict[str, Any]], list[int]]:
    """Engine-side `{team, half, metric, points}` rows (`progression`'s
    team-level series shape) -> report-team convention.

    Grouped by (half, metric) because a half needs BOTH engine sides' rows
    present to know which one to hand to report team 1. Returns the
    translated rows and the halves that could not be resolved (either no
    per-half side, or the pair was incomplete) -- callers append their own
    caveat wording for the block they own.
    """
    grouped: dict[tuple[int, str], dict[int, dict[str, Any]]] = {}
    for row in rows or []:
        half, team, metric = row.get("half"), row.get("team"), row.get("metric")
        if isinstance(half, int) and team in (1, 2) and metric:
            grouped.setdefault((half, metric), {})[team] = row
    out: list[dict[str, Any]] = []
    dropped: set[int] = set()
    for (half, metric), by_team in sorted(grouped.items()):
        engine_side = team1_engine_side.get(half)
        if engine_side is None or 1 not in by_team or 2 not in by_team:
            dropped.add(half)
            continue
        other_side = 1 if engine_side == 2 else 2
        out.append({"team": 1, "half": half, "metric": metric,
                    "points": by_team[engine_side].get("points") or []})
        out.append({"team": 2, "half": half, "metric": metric,
                    "points": by_team[other_side].get("points") or []})
    return out, sorted(dropped)


def translate_objective_timeline(
    objectives: Sequence[dict[str, Any]], team1_engine_side: dict[int, int],
) -> list[dict[str, Any]]:
    """Flag-capture rows -> report-team convention, keeping the engine side.

    `sql/analytics/objective_timeline_fact.sql` maps the capture's team NAME
    onto 1 = Allies / 2 = Axis, so it is engine side. `match_timelines`
    compares it against a multikill killer's team to decide whether the kills
    were converted into an objective, and that killer's team is report-team
    convention -- so in every half the sides were swapped the comparison
    matched the OPPONENT's captures, crediting a conversion to the wrong side
    of the kill and denying it to the right one.

    `engine_side` keeps the original, so `team_name` (which names a side, not a
    team) stays readable beside it. A half with no resolvable side is dropped,
    the same rule as the other translators here.
    """
    out: list[dict[str, Any]] = []
    for row in objectives or []:
        half, team = _int_or_none(row.get("half")), _int_or_none(row.get("team"))
        engine_side = team1_engine_side.get(half) if half is not None else None
        if engine_side is None or team not in (1, 2):
            continue
        translated = dict(row)
        translated["engine_side"] = team
        translated["team"] = 1 if team == engine_side else 2
        out.append(translated)
    return out


def translate_objective_attempts(
    attempts: Sequence[dict[str, Any]], team1_engine_side: dict[int, int],
) -> list[dict[str, Any]]:
    """Capture-attempt rows -> report-team convention, keeping the engine side.

    `ktp_objective_attempt_events.capturing_team` is the engine side the
    producer saw taking the flag. `flag_fights` compares it against a frag's
    killer team and against the corrected roster -- both report-team convention
    -- so in a swapped half every window was judged against the OPPONENT: the
    opening duel's `won_by_capturing_team` inverted, the clutch winner resolved
    to the other side, and `build_entry_shadow` picked its entrant from the
    DEFENDERS. `interruptions.py` reads the same column correctly by resolving
    the frag's side from the life feed, so it keeps the untranslated feed.

    An unresolvable half keeps its row with `capturing_team` set to None rather
    than being dropped: a window is assembled from a START and its TERMINAL
    rows, so discarding one of a pair would read as an incomplete window
    instead of an untranslatable one. Every `flag_fights` consumer already
    skips a window whose `capturing_team` is not 1 or 2.
    """
    out: list[dict[str, Any]] = []
    for row in attempts or []:
        half = _int_or_none(row.get("half"))
        team = _int_or_none(row.get("capturing_team"))
        engine_side = team1_engine_side.get(half) if half is not None else None
        translated = dict(row)
        if engine_side is None or team not in (1, 2):
            translated["capturing_team"] = None
        else:
            translated["engine_side"] = team
            translated["capturing_team"] = 1 if team == engine_side else 2
        out.append(translated)
    return out


def engine_side_for_report_team(
    team: Any, half: Any, team1_engine_side: dict[int, int],
) -> int | None:
    """Report team 1/2 -> the engine side it played that half.

    The inverse of the translators above, for a consumer whose model is
    engine-side GEOMETRY rather than a team label. `positional_shadow` depth is
    side-normalized per half off `ktp_position_samples.team`, so a report team
    handed to it measures from the wrong end of the map in a swapped half.
    """
    half_i, team_i = _int_or_none(half), _int_or_none(team)
    engine_side = team1_engine_side.get(half_i) if half_i is not None else None
    if engine_side is None or team_i not in (1, 2):
        return None
    return engine_side if team_i == 1 else (1 if engine_side == 2 else 2)


def translate_recap_speed(
    recap_speed: dict[str, Any], team1_engine_side: dict[int, int],
) -> None:
    """Mutate `recap_speed` in place from engine side to report-team convention.

    `objective_control.build_recap_speed` keys every recap on
    `ktp_flag_state_events.owner_team`, the engine side that owned the flag. The
    site renders both `events[].team` and `teams[].team` as a report team, so in
    a swapped half each recap is labeled with the opponent -- and `teams[]`,
    which sums across halves BY SIDE, is a mixture of the two rosters rather
    than either one's figure.

    `teams` is therefore re-aggregated from the translated events rather than
    relabeled: summing engine-Allies across two halves that belong to different
    report teams was never a meaningful number. A half with no resolvable side
    is dropped with a caveat, same rule as the curve and series translators.
    """
    translated: list[dict[str, Any]] = []
    dropped: set[int] = set()
    for event in recap_speed.get("recaps") or []:
        half = _int_or_none(event.get("half"))
        team = _int_or_none(event.get("team"))
        engine_side = team1_engine_side.get(half) if half is not None else None
        if engine_side is None or team not in (1, 2):
            if half is not None:
                dropped.add(half)
            continue
        row = dict(event)
        row["engine_side"] = team
        row["team"] = 1 if team == engine_side else 2
        translated.append(row)
    recap_speed["recaps"] = translated
    recap_speed["team_convention"] = "report_team"

    by_team: dict[int, list[float]] = {}
    for event in translated:
        seconds = event.get("seconds")
        if seconds is not None:
            by_team.setdefault(int(event["team"]), []).append(float(seconds))
    teams: list[dict[str, Any]] = []
    for team in sorted(by_team):
        seconds = sorted(by_team[team])
        mid = len(seconds) // 2
        median = (seconds[mid] if len(seconds) % 2
                  else (seconds[mid - 1] + seconds[mid]) / 2.0)
        teams.append({
            "team": team,
            "recaps": len(seconds),
            "median_seconds": round(median, 3),
            "mean_seconds": round(sum(seconds) / len(seconds), 3),
        })
    recap_speed["teams"] = teams
    if dropped:
        caveats = list(recap_speed.get("caveats") or [])
        caveats.append(
            "Half(s) " + ", ".join(str(h) for h in sorted(dropped))
            + " could not be resolved to a report team (no single engine side "
              "for every report-team-1 player that half) and their recaps are "
              "omitted rather than mislabeled.")
        recap_speed["caveats"] = caveats


def translate_capouts(
    capouts: Sequence[dict[str, Any]], team1_engine_side: dict[int, int],
) -> list[dict[str, Any]]:
    """Engine-side `{half, game_time, team}` cap-out events -> report-team
    convention. An event whose half cannot be resolved is dropped, not
    guessed -- same rule as the curve and series translators."""
    out: list[dict[str, Any]] = []
    for row in capouts or []:
        half, team = row.get("half"), row.get("team")
        engine_side = team1_engine_side.get(half) if isinstance(half, int) else None
        if engine_side is None or team not in (1, 2):
            continue
        out.append({
            "half": half,
            "game_time": row.get("game_time"),
            "team": 1 if team == engine_side else 2,
        })
    return out
