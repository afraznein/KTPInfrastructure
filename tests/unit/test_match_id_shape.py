"""The match_id_shape check, and the single definition its two readers share.

The check was stamping FAIL on every production match: it accepted only
`<digits>-KTP<digits>` or `*-TEST`, while a real id is `<epoch>-<SERVER>` such
as 1788919258-CHI1. The pattern was also spelled out separately in
match_analytics and match_readiness, which is how one copy gets fixed and the
other is left behind, so the shared object is pinned here alongside the shapes.
"""
from __future__ import annotations

import pytest

from scripts import match_readiness
from scripts.match_analytics import MATCH_ID_RE, evaluate_quality

# What KTPMatchHandler actually writes.
PRODUCTION = [
    "1788919258-CHI1",
    "1788915557-ATL1",
    "1772072225-ATL5",
    "1789005000-DAL1",
    "1754839201-DEN5",
    "1782677636-NY1",
]
# The 12-man branch keys on its queue id instead of the clock.
LEGACY_12MAN = ["1.3-6774-ATL1", "1.3-6574-DEN4", "1.3-9002-DAL2"]
TEST_MODE = ["1786721179-TEST", "objective-witness-TEST", "anything-TEST"]
# Accepted before this change. A widening that dropped one of these would be a
# regression riding inside a fix.
PREVIOUSLY_ACCEPTED = ["12345-KTP678", "1785715972-KTP1", "1700000000-KTP1"]

MALFORMED = [
    "1788919258",       # no server alias
    "-CHI1",            # no epoch
    "1788919258-chi1",  # the alias convention is upper case
    "1788919258-CHI",   # alias carries no instance number
    "1.3-1-X",
    "not-an-id",
    "",
]


@pytest.mark.parametrize(
    "match_id", PRODUCTION + LEGACY_12MAN + TEST_MODE + PREVIOUSLY_ACCEPTED)
def test_recognised_ids_are_accepted(match_id):
    assert MATCH_ID_RE.fullmatch(match_id)


@pytest.mark.parametrize("match_id", MALFORMED)
def test_malformed_ids_are_still_rejected(match_id):
    """Negative control: a pattern that accepted anything would satisfy the
    test above while saying nothing about any id."""
    assert MATCH_ID_RE.fullmatch(match_id) is None


def test_both_readers_share_one_definition():
    """These literals drifted apart once already; identity is what keeps a
    later fix from landing in only one of them."""
    assert match_readiness.MATCH_ID_RE is MATCH_ID_RE


def _shape_check(match_id: str) -> dict:
    checks = evaluate_quality(match_id, None, [], {})["checks"]
    return next(c for c in checks if c["code"] == "match_id_shape")


def test_a_production_id_passes_the_quality_check():
    assert _shape_check("1788919258-CHI1")["level"] == "PASS"


def test_an_unrecognised_id_still_fails_the_quality_check():
    """Positive control for the test above: the check can still say FAIL, so
    the PASS is a verdict rather than a check that stopped discriminating."""
    assert _shape_check("not-an-id")["level"] == "FAIL"
