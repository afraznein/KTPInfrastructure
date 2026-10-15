"""scripts/ktp-map-coefficients-refit.sh -- the weekly refit must not move $REPO.

$REPO is `/opt/ktp-reports/KTPInfrastructure`, which SERVES: report jobs read it.
The first version of this script ran `git checkout -B map-coefficients/<date>`
in $REPO and changed back on only two paths -- the clean exit and the last line.
Under `set -e` everything between them exits immediately, so a failed fit left
the serving checkout parked on a dated branch with nothing saying so; and even
the success path served a dated branch for the length of the fit.

So the test that matters is behavioural, not textual: run the thing against a
throwaway repo, fail it in the middle, and assert the repo is still on the ref
it started on. The static asserts below only guard the shape that makes that
true. A `python3` shim on PATH stands in for the fit, so the whole file needs
nothing but bash and git.
"""
import os
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ktp-map-coefficients-refit.sh"
UNIT = ROOT / "scripts" / "ktp-map-coefficients.service"
# ⚠️ On Windows a bare `bash` resolves to WSL's, which cannot read a C:\... path
# and exits 127 -- every behavioural test below then fails for a reason that has
# nothing to do with the script. Point KTP_TEST_BASH at git-bash there:
#   KTP_TEST_BASH="C:\Program Files\Git\usr\bin\bash.exe"
BASH = os.environ.get("KTP_TEST_BASH", "bash")

pytestmark = pytest.mark.skipif(
    shutil.which(BASH) is None or shutil.which("git") is None,
    reason="needs bash and git",
)

TEXT = SCRIPT.read_text(encoding="utf-8")


def code_lines():
    """Non-comment lines only.

    The header comment deliberately QUOTES the removed `git checkout -B` in order
    to forbid it, so a grep over the whole file would fire on the explanation
    rather than on a regression.
    """
    out = []
    for ln in TEXT.split("\n"):
        s = ln.strip()
        if not s or s.startswith("#"):
            continue
        out.append(ln)
    return "\n".join(out)


# --------------------------------------------------------------------------
# the regression
# --------------------------------------------------------------------------

def test_it_is_syntactically_valid():
    p = subprocess.run([BASH, "-n", str(SCRIPT)], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr


def test_the_serving_checkout_is_never_moved():
    """THE regression. Any `git checkout` in executable code is one."""
    assert "git checkout" not in code_lines()


def test_the_explanation_survives():
    """Keep the reason, or the next reader reintroduces the checkout."""
    assert "NEVER MOVES $REPO" in TEXT
    assert "SERVING" in TEXT


def test_it_works_in_a_worktree_off_origin_main():
    code = code_lines()
    assert "git worktree add" in code
    assert "--detach" in code, "a dated local branch in $REPO reads as work in progress"
    assert "origin/main" in code


def test_the_fit_runs_inside_the_worktree():
    """Fitting in $REPO is the same defect by another route."""
    code = code_lines()
    i_cd = code.index('cd "$WORKTREE"')
    i_fit = code.index("scripts.fit_map_coefficients")
    assert i_cd < i_fit, "the fit must run after cd into the worktree"


def test_cleanup_is_trapped_and_cannot_fail_the_run():
    code = code_lines()
    assert re.search(r"^trap drop_worktree EXIT", code, re.M), "cleanup is not trapped"
    body = code.split("drop_worktree() {", 1)[1].split("}", 1)[0]
    assert body.count("|| true") >= 3, "a failing cleanup must not fail a finished refit"
    assert "prune" in body, "a crashed run must not block the next one"


def test_cleanup_names_one_path_and_never_a_glob():
    """This repo has other registered worktrees; a sweep would unregister them."""
    body = code_lines().split("drop_worktree() {", 1)[1].split("}", 1)[0]
    for line in body.split("\n"):
        if "worktree remove" in line or "rm -rf" in line:
            assert '"$WORKTREE"' in line, "cleanup targets something other than $WORKTREE: %s" % line
            assert "*" not in line, "cleanup uses a glob: %s" % line


def test_the_push_names_the_remote_branch_explicitly():
    """The commit is on a detached HEAD, so `git push origin $BRANCH` has no
    local ref to resolve."""
    code = code_lines()
    assert "HEAD:refs/heads/$BRANCH" in code


def test_strict_mode_and_documented_exit_codes():
    assert "set -euo pipefail" in code_lines()
    assert "0 nothing changed or PR opened, 1 the refit itself failed" in TEXT


def test_the_unit_still_points_at_this_script():
    if not UNIT.is_file():
        pytest.skip("unit file not in this tree")
        return
    assert "ktp-map-coefficients-refit.sh" in UNIT.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# behaviour: the thing the old version got wrong
# --------------------------------------------------------------------------

FIT_SHIM = """#!/usr/bin/env bash
# Stands in for `python3 -m scripts.fit_map_coefficients`.
# KTP_FIT_CHECK: exit code for --check (0 = table matches, nothing to propose)
# KTP_FIT_WRITE: exit code for --write
# KTP_FIT_NOCHANGE: --write succeeds but leaves the table alone, which is what
#   the real fitter does when no coefficient moved
# KTP_FIT_PROBE: where to record what $REPO looks like WHILE the fit is running
if [ -n "${KTP_FIT_PROBE:-}" ]; then
  git -C "$REPO" rev-parse --abbrev-ref HEAD >> "$KTP_FIT_PROBE" 2>&1 || true
fi
for a in "$@"; do
  case "$a" in
    --check) exit "${KTP_FIT_CHECK:-0}" ;;
    --write)
      if [ "${KTP_FIT_WRITE:-0}" -ne 0 ]; then exit "$KTP_FIT_WRITE"; fi
      if [ -n "${KTP_FIT_NOCHANGE:-}" ]; then exit 0; fi
      echo '{"maps":{"dod_donner":1.25}}' > config/map_coefficients.json
      exit 0 ;;
  esac
done
exit 0
"""


def _git(cwd, *args):
    p = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True)
    assert p.returncode == 0, "git %s failed: %s" % (" ".join(args), p.stderr)
    return p.stdout.strip()


