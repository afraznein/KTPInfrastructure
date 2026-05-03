"""MatchDriver — typed wrapper around `amx_ktp_test_*` rcon commands.

Tests use the driver's methods (setup_match, advance_pending, advance_live,
end_match, reset, get_state, get_localinfo) rather than passing raw rcon
strings. Two reasons:

  1. Server-side error responses (`KTP_TEST_*: ERROR <reason>`) get
     surfaced as Python `MatchDriverError` exceptions with the reason in
     the message. Otherwise the test would silently pass an error string
     where it expected success output.
  2. The state-readback rcon prints one-line JSON with short keys
     (`mt`/`h`/`l`/`p`/`id`/`s1`/`s2`/`tb1`/`tb2`/`pn`/`c1`/`c2`/`rc`)
     to fit the console_print line cap. `get_state` parses + remaps to
     long names so test assertions read cleanly.

The wrapped rcons all live behind the test-mode build flag in
KTPMatchHandler 0.10.122; production builds compile the entire block
to zero bytes. See KTPMatchHandler/CHANGELOG.md § 0.10.122.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import IntEnum
from typing import Any


class MatchDriverError(RuntimeError):
    """Raised when a test-mode rcon returns a `KTP_TEST_*: ERROR <reason>`
    line. Wraps the reason verbatim so test failures surface the exact
    server-side state that rejected the call."""


class MatchType(IntEnum):
    """Mirror of KTPMatchHandler.sma's MatchType enum. Numeric values are
    the wire contract for `amx_ktp_test_setup_match <type>`; never reorder.
    """
    COMPETITIVE = 0
    SCRIM = 1
    TWELVE_MAN = 2
    DRAFT = 3
    KTP_OT = 4
    DRAFT_OT = 5


# State-readback JSON-key remapping. Long names are the test-facing API;
# short names are what the rcon emits (kept short to fit console_print's
# ~256-char line cap).
_STATE_KEY_MAP = {
    "mt":  "match_type",
    "h":   "current_half",
    "l":   "match_live",
    "p":   "is_paused",
    "id":  "match_id",
    "s1":  "score_team1",
    "s2":  "score_team2",
    "tb1": "tech_budget_team1",
    "tb2": "tech_budget_team2",
    "pn":  "match_pending",
    "c1":  "captain1",
    "c2":  "captain2",
    "rc":  "required_ready_count",
}


@dataclass(frozen=True)
class MatchState:
    """Parsed snapshot from `amx_ktp_test_get_state`. Long-form field names;
    booleans converted from the raw 0/1 ints."""
    match_type: MatchType
    current_half: int
    match_live: bool
    is_paused: bool
    match_id: str
    score_team1: int
    score_team2: int
    tech_budget_team1: int
    tech_budget_team2: int
    match_pending: bool
    captain1: str  # "<name>|<sid>" raw
    captain2: str
    required_ready_count: int


_RCON_OK_PREFIXES = ("KTP_TEST_SETUP:", "KTP_TEST_PENDING:", "KTP_TEST_LIVE:",
                     "KTP_TEST_END:", "KTP_TEST_RESET:")
_STATE_LINE_RE = re.compile(r"KTP_TEST_STATE:\s*(\{.*\})")
_LOCALINFO_LINE_RE = re.compile(r"KTP_TEST_LOCALINFO:\s+key=(\S+)\s+value=(.*)")


class MatchDriver:
    """Issue test-mode rcons against a ServerHandle. Stateless — every
    method makes a single rcon call. Tests can hold one driver for an
    entire test or instantiate per-call; both work."""

    def __init__(self, handle):
        self._handle = handle

    # -- Lifecycle / state-machine --------------------------------------

    def setup_match(self, match_type: MatchType, map_name: str = "") -> str:
        """PRESTART_BEGIN with synthetic captains. Returns the assigned
        match_id (production-shape `<systime>-TEST`)."""
        cmd = f"amx_ktp_test_setup_match {int(match_type)}"
        if map_name:
            cmd += f" {map_name}"
        out = self._handle.rcon(cmd)
        self._raise_on_error(out, "KTP_TEST_SETUP")
        # Output: `KTP_TEST_SETUP: matchType=N match_id=X-TEST map=Y`
        m = re.search(r"match_id=(\S+)", out)
        if not m:
            raise MatchDriverError(f"setup_match output missing match_id: {out!r}")
        return m.group(1)

    def advance_pending(self) -> None:
        """PRESTART → PENDING via the production `enter_pending_phase()`
        helper. No-op response on success; raises on error."""
        out = self._handle.rcon("amx_ktp_test_advance_pending")
        self._raise_on_error(out, "KTP_TEST_PENDING")

    def advance_live(self, half: int) -> None:
        """PENDING → LIVE for the given half (1=h1, 2=h2, 101+=OT). Fires
        the `ktp_match_start` multi-forward — KTPWitness.amxx records the
        fire to `addons/ktpamx/logs/witness.jsonl`."""
        out = self._handle.rcon(f"amx_ktp_test_advance_live {int(half)}")
        self._raise_on_error(out, "KTP_TEST_LIVE")

    def end_match(self, score_team1: int, score_team2: int) -> None:
        """Fires `ktp_match_end` multi-forward + logs `KTP_MATCH_END` for
        HLStatsX parity. Clears match-live state."""
        out = self._handle.rcon(f"amx_ktp_test_end_match {int(score_team1)} {int(score_team2)}")
        self._raise_on_error(out, "KTP_TEST_END")

    def reset(self) -> None:
        """Clear all match state to idle. Used by the conftest autouse
        fixture between tests; tests can call directly if they need to
        re-test setup-from-clean within a single test body."""
        out = self._handle.rcon("amx_ktp_test_reset")
        self._raise_on_error(out, "KTP_TEST_RESET")

    # -- State readback -------------------------------------------------

    def get_state(self) -> MatchState:
        """Snapshot the match-flow state machine. Parses the one-line JSON
        the test-mode rcon emits + remaps short → long key names."""
        out = self._handle.rcon("amx_ktp_test_get_state")
        m = _STATE_LINE_RE.search(out)
        if not m:
            raise MatchDriverError(
                f"get_state response missing KTP_TEST_STATE prefix: {out!r}"
            )
        try:
            raw = json.loads(m.group(1))
        except json.JSONDecodeError as ex:
            raise MatchDriverError(
                f"get_state JSON parse failed: {ex}; raw={m.group(1)!r}"
            ) from ex
        return MatchState(
            match_type=MatchType(raw["mt"]),
            current_half=raw["h"],
            match_live=bool(raw["l"]),
            is_paused=bool(raw["p"]),
            match_id=raw["id"],
            score_team1=raw["s1"],
            score_team2=raw["s2"],
            tech_budget_team1=raw["tb1"],
            tech_budget_team2=raw["tb2"],
            match_pending=bool(raw["pn"]),
            captain1=raw["c1"],
            captain2=raw["c2"],
            required_ready_count=raw["rc"],
        )

    def get_localinfo(self, key: str) -> str:
        """Read a localinfo key. Returns empty string if the key isn't set
        (the engine's get_localinfo returns "" for unset keys, which we
        pass through verbatim)."""
        out = self._handle.rcon(f"amx_ktp_test_get_localinfo {key}")
        m = _LOCALINFO_LINE_RE.search(out)
        if not m:
            raise MatchDriverError(
                f"get_localinfo response missing KTP_TEST_LOCALINFO prefix: {out!r}"
            )
        if m.group(1) != key:
            raise MatchDriverError(
                f"get_localinfo key mismatch: requested {key!r}, got {m.group(1)!r}"
            )
        return m.group(2).rstrip()

    # -- Error handling -------------------------------------------------

    @staticmethod
    def _raise_on_error(out: str, expected_prefix: str) -> None:
        """If the rcon output contains `<prefix>: ERROR <reason>`, raise
        MatchDriverError with the reason. Otherwise verify the expected
        success prefix appears (catches the case where the wrong rcon
        was invoked or the test-mode build isn't loaded)."""
        if f"{expected_prefix}: ERROR" in out:
            # Extract the reason (everything after "ERROR ")
            m = re.search(rf"{re.escape(expected_prefix)}:\s*ERROR\s+(.+)", out)
            reason = m.group(1).rstrip() if m else "(no reason)"
            raise MatchDriverError(f"{expected_prefix} failed: {reason}")
        if expected_prefix + ":" not in out:
            raise MatchDriverError(
                f"Expected {expected_prefix}: prefix in output (test-mode build "
                f"not loaded?), got: {out!r}"
            )
