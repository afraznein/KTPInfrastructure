"""ktp-ac-retention.sh sweep 1: "retention off" and "store missing" are different.

The upload sweep used to be guarded by one condition --
`[ -d "$UPLOADS_DIR" ] && [ "$UPLOAD_RETENTION_DAYS" -gt 0 ]` -- whose single else
branch printed `WARN <dir> missing; skipping upload sweep` for BOTH failures. Since
line 40 defaults an unset `UPLOAD_RETENTION_DAYS` to 0, the ordinary opt-in default
reported the evidence store as ABSENT while 104 day-dirs sat in it.

Two properties are asserted here that reading the guard does not show:

  - retention off with the store PRESENT must not claim anything is missing, and
    says so on stdout rather than as a WARN on stderr -- the sibling sweeps' house
    style for a configured-off lane, and a correct configuration should not mail
    cron output every night.
  - the directory is tested FIRST and separately, so an absent store still warns
    under the default of 0. Checking retention first would have silenced that
    warning on every host that never sets the variable, which is all of them by
    design.

The shipped script is run whole, under bash, through the sibling module's harness:
the branch under test is the branch the data server will take. The sweep leg runs
under DRY_RUN=1 because its live path issues an unLIMITed `UPDATE ktp_ac_sessions`
that the fake mysql refuses by design.

A grep note worth keeping, since it cost a probe: the warning is INTERPOLATED
(`WARN $UPLOADS_DIR missing`), so grepping the rendered phrase returns zero on a
script that plainly emits it. These tests match the format string's literal tail.
"""
import pathlib

import pytest

from tests.unit.test_ac_retention_net_identity import SCRIPT, run_script

OFF = "upload sweep is off (UPLOAD_RETENTION_DAYS=0)"
MISSING = "missing; skipping upload sweep"


def _store(tmp_path, *days):
    """A real uploads dir holding ISO day-dirs, as the API writes them."""
    d = tmp_path / "uploads"
    d.mkdir(exist_ok=True)
    for day in days:
        (d / day).mkdir(exist_ok=True)
    return d


# ── non-vacuity: the fixture has to straddle the cutoff ────────────────

def test_the_store_exists_and_straddles_the_cutoff(tmp_path):
    """Both legs below assert something only because this holds."""
    store = _store(tmp_path, "2020-01-01", "2099-01-01")
    assert store.is_dir()
    r = run_script(tmp_path, env={"UPLOADS_DIR": str(store),
                                  "UPLOAD_RETENTION_DAYS": "30", "DRY_RUN": "1"})
    assert r.rc == 0, r.err
    assert "would delete" in r.out
    assert "2020-01-01" in r.out and "2099-01-01" not in r.out


# ── the split ──────────────────────────────────────────────────────────

def test_retention_off_does_not_claim_the_store_is_missing(tmp_path):
    """The defect: an unset horizon reported the evidence store as absent."""
    store = _store(tmp_path, "2020-01-01")
    r = run_script(tmp_path, env={"UPLOADS_DIR": str(store),
                                  "UPLOAD_RETENTION_DAYS": "0"})
    assert r.rc == 0, r.err
    assert OFF in r.out
    assert MISSING not in r.out and MISSING not in r.err


def test_an_unset_horizon_is_the_same_as_zero(tmp_path):
    """Line 40 defaults it to 0, so unset must take the off branch, not the warn."""
    store = _store(tmp_path, "2020-01-01")
    r = run_script(tmp_path, env={"UPLOADS_DIR": str(store),
                                  "UPLOAD_RETENTION_DAYS": ""})
    assert r.rc == 0, r.err
    assert OFF in r.out
    assert MISSING not in r.out and MISSING not in r.err


def test_the_off_message_is_not_a_warning_on_stderr(tmp_path):
    """A configured-off lane is normal state; only a missing store is a WARN."""
    store = _store(tmp_path, "2020-01-01")
    r = run_script(tmp_path, env={"UPLOADS_DIR": str(store),
                                  "UPLOAD_RETENTION_DAYS": "0"})
    assert OFF in r.out
    assert "WARN" not in r.err


def test_a_missing_store_still_warns_under_the_default(tmp_path):
    """The ordering leg: retention 0 must not swallow an absent evidence store."""
    gone = tmp_path / "no-such-uploads"
    assert not gone.exists()
    r = run_script(tmp_path, env={"UPLOADS_DIR": str(gone),
                                  "UPLOAD_RETENTION_DAYS": "0"})
    assert r.rc == 0, r.err
    assert MISSING in r.err
    assert OFF not in r.out


def test_a_missing_store_warns_with_retention_on(tmp_path):
    gone = tmp_path / "no-such-uploads"
    r = run_script(tmp_path, env={"UPLOADS_DIR": str(gone),
                                  "UPLOAD_RETENTION_DAYS": "30"})
    assert r.rc == 0, r.err
    assert MISSING in r.err
    assert OFF not in r.out


def test_retention_on_with_a_present_store_sweeps(tmp_path):
    """Neither message: the third outcome is the sweep actually reporting."""
    store = _store(tmp_path, "2020-01-01")
    r = run_script(tmp_path, env={"UPLOADS_DIR": str(store),
                                  "UPLOAD_RETENTION_DAYS": "30", "DRY_RUN": "1"})
    assert r.rc == 0, r.err
    assert "uploads swept 1 day-dir(s)" in r.out
    assert OFF not in r.out
    assert MISSING not in r.out and MISSING not in r.err


