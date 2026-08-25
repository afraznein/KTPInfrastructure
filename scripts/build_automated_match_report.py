#!/usr/bin/env python3
"""Build an immutable deterministic match-report bundle and AI checkpoint."""

from __future__ import annotations

import argparse
import hashlib
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