@pytest.fixture
def world(tmp_path):
    """A bare 'origin', a serving clone on a branch called `serving`, and a
    python3 shim on PATH."""
    upstream = tmp_path / "upstream.git"
    _git(tmp_path, "init", "--quiet", "--bare", str(upstream))

    repo = tmp_path / "repo"
    _git(tmp_path, "clone", "--quiet", str(upstream), str(repo))
    (repo / "config").mkdir()
    (repo / "config" / "map_coefficients.json").write_text('{"maps":{}}\n', encoding="utf-8")
    _git(repo, "add", "-A")
    # -c on the seed only: the repo must be left WITHOUT a stored identity, or
    # the script inherits one and this suite cannot see the production failure.
    _git(repo, "-c", "user.email=seed@example.invalid", "-c", "user.name=seed",
         "commit", "--quiet", "-m", "seed")
    _git(repo, "branch", "-M", "main")
    _git(repo, "push", "--quiet", "origin", "main")
    # the serving checkout sits on its own branch, which must survive every run
    _git(repo, "checkout", "--quiet", "-b", "serving")

    bindir = tmp_path / "bin"
    bindir.mkdir()
    shim = bindir / "python3"
    shim.write_text(FIT_SHIM.replace("\r\n", "\n"), encoding="utf-8", newline="\n")
    shim.chmod(0o755)

    return {
        "repo": repo,
        # never created -- git reads a missing config file as an empty one
        "noconfig": tmp_path / "no-such-gitconfig",
        "log": tmp_path / "refit.log",
        "proposal": tmp_path / "proposal",
        "worktree": tmp_path / "wt",
        "bindir": bindir,
    }


def _run(world, **extra):
    env = dict(os.environ)
    env["PATH"] = str(world["bindir"]) + os.pathsep + env["PATH"]
    env.update({
        "REPO": str(world["repo"]),
        "LOG": str(world["log"]),
        "PROPOSAL": str(world["proposal"]),
        "WORKTREE": str(world["worktree"]),
        # ktpreports is a nologin account with no home directory and no
        # gitconfig. Point git's user AND system config at a file that does not
        # exist, so this suite cannot borrow an identity the data server lacks.
        # The old fixture pointed GIT_CONFIG_GLOBAL at a config it had just
        # written an identity into, which is why a suite with a "commits and
        # pushes" case never saw `git commit` exit 128 on the box.
        "GIT_CONFIG_GLOBAL": str(world["noconfig"]),
        "GIT_CONFIG_SYSTEM": str(world["noconfig"]),
    })
    for k in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME",
              "GIT_COMMITTER_EMAIL", "EMAIL"):
        env.pop(k, None)
    env.update({k: str(v) for k, v in extra.items()})
    p = subprocess.run([BASH, str(SCRIPT)], capture_output=True, text=True, env=env)
    log = world["log"].read_text(encoding="utf-8", errors="replace") if world["log"].exists() else ""
    return p.returncode, log


def test_a_clean_run_leaves_the_serving_branch_alone(world):
    rc, log = _run(world, KTP_FIT_NOCHANGE=1)
    assert rc == 0, log
    assert "nothing to propose" in log
    assert _git(world["repo"], "rev-parse", "--abbrev-ref", "HEAD") == "serving"
    assert not world["worktree"].exists(), "the scratch worktree was left behind"


def test_a_failure_midway_still_leaves_the_serving_branch_alone(world):
    """The old version's exact failure: the fit dies, which is after the point
    the old script had already moved $REPO onto a dated branch."""
    rc, log = _run(world, KTP_FIT_WRITE=3)
    assert rc != 0, "a failed fit must not report success\n" + log
    assert _git(world["repo"], "rev-parse", "--abbrev-ref", "HEAD") == "serving", \
        "the serving checkout was stranded off its branch -- this is the whole bug"
    assert not world["worktree"].exists()


