"""The drift check compares a WORKING TREE, so its report has to say which one.

Without the source: line, "in sync" reads as "in sync with main" no matter which
branch the operator had checked out — so the same box could be reported clean
and dirty on the same day and neither report would be wrong about anything it
actually said.

Every state gets a test, including UNKNOWN: a provenance line that quietly
disappears when git is unavailable leaves a report that looks measured against
the base ref.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DRIFT_PY = os.path.join(REPO_ROOT, "scripts", "ktp-lan-web-drift.py")

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git not on PATH")


def _load():
    spec = importlib.util.spec_from_file_location("ktp_lan_web_drift_prov", DRIFT_PY)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ktp_lan_web_drift_prov"] = mod
    spec.loader.exec_module(mod)
    return mod


drift = _load()


def _git(root, *args):
    subprocess.run(("git", "-C", str(root)) + args, check=True,
                   capture_output=True, text=True)


@pytest.fixture()
def repo(tmp_path):
    """A repo with sites/lan-web/app committed on a 'base' ref."""
    root = tmp_path / "repo"
    app = root / "sites" / "lan-web" / "app"
    app.mkdir(parents=True)
    (app / "main.py").write_text("original\n", encoding="utf-8")
    _git(root.parent, "init", "-q", str(root))
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "base")
    _git(root, "branch", "base")
    return root, app


@needs_git
def test_matching_tree_names_the_base_ref(repo):
    root, app = repo
    line = drift.source_provenance(str(root), str(app), "base")
    assert "sites/lan-web/app" in line
    assert "matches base" in line
    assert "DIFFERS" not in line


@needs_git
def test_uncommitted_edit_reads_as_differing(repo):
    """rsync pushes the working tree, so an uncommitted edit is a real divergence."""
    root, app = repo
    (app / "main.py").write_text("edited\n", encoding="utf-8")
    line = drift.source_provenance(str(root), str(app), "base")
    assert "DIFFERS from base" in line


@needs_git
def test_other_branch_reads_as_differing(repo):
    root, app = repo
    _git(root, "checkout", "-qb", "feat/x")
    (app / "main.py").write_text("feature\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "feature")
    line = drift.source_provenance(str(root), str(app), "base")
    assert "DIFFERS from base" in line
    assert "feat/x" in line


@needs_git
def test_changes_outside_the_app_dir_do_not_read_as_divergence(repo):
    """The scope is what rsync sends. A README edit is not a lan-web deploy."""
    root, app = repo
    (root / "README.md").write_text("unrelated\n", encoding="utf-8")
    line = drift.source_provenance(str(root), str(app), "base")
    assert "matches base" in line


@needs_git
def test_unresolvable_base_ref_says_unknown_not_matches(repo):
    root, app = repo
    line = drift.source_provenance(str(root), str(app), "origin/does-not-exist")
    assert "UNKNOWN" in line
    assert "matches" not in line


def test_non_git_directory_says_unknown_not_matches(tmp_path):
    app = tmp_path / "sites" / "lan-web" / "app"
    app.mkdir(parents=True)
    line = drift.source_provenance(str(tmp_path), str(app), "origin/main")
    assert "UNKNOWN" in line
    assert "matches" not in line


def test_source_outside_the_repo_is_called_out(tmp_path):
    """LAN_WEB_SRC can point anywhere; there is then no ref to compare against."""
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    line = drift.source_provenance(str(tmp_path / "repo"), str(outside), "origin/main")
    assert "OUTSIDE the repo" in line
    assert "matches" not in line
