#!/usr/bin/env python3
"""Drive a bot-backed 6v6 through go-live on the local bot server.

Companion to `docker-compose.local.yml`'s ktp-game-2. Reuses the existing
harness rather than reimplementing anything:

    tests/smoke/rcon.RconClient          the rcon wire protocol
    tests/smoke/server_handle            wait_ready + one-shot rcon
    tests/integration/match_flow         MatchDriver.testmatch()
    tests/e2e_stats/bot_driver.NEW_BOT   the objective cvars, read from the
                                         mod's own _COMMANDS.txt

## What `.testmatch` actually does

It is not a shortcut around the match state machine — it *is* the machine.
The plugin fills the server to 6v6 with bots, then makes those bots issue the
real `.ktp` / `.confirm` / `.ready` chat commands, so the server walks the same
PRESTART -> PENDING -> LIVE path a real match walks, including the
`mp_clan_timer` countdown and the `mp_clan_restartround` go-live.

That is the whole point: it exercises the paths the mocker structurally cannot
reach, because the mocker authors its own output.

## Preconditions it will refuse on

`.testmatch` is fail-closed in the plugin, and deliberately so:

    ktp_testmatch_enabled 1     set here, by rcon, on purpose (see below)
    sv_lan 1                    already set in config/local/dodserver.cfg
    server idle                 no match pending or live
    NO human client connected   so start this BEFORE you join

HLTV is excluded from the human check and may stay connected.

`ktp_testmatch_enabled` is set at trigger time rather than in a cfg because
/config is shared with ktp-game-1, and duplicating the config tree to arm one
cvar would drift. Setting it here also keeps arming the test path an explicit
act rather than ambient server state.

## Requires a KTP_TEST_MODE KTPMatchHandler

`.testmatch` lives behind `#if defined KTP_TEST_MODE`. A production-build
KTPMatchHandler does not register the command at all, and the error you get is
an unhelpful "Unknown command". `make local-bots-plugins` builds the test-mode
one into local/plugins-bots/.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tests.e2e_stats.bot_driver import NEW_BOT  # noqa: E402
from tests.integration.match_flow import MatchDriver, MatchDriverError  # noqa: E402
from tests.smoke.server_handle import ServerHandle  # noqa: E402

# Must match SERVER_HOSTNAME for ktp-game-2 in docker-compose.local.yml — the
# HUD keys its socket rooms on X-Server-Hostname, which is that cvar.
SERVER_HOSTNAME = "KTP LOCAL BOTS #2 [NON-PROD metamod+patched-amxx]"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=27017,
                    help="ktp-game-2's published port (docker-compose.local.yml)")
    ap.add_argument("--rcon-password", default="changeme",
                    help="must match RCON_PASSWORD in the compose env")
    ap.add_argument("--per-team", type=int, default=6)
    ap.add_argument("--timeout", type=float, default=120.0,
                    help="how long to wait for LIVE; bots take a while to "
                         "connect and ready up")
    ap.add_argument("--skip-objective-cvars", action="store_true",
                    help="leave new_bot's flag behaviour at its defaults")
    args = ap.parse_args()

    handle = ServerHandle(host=args.host, port=args.port,
                          rcon_password=args.rcon_password)

    print(f"[bots] waiting for rcon on {args.host}:{args.port} ...")
    handle.wait_ready(timeout=60.0)

    # Objective play. Without these bots duel instead of walking onto flags,
    # and cap / cap-break coverage is zero -- which reads as "the detector is
    # broken" rather than "the bots never contested a point".
    if not args.skip_objective_cvars:
        for cmd in NEW_BOT.objective_commands:
            try:
                handle.rcon(cmd)
                print(f"[bots] {cmd}")
            except Exception as exc:  # an unrecognised cvar is a console gripe
                print(f"[bots] (ignored) {cmd}: {exc}")

    print("[bots] arming ktp_testmatch_enabled 1")
    handle.rcon("ktp_testmatch_enabled 1")

    driver = MatchDriver(handle)
    print(f"[bots] .testmatch {args.per_team}v{args.per_team} — filling and readying up ...")
    try:
        match_id = driver.testmatch(per_team=args.per_team, timeout=args.timeout)
    except MatchDriverError as exc:
        print(f"\n[bots] FAILED: {exc}\n", file=sys.stderr)
        print("Common causes, in the order they actually happen:", file=sys.stderr)
        print("  * KTPMatchHandler is not a KTP_TEST_MODE build "
              "(make local-bots-plugins)", file=sys.stderr)
        print("  * a human client is connected — .testmatch refuses; "
              "disconnect and retry", file=sys.stderr)
        print("  * no bots connected at all: the patched ktpamx is missing or "
              "the map has no waypoints", file=sys.stderr)
        print("\nAsk the server directly:  rcon amx_ktp_testmatch_status",
              file=sys.stderr)
        return 1

    print(f"\n[bots] LIVE — match_id={match_id}")

    # https://localhost, NOT :3000. The data container serves the React bundle
    # on :3000 with no /socket.io proxy, so a page opened there loads fine and
    # then silently receives no state — an empty board with a 0:00 clock, which
    # reads as "no match running" rather than "wrong origin". The single-origin
    # nginx on :443 is the one that works. It self-signs, so the browser warns
    # once.
    from urllib.parse import quote
    q = quote(SERVER_HOSTNAME)
    print("[bots] watch it (accept the self-signed cert once):")
    print(f"       https://localhost/caster?server={q}   <- minimap + stats")
    print(f"       https://localhost/screen?server={q}   <- the on-air overlay")
    print("       https://localhost/hq")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
