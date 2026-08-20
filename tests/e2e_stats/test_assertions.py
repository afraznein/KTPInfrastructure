"""Unit tests for the Lane B database assertions.

These test the *judgements*, not the database. Whether MySQL returns the right
rows is Lane B's job; whether a row count of zero produces a failure with a
message someone can act on at 06:00 is this file's job.

The bar for each assertion is: would it catch the specific failure it was
written for, and does it stay quiet on a legitimate run? Both directions are
tested, because an assertion that never fires is the same as no assertion.
"""

from __future__ import annotations

import pytest

from . import assertions


class FakeDb:
    """Answers queries from canned numbers, matched on query substrings."""

    database = "hlstatsx_test"

    def __init__(self, *, ppa=0, pa=0, frags=0, players=0, positions=None):
        self._ppa, self._pa = ppa, pa
        self._frags, self._players = frags, players
        # (rows, nulls, all_zero, distinct, max_abs)
        self._positions = positions

    def sql(self, query):
        if "COUNT(DISTINCT" in query:
            if self._positions is None:
                return "a\tb\tc\td\te\n"
            return ("total\tnulls\tzeros\tdistinct\tmax\n"
                    + "\t".join(str(v) for v in self._positions) + "\n")
        return ""

    def count(self, query):
        if "PlayerPlayerActions" in query:
            return self._ppa
        if "PlayerActions" in query:
            return self._pa
        if "Events_Frags" in query:
            return self._frags
        if "hlstats_Players" in query:
            return self._players
        return 0

    def scalar(self, query):
        return None


_PPA = "hlstats_Events_PlayerPlayerActions"
_PA = "hlstats_Events_PlayerActions"


class FlagStateDb(FakeDb):
    def __init__(self, *, rows, initial, bad_owners=0):
        super().__init__()
        self.rows = rows
        self.initial = initial
        self.bad_owners = bad_owners

    def count(self, query):
        if "ktp_flag_state_events" not in query:
            return super().count(query)
        if "owner_team NOT IN" in query:
            return self.bad_owners
        if "is_initial = 1" in query:
            return self.initial
        return self.rows


class QueryCaptureDb(FakeDb):
    def __init__(self, rows):
        super().__init__()
        self.rows = rows
        self.queries = []

    def count(self, query):
        self.queries.append(query)
        return self.rows


class LifeEventDb(FakeDb):
    def __init__(self, *, rows, starts, deaths, invalid=0, duplicates=0):
        super().__init__()
        self.rows = rows
        self.starts = starts
        self.deaths = deaths
        self.invalid = invalid
        self.duplicates = duplicates

    def count(self, query):
        if "ktp_life_events" not in query:
            return super().count(query)
        if "duplicates" in query:
            return self.duplicates
        if "boundary_kind = 'start'" in query and "NOT IN" not in query:
            return self.starts
        if "boundary_kind = 'end'" in query and "reason = 'death'" in query:
            return self.deaths
        if "NOT IN ('start','end')" in query:
            return self.invalid
        return self.rows


class CaptureSchemaDb(FakeDb):
    def __init__(self, matched):
        super().__init__()
        self.matched = matched
        self.query = ""

    def count(self, query):
        if "information_schema.COLUMNS" in query:
            self.query = query
            return self.matched
        return super().count(query)


class AssistContextDb(FakeDb):
    def __init__(self, *, rows, scoped=None, ppa=0, table_exists=True,
                 invalid=0, duplicates=0, interval_mismatches=0):
        super().__init__(ppa=ppa)
        self.rows = rows
        self.scoped = rows if scoped is None else scoped
        self.table_exists = table_exists
        self.invalid = invalid
        self.duplicates = duplicates
        self.interval_mismatches = interval_mismatches
        self.queries = []

    def count(self, query):
        self.queries.append(query)
        if "information_schema.TABLES" in query:
            return int(self.table_exists)
        if "LEFT JOIN ktp_matches" in query:
            return self.interval_mismatches
        if ") duplicates" in query:
            return self.duplicates
        if "UNIX_TIMESTAMP(event_time)" in query:
            return self.invalid
        if "BINARY match_id = BINARY" in query:
            return self.scoped
        if "ktp_assist_events" in query:
            return self.rows
        return super().count(query)


