from __future__ import annotations

import pytest

from tests.e2e_stats.assertions import check_capture_health
from tests.e2e_stats.ephemeral_mysql import EphemeralMysql


MATCH_ID = "capture-health-regression-TEST"
EVENT_TYPES = (
    "life", "damage", "position", "frag", "assist", "break",
    "flag_state", "flag_position",
)


@pytest.fixture(scope="module")
def capture_db(tmp_path_factory):
    parent = tmp_path_factory.mktemp("capture-health-db")
    with EphemeralMysql.start(parent=parent) as db:
        db.sql("""
CREATE TABLE ktp_capture_manifests (
  match_id VARCHAR(64) NOT NULL,
  half INT NOT NULL,
  producer VARCHAR(32) NOT NULL,
  schema_version INT NOT NULL
);
CREATE TABLE ktp_capture_health (
  match_id VARCHAR(64) NOT NULL,
  half INT NOT NULL,
  event_type VARCHAR(32) NULL,
  dropped BIGINT NULL,
  emitted BIGINT NULL,
  daemon_received BIGINT NULL,
  daemon_accepted BIGINT NULL,
  daemon_rejected BIGINT NULL,
  correlation_failure_count BIGINT NULL,
  sequence_gap_count BIGINT NULL,
  duplicate_or_reordered_count BIGINT NULL
);
""")
        yield db


def _seed_health(capture_db, *, frag: dict[str, int] | None = None,
                 event_overrides: dict[str, dict[str, int]] | None = None) -> None:
    capture_db.sql("DELETE FROM ktp_capture_health; DELETE FROM ktp_capture_manifests")
    capture_db.sql(f"""
INSERT INTO ktp_capture_manifests
  (match_id, half, producer, schema_version)
VALUES ('{MATCH_ID}', 1, 'stats_logging', 21)
""")

    overrides = dict(event_overrides or {})
    if frag is not None:
        overrides["frag"] = frag
    values = []
    for event_type in EVENT_TYPES:
        counters = {
            "emitted": 5 if event_type == "frag" else 3,
            "received": 5 if event_type == "frag" else 3,
            "accepted": 5 if event_type == "frag" else 3,
            "rejected": 0,
            "correlation": 0,
        }
        counters.update(overrides.get(event_type, {}))
        values.append(
            f"('{MATCH_ID}', 1, '{event_type}', 0, "
            f"{counters['emitted']}, {counters['received']}, "
            f"{counters['accepted']}, {counters['rejected']}, "
            f"{counters['correlation']}, 0, 0)"
        )
    capture_db.sql("""
INSERT INTO ktp_capture_health
  (match_id, half, event_type, dropped, emitted, daemon_received,
   daemon_accepted, daemon_rejected, correlation_failure_count,
   sequence_gap_count, duplicate_or_reordered_count)
VALUES
""" + ",\n".join(values))


def test_capture_health_accepts_exact_zero_failure_receipts(capture_db):
    _seed_health(capture_db)

    result = check_capture_health(capture_db, match_id=MATCH_ID, half=1)

    assert result["status"] == "ok"
    assert result["unhealthy_rows"] == 0


def test_capture_health_accepts_expected_synthetic_frag_failures(capture_db):
    _seed_health(capture_db, frag={
        "emitted": 5, "received": 5, "accepted": 3,
        "rejected": 2, "correlation": 2,
    })

    result = check_capture_health(
        capture_db, match_id=MATCH_ID, half=1,
        expected_frag_correlation_failures=2,
    )

    assert result["status"] == "ok"
    assert result["unhealthy_rows"] == 0


@pytest.mark.parametrize(("frag", "event_overrides", "expected_failures"), (
    ({"accepted": 4, "rejected": 2, "correlation": 2}, None, 2),
    ({"accepted": 3, "rejected": 1, "correlation": 2}, None, 2),
    ({"accepted": 3, "rejected": 2, "correlation": 1}, None, 2),
    ({"emitted": 1, "received": 1, "accepted": 0,
      "rejected": 2, "correlation": 2}, None, 2),
    ({"accepted": 3, "rejected": 2, "correlation": 2},
     {"life": {"accepted": 2, "rejected": 1}}, 2),
))
def test_capture_health_rejects_counter_mismatches(
        capture_db, frag, event_overrides, expected_failures):
    _seed_health(capture_db, frag=frag, event_overrides=event_overrides)

    result = check_capture_health(
        capture_db, match_id=MATCH_ID, half=1,
        expected_frag_correlation_failures=expected_failures,
    )

    assert result["status"] == "pipeline"
    assert result["unhealthy_rows"] == 1


def test_capture_health_rejects_negative_expected_failure_count(capture_db):
    _seed_health(capture_db)

    result = check_capture_health(
        capture_db, match_id=MATCH_ID, half=1,
        expected_frag_correlation_failures=-1,
    )

    assert result["status"] == "pipeline"
    assert result["unhealthy_rows"] == 1
    assert "cannot be negative" in result["detail"]
