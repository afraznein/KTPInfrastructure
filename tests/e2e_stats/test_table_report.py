from tests.e2e_stats.table_report import (_select_list, changed_table_samples,
                                          render_markdown, table_counts)


class FakeDb:
    def __init__(self):
        self.counts = {"events": 2, "static": 4}

    def sql(self, query):
        if query == "SHOW TABLES":
            return "Tables_in_test\nevents\nstatic\n"
        if query.startswith("SHOW KEYS FROM `events`"):
            return "Table\tKey_name\tSeq_in_index\tColumn_name\nevents\tPRIMARY\t1\tid\n"
        if query.startswith("SHOW KEYS FROM `static`"):
            return ""
        if query.startswith("SELECT * FROM `events`"):
            return "id\tvalue\n5\tnewest\n4\tnewer\n"
        raise AssertionError(query)

    def count(self, query):
        table = query.split("`")[1]
        return self.counts[table]


def test_changed_table_samples_reports_only_growth():
    db = FakeDb()
    assert table_counts(db) == {"events": 2, "static": 4}
    before = {"events": 3, "static": 4}
    db.counts["events"] = 5
    samples = changed_table_samples(db, before)
    assert samples == [{
        "table": "events", "before": 3, "after": 5, "inserted": 2,
        "order_by": ["id"], "columns": ["id", "value"],
        "rows": [["5", "newest"], ["4", "newer"]],
    }]


def test_wide_legacy_player_table_uses_operator_facing_projection():
    selection = _select_list("hlstats_Players")
    assert "`playerId`" in selection
    assert "`kills`" in selection
    assert "`last_skill_change`" in selection
    for legacy_profile_column in ("email", "homepage", "fullName", "icq"):
        assert legacy_profile_column not in selection


def test_event_tables_remain_unabridged_by_default():
    assert _select_list("hlstats_Events_Frags") == "*"


def test_render_markdown_includes_summary_and_samples():
    report = {
        "map": "dod_anzio",
        "play_seconds": 240,
        "match": {"match_id": "20260814-TEST", "half": 1},
        "emitted": {"kills": 13, "frags": 12, "teamkills": 1,
                    "assist": 3, "assist_context": 2, "cap_break": 1,
                    "life_boundary": 24},
        "rows": {
            "players": 16, "bots": 16, "frags": 12, "teamkills": 1,
            "suicides": 1,
            "life_events": 24,
            "assist_context": 2,
            "assist": {"ppa": 3}, "cap_break": {"pa": 1},
        },
        "amxx_gamedata": {
            "artifact_source": "a" * 40 + ":gamedata",
            "source": "/work/build/artifacts/gamedata",
            "destination": "dod/addons/ktpamx/data/gamedata",
            "file_count": 803, "bytes": 123456,
            "tree_sha256": "b" * 64,
        },
        "gamerules_clock_preflight": {
            "status": "ok", "detail": "GameRules available",
            "server_crc": [{"crc32": "89ABCDEF",
                            "path": "/opt/hlds/dod/dlls/dod.so"}],
        },
        "frag_context_diagnostics": {
            "expected_synthetic_unmatched": 3,
            "observed_unmatched": 3,
            "claimed_expected_rows": 63,
            "producer_clock_expected_rows": 63,
            "expected_identities": ["321->329:amerknife",
                                    "321->330:amerknife",
                                    "321->330:amerknife"],
            "observed_identities": ["321->330:amerknife",
                                    "321->329:amerknife",
                                    "321->330:amerknife"],
        },
        "carried": [{"code": "assist", "status": "ok", "detail": "3/3 carried"}],
        "failures": [],
        "coverage_gaps": [],
        "table_samples": [{
            "table": "hlstats_Events_Frags", "before": 0, "after": 12,
            "inserted": 12, "columns": ["id", "weapon"],
            "rows": [["12", "garand|scoped"]],
        }],
    }
    body = render_markdown(report)
    assert "| PASS | dod_anzio | 20260814-TEST" in body
    assert "| Frags | 12 | 12 |" in body
    assert "| Teamkills | 1 | 1 |" in body
    assert "| Assists (generic PPA) | 3 | 3 |" in body
    assert "| Assist contexts (canonical, in-match) | 2 | 2 |" in body
    assert "| Life boundaries | 24 | 24 |" in body
    assert "## Frag-context diagnostic reconciliation" in body
    assert "| 3 | 3 | 63 | 63 |" in body
    assert "321->330:amerknife x2" in body
    assert "## Exact AMXX gamedata provenance" in body
    assert "803 | 123456" in body
    assert "## GameRules / round-clock preflight" in body
    assert "/opt/hlds/dod/dlls/dod.so" in body
    assert "SQL `NULL` / not applicable" in body
    assert "`hlstats_Events_Frags`" in body
    assert "garand\\|scoped" in body


def test_render_markdown_includes_verified_v5_scoreboard():
    report = {
        "map": "dod_anzio", "play_seconds": 360,
        "match": {"match_id": "scored-TEST", "half": 1},
        "emitted": {}, "rows": {"players": 12, "bots": 12},
        "carried": [], "failures": [], "coverage_gaps": [],
        "table_samples": [],
        "v5_match_report": {
            "status": "PASS",
            "normalization": {"center_index": 100},
            "players": [{"rank": 1, "name": "Bot One", "overall_rating": 150.0,
                         "raw_points": 500.0, "momentum_points": 25.0}],
        },
    }
    body = render_markdown(report)
    assert "V5 accumulated match report" in body
    assert "complete accumulated score" in body
    assert "| 1 | Bot One | 150.00 | 500.00 | 25.00 |" in body
    assert "`momentum.svg`" in body
