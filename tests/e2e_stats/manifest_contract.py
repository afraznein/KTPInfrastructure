"""Bind this harness's `KTP_CAPTURE_MANIFEST` grammar to the producer emitting it.

Three times a capture contract widened in KTPAMXX and a reader here did not
follow. `move` (2026-09-29) and `aim_vis` (2026-10-05) were event types, and
both were "fixed" by de-duplicating a list. Schema 26's `(sv_maxunlag "%.3f")`
is a manifest FIELD, and that is the worse shape: `_MANIFEST_RE` in
`break_scenarios` is an ordered positional grammar, so an inserted field makes
it match **zero** lines rather than ignore one. It matched 0 of 46 manifest
lines in run 37621405799, `begin_series` aborted `current_manifest_missing`,
and three scenarios that name nothing about manifests failed downstream of it.

Both earlier class fixes restated the contract in a second place, which is the
thing that keeps failing. This module restates nothing. It reads the producer's
own format string, renders a line from it, and asks a reader to match that
line. The authority is `plugins/dod/ktp_stats_capture.inc` at the amxx sha
under test, which `ArtifactSet.collect()` already extracts -- so there is no
reference copy here to go stale.

A field the producer adds fails CLOSED and by name: `render()` has no sample
value for it and says so, instead of inventing one the reader might accept.
"""

from __future__ import annotations

import re

MARKER = "KTP_CAPTURE_MANIFEST"

ENGINE_LOG_STAMP = "L 10/07/2026 - 12:34:56: "


class ManifestContractError(RuntimeError):
    """The producer's manifest grammar and a reader of it have diverged."""


# A Pawn string literal escapes its quotes as `^"`, so the alternation has to
# consume that pair before `[^"]` stalls on the quote inside it. The trailing
# ` \(` is load-bearing: without it the marker prefix-matches a LONGER name, so
# renaming it to `KTP_CAPTURE_MANIFEST2` still extracted a format string and the
# failure blamed field order. Anchored, a rename reads as "found 0".
_PAWN_LITERAL = re.compile(r'"(' + MARKER + r' \((?:\^"|[^"])*)"')

# Each manifest field is `(name "value")`, where value is a printf conversion
# for a real field or a fixed word for a self-describing one (`producer`,
# `map_revision_algorithm`).
_PRODUCER_FIELD = re.compile(r'\((?P<name>[a-z_][a-z0-9_]*) "(?P<spec>[^"]*)"\)')

# The same shape as it appears in a reader's PATTERN SOURCE, where the paren is
# escaped. Deriving the reader's field order from its own pattern is what lets a
# mismatch name the field instead of just saying "no match".
_READER_FIELD = re.compile(r'\\\((?P<name>[a-z_][a-z0-9_]*) "')

# Rendering values, taken from real manifest lines in run 37621405799. This is a
# value corpus, NOT a copy of the grammar: order, field names and conversions all
# come from the producer. A field missing here raises, which is the whole point --
# a widened manifest stops the lane with the new field's name in the message.
SAMPLES = {
    "matchid": "1791376597-TEST",
    "half": "1",
    "map": "dod_anzio",
    "producer_version": "1.27.1",
    "schema": "26",
    "capabilities": (
        "frag_context,damage,position,assist,life,break,flag_state,"
        "flag_position,objective_attempt,team_membership,grenade_entity,shot,"
        "score,duel,player_state,grenade_throw,position_state,map_revision,"
        "sequence,health,move"
    ),
    "position_interval": "2.0",
    "buffer_entries": "128",
    "life_buffer_entries": "64",
    "map_revision": "9663b42b1721147a45e8a489019e6e732d39347cfcd6b48976539cd26a254cfe",
    "sv_maxunlag": "0.499",
    "sequence": "1",
    "event_epoch": "1791376612",
}


