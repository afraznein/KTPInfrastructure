from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess

import pytest

from scripts import release_candidate_manifest as manifest


def make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "test@example.invalid"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "Test"], check=True)
    (repo / "README.md").write_text("candidate\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "candidate"], check=True)
    return repo


def test_windows_ref_spec_uses_last_at_separator():
    name, path, ref = manifest.split_ref_spec(
        r"KTPInfrastructure=G:\GIT\candidate@feat/report"
    )
    assert name == "KTPInfrastructure"
    assert str(path).replace("\\", "/").endswith("/candidate")
    assert ref == "feat/report"


def test_hash_file_records_exact_bytes(tmp_path):
    artifact = tmp_path / "plugin.amxx"
    artifact.write_bytes(b"release bytes")
    result = manifest.hash_file(artifact)
    assert result == {
        "file": "plugin.amxx",
        "bytes": 13,
        "sha256": hashlib.sha256(b"release bytes").hexdigest(),
    }


def test_collect_repository_resolves_exact_commit_without_paths(tmp_path):
    repo = make_repo(tmp_path)
    result = manifest.collect_repository("KTPInfrastructure", repo, "HEAD")
    assert len(result["sha"]) == 40
    assert result["checkout"] == repo.name
    assert "path" not in result


def test_manifest_requires_exactly_three_release_repositories(tmp_path):
    repo = make_repo(tmp_path)
    result = manifest.build_manifest(
        [f"KTPInfrastructure={repo}@HEAD"], [], [], None
    )
    assert result["status"] == "BLOCKED"
    assert "release repository set" in result["errors"][0]


@pytest.mark.parametrize("value", ["missing", "name=path", "=path@ref", "name=@ref"])
def test_invalid_repository_specs_fail(value):
    with pytest.raises(ValueError, match="expected NAME=PATH@REF"):
        manifest.split_ref_spec(value)
