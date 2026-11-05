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
- THE RCON CREDENTIAL REACHES ONLY THE SCRIPT THAT ISSUES RCON. The wrapper holds a
  live value; handing it to all five would be the convenient change. Four of them have
  no reference to KTP_RCON_PASSWORD at all.
- A MISSING FLEET_RCON_PASSWORD IS SAID, NOT GUESSED AND NOT SWALLOWED. This is the
  defect that prompted it: ktp_hosts.py had no rcon attribute, so the sanctioned path
  could not run a runtime verify, and every wave verify taken that way was missing the
  leg while reporting GREEN. The child already refuses loudly, so the wrapper only has
  to not invent a value and not stay quiet about why.
- THE NAMES SET MATCH THE NAMES READ. sync-runner-stack.py reads the fleet credential
  as GAME_SSH_PASSWORD, not KTP_FLEET_SSH_PASSWORD, so for as long as nobody ran it
  through here it was allowlisted and unusable: paramiko raised "No authentication
  methods available", which reads like a host or key fault rather than a wiring one.
  The alias table fixes that one case; the test that the names read are all either
  supplied or declared is what stops the next one, because a hand-kept table is the
  same defect one layer up.
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


# --- the rcon credential ----------------------------------------------------
# These inject a FAKE ktp_hosts rather than the real one: the point is the wiring,
# and a test that imported the real module would depend on the operator's own box.

class _FakeHosts:
    FLEET_SSH_PASSWORD = "dummy-ssh-not-a-real-credential"
    FLEET_RCON_PASSWORD = "dummy-rcon-not-a-real-credential"


def _fake_hosts(monkeypatch, **attrs):
    mod = type(sys)("ktp_hosts")
    for k, v in attrs.items():
        setattr(mod, k, v)
    monkeypatch.setitem(sys.modules, "ktp_hosts", mod)
    return mod


def test_rcon_is_imported_for_the_script_that_issues_rcon(mod, tmp_path, monkeypatch):
    for k, v in _env(tmp_path).items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("KTP_RCON_PASSWORD", raising=False)
    _fake_hosts(monkeypatch, FLEET_RCON_PASSWORD=_FakeHosts.FLEET_RCON_PASSWORD)
    env = mod.child_env("ktp-verify-deploy.py")
    assert env["KTP_RCON_PASSWORD"] == _FakeHosts.FLEET_RCON_PASSWORD


def test_rcon_is_not_handed_to_scripts_that_do_not_issue_it(mod, tmp_path, monkeypatch):
    for k, v in _env(tmp_path).items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("KTP_RCON_PASSWORD", raising=False)
    # None in sys.modules makes `import ktp_hosts` raise: if any of these reached for
    # it, this fails rather than quietly widening who gets a live credential.
    monkeypatch.setitem(sys.modules, "ktp_hosts", None)
    for name in mod.RUNNABLE:
        if name in mod.NEEDS_RCON:
            continue
        assert "KTP_RCON_PASSWORD" not in mod.child_env(name), name


def test_needs_rcon_is_narrower_than_the_allowlist(mod):
    # If these ever match, least privilege has been lost without anyone deciding to.
    assert set(mod.NEEDS_RCON) < set(mod.RUNNABLE)
    scripts_dir = os.path.join(os.path.dirname(os.path.dirname(SCRIPT)), "scripts")
    for name in mod.NEEDS_RCON:
        body = open(os.path.join(scripts_dir, name), encoding="utf-8").read()
        # the child must actually read the variable, or we are handing out a
        # credential nothing consumes
        assert "KTP_RCON_PASSWORD" in body, name
    for name in set(mod.RUNNABLE) - set(mod.NEEDS_RCON):
        body = open(os.path.join(scripts_dir, name), encoding="utf-8").read()
        assert "KTP_RCON_PASSWORD" not in body, (
            "%s reads KTP_RCON_PASSWORD but is not in NEEDS_RCON" % name)


