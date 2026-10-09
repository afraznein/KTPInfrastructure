"""ktp-ac-retention.sh sweep 4: ktp_net_sessions identity blanking.

Ruled 2026-10-08: the per-connection netcode metrics in `ktp_net_sessions` are
kept indefinitely and only `name` + `steam_id` age out, at 90 days. That makes
the sweep an UPDATE, which is a different shape from the three DELETE sweeps
beside it, and two of its properties are invisible to a reading of the SQL:

  - `ROW_COUNT()` on an UPDATE counts rows **changed**, not matched. The
    `steam_id <> ''` guard is therefore what makes the batched loop complete:
    without it the second batch can re-select rows it already blanked, report
    0 changed, and stop with identities still on every remaining row.
  - a horizon of 0 would resolve `INTERVAL 0 DAY` to `NOW()` and blank the
    whole table, so 0 has to mean "keep forever" at the sweep, not only in the
    default -- the same trap `UPLOAD_RETENTION_DAYS` carries.

The shipped script is run whole, under bash, with a fake `mysql` first on PATH.
Nothing is extracted or re-implemented: the SQL under test is the SQL the data
server will run. The fake backs those statements with stdlib sqlite3 and
translates exactly two MySQL constructs (`NOW() - INTERVAL n DAY`, and
`UPDATE/DELETE ... LIMIT n`), emulating MySQL's changed-rows `ROW_COUNT()`. It
refuses any statement shape it does not recognise rather than returning a
plausible zero -- see `test_the_fake_refuses_an_unrecognised_statement`.

⛔ What this does NOT prove: that MySQL parses the statement, or anything about
the live table. No database is reachable from here. The mutation tests at the
bottom are what show these assertions can fail at all.
"""
import os
import pathlib
import shutil
import sqlite3
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "ktp-ac-retention.sh"
# Resolved through PATH rather than handed to CreateProcess as a bare name: on
# Windows that search reaches System32 -- and therefore WSL's bash, which cannot
# open a C:/ path -- before it reaches PATH.
BASH = os.environ.get("KTP_TEST_BASH") or shutil.which("bash") or "bash"

pytestmark = pytest.mark.skipif(shutil.which(BASH) is None, reason="needs bash")

# Deliberately narrow: a fake that accepts anything would pass against a sweep
# rewritten into a statement it never ran.
FAKE_MYSQL = r'''
import os, re, sqlite3, sys

db = os.environ["STUB_DB"]
args = [a for a in sys.argv[1:] if a not in ("-N", "hlstatsx")]
if args and args[0] == "-e":
    args = args[1:]
sql = args[0] if args else ""
with open(os.environ["STUB_SQL_LOG"], "a", encoding="utf-8") as fh:
    fh.write(sql.strip() + "\n@@\n")

conn = sqlite3.connect(db)
conn.isolation_level = None
row_count = 0

def translate(stmt):
    stmt = re.sub(r"NOW\(\)\s*-\s*INTERVAL\s+(\d+)\s+DAY",
                  lambda m: "datetime('now', '-%s days')" % m.group(1), stmt)
    return re.sub(r"\bNOW\(\)", "datetime('now')", stmt)

def limited(stmt):
    """MySQL's single-table `UPDATE/DELETE ... LIMIT n` as a rowid subquery."""
    m = re.match(r"^(DELETE FROM|UPDATE)\s+(\w+)\s+(.*?)\s*WHERE\s+(.*?)\s+LIMIT\s+(\d+)$",
                 stmt, re.S | re.I)
    if not m:
        return None
    verb, table, mid, where, limit = m.groups()
    pick = "SELECT rowid FROM %s WHERE %s LIMIT %s" % (table, where, limit)
    if verb.upper() == "UPDATE":
        sets = dict(re.findall(r"(\w+)\s*=\s*('(?:[^']|'')*'|NULL)", mid))
        if not sets or not mid.upper().startswith("SET"):
            return None
        # ROW_COUNT() on an UPDATE is rows CHANGED, so count only the rows whose
        # current values differ from what is being assigned.
        cols = list(sets)
        cur = conn.execute("SELECT rowid, %s FROM %s WHERE %s LIMIT %s"
                           % (", ".join(cols), table, where, limit))
        want = [None if sets[c] == "NULL" else sets[c].strip("'").replace("''", "'")
                for c in cols]
        rowids = [r[0] for r in cur.fetchall() if list(r[1:]) != want]
        conn.execute("UPDATE %s %s WHERE rowid IN (%s)"
                     % (table, mid, ",".join("?" * len(rowids))), rowids)
        return len(rowids)
    rowids = [r[0] for r in conn.execute(pick).fetchall()]
    conn.execute("DELETE FROM %s WHERE rowid IN (%s)"
                 % (table, ",".join("?" * len(rowids))), rowids)
    return len(rowids)

for raw in sql.split(";"):
    stmt = translate(" ".join(raw.split()))
    if not stmt:
        continue
    if re.match(r"^SELECT\s+ROW_COUNT\(\)$", stmt, re.I):
        print(row_count)
        continue
    if re.match(r"^SELECT\b", stmt, re.I):
        for row in conn.execute(stmt).fetchall():
            print("\t".join("" if v is None else str(v) for v in row))
        continue
    n = limited(stmt)
    if n is None:
        sys.stderr.write("fake mysql: unrecognised statement: %s\n" % stmt)
        sys.exit(2)
    row_count = n
conn.commit()
'''

