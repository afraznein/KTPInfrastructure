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
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.e2e_stats import (assertions, assist_scenario, break_scenarios,  # noqa: E402
                             containment, log_invariants, metamod)
from tests.e2e_stats.table_report import (changed_table_samples,  # noqa: E402
                                          render_markdown, table_counts)
from tests.e2e_stats.bot_driver import NEW_BOT  # noqa: E402
from tests.e2e_stats.ephemeral_mysql import EphemeralMysql  # noqa: E402
from tests.e2e_stats.ephemeral_tree import EphemeralTree  # noqa: E402
from tests.e2e_stats.hlstats_daemon import HlstatsDaemon  # noqa: E402
from tests.integration.match_flow import MatchDriver, MatchDriverError  # noqa: E402
from tests.smoke.boot_subprocess import booted_subprocess  # noqa: E402

# The first hlds boot in a fresh container dies inside SteamAPI_Init and the
# next one with identical arguments succeeds. Isolated by running the same
# command three times in one container; retried rather than explained.
BOOT_ATTEMPTS = 3


def compile_sma(src: Path, out: Path, *, scripting: Path,
                extra_sources: tuple[Path, ...] = (),
                defines: tuple[str, ...] = (),
                include_dir: Path | None = None) -> Path:
    """Compile a .sma against the image's own amxxpc.

    amxxpc must run from its own directory or it cannot find amxxpc32.so, and
    it reports that as a missing source file rather than a missing loader.
    Line endings are normalised first: the repo is edited on Windows and a
    stray CR ends up inside a token.

    `extra_sources` are copied next to the main file so sibling `#include`s
    resolve — KTPMatchHandler needs `ktp_matchhandler_discord.inc` this way.

    `defines` are passed as trailing `NAME=VALUE` arguments, which is how the
    Pawn compiler takes command-line `#define`s. That is the mechanism behind
    `KTP_TEST_MODE=1`, and it is why a test-mode build is a compile-time
    decision that cannot leak into a production binary.

    `include_dir`, when given, is searched BEFORE `{scripting}/include` (the
    image's own baked-in includes, from whenever the image was last built).
    Without this, a source checked out fresh from a branch can reference
    natives the image's stale includes don't have yet — found live: current
    KTPMatchHandler calls dodx_get_aim_stats()/dodx_reset_aim_stats()/
    dodx_get_aim_window(), all present in KTPAMXX's current dodx.inc, absent
    from the image's baked copy, so a plain compile_sma() call failed with
    "undefined symbol" even though the natives genuinely exist.
    """
    # read_text() applies universal newlines, so a CRLF source lands as LF.
    work_dir = Path("/tmp/sma")
    work_dir.mkdir(parents=True, exist_ok=True)
    work = work_dir / src.name
    work.write_text(src.read_text(encoding="utf-8", errors="replace"))
    for extra in extra_sources:
        (work_dir / extra.name).write_text(
            extra.read_text(encoding="utf-8", errors="replace"))

    argv = [str(scripting / "amxxpc"), str(work)]
    if include_dir is not None:
        argv.append(f"-i{include_dir}")
    argv += [f"-i{scripting}/include", f"-i{work_dir}", f"-o{out}"]
    argv += list(defines)
    r = subprocess.run(argv, cwd=str(scripting), capture_output=True,
                       text=True, timeout=300)
    if not out.is_file():
        raise SystemExit(f"{src.name} failed to compile: {r.stdout} {r.stderr}")
    return out


