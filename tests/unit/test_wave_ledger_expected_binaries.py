"""ktp-wave-ledger: keep provision/expected-binaries.conf in step with the fleet.

The weekly fleet audit compares the fleet against that file from a fresh
checkout on the data server, which can read neither the version rows nor the
wave ledger. Every engine/dodx wave therefore left it stale, and the audit
re-reported the new md5s as new drift until someone re-pinned by hand.
Reconcile already holds the fleet's md5s, so it checks the file and
`repin-expected` writes it. No network here: the fleet read is in-memory.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import os
import sys
import types

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load():
    spec = importlib.util.spec_from_file_location(
        "ktp_wave_ledger_expbin", os.path.join(_ROOT, "scripts", "ktp-wave-ledger.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ktp_wave_ledger_expbin"] = mod
    spec.loader.exec_module(mod)
    return mod


wl = _load()

ENGINE_OLD = "7da5cb6a81bdbc6a" + "0" * 16
ENGINE_NEW = "39d592809128bac1" + "1" * 16
DODX = "4dc65b4d60ddac65" + "2" * 16
INSTS = ["atlanta:27015", "dallas:27015", "chicago:27018"]

CONF = """\
# header comment = not a pin
[default]

# KTP-ReHLDS 3.22.0.1073-dev
engine_i486.so = 7da5cb6a81bdbc6a
hlds_linux = fbebc79b6fdfb0eb

# DODX
dod/addons/ktpamx/modules/dodx_ktp_i386.so = 4dc65b4d60ddac65

