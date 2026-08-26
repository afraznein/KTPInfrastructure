"""Regression tests for the management scripts install-linuxgsm.sh generates.

Three defects shipped to the fleet in these scripts and survived for months
because nothing here ever ran them:

  set -e + a baked-in instance list
      The generated restart script ran under `set -e` and looped over a
      hardcoded `1 2 3 4 5`. Chicago's 27019 was deleted 2026-07-13, so the
      start loop hit a control script that no longer exists, exited non-zero,
      and `set -e` killed the run before the verify -- on a four-instance host
      the script could never report anything at all.

  ((running++)) from zero
      Post-increment evaluates to the OLD value. At running=0 that makes the
      arithmetic expansion return exit status 1, so under `set -e` the verify
      aborted at the FIRST healthy server. The failure mode was a script that
      looked like it worked on every host with at least one dead instance and
      silently truncated on every host without one.

  no way to reach an installed host
      The scripts exist only as heredocs inside the installer and the installer
      only runs on a bare host, so a fix in this repo could not reach the five
      live hosts. --regen-management-scripts is that path, and these tests are
      what make it safe to point at production.

Everything below drives the real installer in --regen-management-scripts mode
against a sandboxed HOME. No fleet host is involved and nothing is started or
stopped: the generated restart script is never executed, only parsed and read.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

INSTALLER = Path(__file__).parents[2] / "provision" / "install-linuxgsm.sh"

# geteuid() does not exist on Windows, so the nt check has to come first --
# skipif evaluates its condition at collection time.
pytestmark = [
    pytest.mark.skipif(
        shutil.which("bash") is None or os.name == "nt",
        reason="needs bash",
    ),
    pytest.mark.skipif(
        os.name != "nt" and os.geteuid() == 0,
        reason="the installer refuses to run as root, by design",
    ),
]


def _instance(home: Path, port: int, ctl: str) -> None:
    d = home / f"dod-{port}"
    d.mkdir(parents=True, exist_ok=True)
    script = d / ctl
    script.write_text("#!/bin/bash\nexit 0\n")
    script.chmod(0o755)


def _regen(home: Path) -> subprocess.CompletedProcess:
    """Run the installer's regen mode against `home`.

    YES=1 answers the "not running as dodserver" prompt; without it the
    installer blocks on `read` and the test would hang rather than fail.
    """
    env = dict(os.environ, HOME=str(home), YES="1")
    return subprocess.run(
        ["bash", str(INSTALLER), "--regen-management-scripts"],
        capture_output=True, text=True, env=env, timeout=120,
    )


@pytest.fixture
def baremetal(tmp_path: Path) -> Path:
    """Atlanta/Dallas/Denver/NY shape: five instances, 27015-27019."""
    home = tmp_path / "home"
    _instance(home, 27015, "dodserver")
    for i in range(2, 6):
        _instance(home, 27014 + i, f"dodserver{i}")
    return home


@pytest.fixture
def chicago(tmp_path: Path) -> Path:
    """Chicago shape: four instances. 27019 was deleted 2026-07-13."""
    home = tmp_path / "home"
    _instance(home, 27015, "dodserver")
    for i in range(2, 5):
        _instance(home, 27014 + i, f"dodserver{i}")
    return home


# --------------------------------------------------------------- regen mode

def test_regen_writes_both_scripts_and_touches_nothing_else(baremetal: Path):
    r = _regen(baremetal)
    assert r.returncode == 0, r.stderr
    assert (baremetal / "restart-all-servers.sh").is_file()
    assert (baremetal / "status.sh").is_file()
    # Regen must not provision. If it ever grows an install side effect, a new
    # dod-* directory is the first thing that shows up.
    assert sorted(p.name for p in baremetal.glob("dod-*")) == [
        "dod-27015", "dod-27016", "dod-27017", "dod-27018", "dod-27019"
    ]


def test_regen_backs_up_before_overwriting(baremetal: Path):
    target = baremetal / "restart-all-servers.sh"
    target.write_text("#!/bin/bash\n# the stale fleet copy\n")

    assert _regen(baremetal).returncode == 0

    backups = list(baremetal.glob("restart-all-servers.sh.bak-*"))
    assert len(backups) == 1, backups
    assert "the stale fleet copy" in backups[0].read_text()
    assert "the stale fleet copy" not in target.read_text()


def test_regen_is_idempotent(baremetal: Path):
    assert _regen(baremetal).returncode == 0
    first = (baremetal / "restart-all-servers.sh").read_text()
    assert _regen(baremetal).returncode == 0
    assert (baremetal / "restart-all-servers.sh").read_text() == first


def test_regen_does_not_need_a_server_ip(baremetal: Path):
    """The flag has to work alone -- the operator has no IP argument to give."""
    r = _regen(baremetal)
    assert r.returncode == 0
    assert "Usage:" not in r.stdout


# ------------------------------------------------------- the shipped defects

def test_generated_restart_script_has_none_of_the_shipped_defects(baremetal: Path):
    assert _regen(baremetal).returncode == 0
    body = (baremetal / "restart-all-servers.sh").read_text()

    code = [ln for ln in body.splitlines() if not ln.lstrip().startswith("#")]
    joined = "\n".join(code)

    assert not any(ln.strip() == "set -e" for ln in code), \
        "set -e aborts the run at the first dead instance"
    assert "1 2 3 4 5" not in joined, \
        "a baked-in instance list outlives the install (Chicago's 27019)"
    assert "((running++))" not in joined, \
        "post-increment from 0 returns exit status 1"
    assert "discover_instances" in joined


def test_generated_scripts_parse(baremetal: Path):
    assert _regen(baremetal).returncode == 0
    for name in ("restart-all-servers.sh", "status.sh"):
        p = baremetal / name
        r = subprocess.run(["bash", "-n", str(p)], capture_output=True, text=True)
        assert r.returncode == 0, f"{name}: {r.stderr}"
        assert os.access(p, os.X_OK), f"{name} is not executable"


def test_counting_from_zero_survives(baremetal: Path):
    """The `((running++))` bug, reproduced against the generated code itself.

    Extracting the verify loop is not enough -- it has to be run under the same
    options the script sets, or the exact interaction that killed it is absent.
    """
    assert _regen(baremetal).returncode == 0
    body = (baremetal / "restart-all-servers.sh").read_text()
    opts = next((ln for ln in body.splitlines() if ln.startswith("set ")), None)
    incr = next((ln.strip() for ln in body.splitlines()
                 if ln.strip().startswith("running=$((")), None)
    assert opts, "generated script sets no shell options"
    assert incr, "the counter is not a plain `running=$((running + 1))` assignment"

    probe = f"{opts}\nrunning=0\n{incr}\n{incr}\necho $running\n"
    r = subprocess.run(["bash", "-c", probe], capture_output=True, text=True)
    assert r.returncode == 0, f"increment aborted under `{opts}`: {r.stderr}"
    assert r.stdout.strip() == "2"

    # Control: the shape that shipped does abort, so the assertion above is
    # testing something real and not just a bash version that stopped caring.
    control = "set -e\nrunning=0\n((running++))\necho $running\n"
    assert subprocess.run(["bash", "-c", control], capture_output=True).returncode != 0


# ------------------------------------------------------- instance discovery

def _discovered_ports(home: Path) -> list[str]:
    """Run only the discovery block from the generated script and print ports.

    Stops before the stop/start loops, so nothing is ever invoked.
    """
    body = (home / "restart-all-servers.sh").read_text()
    head, _, _ = body.partition('echo "========================================"')
    r = subprocess.run(
        ["bash", "-c", head + '\nprintf "%s\\n" "${KTP_PORTS[@]}"\n'],
        capture_output=True, text=True, env=dict(os.environ, HOME=str(home)),
    )
    assert r.returncode == 0, r.stderr
    return sorted(r.stdout.split())


def test_discovers_five_on_a_baremetal(baremetal: Path):
    assert _regen(baremetal).returncode == 0
    assert _discovered_ports(baremetal) == ["27015", "27016", "27017", "27018", "27019"]


def test_discovers_four_on_chicago(chicago: Path):
    """The case the shipped script could not survive."""
    assert _regen(chicago).returncode == 0
    assert _discovered_ports(chicago) == ["27015", "27016", "27017", "27018"]


def test_discovery_skips_non_instances(chicago: Path):
    """Three decoys that a looser glob would pick up."""
    (chicago / "dod-warmup").mkdir()                      # non-numeric suffix
    (chicago / "dod-27099").mkdir()                       # numeric, no control script
    backup = chicago / "dod-27015" / "dodserver.cfg.bak"  # matches dodserver*
    backup.write_text("not a control script\n")
    backup.chmod(0o644)

    assert _regen(chicago).returncode == 0
    assert _discovered_ports(chicago) == ["27015", "27016", "27017", "27018"]


def test_empty_home_refuses_rather_than_no_ops(tmp_path: Path):
    home = tmp_path / "empty"
    home.mkdir()
    assert _regen(home).returncode == 0  # regen itself succeeds; discovery is at run time

    body = (home / "restart-all-servers.sh").read_text()
    head, _, _ = body.partition('echo "========================================"')
    r = subprocess.run(["bash", "-c", head], capture_output=True, text=True,
                       env=dict(os.environ, HOME=str(home)))
    assert r.returncode != 0, "a host with no instances must not read as success"
    assert "No LinuxGSM instances found" in r.stderr
