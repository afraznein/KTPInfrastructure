"""run-fleet-script.py: the three properties that make it safe to hand a live
credential to, and the one that makes it usable from a worktree.

This script exists because `stage-wave.py` could not be run as documented on the
operator workstation -- it reads the dodserver credential from an env var or a
file on disk, and project policy puts it in neither -- so every wave was staged
through a hand-written throwaway shim in a temp directory. The gap was the
invocation, not the tool.

A convenience wrapper that runs with a live fleet credential earns tests on the
parts that are easy to regress by making it more convenient:

- The ALLOWLIST. It passes a credential to whatever it execs, so what it may exec
  is explicit. Widening it to "anything in scripts/" is the obvious convenience
  change and is the one that must not happen quietly.
- GUARD OVERRIDES ARE NOT FORWARDED. `KTP_FRESHNESS_BYPASS` and friends loosen the
  freshness guard the child runs behind. A wrapper that passed them through would
  turn that guard into decoration, and would do it invisibly. The drop is also
  announced, because a silent drop reads as the guard having passed.
- AN ALREADY-SET CREDENTIAL IS HONOURED, so the ktp_hosts import -- the only step
  that touches live values -- does not happen when it is not needed. These tests
  rely on that: they set a dummy password and never import ktp_hosts.
- KTP_HOSTS_DIR. Fleet scripts must run from a detached worktree at origin/main,
  and a worktree on another drive has no project root above it. Without the
  override the default resolves to a directory holding neither the rows nor
  ktp_hosts.py, which is the trap the script is meant to remove rather than
  reproduce.
"""
import importlib.util
import os
import subprocess
import sys

import pytest

SCRIPT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "scripts", "run-fleet-script.py")


def load():
    """Import the script by path -- its name has a hyphen, so it is not a module."""
    spec = importlib.util.spec_from_file_location("run_fleet_script", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def mod():
    return load()


def test_script_exists():
    assert os.path.isfile(SCRIPT), SCRIPT


def test_allowlist_is_not_everything_in_scripts(mod):
    # The point of the list is that it is shorter than scripts/.
    scripts_dir = os.path.join(os.path.dirname(os.path.dirname(SCRIPT)), "scripts")
    on_disk = [f for f in os.listdir(scripts_dir) if f.endswith(".py")]
    assert len(mod.RUNNABLE) < len(on_disk)
    for name in mod.RUNNABLE:
        assert os.path.isfile(os.path.join(scripts_dir, name)), name


def test_rejects_a_script_not_on_the_allowlist(tmp_path):
    out = subprocess.run([sys.executable, SCRIPT, "definitely-not-allowed.py"],
                         capture_output=True, text=True)
    assert out.returncode != 0
    combined = out.stdout + out.stderr
    assert "allowlist" in combined
    # The refusal names the list, so the reader does not have to open the file.
    assert "stage-wave.py" in combined


def test_rejects_a_path_that_escapes_scripts_dir():
    # basename() is what confines it; a path is not a way to reach elsewhere.
    out = subprocess.run([sys.executable, SCRIPT, "../../../bin/sh"],
                         capture_output=True, text=True)
    assert out.returncode != 0
    assert "allowlist" in (out.stdout + out.stderr)


def test_list_names_only_allowlisted_scripts(mod):
    out = subprocess.run([sys.executable, SCRIPT, "--list"],
                         capture_output=True, text=True)
    assert out.returncode == 0
    assert sorted(out.stdout.split()) == sorted(mod.RUNNABLE)


def _env(tmp_path, **extra):
    rows = tmp_path / "SKILL.md"
    rows.write_text("rows", encoding="utf-8")
    env = dict(os.environ)
    env.pop("KTP_FLEET_SSH_KEY", None)
    env["KTP_CLAUDE_MD"] = str(rows)
    env["KTP_FLEET_SSH_PASSWORD"] = "dummy-not-a-real-credential"
    env.update(extra)
    return env


def test_guard_overrides_are_dropped_and_announced(mod, tmp_path, monkeypatch, capsys):
    for k in mod.GUARD_OVERRIDES:
        monkeypatch.setenv(k, "some reason")
    for k, v in _env(tmp_path).items():
        monkeypatch.setenv(k, v)

    env = mod.child_env("stage-wave.py")

    for k in mod.GUARD_OVERRIDES:
        assert k not in env, "%s must not reach the child" % k
    err = capsys.readouterr().err
    assert "not forwarding" in err
    # A silent drop reads as the guard having passed, so each one is named.
    for k in mod.GUARD_OVERRIDES:
        assert k in err


def test_bypass_is_refused_even_though_the_child_accepts_it(mod):
    # Belt and braces: the child documents KTP_FRESHNESS_BYPASS, so the only
    # thing stopping it is this list. Keep them in step.
    assert "KTP_FRESHNESS_BYPASS" in mod.GUARD_OVERRIDES


def test_already_set_password_is_used_without_importing_ktp_hosts(mod, tmp_path, monkeypatch):
    for k, v in _env(tmp_path).items():
        monkeypatch.setenv(k, v)
    # If child_env reached for ktp_hosts here, this would fail on a box without it.
    monkeypatch.setitem(sys.modules, "ktp_hosts", None)
    env = mod.child_env("stage-wave.py")
    assert env["KTP_FLEET_SSH_PASSWORD"] == "dummy-not-a-real-credential"


def test_a_key_suppresses_the_password_import(mod, tmp_path, monkeypatch):
    for k, v in _env(tmp_path).items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("KTP_FLEET_SSH_PASSWORD")
    monkeypatch.setenv("KTP_FLEET_SSH_KEY", str(tmp_path / "id_ed25519"))
    monkeypatch.setitem(sys.modules, "ktp_hosts", None)
    env = mod.child_env("stage-wave.py")
    # The child prefers the key, so no credential is imported for it to ignore.
    assert "KTP_FLEET_SSH_PASSWORD" not in env


def test_hosts_dir_override_moves_the_project_root(mod, tmp_path, monkeypatch):
    monkeypatch.setenv("KTP_HOSTS_DIR", str(tmp_path))
    assert mod.project_root() == os.path.abspath(str(tmp_path))


def test_project_root_defaults_to_the_parent_of_scripts(mod, monkeypatch):
    monkeypatch.delenv("KTP_HOSTS_DIR", raising=False)
    assert mod.project_root() == os.path.dirname(os.path.dirname(SCRIPT))


def test_missing_rows_fails_closed_with_a_specific_message(mod, tmp_path, monkeypatch):
    monkeypatch.setenv("KTP_CLAUDE_MD", str(tmp_path / "nope" / "SKILL.md"))
    monkeypatch.setenv("KTP_FLEET_SSH_PASSWORD", "dummy-not-a-real-credential")
    with pytest.raises(SystemExit) as exc:
        mod.child_env("stage-wave.py")
    msg = str(exc.value)
    # The row-flip gate reports an unreadable table as a failure to look, which
    # is indistinguishable from "the rows are fine" unless this says otherwise.
    assert "version rows not found" in msg
    assert "KTP_CLAUDE_MD" in msg
