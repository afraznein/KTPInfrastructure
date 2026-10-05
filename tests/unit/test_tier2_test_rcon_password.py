"""The tier-2 test server's rcon password comes from the environment, never the repo."""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tests.smoke import boot_subprocess
from tests.smoke.boot_subprocess import (
    TEST_RCON_ENV,
    booted_subprocess,
    cfg_with_rcon_password,
    resolve_test_rcon_password,
)

REPO = Path(__file__).resolve().parents[2]
FIXTURE = REPO / "tests" / "smoke" / "fixtures" / "test_server.cfg"
CURL_SMOKE = REPO / "scripts" / "curl_smoke.py"
TIER2_WORKFLOW = REPO / ".github" / "workflows" / "tier2-integration.yml"
CONFTEST = REPO / "tests" / "integration" / "conftest.py"


def test_resolver_refuses_when_unset(monkeypatch):
    monkeypatch.delenv(TEST_RCON_ENV, raising=False)
    with pytest.raises(RuntimeError, match=TEST_RCON_ENV):
        resolve_test_rcon_password()


def test_resolver_refuses_empty(monkeypatch):
    monkeypatch.setenv(TEST_RCON_ENV, "")
    with pytest.raises(RuntimeError):
        resolve_test_rcon_password()


def test_resolver_returns_env_value(monkeypatch):
    monkeypatch.setenv(TEST_RCON_ENV, "fromEnv123")
    assert resolve_test_rcon_password() == "fromEnv123"


def test_boot_without_password_refuses_before_spawning(monkeypatch, tmp_path):
    monkeypatch.delenv(TEST_RCON_ENV, raising=False)

    def _no_spawn(*_a, **_k):
        raise AssertionError("hlds_linux was spawned without a resolved rcon password")

    monkeypatch.setattr(boot_subprocess, "_spawn", _no_spawn)
    with pytest.raises(RuntimeError, match=TEST_RCON_ENV):
        with booted_subprocess(tmp_path):
            pass


def test_staged_fixture_carries_the_env_value_not_the_literal():
    staged = cfg_with_rcon_password(FIXTURE.read_text(), "fromEnv123")
    values = re.findall(r'^\s*rcon_password\s+"([^"]*)"', staged, re.M)
    assert values == ["fromEnv123"]
    # Every other line is untouched.
    assert staged.replace('rcon_password "fromEnv123"', "") == \
        re.sub(r'rcon_password "[^"]*"', "", FIXTURE.read_text())


@pytest.mark.parametrize("bad", ["", 'a"b', "a\nb", "a\rb"])
def test_staging_rejects_unsafe_values(bad):
    with pytest.raises(ValueError):
        cfg_with_rcon_password(FIXTURE.read_text(), bad)


def test_staging_requires_exactly_one_rcon_line():
    with pytest.raises(ValueError, match="found 0"):
        cfg_with_rcon_password("hostname x\n", "pw")
    with pytest.raises(ValueError, match="found 2"):
        cfg_with_rcon_password('rcon_password "a"\nrcon_password "b"\n', "pw")


def test_tier2_conftest_stages_and_boots_with_the_resolved_password():
    src = CONFTEST.read_text()
    assert "cfg_with_rcon_password(smoke_cfg.read_text(), rcon_password)" in src
    assert re.search(r'rcon_password\s*=\s*"', src) is None


def test_curl_smoke_has_no_literal_password():
    src = CURL_SMOKE.read_text()
    assert re.search(r'RCON_PW\s*=\s*["\']', src) is None
    assert 'os.environ.get("KTP_TEST_RCON_PASSWORD"' in src


def test_curl_smoke_exits_loudly_when_unset():
    env = {k: v for k, v in os.environ.items() if k != TEST_RCON_ENV}
    proc = subprocess.run([sys.executable, str(CURL_SMOKE), "unit"], env=env,
                          capture_output=True, text=True, timeout=30)
    assert proc.returncode != 0
    assert TEST_RCON_ENV in proc.stderr
    assert "RESULT_JSON" not in proc.stdout


def test_tier2_workflow_masks_and_exports_before_pytest():
    wf = TIER2_WORKFLOW.read_text()
    load = wf.index("- name: Load test-server rcon password")
    run = wf.index("- name: Run Tier 2 integration suite")
    assert load < run
    step = wf[load:run]
    assert "/etc/ktp/tier2-test-rcon.env" in step
    assert step.index('::add-mask::$pw') < step.index('>> "$GITHUB_ENV"')
    assert "exit 1" in step
