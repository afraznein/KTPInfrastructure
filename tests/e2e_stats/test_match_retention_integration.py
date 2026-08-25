from __future__ import annotations

import importlib.util
import subprocess
import time
from pathlib import Path

from tests.e2e_stats.ephemeral_mysql import EphemeralMysql


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "ktp-match-retention.py"
SPEC = importlib.util.spec_from_file_location("ktp_match_retention_e2e", SCRIPT)
assert SPEC and SPEC.loader
retention = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(retention)

PURGED_MATCHES = {"scrim-old", "twelve-old", "official-test-TEST"}
RETAINED_MATCHES = {
    "official-old",
    "draft-old",
    "ktp-ot-old",
    "draft-ot-old",
    "unknown-old",
    "mixed-old",
    "recent-scrim",
}


def _prepare_retention_fixture(db: EphemeralMysql) -> None:
    statements = [
        """
CREATE TABLE ktp_matches (
    id INT AUTO_INCREMENT PRIMARY KEY,
    match_id VARCHAR(64) NOT NULL,
    match_type TINYINT UNSIGNED NULL,
    start_time DATETIME NOT NULL,
    end_time DATETIME NULL,
    UNIQUE KEY uk_match_half (match_id, id),
    KEY idx_retention (match_type, start_time),
    KEY idx_match_id (match_id)
)
""".strip()
    ]
    for table in retention.MATCH_TABLES:
        producer_column = (
            ", producer_match_id VARCHAR(64) NULL, "
            "KEY idx_producer_context (producer_match_id)"
            if table in retention.PRODUCER_CONTEXT_TABLES
            else ""
        )
        statements.append(
            f"""
CREATE TABLE `{table}` (
    id INT AUTO_INCREMENT PRIMARY KEY,
    match_id VARCHAR(64) NULL,
    marker VARCHAR(96) NOT NULL,
    KEY idx_match_id (match_id)
    {producer_column}
)
""".strip()
        )
    db.sql(";\n".join(statements) + ";")

    db.sql("""
INSERT INTO ktp_matches (match_id, match_type, start_time, end_time) VALUES
    ('official-old',       0, NOW() - INTERVAL 31 DAY, NOW() - INTERVAL 30 DAY),
    ('scrim-old',          1, NOW() - INTERVAL 31 DAY, NOW() - INTERVAL 30 DAY),
    ('twelve-old',         2, NOW() - INTERVAL 31 DAY, NOW() - INTERVAL 30 DAY),
    ('draft-old',          3, NOW() - INTERVAL 31 DAY, NOW() - INTERVAL 30 DAY),
    ('ktp-ot-old',         4, NOW() - INTERVAL 31 DAY, NOW() - INTERVAL 30 DAY),
    ('draft-ot-old',       5, NOW() - INTERVAL 31 DAY, NOW() - INTERVAL 30 DAY),
    ('unknown-old',     NULL, NOW() - INTERVAL 31 DAY, NOW() - INTERVAL 30 DAY),
    ('mixed-old',          1, NOW() - INTERVAL 31 DAY, NOW() - INTERVAL 30 DAY),
    ('mixed-old',          0, NOW() - INTERVAL 31 DAY, NOW() - INTERVAL 30 DAY),
    ('recent-scrim',       1, NOW() - INTERVAL 10 DAY, NOW() - INTERVAL 9 DAY),
    ('official-test-TEST', 0, NOW() - INTERVAL 31 DAY, NOW() - INTERVAL 30 DAY);
""")

    all_matches = sorted(PURGED_MATCHES | RETAINED_MATCHES)
    for table in retention.MATCH_TABLES:
        legacy_values = ",\n".join(
            f"('{match_id}', 'baseline:{match_id}')" for match_id in all_matches
        )
        if table not in retention.PRODUCER_CONTEXT_TABLES:
            db.sql(
                f"INSERT INTO `{table}` (match_id, marker) VALUES\n"
                f"{legacy_values};"
            )
            continue

        producer_values = """
('official-old', 'producer-scrim-receipt-official', 'scrim-old'),
('scrim-old', 'producer-official-receipt-scrim', 'official-old'),
(NULL, 'producer-test-receipt-null', 'official-test-TEST'),
('official-test-TEST', 'producer-draft-receipt-test', 'draft-old'),
(NULL, 'producer-twelve-receipt-null', 'twelve-old')
""".strip()
        db.sql(
            f"INSERT INTO `{table}` (match_id, marker) VALUES\n"
            f"{legacy_values};\n"
            f"INSERT INTO `{table}` "
            "(match_id, marker, producer_match_id) VALUES\n"
            f"{producer_values};"
        )


def _counts(db: EphemeralMysql) -> dict[str, int]:
    return {
        "ktp_matches": db.count("SELECT COUNT(*) FROM ktp_matches"),
        **{
            table: db.count(f"SELECT COUNT(*) FROM `{table}`")
            for table in retention.MATCH_TABLES
        },
    }


def _result_value(output: str, header: str) -> str:
    lines = output.strip().splitlines()
    for index, line in enumerate(lines[:-1]):
        if line == header:
            return lines[index + 1].split("\t", 1)[0]
    raise AssertionError(f"result header {header!r} missing from:\n{output}")


def _audit_count(output: str, label: str) -> int:
    for line in output.splitlines():
        fields = line.split("\t")
        if len(fields) == 2 and fields[0] == label:
            return int(fields[1])
    raise AssertionError(f"audit row {label!r} missing from:\n{output}")


