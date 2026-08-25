#!/usr/bin/env python3
"""Create a reproducible, local manifest for the three-repository stats release."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1


def git(repo: Path, *args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False, capture_output=True, text=True, encoding="utf-8",
    )
    if check and result.returncode:
        raise ValueError(
            f"git {' '.join(args)} failed for {repo.name}: "
            f"{(result.stderr or result.stdout).strip()}"
        )
    return result.stdout.strip() if result.returncode == 0 else ""


def split_ref_spec(value: str) -> tuple[str, Path, str]:
    if "=" not in value or "@" not in value:
        raise ValueError(f"expected NAME=PATH@REF, got {value!r}")
    name, location = value.split("=", 1)
    path_text, ref = location.rsplit("@", 1)
    if not name or not path_text or not ref:
        raise ValueError(f"expected NAME=PATH@REF, got {value!r}")
    return name, Path(path_text).resolve(), ref


def split_file_spec(value: str) -> tuple[str, Path]:
    if "=" not in value:
        raise ValueError(f"expected NAME=PATH, got {value!r}")
    name, path_text = value.split("=", 1)
    if not name or not path_text:
        raise ValueError(f"expected NAME=PATH, got {value!r}")
    return name, Path(path_text).resolve()


def hash_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return {"file": path.name, "bytes": path.stat().st_size, "sha256": digest.hexdigest()}


def ref_exists(repo: Path, ref: str) -> bool:
    result = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", ref],
        check=False, capture_output=True,
    )
    return result.returncode == 0


def collect_repository(name: str, repo: Path, ref: str, *, test_only=False) -> dict[str, Any]:
    if not repo.is_dir():
        raise FileNotFoundError(repo)
    sha = git(repo, "rev-parse", ref)
    head = git(repo, "rev-parse", "HEAD")
    branch = git(repo, "branch", "--show-current") or "detached"
    dirty_lines = [line for line in git(repo, "status", "--porcelain").splitlines() if line]
    entry: dict[str, Any] = {
        "name": name,
        "checkout": repo.name,
        "requested_ref": ref,
        "sha": sha,
        "checked_out_branch": branch,
        "ref_is_checked_out": sha == head,
        "working_tree_clean": not dirty_lines,
        "working_tree_change_count": len(dirty_lines),
        "test_only": test_only,
    }
    for baseline in ("main", "preprod"):
        if not ref_exists(repo, baseline):
            continue
        baseline_sha = git(repo, "rev-parse", baseline)
        entry[f"{baseline}_sha"] = baseline_sha
        entry[f"commits_ahead_of_{baseline}"] = int(
            git(repo, "rev-list", "--count", f"{baseline}..{sha}") or 0
        )
        entry[f"commits_behind_{baseline}"] = int(
            git(repo, "rev-list", "--count", f"{sha}..{baseline}") or 0
        )
        entry[f"contains_{baseline}"] = subprocess.run(
            ["git", "-C", str(repo), "merge-base", "--is-ancestor", baseline_sha, sha],
            check=False, capture_output=True,
        ).returncode == 0
    return entry


def build_manifest(repository_specs: list[str], dependency_specs: list[str],
                   artifact_specs: list[str], migration_dir: Path | None) -> dict[str, Any]:
    repositories = [
        collect_repository(name, path, ref)
        for name, path, ref in map(split_ref_spec, repository_specs)
    ]
    dependencies = [
        collect_repository(name, path, ref, test_only=True)
        for name, path, ref in map(split_ref_spec, dependency_specs)
    ]
    artifacts = []
    for name, path in map(split_file_spec, artifact_specs):
        artifacts.append({"name": name, **hash_file(path)})
    migrations = []
    if migration_dir is not None:
        migration_dir = migration_dir.resolve()
        if not migration_dir.is_dir():
            raise FileNotFoundError(migration_dir)
        migrations = [hash_file(path) for path in sorted(migration_dir.glob("*.sql"))]
        if not migrations:
            raise ValueError(f"no SQL migrations found in {migration_dir}")

    required_names = {"KTPAMXX", "KTPHLStatsX", "KTPInfrastructure"}
    present_names = {repo["name"] for repo in repositories}
    errors = []
    if present_names != required_names:
        errors.append(
            "release repository set must be exactly "
            f"{sorted(required_names)}; got {sorted(present_names)}"
        )
    for repo in repositories:
        if not repo["working_tree_clean"]:
            errors.append(f"{repo['name']} checkout has local changes")
        if not repo["ref_is_checked_out"]:
            errors.append(f"{repo['name']} requested ref is not the checked-out commit")
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "READY_FOR_REHEARSAL" if not errors else "BLOCKED",
        "errors": errors,
        "repositories": repositories,
        "test_dependencies": dependencies,
        "artifacts": artifacts,
        "migrations": migrations,
        "policy": {
            "remote_changes_performed": False,
            "production_changes_performed": False,
            "artifact_identity": "sha256",
            "position_points": "shadow_only",
        },
    }


def short(sha: str | None) -> str:
    return sha[:12] if sha else "n/a"


def render_markdown(manifest: dict[str, Any]) -> str:
    lines = [
        "# Stats release-candidate manifest",
        "",
        f"**Status:** {manifest['status']}  ",
        f"**Generated:** {manifest['generated_at_utc']}  ",
        "**Scope:** local evidence only; no remote or production changes",
        "",
        "## Release repositories",
        "",
        "| Repository | Candidate | Branch | Clean | Contains preprod | Ahead of main | Behind main |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for repo in manifest["repositories"]:
        lines.append(
            f"| {repo['name']} | `{short(repo['sha'])}` | `{repo['checked_out_branch']}` | "
            f"{'yes' if repo['working_tree_clean'] else 'no'} | "
            f"{'yes' if repo.get('contains_preprod') else 'no'} | "
            f"{repo.get('commits_ahead_of_main', 'n/a')} | {repo.get('commits_behind_main', 'n/a')} |"
        )
    if manifest["test_dependencies"]:
        lines.extend([
            "", "## Test-only dependencies", "",
            "| Repository | Commit | Branch | Clean |", "|---|---|---|---:|",
        ])
        for repo in manifest["test_dependencies"]:
            lines.append(
                f"| {repo['name']} | `{short(repo['sha'])}` | `{repo['checked_out_branch']}` | "
                f"{'yes' if repo['working_tree_clean'] else 'no'} |"
            )
    lines.extend([
        "", "## Built artifacts", "",
        "| Artifact | File | Bytes | SHA-256 |", "|---|---|---:|---|",
    ])
    lines.extend(
        f"| {item['name']} | `{item['file']}` | {item['bytes']} | `{item['sha256']}` |"
        for item in manifest["artifacts"]
    )
    lines.extend([
        "", "## Database migrations", "",
        "| File | Bytes | SHA-256 |", "|---|---:|---|",
    ])
    lines.extend(
        f"| `{item['file']}` | {item['bytes']} | `{item['sha256']}` |"
        for item in manifest["migrations"]
    )
    if manifest["errors"]:
        lines.extend(["", "## Blocking findings", ""])
        lines.extend(f"- {error}" for error in manifest["errors"])
    lines.extend([
        "", "## Promotion boundary", "",
        "This manifest identifies bytes and commits for rehearsal. It does not authorize a push, merge, deployment, "
        "production match, or conversion of shadow positional points into KTPR.", "",
    ])
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", action="append", default=[], metavar="NAME=PATH@REF")
    parser.add_argument("--test-dependency", action="append", default=[], metavar="NAME=PATH@REF")
    parser.add_argument("--artifact", action="append", default=[], metavar="NAME=PATH")
    parser.add_argument("--migration-dir", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        manifest = build_manifest(
            args.repository, args.test_dependency, args.artifact, args.migration_dir
        )
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "release-candidate-manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        (args.output_dir / "RELEASE_CANDIDATE_MANIFEST.md").write_text(
            render_markdown(manifest), encoding="utf-8"
        )
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"release manifest: {exc}", file=sys.stderr)
        return 2
    print(f"release manifest: {manifest['status']}")
    return 0 if manifest["status"] != "BLOCKED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
