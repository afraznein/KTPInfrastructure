#!/usr/bin/env python3
"""Shape classification and key/value parsing for KTP config text.

WHY THIS IS A MODULE AND NOT TWO COPIES. `tests/config_parse/parsers.py` already
parsed these files from a Path for the Tier-1 gate, and
`audit-config-key-drift.py` needs the same parse applied to text pulled off an
instance over SSH. Two parsers would be two definitions of "what a key is", free
to disagree about the file whose key loss started all this -- so the text form
lives here and both callers use it.

THREE FLAVOURS, CLASSIFIED RATHER THAN GUESSED

    kv      `key = value`, `;` comments.      discord.ini, ktp.ini, ktp_file.ini
    cvar    `cvar value`, `//` comments.      dodserver.cfg, configs/ktp_*.cfg
    list    one bare token per line.          extensions.ini, modules.ini

`list` is not a special case in the comparison: a line IS a key with an empty
value, which is exactly the semantics wanted -- a plugin that vanished from
plugins.ini reads as a missing key, named.

A file whose content lines DISAGREE about the flavour -- some with `=`, some
without -- is `mixed`, and the caller must treat that as "could not check", not
as either flavour. Picking one would silently invent keys: the cvar reader
applied to `discord_auth_secret = x` yields a key whose value starts with `=`,
compares equal to nothing, and reports drift that is an artifact of the reader.
This is the one place where refusing to answer is the only honest answer.

COMMENT STRIPPING IS QUOTE-AWARE, AND THAT IS NOT FUSSINESS

The first run of this check against the live fleet reported `;` as a drifting
KEY in plugins.ini and `#` as one in 28 map configs, because a naive
`split(marker)[0]` had turned a trailing comment into a value and a full-line
comment into a key. Worse, it classified the SAME file as `cvar` at the source
and `list` on the instance -- `admin.amxx<TAB>; admin base` has two tokens only
if the comment counts as one. A comment read as a key is a finding that cannot
be fixed and cannot be true, and three of them hid two armed hazards that were
real. So:

  * A line whose first non-blank characters are `;`, `#` or `//` is dropped.
  * A marker later in the line starts a comment only when it is OUTSIDE double
    quotes AND preceded by whitespace. That keeps `hostname "KTP;1"` and the
    `//` in `https://relay/reply` intact, and still cuts `admin.amxx ; base`.

Stdlib only; no I/O beyond what the caller hands in.
"""

from __future__ import annotations

import re

KV, CVAR, LIST, MIXED, EMPTY = "kv", "cvar", "list", "mixed", "empty"

_CVAR_LINE_RE = re.compile(r"^\s*(\S+)(?:\s+(.*))?\s*$")

#: Every marker any KTP config flavour uses for a whole-line comment. Applied
#: regardless of flavour, because classification happens before the flavour is
#: known and a full-line comment is never content in any of them.
LINE_COMMENT_MARKERS = (";", "#", "//")

#: Trailing-comment markers. `#` is deliberately absent: it is a whole-line
#: marker in these files and appears mid-value in map and sprite names.
TRAILING_COMMENT_MARKERS = (";", "//")


def strip_comment(raw, markers=TRAILING_COMMENT_MARKERS):
    """The content half of one line, or "" if the line is a comment.

    Quote-aware and whitespace-anchored -- see the header for why both matter.
    """
    line = raw.strip()
    for marker in LINE_COMMENT_MARKERS:
        if line.startswith(marker):
            return ""
    in_quote = False
    index = 0
    while index < len(line):
        char = line[index]
        if char == '"':
            in_quote = not in_quote
            index += 1
            continue
        if not in_quote and index > 0 and line[index - 1].isspace():
            for marker in markers:
                if line.startswith(marker, index):
                    return line[:index].strip()
        index += 1
    return line.strip()


def content_lines(text, markers=TRAILING_COMMENT_MARKERS):
    """(line number, content) for every line that is not blank or a comment."""
    out = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = strip_comment(raw, markers)
        if line:
            out.append((lineno, line))
    return out


def classify(text):
    """Which flavour this text is, or MIXED / EMPTY."""
    lines = content_lines(text)
    if not lines:
        return EMPTY
    with_eq = sum(1 for _, line in lines if "=" in line)
    if with_eq == len(lines):
        return KV
    if with_eq:
        return MIXED
    # No `=` anywhere. A bare token per line is the list flavour; anything with
    # an argument is a cvar set. They parse identically here -- the distinction
    # is kept only because it is what a reader of the report needs to know.
    return LIST if all(len(line.split()) == 1 for _, line in lines) else CVAR


def parse_kv_text(text, label="<text>"):
    """`key = value`, keys lowercased, surrounding double quotes stripped.

    Raises ValueError on a line without `=` or on a duplicate key. A duplicate
    is an error rather than last-wins because these files are read by plugins
    that take the FIRST hit, so a silent last-wins here would compare a value
    the stack never uses.
    """
    out = {}
    for lineno, line in content_lines(text, markers=(";",)):
        if "=" not in line:
            raise ValueError("%s:%d: expected `key = value`, got %r" % (label, lineno, line))
        key, _, value = line.partition("=")
        key = key.strip().lower()
        value = value.strip()
        if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        if key in out:
            raise ValueError("%s:%d: duplicate key %r" % (label, lineno, key))
        out[key] = value
    return out


def parse_cvar_text(text, label="<text>"):
    """`cvar value`. A repeated cvar is POSITIONAL: `exec`, `exec#2`, `exec#3`.

    Deliberately not the last-wins collapse that `tests/config_parse/parsers.py`
    uses. That one answers "does this template set the required cvars", where
    only the effective value matters; this one answers "is every line mirrored",
    and a collapse there loses exactly the line someone deleted. A map config
    with three `exec` lines at the source and two on the fleet is a finding
    (`exec#3`), and last-wins reports it only if the SURVIVING one differs --
    which, for an append-only exec list, it usually does not. The existing test
    already had to assert that one on raw text to route around the collapse.

    A bare-token line yields an empty value, so the list flavour parses here too
    and a plugin that vanished from plugins.ini reads as a missing key, named.
    """
    out = {}
    seen = {}
    for lineno, line in content_lines(text):
        match = _CVAR_LINE_RE.match(line)
        if not match:
            raise ValueError("%s:%d: cannot parse %r" % (label, lineno, line))
        cvar, value = match.group(1).lower(), (match.group(2) or "").strip()
        if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
            value = value[1:-1]
        seen[cvar] = seen.get(cvar, 0) + 1
        out[cvar if seen[cvar] == 1 else "%s#%d" % (cvar, seen[cvar])] = value
    return out


def parse_text(text, label="<text>"):
    """(flavour, {key: value}), or (MIXED, None) which means "could not parse".

    EMPTY is NOT None. A comment-only or blank config parses to an empty key
    set, which is a real answer: compared against another empty set it agrees,
    and compared against a populated instance every one of that instance's keys
    is a `source-missing` finding. Returning None here instead would skip the
    comparison in precisely the direction that matters -- an emptied source file
    against a populated fleet is the 2026-08-19 revert taken to its limit.

    MIXED is the only unparsed outcome, and the caller must treat a None as
    "could not compare" rather than as a file with no drift.
    """
    flavour = classify(text)
    if flavour == MIXED:
        return flavour, None
    try:
        if flavour == KV:
            return flavour, parse_kv_text(text, label)
        return flavour, parse_cvar_text(text, label)
    except ValueError:
        return MIXED, None