class TaggedCountDb(FakeDb):
    def __init__(self, code, **counts):
        super().__init__()
        self.code = code
        self.counts = counts
        self.queries = []

    def count(self, query):
        self.queries.append(query)
        for name, value in self.counts.items():
            if f"/* {self.code}:{name} */" in query:
                return value
        return super().count(query)


def _carried(db, code="assist", *, emitted, table=_PPA, other=_PA):
    return assertions.check_carried(db, code, emitted=emitted, table=table,
                                    other_table=other)


# -- the three-way verdict -------------------------------------------------


def test_every_emitted_line_carried_is_ok():
    assert _carried(FakeDb(ppa=7), emitted=7)["status"] == "ok"


def test_partial_loss_is_a_pipeline_failure():
    """The one a `>= 1` check waves through. The unflushed-queue bug wrote 39
    rows for 47 events and would have passed a minimum-count assertion."""
    v = _carried(FakeDb(ppa=39), emitted=47)
    assert v["status"] == "pipeline"
    assert "39 row(s)" in v["detail"]


def test_nothing_emitted_is_not_exercised_rather_than_a_failure():
    """Bot AI decides whether the scenario happens. Calling an empty log a
    pipeline defect trains people to ignore the lane."""
    v = _carried(FakeDb(ppa=0), "cap_break", emitted=0, table=_PA, other=_PPA)
    assert v["status"] == "not_exercised"
    assert "did not produce the scenario" in v["detail"]


def test_flag_state_pipeline_requires_exact_carry_and_a_baseline():
    assert assertions.check_flag_states(
        FlagStateDb(rows=7, initial=5), emitted=7
    )["status"] == "ok"
    assert assertions.check_flag_states(
        FlagStateDb(rows=6, initial=5), emitted=7
    )["status"] == "pipeline"
    assert assertions.check_flag_states(
        FlagStateDb(rows=7, initial=0), emitted=7
    )["status"] == "pipeline"


def test_position_samples_compare_only_the_driven_match():
    db = QueryCaptureDb(rows=12)
    verdict = assertions.check_position_samples(
        db, emitted=12, match_id="1787019402-TEST")
    assert verdict["status"] == "ok"
    assert db.queries == [
        "SELECT COUNT(*) FROM ktp_position_samples "
        "WHERE match_id = '1787019402-TEST'"
    ]


def test_life_events_require_exact_valid_start_and_death_coverage():
    assert assertions.check_life_events(
        LifeEventDb(rows=20, starts=12, deaths=8), emitted=20
    )["status"] == "ok"
    assert assertions.check_life_events(
        LifeEventDb(rows=19, starts=12, deaths=7), emitted=20
    )["status"] == "pipeline"
    assert assertions.check_life_events(
        LifeEventDb(rows=20, starts=12, deaths=8, invalid=1), emitted=20
    )["status"] == "pipeline"
    assert assertions.check_life_events(
        LifeEventDb(rows=20, starts=20, deaths=0), emitted=20
    )["status"] == "pipeline"


@pytest.mark.parametrize(
    ("checker", "code"),
    [
        (assertions.check_frag_producer_clocks, "frag_producer_clocks"),
        (assertions.check_damage_producer_clocks, "damage_producer_clocks"),
    ],
)
def test_target_producer_clocks_require_exact_context_and_interval(
        checker, code):
    db = TaggedCountDb(
        code, candidates=6, exact=6, invalid_clocks=0,
        interval_mismatches=0,
    )
    verdict = checker(
        db, emitted=6, match_id="1787019402-TEST", half=1
    )

    assert verdict["status"] == "ok"
    assert verdict["clocked_rows"] == 6
    sql = "\n".join(db.queries)
    assert "BINARY e.producer_match_id = BINARY '1787019402-TEST'" in sql
    assert "e.producer_half = 1" in sql
    assert "e.game_time IS NULL" in sql
    assert "e.event_epoch IS NULL" in sql
    assert "UNIX_TIMESTAMP(m.start_time)" in sql
    assert "UNIX_TIMESTAMP(m.end_time)" in sql


