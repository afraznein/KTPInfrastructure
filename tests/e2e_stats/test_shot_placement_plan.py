"""shot_placement_fact must read a per-shot time window, not the whole half.

The join to ktp_position_samples used to be written with equalities on
(match_id, half). MySQL then plans a ref on that prefix and visits every sample
of the half for every shot, which on production cost about a minute a match.
With bounds instead of equalities, and KTPHLStatsX migration 043's
(match_id, half, game_time) index, it re-plans a range per shot.
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts import match_analytics as analytics
from tests.e2e_stats.ephemeral_mysql import EphemeralMysql

MATCH = "placement-plan-TEST"
SAMPLES_PER_HALF = 1500
SHOTS_PER_HALF = 300
HALF_SECONDS = 600
# Other matches' samples: on a table holding one match, MySQL scans it whole
# with a hash join, and neither form of the join shows its production plan.
FILLER_MATCHES = 39

SCHEMA = f"""
CREATE TABLE ktp_match_players (
  id INT AUTO_INCREMENT PRIMARY KEY, match_id VARCHAR(64) NOT NULL,
  player_id INT NOT NULL, team TINYINT NOT NULL,
  UNIQUE KEY uk_match_player (match_id, player_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE ktp_shot_events (
  id INT AUTO_INCREMENT PRIMARY KEY, match_id VARCHAR(64), half TINYINT,
  player_id INT, game_time FLOAT, pos_x INT, pos_y INT, pos_z INT,
  pitch FLOAT, yaw FLOAT, KEY idx_match (match_id), KEY idx_player (player_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
CREATE TABLE ktp_position_samples (
  id INT AUTO_INCREMENT PRIMARY KEY, match_id VARCHAR(64) DEFAULT NULL,
  half TINYINT NOT NULL DEFAULT 0, player_id INT NOT NULL, team TINYINT NOT NULL,
  pos_x MEDIUMINT NOT NULL, pos_y MEDIUMINT NOT NULL, pos_z MEDIUMINT NOT NULL,
  is_alive TINYINT UNSIGNED DEFAULT NULL,
  map_revision_sha256 CHAR(64) CHARACTER SET ascii COLLATE ascii_bin DEFAULT NULL,
  game_time FLOAT NOT NULL,
  KEY idx_match (match_id),
  KEY idx_position_map_revision (match_id, half, map_revision_sha256),
  KEY idx_pos_match_half_time (match_id, half, game_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
SET SESSION cte_max_recursion_depth = 100000;
INSERT INTO ktp_match_players (match_id, player_id, team)
WITH RECURSIVE n(i) AS (SELECT 0 UNION ALL SELECT i + 1 FROM n WHERE i < 11)
SELECT '{MATCH}', 100 + i, 1 + i % 2 FROM n;
INSERT INTO ktp_position_samples
  (match_id, half, player_id, team, pos_x, pos_y, pos_z, is_alive, map_revision_sha256, game_time)
WITH RECURSIVE n(i) AS (SELECT 0 UNION ALL SELECT i + 1 FROM n WHERE i < {SAMPLES_PER_HALF - 1}),
m(k) AS (SELECT 0 UNION ALL SELECT k + 1 FROM m WHERE k < {FILLER_MATCHES})
SELECT IF(k = 0, '{MATCH}', CONCAT('filler-', k)), h.h, 100 + i % 12, 1 + (i % 12) % 2,
       (i * 37) % 4000 - 2000, (i * 53) % 4000 - 2000, (i * 11) % 300, 1, REPEAT('a', 64),
       i * {HALF_SECONDS}.0 / {SAMPLES_PER_HALF}
FROM n JOIN m JOIN (SELECT 1 AS h UNION ALL SELECT 2) h;
INSERT INTO ktp_shot_events (match_id, half, player_id, game_time, pos_x, pos_y, pos_z, pitch, yaw)
WITH RECURSIVE n(i) AS (SELECT 0 UNION ALL SELECT i + 1 FROM n WHERE i < {SHOTS_PER_HALF - 1})
SELECT '{MATCH}', h.h, 100 + i % 12, i * {HALF_SECONDS}.0 / {SHOTS_PER_HALF},
       (i * 17) % 4000 - 2000, (i * 29) % 4000 - 2000, 50, i % 40 - 20, (i * 7) % 360
FROM n JOIN (SELECT 1 AS h UNION ALL SELECT 2) h;
ANALYZE TABLE ktp_match_players, ktp_shot_events, ktp_position_samples;
"""

BOUNDS = ("p.match_id >= sh.match_id AND p.match_id <= sh.match_id\n"
          "     AND p.half >= sh.half AND p.half <= sh.half")
# The join as it stood before the bounds: the plan this replaced.
EQUALITIES = f"p.match_id = '{MATCH}' AND p.half = sh.half"


def _p_access(plan: object) -> dict | None:
    if isinstance(plan, dict):
        if plan.get("table_name") == "p":
            return plan
        children = plan.values()
    elif isinstance(plan, list):
        children = plan
    else:
        return None
    for child in children:
        found = _p_access(child)
        if found is not None:
            return found
    return None


def _run(db: EphemeralMysql, query: str) -> tuple[str, dict]:
    rows = db.sql(query)
    # --raw leaves the JSON unescaped, so it spans lines below the header.
    plan = json.loads(db.sql("EXPLAIN FORMAT=JSON " + query).split(chr(10), 1)[1])
    return rows, _p_access(plan)


def test_placement_reads_a_window_per_shot_and_matches_the_equality_join(tmp_path: Path):
    query = analytics.read_query("shot_placement_fact.sql", MATCH)
    assert BOUNDS in query, "shot_placement_fact.sql no longer has the bounds join"
    equality_query = query.replace(BOUNDS, EQUALITIES)

    with EphemeralMysql.start(parent=tmp_path) as db:
        db.sql(SCHEMA)
        rows, access = _run(db, query)
        eq_rows, eq_access = _run(db, equality_query)

    assert rows.strip() and rows == eq_rows
    # A range re-planned per shot can bound game_time; a ref cannot.
    assert "range_checked_for_each_record" in access, access
    assert "idx_pos_match_half_time" in access["possible_keys"]
    # Control: the equality form plans a ref on an equality prefix that never
    # reaches game_time, so the assertions above separate the two forms.
    assert eq_access.get("access_type") == "ref", eq_access
    assert "game_time" not in eq_access["used_key_parts"], eq_access