def test_no_dated_branch_is_left_in_the_serving_repo(world):
    """--detach exists so a run leaves nothing that reads as work in progress."""
    _run(world, KTP_FIT_WRITE=3)
    branches = _git(world["repo"], "branch", "--list", "map-coefficients/*")
    assert branches == "", "a dated local branch was left behind: %r" % branches


def test_a_real_proposal_commits_pushes_and_writes_the_artifacts(world):
    rc, log = _run(world, KTP_FIT_WRITE=0)
    assert rc == 0, log
    # $REPO untouched even on the success path
    assert _git(world["repo"], "rev-parse", "--abbrev-ref", "HEAD") == "serving"
    # the detached push landed a remote branch
    remote = _git(world["repo"], "ls-remote", "--heads", "origin", "map-coefficients/*")
    assert "map-coefficients/" in remote, "the detached push did not land:\n" + log
    # and the artifacts a human reads are there, trailer included
    body = (world["proposal"] / "body.md").read_text(encoding="utf-8")
    assert re.search(r"^Coordination-Workstream: infra-hidden-value-plays$", body, re.M)
    assert (world["proposal"] / "map_coefficients.proposed.json").is_file()
    assert list(world["proposal"].glob("0001-*.patch"))
    assert not world["worktree"].exists()


def test_the_serving_repo_is_on_its_own_branch_while_the_fit_runs(world, tmp_path):
    """Not just afterwards. The old version moved $REPO before the fit and put it
    back after, so report jobs reading $REPO during the fit -- which is the slow
    part -- saw a dated branch. The shim records what $REPO looks like at the
    moment it is called, which is the only window where that is observable."""
    probe = tmp_path / "probe.txt"
    rc, log = _run(world, KTP_FIT_WRITE=0, KTP_FIT_PROBE=str(probe))
    assert rc == 0, log
    seen = [ln for ln in probe.read_text(encoding="utf-8").split("\n") if ln.strip()]
    assert seen, "the probe never fired"
    assert set(seen) == {"serving"}, \
        "$REPO was off its branch while the fit ran: %r" % seen


def test_a_leftover_worktree_from_a_crashed_run_does_not_block_the_next(world):
    world["worktree"].mkdir(parents=True)
    (world["worktree"] / "junk").write_text("stale\n", encoding="utf-8")
    rc, log = _run(world, KTP_FIT_NOCHANGE=1)
    assert rc == 0, "a stale worktree path blocked the run\n" + log
    assert "nothing to propose" in log


# --------------------------------------------------------------------------
# found by running it: 2026-10-14, the first real run
# --------------------------------------------------------------------------

def test_the_fit_runs_exactly_once():
    """It ran three times -- --check to decide, --write to produce, --check again
    to render the diff -- at ~64 min a pass measured on 2026-10-14, against
    TimeoutStartSec=3h. Each pass also re-queries the labels, so the third one
    described a different fit than the table being committed."""
    n = code_lines().count("scripts.fit_map_coefficients")
    assert n == 1, "the fit runs %d times; each pass is ~64 min and the cap is 3h" % n


def test_the_commit_carries_its_own_author_identity(world):
    """ktpreports is a nologin account with no home directory and no gitconfig,
    so a bare `git commit` exits 128 'Author identity unknown'. The first real
    run died exactly there, two hours in, with the fit already finished."""
    rc, log = _run(world, KTP_FIT_WRITE=0)
    assert rc == 0, "the commit could not name an author:\n" + log
    assert "Author identity unknown" not in log
    assert list(world["proposal"].glob("0001-*.patch")), log


def test_the_fit_survives_a_commit_that_fails(world):
    """A commit can fail for reasons that cost seconds; the fit costs an hour,
    and the EXIT trap removes the worktree it lives in. So the proposal has to
    be outside the worktree BEFORE the first git step, not after it."""
    hooks = world["repo"] / ".git" / "hooks"
    hooks.mkdir(parents=True, exist_ok=True)
    hook = hooks / "pre-commit"
    hook.write_text("#!/bin/sh" + chr(10) + "exit 1" + chr(10),
                    encoding="utf-8", newline="")
    hook.chmod(0o755)

    rc, log = _run(world, KTP_FIT_WRITE=0)
    assert rc != 0, "a failed commit must not report success\n" + log
    proposed = world["proposal"] / "map_coefficients.proposed.json"
    assert proposed.is_file(), \
        "an hour of fitting was discarded by a failed commit\n" + log
    assert "dod_donner" in proposed.read_text(encoding="utf-8")
    assert (world["proposal"] / "diff.txt").is_file(), "the diff was lost too"
