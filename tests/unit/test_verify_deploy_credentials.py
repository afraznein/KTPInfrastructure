"""Guards for scripts/ktp-verify-deploy.py's credential path.

Every fleet wave is signed off against this script's verdict. On 2026-10-26 the
overdue 03:00 verify printed `fleet SSH password not configured` and ended
without a verdict, and nothing in its exit status distinguished that from a run
that had walked all 24 instances and found nothing wrong. A check that never ran
must not be able to look like a check that passed.

Both directions are asserted here, because a guard that refuses whether or not
it is configured is worse than the bug: it would stop every wave and teach
everyone to read past it. So:

  - no credential  -> a dedicated non-zero exit, a banner saying no host was
                      contacted, and every missing credential named at once
  - credential set -> the verification actually runs and a GREEN fleet still
                      exits 0

Nothing here contacts a host, opens a socket, or reads a real credential. The
home directory is redirected to a tmp path, and one test writes a dotfile there
so the redirection is shown to be live rather than vacuously empty.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "ktp-verify-deploy.py"

ENV_VARS = ("KTP_FLEET_SSH_PASSWORD", "KTP_RCON_PASSWORD", "KTP_FLEET_SSH_KEY")


def _load():
    spec = importlib.util.spec_from_file_location("_ktp_verify_deploy", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    # Registered before exec: @dataclass resolves its own module out of
    # sys.modules, and an unregistered one dies on a None lookup.
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(spec.name, None)
        raise
    return mod


@pytest.fixture
def vd(monkeypatch, tmp_path):
    """The module, with no credential reachable from env or home.

    Loading it at all is the first assertion: resolution used to happen at
    import, so an uncredentialed import exited the interpreter and this file
    could not have existed.
    """
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    mod = _load()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(
        mod.os.path, "expanduser",
        lambda p: str(home / p[2:]) if p.startswith("~/") else p,
    )
    mod.GAME_PASS = ""
    mod.RCON_PASS = ""
    return mod


# --------------------------------------------------------------- the control
def test_the_script_exists_and_declares_distinct_exit_codes(vd) -> None:
    """Without this every assertion below could pass on a renamed constant."""
    assert SCRIPT.is_file()
    codes = (vd.EXIT_GREEN, vd.EXIT_NOT_GREEN, vd.EXIT_FATAL, vd.EXIT_NO_CREDENTIAL)
    assert len(set(codes)) == 4, "a verdict and a refusal must not share an exit code"
    assert vd.EXIT_NO_CREDENTIAL != 0


def test_home_redirection_is_live(vd, tmp_path) -> None:
    """The fixture's silence would prove nothing if `~` resolved nowhere. Write
    the dotfile the resolver looks for and require it to be found."""
    dotfile = Path(vd.os.path.expanduser("~/.ktp_fleet_ssh_password"))
    dotfile.write_text("not-a-real-password\n", encoding="utf-8")
    assert vd.resolve_credentials(need_rcon=False) == []
    assert vd.GAME_PASS == "not-a-real-password"


# ------------------------------------------------- direction 1: it refuses
def test_absent_fleet_password_is_reported_not_resolved(vd) -> None:
    assert vd.resolve_credentials(need_rcon=False) == ["fleet SSH password"]
    assert vd.GAME_PASS == ""


def test_both_missing_credentials_are_named_in_one_pass(vd) -> None:
    """Exiting on the first one is how the rcon leg stayed hidden behind the SSH
    leg for a whole second attempt."""
    assert vd.resolve_credentials(need_rcon=True) == [
        "fleet SSH password", "rcon password",
    ]


def test_main_refuses_with_its_own_exit_code_and_contacts_nothing(
        vd, monkeypatch, capsys) -> None:
    called: list[str] = []
    monkeypatch.setattr(vd, "require_current", lambda *a, **k: None)
    monkeypatch.setattr(vd, "verify_fleet",
                        lambda *a, **k: called.append("verify") or {})
    monkeypatch.setattr(sys, "argv", ["ktp-verify-deploy.py"])

    rc = vd.main()

    assert rc == vd.EXIT_NO_CREDENTIAL
    assert called == [], "the refusal must precede anything that touches a host"
    err = capsys.readouterr().err
    assert "NO HOST WAS CONTACTED" in err
    assert "KTP_FLEET_SSH_PASSWORD" in err


def test_ssh_connect_raises_rather_than_trying_key_auth(vd, monkeypatch) -> None:
    """The old fallback connected with no password at all. Unreachable in
    practice only because import-time resolution exited first — remove that and
    it becomes the quiet path a bare run takes to contact nothing."""
    attempts: list[tuple] = []

    class _Recorder:
        def set_missing_host_key_policy(self, *a):
            pass

        def connect(self, *a, **k):
            attempts.append((a, k))

    monkeypatch.setattr(vd.paramiko, "SSHClient", _Recorder)
    with pytest.raises(RuntimeError, match="not resolved"):
        vd.ssh_connect("198.51.100.1")
    assert attempts == []


def test_runtime_versions_raise_without_an_rcon_password(vd, monkeypatch) -> None:
    sent: list = []
    monkeypatch.setattr(vd, "_RconClient", lambda **k: sent.append(k))
    with pytest.raises(vd.RconError, match="not resolved"):
        vd.collect_runtime_versions("198.51.100.1", 27015)
    assert sent == []


# ------------------------------------------------ direction 2: it still runs
def test_a_disk_only_run_does_not_require_the_rcon_password(vd, monkeypatch) -> None:
    """--check-runtime is opt-in, so demanding its credential from every run is
    the same defect pointed the other way: a gate nobody can open."""
    monkeypatch.setenv("KTP_FLEET_SSH_PASSWORD", "fixture-ssh")
    assert vd.resolve_credentials(need_rcon=False) == []
    assert vd.GAME_PASS == "fixture-ssh"
    assert vd.RCON_PASS == ""


def test_a_configured_runtime_run_resolves_both(vd, monkeypatch) -> None:
    monkeypatch.setenv("KTP_FLEET_SSH_PASSWORD", "fixture-ssh")
    monkeypatch.setenv("KTP_RCON_PASSWORD", "fixture-rcon")
    assert vd.resolve_credentials(need_rcon=True) == []
    assert (vd.GAME_PASS, vd.RCON_PASS) == ("fixture-ssh", "fixture-rcon")


def test_main_runs_the_verification_and_a_green_fleet_still_exits_zero(
        vd, monkeypatch, capsys) -> None:
    monkeypatch.setenv("KTP_FLEET_SSH_PASSWORD", "fixture-ssh")
    monkeypatch.setattr(vd, "require_current", lambda *a, **k: None)
    seen: list = []

    def _fake_verify(reference, scope, include_engine, check_runtime=False):
        seen.append((reference, scope, include_engine, check_runtime))
        return {"overall": "green", "counts": {"green": 24}, "instances": {}}

    monkeypatch.setattr(vd, "verify_fleet", _fake_verify)
    monkeypatch.setattr(sys, "argv", ["ktp-verify-deploy.py"])

    rc = vd.main()

    assert rc == vd.EXIT_GREEN
    assert len(seen) == 1, "a configured run must actually verify, not just pass"
    assert "REFUSING TO RUN" not in capsys.readouterr().err


def test_main_still_separates_a_red_fleet_from_a_refusal(vd, monkeypatch) -> None:
    monkeypatch.setenv("KTP_FLEET_SSH_PASSWORD", "fixture-ssh")
    monkeypatch.setattr(vd, "require_current", lambda *a, **k: None)
    monkeypatch.setattr(
        vd, "verify_fleet",
        lambda *a, **k: {"overall": "red", "counts": {"red": 1}, "instances": {}})
    monkeypatch.setattr(sys, "argv", ["ktp-verify-deploy.py"])
    assert vd.main() == vd.EXIT_NOT_GREEN


# ------------------------------------------- the whole process, not just main
def test_help_is_readable_with_no_credential_configured() -> None:
    """A real process, because the regression was at import: argparse never got
    to run, so `--help` printed nothing and exited 1. No network and no fleet —
    argparse exits before the freshness guard."""
    env = {k: v for k, v in os.environ.items() if k not in ENV_VARS}
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True, text=True, env=env, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    assert "--check-runtime" in proc.stdout
