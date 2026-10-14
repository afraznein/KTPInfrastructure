"""scripts/ktp-hltv-api-drift-guard.sh -- the schedule around check-hltv-api-drift.py.

The checker exits 0/1/2/3 and posts nothing, on purpose: what "drift" means stays in one
reviewed script. This wrapper's whole job is turning those codes into an alert someone
sees, so what is worth testing is the mapping, the exit passthrough, and one safety
property that matters more than any of it:

⛔ THE CHECKER'S OUTPUT MUST NEVER REACH AN ALERT. On drift that output is a diff of the
live hltv-api.py, which holds AUTH_KEY. Exit 3 is the checker refusing to print because it
could not prove it had redacted -- the one case where forwarding is most tempting and
least safe. A stub that prints a secret-shaped sentinel pins that.

The wrapper is run for real against a stub checker. Pointing the routing and relay paths at
files that do not exist makes it log `WOULD POST (<severity>) ... <text>` instead of
posting, which is exactly the seam these tests need: no network, and the severity and the
text are both readable.
"""
import os
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "scripts" / "ktp-hltv-api-drift-guard.sh"
CRON = ROOT / "scripts" / "cron.d" / "check-hltv-api-drift"
ROTATE = ROOT / "scripts" / "ktp-hltv-api-drift.logrotate"
HEALTH = ROOT / "scripts" / "ktp-data-server-health.sh"

# ⚠️ On Windows a bare `bash` resolves to WSL's, which cannot read a C:\... path and exits
# 127 -- every behavioural test then fails for a reason unrelated to the script. Point
# KTP_TEST_BASH at git-bash there:
#   KTP_TEST_BASH="C:\Program Files\Git\usr\bin\bash.exe"
BASH = os.environ.get("KTP_TEST_BASH", "bash")

pytestmark = pytest.mark.skipif(shutil.which(BASH) is None, reason="needs bash")

TEXT = WRAPPER.read_text(encoding="utf-8")
LOG_PATH = "/var/log/ktp-hltv-api-drift.log"
SECRET = "qqxzvv-sentinel-key-must-never-be-posted"

STUB = """#!/usr/bin/env bash
# Stands in for check-hltv-api-drift.py.
printf '%%s\\n' "reference: /stub/hltv-api.py.example @ abc1234 -- 0 commit(s) BEHIND"
printf '%%s\\n' 'AUTH_KEY = "%s"'
exit %s
"""


def code_lines():
    """Non-comment lines only -- the header deliberately discusses the output it forbids."""
    return "\n".join(l for l in TEXT.split("\n")
                     if l.strip() and not l.strip().startswith("#"))


def run(tmp_path, exit_code, make_checker=True):
    checker = tmp_path / "check-hltv-api-drift.py"
    if make_checker:
        checker.write_text(STUB % (SECRET, exit_code), encoding="utf-8", newline="\n")
        checker.chmod(0o755)
    env = dict(os.environ)
    env.update({
        "KTP_DRIFT_CHECKER": str(checker),
        "KTP_DRIFT_STATE": str(tmp_path / "state"),
        # Deliberately absent, so post_alert logs WOULD POST instead of posting.
        "KTP_DRIFT_ROUTING": str(tmp_path / "no-such-routing.sh"),
        "KTP_DRIFT_RELAY": str(tmp_path / "no-such-relay.conf"),
    })
    p = subprocess.run([BASH, str(WRAPPER)], capture_output=True, text=True, env=env)
    return p.returncode, p.stdout + p.stderr, tmp_path / "state"


def posts(out):
    """Every WOULD POST entry as (severity, full text).

    ⛔ The text is captured ACROSS LINES, up to the next timestamped log entry. An earlier
    version used `(.*)`, which does not match newlines, so it inspected only the first
    line of the alert -- and a mutant that appended the checker's whole output to the
    embed passed the leak test, because the secret landed on line two. The capture has to
    span the entry or the safety test is decoration.
    """
    return [(m.group(1), m.group(2)) for m in
            re.finditer(r"WOULD POST \((\w+)\) but [^:]*: (.*?)(?=\n\[\d{4}-|\Z)", out, re.S)]


# --------------------------------------------------------------------------
# the safety property
# --------------------------------------------------------------------------

@pytest.mark.parametrize("code", [1, 3])
def test_the_checkers_output_never_reaches_an_alert(tmp_path, code):
    """THE test. On drift the output is a diff of a file holding AUTH_KEY, and exit 3 is
    the checker refusing to print because redaction could not be proven."""
    rc, out, _ = run(tmp_path, code)
    found = posts(out)
    assert found, "exit %s posted nothing\n%s" % (code, out)
    for _, text in found:
        assert SECRET not in text, "the alert carried the checker's output: %s" % text


def test_the_output_does_still_reach_the_log(tmp_path):
    """The detail has to live somewhere -- just not in Discord."""
    rc, out, _ = run(tmp_path, 1)
    assert SECRET in out, "the run's own stdout lost the checker output entirely"


# --------------------------------------------------------------------------
# the exit-code mapping
# --------------------------------------------------------------------------

def test_a_clean_run_posts_nothing_and_exits_zero(tmp_path):
    rc, out, _ = run(tmp_path, 0)
    assert rc == 0
    assert posts(out) == [], "a clean run must be silent; posted %r" % posts(out)
    assert "no drift; posting nothing" in out


