"""Locating code by its text, without prose being able to answer for it.

A guard that finds a call site as the first line that *looks like* the call
reads a comment about the call as the call. On 2026-10-31 a note written above
an unrelated function became the match twice in a row -- the second time it was
the comment written to explain the first.

Both halves of that failure matter and only one of them is loud. A mislocated
anchor moves EARLIER, because prose about a thing is written above it, so an
`A before B` assertion still holds and a real reordering ships green; the other
side reports a comparison between two offsets that mean nothing.

The primitives, and the reason each exists.

`blank_comments` overwrites comment bytes with spaces rather than deleting them,
so every offset still indexes the original text and an existing slice keeps its
meaning. A stripper that shortens the text cannot be dropped under call sites
that slice by offset.

`AnchoredSource` is a `str` whose `index` refuses the two matches that make a
guard lie: one inside prose, and one of several. Which matches count depends on
what the anchor is. A definition, a directive or a section delimiter sits at
column 0 and prose about it does not, so `LINE_START` is the cheapest rule that
prose cannot satisfy -- and it keeps a deliberate `/**` delimiter usable, which
blanking would not. A mid-line expression inside a function body cannot use
column 0, so `CODE` excludes comments instead.

`call_sites` answers "where is this called" from the parse tree. Text cannot
tell a call from a sentence about one; `ast` has no way to represent the
sentence, which is the point of asking it instead.

The comment scanners keep string and char literals, because an anchor is
routinely a line of code containing one. Pawn escapes with `^` and the rest
with a backslash, and the flavour says which: a scanner that mishandled either
would blank from a quote to the end of the file and report every anchor absent.
"""

from __future__ import annotations

import ast
import io
import tokenize
from pathlib import Path

__all__ = [
    "MislocatedAnchor",
    "blank_comments",
    "AnchoredSource",
    "CODE",
    "LINE_START",
    "PAWN",
    "HASH",
    "PYTHON",
    "SQL",
    "pawn_source",
    "code_text",
    "call_sites",
    "sole_call_site",
    "assert_in_order",
]

PAWN = "pawn"
HASH = "hash"
PYTHON = "python"
SQL = "sql"

CODE = "code"
LINE_START = "line_start"

_COMMENT_OPENERS = ("//", "/*", "*", "#", "--")


class MislocatedAnchor(AssertionError):
    """An anchor prose could have answered for, or that several places match."""


def _blank(out: list[str], text: str, start: int, end: int) -> None:
    """Overwrite [start, end) with spaces, keeping newlines so lines still count."""
    for i in range(start, end):
        out[i] = "\n" if text[i] == "\n" else " "


def _past_literal(text: str, i: int, escape: str) -> int:
    quote = text[i]
    n = len(text)
    i += 1
    while i < n and text[i] != quote:
        if text[i] == escape:
            i += 2
            continue
        if text[i] == "\n":          # an unterminated literal ends with its line
            return i
        i += 1
    return min(i + 1, n)


def _blank_pawn(text: str) -> str:
    out = list(text)
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in "\"'":
            i = _past_literal(text, i, "^")
            continue
        if text.startswith("//", i):
            end = text.find("\n", i)
            end = n if end < 0 else end
            _blank(out, text, i, end)
            i = end
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            end = n if end < 0 else end + 2
            _blank(out, text, i, end)
            i = end
            continue
        i += 1
    return "".join(out)


def _blank_hash(text: str) -> str:
    """`#` to end of line, but only where `#` starts a comment.

    YAML, shell, Dockerfile and Python all require a line start or preceding
    whitespace, so `a#b` is a value and not a comment in every one of them.
    """
    out = list(text)
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in "\"'":
            i = _past_literal(text, i, "\\")
            continue
        if ch == "#" and (i == 0 or text[i - 1] in " \t\n"):
            end = text.find("\n", i)
            end = n if end < 0 else end
            _blank(out, text, i, end)
            i = end
            continue
        i += 1
    return "".join(out)


def _line_starts(text: str) -> list[int]:
    offsets, pos = [0], 0
    for line in text.splitlines(keepends=True):
        pos += len(line)
        offsets.append(pos)
    return offsets


def _blank_python(text: str) -> str:
    """Blank `#` comments and docstrings; leave every other literal alone.

    A docstring is prose wearing a literal's syntax and `inspect.getsource`
    hands it back with the code, so it carries exactly the hazard a comment
    does. Other literals stay: an anchor is commonly a line of code containing
    one.
    """
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # A fragment that will not tokenise still gets the comment pass;
        # refusing here would turn a guard over a snippet into a tooling error.
        return _blank_hash(text)

    out = list(text)
    starts = _line_starts(text)

    def offset(row: int, col: int) -> int:
        return starts[row - 1] + col

    significant = [t for t in tokens
                   if t.type not in (tokenize.NL, tokenize.COMMENT,
                                     tokenize.ENCODING, tokenize.ENDMARKER)]
    for tok in tokens:
        if tok.type == tokenize.COMMENT:
            _blank(out, text, offset(*tok.start), offset(*tok.end))

    # A docstring is a string that IS a whole statement: nothing but a newline
    # or a block boundary before it, and a newline straight after.
    openers = (None, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT)
    for idx, tok in enumerate(significant):
        if tok.type != tokenize.STRING:
            continue
        before = significant[idx - 1].type if idx else None
        after = significant[idx + 1].type if idx + 1 < len(significant) else None
        if before in openers and after == tokenize.NEWLINE:
            _blank(out, text, offset(*tok.start), offset(*tok.end))
    return "".join(out)


