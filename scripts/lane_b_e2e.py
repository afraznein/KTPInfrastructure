#!/usr/bin/env python3
"""Lane B end to end: bots play, the daemon listens, the database is asserted.

The whole pipeline in one process:

    patched ktpamx + stats_logging  ->  game log
    new_bot under Metamod           ->  kills, captures, deaths mid-capture
    hlstats.pl --stdin              ->  ephemeral MySQL
    assertions.py                   ->  pass / fail

Run it inside the Lane B image. `scripts/replay_daemon.py` covers the same
daemon leg deterministically from a captured log; this is the one that proves
the whole chain, and it is the one that is allowed to be flaky, because bot AI
decides how many events happen.

## What it does NOT do

It does not gate merges. Lane B is nightly and advisory — see
tests/e2e_stats/README.md. A red run here means "look at this", not "the branch
is broken", because a bot that spends four minutes failing to find a fight
produces a legitimately empty database.

The one exception is a failure that cannot be bot luck: an assist recorded in
BOTH event tables is a flag inversion, and no amount of bot behaviour produces
it. Those assertions are exact.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.e2e_stats import assertions, metamod  # noqa: E402
from tests.e2e_stats.bot_driver import NEW_BOT  # noqa: E402
from tests.e2e_stats.ephemeral_mysql import EphemeralMysql  # noqa: E402
from tests.e2e_stats.ephemeral_tree import EphemeralTree  # noqa: E402
from tests.e2e_stats.hlstats_daemon import HlstatsDaemon  # noqa: E402
from tests.smoke.boot_subprocess import booted_subprocess  # noqa: E402

# The first hlds boot in a fresh container dies inside SteamAPI_Init and the
# next one with identical arguments succeeds. Isolated by running the same
# command three times in one container; retried rather than explained.
BOOT_ATTEMPTS = 3


def stage_tree(hlds: Path, *, ktpamx_so: Path, plugin: Path, config_dir: Path,
               server_cfg_fixture: Path) -> EphemeralTree:
    """Lay the branch's artifacts over the image's server tree.

    `in_place` rather than a copy: the container is the isolation boundary, so
    a second one buys nothing and costs a full tree copy per run.
    """
    tree = EphemeralTree.in_place(hlds)
    dll = "dod/addons/ktpamx/dlls/ktpamx_i386.so"
    tree.overlay_file(ktpamx_so, dll)

    # The runtime base image ships no modules.ini/plugins.ini — production's
    # entrypoint mounts them. Without these AMXX loads zero modules and zero
    # plugins, and the run looks like a stack that came up fine.
    for ini in config_dir.glob("*.ini"):
        tree.overlay_file(ini, f"dod/addons/ktpamx/configs/{ini.name}")
    tree.overlay_file(plugin, "dod/addons/ktpamx/plugins/stats_logging.amxx")

    tree.write_text(
        "dod/lane_b_server.cfg",
        server_cfg_fixture.read_text()
        + "\nmp_timelimit 0\nmp_limitteams 0\nktp_stats_capture 1\n")
    return tree


def drive_bots(handle, *, per_team: int, play_seconds: int, log_path: Path,
               flag_priority: int = 100, wait_for_cap: int = 100,
               bot_skill: int = 5, progress_every: int = 30) -> None:
    """Fill both teams and let them play.

    `flag_priority_percent 100` points new_bot at the flags rather than into
    deathmatch. Bots that ignore objectives generate kills all day and never a
    single cap_break.

    ## cap_break happens about half the time, and no knob here changes that

    A break needs a capper killed *mid-capture*, which is genuinely rare next
    to an assist. Assists arrive every run (4, 5, 7, 12); cap_break appeared in
    two runs of four:

        240s  wait_for_cap 100  ->  1 break
        240s  wait_for_cap 100  ->  0
        420s  wait_for_cap 100  ->  0
        300s  wait_for_cap   0  ->  1 break

    That is not enough to say the knob does anything, in either direction, so
    the default is left where the fleet-realistic value is. Longer runs did not
    help either, which argues against it being a simple matter of exposure.

    Capture-type ratio was checked and does not explain it: a run with a break
    had 19 `dod_capture_area` (timed, breakable) to 7 `dod_control_point`
    (instant); a run without had 16 to 12. Both had plenty of the interruptible
    kind.

    So it is ordinary rarity. `check_carried` reports a run that produced none
    as `not_exercised` rather than as a pass or a defect, and the path itself
    is separately verified by `replay_daemon.py` against a captured log. If
    this needs to be deterministic, drive the scenario — put a bot in a zone
    and kill it — rather than tuning bot behaviour and hoping.
    """
    for cmd in (f"flag_priority_percent {flag_priority}",
                f"wait_for_cap_percent {wait_for_cap}",
                f"bot_skill {bot_skill}", "balance teams on"):
        handle.rcon(cmd)
    for _ in range(per_team):
        for team in ("allies", "axis"):
            handle.rcon(f"addbot {team}")
            time.sleep(0.8)
    time.sleep(15)

    for elapsed in range(progress_every, play_seconds + 1, progress_every):
        time.sleep(progress_every)
        body = log_path.read_text(errors="replace")
        print(f"  t+{elapsed:>4}s  kills={body.count(chr(34) + ' killed ' + chr(34)):<4} "
              f"assist={body.count('triggered ' + chr(34) + 'assist' + chr(34)):<3} "
              f"cap_break={body.count('triggered ' + chr(34) + 'cap_break' + chr(34)):<3}",
              flush=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--serverfiles", type=Path, default=Path("/opt/hlds"))
    ap.add_argument("--ktpamx-so", type=Path, required=True,
                    help="ktpamx built with KTP_LANE_B_FAKECLIENTS=1")
    ap.add_argument("--plugin", type=Path, required=True,
                    help="compiled stats_logging.amxx from the branch under test")
    ap.add_argument("--config-dir", type=Path, required=True,
                    help="config/local — the sv_lan, no-Steam-auth .ini set")
    ap.add_argument("--server-cfg", type=Path,
                    default=Path("/work/tests/smoke/fixtures/test_server.cfg"))
    ap.add_argument("--hlstats", type=Path, required=True)
    ap.add_argument("--schema", type=Path, nargs="+", required=True)
    ap.add_argument("--seed", type=Path, nargs="*", default=[])
    ap.add_argument("--map", default="dod_anzio")
    ap.add_argument("--per-team", type=int, default=8)
    ap.add_argument("--play-seconds", type=int, default=240)
    ap.add_argument("--wait-for-cap", type=int, default=100,
                    help="new_bot wait_for_cap_percent. Lowering it should mean "
                         "more lone cappers and so more cap_breaks — untested; "
                         "see drive_bots for what is and is not known")
    ap.add_argument("--flag-priority", type=int, default=100)
    ap.add_argument("--port", type=int, default=27015)
    ap.add_argument("--log", type=Path, default=Path("/work/build/lane-b-e2e.log"))
    ap.add_argument("--out", type=Path, default=Path("/work/build/lane-b-e2e.json"))
    args = ap.parse_args()

    report: dict = {"map": args.map, "play_seconds": args.play_seconds}
    failures: list[str] = []
    args.log.parent.mkdir(parents=True, exist_ok=True)
    args.log.unlink(missing_ok=True)

    with EphemeralMysql.start() as db:
        # Everything the daemon caches at startup must exist first: the action
        # rows, the server row, and the server config. A row inserted after it
        # boots is not live and its log lines are dropped without an error.
        db.prepare(schema_files=list(args.schema), seed_files=list(args.seed))
        db.assert_action_seeded("assist", for_pa="0", for_ppa="1")
        db.assert_action_seeded("cap_break", for_pa="1", for_ppa="0")
        report["schema_repairs"] = HlstatsDaemon.repair_reconstructed_schema(db)
        HlstatsDaemon.ensure_server_row(db, address="127.0.0.1", port=args.port,
                                        min_players=2)

        tree = stage_tree(args.serverfiles, ktpamx_so=args.ktpamx_so,
                          plugin=args.plugin, config_dir=args.config_dir,
                          server_cfg_fixture=args.server_cfg)
        topo = metamod.enable_metamod(tree, bot_spec=NEW_BOT, host_ktpamx=False)
        print(f"topology: {topo}", flush=True)

        daemon = HlstatsDaemon(
            script=args.hlstats,
            db_socket=db.socket_path,
            db_name=db.database,
            db_user="root",
            server_ip="127.0.0.1",
            server_port=args.port,
            log_source=args.log,
            stdout_path=args.out.with_name("hlstats-e2e.out"),
            debug=1,
        )
        daemon.start()
        print("daemon up, tailing the game log", flush=True)

        booted = False
        for attempt in range(1, BOOT_ATTEMPTS + 1):
            try:
                with booted_subprocess(args.serverfiles, map_name=args.map,
                                       port=args.port, maxplayers=args.per_team * 2,
                                       rcon_password="smoketest",
                                       server_cfg="lane_b_server.cfg",
                                       log_file=args.log, boot_timeout=90.0,
                                       extra_args=topo.extra_args) as handle:
                    print(f"server up (attempt {attempt})", flush=True)
                    report["boot_attempts"] = attempt
                    booted = True
                    drive_bots(handle, per_team=args.per_team,
                               play_seconds=args.play_seconds, log_path=args.log,
                               flag_priority=args.flag_priority,
                               wait_for_cap=args.wait_for_cap)
                break
            except Exception as e:  # noqa: BLE001
                print(f"boot attempt {attempt} failed: {e}", flush=True)
        if not booted:
            daemon.stop()
            raise SystemExit(f"server never booted in {BOOT_ATTEMPTS} attempts")

        # The server is down; let the tail catch up before closing stdin. The
        # plugin flushes its own ring buffer on a 5s task, so a drain shorter
        # than that can miss the tail of the match and look like lost capture.
        daemon.drain(quiet_for=8.0, timeout=120.0)
        daemon.stop()
        if daemon.died_early:
            failures.append(daemon.died_early)

        log_text = args.log.read_text(errors="replace")
        report["emitted"] = {
            "kills": log_text.count('" killed "'),
            "assist": log_text.count('triggered "assist"'),
            "cap_break": log_text.count('triggered "cap_break"'),
        }
        report["lines_fed"] = daemon.lines_fed
        report["sql_errors"] = daemon.sql_errors()[:20]
        report["rows"] = assertions.summarise(db)

        # Two separate verdicts. `failures` are defects; `gaps` are scenarios
        # the bots never produced, which say nothing either way and must not be
        # dressed up as either a pass or a defect.
        carried = [
            assertions.check_carried(db, "assist", emitted=report["emitted"]["assist"],
                                     table="hlstats_Events_PlayerPlayerActions",
                                     other_table="hlstats_Events_PlayerActions"),
            assertions.check_carried(db, "cap_break", emitted=report["emitted"]["cap_break"],
                                     table="hlstats_Events_PlayerActions",
                                     other_table="hlstats_Events_PlayerPlayerActions"),
        ]
        report["carried"] = carried
        failures += [f"{c['code']}: {c['detail']}" for c in carried
                     if c["status"] == "pipeline"]
        gaps = [f"{c['code']}: {c['detail']}" for c in carried
                if c["status"] == "not_exercised"]
        report["coverage_gaps"] = gaps

        for check in (
            lambda: assertions.assert_baseline_still_flows(db),
            lambda: assertions.assert_no_dropped_lines(log_text),
        ):
            try:
                check()
            except AssertionError as e:
                failures.append(str(e))
        if report["sql_errors"]:
            failures.append(f"{len(report['sql_errors'])} SQL error(s) from the "
                            "daemon:\n  " + "\n  ".join(report["sql_errors"][:5]))

    report["failures"] = failures
    print("\n=== emitted in log vs recorded in db ===")
    e, rows = report["emitted"], report["rows"]
    for code in ("assist", "cap_break"):
        r = rows[code]
        print(f"  {code:<12} log={e[code]:<4} ppa={r['ppa']:<4} pa={r['pa']}")
    print(f"  {'kills':<12} log={e['kills']:<4} frags={rows['frags']}")
    print(f"  players {rows['players']} ({rows['bots']} bot)")
    print(f"  assist positions: {rows['assist_positions']}")
    print(f"  break positions:  {rows['break_positions']}")

    gaps = report.get("coverage_gaps") or []
    if gaps:
        print(f"\n=== {len(gaps)} NOT EXERCISED ===")
        for g in gaps:
            print("  - " + g.replace("\n", "\n    "))
    if failures:
        print(f"\n=== {len(failures)} FAILURE(S) ===")
        for f in failures:
            print("  - " + f.replace("\n", "\n    "))
    elif gaps:
        # Not a pass. Nothing is broken, but the run did not test what it set
        # out to test, and recording that as green is how a lane stops meaning
        # anything.
        print("\nno defects found, but this run is INCOMPLETE — see above")
    else:
        print("\nall assertions passed")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, default=str))
    print(f"wrote {args.out}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
