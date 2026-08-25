#!/usr/bin/env python3
"""Build and render a deterministic, team-only accumulated-points timeline."""

from __future__ import annotations

import math
from collections import defaultdict
from html import escape
from typing import Any, Iterable


BIN_SECONDS = 15.0
ROUND_DIGITS = 4
CONSERVATION_TOLERANCE = 0.05
def _f(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed):
        raise ValueError(f"points timeline rejects non-finite numeric value {value!r}")
    return parsed


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _r(value: float) -> float:
    return round(value, ROUND_DIGITS) or 0.0


def _unknown_keys(value: Any, allowed: set[str], path: str) -> list[str]:
    if not isinstance(value, dict):
        return [f"{path}: expected object"]
    return [f"{path}.{key}" for key in value if key not in allowed]


def _finite_number(value: Any, path: str) -> list[str]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return [f"{path}: expected number"]
    return [] if math.isfinite(float(value)) else [f"{path}: non-finite number"]


def privacy_violations(value: Any, location: str = "points_timeline") -> list[str]:
    """Validate the complete versioned public schema; unknown fields fail."""
    errors = _unknown_keys(value, {
        "schema_version", "match_id", "bin_seconds", "teams", "momentum_sign",
        "privacy", "components", "halves", "annotations", "conservation",
    }, location)
    if errors or not isinstance(value, dict):
        return errors
    if value.get("schema_version") != 1:
        errors.append(f"{location}.schema_version: expected 1")
    if not isinstance(value.get("match_id"), str):
        errors.append(f"{location}.match_id: expected string")
    errors += _finite_number(value.get("bin_seconds"), f"{location}.bin_seconds")
    teams = value.get("teams")
    if (not isinstance(teams, list) or len(teams) != 2
            or any(isinstance(team, bool) or not isinstance(team, int) for team in teams)):
        errors.append(f"{location}.teams: expected two integer team identities")
        teams = []
    components = value.get("components")
    if (not isinstance(components, list) or not components
            or any(not isinstance(component, str) for component in components)):
        errors.append(f"{location}.components: expected non-empty string list")
        components = []
    sign = value.get("momentum_sign")
    errors += _unknown_keys(sign, {"positive_team", "negative_team"}, f"{location}.momentum_sign")
    if isinstance(sign, dict) and teams and sign != {
        "positive_team": teams[0], "negative_team": teams[1]
    }:
        errors.append(f"{location}.momentum_sign: identities must match declared teams")
    privacy = value.get("privacy")
    errors += _unknown_keys(
        privacy, {"scope", "individual_timing", "spatial_detail", "life_position_points",
                  "deferred_position_timing"},
        f"{location}.privacy",
    )
    expected_privacy = {
        "scope": "team_only", "individual_timing": "not_exported",
        "spatial_detail": "not_exported",
        "life_position_points": "aggregated_to_team_before_timeline",
        "deferred_position_timing": "end_of_half_reconciliation_not_earning_time",
    }
    if isinstance(privacy, dict) and privacy != expected_privacy:
        errors.append(f"{location}.privacy: contract values changed")
    halves = value.get("halves")
    if not isinstance(halves, list):
        errors.append(f"{location}.halves: expected list")
        halves = []
    for half_index, half in enumerate(halves):
        half_path = f"{location}.halves[{half_index}]"
        errors += _unknown_keys(half, {"half", "bins"}, half_path)
        if not isinstance(half, dict):
            continue
        if not isinstance(half.get("half"), int):
            errors.append(f"{half_path}.half: expected integer")
        bins = half.get("bins")
        if not isinstance(bins, list):
            errors.append(f"{half_path}.bins: expected list")
            continue
        for bin_index, row in enumerate(bins):
            bin_path = f"{half_path}.bins[{bin_index}]"
            errors += _unknown_keys(row, {
                "start_time", "end_time", "teams", "point_gain_differential",
                "momentum", "momentum_change",
            }, bin_path)
            if not isinstance(row, dict):
                continue
            for key in ("start_time", "end_time", "point_gain_differential",
                        "momentum", "momentum_change"):
                errors += _finite_number(row.get(key), f"{bin_path}.{key}")
            team_rows = row.get("teams")
            if not isinstance(team_rows, dict) or set(team_rows) != {str(team) for team in teams}:
                errors.append(f"{bin_path}.teams: keys must match declared teams")
                continue
            for team, team_row in team_rows.items():
                team_path = f"{bin_path}.teams.{team}"
                errors += _unknown_keys(
                    team_row, {"points_gained", "cumulative_points", "components",
                               "deferred_position_points"},
                    team_path,
                )
                if not isinstance(team_row, dict):
                    continue
                errors += _finite_number(team_row.get("points_gained"), f"{team_path}.points_gained")
                errors += _finite_number(team_row.get("cumulative_points"), f"{team_path}.cumulative_points")
                errors += _finite_number(
                    team_row.get("deferred_position_points"),
                    f"{team_path}.deferred_position_points",
                )
                component_rows = team_row.get("components")
                if not isinstance(component_rows, dict) or set(component_rows) != set(components):
                    errors.append(f"{team_path}.components: keys must match declared components")
                else:
                    for component, number in component_rows.items():
                        errors += _finite_number(number, f"{team_path}.components.{component}")
    annotations = value.get("annotations")
    if not isinstance(annotations, list):
        errors.append(f"{location}.annotations: expected list")
        annotations = []
    for index, row in enumerate(annotations):
        path = f"{location}.annotations[{index}]"
        errors += _unknown_keys(row, {"half", "time", "team", "kind", "label"}, path)
        if not isinstance(row, dict):
            continue
        if not isinstance(row.get("half"), int) or row.get("team") not in teams:
            errors.append(f"{path}: invalid half/team")
        errors += _finite_number(row.get("time"), f"{path}.time")
        if not isinstance(row.get("kind"), str) or not isinstance(row.get("label"), str):
            errors.append(f"{path}: kind/label must be strings")
    conservation = value.get("conservation")
    errors += _unknown_keys(conservation, {
        "report_match_total_points", "timeline_match_total_points", "difference",
        "tolerance", "component_totals",
    }, f"{location}.conservation")
    if isinstance(conservation, dict):
        for key in ("report_match_total_points", "timeline_match_total_points",
                    "difference", "tolerance"):
            errors += _finite_number(conservation.get(key), f"{location}.conservation.{key}")
        totals = conservation.get("component_totals")
        if not isinstance(totals, dict) or set(totals) != set(components):
            errors.append(f"{location}.conservation.component_totals: keys must match components")
        else:
            for component, row in totals.items():
                path = f"{location}.conservation.component_totals.{component}"
                errors += _unknown_keys(row, {"report", "timeline", "difference"}, path)
                if isinstance(row, dict):
                    for key in ("report", "timeline", "difference"):
                        errors += _finite_number(row.get(key), f"{path}.{key}")
    return errors


