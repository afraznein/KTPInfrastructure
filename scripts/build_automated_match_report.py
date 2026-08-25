#!/usr/bin/env python3
"""Build an immutable deterministic match-report bundle and AI checkpoint."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from scripts.accumulation_v3 import (
    build_ai_checkpoint,
    load_profile,
    render_markdown,
    score_match,
    validate_ai_response,
)
from scripts.compare_accumulation_models import compare_models, render_markdown as render_comparison
from scripts.momentum_v5 import render_momentum_svg


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def render_html(report: dict[str, Any]) -> str:
    """Render a portable, sanitized report browser for downloaded artifacts."""
    esc = lambda value: html.escape(str(value if value is not None else "—"))
    players = []
    for row in report.get("players") or []:
        combat = sum(float(row.get(key) or 0) for key in (
            "combat_finisher_points", "combat_damage_share_points",
            "fallback_assist_points", "fallback_damage_points",
        ))
        context = sum(float(row.get(key) or 0) for key in (
            "streak_points", "shutdown_points", "fast_chain_points",
            "capture_points", "conversion_points", "cap_break_points",
        ))
        rating = "—" if row.get("impact_index") is None else f"{row['impact_index']:.1f}"
        players.append(
            "<tr>"
            f"<td>{row.get('rank', '')}</td><td>{esc(row.get('player_name_at_match'))}</td>"
            f"<td>{esc(row.get('team_name'))}</td><td><b>{rating}</b></td>"
            f"<td>{float(row.get('total_points') or 0):.2f}</td>"
            f"<td>{combat:.2f}</td><td>{context:.2f}</td>"
            f"<td>{float(row.get('position_points') or 0):.2f}</td>"
            f"<td>{float(row.get('momentum_points') or 0):.2f}</td>"
            f"<td>{int(row.get('kills') or 0)}/{int(row.get('deaths') or 0)}/"
            f"{int(row.get('assists') or 0)}</td>"
            f"<td>{float(row.get('opponent_damage') or 0):.0f}</td></tr>"
        )
    components = "".join(
        f"<tr><td>{esc(key.replace('_', ' ').title())}</td><td>{float(value):.2f}</td>"
        f"<td>{float((report.get('component_shares_percent') or {}).get(key, 0)):.1f}%</td></tr>"
        for key, value in (report.get("component_totals") or {}).items()
    )
    gates = "".join(
        f"<tr><td>{esc(key.replace('_', ' ').title())}</td>"
        f"<td><span class=\"badge {esc(str(value.get('status', '')).lower())}\">"
        f"{esc(value.get('status'))}</span></td><td>{esc(value.get('detail'))}</td></tr>"
        for key, value in (report.get("quality_gates") or {}).items()
    )
    momentum = report.get("momentum") or {}
    graph = render_momentum_svg(momentum, str((report.get("match") or {}).get("match_id", ""))) \
        if momentum else "<p>Momentum evidence unavailable.</p>"
    normalization = report.get("impact_index") or {}
    match = report.get("match") or {}
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>KTP match report — {esc(match.get('match_id'))}</title>
<style>
:root{{--bg:#101418;--panel:#192127;--ink:#eef4f7;--muted:#a9b8c0;--line:#31404a;--gold:#e8b44d}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.45 system-ui,sans-serif}}main{{max-width:1200px;margin:auto;padding:28px}}
h1,h2{{margin:.2em 0}}.sub{{color:var(--muted);margin-bottom:24px}}.panel{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:18px;margin:18px 0;overflow:auto}}
table{{border-collapse:collapse;width:100%}}th,td{{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);white-space:nowrap}}th{{color:var(--muted)}}
.badge{{padding:3px 7px;border-radius:999px;background:#34434c}}.pass{{background:#195c3a}}.warn{{background:#72551b}}.disabled{{background:#4b5358}}
svg{{max-width:100%;height:auto;background:white;border-radius:6px}}code{{color:var(--gold)}}
</style></head><body><main>
<h1>KTP accumulated match report</h1><p class="sub"><code>{esc(match.get('match_id'))}</code> · {esc(match.get('map_name'))} · profile <code>{esc(report.get('profile'))}</code> · experimental shadow</p>
<div class="panel"><h2>Player scoreboard</h2><p>Overall rating uses the complete accumulated score. The provisional match median is {float(normalization.get('center_index') or 100):.0f}; momentum is one bounded additive component.</p>
<table><thead><tr><th>#</th><th>Player</th><th>Team</th><th>Rating</th><th>Raw</th><th>Combat</th><th>Context</th><th>Position</th><th>Momentum</th><th>K/D/A</th><th>Damage</th></tr></thead><tbody>{''.join(players)}</tbody></table></div>
<div class="panel"><h2>Team momentum</h2>{graph}</div>
<div class="panel"><h2>Component totals</h2><table><thead><tr><th>Component</th><th>Points</th><th>Share</th></tr></thead><tbody>{components}</tbody></table></div>
<div class="panel"><h2>Evidence quality</h2><table><thead><tr><th>Gate</th><th>Status</th><th>Detail</th></tr></thead><tbody>{gates}</tbody></table></div>
<p class="sub">Raw player coordinates and individual movement paths are intentionally excluded. See <code>report.md</code> for the detailed scoring explanation and <code>manifest.json</code> for hashes.</p>
</main></body></html>"""