@pytest.mark.parametrize(
    ("counts", "field"),
    [
        ({"candidates": 6, "exact": 5, "invalid_clocks": 0,
          "interval_mismatches": 0}, "wrong_context"),
        ({"candidates": 6, "exact": 6, "invalid_clocks": 1,
          "interval_mismatches": 0}, "invalid_clocks"),
        ({"candidates": 6, "exact": 6, "invalid_clocks": 0,
          "interval_mismatches": 1}, "interval_mismatches"),
    ],
)
@pytest.mark.parametrize(
    ("checker", "code"),
    [
        (assertions.check_frag_producer_clocks, "frag_producer_clocks"),
        (assertions.check_damage_producer_clocks, "damage_producer_clocks"),
    ],
)
def test_target_producer_clocks_fail_closed(checker, code, counts, field):
    verdict = checker(
        TaggedCountDb(code, **counts), emitted=6,
        match_id="1787019402-TEST", half=1,
    )
    assert verdict["status"] == "pipeline"
    assert verdict[field] == 1
    assert verdict["clocked_rows"] == 5


def test_target_producer_clock_check_does_not_reject_unscoped_legacy_rows():
    db = TaggedCountDb(
        "damage_producer_clocks", candidates=4, exact=4,
        invalid_clocks=0, interval_mismatches=0,
    )
    verdict = assertions.check_damage_producer_clocks(
        db, emitted=4, match_id="target-TEST", half=1
    )
    assert verdict["status"] == "ok"
    candidate_query = next(
        query for query in db.queries
        if "/* damage_producer_clocks:candidates */" in query
    )
    assert "e.match_id" in candidate_query
    assert "e.producer_match_id" in candidate_query
    assert "IS NULL" not in candidate_query


def test_life_event_context_requires_exact_half_and_event_time_interval():
    db = TaggedCountDb(
        "life_event_context", candidates=8, exact=8, invalid=0,
        starts=4, death_ends=4, interval_mismatches=0,
    )
    verdict = assertions.check_life_event_context(
        db, emitted=8, match_id="1787019402-TEST", half=1
    )
    assert verdict["status"] == "ok"
    assert verdict["clocked_rows"] == 8
    sql = "\n".join(db.queries)
    assert "BINARY le.match_id = BINARY '1787019402-TEST'" in sql
    assert "le.half = 1" in sql
    assert "UNIX_TIMESTAMP(le.event_time) = le.event_epoch" in sql
    assert "le.event_time >= m.start_time" in sql
    assert "le.event_time <= m.end_time" in sql


@pytest.mark.parametrize(
    ("counts", "field"),
    [
        ({"candidates": 8, "exact": 7, "invalid": 0, "starts": 4,
          "death_ends": 3, "interval_mismatches": 0}, "wrong_context"),
        ({"candidates": 8, "exact": 8, "invalid": 1, "starts": 4,
          "death_ends": 4, "interval_mismatches": 0}, "invalid"),
        ({"candidates": 8, "exact": 8, "invalid": 0, "starts": 4,
          "death_ends": 4, "interval_mismatches": 1}, "interval_mismatches"),
        ({"candidates": 8, "exact": 8, "invalid": 0, "starts": 8,
          "death_ends": 0, "interval_mismatches": 0}, "death_ends"),
    ],
)
def test_life_event_context_fails_closed(counts, field):
    verdict = assertions.check_life_event_context(
        TaggedCountDb("life_event_context", **counts), emitted=8,
        match_id="1787019402-TEST", half=1,
    )
    assert verdict["status"] == "pipeline"
    if field == "death_ends":
        assert verdict[field] == 0
    else:
        assert verdict[field] == 1


