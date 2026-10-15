"""ktp-map-coefficients.service must permit every path the refit writes.

Three defects shipped in this pair and all three would have failed the FIRST
Monday run, silently from the unit's point of view:

  1. ProtectSystem=strict with ReadWritePaths naming only the repo and /var/log,
     while #707 had moved the fit's writes to /var/lib/ktp-map-coefficients --
     so `git worktree add`, the entire point of #707, would be denied.
  2. TimeoutStartSec=30min against a measured ~61-minute fit.
  3. LOG defaulting to a bare file in /var/log, which is 775 root:syslog and so
     uncreatable by User=ktpreports -- the script's first action.

None is visible by reading the unit alone: (1) needs #707's diff, (2) needs a
measured duration, (3) needs the box's filesystem permissions.

So these tests DERIVE the script's write paths from the script and check the unit
covers them, rather than restating a list that would drift the same way.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
UNIT = ROOT / "scripts" / "ktp-map-coefficients.service"
TIMER = ROOT / "scripts" / "ktp-map-coefficients.timer"
SCRIPT = ROOT / "scripts" / "ktp-map-coefficients-refit.sh"

UNIT_TEXT = UNIT.read_text(encoding="utf-8")
SCRIPT_TEXT = SCRIPT.read_text(encoding="utf-8")


def directive(name):
    """A directive's value from the unit, ignoring commented-out lines."""
    m = re.search(r"(?m)^%s=(.*)$" % re.escape(name), UNIT_TEXT)
    return m.group(1).strip() if m else None


def script_write_paths():
    """Absolute default paths the script writes to, taken FROM the script.

    Parsed from the `VAR="${VAR:-/path}"` defaults rather than listed here, so a
    path that moves in the script and not in the unit fails this file.
    """
    out = {}
    for var in ("LOG", "PROPOSAL", "WORKTREE"):
        m = re.search(r'%s="\$\{%s:-([^}]+)\}"' % (var, var), SCRIPT_TEXT)
        assert m, "%s default is gone from the script" % var
        out[var] = m.group(1)
    return out


def writable_roots():
    """Every filesystem root the unit grants, including the implicit ones.

    StateDirectory=X and LogsDirectory=X grant /var/lib/X and /var/log/X -- that
    is the whole reason they are used here, so a test that only read
    ReadWritePaths would call a working unit broken.
    """
    roots = []
    rw = directive("ReadWritePaths")
    if rw:
        roots.extend(rw.split())
    sd = directive("StateDirectory")
    if sd:
        roots.extend("/var/lib/" + d for d in sd.split())
    ld = directive("LogsDirectory")
    if ld:
        roots.extend("/var/log/" + d for d in ld.split())
    return roots


# --------------------------------------------------------------------------
# the defect that mattered
# --------------------------------------------------------------------------

def test_every_path_the_script_writes_is_writable_in_the_unit():
    """THE test. ProtectSystem=strict means an unlisted path is read-only, and
    the failure surfaces as a git or redirect error, not as a sandbox error."""
    roots = writable_roots()
    for var, path in script_write_paths().items():
        assert any(path == r or path.startswith(r.rstrip("/") + "/") for r in roots), \
            "%s writes %s, which no ReadWritePaths/StateDirectory/LogsDirectory covers: %r" \
            % (var, path, roots)


def test_protect_system_is_still_strict():
    """If this is ever relaxed the test above stops meaning anything."""
    assert directive("ProtectSystem") == "strict"


def test_the_state_and_logs_directories_are_declared():
    """They do the creating AND the chowning. Without them the paths are both
    read-only and absent, and /var/log cannot be written by this User at all."""
    assert directive("StateDirectory") == "ktp-map-coefficients"
    assert directive("LogsDirectory") == "ktp-map-coefficients"


def test_the_log_is_not_a_bare_file_in_var_log():
    """/var/log is 775 root:syslog on the data server, so User=ktpreports cannot
    create a file there -- and `exec >>"$LOG"` is the script's first action."""
    log = script_write_paths()["LOG"]
    assert log != "/var/log/ktp-map-coefficients.log"
    assert log.startswith("/var/log/ktp-map-coefficients/")


# --------------------------------------------------------------------------
# the timeout, against a measurement rather than a guess
# --------------------------------------------------------------------------

def _seconds(v):
    m = re.fullmatch(r"(\d+)(s|sec|m|min|h)?", v.strip())
    assert m, "unparsed TimeoutStartSec: %r" % v
    n, unit = int(m.group(1)), (m.group(2) or "s")
    return n * {"s": 1, "sec": 1, "m": 60, "min": 60, "h": 3600}[unit]


# 2026-10-14, the first real run under the unit's own Nice=10/IOSchedulingClass=idle:
# two passes over ~690 labelled halves in 2h08m00s, so ~64 min a pass. The job is
# ONE pass -- it was three until that day, which is how a 3h cap came to be
# shorter than the job it was raised to clear.
MEASURED_FIT_SECONDS = 64 * 60


def test_the_start_timeout_clears_the_measured_fit():
    v = directive("TimeoutStartSec")
    assert v, "the bound was removed; a wedged weekly run would block every later one"
    assert _seconds(v) > MEASURED_FIT_SECONDS * 2, \
        "TimeoutStartSec=%s does not clear the measured %dmin fit with headroom" \
        % (v, MEASURED_FIT_SECONDS // 60)


def test_the_refit_makes_one_pass_over_the_corpus():
    """The timeout above is a bound on the whole job, so it only means anything
    while the job is one fit. Three passes put a 3h cap under the real runtime."""
    code = "\n".join(ln for ln in SCRIPT_TEXT.split("\n")
                      if ln.strip() and not ln.strip().startswith("#"))
    n = code.count("scripts.fit_map_coefficients")
    assert n == 1, "%d fit passes at ~%dmin each, under a %s cap" % (
        n, MEASURED_FIT_SECONDS // 60, directive("TimeoutStartSec"))


def test_the_bound_still_exists_and_its_reason_survives():
    """Type=oneshot has no start timeout by default. Removing the bound instead of
    raising it is the other way to get this wrong."""
    assert "TimeoutStartSec" in UNIT_TEXT
    assert "unbounded network calls" in UNIT_TEXT
    assert "SHORTER THAN THE JOB" in UNIT_TEXT


# --------------------------------------------------------------------------
# the pair has to stay coherent
# --------------------------------------------------------------------------

def test_the_timer_and_service_name_each_other():
    assert "ktp-map-coefficients-refit.sh" in UNIT_TEXT
    t = TIMER.read_text(encoding="utf-8")
    assert "OnCalendar=" in t and "WantedBy=timers.target" in t


def test_it_runs_as_the_user_the_grant_was_made_to():
    """The fit reads the match database as ktpreports; that is why dpl-e72e needed
    a GRANT at all. A changed User= silently re-opens that blocker."""
    assert directive("User") == "ktpreports"
