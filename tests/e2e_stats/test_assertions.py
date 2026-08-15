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


def test_missing_lane_b_weaponstats_is_a_pipeline_failure():
    v = assertions.check_statsme_flushed(FakeDb(), weaponstats_lines=0)
    assert v["status"] == "pipeline"
    assert "compile flag" in v["detail"]


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