def test_the_off_message_carries_the_value_that_caused_it(tmp_path):
    """"off" without the number sends the reader back to the script to find out."""
    store = _store(tmp_path, "2020-01-01")
    r = run_script(tmp_path, env={"UPLOADS_DIR": str(store),
                                  "UPLOAD_RETENTION_DAYS": "0"})
    assert "UPLOAD_RETENTION_DAYS=0" in r.out


# ── mutation tests: each restores a defect and names what reddens ──────

COMBINED_HEAD = (
    'if [ ! -d "$UPLOADS_DIR" ]; then\n'
    '    echo "[$(ts)] ac-retention: WARN $UPLOADS_DIR missing;'
    ' skipping upload sweep" >&2\n'
    'elif [ "${UPLOAD_RETENTION_DAYS}" -le 0 ]; then\n'
    '    echo "[$(ts)] ac-retention: upload sweep is off'
    ' (UPLOAD_RETENTION_DAYS=${UPLOAD_RETENTION_DAYS}); retaining all bundles"\n'
    'else'
)
SWEEP_TAIL = (
    '    echo "[$(ts)] ac-retention: uploads swept ${swept}'
    ' day-dir(s) older than ${cutoff}"\nfi'
)


def _mutate(*pairs):
    text = SCRIPT.read_text(encoding="utf-8")
    for old, new in pairs:
        assert text.count(old) == 1, "mutation anchor is not unique: %r" % old
        text = text.replace(old, new)
    return text


def test_mutation_the_combined_guard_reddens_the_off_branch(tmp_path):
    """Restores the exact pre-fix shape: one guard, one else, one message.

    Exercises test_retention_off_does_not_claim_the_store_is_missing -- with the
    store present and retention 0, the recombined guard warns that it is missing.
    """
    text = _mutate(
        (COMBINED_HEAD,
         'if [ -d "$UPLOADS_DIR" ] && [ "${UPLOAD_RETENTION_DAYS}" -gt 0 ]; then'),
        (SWEEP_TAIL,
         '    echo "[$(ts)] ac-retention: uploads swept ${swept}'
         ' day-dir(s) older than ${cutoff}"\n'
         'else\n'
         '    echo "[$(ts)] ac-retention: WARN $UPLOADS_DIR missing;'
         ' skipping upload sweep" >&2\n'
         'fi'),
    )
    store = _store(tmp_path, "2020-01-01")
    r = run_script(tmp_path, script_text=text,
                   env={"UPLOADS_DIR": str(store), "UPLOAD_RETENTION_DAYS": "0"})
    assert MISSING in r.err
    assert OFF not in r.out


def test_mutation_retention_checked_first_reddens_the_ordering_leg(tmp_path):
    """Swaps the two branches.

    Exercises test_a_missing_store_still_warns_under_the_default -- with retention
    tested first, an absent store under the opt-in default reports "off" and the
    warning is never reachable on a host that leaves the variable unset.
    """
    text = _mutate((
        COMBINED_HEAD,
        'if [ "${UPLOAD_RETENTION_DAYS}" -le 0 ]; then\n'
        '    echo "[$(ts)] ac-retention: upload sweep is off'
        ' (UPLOAD_RETENTION_DAYS=${UPLOAD_RETENTION_DAYS}); retaining all bundles"\n'
        'elif [ ! -d "$UPLOADS_DIR" ]; then\n'
        '    echo "[$(ts)] ac-retention: WARN $UPLOADS_DIR missing;'
        ' skipping upload sweep" >&2\n'
        'else',
    ))
    gone = tmp_path / "no-such-uploads"
    r = run_script(tmp_path, script_text=text,
                   env={"UPLOADS_DIR": str(gone), "UPLOAD_RETENTION_DAYS": "0"})
    assert MISSING not in r.err
    assert OFF in r.out


def test_mutation_a_silent_off_branch_reddens(tmp_path):
    """Drops the off message: a lane that reports nothing reads as one that ran."""
    text = _mutate((
        '    echo "[$(ts)] ac-retention: upload sweep is off'
        ' (UPLOAD_RETENTION_DAYS=${UPLOAD_RETENTION_DAYS}); retaining all bundles"',
        '    :',
    ))
    store = _store(tmp_path, "2020-01-01")
    r = run_script(tmp_path, script_text=text,
                   env={"UPLOADS_DIR": str(store), "UPLOAD_RETENTION_DAYS": "0"})
    assert OFF not in r.out


def test_mutation_dropped_zero_guard_reddens(tmp_path):
    """Removes the `-le 0` gate: retention 0 then sweeps the whole archive.

    "-0 days" resolves to TODAY, so every day-dir sorts older than the cutoff.
    """
    text = _mutate((
        'elif [ "${UPLOAD_RETENTION_DAYS}" -le 0 ]; then',
        'elif false; then',
    ))
    store = _store(tmp_path, "2020-01-01", "2099-01-01")
    r = run_script(tmp_path, script_text=text,
                   env={"UPLOADS_DIR": str(store), "UPLOAD_RETENTION_DAYS": "0",
                        "DRY_RUN": "1"})
    assert OFF not in r.out
    assert "would delete" in r.out