NET_COLS = "ts, name, steam_id, dur_s, latency_avg_ms"
# Both sides of the 90-day boundary, on purpose: a fixture entirely past the
# horizon passes against a sweep that blanks everything, and a fixture entirely
# inside it passes against a sweep that blanks nothing.
SEED = [
    ("-200 days", "OldTimer", "STEAM_0:0:111", 900, 31.5),
    ("-120 days", "kroD-", "STEAM_0:1:222", 1800, 44.0),
    ("-91 days", "JustPast", "STEAM_0:0:333", 60, 12.0),
    ("-89 days", "JustInside", "STEAM_0:1:444", 61, 13.0),
    ("-1 days", "Yesterday", "STEAM_0:0:555", 120, 22.5),
]


# Read from information_schema on the data server, 2026-10-09.
INTERVAL_NAME_COLUMNS = (
    "lagcomp_first_name", "latency_worst_name", "jitter_worst_name",
    "maxunlag_excess_worst_name", "shadow_worst_name", "drops_worst_name",
    "latzero_worst_name", "updates_worst_name", "loss_worst_name",
    "subinterval_worst_name", "synth_worst_name", "interp_diff_worst_name",
)


def _seed(db, rows=SEED, intervals=()):
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE ktp_net_intervals (ts TEXT, latency_worst_ms REAL,"
                 " latency_worst_slot INT, %s)"
                 % ", ".join("%s TEXT" % c for c in INTERVAL_NAME_COLUMNS))
    for offset, latency, slot, names in intervals:
        cols = ["ts", "latency_worst_ms", "latency_worst_slot", *names]
        conn.execute("INSERT INTO ktp_net_intervals (%s) VALUES (datetime('now', ?), %s)"
                     % (", ".join(cols), ", ".join("?" * (len(cols) - 1))),
                     (offset, latency, slot, *names.values()))
    conn.execute("CREATE TABLE ktp_net_sessions (ts TEXT, name TEXT, steam_id TEXT,"
                 " dur_s INT, latency_avg_ms REAL)")
    for t in ("ktp_ac_weapon_hits", "ktp_ac_weapon_switches"):
        conn.execute("CREATE TABLE %s (ingested_at TEXT)" % t)
    conn.execute("CREATE TABLE ktp_ac_session_tokens (expires_at TEXT)")
    conn.execute("CREATE TABLE ktp_ac_sessions (zip_path TEXT)")
    for offset, name, steam, dur, lat in rows:
        conn.execute("INSERT INTO ktp_net_sessions (%s) VALUES"
                     " (datetime('now', ?), ?, ?, ?, ?)" % NET_COLS,
                     (offset, name, steam, dur, lat))
    conn.commit()
    conn.close()


class Run:
    def __init__(self, proc, db, sql_log):
        self.rc, self.out, self.err = proc.returncode, proc.stdout, proc.stderr
        self.db, self.sql = db, sql_log.read_text(encoding="utf-8")

    def sessions(self):
        conn = sqlite3.connect(self.db)
        rows = conn.execute("SELECT name, steam_id, dur_s, latency_avg_ms,"
                            " ts FROM ktp_net_sessions ORDER BY ts").fetchall()
        conn.close()
        return rows

    def identified(self):
        """Rows that still carry an identity, oldest first."""
        return [r[0] for r in self.sessions() if r[1] != ""]

    def blanked(self):
        return [r for r in self.sessions() if r[1] == ""]


