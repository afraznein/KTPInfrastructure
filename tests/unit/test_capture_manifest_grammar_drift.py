"""Drift guard for the KTP_CAPTURE_MANIFEST grammar, and for the guard itself.

A capture contract has widened ahead of a reader here three times: `move`
(2026-09-29), `aim_vis` (2026-10-05), and schema 26's `(sv_maxunlag "%.3f")`.
Both earlier class fixes restated the contract in a second place and the third
widening walked straight past them, because the duplication that mattered was a
positional regex rather than a list.

`tests/e2e_stats/manifest_contract.py` restates nothing: the producer's own
format string is the reference, and `ArtifactSet.collect()` checks it against
the extracted `.inc` at the amxx sha under test, so the authoritative leg cannot
go stale behind KTPAMXX.

What this file adds is the leg that runs on EVERY PR -- config-tests.yml runs
tests/unit/ while tests/e2e_stats/ runs only inside a Lane B job. It cannot see
today's producer (different repo, no network here), so it does not pretend to.
It guards the three things that are checkable offline:

  1. the extractor and renderer work, and can FAIL -- a guard never shown to
     fail is not a guard;
  2. `collect()` still calls the check, so the Lane B leg cannot be deleted or
     short-circuited without a PR-time failure. This is the part the two
     earlier class fixes lacked;
  3. the two-reader asymmetry is asserted, not folklore.

The format string below is an EXERCISE CORPUS, not the contract. Its being
out of date costs nothing and proves nothing -- freshness lives in `collect()`.
"""

from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tests.e2e_stats import artifacts, manifest_contract  # noqa: E402
from tests.e2e_stats.break_scenarios import _MANIFEST_RE  # noqa: E402
from tests.e2e_stats.log_invariants import (  # noqa: E402
    _ENGINE_CAPTURE_MANIFEST_RE,
)

# Verbatim from KTPAMXX plugins/dod/ktp_stats_capture.inc at 8a62fe1d (schema
# 26, stats_logging 1.27.0), wrapped as the producer writes it. A snapshot for
# exercising the machinery -- see the docstring.
PRODUCER_SNAPSHOT = (
    'server_print("KTP_CAPTURE_MANIFEST (matchid ^"%s^") (half ^"%d^") '
    '(map ^"%s^") (producer ^"stats_logging^") (producer_version ^"%s^") '
    '(schema ^"%d^") (capabilities ^"%s^") (position_interval ^"%.1f^") '
    '(buffer_entries ^"%d^") (life_buffer_entries ^"%d^") '
    '(map_revision_algorithm ^"sha256^") (map_revision ^"%s^") '
    '(sv_maxunlag ^"%.3f^") (sequence ^"%d^") (event_epoch ^"%d^")", foo);'
)

# One real manifest line from Lane B run 37621405799 (2026-10-07), the nightly
# whose artifact showed _MANIFEST_RE matching 0 of its 46 manifest lines. A
# live-data control: whatever the snapshot above says, the reader must accept
# what production actually emitted.
REAL_NIGHTLY_LINE = (
    'L 10/07/2026 - 12:29:57: KTP_CAPTURE_MANIFEST (matchid "1791376597-TEST") '
    '(half "1") (map "dod_anzio") (producer "stats_logging") '
    '(producer_version "1.27.1") (schema "26") (capabilities "frag_context,'
    'damage,position,assist,life,break,flag_state,flag_position,'
    'objective_attempt,team_membership,grenade_entity,shot,score,duel,'
    'player_state,grenade_throw,position_state,map_revision,sequence,health,'
    'move") (position_interval "2.0") (buffer_entries "128") '
    '(life_buffer_entries "64") (map_revision_algorithm "sha256") '
    '(map_revision "9663b42b1721147a45e8a489019e6e732d39347cfcd6b48976539'
    'cd26a254cfe") (sv_maxunlag "0.499") (sequence "1") '
    '(event_epoch "1791376612")'
)


def _widened(extra: str) -> str:
    """The snapshot with `extra` inserted where schema 26 inserted its field."""
    out = PRODUCER_SNAPSHOT.replace(
        '(sequence ^"%d^")', f'{extra} (sequence ^"%d^")', 1)
    assert out != PRODUCER_SNAPSHOT
    return out