def test_an_already_set_rcon_password_is_honoured(mod, tmp_path, monkeypatch):
    for k, v in _env(tmp_path).items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("KTP_RCON_PASSWORD", "preset-not-a-real-credential")
    monkeypatch.setitem(sys.modules, "ktp_hosts", None)
    env = mod.child_env("ktp-verify-deploy.py")
    assert env["KTP_RCON_PASSWORD"] == "preset-not-a-real-credential"


def test_a_missing_rcon_attribute_is_announced_and_not_invented(mod, tmp_path,
                                                                monkeypatch, capsys):
    """THE NEGATIVE CONTROL. The attribute absent is the state this change fixes."""
    for k, v in _env(tmp_path).items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("KTP_RCON_PASSWORD", raising=False)
    _fake_hosts(monkeypatch, FLEET_SSH_PASSWORD=_FakeHosts.FLEET_SSH_PASSWORD)
    env = mod.child_env("ktp-verify-deploy.py")
    # no value invented, and nothing empty either -- an empty string is a value the
    # child would accept and then fail an rcon handshake with
    assert "KTP_RCON_PASSWORD" not in env
    err = capsys.readouterr().err
    assert "FLEET_RCON_PASSWORD" in err
    assert "ktp-verify-deploy.py" in err


def test_an_ssh_only_run_still_resolves_ssh_when_rcon_is_absent(mod, tmp_path, monkeypatch):
    # The two must not be coupled: no rcon attribute cannot break staging a wave.
    for k, v in _env(tmp_path).items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("KTP_FLEET_SSH_PASSWORD")
    _fake_hosts(monkeypatch, FLEET_SSH_PASSWORD=_FakeHosts.FLEET_SSH_PASSWORD)
    env = mod.child_env("ktp-verify-deploy.py")
    assert env["KTP_FLEET_SSH_PASSWORD"] == _FakeHosts.FLEET_SSH_PASSWORD


def test_a_missing_ssh_attribute_still_refuses(mod, tmp_path, monkeypatch):
    # Unchanged behaviour, asserted because the resolution was restructured around it.
    for k, v in _env(tmp_path).items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("KTP_FLEET_SSH_PASSWORD")
    _fake_hosts(monkeypatch, FLEET_RCON_PASSWORD=_FakeHosts.FLEET_RCON_PASSWORD)
    with pytest.raises(SystemExit) as exc:
        mod.child_env("stage-wave.py")
    assert "FLEET_SSH_PASSWORD" in str(exc.value)


def test_the_transcript_line_names_rcon_only_when_it_was_supplied(mod):
    # The printed line is how a reader of a wave transcript knows which legs could
    # have run. It must not claim a credential that is not in the child env.
    body = open(SCRIPT, encoding="utf-8").read()
    assert 'if env.get("KTP_RCON_PASSWORD"):' in body
    assert "value not shown" in body


def test_the_ssh_alias_reaches_the_child_that_reads_it(mod, tmp_path, monkeypatch):
    # sync-runner-stack.py's fleet-reference connection reads GAME_SSH_PASSWORD and
    # passes no key, so without this it is allowlisted and cannot authenticate.
    for k, v in _env(tmp_path).items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("GAME_SSH_PASSWORD", raising=False)
    env = mod.child_env("sync-runner-stack.py")
    assert env["GAME_SSH_PASSWORD"] == env["KTP_FLEET_SSH_PASSWORD"]


def test_the_alias_is_a_copy_and_triggers_no_import(mod, tmp_path, monkeypatch):
    # The import is the only step that touches live values. An alias satisfiable from
    # what is already set must not reach for one -- None in sys.modules makes
    # `import ktp_hosts` raise, so a reach fails here rather than passing quietly.
    for k, v in _env(tmp_path).items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("GAME_SSH_PASSWORD", raising=False)
    monkeypatch.setitem(sys.modules, "ktp_hosts", None)
    env = mod.child_env("sync-runner-stack.py")
    assert env["GAME_SSH_PASSWORD"] == env["KTP_FLEET_SSH_PASSWORD"]