def run_script(tmp_path, env=None, script_text=None, rows=SEED, runs=1, intervals=()):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    (bin_dir / "fake_mysql.py").write_text(FAKE_MYSQL, encoding="utf-8")
    (bin_dir / "mysql").write_text(
        '#!/bin/sh\nexec "%s" "%s" "$@"\n'
        % (sys.executable.replace("\\", "/"), (bin_dir / "fake_mysql.py").as_posix()),
        encoding="utf-8", newline="\n")
    (bin_dir / "mysql").chmod(0o755)

    script = tmp_path / "ktp-ac-retention.sh"
    script.write_text(script_text if script_text is not None
                      else SCRIPT.read_text(encoding="utf-8"),
                      encoding="utf-8", newline="\n")

    db = tmp_path / "hlstatsx.sqlite"
    if db.exists():
        db.unlink()
    _seed(str(db), rows, intervals)
    sql_log = tmp_path / "statements.sql"
    sql_log.write_text("", encoding="utf-8")

    full = dict(os.environ)
    full["PATH"] = str(bin_dir) + os.pathsep + full.get("PATH", "")
    full["STUB_DB"] = str(db)
    full["STUB_SQL_LOG"] = str(sql_log)
    # A path that cannot exist, so sweep 1 takes its documented skip branch.
    full["UPLOADS_DIR"] = str(tmp_path / "no-such-uploads")
    full.update(env or {})

    for _ in range(runs):
        # as_posix(): a Windows path reaches this bash with its backslashes eaten.
        proc = subprocess.run([BASH, script.as_posix()], env=full,
                              capture_output=True, text=True)
    return Run(proc, str(db), sql_log)


# ── the fixture itself has to straddle the boundary ────────────────────

def test_the_fixture_straddles_the_horizon(tmp_path):
    """Non-vacuity. Both legs below assert something only because this holds."""
    r = run_script(tmp_path, env={"NET_IDENTITY_RETENTION_DAYS": "90", "DRY_RUN": "1"})
    assert r.rc == 0, r.err
    conn = sqlite3.connect(r.db)
    past = conn.execute("SELECT COUNT(*) FROM ktp_net_sessions"
                        " WHERE ts < datetime('now', '-90 days')").fetchone()[0]
    inside = conn.execute("SELECT COUNT(*) FROM ktp_net_sessions"
                          " WHERE ts >= datetime('now', '-90 days')").fetchone()[0]
    conn.close()
    assert past == 3 and inside == 2, (past, inside)


def test_the_fake_refuses_an_unrecognised_statement(tmp_path):
    """A fake that silently accepts a rewritten sweep would pass for free."""
    mangled = SCRIPT.read_text(encoding="utf-8").replace(
        "UPDATE ktp_net_sessions SET name = '', steam_id = ''",
        "TRUNCATE ktp_net_sessions")
    r = run_script(tmp_path, script_text=mangled)
    assert r.rc != 0
    assert "unrecognised statement" in r.err


# ── the ruling ─────────────────────────────────────────────────────────

def test_rows_past_the_horizon_are_blanked_and_recent_rows_are_not(tmp_path):
    r = run_script(tmp_path)
    assert r.rc == 0, r.err
    assert r.identified() == ["JustInside", "Yesterday"]
    assert len(r.blanked()) == 3
    assert all(row[0] == "" and row[1] == "" for row in r.blanked())


def test_the_metrics_survive_the_blanking(tmp_path):
    """The whole reason this is an UPDATE: the measurement outlives the name."""
    r = run_script(tmp_path)
    metrics = sorted((row[2], row[3]) for row in r.sessions())
    assert metrics == sorted((dur, lat) for _, _, _, dur, lat in SEED)


def test_the_run_says_how_many_it_blanked(tmp_path):
    """A silent retention job is indistinguishable from one that never ran."""
    r = run_script(tmp_path)
    assert "ac-retention: net_sessions identity blanked 3 row(s)" in r.out


def test_a_second_run_blanks_nothing(tmp_path):
    r = run_script(tmp_path, runs=2)
    assert "ac-retention: net_sessions identity blanked 0 row(s)" in r.out
    assert r.identified() == ["JustInside", "Yesterday"]


def test_the_sweep_finishes_past_the_first_batch(tmp_path):
    """BATCH_SIZE smaller than the work: all three go, not just the first two."""
    r = run_script(tmp_path, env={"BATCH_SIZE": "2"})
    assert "ac-retention: net_sessions identity blanked 3 row(s)" in r.out
    assert r.identified() == ["JustInside", "Yesterday"]
    assert r.sql.count("UPDATE ktp_net_sessions") >= 2


