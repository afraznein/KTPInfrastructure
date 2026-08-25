#!/usr/bin/env python3
"""Build one public, reviewable match-report bundle from local artifacts."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import metric_confidence  # noqa: E402


SCHEMA_VERSION = 1
FORBIDDEN_KEY_TOKENS = {
    "playerid", "steamid", "killerid", "victimid", "attackerid",
    "assisterid", "posx", "posy", "posz", "posvictimx", "posvictimy",
    "posvictimz", "heatmapcells", "individualheatmap", "playerroute",
}


def read_json(path: Path | None) -> dict[str, Any] | None:
    if path is None:
        return None
    return json.loads(path.read_text(encoding="utf-8-sig"))


def privacy_violations(value: Any, path="report") -> list[str]:
    violations: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            token = re.sub(r"[^a-z0-9]", "", str(key).lower())
            if token in FORBIDDEN_KEY_TOKENS:
                violations.append(f"{path}.{key}")
            violations.extend(privacy_violations(nested, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            violations.extend(privacy_violations(nested, f"{path}[{index}]"))
    return violations


def number(value: Any, default=0.0) -> float:
    if value in (None, ""):
        return default
    return float(value)


def integer(value: Any, default=0) -> int:
    if value in (None, ""):
        return default
    return int(value)


def join_status(readiness: dict[str, Any], analytics: dict[str, Any]) -> str:
    levels = [
        readiness.get("status", "FAIL"),
        (analytics.get("quality") or {}).get("status", "FAIL"),
    ]
    severity = {"PASS": 0, "WARN": 1, "FAIL": 2}
    return max(levels, key=lambda level: severity.get(level, 2))


def accumulation_index(accumulation: dict[str, Any] | None) -> dict[tuple[str, str], dict[str, Any]]:
    result: dict[tuple[str, str], dict[str, Any]] = {}
    if not accumulation:
        return result
    for player in accumulation.get("players", []):
        key = (str(player.get("team_name") or ""), str(player.get("player_name_at_match") or ""))
        if key in result:
            raise ValueError(f"ambiguous accumulation player key: {key}")
        result[key] = player
    return result


def public_players(analytics: dict[str, Any], accumulation: dict[str, Any] | None,
                   confidence_config: dict[str, Any]) -> list[dict[str, Any]]:
    synthetic = str(analytics["match_id"]).endswith("-TEST")
    accumulation_players = accumulation_index(accumulation)
    result = []
    for source in analytics.get("players", []):
        name = str(source.get("player_name_at_match") or "Unknown")
        team = str(source.get("team_name") or "Unknown")
        accumulated = accumulation_players.get((team, name), {})
        deaths = integer(source.get("deaths"))
        damage = integer(source.get("damage_dealt"))
        damage_per_life = source.get("damage_per_life")
        if damage_per_life is None and deaths:
            damage_per_life = round(damage / deaths, 2)
        player = {
            "name": name,
            "team": team,
            "kills": integer(source.get("kills")),
            "deaths": deaths,
            "assists": integer(source.get("assists")),
            "headshots": integer(source.get("headshots")),
            "damage_dealt": damage,
            "damage_taken": source.get("damage_taken"),
            "damage_differential": source.get("damage_differential"),
            "damage_per_minute": source.get("damage_per_minute"),
            "damage_per_life": damage_per_life,
            "capture_credits": integer(source.get("capture_credits")),
            "cap_breaks": integer(source.get("cap_breaks")),
            "shots": integer(source.get("shots")),
            "hits": integer(source.get("hits")),
            "raw_accuracy": source.get("raw_accuracy"),
            "position_points": accumulated.get("position_points"),
            "total_shadow_points": accumulated.get("total_points"),
        }
        confidence_source = dict(source)
        confidence_source["damage_per_life"] = damage_per_life
        player["confidence"] = {
            "counts": metric_confidence.exact_fact(available=True, synthetic=synthetic),
            "damage_per_minute": metric_confidence.player_rate(
                "damage_per_minute", confidence_source, synthetic=synthetic,
                config=confidence_config,
            ),
            "damage_per_life": metric_confidence.player_rate(
                "damage_per_life", confidence_source, synthetic=synthetic,
                config=confidence_config,
            ),
            "headshot_rate": metric_confidence.player_rate(
                "headshot_rate", confidence_source, synthetic=synthetic,
                config=confidence_config,
            ),
            "raw_accuracy": metric_confidence.player_rate(
                "raw_accuracy", confidence_source, synthetic=synthetic,
                config=confidence_config,
            ),
            "position_points": metric_confidence.position_points(
                available=player["position_points"] is not None
            ),
        }
        result.append(player)
    return result


def public_teams(analytics: dict[str, Any], synthetic: bool) -> list[dict[str, Any]]:
    fields = (
        "team_name", "players", "kills", "deaths", "assists",
        "damage_dealt", "damage_taken", "damage_differential",
        "capture_credits", "cap_breaks", "shots", "hits", "raw_accuracy",
    )
    rows = []
    for source in analytics.get("teams", []):
        row = {key: source.get(key) for key in fields}
        row["confidence"] = metric_confidence.exact_fact(
            available=True, synthetic=synthetic
        )
        rows.append(row)
    return rows


def atlas_section(atlas: dict[str, Any] | None, *, synthetic: bool,
                  link_prefix: str, confidence_config: dict[str, Any]) -> dict[str, Any]:
    if not atlas:
        return {
            "available": False,
            "confidence": metric_confidence.label(
                "unavailable", "No atlas metadata was supplied.",
                source_complete=False, publishable=False,
            ),
            "images": [],
        }
    summary = dict(atlas.get("summary") or {})
    match_count = integer(summary.get("matches"))
    features = {}
    for key in (
        "trade_kills", "fast_multikill_frags", "isolated_deaths",
        "capture_events", "cap_breaks", "reconstructed_capouts",
    ):
        count = integer(summary.get(key))
        features[key] = {
            "count": count,
            "confidence": metric_confidence.sequence_metric(
                count, match_count, synthetic=synthetic, config=confidence_config
            ),
        }
    images = [
        {
            "file": f"{link_prefix.rstrip('/')}/{image['file']}",
            "category": image.get("category"),
            "title": image.get("title"),
        }
        for image in atlas.get("images", [])
    ]
    return {
        "available": True,
        "map": atlas.get("map"),
        "match_count": match_count,
        "coordinate_frag_coverage": {
            "coordinate": integer(summary.get("target_coordinate_frags")),
            "total": integer(summary.get("target_raw_frags")),
        },
        "features": features,
        "confidence": metric_confidence.baseline(
            match_count, synthetic=synthetic, config=confidence_config
        ),
        "contact_sheet": f"{link_prefix.rstrip('/')}/{atlas.get('contact_sheet')}"
        if atlas.get("contact_sheet") else None,
        "images": images,
    }


def build_bundle(analytics: dict[str, Any], readiness: dict[str, Any],
                 accumulation: dict[str, Any] | None = None,
                 atlas: dict[str, Any] | None = None,
                 *, atlas_link_prefix="spatial",
                 confidence_config: dict[str, Any] | None = None) -> dict[str, Any]:
    confidence_config = confidence_config or metric_confidence.load_config()
    match_id = str(analytics.get("match_id") or "")
    if readiness.get("match_id") != match_id:
        raise ValueError("analytics and readiness match IDs differ")
    if accumulation and accumulation.get("match_id") != match_id:
        raise ValueError("analytics and accumulation match IDs differ")
    if atlas:
        if not atlas.get("target_match_id"):
            raise ValueError("atlas metadata has no target_match_id")
        if atlas.get("target_match_id") != match_id:
            raise ValueError("analytics and atlas target match IDs differ")
        if atlas.get("map") != (analytics.get("match") or {}).get("map_name"):
            raise ValueError("analytics and atlas maps differ")
    synthetic = match_id.endswith("-TEST") or bool((analytics.get("match") or {}).get("is_test_match"))
    match = analytics.get("match") or {}
    report = {
        "schema_version": SCHEMA_VERSION,
        "metric_contract_version": confidence_config["contract_version"],
        "match": {
            "match_id": match_id,
            "map_name": match.get("map_name"),
            "halves_played": match.get("halves_played"),
            "duration_seconds": match.get("duration_seconds"),
            "synthetic": synthetic,
        },
        "status": join_status(readiness, analytics),
        "privacy": (
            "Player box-score facts and aggregate spatial products only; no Steam IDs, "
            "database player IDs, individual coordinates, heatmaps, or routes."
        ),
        "source_versions": {
            "analytics_schema": analytics.get("schema_version"),
            "readiness_schema": readiness.get("schema_version"),
            "atlas_schema": atlas.get("schema_version") if atlas else None,
            "accumulation_schema": accumulation.get("schema_version") if accumulation else None,
        },
        "quality": {
            "readiness_status": readiness.get("status"),
            "analytics_status": (analytics.get("quality") or {}).get("status"),
            "findings": [
                {key: check.get(key) for key in ("level", "code", "message")}
                for check in readiness.get("checks", [])
                if check.get("level") != "PASS"
            ],
        },
        "interpretation": metric_confidence.exact_fact(
            available=True, synthetic=synthetic
        ),
        "teams": public_teams(analytics, synthetic),
        "players": public_players(analytics, accumulation, confidence_config),
        "spatial": atlas_section(
            atlas, synthetic=synthetic, link_prefix=atlas_link_prefix,
            confidence_config=confidence_config,
        ),
    }
    violations = privacy_violations(report)
    if violations:
        raise AssertionError(f"public bundle contains private fields: {violations}")
    return report


def md(value: Any) -> str:
    if value is None:
        return "n/a"
    return str(value).replace("|", "\\|").replace("\n", " ")


def render_markdown(report: dict[str, Any]) -> str:
    match = report["match"]
    out = [
        f"# Match report - {match['match_id']}", "",
        f"**Review status:** {report['status']}  ",
        f"**Map:** `{md(match.get('map_name'))}`  ",
        f"**Duration:** {md(match.get('duration_seconds'))} seconds  ",
        f"**Metric contract:** v{report['metric_contract_version']}  ",
        f"**Interpretation:** {report['interpretation']['level']} - {report['interpretation']['reason']}", "",
        "> This report contains player box-score facts and aggregate spatial products. "
        "It contains no Steam IDs, database player IDs, individual coordinates, heatmaps, or routes.", "",
        "## Data quality", "",
    ]
    findings = report["quality"]["findings"]
    if findings:
        out += ["| Result | Check | Explanation |", "|---|---|---|"]
        out.extend(
            f"| {item['level']} | `{item['code']}` | {md(item['message'])} |"
            for item in findings
        )
    else:
        out.append("All configured source-quality checks passed.")

    out += [
        "", "## Team summary", "",
        "| Team | Players | K | D | A | Damage | Taken | +/- | Caps | Breaks | Raw acc. |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for team in report["teams"]:
        out.append(
            f"| {md(team.get('team_name'))} | {md(team.get('players'))} | "
            f"{md(team.get('kills'))} | {md(team.get('deaths'))} | {md(team.get('assists'))} | "
            f"{md(team.get('damage_dealt'))} | {md(team.get('damage_taken'))} | "
            f"{md(team.get('damage_differential'))} | {md(team.get('capture_credits'))} | "
            f"{md(team.get('cap_breaks'))} | {md(team.get('raw_accuracy'))} |"
        )

    out += [
        "", "## Player box score", "",
        "| Player | Team | K | D | A | Damage | Dmg/min | Dmg/life | Caps | Breaks | Position* | Total shadow* |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for player in report["players"]:
        out.append(
            f"| {md(player['name'])} | {md(player['team'])} | {player['kills']} | {player['deaths']} | "
            f"{player['assists']} | {player['damage_dealt']} | {md(player['damage_per_minute'])} | "
            f"{md(player['damage_per_life'])} | {player['capture_credits']} | {player['cap_breaks']} | "
            f"{md(player['position_points'])} | {md(player['total_shadow_points'])} |"
        )
    out += [
        "", "`*` Position and total accumulation points are shadow-only experimental values, not KTPR.",
        "Raw accuracy remains descriptive only because weapon mechanics, especially Garand chamber clearing, bias it.",
        "", "### Player rate confidence", "",
        "| Player | Dmg/min | Dmg/life | Headshot rate | Raw accuracy | Position |",
        "|---|---|---|---|---|---|",
    ]
    for player in report["players"]:
        confidence = player["confidence"]
        out.append(
            f"| {md(player['name'])} | {confidence['damage_per_minute']['level']} | "
            f"{confidence['damage_per_life']['level']} | {confidence['headshot_rate']['level']} | "
            f"{confidence['raw_accuracy']['level']} | {confidence['position_points']['level']} |"
        )

    spatial = report["spatial"]
    out += ["", "## Match patterns and spatial report", ""]
    if not spatial["available"]:
        out.append("Spatial atlas unavailable.")
    else:
        out += [
            f"Baseline confidence: **{spatial['confidence']['level']}** - {spatial['confidence']['reason']}", "",
            f"[Open the complete spatial contact sheet]({spatial['contact_sheet']})", "",
            "| Feature | Count | Confidence |", "|---|---:|---|",
        ]
        for name, feature in spatial["features"].items():
            out.append(
                f"| `{name}` | {feature['count']} | {feature['confidence']['level']} |"
            )
        out += ["", "### Spatial image index", ""]
        for image in spatial["images"]:
            out.append(f"- [{image['title']}]({image['file']}) - {image['category']}")

    out += [
        "", "## Confidence interpretation", "",
        "- `synthetic`: the calculation and capture path are testable, but bot behavior is not competitive evidence.",
        "- `low_sample`: a real observation exists but its denominator is below the v1 display threshold.",
        "- `descriptive`: suitable for describing this match, not for population-level ranking.",
        "- `emerging`, `reviewable`, and `established`: baseline maturity levels based on human match count.",
        "- `shadow_only`: experimental output that must not be presented as KTPR.", "",
    ]
    return "\n".join(out)


def copy_atlas(atlas_metadata: Path, output_dir: Path) -> str:
    source_dir = atlas_metadata.parent
    destination = output_dir / "spatial"
    destination.mkdir(parents=True, exist_ok=True)
    metadata = read_json(atlas_metadata) or {}
    names = [image["file"] for image in metadata.get("images", [])]
    names += [name for name in (metadata.get("contact_sheet"), "README.md", "atlas-metadata.json") if name]
    for name in names:
        source = source_dir / name
        if not source.is_file():
            raise FileNotFoundError(f"atlas artifact missing: {source}")
        shutil.copy2(source, destination / name)
    return "spatial"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analytics-json", required=True, type=Path)
    parser.add_argument("--readiness-json", required=True, type=Path)
    parser.add_argument("--accumulation-json", type=Path)
    parser.add_argument("--atlas-metadata", type=Path)
    parser.add_argument("--atlas-link-prefix")
    parser.add_argument("--copy-atlas", action="store_true")
    parser.add_argument("--confidence-config", type=Path, default=metric_confidence.DEFAULT_CONFIG)
    parser.add_argument("--output-dir", type=Path, default=Path("build/match-report"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    analytics = read_json(args.analytics_json) or {}
    readiness = read_json(args.readiness_json) or {}
    accumulation = read_json(args.accumulation_json)
    atlas = read_json(args.atlas_metadata)
    if args.copy_atlas:
        if args.atlas_metadata is None:
            raise ValueError("--copy-atlas requires --atlas-metadata")
        link_prefix = copy_atlas(args.atlas_metadata, args.output_dir)
    elif args.atlas_link_prefix:
        link_prefix = args.atlas_link_prefix.replace("\\", "/")
    elif args.atlas_metadata:
        link_prefix = os.path.relpath(
            args.atlas_metadata.parent, args.output_dir
        ).replace("\\", "/")
    else:
        link_prefix = "spatial"
    report = build_bundle(
        analytics, readiness, accumulation, atlas,
        atlas_link_prefix=link_prefix,
        confidence_config=metric_confidence.load_config(args.confidence_config),
    )
    json_path = args.output_dir / "match-report.json"
    markdown_path = args.output_dir / "MATCH_REPORT.md"
    json_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    print(f"Match report bundle: {report['status']}")
    print(f"  Markdown: {markdown_path}")
    print(f"  JSON: {json_path}")
    return int(report["status"] == "FAIL")


if __name__ == "__main__":
    raise SystemExit(main())