def _past_sql_literal(text: str, i: int) -> int:
    """Past a `'`, `"` or backtick run; a backtick identifier has no escapes.

    Doubling needs no case of its own, which is measured rather than assumed:
    `''` is two boundaries, so ending at the first and reopening at the second
    covers exactly the same span as reading it as one escaped quote. A branch
    for it survived every mutation and a 60,000-string fuzz found no input
    where it changed the blanking, so it is not here.
    """
    quote = text[i]
    n = len(text)
    i += 1
    while i < n:
        if text[i] == "\\" and quote != "`":
            i += 2
            continue
        if text[i] == quote:
            return i + 1
        i += 1
    return n


def _blank_sql(text: str) -> str:
    """MySQL comments blanked: `--` to end of line, `#` to end of line, `/*...*/`.

    MySQL's own rules, not a generic SQL's, because every statement a guard
    here reads is built for MySQL: `--` needs whitespace after it, so `a--b`
    is arithmetic, while `#` does not, so `SELECT 1#x` is a comment. An
    optimizer hint is a comment to this scanner, which is the loud direction:
    an anchor inside one is reported ABSENT rather than matched.

    Literals are skipped whole, because `-- `, `#` and `/*` inside one are
    data: a scanner that read them as comments would blank a selected value
    and report an anchor naming it absent.
    """
    out = list(text)
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in "'\"`":
            i = _past_sql_literal(text, i)
            continue
        if ch == "#" or (text.startswith("--", i)
                         and (i + 2 >= n or text[i + 2] in " \t\r\n")):
            end = text.find("\n", i)
            end = n if end < 0 else end
            _blank(out, text, i, end)
            i = end
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            end = n if end < 0 else end + 2
            _blank(out, text, i, end)
            i = end
            continue
        i += 1
    return "".join(out)


_BLANKERS = {PAWN: _blank_pawn, HASH: _blank_hash, PYTHON: _blank_python,
             SQL: _blank_sql}


def blank_comments(text: str, flavour: str = PAWN) -> str:
    """Comment bytes replaced by spaces, so every offset still means what it did."""
    if flavour not in _BLANKERS:
        raise ValueError(f"flavour must be one of {sorted(_BLANKERS)}, got {flavour!r}")
    blanked = _BLANKERS[flavour](text)
    assert len(blanked) == len(text), "blanking must not move any offset"
    return blanked


