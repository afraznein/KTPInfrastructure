"""The e2e lane's migration list must not claim a migration's PRODUCTION state.

Four comments in DEFAULT_SCHEMA_FILES read "PROPOSED for production" for
migrations 038, 039, 040 and 042. All four had been applied to hlstatsx -- 038
since 2026-09-26 -- so every one of them was false, and one of them (042) was
cross-referencing another's wrongness to justify itself.

The rot is structural, not a typo. This file lives in a test lane that stands up
its own database; it has no way to observe production, so a production claim here
can only ever be a remembered fact with nothing holding it true. It will go stale
again the next time someone applies a migration, and a reader has no reason to
doubt it.

So the guard is on the PROPERTY rather than on today's four spellings: a comment
in the migration lists may say why the LANE needs a migration, and may not say
where production stands. The mechanical reasons ("the daemon INSERTs into
ktp_move_census, so a lane without the table no-ops silently") are the parts
worth keeping -- they are about this file and they do not rot.

Comment blocks are joined before matching, so a claim that wraps across two
lines is still caught; and the detector is exercised against the exact four
wordings it was written for, so this cannot quietly become a test that passes
because it matches nothing.
"""
import pathlib
import re

ARTIFACTS = pathlib.Path(__file__).resolve().parents[2] / "tests" / "e2e_stats" / "artifacts.py"
TEXT = ARTIFACTS.read_text(encoding="utf-8")

# A state word near "production" is the claim. "the plan production will have"
# is not one: it says what the lane is for, not whether anything is applied.
STATE = r"proposed|pending|unapplied|awaiting|not\s+(?:yet\s+)?(?:been\s+)?applied|already\s+applied|still\s+to\s+be\s+applied"
# Span is `.`, not `\W`: "PROPOSED for production" puts a word between the two,
# so a non-word-only gap matches nothing at all -- which made the first draft of
# this guard pass against all four comments it exists to catch.
CLAIM = re.compile(
    r"(?is)(?:(?:%s).{0,40}production|production.{0,40}(?:%s))" % (STATE, STATE)
)

# The four wordings this guard was written for, verbatim off the commit before it.
KNOWN_BAD = (
    "Applied here even though it is still PROPOSED for production: the daemon "
    "INSERTs into ktp_move_census, so a lane without the table exercises the "
    "new handler as a no-op and reports clean either way.",
    "Applied here even though it is still PROPOSED for production: the daemon's "
    "score INSERT names ktp_score_events.round_time_left, so a lane without it "
    "fails every score row.",
    "Proposed for production. The daemon's flag-capture INSERT does not name "
    "either new column, so applying it here proves that INSERT still lands.",
    "Proposed for production, and applied here for the same reason 038 is: the "
    "daemon INSERTs into ktp_aim_vis, so a lane without the table exercises the "
    "new handler as a no-op and reports clean either way.",
)

# Wording that must NOT trip it, or the guard would force out the reasons worth keeping.
KNOWN_GOOD = (
    "Index only; nothing the daemon writes depends on it. Applied so the lane "
    "runs analytics against the plan production will have.",
    "The daemon INSERTs into ktp_move_census, so a lane without the table "
    "exercises the handler as a no-op and reports clean either way.",
    "Carried by KTPHLStatsX but never applied here; any other unlisted "
    "migration fails the build.",
)


def comment_blocks():
    """Consecutive `#` lines joined into one string each.

    Joined, because a claim wrapped over two lines is invisible to a per-line
    match -- and these comments wrap at 79 columns, so that is the normal case
    rather than the exotic one.
    """
    blocks, cur = [], []
    for ln in TEXT.split("\n"):
        s = ln.strip()
        if s.startswith("#"):
            cur.append(s.lstrip("#").strip())
        elif cur:
            blocks.append(" ".join(cur))
            cur = []
    if cur:
        blocks.append(" ".join(cur))
    return blocks


def test_the_detector_fires_on_every_wording_it_was_written_for():
    """Without this, an over-narrow regex makes the guard below vacuous."""
    for bad in KNOWN_BAD:
        assert CLAIM.search(bad), "detector misses a known-bad comment: %r" % bad[:70]


def test_the_detector_spares_the_reasons_worth_keeping():
    for good in KNOWN_GOOD:
        assert not CLAIM.search(good), "detector would force out a sound comment: %r" % good[:70]


def test_no_comment_claims_a_migrations_production_state():
    """THE test. This file cannot observe production, so it must not describe it."""
    offenders = [b for b in comment_blocks() if CLAIM.search(b)]
    assert not offenders, \
        "comment claims production state, which this lane cannot verify: %r" % offenders


def test_the_blocks_actually_parsed():
    """A docstring-only file or a changed comment style would empty the scan and
    make the test above pass by finding nothing to look at."""
    blocks = comment_blocks()
    assert len(blocks) > 10, "only %d comment blocks parsed; the scan is not reading the file" % len(blocks)
    assert any("daemon" in b for b in blocks), "the migration-list comments are not in the parsed blocks"


def test_the_migrations_the_stale_comments_named_are_still_listed():
    """The fix was to the comments, not to the lane's coverage."""
    for m in ("038_move_census", "039_score_round_time_left",
              "040_flag_captures_provenance", "042_aim_vis"):
        assert "sql/migrate_%s.sql" % m in TEXT, "lane no longer applies %s" % m