def build_test_mode_matchhandler(src_dir: Path, out: Path, *,
                                 scripting: Path,
                                 include_dir: Path | None = None) -> Path:
    """Compile KTPMatchHandler with the `amx_ktp_test_*` rcons enabled.

    The image ships the PRODUCTION build, in which the whole test block
    compiles to zero bytes, so none of the rcons exist. Without them a match
    cannot be driven and every row Lane B produces carries `match_id NULL` —
    which is correct for warmup and useless for testing match attribution.

    Mirrors `KTPMatchHandler/compile.sh KTP_TEST_MODE=1`, deliberately: if that
    script's flags change, this should follow rather than drift.

    `include_dir` should point at the KTPAMXX branch under test's
    `plugins/include` — see `compile_sma`'s docstring for why the image's own
    baked-in includes can be stale relative to it.
    """
    sma = src_dir / "KTPMatchHandler.sma"
    inc = src_dir / "ktp_matchhandler_discord.inc"
    if not sma.is_file():
        raise SystemExit(f"KTPMatchHandler.sma not found under {src_dir}")
    return compile_sma(sma, out, scripting=scripting,
                       extra_sources=(inc,) if inc.is_file() else (),
                       defines=("KTP_TEST_MODE=1",),
                       include_dir=include_dir)


def stage_tree(hlds: Path, *, ktpamx_so: Path, dodx_so: Path, plugin: Path, config_dir: Path,
               server_cfg_fixture: Path, break_drive: Path | None = None,
               assist_drive: Path | None = None,
               matchhandler: Path | None = None) -> tuple[EphemeralTree, list[str]]:
    """Lay the branch's artifacts over the image's server tree.

    `in_place` rather than a copy: the container is the isolation boundary, so
    a second one buys nothing and costs a full tree copy per run.

    Returns the tree and the list of plugins removed for containment.
    """
    tree = EphemeralTree.in_place(hlds)
    dll = "dod/addons/ktpamx/dlls/ktpamx_i386.so"
    tree.overlay_file(ktpamx_so, dll)
    tree.overlay_file(dodx_so, "dod/addons/ktpamx/modules/dodx_ktp_i386.so")

    # The runtime base image ships no modules.ini/plugins.ini — production's
    # entrypoint mounts them. Without these AMXX loads zero modules and zero
    # plugins, and the run looks like a stack that came up fine.
    for ini in config_dir.glob("*.ini"):
        tree.overlay_file(ini, f"dod/addons/ktpamx/configs/{ini.name}")
    tree.overlay_file(plugin, "dod/addons/ktpamx/plugins/stats_logging.amxx")

    if matchhandler is not None:
        # Replaces the image's PRODUCTION build, in which the whole
        # amx_ktp_test_* block is zero bytes. Same filename and same position
        # in plugins.ini, so load order is unchanged.
        tree.overlay_file(matchhandler,
                          "dod/addons/ktpamx/plugins/KTPMatchHandler.amxx")

    plugins_rel = "dod/addons/ktpamx/configs/plugins.ini"
    plugins_txt = (tree.path / plugins_rel).read_text()
    plugins_txt, dropped = containment.strip_outbound_plugins(plugins_txt)

    if break_drive is not None:
        # Appended rather than replacing the list, so the stack under test
        # stays production's plugin set plus one diagnostic.
        tree.overlay_file(break_drive,
                          "dod/addons/ktpamx/plugins/KTPBreakDrive.amxx")
        plugins_txt = plugins_txt.rstrip() + "\nKTPBreakDrive.amxx\n"

    if assist_drive is not None:
        tree.overlay_file(assist_drive,
                          "dod/addons/ktpamx/plugins/KTPAssistDrive.amxx")
        plugins_txt = plugins_txt.rstrip() + "\nKTPAssistDrive.amxx\n"

    tree.write_text(plugins_rel, plugins_txt)

    tree.write_text(
        "dod/lane_b_server.cfg",
        server_cfg_fixture.read_text()
        + "\nmp_timelimit 0\nmp_limitteams 0\nktp_stats_capture 1\n"
        + "ktp_testmatch_enabled 1\n")
    return tree, dropped


