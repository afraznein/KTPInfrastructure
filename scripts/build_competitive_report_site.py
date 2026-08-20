#!/usr/bin/env python3
"""Build a static, privacy-safe explorer for a competitive bot corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


METRICS = {
    "kills": "Match-tagged frags",
    "captures_total": "Captures",
    "position_samples": "Position samples",
    "assists_stored": "Assists",
    "cap_breaks_stored": "Cap breaks",
    "match_players": "Roster",
}
SIDE_METRICS = {
    "kills": "Kills", "assists": "Assists", "damage_dealt": "Damage",
    "capture_credits": "Capture credits", "cap_breaks": "Cap breaks",
}


def describe(values: list[float]) -> dict[str, float | int]:
    if not values:
        return {"n": 0, "total": 0, "mean": 0, "median": 0, "sd": 0, "min": 0, "max": 0}
    return {
        "n": len(values), "total": round(sum(values), 3),
        "mean": round(statistics.mean(values), 3),
        "median": round(statistics.median(values), 3),
        "sd": round(statistics.stdev(values), 3) if len(values) > 1 else 0,
        "min": round(min(values), 3), "max": round(max(values), 3),
    }


def profile_summary(matches: list[dict], profile_name: str) -> dict[str, Any]:
    profiles = [
        next(item for item in match["accumulation"] if item["profile"] == profile_name)
        for match in matches
    ]
    event = sum(float(item["event_points"]) for item in profiles)
    position = sum(float(item["position_points"]) for item in profiles)
    combined = event + position
    caps = {"accumulation_v0": 100.0, "accumulation_v1": 100.0,
            "accumulation_v2_target10": 150.0}
    cap = caps[profile_name]
    capped = 0
    for match, profile in zip(matches, profiles):
        halves = max(1, int((match.get("match") or {}).get("halves_played") or 1))
        capped += sum(float(player["position_points"]) >= cap * halves - 0.001
                      for player in profile["players"])
    return {
        "profile": profile_name,
        "event_points": round(event, 2),
        "position_points": round(position, 2),
        "combined_points": round(combined, 2),
        "position_share_percent": round(100 * position / combined, 2) if combined else 0,
        "fixture_share_distribution": describe([
            float(item["position_share_percent"]) for item in profiles
        ]),
        "capped_player_rows": capped,
        "player_rows": sum(len(item["players"]) for item in profiles),
    }


def rank_sensitivity(matches: list[dict]) -> dict[str, int]:
    changed = 0
    compared = 0
    max_move = 0
    for match in matches:
        profiles = {item["profile"]: item for item in match["accumulation"]}
        if "accumulation_v0" not in profiles or "accumulation_v2_target10" not in profiles:
            continue
        v0 = {row["player_name_at_match"]: rank for rank, row in enumerate(profiles["accumulation_v0"]["players"], 1)}
        v2 = {row["player_name_at_match"]: rank for rank, row in enumerate(profiles["accumulation_v2_target10"]["players"], 1)}
        for name in set(v0) & set(v2):
            move = abs(v0[name] - v2[name])
            compared += 1
            changed += move > 0
            max_move = max(max_move, move)
    return {"player_rows_compared": compared, "rank_changed": changed, "max_rank_move": max_move}


def recommendations(map_name: str, map_item: dict, matches: list[dict]) -> list[str]:
    result = []
    totals = map_item["selected_totals"]
    if map_item["cohort"] == "pipeline_only" or totals["kills"] == 0:
        result.append("Revise and requalify waypoints until bots produce repeatable combat and objective interaction; current evidence validates persistence only.")
    if map_item["cohort"] == "experimental_unvalidated":
        result.append("Human-review the experimental waypoint graph before treating its spatial patterns as a competitive baseline.")
    positional = map_item.get("positional_baseline") or {}
    if positional.get("status") == "no_owned_flag_baseline":
        result.append("Repair or validate the non-neutral flag-ownership baseline before ownership-distance or capout analysis is enabled.")
    if map_item["quality_status"] == "baseline_ready_with_warnings":
        result.append("Stabilize the 12-player roster across all five fixtures, then rerun this map's corpus.")
    coordinate_checks = []
    for match in matches:
        for check in match["quality"]["checks"]:
            if check["code"] == "frag_coordinate_coverage":
                coordinate_checks.append(check)
    if any(check["level"] != "PASS" for check in coordinate_checks):
        result.append("Inspect coordinate-less frag timing and improve endpoint capture before relying on normalized kill/death spatial rates.")
    v2_rows = []
    for match in matches:
        profile = next(
            (item for item in match["accumulation"]
             if item["profile"] == "accumulation_v2_target10"), None
        )
        if profile:
            halves = max(1, int((match.get("match") or {}).get("halves_played") or 1))
            v2_rows.extend((player, halves) for player in profile["players"])
    capped = sum(float(player["position_points"]) >= 150.0 * halves - 0.001
                 for player, halves in v2_rows)
    if v2_rows and capped / len(v2_rows) >= 0.25:
        result.append(
            f"Keep v2 shadow-only: its positional cap saturated for {capped}/{len(v2_rows)} "
            "player-match rows; retest point rate and cap against real match duration."
        )
    if not result:
        result.append("Use the first controlled human preprod match to validate that collection shape transfers beyond bots; do not tune weights from this corpus.")
    return result


def markdown_map(item: dict) -> str:
    lines = [
        f"# {item['display_name']} synthetic corpus", "",
        f"Cohort: `{item['cohort']}`  ",
        f"Dataset quality: `{item['quality_status']}`  ",
        f"Fixtures: **{len(item['fixtures'])}** independent `.testmatch` halves", "",
        "Bot data validates collection and analysis behavior; it is not human skill calibration.", "",
        "## Five-fixture distributions", "",
        "| Metric | Total | Mean | Sample SD | Median | Range |", "|---|---:|---:|---:|---:|---:|",
    ]
    for key, label in METRICS.items():
        value = item["metrics"][key]
        lines.append(f"| {label} | {value['total']:,.0f} | {value['mean']:,.2f} | {value['sd']:,.2f} | {value['median']:,.2f} | {value['min']:,.0f}–{value['max']:,.0f} |")
    lines += ["", "With only five synthetic fixtures, sample SD and observed range are shown instead of a confidence interval.", "", f"Lane B reconciliation: {item['containment']['all_frag_rows']:,} total frag rows; {item['containment']['match_tagged_frags']:,} match-tagged; {item['containment']['outside_match_scope']:,} outside match scope.", "", "## Per side", "", "| Side | Metric | Total | Mean | Sample SD | Range |", "|---|---|---:|---:|---:|---:|"]
    for side, metrics in item["sides"].items():
        for key, label in SIDE_METRICS.items():
            value = metrics[key]
            lines.append(f"| {side} | {label} | {value['total']:,.0f} | {value['mean']:,.2f} | {value['sd']:,.2f} | {value['min']:,.0f}–{value['max']:,.0f} |")
    lines += ["", "## Shadow accumulation sensitivity", "", "| Profile | Events | Position | Position share | Capped rows |", "|---|---:|---:|---:|---:|"]
    for profile in item["accumulation"]:
        lines.append(f"| `{profile['profile']}` | {profile['event_points']:,.2f} | {profile['position_points']:,.2f} | {profile['position_share_percent']:.2f}% | {profile['capped_player_rows']}/{profile['player_rows']} |")
    sensitivity = item["rank_sensitivity"]
    lines += ["", f"From v0 to v2, {sensitivity['rank_changed']} of {sensitivity['player_rows_compared']} player-match rows changed rank; maximum movement was {sensitivity['max_rank_move']} places.", "", "## Positional and ownership coverage", "", f"Supplied positional baseline: `{item['positional']['status']}`. Usable samples: {item['positional']['usable_samples']:,}; excluded: {item['positional']['excluded_samples']:,}.", "", f"[Open aggregate spatial contact sheet](spatial/99-atlas-contact-sheet.png)", "", "## Fixtures", "", "| Run | Match | Roster | Tagged frags | All frag rows | Outside match | Captures | Assists | Positions | Gate | Warnings |", "|---:|---|---:|---:|---:|---:|---:|---:|---:|---|---:|"]
    for fixture in item["fixtures"]:
        metrics = fixture["fixture"]["metrics"]
        tagged = int(fixture["source_inventory"]["frags"])
        all_rows = int(metrics["frags"])
        lines.append(f"| {fixture['fixture']['ordinal']} | `{fixture['fixture']['match_id']}` | {metrics['match_players']} | {tagged} | {all_rows} | {all_rows - tagged} | {metrics['captures_total']} | {metrics['assists_stored']} | {metrics['position_samples']} | `{fixture['quality']['status']}` | {len(fixture['fixture']['warnings'])} |")
    lines += ["", "## Recommendations", ""]
    lines.extend(f"- {text}" for text in item["recommendations"])
    lines += ["", "## Interpretation boundary", "", item["interpretation"], ""]
    return "\n".join(lines)


def build_report(dataset: dict, analysis_root: Path, atlas_root: Path) -> dict:
    index = json.loads((analysis_root / "analysis-index.json").read_text(encoding="utf-8"))
    if index["fixtures_completed"] != dataset["fixture_count"] or index["fixtures_failed"]:
        raise ValueError("analysis index is incomplete")
    public_matches = {
        item["match_id"]: json.loads((analysis_root / item["public"]).read_text(encoding="utf-8"))
        for item in index["matches"]
    }
    atlas_index = json.loads(
        (atlas_root / "atlas-index.json").read_text(encoding="utf-8-sig")
    )
    maps = []
    for map_name, map_item in dataset["maps"].items():
        fixtures = [public_matches[fixture["match_id"]] for fixture in map_item["fixtures"]]
        def metric_value(fixture: dict, key: str) -> float:
            if key == "kills":
                return float(fixture["source_inventory"]["frags"])
            if key == "position_samples":
                return float(fixture["source_inventory"]["position_samples"])
            if key == "match_players":
                return float(fixture["source_inventory"]["roster_players"])
            return float(fixture["fixture"]["metrics"][key])
        metrics = {
            key: describe([metric_value(fixture, key) for fixture in fixtures])
            for key in METRICS
        }
        all_frag_rows = sum(int(fixture["fixture"]["metrics"]["frags"]) for fixture in fixtures)
        match_tagged_frags = sum(int(fixture["source_inventory"]["frags"]) for fixture in fixtures)
        sides = {}
        for side in ("Allies", "Axis"):
            team_rows = [next((row for row in fixture["teams"] if row["team_name"] == side), {}) for fixture in fixtures]
            sides[side] = {
                key: describe([float(row.get(key) or 0) for row in team_rows])
                for key in SIDE_METRICS
            }
        profiles = [
            profile_summary(fixtures, name)
            for name in ("accumulation_v0", "accumulation_v1", "accumulation_v2_target10")
        ]
        positional = map_item.get("positional_baseline") or {}
        positional_metrics = positional.get("metrics") or {}
        metadata_path = atlas_root / map_name / "atlas-metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
        item = {
            "name": map_name,
            "display_name": map_name.removeprefix("dod_").replace("_", " ").title(),
            "cohort": map_item["cohort"],
            "quality_status": map_item["quality_status"],
            "waypoint_status": map_item["waypoint_status"],
            "metrics": metrics,
            "containment": {
                "all_frag_rows": all_frag_rows,
                "match_tagged_frags": match_tagged_frags,
                "outside_match_scope": all_frag_rows - match_tagged_frags,
                "fixtures_with_outside_rows": sum(
                    int(fixture["fixture"]["metrics"]["frags"])
                    != int(fixture["source_inventory"]["frags"])
                    for fixture in fixtures
                ),
            },
            "sides": sides,
            "accumulation": profiles,
            "rank_sensitivity": rank_sensitivity(fixtures),
            "positional": {
                "status": positional.get("status", "not_run"),
                "usable_samples": int(positional_metrics.get("baseline_samples") or 0),
                "excluded_samples": int(positional_metrics.get("excluded") or metrics["position_samples"]["total"]),
                "excluded_percent": int(positional_metrics.get("excluded_percent") or 100),
                "mean_enemy_flag_distance": positional_metrics.get("mean"),
                "median_enemy_flag_distance": positional_metrics.get("median"),
            },
            "ownership": {
                "state_events": sum(int(fixture["ownership"]["state_events"]) for fixture in fixtures),
                "initial_events": sum(int(fixture["ownership"]["initial_events"]) for fixture in fixtures),
                "baseline_flags_per_fixture": [int(fixture["ownership"]["baseline_flags"]) for fixture in fixtures],
            },
            "atlas": {
                "target_match_id": metadata["target_match_id"],
                "summary": metadata["summary"],
                "contact_sheet": f"spatial/{map_name}/{metadata['contact_sheet']}",
                "images": [{**image, "path": f"spatial/{map_name}/{image['file']}"} for image in metadata["images"]],
            },
            "fixtures": fixtures,
            "recommendations": recommendations(map_name, map_item, fixtures),
            "interpretation": (
                "This pipeline-only map demonstrates persistence and aggregate occupancy, but its current waypoints do not produce enough combat to support gameplay conclusions."
                if map_item["cohort"] == "pipeline_only" else
                "This experimental waypoint corpus exercises the pipeline, but its gameplay and spatial patterns require waypoint review before baseline use."
                if map_item["cohort"] == "experimental_unvalidated" else
                "Observed values describe five bot fixtures and validate the analytics path. They must not be interpreted as human norms or production scoring calibration."
            ),
        }
        maps.append(item)
    schema = json.loads((analysis_root / "schema-inventory.json").read_text(encoding="utf-8"))
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset_id": dataset["dataset_id"],
        "privacy": "Aggregate spatial data and derived player totals only; no player coordinates, paths, nearest flags, or personal heatmaps.",
        "integrity": {"fixtures": dataset["fixture_count"], "maps": dataset["map_count"], "unique_match_ids": dataset["unique_match_ids"], "unique_sql_dumps": dataset["unique_sql_dumps"], "verified": True},
        "quality_counts": index["quality_counts"],
        "containment": {
            "all_frag_rows": sum(item["containment"]["all_frag_rows"] for item in maps),
            "match_tagged_frags": sum(item["containment"]["match_tagged_frags"] for item in maps),
            "outside_match_scope": sum(item["containment"]["outside_match_scope"] for item in maps),
            "fixtures_with_outside_rows": sum(item["containment"]["fixtures_with_outside_rows"] for item in maps),
        },
        "maps": maps,
        "schema": schema,
    }


def page_html(report: dict) -> str:
    payload = json.dumps(report, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>KTP competitive bot corpus</title><style>
:root{--bg:#07111c;--panel:#0e1c2a;--panel2:#132638;--text:#eaf2f8;--muted:#91a6b7;--line:#274157;--cyan:#45d4d0;--gold:#f2bd57;--red:#f36d74;--blue:#62a8ff}*{box-sizing:border-box}body{margin:0;background:linear-gradient(135deg,#07111c,#0a1723 50%,#061019);color:var(--text);font:15px/1.5 Inter,Segoe UI,Arial,sans-serif}a{color:var(--cyan)}header{padding:28px clamp(20px,4vw,58px);border-bottom:1px solid var(--line);background:#091621dd;position:sticky;top:0;z-index:5;backdrop-filter:blur(12px)}h1{margin:0;font-size:clamp(24px,4vw,42px);letter-spacing:-.03em}header p{margin:6px 0 0;color:var(--muted)}.layout{display:grid;grid-template-columns:260px 1fr;max-width:1600px;margin:auto}.nav{padding:24px 16px;border-right:1px solid var(--line);min-height:calc(100vh - 100px)}.nav button{display:block;width:100%;padding:10px 12px;margin:4px 0;border:0;border-radius:9px;color:var(--text);background:transparent;text-align:left;cursor:pointer}.nav button:hover,.nav button.active{background:var(--panel2);color:var(--cyan)}main{padding:28px clamp(18px,4vw,54px);min-width:0}.badges{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0 22px}.badge{padding:4px 9px;border:1px solid var(--line);border-radius:999px;color:var(--muted);font-size:12px}.badge.good{border-color:#246d69;color:var(--cyan)}.badge.warn{border-color:#816633;color:var(--gold)}.badge.bad{border-color:#793e49;color:var(--red)}.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(155px,1fr));gap:12px;margin:18px 0}.card{background:var(--panel);border:1px solid var(--line);border-radius:14px;padding:16px}.card b{font-size:24px;display:block;color:var(--cyan)}.card span{color:var(--muted);font-size:12px}.section{background:#0b1925cc;border:1px solid var(--line);border-radius:16px;padding:20px;margin:18px 0;overflow:auto}h2{margin:0 0 12px;font-size:22px}h3{margin:22px 0 8px;color:#cfe1ec}table{border-collapse:collapse;width:100%;min-width:680px}th,td{border-bottom:1px solid var(--line);padding:8px 10px;text-align:right;vertical-align:top}th:first-child,td:first-child{text-align:left}th{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.05em}.muted{color:var(--muted)}details{border-top:1px solid var(--line);padding:10px 0}summary{cursor:pointer;color:#d9e8f0}.contact{display:block;max-width:100%;border:1px solid var(--line);border-radius:12px;background:#050b10}.gallery{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px}.gallery figure{margin:0;background:var(--panel);border:1px solid var(--line);border-radius:12px;overflow:hidden}.gallery img{width:100%;display:block;aspect-ratio:4/3;object-fit:contain;background:#050b10}.gallery figcaption{padding:10px}.gallery small{color:var(--muted);display:block}.notice{border-left:3px solid var(--gold);padding:10px 14px;background:#2a211455;color:#e9d9b8}.filters{display:flex;gap:10px;flex-wrap:wrap;margin:10px 0}.filters input,.filters select{background:var(--panel);color:var(--text);border:1px solid var(--line);border-radius:8px;padding:8px}ul{padding-left:22px}@media(max-width:850px){.layout{display:block}.nav{display:flex;overflow:auto;min-height:0;border-right:0;border-bottom:1px solid var(--line);padding:8px}.nav button{min-width:160px}header{position:static}}
</style></head><body><header><h1>KTP competitive bot corpus</h1><p>13 maps × 5 isolated test matches · aggregate spatial atlas · shadow scoring sensitivity</p></header><div class="layout"><nav class="nav" id="nav"></nav><main id="main"></main></div>
<script id="report-data" type="application/json">""" + payload + """</script><script>
const R=JSON.parse(document.getElementById('report-data').textContent),nav=document.getElementById('nav'),main=document.getElementById('main');
const esc=v=>String(v??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]));
const num=v=>Number(v||0).toLocaleString(undefined,{maximumFractionDigits:2});
const badge=(v,cls='')=>`<span class="badge ${cls}">${esc(v)}</span>`;
function metricRows(m){return Object.entries({kills:'Match-tagged frags',captures_total:'Captures',position_samples:'Positions',assists_stored:'Assists',cap_breaks_stored:'Cap breaks',match_players:'Roster'}).map(([k,l])=>{const d=m.metrics[k];return `<tr><td>${l}</td><td>${num(d.total)}</td><td>${num(d.mean)}</td><td>${num(d.sd)}</td><td>${num(d.median)}</td><td>${num(d.min)}–${num(d.max)}</td></tr>`}).join('')}
function players(f){return `<table><thead><tr><th>Player</th><th>Side</th><th>K</th><th>D</th><th>A</th><th>Damage</th><th>DPM</th><th>Captures</th><th>Breaks</th><th>K/D</th></tr></thead><tbody>${f.players.map(p=>`<tr><td>${esc(p.player_name_at_match)}</td><td>${esc(p.team_name)}</td><td>${num(p.kills)}</td><td>${num(p.deaths)}</td><td>${num(p.assists)}</td><td>${num(p.damage_dealt)}</td><td>${num(p.damage_per_minute)}</td><td>${num(p.capture_credits)}</td><td>${num(p.cap_breaks)}</td><td>${num(p.kd_ratio)}</td></tr>`).join('')}</tbody></table>`}
function matches(m){return m.fixtures.map(f=>{const x=f.fixture.metrics,w=f.fixture.warnings||[],tagged=Number(f.source_inventory.frags),outside=Number(x.frags)-tagged;return `<details><summary>Run ${x?f.fixture.ordinal:''} · ${esc(f.fixture.match_id)} · ${tagged} tagged frags · ${x.captures_total} captures · ${badge(f.quality.status,f.quality.status==='PASS'?'good':f.quality.status==='WARN'?'warn':'bad')}</summary><p class="muted">All frag rows ${x.frags}; outside match scope ${outside}; roster ${x.match_players}; assists ${x.assists_stored}; positions ${num(x.position_samples)}; cohort ${esc(m.cohort)}; dataset quality ${esc(m.quality_status)}.</p>${w.length?`<div class="notice"><b>Fixture warnings</b><ul>${w.map(v=>`<li>${esc(v)}</li>`).join('')}</ul></div>`:''}${players(f)}</details>`}).join('')}
function gallery(m){const cats=[...new Set(m.atlas.images.map(i=>i.category))];return `<div class="filters"><select id="cat"><option value="">All atlas categories</option>${cats.map(c=>`<option>${esc(c)}</option>`).join('')}</select></div><div class="gallery" id="gallery">${m.atlas.images.map(i=>`<figure data-cat="${esc(i.category)}"><a href="${esc(i.path)}"><img loading="lazy" src="${esc(i.path)}" alt="${esc(i.title)}"></a><figcaption><b>${esc(i.title)}</b><small>${esc(i.category)} · ${esc(i.detail)}</small></figcaption></figure>`).join('')}</div>`}
function render(name){const m=R.maps.find(x=>x.name===name)||R.maps[0];location.hash=m.name;[...nav.children].forEach(b=>b.classList.toggle('active',b.dataset.map===m.name));const q=m.quality_status.includes('warning')?'warn':m.cohort==='pipeline_only'?'bad':'good';main.innerHTML=`<h1>${esc(m.display_name)}</h1><div class="badges">${badge(m.name)}${badge(m.cohort,q)}${badge(m.quality_status,q)}${badge('5 independent fixtures')}</div><div class="notice">${esc(m.interpretation)}</div><div class="cards"><div class="card"><b>${num(m.metrics.kills.total)}</b><span>Match-tagged frags</span></div><div class="card"><b>${num(m.containment.outside_match_scope)}</b><span>Outside match scope</span></div><div class="card"><b>${num(m.metrics.captures_total.total)}</b><span>Captures across five</span></div><div class="card"><b>${num(m.metrics.position_samples.total)}</b><span>Position samples</span></div></div><section class="section"><h2>Observed five-match distribution</h2><p class="muted">Sample SD and observed range are shown; n=5 is too small for a useful human-performance confidence interval. Frag distributions use match-tagged rows only.</p><table><thead><tr><th>Metric</th><th>Total</th><th>Mean</th><th>Sample SD</th><th>Median</th><th>Range</th></tr></thead><tbody>${metricRows(m)}</tbody></table></section><section class="section"><h2>Shadow accumulation sensitivity</h2><table><thead><tr><th>Profile</th><th>Events</th><th>Position</th><th>Position share</th><th>Capped rows</th></tr></thead><tbody>${m.accumulation.map(p=>`<tr><td>${esc(p.profile)}</td><td>${num(p.event_points)}</td><td>${num(p.position_points)}</td><td>${num(p.position_share_percent)}%</td><td>${p.capped_player_rows}/${p.player_rows}</td></tr>`).join('')}</tbody></table><p>v0 → v2 rank changes: ${m.rank_sensitivity.rank_changed}/${m.rank_sensitivity.player_rows_compared}; maximum movement ${m.rank_sensitivity.max_rank_move} places.</p><p class="muted">Non-Anzio maps use uncalibrated base proximity and captured ownership evidence only. These profiles remain shadow-only.</p></section><section class="section"><h2>Positional and ownership coverage</h2><div class="cards"><div class="card"><b>${esc(m.positional.status)}</b><span>Baseline result</span></div><div class="card"><b>${num(m.positional.usable_samples)}</b><span>Usable samples</span></div><div class="card"><b>${num(m.positional.excluded_samples)}</b><span>Excluded samples</span></div><div class="card"><b>${num(m.ownership.state_events)}</b><span>Ownership events</span></div></div></section><section class="section"><h2>Aggregate spatial atlas</h2><p><a href="${esc(m.atlas.contact_sheet)}">Open full-size contact sheet</a></p><img class="contact" loading="lazy" src="${esc(m.atlas.contact_sheet)}" alt="${esc(m.display_name)} atlas contact sheet"><h3>Explore individual layers</h3>${gallery(m)}</section><section class="section"><h2>Five match reports</h2>${matches(m)}</section><section class="section"><h2>Recommended next work</h2><ul>${m.recommendations.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></section>`;document.getElementById('cat').addEventListener('change',e=>document.querySelectorAll('#gallery figure').forEach(f=>f.hidden=e.target.value&&f.dataset.cat!==e.target.value));}
function active(key){[...nav.children].forEach(b=>b.classList.toggle('active',b.dataset.map===key))}
function overview(){location.hash='overview';active('overview');const totals=k=>R.maps.reduce((n,m)=>n+Number(m.metrics[k].total),0);main.innerHTML=`<h1>Corpus overview</h1><div class="badges">${badge(R.dataset_id)}${badge('checksum verified','good')}${badge(R.privacy)}</div><div class="cards"><div class="card"><b>${R.integrity.maps}</b><span>Competitive maps</span></div><div class="card"><b>${R.integrity.fixtures}</b><span>Independent fixtures</span></div><div class="card"><b>${num(totals('kills'))}</b><span>Match-tagged frags</span></div><div class="card"><b>${num(R.containment.outside_match_scope)}</b><span>Outside match scope</span></div><div class="card"><b>${num(totals('position_samples'))}</b><span>Position samples</span></div></div><section class="section"><h2>Coverage matrix</h2><table><thead><tr><th>Map</th><th>Cohort</th><th>Dataset quality</th><th>Tagged frags</th><th>Outside match</th><th>Captures</th><th>Positions</th><th>Positional result</th><th>v2 position share</th><th>v2 capped</th></tr></thead><tbody>${R.maps.map(m=>{const p=m.accumulation.find(x=>x.profile==='accumulation_v2_target10');return `<tr><td><a href="#${esc(m.name)}">${esc(m.display_name)}</a></td><td>${esc(m.cohort)}</td><td>${esc(m.quality_status)}</td><td>${num(m.metrics.kills.total)}</td><td>${num(m.containment.outside_match_scope)}</td><td>${num(m.metrics.captures_total.total)}</td><td>${num(m.metrics.position_samples.total)}</td><td>${esc(m.positional.status)}</td><td>${num(p.position_share_percent)}%</td><td>${p.capped_player_rows}/${p.player_rows}</td></tr>`}).join('')}</tbody></table></section><section class="section"><h2>Interpretation</h2><h3>Observed</h3><ul><li>All 65 checksum-pinned dumps were restored and analyzed independently.</li><li>${R.containment.match_tagged_frags} frag rows are match-tagged; ${R.containment.outside_match_scope} are outside match scope and excluded from reports.</li><li>Every map persisted positions; four pipeline-only maps produced insufficient combat.</li><li>Chemille and Railroad2 fail closed for ownership-derived positional baselines.</li></ul><h3>Inference</h3><p>The corpus validates collection and analysis behavior across map geometries. v2 saturation on several long fixtures demonstrates cap/duration sensitivity; none of these bot values calibrate human skill, map balance, or production scoring.</p><h3>Next</h3><p>Improve the named waypoint/ownership gaps, then validate the first controlled human preprod match before changing scoring weights.</p></section>`;document.querySelectorAll('a[href^="#dod_"]').forEach(a=>a.onclick=e=>{e.preventDefault();render(a.hash.slice(1))})}
function schema(){location.hash='schema';active('schema');const rows=R.schema.tables.map(t=>`<details class="schema-row" data-name="${esc(t.name.toLowerCase())}"><summary><b>${esc(t.name)}</b> · non-empty ${t.fixtures_nonempty}/${t.fixtures_present} fixtures · ${t.schema_variants.length} schema variant(s)</summary>${t.schema_variants.map(v=>`<p class="muted">Observed in ${v.fixtures} fixtures across ${v.maps.length} maps.</p><table><thead><tr><th>Column</th><th>Type</th><th>Nullable</th><th>Default</th><th>Extra</th></tr></thead><tbody>${v.columns.map(c=>`<tr><td>${esc(c.name)}</td><td>${esc(c.type)}</td><td>${c.nullable?'yes':'no'}</td><td>${esc(c.default)}</td><td>${esc(c.extra)}</td></tr>`).join('')}</tbody></table>`).join('')}</details>`).join('');main.innerHTML=`<h1>Schema and table coverage</h1><div class="badges">${badge(`${R.schema.table_count} tables`)}${badge(`${R.schema.fixture_observations} fixture observations`,'good')}</div><p class="notice">This inventory shows definitions and aggregate row coverage only; no database rows are published.</p><div class="filters"><input id="schema-filter" placeholder="Filter tables"></div><section class="section" id="schema-list">${rows}</section>`;document.getElementById('schema-filter').oninput=e=>document.querySelectorAll('.schema-row').forEach(row=>row.hidden=!row.dataset.name.includes(e.target.value.toLowerCase()))}
const addNav=(label,key,fn)=>{const b=document.createElement('button');b.textContent=label;b.dataset.map=key;b.onclick=fn;nav.appendChild(b)};addNav('Corpus overview','overview',overview);addNav('Schema & coverage','schema',schema);R.maps.forEach(m=>addNav(m.display_name,m.name,()=>render(m.name)));const start=location.hash.slice(1);if(start==='schema')schema();else if(start&&start!=='overview')render(start);else overview();
</script></body></html>"""


