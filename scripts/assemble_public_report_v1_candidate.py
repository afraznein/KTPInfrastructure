#!/usr/bin/env python3
"""Assemble and checksum the frozen public-report-v1 handover packet."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "development_candidate" / "public-report-v1"
DEFAULT_OUTPUT = Path(
    r"G:\GIT\ktp_stats\handover\analytics-handover\public-match-report\v1.2.0-development_candidate"
)
PACKET_VERSION = "v1.2.0-development_candidate"
CONTRACT_VERSION = "1.2.0"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def git_head() -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, check=True,
        capture_output=True, text=True,
    )
    return completed.stdout.strip()


def write_checksums(output: Path) -> None:
    entries = []
    for path in sorted(item for item in output.rglob("*") if item.is_file()):
        if path.name == "SHA256SUMS":
            continue
        relative = path.relative_to(output).as_posix()
        entries.append(f"{sha256(path)}  {relative}")
    (output / "SHA256SUMS").write_text(
        "\n".join(entries) + "\n", encoding="utf-8"
    )


def populate(output: Path) -> None:
    for name in (
        "HANDOVER.md", "metric-contract.md", "private-schema.json",
        "decisions.md", "limitations.md",
    ):
        copy(SOURCE / name, output / name)

    schema_root = SOURCE / "schemas"
    for path in sorted(schema_root.glob("*.json")):
        copy(path, output / "schemas" / path.name)
    copy(
        schema_root / "public-report-v1.schema.json",
        output / "public-schema.json",
    )

    for path in sorted((SOURCE / "fixtures" / "golden").glob("*.json")):
        copy(path, output / "golden-output" / path.name)
        copy(path, output / "fixtures" / "positive" / path.name)
    for path in sorted((SOURCE / "fixtures" / "privacy-negative").glob("*.json")):
        copy(path, output / "privacy-negative-fixtures" / path.name)

    implementation = {
        REPO / "scripts" / "build_public_report_v1.py": "build_public_report_v1.py",
        REPO / "scripts" / "validate_public_report_v1.py": "validate_public_report_v1.py",
        SOURCE / "implementation" / "test_packet.py": "test_packet.py",
    }
    for source, name in implementation.items():
        copy(source, output / "implementation" / name)

    producer_inputs = {
        REPO / "tests" / "fixtures" / "public_report_v1" / "internal-analytics-v3.json": "analytics-v3.synthetic.json",
        REPO / "tests" / "fixtures" / "public_report_v1" / "readiness.json": "readiness-v1.synthetic.json",
        REPO / "tests" / "fixtures" / "public_report_v1" / "private-points-timeline.json": "timeline-v1.synthetic.json",
        REPO / "tests" / "fixtures" / "public_report_v1" / "private-momentum-episodes.json": "momentum-v1.synthetic.json",
    }
    for source, name in producer_inputs.items():
        copy(source, output / "producer-inputs" / name)

    validation = subprocess.run(
        [
            sys.executable, "-B",
            str(REPO / "scripts" / "validate_public_report_v1.py"),
            str(SOURCE),
        ],
        cwd=REPO, check=True, capture_output=True, text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    (output / "validation-report.json").write_text(
        validation.stdout, encoding="utf-8"
    )

    manifest = {
        "packet_version": PACKET_VERSION,
        "contract_version": CONTRACT_VERSION,
        "status": "development_candidate",
        "created_date": "2026-08-29",
        "source": {
            "worktree": str(REPO),
            "git_head": git_head(),
            "working_tree_note": "Candidate files are uncommitted; this immutable packet plus SHA256SUMS is the transfer anchor."
        },
        "artifact_version_reconciliation": {
            "analytics_box_score_input_schema": 3,
            "readiness_input_schema": 1,
            "private_scoring_input_schema": 1,
            "private_team_timeline_input_schema": 1,
            "private_momentum_input_schema": 1,
            "public_report_envelope": "public-report-v1",
            "public_timeline": "public-timeline-v1",
            "public_momentum_episodes": "momentumEpisode-v1",
            "public_payload_contract_version": CONTRACT_VERSION,
            "public_payload_contains_source_provenance": False
        },
        "team_contract": {
            "keys": ["team_a", "team_b"],
            "side_mapping": "explicit_for_every_played_half"
        },
        "privacy": {
            "public": "descriptive box score and precomputed aggregate team timeline/momentum only",
            "restricted": "player ratings, player scoring/allocations/ranks, stable identities, ledgers, and individual positional evidence",
            "private_denver_input_included": False
        },
        "spatial_atlas": "deferred_not_in_packet",
        "validation": {
            "report": "validation-report.json",
            "packet_local_suite": "implementation/test_packet.py",
            "expected_status": "PASS",
            "python_dependency": "jsonschema>=4.18"
        }
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )

    packet_test = subprocess.run(
        [sys.executable, "-B", str(output / "implementation" / "test_packet.py")],
        cwd=output, check=True, capture_output=True, text=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    (output / "packet-test-report.txt").write_text(
        packet_test.stdout + packet_test.stderr, encoding="utf-8"
    )

    write_checksums(output)


def assemble(output: Path, *, replace_invalidated: bool = False) -> None:
    if output.exists() and not replace_invalidated:
        raise FileExistsError(
            f"refusing to overwrite frozen packet: {output}; choose a new version"
        )
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(
        prefix=f".{output.name}.tmp-", dir=output.parent,
    ))
    backup: Path | None = None
    installed = False
    try:
        populate(staging)
        if output.exists():
            if not output.is_dir():
                raise FileExistsError(f"refusing to replace non-directory: {output}")
            backup = output.with_name(
                f".{output.name}.invalidated-{uuid.uuid4().hex}"
            )
            output.rename(backup)
        staging.rename(output)
        installed = True
        if backup is not None:
            shutil.rmtree(backup)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        if not installed and backup is not None and backup.exists() and not output.exists():
            backup.rename(output)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--replace-invalidated", action="store_true",
        help="atomically replace the exact invalidated output after staging validates",
    )
    args = parser.parse_args()
    assemble(args.output.resolve(), replace_invalidated=args.replace_invalidated)
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