def configure_bots(handle, *, flag_priority: int = 100,
                   wait_for_cap: int = 100, bot_skill: int = 5,
                   settle: float = 0.0) -> None:
    """Configure objective-focused behavior before .testmatch creates bots.

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
    if settle:
        time.sleep(settle)


def play(*, play_seconds: int, log_path: Path, progress_every: int = 30) -> None:
    """Let the match run, reporting what the log has accumulated."""
    for elapsed in range(progress_every, play_seconds + 1, progress_every):
        time.sleep(progress_every)
        body = log_path.read_text(errors="replace")
        print(f"  t+{elapsed:>4}s  kills={body.count(chr(34) + ' killed ' + chr(34)):<4} "
              f"assist={body.count('triggered ' + chr(34) + 'assist' + chr(34)):<3} "
              f"cap_break={body.count('triggered ' + chr(34) + 'cap_break' + chr(34)):<3}",
              flush=True)


def run_match(driver, *, half: int, play_seconds: int, log_path: Path,
              per_team: int = 8, before_play=None, during_play=None,
              after_match=None) -> dict:
    """Take the state machine LIVE, play, and end the match.

    This is what makes rows carry `match_id` and `half`. `recordEvent` injects
    `match_id` server-side and gates it on `round_live`, so everything emitted
    outside a live match is tagged NULL — correct behaviour, and useless for
    asserting the thing KTPR actually reads.

    Match start is intentionally not synthesized here. `.testmatch` executes
    the production restart, so the engine must reach `RoundState=1` and emit the
    real `KTP_MATCH_START`; failure to do so is a regression, not a harness gap.

    One teardown step remains test-only:

    - `end_match` — calls `dodx_flush_all_stats()`, which is what pushes
      weaponstats out to `hlstats_Events_Statsme`. Skipping it does not just
      leave the match open; it means the Statsme regression check cannot pass.
    """
    out = {"half": half}
    out["match_id"] = containment.assert_test_match_id(
        driver.testmatch(per_team=per_team))
    print(f"  match {out['match_id']} live, half {half}", flush=True)

    # Let the state change settle before the play window: the zone poll runs on
    # a 0.5s task and the capture buffer flushes on a 5s one, so starting the
    # clock immediately attributes pre-live time to the match.
    time.sleep(5.0)
    if before_play is not None:
        before_play()
    out["live_from"] = _count(log_path, chr(34) + " killed " + chr(34))

    play(play_seconds=play_seconds, log_path=log_path)

    if during_play is not None:
        # Anything that needs the game actually running has to happen HERE,
        # before end_match. Once the match ends the round is no longer live and
        # the bots stop contesting points, so scenarios that need a cap in
        # progress simply never stage — three of five aborted with "no flag is
        # capturing right now" when they ran afterwards.
        during_play()

    out["live_to"] = _count(log_path, chr(34) + " killed " + chr(34))
    driver.end_match(1, 0)
    if after_match is not None:
        after_match()
        time.sleep(2.0)
    out["kills_during_match"] = out["live_to"] - out["live_from"]
    print(f"  match ended after {out['kills_during_match']} kills", flush=True)
    return out


def _count(log_path: Path, needle: str) -> int:
    return log_path.read_text(errors="replace").count(needle)


def kill_switch_off_window(handle, *, log_path: Path, seconds: int) -> dict:
    """Play with `ktp_stats_capture 0`, then turn it back on.

    Unit 2 step 8, and worth more than its position on the list suggests: it is
    the documented first move if anything looks wrong in production, ahead of
    any redeploy. A rollback lever nobody has pulled is not a rollback lever.

    Measured against kills rather than wall-clock, because "no assists in 60s"
    proves nothing if the bots also stopped fighting.

    This runs **before** the main match on purpose. Proving the switch turns
    capture back ON needs enough play to produce an assist, and assists arrive
    at roughly one a minute — a 60s window after re-enabling came back with 12
    kills and 0 assists, which is entirely normal and proves nothing. Putting
    the off-window first makes the whole match the evidence for re-enabling,
    at no extra wall-clock cost.
    """
    handle.rcon("ktp_stats_capture 0")
    before = {"assist": _count(log_path, 'triggered "assist"'),
              "kills": _count(log_path, '" killed "')}
    time.sleep(seconds)
    off = {"assist": _count(log_path, 'triggered "assist"'),
           "kills": _count(log_path, '" killed "')}
    handle.rcon("ktp_stats_capture 1")

    result = {"kills_while_off": off["kills"] - before["kills"],
              "assists_while_off": off["assist"] - before["assist"]}
    print(f"  kill switch off for {seconds}s: {result['kills_while_off']} kills, "
          f"{result['assists_while_off']} assists (want 0)", flush=True)
    return result


def check_kill_switch(result: dict, *, assists_after_on: int) -> dict:
    """Verdict on the kill switch. Same three-way shape as the rest.

    `assists_after_on` is the whole match that followed the off-window, which
    is what makes "it turned back on" provable at all.
    """
    if result["kills_while_off"] == 0:
        return {"code": "kill_switch", "status": "not_exercised",
                "detail": "no kills at all while capture was off, so silence "
                          "proves nothing — the bots simply stopped fighting."}
    if result["assists_while_off"] != 0:
        return {"code": "kill_switch", "status": "pipeline",
                "detail":
                f"{result['assists_while_off']} assist(s) emitted during "
                f"`ktp_stats_capture 0`. The documented rollback lever does "
                f"not stop capture, so there is no way to turn this off in "
                f"production short of a redeploy."}
    if assists_after_on == 0:
        return {"code": "kill_switch", "status": "not_exercised",
                "detail":
                f"capture correctly emitted nothing across "
                f"{result['kills_while_off']} kills while off, but the match "
                f"after re-enabling produced no assists either, so turning it "
                f"back on is unproven this run."}
    return {"code": "kill_switch", "status": "ok",
            "detail": f"{result['kills_while_off']} kills produced 0 assists "
                      f"while off; {assists_after_on} once re-enabled"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--serverfiles", type=Path, default=Path("/opt/hlds"))
    ap.add_argument("--ktpamx-so", type=Path, required=True,
                    help="ktpamx built with KTP_LANE_B_FAKECLIENTS=1")
    ap.add_argument("--dodx-so", type=Path, required=True,
                    help="DODX module built with KTP_LANE_B_FAKECLIENTS=1")
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
    ap.add_argument("--per-team", type=int, choices=(6,), default=6,
                    help="Lane B is fixed at tournament-sized 6v6")
    ap.add_argument("--play-seconds", type=int, default=240)
    ap.add_argument("--wait-for-cap", type=int, default=100,
                    help="new_bot wait_for_cap_percent. Lowering it should mean "
                         "more lone cappers and so more cap_breaks — untested; "
                         "see configure_bots for what is and is not known")
    ap.add_argument("--flag-priority", type=int, default=100)
    ap.add_argument("--break-drive-sma", type=Path,
                    default=Path("/work/tests/e2e_stats/diagnostics/KTPBreakDrive.sma"),
                    help="diagnostic that stages the Unit 3 cap-break scenarios")
    ap.add_argument("--assist-drive-sma", type=Path,
                    default=Path("/work/tests/e2e_stats/diagnostics/KTPAssistDrive.sma"),
                    help="diagnostic that stages the degraded projectile-killer assist scenario")
    ap.add_argument("--matchhandler-src", type=Path,
                    default=Path("/src/KTPMatchHandler"),
                    help="KTPMatchHandler checkout; compiled with "
                         "KTP_TEST_MODE=1 so a match can be driven")
    ap.add_argument("--matchhandler-includes", type=Path, default=None,
                    help="KTPAMXX plugins/include dir to compile "
                         "KTPMatchHandler against, searched before the "
                         "image's own baked-in includes. Needed whenever "
                         "KTPMatchHandler references a native newer than the "
                         "image — see compile_sma's docstring")
    ap.add_argument("--no-match", action="store_true",
                    help="run without driving a match. Every row is then "
                         "match_id NULL, which is correct for warmup and "
                         "proves nothing about match attribution")
    ap.add_argument("--no-break-scenarios", action="store_true",
                    help="skip the staged scenarios (they kill bots on command)")
    ap.add_argument("--kill-switch-seconds", type=int, default=60,
                    help="seconds to play with ktp_stats_capture 0, then 1. "
                         "0 skips the check (deployment plan Unit 2 step 8)")
    ap.add_argument("--port", type=int, default=27015)
    ap.add_argument("--log", type=Path, default=Path("/work/build/lane-b-e2e.log"))
    ap.add_argument("--out", type=Path, default=Path("/work/build/lane-b-e2e.json"))
    ap.add_argument("--summary-out", type=Path,
                    default=Path("/work/build/lane-b-summary.md"))
    args = ap.parse_args()

    report: dict = {"map": args.map, "play_seconds": args.play_seconds}
    failures: list[str] = []
    # Scenarios that could not be staged. Kept apart from `failures`
    # for the same reason as the other coverage gaps: a scenario that
    # never set up says nothing about the code it was aimed at.
    gaps_extra: list[str] = []
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
        # Capture the seeded/configuration baseline. The final report then
        # samples every table that gained rows during this specific match.
        before_counts = table_counts(db)

        # Containment, before anything boots. This lane drives a REAL match
        # through the real state machine, so the Discord and HLTV code paths
        # are genuinely entered — the only thing keeping them harmless is that
        # their URLs are empty. Check rather than assume.
        report["containment"] = {
            "config_keys_checked": containment.assert_no_outbound_config(
                args.config_dir)}
        print(f"containment: {len(report['containment']['config_keys_checked'])} "
              f"outbound key(s) confirmed empty", flush=True)

        mh_amxx = None
        if not args.no_match and args.matchhandler_src.is_dir():
            mh_amxx = build_test_mode_matchhandler(
                args.matchhandler_src, Path("/tmp/KTPMatchHandler.amxx"),
                scripting=args.serverfiles / "dod/addons/ktpamx/scripting",
                include_dir=args.matchhandler_includes)
            print(f"compiled test-mode KTPMatchHandler "
                  f"({mh_amxx.stat().st_size} bytes)", flush=True)
        elif not args.no_match:
            raise SystemExit(
                f"--matchhandler-src {args.matchhandler_src} is not a directory. "
                f"Without a test-mode build there are no amx_ktp_test_* rcons, "
                f"no match can be driven, and every row would be match_id NULL. "
                f"Pass --no-match to run the untagged lane deliberately.")

        drive_amxx = None
        if not args.no_break_scenarios and args.break_drive_sma.is_file():
            drive_amxx = compile_sma(
                args.break_drive_sma, Path("/tmp/KTPBreakDrive.amxx"),
                scripting=args.serverfiles / "dod/addons/ktpamx/scripting")
            print(f"compiled {drive_amxx.name}", flush=True)

        assist_drive_amxx = None
        if args.assist_drive_sma.is_file():
            assist_drive_amxx = compile_sma(
                args.assist_drive_sma, Path("/tmp/KTPAssistDrive.amxx"),
                scripting=args.serverfiles / "dod/addons/ktpamx/scripting")
            print(f"compiled {assist_drive_amxx.name}", flush=True)

        tree, dropped = stage_tree(args.serverfiles, ktpamx_so=args.ktpamx_so,
                                   dodx_so=args.dodx_so,
                                   plugin=args.plugin, config_dir=args.config_dir,
                                   server_cfg_fixture=args.server_cfg,
                                   break_drive=drive_amxx,
                                   assist_drive=assist_drive_amxx,
                                   matchhandler=mh_amxx)
        report["containment"]["plugins_dropped"] = dropped
        if dropped:
            print(f"containment: dropped {dropped} from the plugin list", flush=True)
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

        completed = False
        run_error = None
        for attempt in range(1, BOOT_ATTEMPTS + 1):
            server_started = False
            try:
                with booted_subprocess(args.serverfiles, map_name=args.map,
                                       port=args.port, maxplayers=12,
                                       rcon_password="smoketest",
                                       server_cfg="lane_b_server.cfg",
                                       log_file=args.log, boot_timeout=90.0,
                                       extra_args=topo.extra_args) as handle:
                    print(f"server up (attempt {attempt})", flush=True)
                    server_started = True
                    report["boot_attempts"] = attempt
                    configure_bots(handle, flag_priority=args.flag_priority,
                                   wait_for_cap=args.wait_for_cap)
                    def _stage_scenarios():
                        if assist_drive_amxx is not None:
                            print("staging degraded-killer assist scenario", flush=True)
                            report["assist_scenario"] = assist_scenario.run(
                                handle, args.log)
                        if drive_amxx is None:
                            return
                        print("staging cap-break scenarios", flush=True)
                        report["break_scenarios"] = break_scenarios.run_all(
                            handle, args.log)

                    def _stage_post_match_frag():
                        if assist_drive_amxx is not None:
                            print("staging post-match context probe", flush=True)
                            handle.rcon("ktp_ad_postmatch_frag")

                    def _stage_kill_switch():
                        if not args.kill_switch_seconds:
                            return
                        report["kill_switch"] = kill_switch_off_window(
                            handle, log_path=args.log,
                            seconds=args.kill_switch_seconds)
                        report["assists_before_match"] = _count(
                            args.log, 'triggered "assist"')

                    if mh_amxx is not None:
                        report["match"] = run_match(
                            MatchDriver(handle), half=1,
                            play_seconds=args.play_seconds, log_path=args.log,
                            per_team=args.per_team, before_play=_stage_kill_switch,
                            during_play=_stage_scenarios,
                            after_match=_stage_post_match_frag)
                    else:
                        play(play_seconds=args.play_seconds, log_path=args.log)
                        _stage_scenarios()
                completed = True
                break
            except Exception as e:  # noqa: BLE001
                print(f"boot attempt {attempt} failed: {e}", flush=True)
                # Retry transient engine boot failures only. Once the server
                # accepted RCON, replaying against the same daemon/database
                # would mix two attempted matches into one regression result.
                if server_started:
                    run_error = e
                    break
        if run_error is not None:
            daemon.stop()
            raise run_error
        if not completed:
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
        daemon_text = daemon.stdout_path.read_text(errors="replace")
        report["emitted"] = {
            "kills": log_text.count('" killed "'),
            "assist": log_text.count('triggered "assist"'),
            "cap_break": log_text.count('triggered "cap_break"'),
            "suicide": log_text.count('committed suicide with'),
            # Phase 5 retired the dedicated "headshot_kill" marker for
            # `(headshot "1")` as one property on the unconditional
            # "frag_context" marker every kill now emits.
            "headshot": log_text.count('(headshot "1")'),
            "frag_context": log_text.count('triggered "frag_context"'),
            "damage": log_text.count('triggered "damage"'),
            "flag_capture": sum(
                1 for line in log_text.splitlines()
                if re.search(r'^L .*"[^<]+<\d+><[^>]*><[^>]*>" triggered a "dod_capture_area"', line)
            ),
            "flag_position": log_text.count("KTP_FLAG_POSITION "),
            "position_sample": log_text.count('triggered "position_sample"'),
        }
        report["lines_fed"] = daemon.lines_fed
        real_sql, benign_sql = daemon.classify_sql_errors(
            expected_unresolved_actions={"assist"}
            if report.get("kill_switch") else set())
        report["sql_errors"] = real_sql[:20]
        report["sql_errors_benign"] = benign_sql[:5]
        report["rows"] = assertions.summarise(db)

        # Attribution negatives, from the log rather than the database: the log
        # is what capture emitted, so a violation here is a plugin bug and not
        # something the daemon did. Deployment plan Unit 2 steps 4-5 and Unit 3.
        report["log_invariants"] = log_invariants.summarise(log_text)
        for kind in ("assist_violations", "break_violations"):
            for v in report["log_invariants"][kind]:
                failures.append(v)

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
            assertions.check_suicides_carried(db, emitted=report["emitted"]["suicide"]),
            assertions.check_headshots_carried(db, emitted=report["emitted"]["headshot"]),
            assertions.check_frag_context_claimed(
                db,
                emitted=report["emitted"]["frag_context"],
                unmatched=daemon_text.count(
                    "KTP_NO_ROW_MATCHED: frag_context:")),
            assertions.check_damage_ledger(db, emitted=report["emitted"]["damage"]),
            assertions.check_flag_captures(
                db, emitted=report["emitted"]["flag_capture"]),
            assertions.check_flag_positions(
                db, emitted=report["emitted"]["flag_position"]),
            assertions.check_position_samples(
                db, emitted=report["emitted"]["position_sample"]),
            assertions.check_capture_buffer(log_text),
        ]
        if report.get("assist_scenario"):
            carried.append(report["assist_scenario"])
        for sc in report.get("break_scenarios", []):
            if sc["status"] == "violation":
                failures.append(f"{sc['name']}: {sc['detail']}")
            elif sc["status"] == "not_staged":
                gaps_extra.append(f"{sc['name']}: {sc['detail']}")

        if report.get("match"):
            m = report["match"]
            carried.append(assertions.check_match_players(
                db, expected=args.per_team * 2))
            carried += assertions.check_match_tagging(
                db, match_id=m["match_id"], half=m["half"])
            carried.append(assertions.check_statsme_flushed(
                db, weaponstats_lines=log_text.count(chr(34) + "weaponstats" + chr(34)),
                match_id=m["match_id"], half=m["half"]))
            carried.append(assertions.check_match_stats_reconciled(
                db, match_id=m["match_id"]))
            # The window comes from the log's own KTP_MATCH_START/END markers,
            # not from sampling a counter around the play window. Sampling is
            # off by whatever lands between the state machine going live and
            # the sample being taken, which reported a context leak that did
            # not exist.
            win = log_invariants.match_window(log_text)
            report["match"]["window"] = win
            carried.append(assertions.check_untagged_after_match(
                db, match_id=m["match_id"],
                kills_before_match=win["before"],
                kills_during_match=win["during"],
                kills_after_match=win["after"]))

        if report.get("kill_switch"):
            carried.append(check_kill_switch(
                report["kill_switch"],
                assists_after_on=report["emitted"]["assist"]
                - report.get("assists_before_match", 0)))
        report["carried"] = carried
        failures += [f"{c['code']}: {c['detail']}" for c in carried
                     if c["status"] == "pipeline"]
        gaps = [f"{c['code']}: {c['detail']}" for c in carried
                if c["status"] == "not_exercised"]
        report["coverage_gaps"] = gaps + gaps_extra

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
        if benign_sql:
            # Known all-bot artifacts. Reported, never silent: those rows really
            # did not get written, so anything downstream of them is untested.
            gaps_extra.append(
                f"{len(benign_sql)} known all-bot SQL artifact(s):\n  "
                + "\n  ".join(benign_sql[:3]))

        # Reassign after daemon classification so known all-bot SQL gaps are
        # present in both JSON and Markdown, not just console output.
        report["coverage_gaps"] = gaps + gaps_extra
        if not any(check.get("status") == "ok" for check in carried):
            failures.append(
                "coverage floor: the match produced no successful carried "
                "assertion; a green run would certify no stats behavior"
            )

        report["table_samples"] = changed_table_samples(db, before_counts, limit=10)

    report["failures"] = failures
    print("\n=== emitted in log vs recorded in db ===")
    e, rows = report["emitted"], report["rows"]
    for code in ("assist", "cap_break"):
        r = rows[code]
        print(f"  {code:<12} log={e[code]:<4} ppa={r['ppa']:<4} pa={r['pa']}")
    print(f"  {'kills':<12} log={e['kills']:<4} frags={rows['frags']}")
    print(f"  {'suicide':<12} log={e['suicide']:<4} suicides={rows['suicides']}"
          f"  {rows['suicide_weapons'].splitlines()[1:] if rows['suicide_weapons'] else ''}")
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
    args.summary_out.parent.mkdir(parents=True, exist_ok=True)
    args.summary_out.write_text(render_markdown(report), encoding="utf-8")
    print(f"wrote {args.out}")
    print(f"wrote {args.summary_out}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
