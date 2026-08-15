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
import time
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


@dataclass(frozen=True)
class SetStateResult:
    """Outcome of an `amx_ktp_test_setstate` call.

    A refusal is a legitimate result, not an error — most of what these tests
    assert is that the gates refuse when they should. So `setstate()` returns
    this instead of raising on rejection; it still raises MatchDriverError for
    `ERROR` (malformed call / test-mode build not loaded), which IS a bug.

    `reason` mirrors the plugin's own vocabulary verbatim: `parse=bad_token`,
    `gate=not_live`, `gate=overtime`, `gate=intermission`, `scores=bad_half`,
    `scores=negative_h2`, `scores=h1_mismatch`. Empty on accept.
    """
    accepted: bool
    reason: str = ""
    derived_h2: tuple[int, int] | None = None  # (team1, team2); set on accept


_RCON_OK_PREFIXES = ("KTP_TEST_SETUP:", "KTP_TEST_PENDING:", "KTP_TEST_LIVE:",
                     "KTP_TEST_END:", "KTP_TEST_END_HALF1:", "KTP_TEST_ABANDON:",
                     "KTP_TEST_ROUNDLIVE_LOG:", "KTP_TEST_FORCERESET:",
                     "KTP_TEST_RESTARTHALF:", "KTP_TEST_RESET:",
                     "KTP_TEST_SETSTATE:")
_STATE_LINE_RE = re.compile(r"KTP_TEST_STATE:\s*(\{.*\})")
_LOCALINFO_LINE_RE = re.compile(r"KTP_TEST_LOCALINFO:\s+key=(\S+)\s+value=(.*)")
_SETSTATE_REJECT_RE = re.compile(
    r"KTP_TEST_SETSTATE:\s*REJECTED\s+((?:parse|gate|scores)=\S+)"
)
_SETSTATE_OK_RE = re.compile(r"KTP_TEST_SETSTATE:\s*ok\b.*?\bh2=(-?\d+),(-?\d+)")


