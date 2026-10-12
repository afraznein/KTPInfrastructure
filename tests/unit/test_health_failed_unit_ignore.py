"""ktp-data-server-health.sh: an accepted failure is a STATUS, not a unit name.

`systemctl --failed` is swept so a unit nobody allowlisted still surfaces, and
units whose failure is known and accepted are ignored. The ignore used to match
on the unit NAME, which accepts every way a unit can fail.

That cost a week's report on 2026-10-12. `ktp-weekly-outliers.service` exited
`203/EXEC` -- systemd could not execute the program at all, because the wrapper
its ExecStart names was not installed -- and the name glob swallowed it exactly
as it swallows the by-design exit 1 that means "the report found something".
The timer leg could not cover it either: the timer was healthy and fired on
schedule; the unit ran and could not exec. So the only signal that went out was
the OnFailure embed the board already treats as expected.

What this file keeps true:

  * the accepted exit is ignored, and NOTHING else from that unit is,
  * a unit killed by a SIGNAL is never ignored -- ExecMainStatus holds the
    signal number there, so a status-only test would accept a SIGHUP death as
    the accepted exit, and
  * a status that cannot be read reports. An unreadable property must never
    inherit an ignore.

The block is extracted from the shipped script by marker, so renaming or
deleting it fails this file rather than testing a copy that no longer ships.
systemd is not involved: a stub `systemctl` on PATH answers the two `show`
properties.
"""
import os
import pathlib
import shutil
import subprocess

import pytest

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "ktp-data-server-health.sh"
MARKER = "ktp-failed-unit-ignore"
# CI runs plain bash; on a Windows workstation "bash" resolves to WSL's, which
# cannot see these paths -- point KTP_TEST_BASH at Git Bash there.
BASH = os.environ.get("KTP_TEST_BASH", "bash")

pytestmark = pytest.mark.skipif(shutil.which(BASH) is None, reason="needs bash")


def block():
    begin, end = "# >>> %s" % MARKER, "# <<< %s" % MARKER
    text = SCRIPT.read_text(encoding="utf-8")
    assert begin in text and end in text, "%s markers are gone from the shipped script" % MARKER
    body = text.split(begin, 1)[1].split("\n", 1)[1].split(end, 1)[0]
    assert "failed_unit_accepted()" in body, "the function under test is not in the block"
    assert len(body) > 600, "extracted block is implausibly small (%d bytes)" % len(body)
    return body


