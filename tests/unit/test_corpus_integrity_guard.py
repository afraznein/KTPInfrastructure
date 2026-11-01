"""scripts/ktp-corpus-integrity-guard.sh -- the daily accrual check.

The first version of this guard PARSED `mysql --table` output to pull a named metric out
of the two pinned reports. That cannot work: the position file is row-oriented key/value
(the metric name is a VALUE in a name column) while the producer-clock file is
column-oriented per stream. A trial run proved it -- it read `orphan_max_id=9` (the row
NUMBER, while every real cell was NULL), `epoch_zero_rows=58442` against a true 326,429,
and produced the SAME watermark for two different tables.

So the parser is gone and the question is asked directly. What is left to test is the
things that can still be silently wrong: the predicates, the sentinel that stops a
corpus-wide false finding, read-only-ness, and agreement across the four files that have
to name the same log. A mismatch in that last group is the shape where every file is
correct alone and the chain does nothing.
"""
import os
import pathlib
import re
import shlex
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
GUARD = ROOT / "scripts" / "ktp-corpus-integrity-guard.sh"
CRON = ROOT / "scripts" / "cron.d" / "ktp-corpus-integrity-guard"
ROTATE = ROOT / "scripts" / "ktp-corpus-integrity-guard.logrotate"
HEALTH = ROOT / "scripts" / "ktp-data-server-health.sh"
BASH = os.environ.get("KTP_TEST_BASH", "bash")

pytestmark = pytest.mark.skipif(shutil.which(BASH) is None, reason="needs bash")
LOG_PATH = "/var/log/ktp-corpus-integrity-guard.log"
TEXT = GUARD.read_text(encoding="utf-8")


def block(name):
    begin, end = "# >>> %s" % name, "# <<< %s" % name
    assert begin in TEXT and end in TEXT, "%s markers are gone" % name
    return TEXT.split(begin, 1)[1].split("\n", 1)[1].split(end, 1)[0]


def test_it_is_syntactically_valid():
    # A relative path with a cwd, not an absolute one: an absolute Windows path reaches
    # bash with its separators eaten, so this leg failed off-CI while every other leg
    # in the file passed -- a red that says nothing about the guard.
    p = subprocess.run([BASH, "-n", GUARD.relative_to(ROOT).as_posix()],
                       cwd=str(ROOT), capture_output=True, text=True)
    assert p.returncode == 0, p.stderr


def test_the_parser_is_gone_and_must_not_come_back():
    """The regression that matters. It did not fail loudly -- it returned the wrong
    number for the right-looking metric, which is worse than an error."""
    assert "metric_of" not in TEXT
    assert "awk" not in TEXT, "parsing --table output is what produced orphan_max_id=9"


def test_epoch_zero_uses_the_function_not_a_literal():
    """FROM_UNIXTIME(0) renders 1969-12-31 19:00:00 on an ET server. Hardcoding either
    that or a UTC literal is how this breaks on a box with a different clock -- and the
    ledger already warns not to carry a UTC literal into a follow-up query."""
    # Assert on CODE, not prose: the comment deliberately names the literal in order to
    # forbid it, and an earlier version of this test failed on its own explanation.
    pred = block("ktp-corpus-guard-predicates")
    code = "\n".join(ln for ln in pred.split("\n") if not ln.lstrip().startswith("#"))
    assert "FROM_UNIXTIME(0)" in code
    assert "1969-12-31" not in code
    assert "1970-01-01" not in code
    # and the forbidding comment must survive, or the next reader loses the reason
    assert "never hardcode that literal" in pred


def test_the_orphan_predicate_excludes_null_and_empty_match_ids():
    """`rows_match_id_null` is 72,062 on the position corpus and the .sql files flag it
    NOT a defect. Without these guards every one of them would score as an orphan."""
    pred = block("ktp-corpus-guard-predicates")
    assert "match_id IS NOT NULL" in pred
    assert 'match_id <> ""' in pred or "match_id <> ''" in pred