def extract_format_string(source: str) -> str:
    """The producer's manifest format string, un-escaped from its Pawn literal.

    Raises unless exactly one is present. Zero means the marker was renamed and
    every grammar check downstream would otherwise pass by vacuum; more than one
    means there are two producers and this check covers an arbitrary one.
    """
    found = {match.group(1) for match in _PAWN_LITERAL.finditer(source)}
    if len(found) != 1:
        raise ManifestContractError(
            f"expected exactly 1 distinct {MARKER} format string in the "
            f"producer source, found {len(found)}"
        )
    fmt = found.pop().replace('^"', '"')
    if "^" in fmt:
        raise ManifestContractError(
            f"{MARKER} format string carries an unhandled Pawn escape: {fmt!r}"
        )
    return fmt


def producer_fields(fmt: str) -> tuple[tuple[str, str], ...]:
    """Ordered `(name, spec)` pairs, where spec is a conversion or a fixed word."""
    return tuple(
        (match.group("name"), match.group("spec"))
        for match in _PRODUCER_FIELD.finditer(fmt)
    )


def reader_fields(pattern: str) -> tuple[str, ...]:
    """Ordered field names a reader's pattern source names."""
    return tuple(match.group("name") for match in _READER_FIELD.finditer(pattern))


def render(fmt: str) -> str:
    """The producer's format string with a sample substituted per field.

    A conversion whose sample cannot be read back as its own type is as much a
    defect as a missing one: `map_revision` moving from `%s` to `%d` would leave
    the reader's `[0-9a-f]{64}` unsatisfiable, and silently rendering a number
    would hide that.
    """
    def one(match: re.Match) -> str:
        name, spec = match.group("name"), match.group("spec")
        if "%" not in spec:
            return match.group(0)
        if name not in SAMPLES:
            raise ManifestContractError(
                f'{MARKER} field (name "{name}", conversion "{spec}") has no '
                f"sample value in manifest_contract.SAMPLES. The producer has "
                f"widened the manifest: add a sample, then widen every reader "
                f"of it -- see this module's docstring."
            )
        value = SAMPLES[name]
        try:
            if spec.endswith("d"):
                int(value)
            elif spec.endswith("f"):
                float(value)
        except ValueError as exc:
            raise ManifestContractError(
                f'{MARKER} field (name "{name}") changed conversion to "{spec}", '
                f"which its sample {value!r} is not. A reader constraining this "
                f"field to the old type can no longer be satisfied."
            ) from exc
        return f'({name} "{value}")'

    return _PRODUCER_FIELD.sub(one, fmt)


def render_log_line(fmt: str, *, stamp: str = ENGINE_LOG_STAMP) -> str:
    """`render()` behind the engine log prefix every reader anchors on."""
    return stamp + render(fmt)


def assert_reader_accepts(source: str, reader: re.Pattern, *, reader_name: str) -> None:
    """Fail unless `reader` matches a line rendered from the producer's own format.

    Behavioural on purpose. Comparing field-name lists would miss a conversion
    change (`%.1f` to `%s` on `position_interval`), so the match is the gate and
    the name lists only make the failure legible.
    """
    fmt = extract_format_string(source)
    line = render_log_line(fmt)
    if reader.search(line):
        return

    produced = [name for name, _ in producer_fields(fmt)]
    read = list(reader_fields(reader.pattern))
    extra = [name for name in produced if name not in read]
    missing = [name for name in read if name not in produced]
    detail = []
    if extra:
        detail.append(f"producer emits but {reader_name} does not accept: {extra}")
    if missing:
        detail.append(f"{reader_name} requires but producer no longer emits: {missing}")
    if not detail:
        detail.append(
            f"field names agree, so a conversion or the field ORDER changed: "
            f"producer order {produced}, {reader_name} order {read}"
        )
    raise ManifestContractError(
        f"{reader_name} matches none of the producer's {MARKER} lines. "
        + "; ".join(detail)
        + f". Rendered line was: {line!r}"
    )
