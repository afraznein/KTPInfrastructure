"""deploy-to-fleet.py must not report "no credential" with the code it uses for
"some pushes failed".

Its sibling ktp-verify-deploy.py was given a dedicated code after the 2026-10-26
verify exited on an absent credential and nothing in the status said no host had
been contacted. This script had the same shape from the other end: both its
credential refusals and its own "a push failed" summary left 1, so a wrapper
reading the status could not tell a wave that half-landed from one that never
started.

Both directions are asserted, because a refusal that fires whether or not a
credential is present would stop every wave and teach everyone to read past it.
Nothing here opens a socket or reads a real credential: HOME is redirected to a
tmp path, and one test writes a dotfile there so the redirection is shown to be
live rather than vacuously empty.
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
SCRIPT = SCRIPTS / "deploy-to-fleet.py"
SIBLING = SCRIPTS / "ktp-verify-deploy.py"
GUARD = SCRIPTS / "ktp_script_freshness.py"

ENV_VARS = ("KTP_FLEET_SSH_PASSWORD", "KTP_FLEET_SSH_KEY")


def _load():
    if "paramiko" not in sys.modules:
        stub = types.ModuleType("paramiko")
        stub.SSHClient = object
        stub.AutoAddPolicy = object
        sys.modules["paramiko"] = stub
    spec = importlib.util.spec_from_file_location("_deploy_to_fleet_creds", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    except BaseException:
        sys.modules.pop(spec.name, None)
        raise
    return mod


@pytest.fixture
def d2f(monkeypatch, tmp_path):
    """The module with no credential reachable from the environment or from home."""
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    home = tmp_path / "home"
    home.mkdir()
    for var in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(var, str(home))
    monkeypatch.delenv("HOMEDRIVE", raising=False)
    monkeypatch.delenv("HOMEPATH", raising=False)
    mod = _load()
    mod._test_home = home
    return mod


# --------------------------------------------------------------- the controls
def test_the_home_redirect_is_live(d2f):
    """Without this every refusal below could be passing on the real dotfile
    being absent from this machine rather than on the redirect working."""
    resolved = Path(os.path.expanduser("~/.ktp_fleet_ssh_password"))
    assert resolved == d2f._test_home / ".ktp_fleet_ssh_password"


def test_the_codes_are_distinct(d2f):
    codes = (d2f.EXIT_OK, d2f.EXIT_NOT_ALL_PUSHED, d2f.EXIT_NO_CREDENTIAL)
    assert len(set(codes)) == 3, "a refusal and a verdict must not share an exit code"
    assert d2f.EXIT_NO_CREDENTIAL != 0


def test_it_does_not_take_the_freshness_guards_code(d2f):
    """require_current raises SystemExit(3) and the deploy ledger reads 3 as
    "the guard REFUSED and the install did not take". A second meaning for 3
    would make that reading wrong without changing it."""
    guard = GUARD.read_text(encoding="utf-8")
    assert "raise SystemExit(3)" in guard
    assert d2f.EXIT_NO_CREDENTIAL != 3


def test_it_agrees_with_the_sibling_fleet_script(d2f):
    """One meaning across the fleet scripts. Read out of the sibling's source so
    a divergence reds here instead of being discovered by a caller."""
    m = re.search(r"^EXIT_NO_CREDENTIAL = (\d+)$",
                  SIBLING.read_text(encoding="utf-8"), re.M)
    assert m, "the sibling no longer declares EXIT_NO_CREDENTIAL"
    assert int(m.group(1)) == d2f.EXIT_NO_CREDENTIAL


# ------------------------------------------------------- no credential at all
def test_absent_password_exits_on_the_credential_code(d2f, capsys):
    with pytest.raises(SystemExit) as e:
        d2f._fleet_ssh_password()
    assert e.value.code == d2f.EXIT_NO_CREDENTIAL
    assert e.value.code != d2f.EXIT_NOT_ALL_PUSHED


def test_the_refusal_names_both_sources_and_says_nothing_was_staged(d2f, capsys):
    with pytest.raises(SystemExit):
        d2f._fleet_ssh_password()
    err = capsys.readouterr().err
    assert "KTP_FLEET_SSH_PASSWORD" in err
    assert ".ktp_fleet_ssh_password" in err
    assert "nothing was staged" in err
    assert str(d2f.EXIT_NO_CREDENTIAL) in err


def test_fleet_ssh_auth_carries_the_code_out(d2f):
    """The push path calls fleet_ssh_auth, not the helper, and stage-wave.py
    imports this same function."""
    with pytest.raises(SystemExit) as e:
        d2f.fleet_ssh_auth()
    assert e.value.code == d2f.EXIT_NO_CREDENTIAL


def test_a_named_key_that_does_not_exist_is_the_same_refusal(d2f, monkeypatch, tmp_path):
    """There is deliberately no password fallback once a key is named, so this
    is also "no credential reached the fleet" and must not read as a push
    failure."""
    monkeypatch.setenv("KTP_FLEET_SSH_KEY", str(tmp_path / "absent-key"))
    monkeypatch.setenv("KTP_FLEET_SSH_PASSWORD", "pw")
    with pytest.raises(SystemExit) as e:
        d2f.fleet_ssh_auth()
    assert e.value.code == d2f.EXIT_NO_CREDENTIAL


# ------------------------------------------------------------ the other way
def test_a_configured_password_still_resolves(d2f, monkeypatch):
    monkeypatch.setenv("KTP_FLEET_SSH_PASSWORD", "pw")
    assert d2f._fleet_ssh_password() == "pw"
    assert d2f.fleet_ssh_auth() == {"password": "pw"}


def test_the_dotfile_path_still_resolves(d2f):
    (d2f._test_home / ".ktp_fleet_ssh_password").write_text("pw\n", encoding="utf-8")
    assert d2f._fleet_ssh_password() == "pw"


def test_a_named_key_that_exists_still_resolves(d2f, monkeypatch, tmp_path):
    key = tmp_path / "id_ed25519"
    key.write_text("x", encoding="utf-8")
    monkeypatch.setenv("KTP_FLEET_SSH_KEY", str(key))
    auth = d2f.fleet_ssh_auth()
    assert auth["key_filename"] == str(key)
    assert auth["allow_agent"] is False and auth["look_for_keys"] is False
