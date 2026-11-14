"""player_match_fact must reach each event table through an index, not a full scan.

hlstats_Events_Statsme and hlstats_Events_PlayerPlayerActions are MyISAM with no
match_id index, so `WHERE match_id = X` alone reads every row under the table read lock the stats daemon's writes wait
on. Reaching it through the roster's playerId lookups reads only those players'
rows, and the roster is all the outer query keeps.
"""
from __future__ import annotations

import re
from pathlib import Path

SQL = (Path(__file__).resolve().parents[2] / "sql" / "analytics"
       / "player_match_fact.sql").read_text(encoding="utf-8")


def _code() -> str:
    return re.sub(r"--[^\n]*", "", SQL)


def _cte(name: str) -> str:
    code = _code()
    m = re.search(rf"\b{name}\s+AS\s*\(", code)
    assert m, name
    depth, i = 1, m.end()
    while depth:
        depth += {"(": 1, ")": -1}.get(code[i], 0)
        i += 1
    return " ".join(code[m.end():i - 1].split())


def test_weapon_totals_reads_statsme_through_the_roster():
    body = _cte("weapon_totals")
    assert "FROM roster r JOIN hlstats_Events_Statsme st ON st.playerId = r.player_id" in body, body
    assert "st.match_id = {{MATCH_ID}}" in body, body
    # Control: the old shape, Statsme alone filtered by match_id, is gone.
    assert not re.search(r"FROM hlstats_Events_Statsme\s+WHERE", body), body


def test_weapon_totals_is_still_keyed_by_the_roster_player():
    # The outer query joins on player_id; a roster row can join Statsme rows
    # for its own playerId only, so grouping stays one row per player.
    body = _cte("weapon_totals")
    assert body.startswith("SELECT st.playerId AS player_id,"), body
    assert body.endswith("GROUP BY st.playerId"), body
    assert re.search(r"LEFT JOIN weapon_totals w ON w\.player_id = r\.player_id", _code())


def test_assists_read_player_player_actions_through_the_roster():
    # Nearly every PlayerPlayerActions row is an assist, so the actionId index
    # reads the whole table; the roster's playerId lookups read its players only.
    body = _cte("assists")
    assert ("FROM roster r JOIN hlstats_Events_PlayerPlayerActions e "
            "ON e.playerId = r.player_id") in body, body
    assert "e.match_id = {{MATCH_ID}}" in body and "a.code = 'assist'" in body, body
    assert body.endswith("GROUP BY e.playerId"), body


def test_producer_coverage_bounds_are_sargable():
    body = _cte("producer_coverage")
    # A bound built from the row's own column, COALESCE(x, e.eventTime), is not a
    # range the optimizer can seek; the DATETIME maximum is, and it keeps the
    # open-match answer (every non-NULL time qualifies).
    assert "COALESCE(mc.ended_at, e.eventTime)" not in body
    assert "COALESCE(mc.ended_at, c.event_time)" not in body
    assert body.count("COALESCE(mc.ended_at, TIMESTAMP '9999-12-31 23:59:59')") == 3, body
    # Control: the three producers are all still checked.
    for code in ("a.code = 'assist'", "a.code = 'cap_break'", "FROM ktp_flag_captures c"):
        assert code in body, code
