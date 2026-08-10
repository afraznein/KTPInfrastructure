"""Run one full match with bots, so the capture code emits under real conditions.

## Composes, does not duplicate

`tests/integration/match_flow.py` already has a `MatchDriver` that wraps every
`amx_ktp_test_*` rcon, parses the `KTP_TEST_*:` responses and raises
`MatchDriverError` with the reason. This module reuses it and adds only what
Lane B needs on top: bots on the map, a play window, and an ordering that leaves
rows tagged the way production would tag them.

## Why the match matters and cannot be skipped

The capture code emits its lines regardless of match state, but `hlstats.pl`'s
`recordEvent()` injects `match_id` **server-side and gates it on `round_live`**.
Emitting outside a live match yields rows with `match_id` NULL — which is
correct behaviour, and useless for asserting the thing KTPR actually reads.
`KTPR_DEPLOYMENT_PLAN.md` calls for `match_id` populated on rows from live play,
so the lane has to drive a real match rather than just boot a server and shoot.

`end_match` is also load-bearing rather than tidy-up: KTPMatchHandler's
test-mode `cmd_test_end_match` calls `dodx_flush_all_stats()` (0.10.124), which
is what pushes the weaponstats/`Statsme` side out. The regression checks in the
deployment plan read those tables, so a run that never ends the match cannot
prove weaponstats survived.

## Ordering

    fill bots  →  setup_match  →  advance_pending  →  advance_live(half)
              →  fire_match_start_log  →  [PLAY]  →  end_match  →  drain

`fire_match_start_log` is needed because production emits `KTP_MATCH_START` from
a task gated on the engine's `RoundState=1`, which does not fire without a real
round; the rcon drives the emission directly. Bots are filled *before*
`setup_match` so the match starts with a populated roster, the way a real one
would.
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# tests/integration is a sibling package; Lane B reuses its driver rather than
# reimplementing the rcon contract.
_TESTS_DIR = Path(__file__).resolve().parent.parent
if str(_TESTS_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_TESTS_DIR.parent))

from tests.integration.match_flow import MatchDriver, MatchType  # noqa: E402

from . import bot_driver  # noqa: E402
from .bot_driver import BotKit, BotUnavailable  # noqa: E402


@dataclass
class MatchOutcome:
    """What the run did, for the report. Counts are observations, not
    assertions — bot AI decides how much happens."""

    match_id: str = ""
    half: int = 1
    bots: list[str] = field(default_factory=list)
    add_command: str = ""
    objective_hints: list[str] = field(default_factory=list)
    play_seconds: float = 0.0
    lines_fed: int = 0
    ended: bool = False
    notes: list[str] = field(default_factory=list)


class MatchRunner:
    """Drive one bot-populated match end to end."""

    def __init__(self, handle, kit: BotKit):
        self._handle = handle
        self._kit = kit
        self._driver = MatchDriver(handle)

    def run(
        self,
        *,
        per_team: int = 3,
        play_seconds: float = 180.0,
        half: int = 1,
        match_type: MatchType = MatchType.COMPETITIVE,
        map_name: str = "",
        daemon=None,
        settle_before_play: float = 5.0,
    ) -> MatchOutcome:
        out = MatchOutcome(half=half)

        # 1. Bodies first — a match that goes live on an empty server produces
        #    nothing to capture, and the roster is part of what production's
        #    setup path sees.
        out.add_command = bot_driver.probe_add_command(self._handle.rcon, self._kit.spec)
        out.bots = bot_driver.fill_teams(
            self._handle.rcon, self._kit.spec,
            add_command=out.add_command, per_team=per_team,
        )
        out.objective_hints = bot_driver.apply_objective_hints(
            self._handle.rcon, self._kit.spec)
        if not out.objective_hints:
            # Not fatal, but the single likeliest reason a run produces kills
            # and zero cap activity, so it belongs in the report rather than
            # being silently absent.
            out.notes.append(
                "no objective cvars accepted by the bot mod — cap-break "
                "coverage may be zero for reasons unrelated to the detector"
            )

        # 2. Match to LIVE. Each of these raises MatchDriverError with the
        #    plugin's own reason string on rejection, so a wrong state machine
        #    step fails here with a diagnosis rather than downstream as
        #    "no rows".
        out.match_id = self._driver.setup_match(match_type, map_name)
        self._driver.advance_pending()
        self._driver.advance_live(half)
        self._driver.fire_match_start_log()

        # Let the state change settle before counting play time. The plugin's
        # zone poll runs on a 0.5s task and the capture buffer flushes on a 5s
        # task; starting the clock immediately would attribute pre-live time to
        # the play window.
        time.sleep(settle_before_play)

        # 3. Play.
        started = time.monotonic()
        time.sleep(play_seconds)
        out.play_seconds = time.monotonic() - started

        # 4. End the match — this is what triggers dodx_flush_all_stats(), so
        #    it is required for the weaponstats regression check, not optional
        #    cleanup.
        self._driver.end_match(1, 0)
        out.ended = True

        # 5. Let the daemon catch up. drain() waits past the plugin's own 5s
        #    KSC_BUF_FLUSH_SECS — asserting before that flush is indistinguishable
        #    from the capture being broken.
        if daemon is not None:
            out.lines_fed = daemon.drain()

        return out

    def abort(self) -> None:
        """Best-effort teardown so a failed run does not leave the state
        machine live for the next one. The autouse reset in
        tests/integration/conftest.py does the same job there."""
        try:
            self._handle.rcon("amx_ktp_test_reset")
        except Exception:
            pass


def require_kit(bot_kit_root: Path, bot: str) -> BotKit:
    """Locate the bot kit, raising rather than skipping when it is absent.

    Lane B inherits conftest.py's fail-don't-skip rule: a configured-but-broken
    bot must not read as a green stats run. The five `addbot` tests that sat
    skip-marked for months are the reason that rule exists.
    """
    try:
        return BotKit.locate(bot_kit_root, bot)
    except BotUnavailable:
        raise