def _closed_end_bin_index(when: float, bin_seconds: float) -> int:
    """Map t=0 to bin 0 and an exact boundary to the bin ending there."""
    return 0 if when <= 0 else max(0, math.ceil(when / bin_seconds) - 1)


def _team_sources(
    components: Iterable[str], player_rows: list[dict[str, Any]],
    player_teams: dict[int, int],
    contribution_sources: dict[tuple[int, str], list[dict[str, Any]]],
    team_position_contributions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Scale source weights to the scorer's final rounded component awards.

    Player identity exists only while event awards are reconciled. Rows are
    immediately collapsed to team/time/component before this helper returns.
    Positional timing enters only through the already team-aggregated input.
    """
    component_names = tuple(components)
    aggregate: dict[tuple[int, float, int, str, bool], float] = defaultdict(float)
    team_targets: dict[tuple[int, str], float] = defaultdict(float)
    for row in player_rows:
        player_id = _i(row.get("player_id"))
        team = player_teams.get(player_id, 0)
        if team <= 0:
            continue
        for component in component_names:
            team_targets[(team, component)] += max(0.0, _f(row.get(component)))
            if component == "position_points":
                continue
            target = max(0.0, _f(row.get(component)))
            if target <= 0:
                continue
            sources = [
                source for source in contribution_sources.get((player_id, component), [])
                if _f(source.get("points")) > 0
            ]
            source_total = sum(_f(source.get("points")) for source in sources)
            if not sources or source_total <= 0:
                aggregate[(1, 0.0, team, component, False)] += target
                continue
            scale = target / source_total
            for source in sources:
                aggregate[(
                    max(1, _i(source.get("half"), 1)),
                    max(0.0, _f(source.get("time"))), team, component, False,
                )] += _f(source.get("points")) * scale

    position_by_team: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for row in team_position_contributions:
        team = _i(row.get("team"))
        if team > 0 and _f(row.get("points")) > 0:
            position_by_team[team].append(row)
    for (team, component), target in sorted(team_targets.items()):
        if component != "position_points" or target <= 0:
            continue
        sources = position_by_team.get(team, [])
        source_total = sum(_f(source.get("points")) for source in sources)
        if not sources or source_total <= 0:
            aggregate[(1, 0.0, team, component, True)] += target
            continue
        scale = target / source_total
        for source in sources:
            aggregate[(
                max(1, _i(source.get("half"), 1)),
                max(0.0, _f(source.get("bin_end", source.get("time")))),
                team, component,
                source.get("timing") == "privacy_deferred_reconciliation",
            )] += _f(source.get("points")) * scale

    return [
        {"half": half, "time": when, "team": team,
         "component": component, "points": points, "privacy_deferred": deferred}
        for (half, when, team, component, deferred), points in sorted(aggregate.items())
        if points > 0
    ]


def _momentum_at(rows: list[dict[str, Any]], when: float) -> float:
    value = 0.0
    for row in rows:
        if _f(row.get("time")) > when + 1e-9:
            break
        value = _f(row.get("momentum"))
    return value


def build_points_timeline(
    *, match_id: str, components: Iterable[str], component_totals: dict[str, Any],
    match_total_points: float, player_rows: list[dict[str, Any]],
    player_teams: dict[int, int],
    contribution_sources: dict[tuple[int, str], list[dict[str, Any]]],
    team_position_contributions: list[dict[str, Any]],
    momentum: dict[str, Any], annotations: list[dict[str, Any]],
    bin_seconds: float = BIN_SECONDS,
) -> dict[str, Any]:
    """Return aligned points-gain, cumulative-points, and momentum panels."""
    if bin_seconds <= 0:
        raise ValueError("points timeline requires a positive bin size")
    component_names = tuple(components)
    teams = sorted({
        *(_i(value) for value in player_teams.values() if _i(value) > 0),
        _i(momentum.get("team1")), _i(momentum.get("team2")),
    } - {0})
    if len(teams) != 2:
        raise ValueError("points timeline requires exactly two stable teams")
    team1, team2 = teams
    ledger = _team_sources(
        component_names, player_rows, player_teams, contribution_sources,
        team_position_contributions,
    )
    clean_annotations = [
        {
            "half": max(1, _i(row.get("half"), 1)),
            "time": _r(max(0.0, _f(row.get("time")))),
            "team": _i(row.get("team")),
            "kind": str(row.get("kind") or "event"),
            "label": str(row.get("label") or "Team event"),
        }
        for row in annotations if _i(row.get("team")) in teams
    ]
    clean_annotations.sort(key=lambda row: (
        row["half"], row["time"], row["team"], row["kind"], row["label"]
    ))
    curve = sorted(
        (dict(row) for row in (momentum.get("curve") or [])),
        key=lambda row: (_i(row.get("half")), _f(row.get("time"))),
    )
    curve_end_by_half: dict[int, float] = defaultdict(lambda: bin_seconds)
    for row in curve:
        half = max(1, _i(row.get("half"), 1))
        curve_end_by_half[half] = max(curve_end_by_half[half], _f(row.get("time")))
    for row in ledger:
        if not row.get("privacy_deferred"):
            continue
        if _f(row.get("time")) <= 0:
            row["time"] = curve_end_by_half[row["half"]]
        clean_annotations.append({
            "half": row["half"], "time": _r(row["time"]), "team": row["team"],
            "kind": "privacy_deferred_position_reconciliation",
            "label": (
                f"Team {row['team']} deferred positional reconciliation "
                "(timing withheld)"
            ),
        })
    clean_annotations.sort(key=lambda row: (
        row["half"], row["time"], row["team"], row["kind"], row["label"]
    ))
    halves = sorted({
        *(_i(row.get("half")) for row in ledger),
        *(_i(row.get("half")) for row in curve),
        *(_i(row.get("half")) for row in clean_annotations),
    } - {0}) or [1]
    cumulative = {team: 0.0 for team in teams}
    output_halves: list[dict[str, Any]] = []
    bin_component_totals: dict[str, float] = defaultdict(float)
    for half in halves:
        half_ledger = [row for row in ledger if row["half"] == half]
        half_curve = [row for row in curve if _i(row.get("half")) == half]
        half_annotations = [row for row in clean_annotations if row["half"] == half]
        max_time = max([
            *(_f(row.get("time")) for row in half_ledger),
            *(_f(row.get("time")) for row in half_curve),
            *(_f(row.get("time")) for row in half_annotations),
            bin_seconds,
        ])
        bin_count = max(1, math.ceil(max_time / bin_seconds))
        bucketed: dict[tuple[int, int, str], float] = defaultdict(float)
        deferred_bucketed: dict[tuple[int, int], float] = defaultdict(float)
        for row in half_ledger:
            index = min(_closed_end_bin_index(_f(row["time"]), bin_seconds), bin_count - 1)
            bucketed[(index, _i(row["team"]), str(row["component"]))] += _f(row["points"])
            if row.get("privacy_deferred"):
                deferred_bucketed[(index, _i(row["team"]))] += _f(row["points"])
        bins = []
        for index in range(bin_count):
            start, end = index * bin_seconds, (index + 1) * bin_seconds
            team_rows: dict[str, Any] = {}
            for team in teams:
                values = {
                    component: bucketed[(index, team, component)]
                    for component in component_names
                }
                gain = sum(values.values())
                cumulative[team] += gain
                for component, value in values.items():
                    bin_component_totals[component] += value
                team_rows[str(team)] = {
                    "points_gained": _r(gain),
                    "cumulative_points": _r(cumulative[team]),
                    "deferred_position_points": _r(deferred_bucketed[(index, team)]),
                    "components": {key: _r(value) for key, value in values.items()},
                }
            momentum_start = _momentum_at(half_curve, start)
            momentum_end = _momentum_at(half_curve, end)
            bins.append({
                "start_time": _r(start), "end_time": _r(end),
                "teams": team_rows,
                "point_gain_differential": _r(
                    team_rows[str(team1)]["points_gained"]
                    - team_rows[str(team2)]["points_gained"]
                ),
                "momentum": _r(momentum_end),
                "momentum_change": _r(momentum_end - momentum_start),
            })
        output_halves.append({"half": half, "bins": bins})

    timeline_total = sum(cumulative.values())
    result = {
        "schema_version": 1,
        "match_id": match_id,
        "bin_seconds": _r(bin_seconds),
        "teams": teams,
        "momentum_sign": {"positive_team": team1, "negative_team": team2},
        "privacy": {
            "scope": "team_only",
            "individual_timing": "not_exported",
            "spatial_detail": "not_exported",
            "life_position_points": "aggregated_to_team_before_timeline",
            "deferred_position_timing": "end_of_half_reconciliation_not_earning_time",
        },
        "components": list(component_names),
        "halves": output_halves,
        "annotations": clean_annotations,
        "conservation": {
            "report_match_total_points": _r(match_total_points),
            "timeline_match_total_points": _r(timeline_total),
            "difference": _r(timeline_total - match_total_points),
            "tolerance": CONSERVATION_TOLERANCE,
            "component_totals": {
                component: {
                    "report": _r(_f(component_totals.get(component))),
                    "timeline": _r(bin_component_totals[component]),
                    "difference": _r(
                        bin_component_totals[component]
                        - _f(component_totals.get(component))
                    ),
                }
                for component in component_names
            },
        },
    }
    violations = privacy_violations(result)
    if violations:
        raise ValueError("points timeline privacy violation: " + ", ".join(violations[:10]))
    return result


def render_points_timeline_svg(timeline: dict[str, Any]) -> str:
    """Render three aligned team-only panels from the sanitized 15s bins."""
    width, height = 1260, 920
    left, right, top = 85.0, 35.0, 85.0
    panel_h, gap = 210.0, 62.0
    plot_w = width - left - right
    halves = timeline.get("halves") or []
    teams = [_i(value) for value in timeline.get("teams") or []]
    colors = {teams[0]: "#38bdf8", teams[1]: "#fb7185"} if len(teams) == 2 else {}
    half_width = plot_w / max(len(halves), 1)
    all_bins = [row for half in halves for row in half.get("bins") or []]
    max_cumulative = max((
        _f(team_row.get("cumulative_points"))
        for row in all_bins for team_row in (row.get("teams") or {}).values()
    ), default=1.0) or 1.0
    max_gain = max((
        _f(team_row.get("points_gained"))
        for row in all_bins for team_row in (row.get("teams") or {}).values()
    ), default=1.0) or 1.0

    def x_for(half_index: int, half: dict[str, Any], when: float) -> float:
        bins = half.get("bins") or []
        maximum = max((_f(row.get("end_time")) for row in bins), default=1.0) or 1.0
        return left + half_index * half_width + min(max(when / maximum, 0.0), 1.0) * half_width

    paths = []
    for panel, maximum, field in ((0, max_cumulative, "cumulative_points"),
                                   (1, max_gain, "points_gained")):
        y0 = top + panel * (panel_h + gap)
        for half_index, half in enumerate(halves):
            bins = half.get("bins") or []
            for team in teams:
                points = []
                for row in bins:
                    value = _f((row.get("teams") or {}).get(str(team), {}).get(field))
                    x = x_for(half_index, half, _f(row.get("end_time")))
                    y = y0 + panel_h - (value / maximum) * panel_h
                    points.append(f"{x:.1f},{y:.1f}")
                if points:
                    paths.append(
                        f'<polyline points="{" ".join(points)}" fill="none" '
                        f'stroke="{colors.get(team, "#ddd")}" stroke-width="3"/>'
                    )
    momentum_y = top + 2 * (panel_h + gap)
    for half_index, half in enumerate(halves):
        points = []
        for row in half.get("bins") or []:
            x = x_for(half_index, half, _f(row.get("end_time")))
            y = momentum_y + (100.0 - _f(row.get("momentum"))) / 200.0 * panel_h
            points.append(f"{x:.1f},{y:.1f}")
        if points:
            paths.append(
                f'<polyline points="{" ".join(points)}" fill="none" '
                'stroke="#f8fafc" stroke-width="3"/>'
            )
    dividers, labels = [], []
    for index, half in enumerate(halves):
        labels.append(
            f'<text x="{left + (index + .5) * half_width:.1f}" y="{height - 24}" '
            f'class="axis" text-anchor="middle">Half {_i(half.get("half"))}</text>'
        )
        if index:
            x = left + index * half_width
            dividers.append(
                f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" '
                f'y2="{momentum_y + panel_h}" stroke="#64748b" stroke-dasharray="7 7"/>'
            )
    annotation_marks = []
    by_half = {_i(row.get("half")): (index, row) for index, row in enumerate(halves)}
    for event in timeline.get("annotations") or []:
        located = by_half.get(_i(event.get("half")))
        if located is None:
            continue
        index, half = located
        x = x_for(index, half, _f(event.get("time")))
        annotation_marks.append(
            f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" '
            f'y2="{momentum_y + panel_h}" stroke="#fbbf24" opacity=".22">'
            f'<title>{escape(str(event.get("label")))}</title></line>'
        )
    title = escape(str(timeline.get("match_id") or "match"))
    team_legend = " · ".join(
        f'<tspan fill="{colors.get(team, "#ddd")}">Team {team}</tspan>' for team in teams
    )
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<style>.title{{font:700 24px system-ui;fill:#f8fafc}}.panel{{font:700 16px system-ui;fill:#e2e8f0}}.axis{{font:13px system-ui;fill:#cbd5e1}}.small{{font:12px system-ui;fill:#94a3b8}}</style>
<rect width="100%" height="100%" fill="#0f172a"/>
<text x="{left}" y="36" class="title">Accumulated points over time — {title}</text>
<text x="{left}" y="58" class="small">15-second team-only windows · {team_legend} · gold guides are team events</text>
<text x="{left}" y="75" class="small">Deferred positional points appear only at end-of-half reconciliation; that placement is not their earning time.</text>
<text x="{left}" y="{top - 12}" class="panel">Cumulative raw team points</text>
<text x="{left}" y="{top + panel_h + gap - 12}" class="panel">Raw points gained per window</text>
<text x="{left}" y="{momentum_y - 12}" class="panel">Public team momentum (signed)</text>
<line x1="{left}" y1="{momentum_y + panel_h/2}" x2="{left + plot_w}" y2="{momentum_y + panel_h/2}" stroke="#94a3b8"/>
{''.join(dividers)}{''.join(annotation_marks)}{''.join(paths)}{''.join(labels)}
</svg>'''
