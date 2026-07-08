"""Parsers for `amx modules` and `amx plugins` rcon output.

Format strings taken verbatim from KTPAMXX `amxmodx/srvcmd.cpp`:

  modules: " [%2d] %-23.22s %-11.10s %-20.19s %-11.10s\n"
              index name(22)         version(10) author(19)         status(10)

  plugins: " [%3d] %-3i %-23.22s %-11.10s %-17.16s %-32.31s %-12.11s %-9.8s\n"
              index id   name(22)         version(10) author(16)
              url(31)                          file(11)      status(8)

Notable: AMXX truncates strings to the `.MAX` precision (e.g. `%-12.11s` =
max 11 chars). Long names like `KTPMatchHandler.amxx` (20) become `KTPMatchHan`
in the output, so callers must do prefix-or-substring matching, not exact.

We parse by fixed column offsets — runs of 1+ space cannot be reliably split
when columns are at max width.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Row prefix: ` [<padded-num>]` followed by a space.
_ROW_RE = re.compile(r"^\s*\[\s*\d+\]\s")


@dataclass(frozen=True)
class ModuleRow:
    index: int
    name: str
    version: str
    author: str
    status: str

    @property
    def is_running(self) -> bool:
        # AMXX reports `running` for JIT-compiled plugins and `debug` for
        # plugins loaded with the `debug` flag (interpreted VM, no JIT).
        # Both mean "loaded and active" — the assertion's intent is
        # "did the plugin load successfully?", not "is it JIT-compiled?".
        # Failure states are `bad load`, `error`, `paused`, `stopped`.
        return self.status.lower() in ("running", "debug")


@dataclass(frozen=True)
class PluginRow:
    index: int
    plugin_id: str
    name: str       # title (truncated to 22 chars)
    version: str    # truncated to 10
    author: str     # truncated to 16
    url: str        # truncated to 31
    filename: str   # truncated to 11 — beware
    status: str     # truncated to 8

    @property
    def is_running(self) -> bool:
        # AMXX reports `running` for JIT-compiled plugins and `debug` for
        # plugins loaded with the `debug` flag (interpreted VM, no JIT).
        # Both mean "loaded and active" — the assertion's intent is
        # "did the plugin load successfully?", not "is it JIT-compiled?".
        # Failure states are `bad load`, `error`, `paused`, `stopped`.
        return self.status.lower() in ("running", "debug")


def _row_index(line: str) -> int | None:
    """Extract the index from a ` [ N]` prefix, or return None for non-rows."""
    m = re.match(r"^\s*\[\s*(\d+)\]", line)
    return int(m.group(1)) if m else None


def parse_modules(output: str) -> list[ModuleRow]:
    """Parse `amx modules` output.

    Format:  ` [%2d] %-23.22s %-11.10s %-20.19s %-11.10s`
    Layout:  '<sp>[NN] NAME(23) VER(11) AUTHOR(20) STATUS(11)'

    Column starts (0-indexed) for KTPAMXX's specific spacing:
        ` [NN]` = positions 0..5  (literal space, [, 2-digit num, ])
        ` `     = position 5      (space after `]`)
        name    = positions 6..28  (23 wide)
        space   = position 29
        version = positions 30..40 (11 wide)
        space   = position 41
        author  = positions 42..61 (20 wide)
        space   = position 62
        status  = positions 63..73 (11 wide)
    """
    rows: list[ModuleRow] = []
    for line in output.splitlines():
        if not _ROW_RE.match(line):
            continue
        idx = _row_index(line)
        if idx is None:
            continue
        # Skip past the `[NN]` prefix to the first column.
        start = line.index("]") + 2  # `]` then space
        body = line[start:]
        # Defensive splitting: try fixed widths first, fall back to multi-space
        # split if line was hand-edited or AMXX changes format.
        cols = _slice_fixed(body, [23, 11, 20, 11])
        if cols is None or len(cols) < 4:
            cols = re.split(r"\s{2,}", body.strip())
            if len(cols) < 4:
                continue
        name, version, author, status = (c.strip() for c in cols[:4])
        rows.append(ModuleRow(idx, name, version, author, status))
    return rows


def parse_plugins(output: str) -> list[PluginRow]:
    """Parse `amx plugins` output.

    Format: ` [%3d] %-3i %-23.22s %-11.10s %-17.16s %-32.31s %-12.11s %-9.8s`

    After the leading ` [NNN]` (5 chars + leading space + trailing space):
        plugin_id = 3 wide
        name      = 23 wide (title, max 22)
        version   = 11 wide (max 10)
        author    = 17 wide (max 16)
        url       = 32 wide (max 31)
        filename  = 12 wide (max 11)
        status    = 9 wide (max 8)
    """
    rows: list[PluginRow] = []
    for line in output.splitlines():
        if not _ROW_RE.match(line):
            continue
        idx = _row_index(line)
        if idx is None:
            continue
        start = line.index("]") + 2
        body = line[start:]
        cols = _slice_fixed(body, [3, 23, 11, 17, 32, 12, 9])
        if cols is None or len(cols) < 7:
            cols = re.split(r"\s{2,}", body.strip())
            if len(cols) < 6:
                continue
            # Multi-space fallback: 6 cols (id may be merged into name) — guess.
            cols = cols + [""] * (7 - len(cols))
        plugin_id, name, version, author, url, filename, status = (
            c.strip() for c in cols[:7]
        )
        rows.append(PluginRow(idx, plugin_id, name, version, author, url, filename, status))
    return rows


def _slice_fixed(body: str, widths: list[int]) -> list[str] | None:
    """Slice `body` into columns of the given widths.

    The format strings always include exactly one trailing space inside each
    field's padding when the field is at max length, plus one literal space
    between columns. So consecutive columns are separated by 0..N spaces.

    Returns None if the line is too short for the declared widths — caller
    falls back to whitespace-split.
    """
    cols: list[str] = []
    pos = 0
    for w in widths:
        if pos > len(body):
            return None
        # Each field is `w` chars wide, then a single space separator (except
        # for the last field).
        chunk = body[pos:pos + w]
        cols.append(chunk)
        pos += w + 1  # advance past field + the literal-space delimiter
    return cols


def normalise_module_name(name: str) -> str:
    """Canonicalise an AMXX module identity across filename / display-name flavours.

    The same module shows up as different strings in different places:
      filename: `amxxcurl_ktp_i386.so`
      bare:     `amxxcurl`
      AMXX display name (rcon output): `KTP CURL AMXX`

    All three should map to the same key `curl` so callers can pass any
    of them to assert_modules_loaded(expected=...). The strip rules:

    1. Lowercase
    2. Drop platform/build suffixes: `_i386.so`, `_amd64.so`, `.so`, `.dll`,
       `_i386`, `_amd64`, `_ktp`
    3. Tokenise on whitespace / punctuation
    4. Within each token, strip `amxx` and `ktp` substrings (these are the
       "vendor wrapper" tokens that AMXX uses in display names but aren't
       part of the underlying module identity)
    5. Concatenate the surviving tokens
    """
    import re
    n = name.lower()
    for suffix in ("_i386.so", "_amd64.so", ".so", ".dll", "_i386", "_amd64", "_ktp"):
        if n.endswith(suffix):
            n = n[: -len(suffix)]
    tokens = re.split(r'[\s\-_/]+', n)
    cleaned = []
    for t in tokens:
        # Strip 'amxx' and 'ktp' substrings inside the token — handles
        # 'amxxcurl' → 'curl' and 'curl' → 'curl' (idempotent).
        for noise in ("amxx", "ktp"):
            t = t.replace(noise, "")
        if t:
            cleaned.append(t)
    return "".join(cleaned)


def normalise_plugin_name(name: str) -> str:
    """Match `KTPMatchHandler.amxx`, `KTPMatchHandler`, and the display name
    `KTP Match Handler` against the same key. Returns lowercase, no spaces,
    no underscores, no .amxx extension (whole or truncation-sliced)."""
    n = name.lower()
    if n.endswith(".amxx"):
        n = n[: -len(".amxx")]
    else:
        # AMXX's 11-char filename truncation can slice the extension mid-way
        # (`ktp_file.am`). Without stripping the fragment, a short plugin name
        # normalises under the 8-char overlap floor while its truncated row
        # keeps the fragment — unmatchable from either direction.
        for frag in (".amx", ".am", ".a", "."):
            if n.endswith(frag):
                n = n[: -len(frag)]
                break
    return n.replace(" ", "").replace("_", "")


def matches_truncated(expected: str, actual: str) -> bool:
    """True if `actual` could be a truncation of `expected` (or vice versa).

    AMXX's `%-12.11s` truncates filenames to 11 chars, so the plugin output
    `KTPMatchHan` is the truncation of either `KTPMatchHandler.amxx` (the
    file) or `KTPMatchHandler` (no extension). Either side may be the
    truncated one depending on which way you got the strings.
    """
    e = normalise_plugin_name(expected)
    a = normalise_plugin_name(actual)
    if not e or not a:
        return False
    if e == a:
        return True
    # Truncation match: the SHORTER string must be a prefix of the longer one
    # over its FULL length (a truncation never has extra trailing chars). The
    # old cap of 8 compared only the first 8 chars of two long names, so any
    # 8-char-shared-prefix pair "matched" — KTPGrenadeLoadout vs KTPGrenadeD
    # (both `ktpgrena...`) let assert-plugins pass off the wrong plugin's row.
    # AMXX never emits fewer than 8 visible chars for a non-empty name, so a
    # candidate truncation shorter than that is rejected.
    min_overlap = min(len(e), len(a))
    if min_overlap < 8:
        return False
    return e[:min_overlap] == a[:min_overlap]
