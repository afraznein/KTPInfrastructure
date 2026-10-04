"""The wave ledger and fleet credential when several people stage from one box.

Per-user ledgers split the row-flip gate in two, so the shared install points
everyone at one directory. That exposes three things a single-operator ledger
never needed: an id picked by exists-then-write lets a second stager overwrite
the first's unreconciled wave; an entry with no name cannot say whose wave is
blocking the next stage; and a per-person key must not quietly fall back to
whatever other key the caller holds.

Nothing here touches the fleet or the network. paramiko is stubbed the same way
test_stage_wave_build_base.py does it.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import sys
import types

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPTS = os.path.join(_ROOT, "scripts")


def _load(mod_name, filename):
    spec = importlib.util.spec_from_file_location(mod_name, os.path.join(_SCRIPTS, filename))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


if "paramiko" not in sys.modules:
    _stub = types.ModuleType("paramiko")
    _stub.SSHClient = object
    _stub.AutoAddPolicy = object
    sys.modules["paramiko"] = _stub

wl = _load("ktp_wave_ledger_shared", "ktp-wave-ledger.py")
d2f = _load("deploy_to_fleet_shared", "deploy-to-fleet.py")

MD5_A = "a" * 32
MD5_B = "b" * 32


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("KTP_WAVE_LEDGER_DIR", str(tmp_path / "waves"))
    for k in ("KTP_DEPLOY_ACTOR", "SUDO_USER", "KTP_FLEET_SSH_KEY", "KTP_FLEET_SSH_PASSWORD"):
        monkeypatch.delenv(k, raising=False)


def _art(md5, name="KTPHudObserver.amxx"):
    return {"basename": name, "md5": md5, "remote_dir": "serverfiles/dod/addons/ktpamx/plugins"}


def _staged_at():
    return dt.datetime.now(dt.timezone.utc).timestamp() - 2 * 86400


# --- the shared ledger -----------------------------------------------------------


def test_a_racing_second_stager_does_not_overwrite_the_first(monkeypatch):
    """Both stagers looked before either wrote: the id check saw no file, twice."""
    os.makedirs(wl.ledger_dir(), exist_ok=True)
    real_exists = os.path.exists
    t = _staged_at()
    with monkeypatch.context() as m:
        m.setattr(os.path, "exists",
                  lambda p: False if os.path.basename(str(p)).startswith("wave-")
                  else real_exists(p))
        a = wl.record_wave([_art(MD5_A)], hosts=["atlanta"], targets=24, staged_at=t)
        b = wl.record_wave([_art(MD5_B, "KTPMatchHandler.amxx")], hosts=["atlanta"], targets=24,
                           staged_at=t)
    assert a != b
    md5s = sorted(e["artifacts"][0]["md5"] for _, e in wl.load_waves())
    assert md5s == [MD5_A, MD5_B]


def test_a_record_leaves_no_partial_or_temp_file_behind():
    wl.record_wave([_art(MD5_A)], hosts=["atlanta"], targets=24, staged_at=_staged_at())
    names = os.listdir(wl.ledger_dir())
    assert len(names) == 1 and names[0].startswith("wave-") and names[0].endswith(".json")


def test_the_entry_names_the_person_who_staged_it(monkeypatch):
    monkeypatch.setenv("KTP_DEPLOY_ACTOR", "cadaver")
    p = wl.record_wave([_art(MD5_A)], hosts=["atlanta"], targets=24, staged_at=_staged_at())
    assert json.load(open(p, encoding="utf-8"))["staged_by"] == "cadaver"


def test_sudo_names_the_person_not_root(monkeypatch):
    monkeypatch.setenv("SUDO_USER", "krodssh")
    assert wl.deploy_actor() == "krodssh"
    import getpass
    monkeypatch.setattr(getpass, "getuser", lambda: "loginname")
    monkeypatch.setenv("SUDO_USER", "root")
    assert wl.deploy_actor() == "loginname"


def test_a_blocked_stager_is_told_whose_wave_blocks_them(monkeypatch, tmp_path):
    monkeypatch.setenv("KTP_DEPLOY_ACTOR", "cadaver")
    wl.record_wave([_art(MD5_A)], hosts=["atlanta"], targets=24, staged_at=_staged_at())
    rows = tmp_path / "rows.md"
    rows.write_text("| KTPHudObserver | x | 09-29 | `%s` |\n" % MD5_B, encoding="utf-8")
    res = wl.gate(str(rows))
    assert res.status == "blocked"
    assert any("staged by cadaver" in ln for ln in wl.format_block(res, str(rows)))


def test_status_shows_who_staged_and_tolerates_old_entries(monkeypatch, capsys):
    monkeypatch.setenv("KTP_DEPLOY_ACTOR", "krodssh")
    wl.record_wave([_art(MD5_A)], hosts=["atlanta"], targets=24, staged_at=_staged_at())
    old = wl.record_wave([_art(MD5_B)], hosts=["atlanta"], targets=24, staged_at=_staged_at())
    entry = json.load(open(old, encoding="utf-8"))
    del entry["staged_by"]
    with open(old, "w", encoding="utf-8") as fh:
        json.dump(entry, fh)
    assert wl.main(["status"]) == 0
    out = capsys.readouterr().out
    assert "staged by krodssh" in out
    assert "staged by NOT RECORDED" in out


def test_reconciling_records_who_did_it(monkeypatch, tmp_path):
    monkeypatch.setenv("KTP_DEPLOY_ACTOR", "cadaver")
    wl.record_wave([_art(MD5_A)], hosts=["atlanta"], targets=24, staged_at=_staged_at())
    monkeypatch.setenv("KTP_DEPLOY_ACTOR", "krodssh")
    rows = tmp_path / "rows.md"
    rows.write_text("| KTPHudObserver | x | 09-29 | `%s` |\n" % MD5_A, encoding="utf-8")
    assert wl.gate(str(rows)).status == "clear"
    (_, entry), = wl.load_waves(include_reconciled=True)
    assert entry["staged_by"] == "cadaver"
    assert entry["reconciled_actor"] == "krodssh"
    assert entry["reconciled_by"] == "stage-gate"


# --- the per-person key ------------------------------------------------------------


def test_no_key_is_the_password_path_unchanged(monkeypatch):
    monkeypatch.setenv("KTP_FLEET_SSH_PASSWORD", "pw")
    assert d2f.fleet_ssh_auth() == {"password": "pw"}


def test_a_key_is_used_alone_with_no_fallback(monkeypatch, tmp_path):
    key = tmp_path / "ktp_deploy_ed25519"
    key.write_text("k", encoding="utf-8")
    monkeypatch.setenv("KTP_FLEET_SSH_KEY", str(key))
    monkeypatch.setenv("KTP_FLEET_SSH_PASSWORD", "pw")
    auth = d2f.fleet_ssh_auth()
    assert auth == {"key_filename": str(key), "allow_agent": False, "look_for_keys": False}


def test_a_missing_key_is_fatal_not_a_silent_password_fallback(monkeypatch, tmp_path):
    monkeypatch.setenv("KTP_FLEET_SSH_KEY", str(tmp_path / "nope"))
    monkeypatch.setenv("KTP_FLEET_SSH_PASSWORD", "pw")
    with pytest.raises(SystemExit):
        d2f.fleet_ssh_auth()


class _Captured(Exception):
    pass


def _capturing_client(seen):
    class Client:
        def set_missing_host_key_policy(self, _p):
            pass

        def connect(self, host, **kw):
            seen.update(kw)
            raise _Captured()

        def close(self):
            pass
    return Client


def test_every_fleet_connect_uses_the_key(monkeypatch, tmp_path):
    """deploy-to-fleet, stage-wave and the ledger's fleet read each open their own
    connection; a key that reached two of them would stage with one identity and
    verify with another."""
    key = tmp_path / "k"
    key.write_text("k", encoding="utf-8")
    monkeypatch.setenv("KTP_FLEET_SSH_KEY", str(key))
    sw = _load("stage_wave_shared", "stage-wave.py")

    seen = {}
    monkeypatch.setattr(d2f.paramiko, "SSHClient", _capturing_client(seen), raising=False)
    monkeypatch.setattr(d2f.paramiko, "AutoAddPolicy", object, raising=False)
    art = d2f.Artifact("x", "serverfiles/dod/addons/ktpamx/plugins", "x.amxx", MD5_A, 1)
    out = d2f.deploy_to_instance("atlanta", d2f.SERVERS["atlanta"], 27015, [art], dry_run=False)
    assert out[0].status == "ssh_fail"
    assert seen.get("key_filename") == str(key) and "password" not in seen

    seen.clear()
    monkeypatch.setattr(sw, "d2f", d2f)
    monkeypatch.setattr(sw.paramiko, "SSHClient", _capturing_client(seen), raising=False)
    with pytest.raises(_Captured):
        sw._connect(d2f.SERVERS["atlanta"])
    assert seen.get("key_filename") == str(key) and "password" not in seen

    seen.clear()
    monkeypatch.setattr(wl, "_load_d2f", lambda: d2f)
    read = wl.fleet_read({"x.amxx": "serverfiles/dod/addons/ktpamx/plugins"}, hosts=["atlanta"])
    assert "atlanta" in read.errors
    assert seen.get("key_filename") == str(key) and "password" not in seen