def build_bundle(
    facts: dict[str, Any], profile: dict[str, Any], output_dir: Path,
    ai_response: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write a reproducible bundle; AI review is separate and never mutates it."""
    report = score_match(facts, profile)
    comparison = compare_models(facts, profile)
    checkpoint = build_ai_checkpoint(report)
    match_id = report["match"]["match_id"]
    files: dict[str, bytes] = {
        "report.json": _json_bytes(report),
        "report.md": render_markdown(report).encode("utf-8"),
        "report.html": render_html(report).encode("utf-8"),
        "comparison.json": _json_bytes(comparison),
        "comparison.md": render_comparison(comparison).encode("utf-8"),
        "ai-request.json": _json_bytes(checkpoint),
    }
    if report.get("momentum"):
        files["momentum.svg"] = render_momentum_svg(
            report["momentum"], match_id
        ).encode("utf-8")
    ai_status = "PENDING_OPTIONAL"
    publication_checkpoint = "HUMAN_REVIEW_REQUIRED"
    if ai_response is not None:
        validate_ai_response(checkpoint, ai_response)
        files["ai-response.json"] = _json_bytes(ai_response)
        blocking = any(
            anomaly.get("severity") == "block"
            for anomaly in ai_response.get("anomalies") or []
        )
        ai_status = "VALIDATED_HOLD" if blocking else "VALIDATED_REVIEW"
        publication_checkpoint = "HOLD" if blocking else "HUMAN_REVIEW_REQUIRED"

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_files = []
    for relative, body in files.items():
        path = output_dir / relative
        path.write_bytes(body)
        manifest_files.append({
            "path": relative,
            "sha256": _sha256(body),
            "bytes": len(body),
        })
    manifest = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "match_id": match_id,
        "profile": report["profile"],
        "profile_sha256": _sha256(_json_bytes(profile)),
        "facts_sha256": _sha256(_json_bytes(facts)),
        # The semantic hash excludes only wall-clock generation metadata, so
        # rerunning identical facts/profile produces the same identity.
        "deterministic_report_sha256": _sha256(_json_bytes({
            key: value for key, value in report.items() if key != "generated_at"
        })),
        "report_file_sha256": next(
            item["sha256"] for item in manifest_files if item["path"] == "report.json"
        ),
        "ai_status": ai_status,
        "publication_checkpoint": publication_checkpoint,
        "publication_state": "DRAFT",
        "files": manifest_files,
        "invariants": {
            "ai_can_change_scores": False,
            "ai_can_change_quality_gates": False,
            "ai_can_publish": False,
            "raw_individual_positions_exported": False,
        },
    }
    manifest_body = _json_bytes(manifest)
    (output_dir / "manifest.json").write_bytes(manifest_body)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--facts", type=Path, required=True)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--ai-response", type=Path)
    args = parser.parse_args(argv)
    facts = json.loads(args.facts.read_text(encoding="utf-8"))
    profile = load_profile(args.profile) if args.profile else load_profile()
    ai_response = (
        json.loads(args.ai_response.read_text(encoding="utf-8"))
        if args.ai_response else None
    )
    manifest = build_bundle(facts, profile, args.output_dir, ai_response)
    print(f"bundle: {args.output_dir}")
    print(f"manifest: {args.output_dir / 'manifest.json'}")
    print(f"checkpoint: {manifest['publication_checkpoint']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