def test_migration_017_schema_preserves_truthful_legacy_nullability():
    verdict = assertions.check_capture_clock_schema(CaptureSchemaDb(matched=22))
    assert verdict["status"] == "ok"
    assert verdict["expected"] == 22


def test_migration_017_schema_rejects_a_missing_or_wrongly_nonnull_column():
    db = CaptureSchemaDb(matched=21)
    verdict = assertions.check_capture_clock_schema(db)
    assert verdict["status"] == "pipeline"
    assert "IS_NULLABLE = 'YES'" in db.query
    assert "IS_NULLABLE = 'NO'" in db.query


def test_assist_context_is_exact_and_distinct_from_generic_ppa_rows():
    # One generic diagnostic/warmup assist may exist in addition to the two
    # match-scoped canonical rows. The two ledgers intentionally have distinct
    # counts and purposes.
    verdict = assertions.check_assist_context(
        AssistContextDb(rows=2, ppa=3), emitted=2,
        match_id="1787019402-TEST", half=1,
    )
    assert verdict["status"] == "ok"
    assert verdict["rows"] == 2
    assert verdict["generic_ppa_rows"] == 3


def test_assist_context_zero_is_not_a_false_pass_or_false_fact():
    empty = assertions.check_assist_context(
        AssistContextDb(rows=0), emitted=0,
        match_id="1787019402-TEST", half=1,
    )
    assert empty["status"] == "not_exercised"

    false_fact = assertions.check_assist_context(
        AssistContextDb(rows=1, scoped=1), emitted=0,
        match_id="1787019402-TEST", half=1,
    )
    assert false_fact["status"] == "pipeline"


@pytest.mark.parametrize(
    ("overrides", "field"),
    [
        ({"rows": 2, "scoped": 1}, "wrong_context"),
        ({"rows": 2, "invalid": 1}, "invalid"),
        ({"rows": 2, "duplicates": 1}, "duplicate_keys"),
        ({"rows": 2, "interval_mismatches": 1}, "interval_mismatches"),
    ],
)
def test_assist_context_rejects_wrong_half_clock_shape_or_duplicates(
        overrides, field):
    verdict = assertions.check_assist_context(
        AssistContextDb(**overrides), emitted=2,
        match_id="1787019402-TEST", half=1,
    )
    assert verdict["status"] == "pipeline"
    assert verdict[field] > 0


def test_assist_context_requires_migration_017_table():
    verdict = assertions.check_assist_context(
        AssistContextDb(rows=0, table_exists=False), emitted=1,
        match_id="1787019402-TEST", half=1,
    )
    assert verdict["status"] == "pipeline"
    assert "migration 017" in verdict["detail"]


def test_missing_lane_b_weaponstats_is_a_pipeline_failure():
    v = assertions.check_statsme_flushed(FakeDb(), weaponstats_lines=0)
    assert v["status"] == "pipeline"
    assert "compile flag" in v["detail"]


class MatchStatsDb:
    def __init__(self, *, rows=12, mismatches=0, total_mismatches=0,
                 statsme=0, attributed=0):
        self.rows = rows
        self.mismatches = mismatches
        self.total_mismatches = total_mismatches
        self.statsme = statsme
        self.attributed = attributed
        self.queries = []

    def count(self, query):
        self.queries.append(query)
        if "lane_b_match_stats_source_mismatch" in query:
            return self.mismatches
        if "lane_b_match_stats_total_mismatch" in query:
            return self.total_mismatches
        if "ktp_match_stats" in query:
            return self.rows
        if "WHERE match_id" in query and "Events_Statsme" in query:
            return self.attributed
        if "Events_Statsme" in query:
            return self.statsme
        return 0


def test_statsme_requires_match_attribution_when_context_is_supplied():
    verdict = assertions.check_statsme_flushed(
        MatchStatsDb(statsme=64, attributed=0), weaponstats_lines=64,
        match_id="test-match", half=1)
    assert verdict["status"] == "pipeline"
    assert "flush before KTP_MATCH_END" in verdict["detail"]


