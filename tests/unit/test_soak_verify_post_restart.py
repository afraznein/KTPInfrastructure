"""The post-restart soak must say WHY the gate produced no report.

The suite once ran `ktp-verify-deploy ... 2>&1` and kept only stderr, which the
redirect had emptied. Every night the gate refused, the soak reported "failed to
read verify-deploy output" and nothing else, so a STALE refusal printed in full
by the gate never reached the log or Discord.

These tests run the real `sh()` through a real shell, with the hardcoded gate
path swapped for a fake, because the defect lives in the shell redirect: a
stubbed `sh()` returning a tidy stderr would pass against the broken code.
"""
import importlib.util
import pathlib
import sys
import textwrap

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ktp-soak-verify.py"
GATE = "/usr/local/bin/ktp-verify-deploy"


@pytest.fixture
def soak(monkeypatch):
    spec = importlib.util.spec_from_file_location("_ktp_soak_verify", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    # dataclasses resolves annotations through sys.modules while the module executes.
    monkeypatch.setitem(sys.modules, spec.name, mod)
    spec.loader.exec_module(mod)
    return mod


def _fake_gate(tmp_path, body):
    fake = tmp_path / "fake_verify_deploy.py"
    fake.write_text(textwrap.dedent(body), encoding="utf-8", newline="\n")
    return fake


def _route_gate(monkeypatch, soak, fake):
    real_sh = soak.sh

    def sh(cmd, timeout=30):
        assert GATE in cmd, cmd
        return real_sh(cmd.replace(GATE, f'"{sys.executable}" "{fake}"'), timeout=timeout)

    monkeypatch.setattr(soak, "sh", sh)


def _only_check(result):
    assert len(result.checks) == 1, result.checks
    return result.checks[0]


def test_a_refusal_on_stderr_reaches_the_report(tmp_path, monkeypatch, soak):
    fake = _fake_gate(tmp_path, """
        import sys
        print("zqwbw1110 REFUSED: ktp-verify-deploy is STALE", file=sys.stderr)
        sys.exit(3)
    """)
    _route_gate(monkeypatch, soak, fake)

    check = _only_check(soak.suite_post_restart())

    assert check.status == soak.Status.RED
    assert "exit 3" in check.summary
    assert check.detail and "zqwbw1110 REFUSED" in check.detail


def test_output_on_stdout_is_kept_too(tmp_path, monkeypatch, soak):
    fake = _fake_gate(tmp_path, """
        import sys
        print("zqwbw1110 said on stdout")
        sys.exit(2)
    """)
    _route_gate(monkeypatch, soak, fake)

    check = _only_check(soak.suite_post_restart())

    assert "exit 2" in check.summary
    assert check.detail and "zqwbw1110 said on stdout" in check.detail


def test_a_silent_failure_still_reports_red_with_no_detail(tmp_path, monkeypatch, soak):
    fake = _fake_gate(tmp_path, """
        import sys
        sys.exit(1)
    """)
    _route_gate(monkeypatch, soak, fake)

    check = _only_check(soak.suite_post_restart())

    assert check.status == soak.Status.RED
    assert "exit 1" in check.summary
    assert check.detail is None
