"""The nightly soak runs `ktp-verify-deploy --check-runtime` with the rcon
password read at run time from the distributor's dodserver.cfg.

Every value here is a fake. What is pinned: the parse refuses anything but
exactly one non-empty `rcon_password` line, the value reaches the verify
child's environment and nothing the soak prints, and a refusal still runs the
disk checks, posts RED and exits 5.
"""
import importlib.util
import json
import os
import pathlib
import sys
import textwrap

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ktp-soak-verify.py"
GATE = "/usr/local/bin/ktp-verify-deploy"
FAKE_PW = "zqwbw-Fake-Rcon-7731"


@pytest.fixture
def soak(monkeypatch, tmp_path):
    monkeypatch.delenv("KTP_RCON_PASSWORD", raising=False)
    monkeypatch.delenv("KTP_RCON_CFG", raising=False)
    spec = importlib.util.spec_from_file_location("_ktp_soak_verify_rcon", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, mod)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "VERIFY_OUT_DIR", tmp_path.as_posix())
    return mod


def _cfg(tmp_path, body, name="dodserver.cfg"):
    p = tmp_path / name
    p.write_bytes(body.encode("utf-8"))
    return str(p)


# ── parsing ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("body", [
    f'hostname "x"\nrcon_password "{FAKE_PW}"\nsys_ticrate 1500\n',
    f'rcon_password {FAKE_PW}\n',
    f'hostname "x"\r\nrcon_password "{FAKE_PW}"\r\nsys_ticrate 1500\r\n',
    f'rcon_password {FAKE_PW}\r\n',
    f'﻿rcon_password "{FAKE_PW}"\n',
    f'  RCON_PASSWORD   "{FAKE_PW}"   // fleet-wide\n',
    f'rcon_password {FAKE_PW} // fleet-wide\n',
    f'// rcon_password "old"\nsv_rcon_banpenalty 0\nrcon_password "{FAKE_PW}"\n',
], ids=["quoted", "unquoted", "crlf-quoted", "crlf-unquoted", "bom",
        "indented-comment", "unquoted-comment", "ignores-comments-and-lookalikes"])
def test_reads_the_one_value(soak, tmp_path, body):
    assert soak.read_rcon_password(_cfg(tmp_path, body)) == FAKE_PW


@pytest.mark.parametrize("body,needle", [
    (f'rcon_password "{FAKE_PW}"\nrcon_password "{FAKE_PW}-b"\n', "2 rcon_password lines"),
    (f'rcon_password "{FAKE_PW}"\r\nrcon_password "{FAKE_PW}"\r\n', "2 rcon_password lines"),
    ('hostname "x"\nsys_ticrate 1500\n', "0 rcon_password lines"),
    (f'// rcon_password "{FAKE_PW}"\n//rcon_password "{FAKE_PW}"\n', "0 rcon_password lines"),
    ('rcon_password ""\n', "empty value"),
    ('rcon_password\r\n', "empty value"),
], ids=["duplicate", "duplicate-identical-crlf", "missing", "only-commented",
        "empty-quoted", "empty-bare"])
def test_refuses_anything_but_one_non_empty_line(soak, tmp_path, body, needle):
    with pytest.raises(soak.RconSourceError) as e:
        soak.read_rcon_password(_cfg(tmp_path, body))
    assert needle in str(e.value)
    assert FAKE_PW not in str(e.value)


def test_refuses_a_missing_file(soak, tmp_path):
    with pytest.raises(soak.RconSourceError) as e:
        soak.read_rcon_password(str(tmp_path / "nope.cfg"))
    assert "cannot read" in str(e.value)


# ── the suite end to end, through a real shell and a fake gate ───────────

GATE_BODY = """
    import json, os, sys
    out = sys.argv[sys.argv.index("--out") + 1]
    with open({seen!r}, "w") as f:
        json.dump({{"argv": sys.argv[1:], "rcon": os.environ.get("KTP_RCON_PASSWORD")}}, f)
    {extra}
    runtime = "--check-runtime" in sys.argv
    inst = {{"status": "green", "runtime_count": 9, "runtime_error": None}} if runtime else {{"status": "green"}}
    report = {{"reference": {{"host": "h", "port": 1, "label": "ATL1", "manifest_size": 3,
                              "lingering_new_files": [], "runtime_error": None}},
               "check_runtime": runtime, "overall": "green", "counts": {{"green": 2}},
               "instances": {{"ATL1": inst, "ATL2": dict(inst)}}}}
    with open(out, "w") as f:
        json.dump(report, f)
"""


def _route(monkeypatch, soak, tmp_path, extra=""):
    seen = tmp_path / "seen.json"
    fake = tmp_path / "fake_gate.py"
    fake.write_text(textwrap.dedent(GATE_BODY.format(seen=str(seen), extra=extra)),
                    encoding="utf-8", newline="\n")
    real_sh = soak.sh

    def sh(cmd, timeout=30, env=None):
        assert GATE in cmd, cmd
        return real_sh(cmd.replace(GATE, f'"{sys.executable}" "{fake}"'),
                       timeout=timeout, env=env)

    monkeypatch.setattr(soak, "sh", sh)
    return seen