def test_statsme_attribution_passes_when_every_row_is_tagged():
    verdict = assertions.check_statsme_flushed(
        MatchStatsDb(statsme=64, attributed=64), weaponstats_lines=64,
        match_id="test-match", half=1)
    assert verdict["status"] == "ok"


def test_match_stats_cache_reconciles_with_canonical_events():
    db = MatchStatsDb()
    verdict = assertions.check_match_stats_reconciled(db, match_id="test-match")
    assert verdict["status"] == "ok"
    source_query = next(
        query for query in db.queries
        if "lane_b_match_stats_source_mismatch" in query
    )
    assert "match_id=ms.match_id" not in source_query
    assert source_query.count("match_id='test-match'") == 6


def test_match_stats_cache_mismatch_fails():
    verdict = assertions.check_match_stats_reconciled(
        MatchStatsDb(mismatches=1), match_id="test-match")
    assert verdict["status"] == "pipeline"
    assert "canonical events" in verdict["detail"]


class FragContextDb:
    def __init__(self, rows, claimed):
        self.rows = rows
        self.claimed = claimed

    def count(self, query):
        return self.claimed if "frag_context_recorded" in query else self.rows


def test_every_frag_context_is_claimed_once():
    verdict = assertions.check_frag_context_claimed(
        FragContextDb(rows=48, claimed=43), emitted=47, unmatched=4)
    assert verdict["status"] == "ok"


def test_unclaimed_frag_context_fails_the_lane():
    verdict = assertions.check_frag_context_claimed(
        FragContextDb(rows=48, claimed=42), emitted=47, unmatched=4)
    assert verdict["status"] == "pipeline"
    assert "should claim 43" in verdict["detail"]


def test_nothing_emitted_but_rows_present_still_flags_the_flag_inversion():
    """The flag invariant is about configuration, not volume, so it is checked
    even when the run exercised nothing."""
    v = _carried(FakeDb(ppa=3), "cap_break", emitted=0, table=_PA, other=_PPA)
    assert v["status"] == "pipeline"


def test_rows_in_both_tables_is_a_pipeline_failure():
    v = _carried(FakeDb(ppa=5, pa=5), emitted=5)
    assert v["status"] == "pipeline"
    assert "wrong way" in v["detail"]


# -- assists ---------------------------------------------------------------


def test_assists_pass_when_recorded_in_the_right_table():
    rows = assertions.assert_assists_recorded(FakeDb(ppa=5))
    assert rows.ppa == 5


def test_no_assists_fails_and_says_where_to_look():
    """A zero is ambiguous between capture and daemon, so the message has to
    name both sides — that ambiguity cost a session to resolve once already."""
    with pytest.raises(AssertionError) as e:
        assertions.assert_assists_recorded(FakeDb(ppa=0))
    assert "IgnoreBots" in str(e.value)
    assert "capture-side" in str(e.value)


def test_assist_in_both_tables_is_a_failure_even_with_plenty_of_rows():
    """The flag-inversion invariant. Both flags set records every assist twice
    and applies the reward twice — silent rating corruption, no error."""
    with pytest.raises(AssertionError) as e:
        assertions.assert_assists_recorded(FakeDb(ppa=5, pa=5))
    assert "exactly 0" in str(e.value)
    assert "twice" in str(e.value)


# -- cap breaks ------------------------------------------------------------


def test_breaks_pass_when_recorded_as_a_player_action():
    assert assertions.assert_breaks_recorded(FakeDb(pa=1)).pa == 1


def test_break_in_the_player_player_table_is_a_failure():
    """Mirror image of the assist invariant. A break has no victim, so a PPA
    row means it is being attributed against a meaningless second player."""
    with pytest.raises(AssertionError) as e:
        assertions.assert_breaks_recorded(FakeDb(pa=1, ppa=1))
    assert "no victim" in str(e.value)


