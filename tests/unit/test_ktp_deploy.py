"""scripts/ktp-deploy.py: one shared, attributed entry point to stage-wave and the ledger.

The wrapper runs its children from a checkout it has just proven to be
origin/main, behind a lock, against the shared ledger and rows, with the person's
name attached. Each case runs the real wrapper against a throwaway upstream whose
stage-wave.py / ktp-wave-ledger.py are stubs that call the REAL freshness guard
and then report the argv and environment they were given. The pytest markers are
stripped from the child environment, so the guard runs for real.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "scripts" / "ktp-deploy.py"
GUARD = ROOT / "scripts" / "ktp_script_freshness.py"

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="needs git")

STUB = '''\
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ktp_script_freshness import require_current
require_current(__file__, also=["deploy-to-fleet.py"], purpose="test")
keys = ("KTP_DEPLOY_ACTOR", "KTP_CLAUDE_MD", "KTP_WAVE_LEDGER_DIR", "KTP_FLEET_SSH_KEY",
        "KTP_FLEET_SSH_PASSWORD", "KTP_FRESHNESS_BYPASS")
print("CHILD " + json.dumps({{"name": "{name}", "argv": sys.argv[1:],
                             "env": {{k: os.environ.get(k) for k in keys}}}}))
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
    drop = ("PYTEST_CURRENT_TEST", "GITHUB_ACTIONS", "SUDO_USER", "KTP_FLEET_SSH_KEY",
            "KTP_FLEET_SSH_PASSWORD", "KTP_CLAUDE_MD", "KTP_WAVE_LEDGER_DIR", "KTP_DEPLOY_ACTOR")
    env = {k: v for k, v in os.environ.items()
           if k not in drop and not k.startswith("KTP_FRESHNESS") and not k.startswith("GIT_CONFIG")}
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
        for name in ("stage-wave.py", "ktp-wave-ledger.py"):
            (self.work / "scripts" / name).write_text(STUB.format(name=name), newline="\n")
        git(self.work, "add", "-A")
        git(self.work, "commit", "--quiet", "-m", "v1")
        git(self.work, "push", "--quiet", "origin", "main")


@pytest.fixture
def setup(tmp_path):
    up = Upstream(tmp_path)
    home = tmp_path / "deploy-home"
    home.mkdir()
    (home / "fleet-versions.md").write_text("| Component | Live |\n|---|---|\n", encoding="utf-8")
    tree = tmp_path / "opt" / "KTPInfrastructure"

    def run(*argv, **extra):
        base = dict(KTP_DEPLOY_HOME=str(home), KTP_DEPLOY_TREE=str(tree),
                    KTP_DEPLOY_REMOTE=up.bare.as_posix(),
                    KTP_DEPLOY_PASSWORD_FILE=str(tmp_path / "no-such-file"),
                    KTP_FLEET_SSH_PASSWORD="not-a-real-one")
        base.update(extra)
        env = clean_env(**{k: v for k, v in base.items() if v is not None})
        r = subprocess.run([sys.executable, str(WRAPPER), *argv], capture_output=True,
                           text=True, env=env, timeout=120)
        child = None
        for ln in r.stdout.splitlines():
            if ln.startswith("CHILD "):
                child = json.loads(ln[6:])
        return r, child

    return up, home, tree, run


def _audit(home: Path) -> list[dict]:
    p = home / "audit.log"
    return [json.loads(ln) for ln in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def test_stage_runs_from_a_proven_tree_against_the_shared_state(setup):
    up, home, tree, run = setup
    r, child = run("stage", "-f", "x.amxx")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "REFUSING" not in r.stdout + r.stderr
    assert child["name"] == "stage-wave.py"
    assert child["env"]["KTP_CLAUDE_MD"] == str(home / "fleet-versions.md")
    assert child["env"]["KTP_WAVE_LEDGER_DIR"] == str(home / "waves")
    assert child["env"]["KTP_DEPLOY_ACTOR"]
    assert (tree / ".git").exists()


def test_stage_preserves_the_live_build_by_default(setup):
    up, home, tree, run = setup
    _, child = run("stage", "-f", "x.amxx")
    i = child["argv"].index("--pull-live")
    assert child["argv"][i + 1].startswith(str(home / "rollback"))


@pytest.mark.parametrize("flag", ["--preflight-only", "--dry-run"])
def test_a_stage_that_writes_nothing_pulls_nothing(setup, flag):
    _, _, _, run = setup
    _, child = run("stage", flag)
    assert "--pull-live" not in child["argv"]


def test_no_pull_live_is_consumed_by_the_wrapper(setup):
    _, _, _, run = setup
    _, child = run("stage", "--no-pull-live", "-f", "x.amxx")
    assert child["argv"] == ["-f", "x.amxx"]


def test_an_explicit_pull_live_is_left_alone(setup, tmp_path):
    _, _, _, run = setup
    _, child = run("stage", "--pull-live", str(tmp_path / "mine"), "-f", "x.amxx")
    assert child["argv"].count("--pull-live") == 1
    assert str(tmp_path / "mine") in child["argv"]


def test_ledger_commands_pass_through(setup):
    _, _, _, run = setup
    r, child = run("ledger", "status", "--all")
    assert r.returncode == 0, r.stderr
    assert child["name"] == "ktp-wave-ledger.py"
    assert child["argv"] == ["status", "--all"]


def test_ambient_guard_overrides_do_not_reach_the_child(setup):
    _, _, _, run = setup
    r, child = run("ledger", "status", KTP_FRESHNESS_BYPASS="leaked from a shell")
    assert r.returncode == 0, r.stderr
    assert child["env"]["KTP_FRESHNESS_BYPASS"] is None


def test_a_held_lock_refuses_and_names_the_holder(setup):
    up, home, tree, run = setup
    spec = importlib.util.spec_from_file_location("ktp_deploy", WRAPPER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with mod.Lock(str(home / "stage.lock"), "someone-else"):
        r, child = run("stage", "-f", "x.amxx")
    assert r.returncode == 2
    assert child is None
    assert "someone-else" in r.stderr
    assert _audit(home)[-1]["refused"]


def test_missing_rows_refuse_before_anything_runs(setup):
    up, home, tree, run = setup
    (home / "fleet-versions.md").unlink()
    r, child = run("stage", "-f", "x.amxx")
    assert r.returncode == 2 and child is None
    assert "version rows not found" in r.stderr
    assert not tree.exists()


def test_no_credential_refuses_before_anything_runs(setup):
    _, home, tree, run = setup
    r, child = run("stage", "-f", "x.amxx", KTP_FLEET_SSH_PASSWORD=None,
                   HOME=str(home), USERPROFILE=str(home))
    assert r.returncode == 2 and child is None
    assert "no fleet credential" in r.stderr


def test_a_per_person_key_in_home_is_picked_up(setup):
    _, home, _, run = setup
    (home / ".ssh").mkdir()
    (home / ".ssh" / "ktp_deploy_ed25519").write_text("k", encoding="utf-8")
    _, child = run("ledger", "status", KTP_FLEET_SSH_PASSWORD=None,
                   HOME=str(home), USERPROFILE=str(home))
    assert child["env"]["KTP_FLEET_SSH_KEY"] == str(home / ".ssh" / "ktp_deploy_ed25519")
    assert child["env"]["KTP_FLEET_SSH_PASSWORD"] is None


def test_the_shared_password_file_is_the_fallback(setup, tmp_path):
    _, home, _, run = setup
    pw = tmp_path / "fleet-ssh-password"
    pw.write_text("from-the-file\n", encoding="utf-8")
    _, child = run("ledger", "status", KTP_FLEET_SSH_PASSWORD=None, KTP_DEPLOY_PASSWORD_FILE=str(pw),
                   HOME=str(home), USERPROFILE=str(home))
    assert child["env"]["KTP_FLEET_SSH_PASSWORD"] == "from-the-file"


def test_every_run_is_audited_with_actor_commit_and_exit_code(setup):
    up, home, tree, run = setup
    run("stage", "-f", "x.amxx", STUB_RC="1")
    rec = _audit(home)[-1]
    assert rec["cmd"] == "stage" and rec["rc"] == 1
    assert rec["actor"] and rec["commit"] == git(tree, "rev-parse", "HEAD")
    assert "not-a-real-one" not in (home / "audit.log").read_text(encoding="utf-8")


def test_an_edited_shared_tree_is_refused_and_kept(setup):
    up, home, tree, run = setup
    run("ledger", "status")
    sw = tree / "scripts" / "stage-wave.py"
    sw.write_text(sw.read_text() + "# hand edit\n", newline="\n")
    r, child = run("stage", "-f", "x.amxx")
    assert r.returncode == 2 and child is None
    assert sw.read_text().endswith("# hand edit\n")


def test_actor_override_is_ignored_for_a_non_root_caller(setup):
    _, _, _, run = setup
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("running as root, where the override is the point")
    _, child = run("ledger", "status", KTP_DEPLOY_ACTOR="someone-i-am-not")
    assert child["env"]["KTP_DEPLOY_ACTOR"] != "someone-i-am-not"
