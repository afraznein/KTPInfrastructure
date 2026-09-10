"""Regression tests for scripts/ktp-monitor-patch-check.sh.

The script exists because the KTP patch to LinuxGSM's `command_monitor.sh` is
both mandatory and self-erasing: `./dodserver update-lgsm` overwrites the file,
and the line range it was historically applied by is version-specific. Two
failure shapes have actually happened on KTP hardware and both are covered here:

  armed old-type check
      The unpatched branch pkills a healthy instance on every monitor run. On
      2026-07-31 that killed 27015 seven times during matches in four hours.

  patched file that does not parse
      Applying `203,212` against LinuxGSM v26.2.0 orphans an `elif`. Monitor
      then exits 2 every minute, silently, and never restarts a dead server.
      The Philly LAN box ran nine days that way.

The third shape has no incident behind it but would be the worst outcome here:
the canonical `if false; then` patch reading as *armed* because the branch's
`pkill` body still names the same tmux pattern as the condition. A check that
cries wolf on a correctly patched fleet gets ignored, and then the two real
shapes above go unnoticed too.

Nothing here touches a fleet host. Each test builds a fake instance tree in
tmp_path and points DOD_HOME at it.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

CHECKER = Path(__file__).parents[2] / "scripts" / "ktp-monitor-patch-check.sh"
# CI runs plain bash; on a Windows workstation "bash" resolves to WSL's, which
# cannot see these paths -- point KTP_TEST_BASH at Git Bash there. Same
# convention as test_grub_default_kernel_audit.py.
BASH = os.environ.get("KTP_TEST_BASH", "bash")

pytestmark = pytest.mark.skipif(shutil.which(BASH) is None, reason="needs bash")

# Abridged from the real fn_monitor_check_session: the three pgrep conditions in
# their upstream order, plus the genuine dead-server branch the patch must never
# break. Each condition's body repeats its own tmux pattern, which is exactly the
# text that makes naive matching wrong.
UNPATCHED = '''#!/bin/bash
fn_monitor_check_session() {
\tif [ "$(pgrep -fcx "tmux -L ${socketname} new-session")" -ge 2 ]; then
\t\tfn_print_error_nl "Checking session: PIDS with same socket are running"
\t\tpkill -f "tmux -L ${socketname}"
\t\tcommand_restart.sh
\telif [ "$(pgrep -fc "tmux -L ${sessionname} new-session")" != "0" ]; then
\t\tfn_print_error_nl "Checking session: PIDS with same socket and session"
\t\tpkill -f "tmux -L ${sessionname}"
\t\tcommand_restart.sh
\telif [ "$(pgrep -fc "tmux new-session")" != "0" ]; then
\t\tfn_print_error_nl "Checking session: PIDS with old type tmux session"
\t\tpkill -f "tmux new-session"
\t\tcommand_restart.sh
\telse
\t\tfn_print_error_nl "Monitor is restarting ${selfname}"
\t\tcommand_restart.sh
\tfi
}
'''

OLD_TYPE_BLOCK = '''\telif [ "$(pgrep -fc "tmux new-session")" != "0" ]; then
\t\tfn_print_error_nl "Checking session: PIDS with old type tmux session"
\t\tpkill -f "tmux new-session"
\t\tcommand_restart.sh
'''

# Production, 24/24 instances: the sed range prefixed every line of the old-type
# block, condition and body alike. The two upstream branches above it stay live.
PROD_COMMENT_STYLE = UNPATCHED.replace(
    OLD_TYPE_BLOCK,
    "".join("# KTP-DISABLED: " + line + "\n"
            for line in OLD_TYPE_BLOCK.splitlines()),
)

# Canonical/LAN: conditions replaced by `false`, bodies left intact, file whole.
CANONICAL = (
    UNPATCHED
    .replace('\tif [ "$(pgrep -fcx "tmux -L ${socketname} new-session")" -ge 2 ]; then',
             '\tif false; then   # KTP-DISABLED: duplicate-PID check')
    .replace('\telif [ "$(pgrep -fc "tmux -L ${sessionname} new-session")" != "0" ]; then',
             '\telif false; then   # KTP-DISABLED: same socket+session check')
    .replace('\telif [ "$(pgrep -fc "tmux new-session")" != "0" ]; then',
             '\telif false; then   # KTP-DISABLED: old-type check, kills live matches')
)

# The v26.2.0 accident: the range landed one block early and ate the opening
# `if`, orphaning the first `elif`. bash -n rejects it; monitor exits 2 forever.
BROKEN_PARSE = UNPATCHED.replace(
    '\tif [ "$(pgrep -fcx "tmux -L ${socketname} new-session")" -ge 2 ]; then',
    '# KTP-DISABLED: \tif [ "$(pgrep -fcx "tmux -L ${socketname} new-session")" -ge 2 ]; then',
)


def _instance(home: Path, port: int, monitor: str, version: str = "v23.5.3") -> None:
    n = port - 27014
    d = home / f"dod-{port}"
    (d / "lgsm" / "modules").mkdir(parents=True, exist_ok=True)
    (d / "lgsm" / "modules" / "command_monitor.sh").write_text(monitor, newline="\n")
    ctl = "dodserver" if n == 1 else f"dodserver{n}"
    (d / ctl).write_text('#!/bin/bash\nversion="%s"\n' % version, newline="\n")


def _run(home: Path) -> subprocess.CompletedProcess:
    # as_posix() both times: on Windows the tests run under Git Bash, which
    # takes `G:/path` but silently eats the backslashes in `G:\path`.
    return subprocess.run(
        [BASH, CHECKER.as_posix()],
        capture_output=True, text=True, timeout=120,
        env=dict(os.environ, DOD_HOME=home.as_posix()),
    )


def _facts(stdout: str) -> dict:
    """Snapshot-section text -> {key: value}, the way audit-fleet-drift parses it."""
    out = {}
    for line in stdout.splitlines():
        if line.startswith("===") or not line.strip():
            continue
        key, _, value = line.partition(":")
        out[key.strip()] = value.strip()
    return out


def test_prod_shape_is_clean(tmp_path):
    """Five instances patched the way production is: exit 0, old-type disabled.

    The two upstream branches stay armed on purpose, so this also pins that they
    do not fail the run -- converging prod to the canonical form is a
    provisioning decision, not a weekly alert.
    """
    home = tmp_path / "home"
    for port in range(27015, 27020):
        _instance(home, port, PROD_COMMENT_STYLE)
    r = _run(home)
    assert r.returncode == 0, r.stdout + r.stderr
    facts = _facts(r.stdout)
    assert facts["instances"] == "5"
    assert facts["lgsm-versions"] == "v23.5.3"
    assert facts["dod-27015"] == "parse=OK oldtype=disabled samesocket=armed duppid=armed"


def test_canonical_patch_is_not_reported_as_armed(tmp_path):
    """`if false; then` leaves each branch's pkill body naming the same tmux
    pattern. Matching the body instead of the condition would read every
    correctly patched instance as armed."""
    home = tmp_path / "home"
    _instance(home, 27015, CANONICAL)
    r = _run(home)
    assert r.returncode == 0, r.stdout + r.stderr
    assert _facts(r.stdout)["dod-27015"] == (
        "parse=OK oldtype=disabled samesocket=disabled duppid=disabled"
    )


def test_unpatched_old_type_check_fails(tmp_path):
    """An armed old-type branch is the thing that kills live matches."""
    home = tmp_path / "home"
    _instance(home, 27015, UNPATCHED)
    r = _run(home)
    assert r.returncode == 1
    assert "oldtype=armed" in _facts(r.stdout)["dod-27015"]


def test_unparseable_monitor_fails(tmp_path):
    """The v26.2.0 shape: patched, quiet, and doing nothing at all."""
    home = tmp_path / "home"
    _instance(home, 27015, BROKEN_PARSE)
    r = _run(home)
    assert r.returncode == 1
    assert _facts(r.stdout)["dod-27015"].startswith("parse=BROKEN")


def test_one_bad_instance_fails_the_host(tmp_path):
    """Four clean instances must not average away the fifth."""
    home = tmp_path / "home"
    for port in range(27015, 27019):
        _instance(home, port, PROD_COMMENT_STYLE)
    _instance(home, 27019, UNPATCHED)
    r = _run(home)
    assert r.returncode == 1
    facts = _facts(r.stdout)
    assert facts["dod-27018"] == "parse=OK oldtype=disabled samesocket=armed duppid=armed"
    assert "oldtype=armed" in facts["dod-27019"]


def test_chicago_four_instances(tmp_path):
    """Chicago's 27019 was deleted 2026-07-13; four instances is not a fault."""
    home = tmp_path / "home"
    for port in range(27015, 27019):
        _instance(home, port, PROD_COMMENT_STYLE)
    r = _run(home)
    assert r.returncode == 0, r.stdout + r.stderr
    facts = _facts(r.stdout)
    assert facts["instances"] == "4"
    assert "dod-27019" not in facts


def test_missing_monitor_file_fails(tmp_path):
    home = tmp_path / "home"
    _instance(home, 27015, PROD_COMMENT_STYLE)
    (home / "dod-27015" / "lgsm" / "modules" / "command_monitor.sh").unlink()
    r = _run(home)
    assert r.returncode == 1
    assert _facts(r.stdout)["dod-27015"].startswith("parse=MISSING")


def test_no_instances_is_a_failure_not_a_pass(tmp_path):
    """A sweep that matched nothing must not render as a healthy host -- that is
    the same silence this script exists to break."""
    empty = tmp_path / "empty"
    empty.mkdir()
    r = _run(empty)
    assert r.returncode == 1
    assert _facts(r.stdout)["instances"] == "0"


def test_mixed_lgsm_versions_on_one_host_are_visible(tmp_path):
    """update-lgsm is per-instance, so a half-updated host is a real state and
    the one place a version fact earns its keep."""
    home = tmp_path / "home"
    _instance(home, 27015, PROD_COMMENT_STYLE, version="v23.5.3")
    _instance(home, 27016, PROD_COMMENT_STYLE, version="v26.2.0")
    r = _run(home)
    assert _facts(r.stdout)["lgsm-versions"] == "v23.5.3,v26.2.0"
