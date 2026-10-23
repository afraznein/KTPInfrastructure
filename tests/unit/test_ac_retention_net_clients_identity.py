"""ktp-ac-retention.sh sweep 6: ktp_net_clients / ktp_client_settings identity blanking.

KTPProfileAggregator sql/2026-10-19-001 adds two per-player tables -- the
per-client net slice closed at each match boundary, and the five net cvars the
client declared. Both carry `name` and `steam_id`, and both take the 90-day
identity horizon ruled for `ktp_net_sessions`: metrics forever, identity ages
out, blank-not-delete.

Two things this sweep has that sweep 4 does not, and that the tests pin:

- The tables are created by an operator-applied migration in another repo, so
  the cron runs before they exist. An absent table must be logged and skipped,
  and the run must still reach `ac-retention: done` with rc 0.
- The presence probe is `SELECT 1 FROM <t> LIMIT 1`, not information_schema,
  because the shared fake mysql answers SELECT against sqlite and nothing else.

Same harness as test_ac_retention_net_identity.py; `extra_seed` creates the two
tables, which the shared seed does not know about, so the default run_script
IS the absent-table case.
"""
import sqlite3

from tests.unit.test_ac_retention_net_identity import SCRIPT, pytestmark, run_script

__all__ = ["pytestmark"]

TABLES = ("ktp_net_clients", "ktp_client_settings")
# Both sides of the horizon in each table, so a sweep that blanks everything and one
# that blanks nothing both fail.
ROWS = [
    ("-200 days", "OldTimer", "STEAM_0:0:111"),
    ("-120 days", "kroD-", "STEAM_0:1:222"),
    ("-91 days", "JustPast", "STEAM_0:0:333"),
    ("-89 days", "JustInside", "STEAM_0:1:444"),
    ("-1 days", "Yesterday", "STEAM_0:0:555"),
]


def seed_both(db):
    conn = sqlite3.connect(db)
    for t in TABLES:
        conn.execute("CREATE TABLE %s (ts TEXT, name TEXT, steam_id TEXT, msec_p50 INT)" % t)
        for offset, name, steam in ROWS:
            conn.execute("INSERT INTO %s VALUES (datetime('now', ?), ?, ?, 4)" % t,
                         (offset, name, steam))
    conn.commit()
    conn.close()


def seed_one(db):
    """Only ktp_net_clients exists: the DDL half-applied, or a later table."""
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE ktp_net_clients (ts TEXT, name TEXT, steam_id TEXT, msec_p50 INT)")
    for offset, name, steam in ROWS:
        conn.execute("INSERT INTO ktp_net_clients VALUES (datetime('now', ?), ?, ?, 4)",
                     (offset, name, steam))
    conn.commit()
    conn.close()


def identified(db, table):
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT name, steam_id, msec_p50 FROM %s WHERE steam_id <> ''"
                        " ORDER BY ts" % table).fetchall()
    conn.close()
    return rows


def metrics(db, table):
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT msec_p50 FROM %s" % table).fetchall()
    conn.close()
    return rows


def run(tmp_path, **kw):
    return run_script(tmp_path, extra_seed=seed_both, **kw)


# -- absent tables: the state the cron is in until the operator applies the DDL --

def test_absent_tables_are_skipped_and_the_run_still_finishes(tmp_path):
    r = run_script(tmp_path)
    assert r.rc == 0, r.err
    for t in ("net_clients", "client_settings"):
        assert "ac-retention: %s identity blanking skipped (table absent)" % t in r.out
    assert "ac-retention: done" in r.out
    assert "UPDATE ktp_net_clients" not in r.sql
    assert "UPDATE ktp_client_settings" not in r.sql


def test_one_present_one_absent_are_handled_independently(tmp_path):
    r = run_script(tmp_path, extra_seed=seed_one)
    assert r.rc == 0, r.err
    assert "ac-retention: net_clients identity blanked 3 row(s)" in r.out
    assert "ac-retention: client_settings identity blanking skipped (table absent)" in r.out


def test_dry_run_reports_absence_too(tmp_path):
    r = run_script(tmp_path, env={"DRY_RUN": "1"})
    assert r.rc == 0, r.err
    assert "DRY_RUN: net_clients identity blanking skipped (table absent)" in r.out


# -- present tables: sweep 4's behaviour, twice --

def test_identities_past_the_horizon_are_blanked_and_recent_ones_kept(tmp_path):
    r = run(tmp_path)
    assert r.rc == 0, r.err
    for t in TABLES:
        assert [row[0] for row in identified(r.db, t)] == ["JustInside", "Yesterday"], t
        assert sorted(m[0] for m in metrics(r.db, t)) == [4] * 5, "a metric moved"


def test_each_table_counts_its_own_rows(tmp_path):
    r = run(tmp_path)
    assert "ac-retention: net_clients identity blanked 3 row(s)" in r.out
    assert "ac-retention: client_settings identity blanked 3 row(s)" in r.out


def test_a_second_run_blanks_nothing(tmp_path):
    r = run(tmp_path, runs=2)
    assert "ac-retention: net_clients identity blanked 0 row(s)" in r.out
    assert "ac-retention: client_settings identity blanked 0 row(s)" in r.out


def test_the_sweep_finishes_past_the_first_batch(tmp_path):
    r = run(tmp_path, env={"BATCH_SIZE": "2"})
    assert "ac-retention: net_clients identity blanked 3 row(s)" in r.out
    assert r.sql.count("UPDATE ktp_net_clients") >= 2
    assert len(identified(r.db, "ktp_net_clients")) == 2


def test_zero_days_keeps_every_identity(tmp_path):
    r = run(tmp_path, env={"NET_IDENTITY_RETENTION_DAYS": "0"})
    assert r.rc == 0, r.err
    for t in TABLES:
        assert len(identified(r.db, t)) == 5
        assert t not in r.sql


def test_dry_run_counts_and_writes_nothing(tmp_path):
    r = run(tmp_path, env={"DRY_RUN": "1"})
    assert r.rc == 0, r.err
    assert "DRY_RUN: net_clients identities past 90d: 3" in r.out
    assert "DRY_RUN: client_settings identities past 90d: 3" in r.out
    assert "UPDATE ktp_net_clients" not in r.sql
    for t in TABLES:
        assert len(identified(r.db, t)) == 5


# -- mutations: each breaks the shipped sweep and names what reddens --

def _mutate(old, new):
    text = SCRIPT.read_text(encoding="utf-8")
    assert text.count(old) == 1, "mutation anchor is not unique: %r" % old
    return text.replace(old, new)


def test_mutation_a_table_left_off_the_list_keeps_its_identities(tmp_path):
    r = run(tmp_path, script_text=_mutate(
        'NET_CLIENT_TABLES="ktp_net_clients ktp_client_settings"',
        'NET_CLIENT_TABLES="ktp_net_clients"'))
    assert len(identified(r.db, "ktp_client_settings")) == 5
    assert len(identified(r.db, "ktp_net_clients")) == 2


def test_mutation_dropped_presence_guard_fails_the_run_on_an_absent_table(tmp_path):
    """The guard is what keeps a pre-migration cron green; without it the sweep
    errors on the missing table and the run stops before 'done'."""
    r = run_script(tmp_path, script_text=_mutate(
        '        if table_present "$t"; then\n            batched_write',
        '        if true; then\n            batched_write'))
    assert r.rc != 0 or "ac-retention: done" not in r.out