def _assert_no_canonical_orphans(db: EphemeralMysql, table: str) -> None:
    match_expression = (
        "COALESCE(t.producer_match_id, t.match_id)"
        if table in retention.PRODUCER_CONTEXT_TABLES
        else "t.match_id"
    )
    assert db.count(f"""
SELECT COUNT(*)
FROM `{table}` t
LEFT JOIN (SELECT DISTINCT match_id FROM ktp_matches) m
  ON m.match_id = {match_expression}
WHERE {match_expression} IS NOT NULL
  AND m.match_id IS NULL
""") == 0


def _canonical_match_ids(db: EphemeralMysql, table: str) -> set[str]:
    match_expression = (
        "COALESCE(producer_match_id, match_id)"
        if table in retention.PRODUCER_CONTEXT_TABLES
        else "match_id"
    )
    rows = db.sql(
        f"SELECT DISTINCT {match_expression} AS canonical_match_id "
        f"FROM `{table}` WHERE {match_expression} IS NOT NULL "
        "ORDER BY canonical_match_id"
    ).strip().splitlines()
    return set(rows[1:])


def _start_lock_holder(db: EphemeralMysql) -> subprocess.Popen:
    holder = subprocess.Popen(
        [
            db.client,
            "--no-defaults",
            f"--socket={db.socket_path}",
            "-u",
            "root",
            "--batch",
            "--raw",
            db.database,
            "-e",
            "SELECT GET_LOCK('ktp_match_retention', 0); SELECT SLEEP(60);",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if holder.poll() is not None:
            raise AssertionError("retention lock-holder client exited early")
        owner = db.scalar("SELECT IS_USED_LOCK('ktp_match_retention')")
        if owner not in (None, "NULL"):
            return holder
        time.sleep(0.1)
    holder.terminate()
    holder.wait(timeout=5)
    raise AssertionError("retention lock was not acquired within 10 seconds")


def test_retention_classification_precedence_and_idempotency_against_mysql(tmp_path):
    with EphemeralMysql.start(parent=tmp_path) as db:
        _prepare_retention_fixture(db)
        before = _counts(db)

        dry_run = db.sql(retention.build_sql(14, apply=False))
        assert _result_value(dry_run, "candidate_matches") == "3"
        assert PURGED_MATCHES.issubset(set(dry_run.split()))
        assert RETAINED_MATCHES.isdisjoint(set(dry_run.split()))
        assert _counts(db) == before

        applied = db.sql(retention.build_sql(14, apply=True))
        assert _result_value(applied, "candidate_matches") == "3"
        for table in retention.MATCH_TABLES:
            if table in retention.PRODUCER_CONTEXT_TABLES:
                assert _audit_count(applied, f"{table}:producer_match_id") == 3
                assert _audit_count(applied, f"{table}:legacy_match_id") == 3
            else:
                assert _audit_count(applied, table) == 3
        assert _audit_count(applied, "ktp_matches") == 3

        remaining_match_ids = {
            line for line in db.sql(
                "SELECT DISTINCT match_id FROM ktp_matches ORDER BY match_id"
            ).strip().splitlines()[1:]
        }
        assert remaining_match_ids == RETAINED_MATCHES
        assert db.count("SELECT COUNT(*) FROM ktp_matches") == 8

        for table in retention.MATCH_TABLES:
            expected = 9 if table in retention.PRODUCER_CONTEXT_TABLES else 7
            assert db.count(f"SELECT COUNT(*) FROM `{table}`") == expected
            assert _canonical_match_ids(db, table) == RETAINED_MATCHES
            _assert_no_canonical_orphans(db, table)

        for table in retention.PRODUCER_CONTEXT_TABLES:
            markers = set(
                db.sql(f"SELECT marker FROM `{table}` ORDER BY marker")
                .strip().splitlines()[1:]
            )
            assert "producer-official-receipt-scrim" in markers
            assert "producer-draft-receipt-test" in markers
            assert "producer-scrim-receipt-official" not in markers
            assert "producer-test-receipt-null" not in markers
            assert "producer-twelve-receipt-null" not in markers

        after_first_apply = _counts(db)
        second_apply = db.sql(retention.build_sql(14, apply=True))
        assert _result_value(second_apply, "candidate_matches") == "0"
        assert _counts(db) == after_first_apply
        assert _audit_count(second_apply, "ktp_matches") == 0
        for table in retention.MATCH_TABLES:
            labels = (
                (f"{table}:producer_match_id", f"{table}:legacy_match_id")
                if table in retention.PRODUCER_CONTEXT_TABLES
                else (table,)
            )
            assert all(_audit_count(second_apply, label) == 0 for label in labels)


def test_retention_lock_contention_is_a_database_backed_noop(tmp_path):
    with EphemeralMysql.start(parent=tmp_path) as db:
        _prepare_retention_fixture(db)
        before = _counts(db)
        holder = _start_lock_holder(db)
        try:
            blocked = db.sql(retention.build_sql(14, apply=True))
        finally:
            holder.terminate()
            holder.wait(timeout=5)

        assert _result_value(blocked, "candidate_matches") == "0"
        assert _counts(db) == before
        assert _audit_count(blocked, "ktp_matches") == 0
        for table in retention.MATCH_TABLES:
            labels = (
                (f"{table}:producer_match_id", f"{table}:legacy_match_id")
                if table in retention.PRODUCER_CONTEXT_TABLES
                else (table,)
            )
            assert all(_audit_count(blocked, label) == 0 for label in labels)