# -- 1. the machinery works, and the corpus is not vacuous --------------------

def test_the_extractor_finds_something():
    """An extractor that matches nothing turns every check below into a pass."""
    fmt = manifest_contract.extract_format_string(PRODUCER_SNAPSHOT)
    fields = manifest_contract.producer_fields(fmt)
    assert len(fields) >= 15
    assert [name for name, _ in fields][:3] == ["matchid", "half", "map"]
    assert "^" not in fmt
    assert manifest_contract.reader_fields(_MANIFEST_RE.pattern)


def test_reader_field_order_is_derived_from_both_sides_not_restated():
    fmt = manifest_contract.extract_format_string(PRODUCER_SNAPSHOT)
    assert ([name for name, _ in manifest_contract.producer_fields(fmt)]
            == list(manifest_contract.reader_fields(_MANIFEST_RE.pattern)))


def test_rendered_line_reproduces_a_real_nightly_manifest_body():
    """The renderer is only evidence if its output is production-shaped."""
    rendered = manifest_contract.render_log_line(
        manifest_contract.extract_format_string(PRODUCER_SNAPSHOT))
    assert rendered.split(": ", 1)[1] == REAL_NIGHTLY_LINE.split(": ", 1)[1]


def test_the_positional_reader_accepts_the_snapshot_and_the_real_line():
    manifest_contract.assert_reader_accepts(
        PRODUCER_SNAPSHOT, _MANIFEST_RE, reader_name="_MANIFEST_RE")
    match = _MANIFEST_RE.search(REAL_NIGHTLY_LINE)
    assert match is not None
    assert match.group("sv_maxunlag") == "0.499"
    assert match.group("schema") == "26"
    assert match.group("sequence") == "1"


def test_an_older_amxx_ref_without_the_schema_26_field_still_binds():
    """`sv_maxunlag` is optional on purpose -- the lane also runs older refs.

    Asserted so a later tightening has to break a test that says why.
    """
    older = PRODUCER_SNAPSHOT.replace(' (sv_maxunlag ^"%.3f^")', "", 1)
    assert older != PRODUCER_SNAPSHOT
    manifest_contract.assert_reader_accepts(
        older, _MANIFEST_RE, reader_name="_MANIFEST_RE")


# -- 2. mutation: the guard can fail, by every route it has -------------------

def test_guard_fails_on_a_fourth_widening_and_names_the_field():
    with pytest.raises(manifest_contract.ManifestContractError) as exc:
        manifest_contract.assert_reader_accepts(
            _widened('(aim_vis_window ^"%.3f^")'),
            _MANIFEST_RE, reader_name="_MANIFEST_RE")
    assert "aim_vis_window" in str(exc.value)


def test_guard_fails_when_a_known_field_is_reordered():
    """Field names agreeing is not the grammar agreeing."""
    reordered = PRODUCER_SNAPSHOT.replace(
        '(sequence ^"%d^") (event_epoch ^"%d^")',
        '(event_epoch ^"%d^") (sequence ^"%d^")', 1)
    assert reordered != PRODUCER_SNAPSHOT
    with pytest.raises(manifest_contract.ManifestContractError) as exc:
        manifest_contract.assert_reader_accepts(
            reordered, _MANIFEST_RE, reader_name="_MANIFEST_RE")
    assert "ORDER" in str(exc.value)


def test_guard_fails_when_a_required_field_is_dropped():
    dropped = PRODUCER_SNAPSHOT.replace(' (buffer_entries ^"%d^")', "", 1)
    assert dropped != PRODUCER_SNAPSHOT
    with pytest.raises(manifest_contract.ManifestContractError) as exc:
        manifest_contract.assert_reader_accepts(
            dropped, _MANIFEST_RE, reader_name="_MANIFEST_RE")
    assert "buffer_entries" in str(exc.value)


