"""Parse KTPMatchHandler's match state back out of a server hostname.

`update_server_hostname()` publishes `{base} - {TYPE} - {STATE}`, which A2S
returns for free -- so live match state is available without touching a game
server or a plugin API.

The parse runs RIGHT TO LEFT and only on known tokens. Splitting on " - "
left-to-right looks obvious and is wrong: the base hostname already contains the
separator ("KTP - Atlanta 1"), and so does "LIVE - 2ND HALF". Anything that does
not match a known token is left alone as a plain hostname -- a server that has
never hosted a match must render as itself, never as a parse error.
"""

from __future__ import annotations

import re
from typing import NamedTuple

SEP = " - "

# Longest first: "KTP OT" must win over "KTP", "DRAFT OT" over "DRAFT".
MATCH_TYPES = ("KTP OT", "DRAFT OT", "12MAN", "SCRIM", "DRAFT", "MATCH", "KTP")

# Longest first, for the same reason: "LIVE - 1ST HALF" must win over "LIVE".
FIXED_STATES = ("LIVE - 1ST HALF", "LIVE - 2ND HALF", "PENDING", "PAUSED", "LIVE")
_OT_STATE = re.compile(r"^LIVE - OT(\d+)$")


class ServerName(NamedTuple):
    base: str
    match_type: str | None
    state: str | None

    @property
    def in_match(self) -> bool:
        return self.match_type is not None

    @property
    def is_live(self) -> bool:
        return bool(self.state and self.state.startswith("LIVE"))


def _split_suffix(text: str, token: str) -> str | None:
    """`text` minus a trailing SEP+token, or None if it does not end that way."""
    suffix = SEP + token
    return text[: -len(suffix)] if text.endswith(suffix) else None


def _match_state(text: str) -> tuple[str, str] | None:
    for state in FIXED_STATES:
        rest = _split_suffix(text, state)
        if rest is not None:
            return rest, state
    # LIVE - OT<n> is open-ended, so it cannot live in the fixed tuple.
    head, sep, tail = text.rpartition(SEP)
    if sep and _OT_STATE.match(f"LIVE - {tail}") and head.endswith(f"{SEP}LIVE"):
        return head[: -len(f"{SEP}LIVE")], f"LIVE - {tail}"
    return None


def parse(hostname: str) -> ServerName:
    """Split a hostname into base / match type / state, tolerating anything odd."""
    text = (hostname or "").strip()
    if not text:
        return ServerName("", None, None)

    # Bare suffixes: these carry no "<type> - <state>" grammar, so the loop
    # below would strip the state and then find no match type in front of it
    # and give up. PRACTICE comes from KTPPracticeMode, the other two from
    # KTPMatchHandler. Adding them to FIXED_STATES does NOT work -- verified.
    for bare in ("PRACTICE", "WARMUP", "PRE-MATCH"):
        bare_base = _split_suffix(text, bare)
        if bare_base:
            return ServerName(bare_base, bare, bare)

    found = _match_state(text)
    if not found:
        return ServerName(text, None, None)
    rest, state = found

    for mtype in MATCH_TYPES:
        base = _split_suffix(rest, mtype)
        if base is not None:
            # A state with no recognised type in front of it is not our format.
            return ServerName(base, mtype, state) if base else ServerName(text, None, None)
    return ServerName(text, None, None)