def _run_main(soak, monkeypatch, capsys, *extra):
    monkeypatch.setattr(sys, "argv", ["ktp-soak-verify", "--suite", "post-restart",
                                      "--dry-run", "--always-post", *extra])
    rc = soak.main()
    cap = capsys.readouterr()
    return rc, cap.out + cap.err


def test_cfg_value_reaches_the_child_only(soak, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("KTP_RCON_CFG", _cfg(tmp_path, f'rcon_password "{FAKE_PW}"\r\n'))
    seen = _route(monkeypatch, soak, tmp_path)

    rc, printed = _run_main(soak, monkeypatch, capsys)

    child = json.loads(seen.read_text())
    assert child["rcon"] == FAKE_PW
    assert "--check-runtime" in child["argv"]
    assert "KTP_RCON_PASSWORD" not in os.environ
    assert FAKE_PW not in printed
    assert "runtime checked 2/2 instances" in printed
    assert rc == 0


def test_a_child_that_echoes_the_password_is_redacted(soak, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("KTP_RCON_CFG", _cfg(tmp_path, f'rcon_password "{FAKE_PW}"\n'))
    _route(monkeypatch, soak, tmp_path, extra=(
        'print("pw=" + os.environ["KTP_RCON_PASSWORD"], file=sys.stderr); '
        'print("pw=" + os.environ["KTP_RCON_PASSWORD"]); sys.exit(3)'))

    rc, printed = _run_main(soak, monkeypatch, capsys)

    assert FAKE_PW not in printed
    assert "pw=<redacted>" in printed


def test_a_set_env_var_wins_and_the_cfg_is_not_read(soak, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("KTP_RCON_PASSWORD", FAKE_PW)
    monkeypatch.setenv("KTP_RCON_CFG", str(tmp_path / "absent.cfg"))
    seen = _route(monkeypatch, soak, tmp_path)

    rc, printed = _run_main(soak, monkeypatch, capsys)

    assert json.loads(seen.read_text())["rcon"] == FAKE_PW
    assert rc == 0
    assert "Runtime check credential" not in printed


@pytest.mark.parametrize("body", [
    None,
    f'rcon_password "{FAKE_PW}"\nrcon_password "{FAKE_PW}"\n',
    'rcon_password ""\n',
    'sys_ticrate 1500\n',
], ids=["missing-file", "duplicate", "empty", "absent-line"])
def test_a_refusal_still_runs_disk_checks_posts_red_and_exits_5(
        soak, tmp_path, monkeypatch, capsys, body):
    path = str(tmp_path / "absent.cfg") if body is None else _cfg(tmp_path, body)
    monkeypatch.setenv("KTP_RCON_CFG", path)
    seen = _route(monkeypatch, soak, tmp_path)

    rc, printed = _run_main(soak, monkeypatch, capsys)

    child = json.loads(seen.read_text())
    assert "--check-runtime" not in child["argv"]
    assert child["rcon"] is None
    assert rc == soak.EXIT_RCON_SOURCE_REFUSED == 5
    assert "[RED   ] Runtime check credential: --check-runtime NOT run" in printed
    assert "=== Suite: post-restart — RED ===" in printed
    assert FAKE_PW not in printed


def test_the_default_source_is_the_distributor_copy(soak):
    assert soak.RCON_CFG_DEFAULT == "/home/dod/distribute/dodserver.cfg"


# ── coverage: a wrong password must not read GREEN ───────────────────────

def _report(ref_err=None, instances=None, check_runtime=True):
    return {"check_runtime": check_runtime,
            "reference": {"runtime_error": ref_err},
            "instances": instances or {}}


def _ok():
    return {"runtime_count": 9, "runtime_error": None}


def test_coverage_all_answered_is_green(soak):
    c = soak.runtime_coverage(_report(instances={f"I{i}": _ok() for i in range(24)}))
    assert c.status == soak.Status.GREEN
    assert c.summary == "runtime checked 24/24 instances"


def test_coverage_reference_rcon_failure_is_red(soak):
    c = soak.runtime_coverage(_report(ref_err="RconError: Bad rcon_password.",
                                      instances={"I0": {"status": "green"}}))
    assert c.status == soak.Status.RED
    assert "NO instance was compared" in c.summary


def test_coverage_none_answered_is_red(soak):
    bad = {"runtime_count": 0, "runtime_error": "RconError: timeout"}
    c = soak.runtime_coverage(_report(instances={"I0": bad, "I1": dict(bad)}))
    assert c.status == soak.Status.RED
    assert c.detail == "rcon failed: I0, I1"


def test_coverage_partial_is_yellow_and_names_the_gaps(soak):
    inst = {f"I{i}": _ok() for i in range(23)}
    inst["I23"] = {"runtime_count": 0, "runtime_error": "RconError: timeout"}
    c = soak.runtime_coverage(_report(instances=inst))
    assert c.status == soak.Status.YELLOW
    assert c.summary == "runtime checked 23/24 instances"
    assert c.detail == "rcon failed: I23"


def test_coverage_leg_missing_from_report_is_red(soak):
    c = soak.runtime_coverage(_report(check_runtime=False))
    assert c.status == soak.Status.RED