def test_there_is_a_sentinel_for_an_unreadable_ktp_matches():
    """An ungranted or empty ktp_matches turns EVERY row into an orphan. The .sql files
    halt on that rather than report it, and so must this -- a corpus-wide false finding
    is worse than no finding."""
    assert "ktp_matches" in TEXT
    assert "every row would score as an orphan" in TEXT
    # and it must DIE rather than carry on
    sentinel = TEXT.split("matches_rows=", 1)[1].split("log ", 1)[0]
    assert sentinel.count("die ") >= 2, "the sentinel must refuse on both unreadable and 0 rows"


def test_every_stream_entry_names_a_report_file_that_exists():
    streams = block("ktp-corpus-guard-streams")
    entries = re.findall(r'^\s*"([^"]+)"', streams, re.M)
    assert entries, "no stream entries parsed"
    for e in entries:
        parts = e.split(":")
        assert len(parts) == 4, "entry is not <label>:<table>:<idcol>:<report>: %r" % e
        assert (ROOT / "sql" / "integrity" / parts[3]).is_file(), \
            "stream names a missing report: %s" % parts[3]


def test_the_streams_are_the_two_that_have_carried_a_defect():
    streams = block("ktp-corpus-guard-streams")
    assert "ktp_position_samples" in streams
    assert "ktp_flag_state_events" in streams


def test_the_session_is_read_only_on_every_query():
    """Belt to the .sql files' braces: the server refuses a write even if a definition
    gains one later."""
    assert TEXT.count("SET SESSION TRANSACTION READ ONLY") >= 2, \
        "both the scalar helper and the report path must set it"


def test_the_read_only_proof_asks_the_server_rather_than_the_script():
    """The directive above is a REQUEST. It binds the credential it is given and no
    other, so on a write-capable login it is silently ineffective -- which is how an
    estate probe read a successful CREATE TABLE as a refusal. Counting the directive in
    this file can never see that. The proof has to come back from the server."""
    proof = block("ktp-corpus-guard-readonly-proof")
    assert "transaction_read_only" in proof, "the session state is never read back"
    assert "die " in proof, "a failed proof must refuse, not log and continue"
    # and the refusal must be keyed on a PRESENT expected value, not on the absence of
    # an error -- an empty answer is the case that used to read as a pass
    assert '[ "$ro" = "1" ]' in proof, "an empty or unexpected answer must not pass"


# ---------------------------------------------------------------------------
# Behavioural legs. Everything above reads the script; these RUN it against a
# mysql double, because a text assertion cannot tell a proof from a sentence.
# ---------------------------------------------------------------------------

STUB = r"""#!/usr/bin/env bash
# Test double for mysql(1). Answers only what this guard asks, from the environment, so
# each leg of the read-only proof can be driven on its own.
sql=""
while [ $# -gt 0 ]; do
    case "$1" in
        -e) sql="${2-}"; shift 2 ;;
        *)  shift ;;
    esac
done
case "$sql" in
    *ktp_corpus_guard_no_such_variable*)
        printf '%s\n' "${STUB_DISC-ERROR 1193 (HY000) at line 1: Unknown system variable}"
        exit 1 ;;
    *transaction_read_only*|*tx_read_only*) printf '%s\n' "${STUB_RO-1}" ;;
    # order matters: the orphan predicate names ktp_matches in a subquery, so the
    # per-stream defect counts must be matched before the sentinel's bare read
    *WHERE*)                                printf '0
' ;;
    *MAX*)                                  printf '100
' ;;
    *ktp_matches*)                          printf '5
' ;;
    *COUNT*)                                printf '0
' ;;
esac
"""