def test_guard_fails_when_a_conversion_narrows_past_its_sample():
    narrowed = PRODUCER_SNAPSHOT.replace(
        '(map_revision ^"%s^")', '(map_revision ^"%d^")', 1)
    assert narrowed != PRODUCER_SNAPSHOT
    with pytest.raises(manifest_contract.ManifestContractError) as exc:
        manifest_contract.assert_reader_accepts(
            narrowed, _MANIFEST_RE, reader_name="_MANIFEST_RE")
    assert "map_revision" in str(exc.value)


@pytest.mark.parametrize("source, found", [
    ("stock ksc_init() {}", 0),
    # A renamed marker, which prefix-matches the old one. Anchoring the literal
    # on `MARKER + " ("` is what keeps this from extracting a format string and
    # then blaming field order for the mismatch.
    (PRODUCER_SNAPSHOT.replace("KTP_CAPTURE_MANIFEST", "KTP_CAPTURE_MANIFEST2"), 0),
    ('p("KTP_CAPTURE_MANIFEST (a ^"%s^")"); p("KTP_CAPTURE_MANIFEST (b ^"%d^")");', 2),
])
def test_extractor_refuses_zero_or_two_producers(source, found):
    """A renamed marker must not read as a contract nobody violates."""
    with pytest.raises(manifest_contract.ManifestContractError) as exc:
        manifest_contract.extract_format_string(source)
    assert f"found {found}" in str(exc.value)


# -- 3. the guard is wired in, and stays wired in -----------------------------

def test_collect_checks_the_grammar_against_the_extracted_producer():
    """Guards the guard.

    The two earlier class fixes were changelog entries with nothing holding them
    in place. This asserts the authoritative leg is still called, and called on
    the EXTRACTED `.inc` rather than on anything committed here.
    """
    source = inspect.getsource(artifacts.ArtifactSet.collect)
    assert "assert_capture_manifest_grammar(inst.plugin_inc)" in source
    assert (source.index("plugins/dod/ktp_stats_capture.inc")
            < source.index("assert_capture_manifest_grammar"))

    checker = inspect.getsource(artifacts.assert_capture_manifest_grammar)
    assert "_MANIFEST_RE" in checker
    assert "plugin_inc.read_text" in checker


def test_collect_refuses_a_widened_producer_as_a_fatal_build_error(tmp_path):
    """End to end on the real hook: a widened `.inc` must stop the bundle."""
    inc = tmp_path / "ktp_stats_capture.inc"
    inc.write_text(_widened('(aim_vis_window ^"%.3f^")'), encoding="utf-8")
    with pytest.raises(artifacts.BuildError) as exc:
        artifacts.assert_capture_manifest_grammar(inc)
    assert "capture manifest grammar drift" in str(exc.value)
    assert "aim_vis_window" in str(exc.value)

    inc.write_text(PRODUCER_SNAPSHOT, encoding="utf-8")
    artifacts.assert_capture_manifest_grammar(inc)


# -- 4. the two readers are asymmetric, and that is stated ---------------------

def test_the_prefix_only_reader_cannot_corroborate_the_positional_one():
    """A second reader agreeing is not corroboration when it is reading less.

    `log_invariants` matches the prefix and takes fields from `properties`, so a
    widened manifest leaves it green -- correct for its purpose, and exactly why
    nothing flagged schema 26. Asserted in both directions so the asymmetry is a
    measurement rather than a comment someone may later disbelieve.
    """
    fmt = manifest_contract.extract_format_string(PRODUCER_SNAPSHOT)
    good = manifest_contract.render_log_line(fmt)
    widened = manifest_contract.ENGINE_LOG_STAMP + re.sub(
        r'\(sequence "', '(aim_vis_window "0.250") (sequence "',
        manifest_contract.render(fmt), count=1)

    assert _ENGINE_CAPTURE_MANIFEST_RE.match(good)
    assert _ENGINE_CAPTURE_MANIFEST_RE.match(widened), (
        "log_invariants is prefix-only by design; tightening it here would "
        "remove the asymmetry this test exists to document")

    assert _MANIFEST_RE.search(good)
    assert not _MANIFEST_RE.search(widened), (
        "the positional reader is what a widening breaks -- if this passes, "
        "_MANIFEST_RE has been loosened and the drift guard is now decorative")
