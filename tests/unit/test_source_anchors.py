"""The anchoring primitives, including the failure that made them necessary.

Two shapes are reproduced here rather than described. The LOUD one: a comment
naming the guarded call, written above an unrelated function, becomes the match
and the guard compares offsets that mean nothing. The QUIET one, which is
worse: that same mislocation moves the first anchor EARLIER, so an `A before B`
assertion still holds and a real reordering ships green.

Each test states which side it is holding, because a summary table reads the
same either way.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tests.source_anchors import (  # noqa: E402
    CODE,
    HASH,
    LINE_START,
    PAWN,
    PYTHON,
    SQL,
    AnchoredSource,
    MislocatedAnchor,
    assert_in_order,
    blank_comments,
    call_sites,
    code_text,
    sole_call_site,
)

ABSENT = "qqz_no_such_symbol_anywhere"


# ---------------------------------------------------------------------------
# Blanking. Every other primitive reads its output, so it is held on its own.
# ---------------------------------------------------------------------------

PAWN_SRC = '''/**
 * bd_execute_kill() is called from bd_kill_poll().
 */
stock bool:bd_execute_kill()
{
\tlog_amx("a // b /* c */ d");   // trailing note about bd_execute_kill()
\treturn bd_owner(^'x^') == 0;
}
'''


def test_blanking_keeps_every_offset():
    """Offsets have to survive, or an existing slice stops meaning what it did."""
    blanked = blank_comments(PAWN_SRC, PAWN)
    assert len(blanked) == len(PAWN_SRC)
    assert blanked.count("\n") == PAWN_SRC.count("\n")
    # Every surviving character is in its original place.
    for i, ch in enumerate(blanked):
        assert ch == PAWN_SRC[i] or ch in " \n"


def test_blanking_removes_both_comment_forms_and_keeps_literals():
    blanked = blank_comments(PAWN_SRC, PAWN)
    assert "trailing note" not in blanked
    assert "is called from" not in blanked
    assert '"a // b /* c */ d"' in blanked, "a comment marker inside a string was eaten"
    assert "stock bool:bd_execute_kill()" in blanked
    # Pawn escapes with ^, so the char literal must not swallow the line.
    assert "bd_owner(^'x^') == 0" in blanked


def test_hash_blanking_needs_a_comment_position():
    text = 'url: "http://x/#frag"\nkey: a#b   # a real comment\n'
    blanked = blank_comments(text, HASH)
    assert "a real comment" not in blanked
    assert "a#b" in blanked, "`a#b` is a value in yaml, shell and Dockerfile alike"
    assert "#frag" in blanked, "a fragment inside a quoted string is not a comment"


PY_SRC = '''"""Module prose mentioning after_live() first."""


def run():
    """Calls after_live() once the match is live."""
    cfg = {"stage": "before_play()"}
    # after_live() runs here
    settle()
    after_live()
    return cfg
'''


def test_python_blanking_takes_comments_and_docstrings_only():
    blanked = blank_comments(PY_SRC, PYTHON)
    assert "Module prose" not in blanked
    assert "Calls after_live() once" not in blanked
    assert "runs here" not in blanked
    # A dict value is a literal, not prose: blanking it would break an anchor
    # that is a line of code containing a string.
    assert '{"stage": "before_play()"}' in blanked
    assert "    after_live()\n" in blanked


def test_an_unparseable_fragment_still_gets_the_comment_pass():
    """A guard over a snippet must degrade, not raise."""
    blanked = blank_comments("def f(:\n    x = 1  # note\n", PYTHON)
    assert "note" not in blanked and "x = 1" in blanked


def test_an_unknown_flavour_is_refused():
    with pytest.raises(ValueError, match="flavour"):
        blank_comments("x", "klingon")


# ---------------------------------------------------------------------------
# The LOUD half: a comment about the guarded thing becomes the match.
# ---------------------------------------------------------------------------

INCIDENT = '''#!/usr/bin/env python3
# require_current() is what refuses a stale checkout, exit 3.
def unrelated():
    pass


def main():
    args = parse_args()
    require_current(__file__)
    return args
'''


def test_a_comment_naming_the_call_is_refused_as_a_mislocation():
    src = code_text(INCIDENT, PYTHON, "ktp-verify-deploy.py")
    # The comment is above an unrelated function, which is the incident verbatim.
    assert INCIDENT.index("# require_current(") < INCIDENT.index("def main")
    located = src.index("require_current(")
    assert located > INCIDENT.index("args = parse_args()"), (
        "the located call must be the real one, not the sentence about it"
    )


def test_an_anchor_that_exists_only_in_prose_names_itself_a_mislocation():
    text = "def main():\n    pass\n# require_current(__file__) belongs in main()\n"
    src = code_text(text, PYTHON, "script.py")
    with pytest.raises(MislocatedAnchor) as exc:
        src.index("require_current(__file__)")
    assert "MISLOCATION" in str(exc.value)
    assert "inside a comment" in str(exc.value)
    assert "script.py" in str(exc.value)


def test_an_absent_anchor_is_not_reported_as_a_mislocation():
    """The two failures have different remedies, so they must read differently."""
    src = code_text("def main():\n    pass\n", PYTHON, "script.py")
    with pytest.raises(MislocatedAnchor) as exc:
        src.index(ABSENT)
    assert "does not occur at all" in str(exc.value)
    assert "MISLOCATION" not in str(exc.value)


def test_an_ambiguous_anchor_is_refused_and_names_every_line():
    src = code_text("a = f()\nb = 2\na = f()\n", PYTHON, "script.py")
    with pytest.raises(MislocatedAnchor) as exc:
        src.index("a = f()")
    assert "matches 2 places" in str(exc.value)
    assert "[1, 3]" in str(exc.value)


def test_a_bounded_search_may_match_many():
    """`the next } after here` is a legitimate question; uniqueness is not owed."""
    src = code_text("f() {\n}\ng() {\n}\n", PYTHON, "x")
    first = src.index("g() {")
    assert src.index("}", first) > first


# ---------------------------------------------------------------------------
# LINE_START, for a definition or a delimiter at column 0.
# ---------------------------------------------------------------------------

def test_line_start_skips_the_doc_comment_mention():
    src = AnchoredSource(PAWN_SRC, LINE_START, PAWN, "KTPBreakDrive.sma")
    at = src.index("stock bool:bd_execute_kill()")
    assert PAWN_SRC[at:at + 5] == "stock"
    assert PAWN_SRC.count("bd_execute_kill()") > 1, "the mention must really be there"


def test_line_start_refuses_a_mention_that_never_starts_a_line():
    src = AnchoredSource(PAWN_SRC, LINE_START, PAWN, "KTPBreakDrive.sma")
    with pytest.raises(MislocatedAnchor) as exc:
        src.index("bd_execute_kill() is called")
    assert "away from the start of a line" in str(exc.value)


def test_a_deliberate_comment_delimiter_is_still_usable():
    """The guard skips prose unless the anchor IS prose, which is how a `/**`
    section delimiter keeps working."""
    src = AnchoredSource(PAWN_SRC, LINE_START, PAWN, "KTPBreakDrive.sma")
    assert src.index("/**") == 0


def test_body_slices_between_two_unique_anchors():
    src = AnchoredSource(PAWN_SRC, LINE_START, PAWN, "KTPBreakDrive.sma")
    body = src.body("stock bool:bd_execute_kill()", "}")
    assert "return bd_owner" in body
    assert "is called from" not in body


def test_membership_asks_about_the_code_whatever_the_rule():
    src = AnchoredSource(PAWN_SRC, LINE_START, PAWN, "KTPBreakDrive.sma")
    assert "return bd_owner(^'x^') == 0" in src, "a mid-line fact is still a fact"
    assert "is called from bd_kill_poll()" not in src, "a comment satisfied it"
    assert ABSENT not in src


def test_find_returns_minus_one_only_for_a_true_absence():
    src = code_text("a = f()\n# g() in a note\n", PYTHON, "x")
    assert src.find(ABSENT) == -1
    with pytest.raises(MislocatedAnchor):
        src.find("g()")


def test_an_end_bound_is_refused_rather_than_silently_ignored():
    src = code_text("a = f()\n", PYTHON, "x")
    with pytest.raises(TypeError, match="no end bound"):
        src.index("f()", 0, 3)


# ---------------------------------------------------------------------------
# Call sites, from the parse tree.
# ---------------------------------------------------------------------------

def test_the_parse_tree_cannot_be_given_a_call_by_a_comment():
    assert call_sites(INCIDENT, "require_current") == [(9, 4)]
    line, _col = sole_call_site(INCIDENT, "require_current", "ktp-verify-deploy.py")
    assert INCIDENT.splitlines()[line - 1].strip() == "require_current(__file__)"


def test_a_commented_out_call_contributes_nothing():
    text = "def main():\n    # require_current(__file__)\n    pass\n"
    with pytest.raises(MislocatedAnchor) as exc:
        sole_call_site(text, "require_current", "script.py")
    assert "holds no call" in str(exc.value)
    assert "a sentence about the call" in str(exc.value)


def test_two_call_sites_are_refused_with_both_lines():
    text = "def a():\n    require_current(1)\ndef b():\n    require_current(2)\n"
    with pytest.raises(MislocatedAnchor) as exc:
        sole_call_site(text, "require_current", "script.py")
    assert "[2, 4]" in str(exc.value)


def test_an_attribute_call_counts():
    assert call_sites("guard.require_current(x)\n", "require_current") == [(1, 0)]


def test_a_nonsense_name_has_no_call_sites():
    assert call_sites(INCIDENT, ABSENT) == []


# ---------------------------------------------------------------------------
# The QUIET half. This is the one the card did not describe.
# ---------------------------------------------------------------------------

ORDERED = '''def run():
    settle()
    after_live()
    before_play()
'''

REORDERED = '''def run():
    settle()
    before_play()
    after_live()
'''

REORDERED_WITH_NOTE = '''def run():
    settle()
    # after_live() is what go-live waits on
    before_play()
    after_live()
'''


def test_the_order_holds_when_the_code_holds_it():
    assert_in_order(code_text(ORDERED, PYTHON, "x"), "after_live()", "before_play()")


def test_a_real_reordering_fails_and_says_it_is_not_a_mislocation():
    with pytest.raises(AssertionError) as exc:
        assert_in_order(code_text(REORDERED, PYTHON, "x"),
                        "after_live()", "before_play()")
    assert "must come before" in str(exc.value)
    assert "not a mislocation" in str(exc.value)


def test_a_comment_cannot_rescue_a_reordering():
    """The whole point. A plain text index PASSES this; the guard must not.

    The note moves the first anchor earlier, so `A before B` stays true while
    the code has swapped them -- a false pass, with nothing to look at.
    """
    # The defect the shipped shape ships green:
    assert REORDERED_WITH_NOTE.index("after_live()") < \
        REORDERED_WITH_NOTE.index("before_play()")
    # And the guard refusing it:
    with pytest.raises(AssertionError) as exc:
        assert_in_order(code_text(REORDERED_WITH_NOTE, PYTHON, "x"),
                        "after_live()", "before_play()")
    assert "must come before" in str(exc.value)


def test_ordering_refuses_an_ambiguous_anchor_rather_than_taking_the_first():
    text = "def run():\n    after_live()\n    before_play()\n    after_live()\n"
    with pytest.raises(MislocatedAnchor) as exc:
        assert_in_order(code_text(text, PYTHON, "x"),
                        "after_live()", "before_play()")
    assert "matches 2 places" in str(exc.value)


def test_ordering_needs_two_anchors():
    with pytest.raises(ValueError, match="at least two"):
        assert_in_order(code_text(ORDERED, PYTHON, "x"), "after_live()")


def test_a_three_anchor_chain_is_checked_pairwise():
    src = code_text(ORDERED, PYTHON, "x")
    assert_in_order(src, "settle()", "after_live()", "before_play()")
    with pytest.raises(AssertionError):
        assert_in_order(src, "settle()", "before_play()", "after_live()")


def test_an_unknown_rule_is_refused():
    with pytest.raises(ValueError, match="rule must be"):
        AnchoredSource("x", "whenever", PYTHON)


def test_the_rule_constants_are_distinct():
    assert CODE != LINE_START


# ---------------------------------------------------------------------------
# SQL. The haystack here is a statement BUILT at run time, so the hazard is not
# a note somebody wrote above a function -- it is a `--` line the builder emits
# beside the thing a guard orders on. This estate already paid two CI cycles
# for "a comment is query text" on the reading side of the same problem.
# ---------------------------------------------------------------------------

SQL_STATEMENT = """\
START TRANSACTION;
-- COMMIT and ROLLBACK are named here and neither happens
DELETE t FROM `child` t;   # ROLLBACK
/* COMMIT */
SELECT 'a -- b' AS kept, 'it''s #1' AS also_kept, `odd#name` AS backticked;
COMMIT;
"""


def _sql():
    return code_text(SQL_STATEMENT, flavour=SQL, origin="built.sql")


def test_a_dash_comment_cannot_answer_for_the_statement():
    """The LOUD side: `COMMIT` exists twice in prose before it exists in code."""
    assert SQL_STATEMENT.count("COMMIT") == 3
    assert _sql().occurrences("COMMIT") == [SQL_STATEMENT.rindex("COMMIT")]


def test_a_hash_comment_is_a_comment_in_mysql_wherever_it_starts():
    """MySQL needs no whitespace before `#`, unlike YAML or shell."""
    assert "ROLLBACK" in SQL_STATEMENT
    assert "ROLLBACK" not in _sql()


def test_a_comment_marker_inside_a_literal_is_data_and_stays():
    sql = _sql()
    assert "'a -- b' AS kept" in sql
    assert "also_kept" in sql
    assert "backticked" in sql


def test_a_doubled_quote_leaves_the_literal_where_it_was():
    """`''` needs no case of its own: two boundaries span what one escape does.

    Held as a test rather than as a comment because the obvious reading is that
    it needs one, and a branch written for it survived every mutation.
    """
    assert "also_kept" in code_text("select 'it''s -- fine' AS also_kept;",
                                    flavour=SQL, origin="x")
    assert "q, x" in code_text("select '''' AS q, x -- c", flavour=SQL, origin="x")


def test_arithmetic_is_not_a_comment():
    assert "b from" in code_text("select a--b from t;", flavour=SQL, origin="x")


def test_the_quiet_side_a_comment_cannot_rescue_a_reordered_statement():
    """Children before parent, with a `--` line naming the child beforehand.

    The comment moves the first anchor EARLIER, which is the direction that
    keeps an `A before B` assertion green while the statement really does the
    parent first -- the half a reader cannot see.
    """
    reordered = ("-- DELETE t FROM `child` runs first\n"
                 "DELETE t FROM `parent` t;\n"
                 "DELETE t FROM `child` t;\n")
    assert reordered.index("DELETE t FROM `child`") < reordered.index(
        "DELETE t FROM `parent`"), "raw text calls the reordering fine"
    with pytest.raises(AssertionError) as exc:
        assert_in_order(code_text(reordered, flavour=SQL, origin="x"),
                        "DELETE t FROM `child`", "DELETE t FROM `parent`")
    assert "order of the code and not a mislocation" in str(exc.value)


def test_blanking_sql_moves_no_offset():
    assert len(blank_comments(SQL_STATEMENT, SQL)) == len(SQL_STATEMENT)


def test_an_unterminated_block_comment_swallows_the_rest_rather_than_half():
    text = "select 1; /* COMMIT\nCOMMIT;"
    assert code_text(text, flavour=SQL, origin="x").occurrences("COMMIT") == []