@pytest.mark.parametrize("code,severity", [(1, "warn"), (2, "page"), (3, "page"), (7, "page")])
def test_every_nonzero_exit_posts_at_the_right_severity(tmp_path, code, severity):
    rc, out, _ = run(tmp_path, code)
    found = posts(out)
    assert len(found) == 1, "exit %s posted %d times" % (code, len(found))
    assert found[0][0] == severity, "exit %s posted as %s" % (code, found[0][0])


@pytest.mark.parametrize("code", [0, 1, 2, 3, 7])
def test_the_checkers_exit_code_passes_through_unchanged(tmp_path, code):
    """The log, the state file and the wrapper must all say what the tool said."""
    rc, _, _ = run(tmp_path, code)
    assert rc == code


def test_could_not_look_names_both_causes_including_the_deploy_order_one(tmp_path):
    """Exit 2 is the state the box is in TODAY, and one of its two causes is a fielding
    mistake we can make. Guessing between them is what sends someone to the wrong place."""
    _, out, _ = run(tmp_path, 2)
    text = posts(out)[0][1]
    assert "could not look" in text.lower()
    assert "#708" in text, "the too-early-fielding cause is not named"


def test_redaction_failure_is_not_reported_as_drift(tmp_path):
    _, out, _ = run(tmp_path, 3)
    text = posts(out)[0][1]
    assert "redaction" in text.lower()
    assert "secrets-safety" in text.lower() or "secret" in text.lower()


# --------------------------------------------------------------------------
# preflight and state
# --------------------------------------------------------------------------

def test_a_missing_checker_is_could_not_look_not_a_clean_result(tmp_path):
    rc, out, state = run(tmp_path, 0, make_checker=False)
    assert rc == 2
    found = posts(out)
    assert len(found) == 1 and found[0][0] == "page"
    assert "not a clean result" in found[0][1].lower()


@pytest.mark.parametrize("code", [0, 1, 2])
def test_the_state_file_records_the_exit_code(tmp_path, code):
    rc, out, state = run(tmp_path, code)
    f = state / "last"
    assert f.is_file(), "no state file written\n%s" % out
    epoch, recorded = f.read_text(encoding="utf-8").split()
    assert recorded == str(code)
    assert int(epoch) > 1_600_000_000


# --------------------------------------------------------------------------
# the shape that makes the whole chain work
# --------------------------------------------------------------------------

def test_it_is_syntactically_valid():
    p = subprocess.run([BASH, "-n", str(WRAPPER)], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr


def test_it_does_not_modify_the_checker():
    """The checker's bytes are pinned to a review. A wrapper that edits its subject is how
    a reviewed artifact stops being the thing that was reviewed."""
    code = code_lines()
    assert "check-hltv-api-drift.py" in TEXT  # it is named
    for bad in (">", ">>", "sed -i", "tee "):
        assert "%s $CHECKER" % bad not in code
        assert '%s "$CHECKER"' % bad not in code


def test_cron_logrotate_and_health_all_name_the_same_log():
    """The silent-break shape: each file correct alone, the chain doing nothing."""
    assert LOG_PATH in CRON.read_text(encoding="utf-8")
    assert LOG_PATH in ROTATE.read_text(encoding="utf-8")
    assert LOG_PATH in HEALTH.read_text(encoding="utf-8")


def test_cron_runs_the_wrapper_not_the_checker_directly():
    """Running the checker straight from cron gets the schedule with none of the alerting,
    which is the shape that looks installed and reports nothing."""
    cron = CRON.read_text(encoding="utf-8")
    m = re.search(r"(?m)^(\d+)\s+(\d+)\s+\*\s+\*\s+\*\s+root\s+(\S+)", cron)
    assert m, "no daily root entry found"
    assert m.group(3).endswith("ktp-hltv-api-drift-guard"), \
        "cron runs %s, not the wrapper" % m.group(3)


def test_cron_runs_the_extensionless_installed_name():
    """The guard family installs without the extension. A cron entry naming the .sh is
    203/EXEC, which is exactly how ktp-weekly-outliers sat dead for a week."""
    cron = CRON.read_text(encoding="utf-8")
    m = re.search(r"(?m)^\d+\s+\d+\s+\*\s+\*\s+\*\s+root\s+(\S+)", cron)
    assert m, "no daily root entry found"
    assert not m.group(1).endswith(".sh"), \
        "cron names %s; install drops the extension" % m.group(1)


def test_cron_is_daily_and_clear_of_the_other_morning_readers():
    """06:15 review-integrity, 06:20+jitter install-freshness, 06:35 corpus-integrity."""
    cron = CRON.read_text(encoding="utf-8")
    m = re.search(r"(?m)^(\d+)\s+(\d+)\s+\*\s+\*\s+\*\s+root\s", cron)
    minute, hour = int(m.group(1)), int(m.group(2))
    assert hour == 6 and minute > 35, "expected after 06:35, got %02d:%02d" % (hour, minute)


def test_the_deploy_order_warning_survives():
    """Fielded before #708 this pages every morning. The reason has to stay with it."""
    for f in (TEXT, CRON.read_text(encoding="utf-8")):
        assert "#708" in f
    assert "DEPLOY ORDER" in CRON.read_text(encoding="utf-8")