def test_missing_break_says_it_may_just_be_rare():
    """Breaks need a capper killed mid-capture. The message must not send
    someone hunting a pipeline bug when the bots simply never produced one."""
    with pytest.raises(AssertionError) as e:
        assertions.assert_breaks_recorded(FakeDb(pa=0))
    assert "rarer" in str(e.value)


# -- positions -------------------------------------------------------------


def test_varied_in_bounds_positions_pass():
    stats = assertions.assert_positions_populated(
        FakeDb(positions=(5, 0, 0, 5, 2983)), "assist",
        table="hlstats_Events_PlayerPlayerActions")
    assert stats["distinct"] == 5


def test_all_null_positions_fail():
    """Every row NULL is `ksc_origin_str` failing its read and omitting the
    property — emitting works, the origin lookup does not."""
    with pytest.raises(AssertionError, match="NULL positions"):
        assertions.assert_positions_populated(
            FakeDb(positions=(5, 5, 0, 1, 0)), "assist",
            table="hlstats_Events_PlayerPlayerActions")


def test_all_zero_positions_fail():
    """The deployment plan's explicit check. `ksc_origin_str` returns false
    rather than zeros on a failed read, so all-zero means the guard was
    bypassed, not that it fired."""
    with pytest.raises(AssertionError, match="0 0 0"):
        assertions.assert_positions_populated(
            FakeDb(positions=(5, 0, 5, 1, 0)), "assist",
            table="hlstats_Events_PlayerPlayerActions")


def test_one_repeated_position_fails():
    with pytest.raises(AssertionError, match="share one position"):
        assertions.assert_positions_populated(
            FakeDb(positions=(5, 0, 0, 1, 900)), "assist",
            table="hlstats_Events_PlayerPlayerActions")


def test_a_single_row_at_one_position_is_fine():
    """cap_breaks are rare enough that one row is a normal outcome, and one row
    trivially has one distinct position. Failing that would make the rarest
    real success look like a bug."""
    stats = assertions.assert_positions_populated(
        FakeDb(positions=(1, 0, 0, 1, 418)), "cap_break",
        table="hlstats_Events_PlayerActions")
    assert stats["rows"] == 1


def test_out_of_world_positions_fail():
    """Beyond GoldSrc's ±16384 is a misread — a struct offset or a truncated
    string — not a large map."""
    with pytest.raises(AssertionError, match="world"):
        assertions.assert_positions_populated(
            FakeDb(positions=(5, 0, 0, 5, 99999)), "assist",
            table="hlstats_Events_PlayerPlayerActions")


# -- regression and buffer -------------------------------------------------


def test_baseline_requires_frags_and_players():
    assert assertions.assert_baseline_still_flows(
        FakeDb(frags=47, players=16)) == {"frags": 47, "players": 16}


def test_no_frags_fails_loudly():
    """A branch that adds assists while breaking the frag path is the
    regression worth catching; without this the run could go green on it."""
    with pytest.raises(AssertionError, match="Events_Frags"):
        assertions.assert_baseline_still_flows(FakeDb(frags=0, players=16))


def test_no_players_points_at_the_server_row():
    """0 players is almost always a missing/mismatched hlstats_Servers row, not
    anything to do with capture. Saying so saves the wrong investigation."""
    with pytest.raises(AssertionError, match="hlstats_Servers"):
        assertions.assert_baseline_still_flows(FakeDb(frags=0, players=0))


def test_dropped_capture_lines_fail_the_run():
    """A drop means every other count is a lower bound on an unknown quantity,
    so the run cannot be interpreted even though the pipeline "worked"."""
    with pytest.raises(AssertionError, match="buffer-overflow"):
        assertions.assert_no_dropped_lines(
            'L 08/10/2026 - 04:00:00: [KTP-STATS] dropped 3 capture line(s)')


def test_a_clean_log_passes():
    assertions.assert_no_dropped_lines('"A<1><BOT><Allies>" killed "B<2><BOT><Axis>"')
