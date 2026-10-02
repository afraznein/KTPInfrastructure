"""scripts/ktp-wave-sweep.py: the workstation sweep runs a ledger the guard can prove current.

From 2026-09-21 the sweep exported ktp-wave-ledger.py from origin/main into a
temp directory and ran it there. ktp_script_freshness.py refused it every night
-- "it is not under <checkout>" -- because a copy outside any checkout has no
provenance. The guard was right. The wrapper now keeps a dedicated clone at
origin/main and runs the ledger inside it.

Everything here runs against a throwaway upstream repo carrying a stub ledger
that calls the REAL freshness guard, copied from this tree. The guard is inert
under pytest, so the child processes run with the pytest markers stripped:
these tests exercise the guard for real, not its test-mode short circuit.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "scripts" / "ktp-wave-sweep.py"
GUARD = ROOT / "scripts" / "ktp_script_freshness.py"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")

STUB_LEDGER = '''\
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ktp_script_freshness import require_current
VERSION = "{version}"
require_current(__file__, also=["deploy-to-fleet.py"], purpose="test")
print("SWEPT", VERSION, os.environ.get("KTP_FRESHNESS_BYPASS", "-"))
sys.exit(int(os.environ.get("STUB_RC", "0")))
'''

GIT_ENV = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
           "GIT_CONFIG_NOSYSTEM": "1"}


def git(cwd, *args):
    r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True,
                       env=dict(os.environ, **GIT_ENV))
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


def clean_env(**extra):
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTEST_CURRENT_TEST", "GITHUB_ACTIONS")
           and not k.startswith("KTP_FRESHNESS")}
    env.update(GIT_ENV)
    env.update(extra)
    return env


class Upstream:
    def __init__(self, tmp: Path):
        self.bare = tmp / "upstream.git"
        self.work = tmp / "upstream-work"
        subprocess.run(["git", "init", "--quiet", "--bare", "-b", "main", str(self.bare)],
                       check=True, env=dict(os.environ, **GIT_ENV))
        subprocess.run(["git", "init", "--quiet", "-b", "main", str(self.work)],
                       check=True, env=dict(os.environ, **GIT_ENV))
        git(self.work, "remote", "add", "origin", str(self.bare))
        (self.work / "scripts").mkdir()
        shutil.copy(GUARD, self.work / "scripts" / "ktp_script_freshness.py")
        (self.work / "scripts" / "deploy-to-fleet.py").write_text("# stub\n", newline="\n")
        self.commit("v1")

    @property
    def url(self) -> str:
        return self.bare.as_posix()

    def commit(self, version: str) -> None:
        (self.work / "scripts" / "ktp-wave-ledger.py").write_text(
            STUB_LEDGER.format(version=version), newline="\n")
        git(self.work, "add", "-A")
        git(self.work, "commit", "--quiet", "-m", version)
        git(self.work, "push", "--quiet", "origin", "main")


@pytest.fixture
def setup(tmp_path):
    up = Upstream(tmp_path)
    rows = tmp_path / "SKILL.md"
    rows.write_text("| Component | Live |\n|---|---|\n", encoding="utf-8")
    tree = tmp_path / "home" / ".ktp" / "wave-sweep-tree"
    state = tmp_path / "state.json"

    def run(**extra):
        env = clean_env(KTP_CLAUDE_MD=str(rows), KTP_WAVE_SWEEP_TREE=str(tree),
                        KTP_WAVE_SWEEP_REMOTE=up.url, KTP_WAVE_SWEEP_STATE=str(state),
                        KTP_FLEET_SSH_PASSWORD="not-a-real-one", **extra)
        r = subprocess.run([sys.executable, str(WRAPPER)], capture_output=True, text=True,
                           env=env, timeout=120)
        recorded = json.loads(state.read_text(encoding="utf-8")) if state.exists() else None
        return r, recorded

    return up, tree, run


# --- the fix -------------------------------------------------------------------


def test_first_run_clones_and_the_guard_lets_the_ledger_run(setup):
    up, tree, run = setup
    r, rec = run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SWEPT v1" in r.stdout
    assert "REFUSING" not in r.stdout + r.stderr
    assert rec["rc"] == 0
    assert (tree / ".git").exists()


def test_a_newer_main_is_what_runs_next(setup):
    up, tree, run = setup
    run()
    up.commit("v2")
    r, _ = run()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SWEPT v2" in r.stdout


def test_an_edited_tree_is_refused_and_the_edit_is_kept(setup):
    up, tree, run = setup
    run()
    ledger = tree / "scripts" / "ktp-wave-ledger.py"
    ledger.write_text(ledger.read_text() + "# local edit\n", newline="\n")
    r, rec = run()
    assert r.returncode == 2
    assert "not discarding" in r.stderr
    assert rec["rc"] == 2
    assert ledger.read_text().endswith("# local edit\n")


def test_ambient_guard_overrides_do_not_reach_the_ledger(setup):
    up, tree, run = setup
    r, _ = run(KTP_FRESHNESS_BYPASS="leaked from a shell", KTP_FRESHNESS_REPO="/elsewhere")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "SWEPT v1 -" in r.stdout


def test_an_unreachable_remote_is_could_not_look(setup):
    up, tree, run = setup
    run()
    up.bare.rename(up.bare.with_name("moved-away.git"))   # git objects are read-only on Windows
    r, rec = run()
    assert r.returncode == 2
    assert rec["rc"] == 2


def test_a_tree_tracking_another_remote_is_refused(setup, tmp_path):
    up, tree, run = setup
    run()
    git(tree, "remote", "set-url", "origin", (tmp_path / "other.git").as_posix())
    r, _ = run()
    assert r.returncode == 2
    assert "tracks" in r.stderr


@pytest.mark.parametrize(("child", "expect"), [("1", 1), ("3", 2), ("7", 2)])
def test_the_exit_contract_is_kept(setup, child, expect):
    up, tree, run = setup
    r, rec = run(STUB_RC=child)
    assert r.returncode == expect
    assert rec["rc"] == expect


# --- the guard is not weakened: copies it cannot prove are still refused --------


def test_an_exported_copy_is_still_refused(setup, tmp_path):
    """The old wrapper's shape: the blob outside any checkout, the repo named by env."""
    up, tree, run = setup
    run()
    export = tmp_path / "_from-main"
    export.mkdir()
    for name in ("ktp-wave-ledger.py", "deploy-to-fleet.py", "ktp_script_freshness.py"):
        shutil.copy(tree / "scripts" / name, export / name)
    r = subprocess.run([sys.executable, str(export / "ktp-wave-ledger.py"), "sweep"],
                       capture_output=True, text=True, timeout=120,
                       env=clean_env(KTP_FRESHNESS_REPO=str(tree)))
    assert r.returncode == 3
    assert "REFUSING TO RUN ktp-wave-ledger.py" in r.stderr
    assert "is not under" in r.stderr


def test_a_stale_checkout_is_still_refused(setup):
    """A tree left at an older commit while origin/main moved on."""
    up, tree, run = setup
    run()
    up.commit("v2")
    git(tree, "fetch", "--quiet", "origin", "main")
    r = subprocess.run([sys.executable, str(tree / "scripts" / "ktp-wave-ledger.py"), "sweep"],
                       capture_output=True, text=True, timeout=120, cwd=tree, env=clean_env())
    assert r.returncode == 3
    assert "DIFFERS from origin/main" in r.stderr