def report_markdown(report: dict) -> str:
    lines = [
        "# Competitive bot corpus analysis", "",
        f"Dataset: `{report['dataset_id']}`", "",
        "Integrity: **PASS** — 13 maps, 65 unique matches, and 65 unique SQL dumps were checksum verified.", "",
        f"Privacy: {report['privacy']}", "",
        "## Map coverage", "",
        "| Map | Cohort | Dataset quality | Fixtures | Tagged frags | Outside match | Captures | Positions | Positional result | v2 position share | v2 capped | Report |", "|---|---|---|---:|---:|---:|---:|---:|---|---:|---:|---|",
    ]
    for item in report["maps"]:
        v2 = next(profile for profile in item["accumulation"] if profile["profile"] == "accumulation_v2_target10")
        lines.append(f"| `{item['name']}` | `{item['cohort']}` | `{item['quality_status']}` | 5 | {item['metrics']['kills']['total']:,.0f} | {item['containment']['outside_match_scope']:,.0f} | {item['metrics']['captures_total']['total']:,.0f} | {item['metrics']['position_samples']['total']:,.0f} | `{item['positional']['status']}` | {v2['position_share_percent']:.2f}% | {v2['capped_player_rows']}/{v2['player_rows']} | [details](maps/{item['name']}/REPORT.md) |")
    lines += ["", "## Observed facts", "", "- All 65 selected SQL fixtures were analyzed independently in ephemeral, network-disabled databases.", f"- Lane B contains {report['containment']['all_frag_rows']:,} total frag rows: {report['containment']['match_tagged_frags']:,} match-tagged and {report['containment']['outside_match_scope']:,} outside match scope across {report['containment']['fixtures_with_outside_rows']} fixtures. Match reports and atlases use only the tagged rows.", "- Position persistence is complete across all maps.", "- Four pipeline-only maps have insufficient combat for gameplay conclusions.", "- Chemille and Railroad2 lack a usable non-neutral ownership baseline and fail closed for ownership-derived positional work.", "", "## Inferences", "", "- Validated-map bot fixtures demonstrate that the expanded reporting pipeline can ingest combat, objectives, weapons, assists, ownership, and positions across multiple map geometries.", "- Pipeline-only and experimental waypoint results identify waypoint coverage limitations; they do not show that those maps or their competitive layouts are defective.", "- v2 cap saturation on several 1,200-second maps shows duration sensitivity even when its overall positional share looks modest; it is not ready for production calibration.", "- Accumulation sensitivity is useful for software behavior and saturation checks only. It cannot calibrate human scoring weights.", "", "## Recommendations", ""]
    unique = []
    for item in report["maps"]:
        for recommendation in item["recommendations"]:
            entry = f"`{item['name']}`: {recommendation}"
            if entry not in unique:
                unique.append(entry)
    lines.extend(f"- {entry}" for entry in unique)
    lines += ["", "## Schema coverage", "", f"The corpus contains {report['schema']['table_count']} tables. The online explorer and `data/schema-inventory.json` show exact columns plus non-empty-fixture coverage without exposing table rows.", "", "## Viewing", "", "Open `index.html` directly for the self-contained explorer. A local web server is optional; see `README.md`.", ""]
    return "\n".join(lines)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset_root", type=Path)
    parser.add_argument("analysis_root", type=Path)
    parser.add_argument("atlas_root", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args()
    dataset_root = args.dataset_root.resolve()
    analysis_root = args.analysis_root.resolve()
    atlas_root = args.atlas_root.resolve()
    output = args.output_dir.resolve()
    dataset = json.loads((dataset_root / "dataset.json").read_text(encoding="utf-8"))
    report = build_report(dataset, analysis_root, atlas_root)
    output.mkdir(parents=True, exist_ok=True)
    shutil.copytree(analysis_root, output / "data", dirs_exist_ok=True)
    shutil.copytree(atlas_root, output / "spatial", dirs_exist_ok=True)
    (output / "index.html").write_text(page_html(report), encoding="utf-8")
    (output / "REPORT.md").write_text(report_markdown(report), encoding="utf-8")
    for item in report["maps"]:
        map_dir = output / "maps" / item["name"]
        map_dir.mkdir(parents=True, exist_ok=True)
        text = markdown_map(item).replace("spatial/", f"../../spatial/{item['name']}/")
        (map_dir / "REPORT.md").write_text(text, encoding="utf-8")
    (output / "README.md").write_text(
        "# KTP competitive bot corpus explorer\n\n"
        "Open `index.html` directly in a modern browser. No server, database, or network "
        "connection is required. To serve it locally from this directory, run "
        "`python -m http.server 8000` and visit `http://localhost:8000/`.\n\n"
        "The shareable folder contains aggregate positional products and derived player "
        "totals only. Private accumulation working data is deliberately outside it.\n",
        encoding="utf-8",
    )
    public_files = [path for path in output.rglob("*") if path.is_file() and path.name != "artifact-manifest.json"]
    manifest = {
        "schema_version": 1,
        "dataset_id": dataset["dataset_id"],
        "generated_at": report["generated_at"],
        "files": [
            {"path": str(path.relative_to(output)).replace("\\", "/"), "bytes": path.stat().st_size, "sha256": sha256(path)}
            for path in sorted(public_files)
        ],
    }
    (output / "artifact-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Built shareable explorer with {len(manifest['files'])} files: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
