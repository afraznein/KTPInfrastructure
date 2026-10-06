"""persist_report's generated_at lands in the session zone, on a real MySQL.

The pending gate compares ktp_match_reports.generated_at with end_time, which
the daemon writes as NOW(). Production's session zone is the box's (EDT/EST),
so the test pins one with an offset rather than relying on the container's UTC.
"""
from __future__ import annotations

from pathlib import Path

from scripts import report_service
from tests.e2e_stats.ephemeral_mysql import EphemeralMysql

ZONE = "SET time_zone = '-04:00'; "
ROUNDS_UP = "2026-10-06T02:39:05.607600+00:00"
LOCAL_WALL_CLOCK = "2026-10-05 22:39:05"

TABLE = """
CREATE TABLE ktp_match_reports (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  match_id VARCHAR(64) COLLATE utf8mb4_bin NOT NULL,
  schema_version INT UNSIGNED NOT NULL,
  revision INT UNSIGNED NOT NULL DEFAULT 1,
  generated_at DATETIME NOT NULL,
  quality_status VARCHAR(16) COLLATE utf8mb4_bin NOT NULL,
  publishable TINYINT UNSIGNED NOT NULL DEFAULT 0,
  report_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  report MEDIUMTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE KEY uq_match_schema_revision (match_id, schema_version, revision)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin
"""


class _Zoned:
    """LocalMysql's interface, every statement run in the pinned zone."""

    def __init__(self, db: EphemeralMysql) -> None:
        self.db = db

    def sql(self, query: str) -> str:
        return self.db.sql(ZONE + query)


def test_a_rounding_up_fraction_is_stored_as_session_local_time(tmp_path: Path):
    with EphemeralMysql.start(parent=tmp_path) as db:
        db.sql(TABLE)
        report_service.persist_report(_Zoned(db), {
            "match_id": "1.3-1-X", "schema_version": 28,
            "generated_at": ROUNDS_UP, "quality": {"status": "PASS"}})
        stored = db.scalar("SELECT generated_at FROM ktp_match_reports WHERE match_id = '1.3-1-X'")
        # Control: this server really has the defect, so the assertion below
        # is not passing merely because the literal would have worked here too.
        db.sql(ZONE + "INSERT INTO ktp_match_reports (match_id, schema_version, "
               "generated_at, quality_status, report_sha256, report) "
               f"VALUES ('raw', 28, '{ROUNDS_UP}', 'PASS', '', '{{}}')")
        raw = db.scalar("SELECT generated_at FROM ktp_match_reports WHERE match_id = 'raw'")

    assert stored == LOCAL_WALL_CLOCK
    assert raw == "2026-10-06 02:39:06"