def run_guard(tmp_path, **stub_env):
    """Run the real guard with a stubbed mysql. Returns (returncode, combined output)."""
    stub = tmp_path / "mysql"
    stub.write_text(STUB, encoding="utf-8", newline="\n")
    os.chmod(str(stub), 0o755)
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    settings = {
        "KTP_CORPUS_GUARD_MYSQL": "./mysql",
        "KTP_CORPUS_GUARD_STATE": "./state",
        # only read on the accrual branch, which a clean stub run never takes
        "KTP_CORPUS_GUARD_SQL": "./sql",
        # point the relay at nothing: post_alert must never reach a network from a test,
        # and on the data server itself the real conf IS readable
        "KTP_CORPUS_GUARD_RELAY": "./no-such-relay.conf",
    }
    settings.update(stub_env)
    rel = os.path.relpath(str(GUARD), str(tmp_path)).replace(os.sep, "/")
    # Assignments go inside bash rather than through `env=`: `bash` on a Windows dev box
    # can resolve to WSL, which does not inherit the parent's environment, and the guard
    # then silently used its production defaults -- /var/lib and the real relay conf.
    script = "".join("export %s=%s\n" % (k, shlex.quote(v)) for k, v in settings.items())
    script += "exec bash %s\n" % shlex.quote(rel)
    p = subprocess.run([BASH, "-c", script], cwd=str(tmp_path),
                       capture_output=True, text=True)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def test_a_read_only_session_passes_the_proof_and_the_guard_runs(tmp_path):
    """The positive control. Without it a proof that refuses everything would look
    like a working guard."""
    rc, out = run_guard(tmp_path, STUB_RO="1")
    assert "read-only proof ok" in out, out
    assert "sentinel ok" in out, "the proof must not block a healthy run: %s" % out
    assert rc == 0, out


def test_a_writable_session_is_refused(tmp_path):
    rc, out = run_guard(tmp_path, STUB_RO="0")
    assert rc == 2, out
    assert "did not read back read-only" in out, out
    assert "sentinel ok" not in out, "it must refuse BEFORE reading the corpus"


def test_an_empty_answer_is_a_failed_proof_and_not_a_quiet_pass(tmp_path):
    """The actual 2026-10-21 defect, in one assertion: silence read as a refusal.
    A write that succeeds prints nothing on this transport."""
    rc, out = run_guard(tmp_path, STUB_RO="")
    assert rc == 2, out
    assert "did not read back read-only" in out and "<empty>" in out, out


def test_a_harness_that_cannot_report_an_error_is_refused(tmp_path):
    """If the query helper swallows failures then the read-back above passes on
    nothing, so the instrument is checked before the measurement."""
    rc, out = run_guard(tmp_path, STUB_DISC="")
    assert rc == 2, out
    assert "cannot discriminate" in out, out
    assert "read-only proof ok" not in out, out


def test_the_guard_issues_no_writes_of_its_own():
    up = TEXT.upper()
    for kw in ("INSERT INTO", "UPDATE ", "DELETE FROM", "DROP ", "TRUNCATE ", "ALTER TABLE"):
        assert kw not in up, "the guard contains a write keyword: %s" % kw


def test_the_pinned_report_runs_only_on_accrual():
    """A clean day must cost two COUNTs, not a 3-minute unscoped corpus scan. The report
    call has to sit inside the accrual branch."""
    branch = TEXT.split('if [ "$ez" -gt 0 ]', 1)[1].split("printf '%s\\n' \"$new_wm\"", 1)[0]
    assert "$SQL_DIR/$report" in branch, "the pinned report is not inside the accrual branch"


def test_exit_codes_are_distinct_and_documented():
    assert "0 = read, no accrual" in TEXT
    assert "1 = read, accrual found" in TEXT
    assert "2 = could not look" in TEXT


def test_cron_logrotate_and_health_all_name_the_same_log():
    """The silent-break shape: each file correct alone, the chain doing nothing."""
    assert LOG_PATH in CRON.read_text(encoding="utf-8")
    assert LOG_PATH in ROTATE.read_text(encoding="utf-8")
    assert LOG_PATH in HEALTH.read_text(encoding="utf-8")


def test_cron_runs_the_extensionless_installed_name():
    """A cron entry pointing at the .sh name is 203/EXEC, which is exactly how
    ktp-weekly-outliers sat dead for a week."""
    cron = CRON.read_text(encoding="utf-8")
    assert "/usr/local/bin/ktp-corpus-integrity-guard " in cron \
        or "/usr/local/bin/ktp-corpus-integrity-guard\n" in cron
    assert "/usr/local/bin/ktp-corpus-integrity-guard.sh" not in cron


def test_cron_is_daily_and_clear_of_the_freshness_window():
    cron = CRON.read_text(encoding="utf-8")
    m = re.search(r"^(\d+)\s+(\d+)\s+\*\s+\*\s+\*\s+root\s", cron, re.M)
    assert m, "no daily root entry found"
    minute, hour = int(m.group(1)), int(m.group(2))
    assert hour == 6 and minute >= 30, "expected 06:30 or later, got %02d:%02d" % (hour, minute)