class AnchoredSource(str):
    """Source text whose `index` prose cannot answer for.

    An unbounded search must match exactly one place, so a guard that slices or
    orders by anchor fails as a mislocation or as an ambiguity instead of
    comparing offsets that mean nothing. Take a function body with `body()`
    rather than by `[a:b]`, which hands back a bare `str` and puts every
    assertion inside that body back on raw text.
    """

    def __new__(cls, text: str, rule: str = CODE, flavour: str = PAWN,
                origin: str = "<source>"):
        if rule not in (CODE, LINE_START):
            raise ValueError(f"rule must be {CODE!r} or {LINE_START!r}, got {rule!r}")
        self = super().__new__(cls, text)
        self._blanked = blank_comments(str(text), flavour)
        self._rule = rule
        self._flavour = flavour
        self._origin = origin
        return self

    @property
    def code_only(self) -> str:
        """The same text, comments blanked, for a membership assertion."""
        return self._blanked

    def body(self, opening: str, closing: str) -> "AnchoredSource":
        """The text from a unique `opening` anchor up to the next `closing` one.

        Guarded in its own right, under `CODE`: what a caller looks for inside a
        function body is a mid-line expression, which cannot use column 0 and so
        needs comments excluded instead. Returning a plain `str` here is what
        leaves every in-body ordering assertion back on raw text.
        """
        first = self.index(opening)
        text = str(self)[first:self.index(closing, first + len(opening))]
        return AnchoredSource(text, CODE, self._flavour, f"{self._origin}:{opening}")

    def _outside_comments(self, sub: str) -> list[int]:
        raw, blanked = str(self), self._blanked
        deliberate = sub.lstrip().startswith(_COMMENT_OPENERS)
        hits, i = [], raw.find(sub)
        while i != -1:
            if deliberate or blanked[i:i + len(sub)] == sub:
                hits.append(i)
            i = raw.find(sub, i + 1)
        return hits

    def _candidates(self, sub: str) -> list[int]:
        hits = self._outside_comments(sub)
        if self._rule == LINE_START:
            raw = str(self)
            hits = [i for i in hits if i == 0 or raw[i - 1] == "\n"]
        return hits

    def occurrences(self, sub: str) -> list[int]:
        """Every code match, for the case where several are there on purpose.

        The count is the caller's to assert. `index` refuses a plural anchor
        because a guard that silently takes the first is making a claim about
        one of them while reading like a claim about all.
        """
        return self._candidates(sub)

    def _locate(self, sub: str, start):
        if not sub:
            raise ValueError("an empty anchor matches everywhere")
        hits = self._candidates(sub)
        if not hits:
            elsewhere = str(self).count(sub)
            if elsewhere:
                where = ("inside a comment" if self._rule == CODE
                         else "away from the start of a line")
                raise MislocatedAnchor(
                    f"{self._origin}: anchor {sub!r} occurs {elsewhere} time(s) and "
                    f"every one of them is {where}. This is a MISLOCATION, not a "
                    "finding about the code: a guard matching here would be reading "
                    "prose about the thing it guards."
                )
            raise MislocatedAnchor(
                f"{self._origin}: anchor {sub!r} does not occur at all, in code or "
                "in prose, so the guard is looking for something that is not there."
            )
        if start is None:
            if len(hits) > 1:
                lines = [str(self).count("\n", 0, h) + 1 for h in hits]
                raise MislocatedAnchor(
                    f"{self._origin}: anchor {sub!r} matches {len(hits)} places "
                    f"(lines {lines}); a slice or an ordering taken from the first "
                    "is not the one you named. Anchor it uniquely, or bound the "
                    "search with an explicit start offset."
                )
            return hits[0]
        after = [h for h in hits if h >= start]
        if not after:
            raise MislocatedAnchor(
                f"{self._origin}: anchor {sub!r} matches {len(hits)} place(s), none "
                f"of them at or after offset {start}."
            )
        return after[0]

    def index(self, sub, start=None, end=None):
        if end is not None:
            raise TypeError("AnchoredSource.index takes no end bound; slice first")
        return self._locate(sub, start)

    def find(self, sub, start=None, end=None):
        """`-1` only for a true absence; prose and ambiguity still refuse."""
        if end is not None:
            raise TypeError("AnchoredSource.find takes no end bound; slice first")
        if not self._candidates(sub) and str(self).count(sub) == 0:
            return -1
        return self._locate(sub, start)

    def __contains__(self, sub) -> bool:
        """Membership in the code, so a comment cannot satisfy an assertion.

        Comment exclusion only, whatever the locating rule: `X in source` asks
        whether the code does X, and most of what code does is mid-line.
        """
        return bool(self._outside_comments(str(sub)))


def pawn_source(path, rule: str = LINE_START) -> AnchoredSource:
    """A `.sma` whose definition, directive and delimiter anchors sit at column 0."""
    path = Path(path)
    return AnchoredSource(path.read_text(encoding="utf-8", errors="replace"),
                          rule=rule, flavour=PAWN, origin=path.name)


def code_text(text: str, flavour: str = PYTHON, origin: str = "<source>") -> AnchoredSource:
    """Text whose anchors are mid-line expressions, so comments are excluded."""
    return AnchoredSource(text, rule=CODE, flavour=flavour, origin=origin)


def call_sites(source: str, name: str) -> list[tuple[int, int]]:
    """`(line, column)` of every call to `name`, from the parse tree.

    Matches a bare `name(...)` and an attribute `anything.name(...)`.
    """
    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        called = (func.id if isinstance(func, ast.Name)
                  else func.attr if isinstance(func, ast.Attribute) else None)
        if called == name:
            found.append((node.lineno, node.col_offset))
    return sorted(found)


def sole_call_site(source: str, name: str, origin: str = "<source>") -> tuple[int, int]:
    """The one call to `name`, or a refusal saying which way it went wrong."""
    sites = call_sites(source, name)
    if not sites:
        raise MislocatedAnchor(
            f"{origin}: the parse tree holds no call to {name}(). If the text "
            "mentions it, what it holds is a sentence about the call."
        )
    if len(sites) > 1:
        raise MislocatedAnchor(
            f"{origin}: {name}() is called at lines {[ln for ln, _ in sites]}, so a "
            "guard reasoning about 'the' call site cannot say which one it means."
        )
    return sites[0]


def assert_in_order(source: AnchoredSource, *anchors: str) -> None:
    """Each anchor appears before the next, every one located uniquely.

    The uniqueness is the point: an ordering assertion whose first anchor can
    slide earlier into a comment holds whatever the code does.
    """
    if len(anchors) < 2:
        raise ValueError("ordering needs at least two anchors")
    placed = [(source.index(a), a) for a in anchors]
    for (left, a), (right, b) in zip(placed, placed[1:]):
        if left >= right:
            lines = (str(source).count("\n", 0, left) + 1,
                     str(source).count("\n", 0, right) + 1)
            raise AssertionError(
                f"{a!r} (line {lines[0]}) must come before {b!r} (line {lines[1]}), "
                "and does not. Both anchors were located uniquely, so this is the "
                "order of the code and not a mislocation."
            )
