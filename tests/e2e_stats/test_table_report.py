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
        "emitted": {"kills": 12, "assist": 3, "assist_context": 2, "cap_break": 1,
                    "life_boundary": 24},
        "rows": {
            "players": 16, "bots": 16, "frags": 12, "suicides": 1,
            "life_events": 24,
            "assist_context": 2,
            "assist": {"ppa": 3}, "cap_break": {"pa": 1},
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
    assert "| Kills/frags | 12 | 12 |" in body
    assert "| Assists (generic PPA) | 3 | 3 |" in body
    assert "| Assist contexts (canonical, in-match) | 2 | 2 |" in body
    assert "| Life boundaries | 24 | 24 |" in body
    assert "SQL `NULL` / not applicable" in body
    assert "`hlstats_Events_Frags`" in body
    assert "garand\\|scoped" in body