def stub_systemctl(tmp_path, status, code):
    """A `systemctl show -p <prop> --value` that answers those two properties.

    status/code of None means the property is unreadable -- the stub exits 1
    with no output, which is what a missing or malformed unit does.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    answers = {"ExecMainStatus": status, "ExecMainCode": code}
    lines = ["#!/usr/bin/env bash", 'prop=""', "for a in \"$@\"; do",
             '  case "$a" in -p) next=1 ;; *) if [ "${next:-0}" = 1 ]; then prop=$a; next=0; fi ;; esac',
             "done"]
    for prop, value in answers.items():
        if value is None:
            lines.append('if [ "$prop" = "%s" ]; then exit 1; fi' % prop)
        else:
            lines.append('if [ "$prop" = "%s" ]; then echo "%s"; exit 0; fi' % (prop, value))
    lines.append("exit 1")
    p = bindir / "systemctl"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    p.chmod(0o755)
    return bindir


def verdict(tmp_path, unit, status=1, code=1, body=None, **env):
    bindir = stub_systemctl(tmp_path, status, code)
    exports = "".join('export %s=%s\n' % (k, v) for k, v in env.items())
    script = tmp_path / "probe.sh"
    script.write_text(
        "declare -A detail=()\n" + exports + (body if body is not None else block())
        + '\nfailed_unit_accepted "%s"\n' % unit,
        encoding="utf-8", newline="\n")
    r = subprocess.run([BASH, script.as_posix()], capture_output=True, text=True,
                       env={**os.environ, "PATH": bindir.as_posix() + os.pathsep
                            + os.environ.get("PATH", "")})
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


# --- the unit the ignore was installed for -------------------------------

def test_the_accepted_exit_is_ignored(tmp_path):
    """Exit 1 IS the weekly finding; the embed already carried it."""
    assert verdict(tmp_path, "ktp-weekly-outliers.service", status=1, code=1) == "ignore"


def test_203_exec_reports_and_names_the_status(tmp_path):
    """The 2026-10-12 failure. A name-only ignore returned nothing here."""
    out = verdict(tmp_path, "ktp-weekly-outliers.service", status=203, code=1)
    assert out.startswith("report"), out
    assert "exit=203" in out, out


@pytest.mark.parametrize("status", [0, 2, 7, 127, 200, 226])
def test_no_other_exit_from_that_unit_is_ignored(tmp_path, status):
    assert verdict(tmp_path, "ktp-weekly-outliers.service",
                   status=status, code=1).startswith("report")


def test_a_signal_death_is_not_the_accepted_exit(tmp_path):
    """ExecMainStatus holds the SIGNAL number when the unit was killed, so
    status 1 with CLD_KILLED is SIGHUP, not the by-design exit 1."""
    out = verdict(tmp_path, "ktp-weekly-outliers.service", status=1, code=2)
    assert out.startswith("report"), out
    assert "code=2" in out, out


@pytest.mark.parametrize("status,code", [(None, 1), (1, None), (None, None)])
def test_an_unreadable_status_reports(tmp_path, status, code):
    """An unreadable property must not inherit an ignore."""
    assert verdict(tmp_path, "ktp-weekly-outliers.service",
                   status=status, code=code).startswith("report")


# --- everything else -------------------------------------------------------

def test_an_unlisted_unit_reports(tmp_path):
    assert verdict(tmp_path, "some-other.service", status=1, code=1) == "report"


def test_the_name_only_ignore_still_works(tmp_path):
    """FAILED_UNIT_IGNORE keeps its old meaning for a unit whose failure is
    accepted however it fails -- an unused snap hook, say."""
    assert verdict(tmp_path, "snapd.seeded.service", status=203, code=1,
                   FAILED_UNIT_IGNORE="snapd.*") == "ignore"
    assert verdict(tmp_path, "snapd.seeded.service", status=203, code=1) == "report"


def test_a_name_only_ignore_wins_over_a_status_ignore(tmp_path):
    """Both lists can name one unit; the broader one is checked first, so the
    operator can widen an ignore in the env file without editing the script."""
    assert verdict(tmp_path, "ktp-weekly-outliers.service", status=203, code=1,
                   FAILED_UNIT_IGNORE="ktp-weekly-outliers.service") == "ignore"


def test_extra_pairs_come_from_the_environment(tmp_path):
    assert verdict(tmp_path, "thing.service", status=42, code=1,
                   FAILED_UNIT_IGNORE_EXIT="thing.service=42") == "ignore"
    assert verdict(tmp_path, "thing.service", status=43, code=1,
                   FAILED_UNIT_IGNORE_EXIT="thing.service=42").startswith("report")


# --- the shipped defaults, and proof the guard can fail --------------------

def test_the_shipped_default_pins_the_unit_to_exit_1(tmp_path):
    body = block()
    assert "ktp-weekly-outliers.service=1" in body, \
        "the shipped FAILED_UNIT_IGNORE_EXIT no longer pins that unit to exit 1"


def test_the_unit_is_no_longer_ignored_by_name_anywhere(tmp_path):
    """The defect, asserted as an absence against a positive control: the
    weekly unit must not appear in a name-only ignore in the whole script."""
    text = SCRIPT.read_text(encoding="utf-8")
    offenders = [l for l in text.splitlines()
                 if l.startswith("FAILED_UNIT_IGNORE=")
                 and "ktp-weekly-outliers" in l]
    assert offenders == [], offenders
    # positive control: the status list DOES name it, so the probe can see a hit
    assert [l for l in text.splitlines()
            if l.startswith("FAILED_UNIT_IGNORE_EXIT=") and "ktp-weekly-outliers" in l]


def test_dropping_the_status_comparison_makes_203_pass(tmp_path):
    """Mutation: without the status test the block ignores 203 again, which is
    the behaviour this file exists to prevent. The mutation is asserted to have
    LANDED before it is trusted -- a mutant that fails to apply runs the
    unmutated block and reports a pass."""
    body = block()
    needle = '[ "$reason" = "1" ] && [ "$code" = "$want" ]'
    assert body.count(needle) == 1, "the guard is not where the mutation expects it"
    mutant = body.replace(needle, "true")
    assert mutant != body and needle not in mutant, "the mutation did not land"
    assert verdict(tmp_path, "ktp-weekly-outliers.service",
                   status=203, code=1, body=mutant) == "ignore"
    # and the unmutated block, same input, on the same stub: reports
    assert verdict(tmp_path, "ktp-weekly-outliers.service",
                   status=203, code=1).startswith("report")
