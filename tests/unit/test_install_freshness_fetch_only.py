"""scripts/ktp-install-freshness.sh refreshes its reference by FETCH ONLY.

The check compares installed files to `origin/main` in the deploy checkout,
and that checkout is never auto-pulled. So the reference has to be refreshed
without moving anything a person put there: HEAD, the index, the working
tree, and local branches -- even when the checkout's configured refspec would
write `refs/heads/*`. These tests run the real script against a throwaway
upstream and a clone of it, with a fake `ktp-install` that records its argv.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / "scripts" / "ktp-install-freshness.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("git") is None or os.name == "nt",
    reason="needs bash and git",
)

GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid",
    "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
}

FAKE_KTP_INSTALL = """#!/bin/bash
# accepts --against-ref
printf '%s\\n' "$@" > "$ARGV_LOG"
printf 'CURRENT         /usr/local/bin/a  0  KTPInfrastructure@0:scripts/a\\n'
exit 0
"""


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True,
        env={**os.environ, **GIT_ENV},
    ).stdout.strip()


def commit(work: Path, name: str, text: str) -> str:
    (work / name).write_text(text)
    git(work, "add", name)
    git(work, "commit", "-q", "-m", name)
    return git(work, "rev-parse", "HEAD")


@pytest.fixture
def estate(tmp_path: Path):
    """upstream (bare) at A, a deploy checkout detached at A, upstream then moved to B."""
    upstream = tmp_path / "upstream.git"
    git(tmp_path, "init", "-q", "--bare", "-b", "main", str(upstream))
    seed = tmp_path / "seed"
    git(tmp_path, "clone", "-q", str(upstream), str(seed))
    a = commit(seed, "tool.sh", "v1\n")
    git(seed, "push", "-q", "origin", "HEAD:main")

    checkout = tmp_path / "ktp-infra"
    git(tmp_path, "clone", "-q", str(upstream), str(checkout))
    git(checkout, "checkout", "-q", "--detach", a)
    (checkout / "tool.sh").write_text("hand edit\n")      # uncommitted, must survive
    (checkout / "untracked.txt").write_text("keep\n")

    b = commit(seed, "tool.sh", "v2\n")
    git(seed, "push", "-q", "origin", "HEAD:main")

    fake = tmp_path / "ktp-install"
    fake.write_text(FAKE_KTP_INSTALL)
    fake.chmod(0o755)
    return {"tmp": tmp_path, "checkout": checkout, "a": a, "b": b, "fake": fake}


def run(estate, **env_extra) -> subprocess.CompletedProcess:
    tmp = estate["tmp"]
    env = {
        **os.environ, **GIT_ENV,
        "KTP_INSTALL_FRESHNESS_CONF": str(tmp / "absent.conf"),
        "STATE_DIR": str(tmp / "state"),
        "KTP_INSTALL": str(estate["fake"]),
        "ARGV_LOG": str(tmp / "argv.log"),
        "FRESHNESS_REPO": str(estate["checkout"]),
    }
    env.update(env_extra)
    return subprocess.run(["bash", str(SCRIPT)], capture_output=True, text=True,
                          env=env, timeout=120)


def test_fetch_refreshes_the_reference_and_moves_nothing_else(estate):
    co = estate["checkout"]
    r = run(estate)
    assert r.returncode == 0, r.stderr

    assert git(co, "rev-parse", "origin/main") == estate["b"]
    assert git(co, "rev-parse", "HEAD") == estate["a"]
    assert (co / "tool.sh").read_text() == "hand edit\n"
    assert (co / "untracked.txt").exists()
    assert git(co, "status", "--porcelain") == "M tool.sh\n?? untracked.txt"

    result = json.loads((estate["tmp"] / "state" / "last-run.json").read_text())
    assert result["ref_commit"] == estate["b"]
    # The SHA it fetched, not "origin/main": the report re-resolving a symbolic ref
    # would let a merge landing in the second between the two turn this run red.
    argv = (estate["tmp"] / "argv.log").read_text().split()
    assert argv == ["--report", "--repo", str(co), "--against-ref", estate["b"]]


def test_a_local_branch_is_not_moved_even_by_a_heads_refspec(estate):
    """A configured refspec writing refs/heads/* would drag local main to B."""
    co = estate["checkout"]
    git(co, "branch", "-f", "main", estate["a"])
    git(co, "config", "--replace-all", "remote.origin.fetch", "+refs/heads/*:refs/heads/*")
    r = run(estate)
    assert r.returncode == 0, r.stderr
    assert git(co, "rev-parse", "refs/heads/main") == estate["a"]
    assert git(co, "rev-parse", "refs/remotes/origin/main") == estate["b"]


def test_a_checkout_on_a_branch_keeps_its_branch(estate):
    co = estate["checkout"]
    git(co, "checkout", "-q", "-B", "main", estate["a"])
    r = run(estate)
    assert r.returncode == 0, r.stderr
    assert git(co, "symbolic-ref", "HEAD") == "refs/heads/main"
    assert git(co, "rev-parse", "HEAD") == estate["a"]
    assert git(co, "rev-parse", "origin/main") == estate["b"]


def test_the_deploy_checkout_path_is_no_longer_refused(estate):
    r = run(estate, FRESHNESS_REPO="/opt/ktp-infra/does-not-exist-here")
    assert "must not be auto-pulled" not in r.stderr
    assert r.returncode == 1
    assert "does not exist" in r.stderr


@pytest.mark.parametrize("ref", ["main", "origin/", "/main"])
def test_a_ref_a_fetch_cannot_refresh_is_refused(estate, ref):
    r = run(estate, AGAINST_REF=ref)
    assert r.returncode == 2, r.stderr
    assert not (estate["tmp"] / "state" / "last-run.json").exists()


def test_a_failed_fetch_writes_no_result(estate):
    co = estate["checkout"]
    git(co, "remote", "set-url", "origin", str(estate["tmp"] / "gone.git"))
    r = run(estate)
    assert r.returncode == 1
    assert "fetch failed" in r.stderr
    assert not (estate["tmp"] / "state" / "last-run.json").exists()
    assert git(co, "rev-parse", "origin/main") == estate["a"]
# --- the baseline the report states, and what this script does about it -----
#
# The report now names the commit it compared against. This script fetched one,
# so the two must agree -- and an installed ktp-install too old to state one at
# all is the case that decides whether this is a refusal or a record. It is a
# record: that tool's comparison is sound here BECAUSE of the fetch above, so
# dying would take out a working check over missing paperwork.


def _fake(estate, body):
    """Replace the stub ktp-install with one that prints `body` before its rows."""
    f = estate["fake"]
    f.write_text("#!/bin/bash\n"
                 "# accepts --against-ref\n"      # the script's preflight greps for this
                 'printf \'%s\\n\' "$@" > "$ARGV_LOG"\n'
                 + body +
                 "printf 'CURRENT         /usr/local/bin/a  0  "
                 "KTPInfrastructure@0:scripts/a\\n'\nexit 0\n")
    f.chmod(0o755)


def test_a_stated_baseline_that_matches_is_recorded_as_stated(estate):
    _fake(estate, 'printf \'baseline        %s  %s  (verified)\\n\' "$5" "$5"\n')
    r = run(estate)
    assert r.returncode == 0, r.stderr
    result = json.loads((estate["tmp"] / "state" / "last-run.json").read_text())
    assert result["baseline_stated"] is True, result


def test_a_report_with_no_baseline_line_still_runs_and_says_so(estate):
    """An older installed ktp-install cannot state one. That is recorded, not fatal."""
    r = run(estate)
    assert r.returncode == 0, r.stderr
    result = json.loads((estate["tmp"] / "state" / "last-run.json").read_text())
    assert result["baseline_stated"] is False, result


def test_a_baseline_naming_a_different_commit_is_fatal(estate):
    """Then the rows describe neither commit, which no amount of recording fixes."""
    _fake(estate, "printf 'baseline        %s  %s  (verified)\\n' deadbeef "
                  "0000000000000000000000000000000000000000\n")
    r = run(estate)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "not the %s this run fetched" % estate["b"] in r.stderr, r.stderr
    assert not (estate["tmp"] / "state" / "last-run.json").exists()


def test_the_baseline_header_does_not_enter_the_non_fresh_set(estate):
    """Left in, it enters on the first run and posts a transition about a line that
    is working as intended -- and then never leaves."""
    _fake(estate, 'printf \'baseline        %s  %s  (verified)\\n\' "$5" "$5"\n')
    r = run(estate)
    assert r.returncode == 0, r.stderr
    non_fresh = (estate["tmp"] / "state" / "non-fresh.txt").read_text()
    assert "baseline" not in non_fresh, non_fresh
    result = json.loads((estate["tmp"] / "state" / "last-run.json").read_text())
    assert result["non_fresh"] == 0, result