def test_the_horizon_is_the_knob(tmp_path):
    r = run_script(tmp_path, env={"NET_IDENTITY_RETENTION_DAYS": "30"})
    assert r.identified() == ["Yesterday"]


def test_zero_days_keeps_every_identity(tmp_path):
    """INTERVAL 0 DAY is NOW(): unguarded, 0 would blank the whole table."""
    r = run_script(tmp_path, env={"NET_IDENTITY_RETENTION_DAYS": "0"})
    assert r.rc == 0, r.err
    assert r.identified() == ["OldTimer", "kroD-", "JustPast", "JustInside", "Yesterday"]
    assert "blanking is off" in r.out
    assert "UPDATE ktp_net_sessions" not in r.sql


# ── DRY_RUN has to cover the new sweep too ─────────────────────────────

def test_dry_run_counts_and_writes_nothing(tmp_path):
    r = run_script(tmp_path, env={"DRY_RUN": "1"})
    assert r.rc == 0, r.err
    assert "DRY_RUN: net_sessions identities past 90d: 3" in r.out
    assert "UPDATE ktp_net_sessions" not in r.sql
    assert r.identified() == ["OldTimer", "kroD-", "JustPast", "JustInside", "Yesterday"]


def test_dry_run_follows_the_horizon(tmp_path):
    r = run_script(tmp_path, env={"DRY_RUN": "1", "NET_IDENTITY_RETENTION_DAYS": "30"})
    assert "DRY_RUN: net_sessions identities past 30d: 4" in r.out


def test_dry_run_says_so_when_blanking_is_off(tmp_path):
    r = run_script(tmp_path, env={"DRY_RUN": "1", "NET_IDENTITY_RETENTION_DAYS": "0"})
    assert "blanking is off" in r.out
    assert "FROM ktp_net_sessions" not in r.sql


# ── mutation tests: each breaks the shipped sweep and names what reddens ──

def _mutate(old, new):
    text = SCRIPT.read_text(encoding="utf-8")
    assert text.count(old) == 1, "mutation anchor is not unique: %r" % old
    return text.replace(old, new)


def test_mutation_inverted_comparison_reddens(tmp_path):
    """Breaks `ts <` -> `ts >`: exercises the horizon-direction assertion."""
    r = run_script(tmp_path, script_text=_mutate(
        'net_identity_where="ts < NOW()', 'net_identity_where="ts > NOW()'))
    assert r.identified() != ["JustInside", "Yesterday"]
    assert r.identified() == ["OldTimer", "kroD-", "JustPast"]


def test_mutation_no_horizon_reddens(tmp_path):
    """Drops the horizon entirely: exercises the recent-rows-untouched leg."""
    r = run_script(tmp_path, script_text=_mutate(
        'net_identity_where="ts < NOW() - INTERVAL ${NET_IDENTITY_RETENTION_DAYS} DAY '
        'AND steam_id <> \'\'"',
        'net_identity_where="steam_id <> \'\'"'))
    assert r.identified() == []


def test_mutation_dropped_guard_reddens_the_batching_leg(tmp_path):
    """Drops `AND steam_id <> ''`: the loop stops after one batch, under-blanking.

    Exercises test_the_sweep_finishes_past_the_first_batch. With BATCH_SIZE=2 and
    three rows past the horizon, the second batch re-selects two already-blanked
    rows, MySQL reports 0 changed, and the sweep stops one row short.
    """
    r = run_script(tmp_path, env={"BATCH_SIZE": "2"}, script_text=_mutate(
        " AND steam_id <> ''\"", "\""))
    assert "ac-retention: net_sessions identity blanked 2 row(s)" in r.out
    assert len(r.blanked()) == 2
    assert "JustPast" in r.identified()


def test_mutation_dropped_zero_guard_reddens(tmp_path):
    """Removes the `-gt 0` gate: 0 days then blanks the entire table."""
    r = run_script(tmp_path, env={"NET_IDENTITY_RETENTION_DAYS": "0"},
                   script_text=_mutate(
        'if [ "${NET_IDENTITY_RETENTION_DAYS}" -gt 0 ]; then\n    batched_write',
        'if true; then\n    batched_write'))
    assert r.identified() == []


def test_mutation_silent_sweep_reddens(tmp_path):
    """Removes the count from the log line: the observability leg must fail."""
    r = run_script(tmp_path, script_text=_mutate(
        '    echo "[$(ts)] ac-retention: ${label} ${verb} ${total} row(s)"',
        '    :'))
    assert "net_sessions identity blanked" not in r.out
    assert len(r.blanked()) == 3