def test_an_already_set_alias_is_not_overwritten(mod, tmp_path, monkeypatch):
    for k, v in _env(tmp_path).items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("GAME_SSH_PASSWORD", "preset-not-a-real-credential")
    monkeypatch.setitem(sys.modules, "ktp_hosts", None)
    env = mod.child_env("sync-runner-stack.py")
    assert env["GAME_SSH_PASSWORD"] == "preset-not-a-real-credential"


def test_aliases_are_only_given_to_children_that_read_them(mod, tmp_path, monkeypatch):
    # Same least-privilege shape as NEEDS_RCON: the value is live, so a child that does
    # not read the name does not get it.
    scripts_dir = os.path.join(os.path.dirname(os.path.dirname(SCRIPT)), "scripts")
    for name, aliases in mod.SSH_PASSWORD_ALIASES.items():
        assert name in mod.RUNNABLE, name
        body = open(os.path.join(scripts_dir, name), encoding="utf-8").read()
        for alias in aliases:
            assert alias in body, "%s is given %s and never reads it" % (name, alias)
    for k, v in _env(tmp_path).items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("GAME_SSH_PASSWORD", raising=False)
    monkeypatch.setenv("KTP_RCON_PASSWORD", "preset-not-a-real-credential")
    monkeypatch.setitem(sys.modules, "ktp_hosts", None)
    for name in mod.RUNNABLE:
        if name in mod.SSH_PASSWORD_ALIASES:
            continue
        assert "GAME_SSH_PASSWORD" not in mod.child_env(name), name


def test_every_credential_name_a_child_reads_is_supplied_or_declared(mod, tmp_path,
                                                                     monkeypatch):
    """The guard that does not rot, and the one that would have caught the gap.

    Read out of each child's own source: every literal credential name it resolves
    must be one this wrapper sets, or one KNOWN_UNSATISFIED accounts for in writing.
    A child that starts reading a new name fails here until someone decides which.
    """
    for k, v in _env(tmp_path).items():
        monkeypatch.setenv(k, v)
    monkeypatch.delenv("GAME_SSH_PASSWORD", raising=False)
    monkeypatch.setenv("KTP_RCON_PASSWORD", "preset-not-a-real-credential")
    monkeypatch.setitem(sys.modules, "ktp_hosts", None)
    scripts_dir = os.path.join(os.path.dirname(os.path.dirname(SCRIPT)), "scripts")
    for name in mod.RUNNABLE:
        env = mod.child_env(name)
        target = os.path.join(scripts_dir, name)
        undeclared = [n for n in mod.unsatisfied_credentials(target, env)
                      if n not in mod.KNOWN_UNSATISFIED]
        assert not undeclared, (
            "%s reads %s, which nothing supplies and nothing declares. Either add it "
            "to SSH_PASSWORD_ALIASES or record in KNOWN_UNSATISFIED why it is fine."
            % (name, ", ".join(undeclared)))


def test_the_credential_scan_finds_a_literal_name_and_admits_its_blind_spot(mod,
                                                                            tmp_path):
    # Positive: it finds the name the gap was about.
    scripts_dir = os.path.join(os.path.dirname(os.path.dirname(SCRIPT)), "scripts")
    runner = os.path.join(scripts_dir, "sync-runner-stack.py")
    assert "GAME_SSH_PASSWORD" in mod.unsatisfied_credentials(runner, {})
    # Negative: a name with no credential word in it is not swept up.
    assert "KTP_DRIFT_REF_HOST" not in mod.unsatisfied_credentials(runner, {})
    # Blind spot, asserted so it stays documented rather than assumed away:
    # ktp-verify-deploy.py resolves its credentials through a computed name, so the
    # scan sees nothing there. An empty result means "no literal gap", not "wired".
    verify = os.path.join(scripts_dir, "ktp-verify-deploy.py")
    assert 'os.environ.get(env_var' in open(verify, encoding="utf-8").read()
    assert mod.unsatisfied_credentials(verify, {}) == []


def test_known_unsatisfied_entries_carry_a_reason(mod):
    # A bare name here would be an exemption with no argument behind it.
    for name, why in mod.KNOWN_UNSATISFIED.items():
        assert name.isupper() and len(why.split()) >= 6, name