[vps]
engine_i486.so = ffffffffffffffff
"""

CLAUDE_MD = f"""\
| Component | Live | Since | Verified hash |
|---|---|---|---|
| KTP-ReHLDS | 3.22.0.1110-dev | 11-10 | **`{ENGINE_NEW}`** |
| KTPAMXX dodx | 2.7.33.6029 | 11-09 | **`{DODX}`** |
"""


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("KTP_WAVE_LEDGER_DIR", str(tmp_path / "waves"))
    conf = tmp_path / "expected-binaries.conf"
    conf.write_bytes(CONF.encode("utf-8"))
    monkeypatch.setenv("KTP_EXPECTED_BINARIES", str(conf))
    md = tmp_path / "SKILL.md"
    md.write_text(CLAUDE_MD, encoding="utf-8")
    monkeypatch.setenv("KTP_CLAUDE_MD", str(md))
    return conf


def _read(live):
    r = types.SimpleNamespace(live={}, staged={}, errors={})
    for base, md5 in live.items():
        r.live[base] = dict(md5) if isinstance(md5, dict) else {i: md5 for i in INSTS}
    return r


def _fleet(read, monkeypatch):
    monkeypatch.setattr(wl, "fleet_read", lambda basenames, hosts=None: read)


def _run(argv):
    try:
        return wl.main(argv)
    except SystemExit as ex:
        return ex.code


AFTER_ENGINE_WAVE = {"engine_i486.so": ENGINE_NEW, "dodx_ktp_i386.so": DODX}


# -- parsing ----------------------------------------------------------------

def test_parse_reads_the_default_section_only():
    pins = wl.parse_expected_pins(CONF)
    assert pins == {"engine_i486.so": "7da5cb6a81bdbc6a", "hlds_linux": "fbebc79b6fdfb0eb",
                    "dod/addons/ktpamx/modules/dodx_ktp_i386.so": "4dc65b4d60ddac65"}


def test_the_repo_baseline_parses_and_pins_the_engine():
    with open(os.path.join(_ROOT, "provision", "expected-binaries.conf"), encoding="utf-8") as fh:
        pins = wl.parse_expected_pins(fh.read())
    assert "engine_i486.so" in pins and "dod/addons/ktpamx/modules/dodx_ktp_i386.so" in pins
    assert all(len(v) == wl.EXPECTED_PREFIX_LEN for v in pins.values())


# -- the finding --------------------------------------------------------------

def test_a_uniform_new_engine_is_a_stale_pin():
    stale, unchecked = wl.expected_pin_findings(_read(AFTER_ENGINE_WAVE), wl.parse_expected_pins(CONF))
    assert [(f.path, f.live) for f in stale] == [("engine_i486.so", ENGINE_NEW)]
    assert unchecked == ["hlds_linux"], "a pin the read never covered is reported, not passed"


def test_a_split_fleet_is_not_a_repin():
    split = {"engine_i486.so": {INSTS[0]: ENGINE_NEW, INSTS[1]: ENGINE_OLD, INSTS[2]: ENGINE_NEW},
             "dodx_ktp_i386.so": DODX}
    stale, unchecked = wl.expected_pin_findings(_read(split), wl.parse_expected_pins(CONF))
    assert stale == []
    assert "engine_i486.so" in unchecked


def test_an_absent_file_on_one_instance_is_not_a_repin():
    gap = {"engine_i486.so": {INSTS[0]: ENGINE_NEW, INSTS[1]: None, INSTS[2]: ENGINE_NEW},
           "dodx_ktp_i386.so": DODX}
    stale, _ = wl.expected_pin_findings(_read(gap), wl.parse_expected_pins(CONF))
    assert stale == []


def test_a_fleet_that_matches_its_pins_is_clean():
    ok = {"engine_i486.so": ENGINE_OLD, "dodx_ktp_i386.so": DODX}
    stale, _ = wl.expected_pin_findings(_read(ok), wl.parse_expected_pins(CONF))
    assert stale == []


# -- reconcile and sweep ------------------------------------------------------

def _stage_engine(days_ago=2.0):
    staged = dt.datetime.now(dt.timezone.utc).timestamp() - days_ago * 86400
    return wl.record_wave([{"basename": "engine_i486.so", "md5": ENGINE_NEW, "remote_dir": "serverfiles"}],
                          hosts=["atlanta", "dallas", "chicago"], targets=24, staged_at=staged)


def test_reconcile_fails_on_a_stale_pin_but_still_reconciles_the_wave(monkeypatch, capsys):
    _stage_engine()
    _fleet(_read(AFTER_ENGINE_WAVE), monkeypatch)

    rc = _run(["reconcile"])
    cap = capsys.readouterr()

    assert rc == 1
    assert "EXPECTED_STALE: engine_i486.so pins 7da5cb6a81bdbc6a" in cap.out
    assert "repin-expected --write" in cap.out
    assert "expected-binaries.conf pins 1 md5(s)" in cap.err
    assert "CLAUDE.md" not in cap.err.split("FAILED:")[1].split("\n")[0], \
        "the rows agree, so the failure must not blame them"
    assert wl.load_waves() == [], "the rows agree, so the wave reconciles; only the pin is owed"


def test_reconcile_is_clean_once_the_pin_is_current(_isolated, monkeypatch, capsys):
    _isolated.write_text(CONF.replace("7da5cb6a81bdbc6a", ENGINE_NEW[:16]), encoding="utf-8")
    _stage_engine()
    _fleet(_read(AFTER_ENGINE_WAVE), monkeypatch)

    assert _run(["reconcile"]) == 0
    assert "EXPECTED_STALE" not in capsys.readouterr().out


def test_sweep_fails_on_a_stale_pin(monkeypatch, capsys):
    _stage_engine()
    _fleet(_read(AFTER_ENGINE_WAVE), monkeypatch)
    assert _run(["sweep"]) == 1
    assert "EXPECTED_STALE: engine_i486.so" in capsys.readouterr().out


def test_a_missing_baseline_is_reported_not_passed(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("KTP_EXPECTED_BINARIES", str(tmp_path / "nope.conf"))
    _stage_engine()
    _fleet(_read(AFTER_ENGINE_WAVE), monkeypatch)
    assert _run(["sweep"]) == 0
    assert "expected-binaries: NOT checked -- no file at" in capsys.readouterr().out


# -- repin-expected -----------------------------------------------------------

def test_repin_dry_run_writes_nothing(_isolated, monkeypatch, capsys):
    _fleet(_read(AFTER_ENGINE_WAVE), monkeypatch)
    before = _isolated.read_bytes()
    assert _run(["repin-expected"]) == 1
    assert _isolated.read_bytes() == before
    assert f"engine_i486.so: 7da5cb6a81bdbc6a -> {ENGINE_NEW[:16]}" in capsys.readouterr().out


def test_repin_write_changes_only_the_stale_value(_isolated, monkeypatch):
    _fleet(_read(AFTER_ENGINE_WAVE), monkeypatch)
    assert _run(["repin-expected", "--write"]) == 0

    after = _isolated.read_bytes().decode("utf-8")
    assert after == CONF.replace("engine_i486.so = 7da5cb6a81bdbc6a",
                                 f"engine_i486.so = {ENGINE_NEW[:16]}")
    assert "engine_i486.so = ffffffffffffffff" in after, "a group override is left to its owner"
    assert b"\r" not in _isolated.read_bytes()


def test_repin_preserves_crlf_line_endings(_isolated, monkeypatch):
    _isolated.write_bytes(CONF.replace("\n", "\r\n").encode("utf-8"))
    _fleet(_read(AFTER_ENGINE_WAVE), monkeypatch)
    assert _run(["repin-expected", "--write"]) == 0
    raw = _isolated.read_bytes()
    assert raw.count(b"\r\n") == CONF.count("\n")
    assert f"engine_i486.so = {ENGINE_NEW[:16]}\r\n".encode() in raw


def test_repin_refuses_a_split_fleet(_isolated, monkeypatch, capsys):
    split = {"engine_i486.so": {INSTS[0]: ENGINE_NEW, INSTS[1]: ENGINE_OLD, INSTS[2]: ENGINE_NEW},
             "dodx_ktp_i386.so": DODX}
    _fleet(_read(split), monkeypatch)
    before = _isolated.read_bytes()
    assert _run(["repin-expected", "--write"]) == 1
    assert _isolated.read_bytes() == before
    assert "NOT uniform" in capsys.readouterr().err


def test_repin_refuses_an_unread_fleet(_isolated, monkeypatch):
    r = _read(AFTER_ENGINE_WAVE)
    r.errors["dallas"] = "TimeoutError"
    _fleet(r, monkeypatch)
    before = _isolated.read_bytes()
    assert _run(["repin-expected", "--write"]) == 2
    assert _isolated.read_bytes() == before


def test_repin_reads_only_what_the_baseline_pins(_isolated, monkeypatch):
    asked = {}

    def fake(basenames, hosts=None):
        asked.update(basenames)
        return _read(AFTER_ENGINE_WAVE)

    monkeypatch.setattr(wl, "fleet_read", fake)
    _run(["repin-expected"])
    assert set(asked) == {"engine_i486.so", "dodx_ktp_i386.so"}
    assert asked["engine_i486.so"] == "serverfiles"


def test_a_pinned_file_absent_everywhere_is_unchecked_not_a_crash():
    gone = {"engine_i486.so": {i: None for i in INSTS}, "dodx_ktp_i386.so": DODX}
    stale, unchecked = wl.expected_pin_findings(_read(gone), wl.parse_expected_pins(CONF))
    assert stale == [] and "engine_i486.so" in unchecked