class MatchDriver:
    """Issue test-mode rcons against a ServerHandle. Stateless — every
    method makes a single rcon call. Tests can hold one driver for an
    entire test or instantiate per-call; both work."""

    def __init__(self, handle):
        self._handle = handle

    # -- Lifecycle / state-machine --------------------------------------

    def testmatch(self, per_team: int = 6, timeout: float = 90.0) -> str:
        """Fill a disposable LAN server with bots and take the real competitive
        chat flow live: `.ktp` -> two `.confirm`s -> every bot `.ready`.

        The plugin owns bot creation and containment. This method only starts it
        and polls the existing state readback until the production path is LIVE.
        """
        out = self._handle.rcon(f"amx_ktp_testmatch {int(per_team)}")
        self._raise_on_error(out, "KTP_TESTMATCH")
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            status = self._handle.rcon("amx_ktp_testmatch_status")
            self._raise_on_error(status, "KTP_TESTMATCH")
            last = self.get_state()
            if last.match_live:
                if not last.match_id.endswith("-TEST"):
                    raise MatchDriverError(
                        f"testmatch produced non-test match_id: {last.match_id!r}"
                    )
                return last.match_id
            time.sleep(0.5)
        raise MatchDriverError(f"testmatch did not reach LIVE in {timeout}s; last={last!r}")

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

    def fire_match_start_log(self) -> None:
        """Emit the KTP_MATCH_START log_message + event=ROUNDLIVE_MATCH_START_LOG
        log_ktp pair that production fires from `task_roundlive_match_context`
        on engine round-live. The production task gates on the engine's
        RoundState=1 event which doesn't fire in test environment without
        a real round; this rcon lets tests drive the emission directly.

        Use AFTER `advance_live(half=N)` so g_currentHalf and g_matchId
        are populated.
        """
        out = self._handle.rcon("amx_ktp_test_fire_match_start_log")
        self._raise_on_error(out, "KTP_TEST_ROUNDLIVE_LOG")

    def abandon_match(
        self,
        mode: str = "h2",
        regulation_scores: tuple[int, int] | None = None,
    ) -> None:
        """Emit a production-shape abandon Discord embed update. Two shapes
        supported via the `mode` arg (KTPMatchHandler 0.10.136+):

          - `mode="h2"` (default): 2nd-half-abandon path
            ("MATCH ENDED (2nd half) - 1st half: T1 X - Y T2"). Uses current
            g_team1Name/g_team2Name/g_firstHalfScore. Use AFTER
            `end_first_half(s1, s2)` so the half-1 scores are populated.
          - `mode="ot1"` or `mode="ot2"`: OT-abandon path
            ("MATCH ENDED (OT%d) - Regulation: T1 X - Y T2 (tied)"). Pass
            `regulation_scores=(s1, s2)` to populate the regulation totals;
            otherwise emits 0-0. Production reads these from
            LOCALINFO_REG_SCORES; the test rcon accepts them directly.

        Doesn't drive the full localinfo-driven abandon-detection logic —
        only the embed-update side-effect that tests 16 + 16b assert on.
        See KTPMatchHandler.sma's cmd_test_abandon_match docstring for what's
        covered vs deferred.
        """
        if mode == "h2":
            cmd = "amx_ktp_test_abandon_match"
        elif mode in ("ot1", "ot2"):
            if regulation_scores is None:
                cmd = f"amx_ktp_test_abandon_match {mode}"
            else:
                s1, s2 = regulation_scores
                cmd = f"amx_ktp_test_abandon_match {mode} {int(s1)} {int(s2)}"
        else:
            raise ValueError(
                f"abandon_match mode must be 'h2', 'ot1', or 'ot2'; got {mode!r}"
            )
        out = self._handle.rcon(cmd)
        self._raise_on_error(out, "KTP_TEST_ABANDON")

    def tech_pause(self) -> None:
        """Drive the production tech-pause helper directly via
        `amx_ktp_test_tech_pause` (KTPMatchHandler 0.10.136+). Calls
        `execute_pause("KTP-TEST", "tech_pause")` skipping the 5s prepause
        countdown UX. Sets `g_isPaused=true`, fires `rh_set_server_pause(true)`,
        updates hostname.

        Negative-path test contract: production pause is HUD-only (ReHLDS
        RH_SV_UpdatePausedHUD) and does NOT emit Discord notifications. Use
        with `discord_relay` fixture to assert no /create or /edit POSTs land
        across the pause window.

        Use AFTER `advance_live` so g_matchLive=true.
        """
        out = self._handle.rcon("amx_ktp_test_tech_pause")
        self._raise_on_error(out, "KTP_TEST_TECH_PAUSE")

    def tech_unpause(self) -> None:
        """Sibling to `tech_pause()` — drives `ktp_unpause_now("test")` via
        `amx_ktp_test_tech_unpause` (KTPMatchHandler 0.10.136+). Clears
        `g_isPaused`, fires `rh_set_server_pause(false)`, updates hostname.

        Same negative-path contract: unpause should NOT emit Discord
        notifications.
        """
        out = self._handle.rcon("amx_ktp_test_tech_unpause")
        self._raise_on_error(out, "KTP_TEST_TECH_UNPAUSE")

    def end_first_half(self, score_team1: int, score_team2: int) -> None:
        """Drive the production `handle_first_half_end()` path with the
        supplied half-1 scores. Emits the "1st Half Complete - Score: X-Y"
        Discord embed update + KTP_HALF_END HLStatsX log + dod_stats_flush
        forward fires per connected client. Halftime watchdog is suppressed
        in the test rcon so the test environment doesn't get a forced map
        reload after 10s.

        Use this BEFORE advance_live(half=2) to drive the full half-transition
        sequence:
            advance_live(half=1) -> end_first_half(s1, s2) -> advance_live(half=2)
        """
        out = self._handle.rcon(
            f"amx_ktp_test_end_first_half {int(score_team1)} {int(score_team2)}"
        )
        self._raise_on_error(out, "KTP_TEST_END_HALF1")

    def reset(self) -> None:
        """Clear all match state to idle. Used by the conftest autouse
        fixture between tests; tests can call directly if they need to
        re-test setup-from-clean within a single test body."""
        out = self._handle.rcon("amx_ktp_test_reset")
        self._raise_on_error(out, "KTP_TEST_RESET")

    def forcereset(self) -> None:
        """Bypass the production `.forcereset` chat-confirmation flow and
        call `execute_force_reset()` directly with synthetic admin metadata
        ("test_admin", STEAM_0:0:99999999, 127.0.0.1).

        Production-shape side effects (per `execute_force_reset` at
        KTPMatchHandler.sma:6513-6703):
          - Full state reset (g_matchLive, g_matchPending, etc. all cleared)
          - Localinfo cleared (LOCALINFO_MATCH_ID, _MAP, _MODE, etc.)
          - Discord embed posted via `send_discord_simple_embed("Server Force Reset",
            ...)` — lands in `relay.received` (CREATE POST)
          - log_ktp `event=FORCERESET_EXECUTED ...`
          - Hostname reset, idle hint task restarted

        Distinct from `reset()` which only clears test-mode state without
        the production-shape Discord notification or full helper-chain
        invocation.
        """
        out = self._handle.rcon("amx_ktp_test_forcereset")
        self._raise_on_error(out, "KTP_TEST_FORCERESET")

    def restarthalf(self) -> None:
        """Bypass the production `.restarthalf` chat-confirmation flow and
        call `execute_restart_half()` directly with synthetic admin metadata.

        Preconditions (enforced by the test rcon, raises MatchDriverError
        with KTP_TEST_RESTARTHALF: ERROR ... if not met):
          - Match must be LIVE
          - Current half must be 2
          - Match must NOT be in overtime

        Production-shape side effects (per `execute_restart_half` at
        KTPMatchHandler.sma:6772-6834):
          - Round restart via `mp_clan_restartround 1`
          - Scoreboard reset to 1st-half scores (h2 back to 0-0)
          - g_matchScore[1/2] re-synced to h1 values
          - dodx_flush_all_stats + dodx_reset_all_stats deferred (Phase 1, 0.1s)
          - Discord embed posted ("2nd Half Restarted", Phase 2, 0.2s)

        Use AFTER `setup_match → advance_pending → advance_live(half=1) →
        end_first_half → advance_live(half=2)` so g_currentHalf==2.
        """
        out = self._handle.rcon("amx_ktp_test_restarthalf")
        self._raise_on_error(out, "KTP_TEST_RESTARTHALF")

    def setstate(
        self,
        half: int | str,
        allies: int | str,
        axis: int | str,
        h1_team1: int | str,
        h1_team2: int | str,
    ) -> SetStateResult:
        """Drive `.setstate` without the chat layer (KTPMatchHandler 0.10.150+).

        `allies`/`axis` are the CURRENT cumulative scoreboard totals; `h1_team1`
        and `h1_team2` are 1st-half scores BY TEAM IDENTITY — team1 started as
        Allies, team2 as Axis, and the sides swap in the 2nd half. So in half 2
        the plugin derives team1's H2 from `axis` and team2's H2 from `allies`.
        Getting that backwards is the bug this wrapper's naming exists to
        prevent.

        The rcon runs the same `setstate_gate_reason()` and
        `setstate_validate_scores()` the chat command runs, so a refusal here
        is the production refusal. It skips only chat-arg tokenizing and the
        retype-to-confirm window.

        Arguments accept `str` as well as `int` so tests can send tokens the
        plugin must refuse (`"-5"`, `"abc"`, `"1000"`) without the wrapper
        sanitizing away the thing under test.

        Returns SetStateResult; raises MatchDriverError only on `ERROR`.
        """
        out = self._handle.rcon(
            f"amx_ktp_test_setstate {half} {allies} {axis} {h1_team1} {h1_team2}"
        )
        self._raise_on_error(out, "KTP_TEST_SETSTATE")

        rejected = _SETSTATE_REJECT_RE.search(out)
        if rejected:
            return SetStateResult(accepted=False, reason=rejected.group(1))

        ok = _SETSTATE_OK_RE.search(out)
        if not ok:
            raise MatchDriverError(
                f"setstate response was neither REJECTED nor a parseable ok "
                f"line: {out!r}"
            )
        return SetStateResult(
            accepted=True,
            derived_h2=(int(ok.group(1)), int(ok.group(2))),
        )

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
