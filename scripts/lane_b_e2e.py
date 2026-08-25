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
is broken", because a bot that spends six minutes failing to find a fight
produces a legitimately empty database.

The one exception is a failure that cannot be bot luck: an assist recorded in
BOTH event tables is a flag inversion, and no amount of bot behaviour produces
it. Those assertions are exact.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.lane_b_match_report import (generate_lane_b_report,  # noqa: E402
                                         summary_for_lane)
from tests.e2e_stats import (assertions, assist_scenario, break_scenarios,  # noqa: E402
                             containment, log_invariants, metamod)
from tests.e2e_stats.artifacts import (BuildError,  # noqa: E402
                                       REQUIRED_AMXX_GAMEDATA,
                                       directory_tree_provenance,
                                       load_bundle_provenance,
                                       load_gamedata_provenance,
                                       render_bundle_provenance_markdown,
                                       validate_gamedata_bundle_source)
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

_AMXX_GAMEDATA_DEST = "dod/addons/ktpamx/data/gamedata"
_CLOCK_PREFLIGHT_RE = re.compile(
    r"KTP_BD_CLOCK_PREFLIGHT\s+gamerules=(?P<gamerules>-?\d+)\s+"
    r"round=(?P<round>\S+)\s+limit=(?P<limit>\S+)"
)
_SERVER_CRC_RE = re.compile(
    r"GameConfig CRC computed server=(?P<crc>[0-9A-Fa-f]{8})\s+"
    r"\((?P<path>[^)\r\n]+)\)"
)
_SERVER_RESOLVER_WARNINGS = (
    'Unable to find library "server"',
    'Unable to load library "server"',
    "Unable to prove declared mm_gamedll",
    "GameConfig CRC mismatch",
    'GameConfig CRC unable to resolve path for library "server"',
    'GameConfig CRC missing for library "server"',
    "Could not find g_pGameRules address",
)


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


def gamedata_tree_provenance(root: Path) -> dict:
    """Return a path-sensitive, byte-sensitive manifest for a gamedata tree.

    The tree is executable configuration: selecting one checkout's core while
    retaining another checkout's gamedata can resolve offsets against the
    wrong binary. Symlinks and non-regular entries are rejected so a digest
    can never certify content outside the declared checkout.
    """
    try:
        return directory_tree_provenance(root)
    except BuildError as exc:
        raise SystemExit(f"invalid AMXX gamedata: {exc}") from exc


def stage_amxx_gamedata(tree: EphemeralTree, source: Path) -> dict:
    """Replace the baked gamedata with the exact KTPAMXX checkout's tree."""
    source = Path(source)
    missing = [rel for rel in REQUIRED_AMXX_GAMEDATA
               if not (source / rel).is_file()]
    if missing:
        raise SystemExit(
            f"Lane B requires the complete KTPAMXX gamedata tree at {source}; "
            "missing " + ", ".join(missing)
        )

    source_manifest = gamedata_tree_provenance(source)
    staged_root = tree.overlay_dir(source, _AMXX_GAMEDATA_DEST)
    staged_manifest = gamedata_tree_provenance(staged_root)
    if staged_manifest != source_manifest:
        raise SystemExit(
            "staged AMXX gamedata does not byte-for-byte match the declared "
            f"source tree {source}"
        )
    return {
        "source": str(source),
        "destination": _AMXX_GAMEDATA_DEST,
        **source_manifest,
        "staged_tree_sha256": staged_manifest["tree_sha256"],
    }


def stage_tree(hlds: Path, *, ktpamx_so: Path, dodx_so: Path,
               amxx_gamedata: Path, plugin: Path, config_dir: Path,
               server_cfg_fixture: Path, break_drive: Path | None = None,
               assist_drive: Path | None = None,
               matchhandler: Path | None = None
               ) -> tuple[EphemeralTree, list[str], dict]:
    """Lay the branch's artifacts over the image's server tree.

    `in_place` rather than a copy: the container is the isolation boundary, so
    a second one buys nothing and costs a full tree copy per run.

    Returns the tree and the list of plugins removed for containment.
    """
    tree = EphemeralTree.in_place(hlds)
    dll = "dod/addons/ktpamx/dlls/ktpamx_i386.so"
    tree.overlay_file(ktpamx_so, dll)
    tree.overlay_file(dodx_so, "dod/addons/ktpamx/modules/dodx_ktp_i386.so")
    gamedata_provenance = stage_amxx_gamedata(tree, amxx_gamedata)

    # The runtime base image ships no modules.ini/plugins.ini — production's
    # entrypoint mounts them. Without these AMXX loads zero modules and zero
    # plugins, and the run looks like a stack that came up fine.
    for ini in config_dir.glob("*.ini"):
        tree.overlay_file(ini, f"dod/addons/ktpamx/configs/{ini.name}")

    # KTPMatchHandler executes configs/ktp_<map>.cfg when a match goes live;
    # those map files chain into ktpbasic.cfg, which arms mp_clan_match and
    # sets mp_timelimit. The base image does not contain them. Omitting this
    # overlay makes mp_clan_restartround silently no-op and invalidates every
    # restart assertion, so absence is a setup error rather than an optional
    # local customization.
    dod_configs = config_dir / "dod-configs"
    required_configs = (dod_configs / "ktpbasic.cfg",)
    missing_configs = [path for path in required_configs if not path.is_file()]
    if missing_configs:
        raise SystemExit(
            "Lane B requires match-time DoD configs under "
            f"{dod_configs}: missing "
            + ", ".join(path.name for path in missing_configs)
        )
    for cfg in sorted(dod_configs.glob("*.cfg")):
        tree.overlay_file(cfg, f"dod/configs/{cfg.name}")
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
    return tree, dropped, gamedata_provenance


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


def replay_boot_flag_positions(daemon, log_path: Path) -> int:
    """Feed static map metadata emitted before the successful boot was ready.

    HLStatsX intentionally starts only after RCON readiness so a failed Steam
    initialization cannot contaminate event tables. Flag positions are the
    one useful record emitted during boot. They are idempotent map metadata,
    so replay only those lines from the successful boot log after the daemon
    attaches; gameplay and player events remain excluded.
    """
    lines = [line for line in log_path.read_text(errors="replace").splitlines()
             if "KTP_FLAG_POSITION " in line]
    for line in lines:
        daemon.feed_line(line)
    return len(lines)


def run_match(driver, *, half: int, play_seconds: int, log_path: Path,
              per_team: int = 8, before_play=None, during_play=None,
              after_match=None, after_live=None) -> dict:
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
    # a 0.5s task, the capture buffer flushes on a 5s one, and MatchHandler
    # applies the timed map config on a deferred task after setting match_live.
    # The strict callback therefore runs after setup has completed but before
    # the kill-switch/play/scenario windows begin.
    time.sleep(5.0)
    if after_live is not None:
        after_live()
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


def gamerules_clock_preflight(handle, log_path: Path) -> dict:
    """Prove DODX resolved the real game DLL and exposes a live round clock.

    There is deliberately no retry here. A resolver that is unavailable at
    the first live timed-match boundary invalidates the run; waiting for a
    later sample would turn a boot defect into intermittent green evidence.
    """
    output = handle.rcon("ktp_bd_clock_preflight")
    markers = list(_CLOCK_PREFLIGHT_RE.finditer(output))
    log_text = log_path.read_text(errors="replace")
    warnings = [line.strip() for line in log_text.splitlines()
                if any(needle in line for needle in _SERVER_RESOLVER_WARNINGS)]
    crc_evidence = [
        {"crc32": match.group("crc").upper(), "path": match.group("path")}
        for match in _SERVER_CRC_RE.finditer(log_text)
    ]
    evidence = {
        "status": "pipeline",
        "command": "ktp_bd_clock_preflight",
        "rcon_output": output.strip(),
        "resolver_warnings": warnings,
        "server_crc": crc_evidence,
    }

    if len(markers) != 1:
        evidence["detail"] = (
            "clock preflight returned "
            f"{len(markers)} parseable marker(s), expected exactly one"
        )
        return evidence
    marker = markers[0]
    try:
        gamerules = int(marker.group("gamerules"))
        round_time = float(marker.group("round"))
        round_limit = float(marker.group("limit"))
    except ValueError as exc:
        evidence["detail"] = f"clock preflight returned invalid numerics: {exc}"
        return evidence
    evidence.update({
        "gamerules": gamerules,
        "round_time": round_time,
        "round_limit": round_limit,
    })

    if warnings:
        evidence["detail"] = (
            f"server/GameRules resolver emitted {len(warnings)} warning(s)"
        )
        return evidence
    if not crc_evidence:
        evidence["detail"] = "no GameConfig CRC evidence for library server"
        return evidence
    wrong_paths = [
        item["path"] for item in crc_evidence
        if not item["path"].replace("\\", "/").lower()
        .endswith("/dod/dlls/dod.so")
    ]
    if wrong_paths:
        evidence["detail"] = (
            "server GameConfig CRC did not identify dod/dlls/dod.so: "
            + ", ".join(wrong_paths)
        )
        return evidence
    if gamerules != 1:
        evidence["detail"] = f"dodx_has_gamerules returned {gamerules}, expected 1"
        return evidence
    if not math.isfinite(round_time) or round_time < 0.0:
        evidence["detail"] = (
            f"dodx_get_round_time returned non-finite/negative {round_time!r}"
        )
        return evidence
    if not math.isfinite(round_limit) or round_limit <= 0.0:
        evidence["detail"] = (
            f"live match has no finite positive round limit: {round_limit!r}"
        )
        return evidence

    evidence["status"] = "ok"
    evidence["detail"] = (
        f"GameRules available; round={round_time:.2f}s limit={round_limit:.2f}s; "
        f"server CRC resolved {crc_evidence[-1]['path']}"
    )
    return evidence


def persist_preflight_failure(report: dict, failures: list[str], failure: str,
                              *, out_path: Path, summary_path: Path) -> None:
    """Persist the strict capability failure before the server exception exits."""
    failures.append(failure)
    report["failures"] = list(failures)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str),
                        encoding="utf-8")
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(render_markdown(report), encoding="utf-8")


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
    ap.add_argument("--amxx-gamedata", type=Path, required=True,
                    help="complete gamedata tree from the exact KTPAMXX checkout")
    ap.add_argument("--plugin", type=Path, required=True,
                    help="compiled stats_logging.amxx from the branch under test")
    ap.add_argument("--config-dir", type=Path, required=True,
                    help="config/local — local .ini files plus dod-configs/*.cfg")
    ap.add_argument("--server-cfg", type=Path,
                    default=Path("/work/tests/smoke/fixtures/test_server.cfg"))
    ap.add_argument("--hlstats", type=Path, required=True)
    ap.add_argument("--schema", type=Path, nargs="+", required=True)
    ap.add_argument("--seed", type=Path, nargs="*", default=[])
    ap.add_argument("--map", default="dod_anzio")
    ap.add_argument("--per-team", type=int, choices=(6,), default=6,
                    help="Lane B is fixed at tournament-sized 6v6")
    ap.add_argument("--play-seconds", type=int, default=360,
                    help="full-match play window; v5 ratings require at least "
                         "the profile minimum (currently 300 seconds)")
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
    ap.add_argument("--match-report-dir", type=Path,
                    default=Path("/work/build/match-report"),
                    help="shareable deterministic v5 bundle, generated before "
                         "the ephemeral database is destroyed")
    ap.add_argument("--report-profile", type=Path,
                    default=Path("/work/config/analytics/accumulation_v5_momentum.toml"))
    ap.add_argument("--map-objectives", type=Path,
                    default=Path("/work/config/analytics/map_objectives.toml"))
    ap.add_argument("--artifact-manifest", type=Path, default=None,
                    help="artifact manifest carrying the exact four-repository "
                         "bundle; invalid or incomplete provenance is fatal")
    ap.add_argument("--require-complete-coverage", action="store_true",
                    help="return nonzero when any assertion or staged scenario "
                         "is not exercised; required for release evidence")
    ap.add_argument("--database-dump", type=Path, default=None,
                    help="optional local mysqldump written before the isolated "
                         "database is destroyed; intended for read-only "
                         "post-match analytics")
    args = ap.parse_args()

    report: dict = {
        "map": args.map,
        "play_seconds": args.play_seconds,
        "require_complete_coverage": args.require_complete_coverage,
    }
    expected_gamedata_provenance = None
    if args.artifact_manifest is not None:
        try:
            report["bundle_provenance"] = load_bundle_provenance(
                args.artifact_manifest
            )
            expected_gamedata_provenance = load_gamedata_provenance(
                args.artifact_manifest
            )
            validate_gamedata_bundle_source(
                report["bundle_provenance"], expected_gamedata_provenance
            )
        except BuildError as exc:
            raise SystemExit(f"invalid --artifact-manifest: {exc}") from exc
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
        needs_break_drive = mh_amxx is not None or not args.no_break_scenarios
        if needs_break_drive and args.break_drive_sma.is_file():
            drive_amxx = compile_sma(
                args.break_drive_sma, Path("/tmp/KTPBreakDrive.amxx"),
                scripting=args.serverfiles / "dod/addons/ktpamx/scripting",
                include_dir=args.matchhandler_includes)
            print(f"compiled {drive_amxx.name}", flush=True)
        elif needs_break_drive:
            raise SystemExit(
                f"--break-drive-sma {args.break_drive_sma} is missing; its "
                "strict GameRules/clock preflight is required for a live match"
            )

        assist_drive_amxx = None
        if args.assist_drive_sma.is_file():
            assist_drive_amxx = compile_sma(
                args.assist_drive_sma, Path("/tmp/KTPAssistDrive.amxx"),
                scripting=args.serverfiles / "dod/addons/ktpamx/scripting",
                include_dir=args.matchhandler_includes)
            print(f"compiled {assist_drive_amxx.name}", flush=True)

        tree, dropped, gamedata_provenance = stage_tree(
            args.serverfiles, ktpamx_so=args.ktpamx_so,
            dodx_so=args.dodx_so, amxx_gamedata=args.amxx_gamedata,
            plugin=args.plugin, config_dir=args.config_dir,
            server_cfg_fixture=args.server_cfg, break_drive=drive_amxx,
            assist_drive=assist_drive_amxx, matchhandler=mh_amxx)
        if expected_gamedata_provenance is not None:
            identity_fields = (
                "tree_sha256", "file_count", "directory_count", "bytes",
                "files", "directories",
            )
            mismatched = [
                field for field in identity_fields
                if gamedata_provenance.get(field)
                != expected_gamedata_provenance.get(field)
            ]
            if mismatched:
                raise SystemExit(
                    "--amxx-gamedata does not match the exact AMXX commit in "
                    f"--artifact-manifest (mismatched {', '.join(mismatched)})"
                )
            gamedata_provenance["artifact_source"] = (
                expected_gamedata_provenance.get("source")
            )
        report["amxx_gamedata"] = gamedata_provenance
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
                    # Do not let a transient HLDS boot attempt touch the
                    # database. Fresh containers commonly fail their first
                    # SteamAPI_Init and retry with the same console-log path.
                    # Starting the daemon only after RCON readiness means it
                    # attaches at the current end of the successful boot log;
                    # failed-attempt rows can neither be ingested nor mixed
                    # into the match that follows.
                    daemon.start()
                    print("daemon up, tailing the successful boot log", flush=True)
                    report["boot_flag_positions_replayed"] = (
                        replay_boot_flag_positions(daemon, args.log))
                    print("replayed "
                          f"{report['boot_flag_positions_replayed']} successful-boot "
                          "flag position marker(s)", flush=True)
                    configure_bots(handle, flag_priority=args.flag_priority,
                                   wait_for_cap=args.wait_for_cap)
                    def _stage_scenarios():
                        if assist_drive_amxx is not None:
                            print("staging degraded-killer assist scenario", flush=True)
                            report["assist_scenario"] = assist_scenario.run(
                                handle, args.log)
                        if drive_amxx is None or args.no_break_scenarios:
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

                    def _strict_live_preflight():
                        report["gamerules_clock_preflight"] = (
                            gamerules_clock_preflight(handle, args.log)
                        )
                        preflight = report["gamerules_clock_preflight"]
                        if preflight["status"] != "ok":
                            failure = (
                                "strict GameRules/round-clock preflight failed: "
                                + preflight["detail"]
                            )
                            persist_preflight_failure(
                                report, failures, failure,
                                out_path=args.out,
                                summary_path=args.summary_out,
                            )
                            raise RuntimeError(failure)
                        print("  " + preflight["detail"], flush=True)

                    if mh_amxx is not None:
                        report["match"] = run_match(
                            MatchDriver(handle), half=1,
                            play_seconds=args.play_seconds, log_path=args.log,
                            per_team=args.per_team, before_play=_stage_kill_switch,
                            during_play=_stage_scenarios,
                            after_match=_stage_post_match_frag,
                            after_live=_strict_live_preflight)
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
        position_sample_total = log_text.count('triggered "position_sample"')
        position_sample_match = (
            log_invariants.count_in_match(log_text, 'triggered "position_sample"')
            if report.get("match") else position_sample_total
        )
        assist_context_emitted = (
            log_invariants.count_in_match(log_text, 'triggered "assist"')
            if report.get("match") else 0
        )
        frag_context_match_emitted = (
            log_invariants.frag_context_classification(
                log_text, match_only=True
            )["frags"]
            if report.get("match") else 0
        )
        damage_match_emitted = (
            log_invariants.count_in_match(log_text, 'triggered "damage"')
            if report.get("match") else 0
        )
        life_match_emitted = (
            log_invariants.count_in_match(log_text, 'triggered "life_boundary"')
            if report.get("match") else 0
        )
        frag_diagnostic_evidence = (
            log_invariants.frag_context_diagnostic_evidence(
                log_text, daemon_text
            )
            if report.get("match") else {
                "expected_synthetic_unmatched": 0,
                "observed_unmatched": 0,
                "expected_identities": [],
                "observed_identities": [],
                "unresolved_expected": [],
                "unparsed_observed": [],
                "synthetic_kill_markers": [],
                "unmatched_warnings": [],
            }
        )
        kill_evidence = log_invariants.kill_classification(log_text)
        frag_context_evidence = log_invariants.frag_context_classification(
            log_text
        )
        report["emitted"] = {
            "kills": kill_evidence["kills"],
            "frags": kill_evidence["frags"],
            "teamkills": kill_evidence["teamkills"],
            "unclassified_kills": kill_evidence["unclassified"],
            "assist": log_text.count('triggered "assist"'),
            "cap_break": log_text.count('triggered "cap_break"'),
            "suicide": log_text.count('committed suicide with'),
            # Phase 5 retired the dedicated "headshot_kill" marker for
            # `(headshot "1")` as one property on the canonical
            # "frag_context" marker each non-teamkill player frag emits.
            "headshot": frag_context_evidence["headshots"],
            "frag_context": frag_context_evidence["frags"],
            "frag_context_total": frag_context_evidence["total"],
            "frag_context_teamkills": frag_context_evidence["teamkills"],
            "frag_context_unclassified": frag_context_evidence["unclassified"],
            "frag_context_match": frag_context_match_emitted,
            "damage": log_text.count('triggered "damage"'),
            "damage_match": damage_match_emitted,
            "flag_capture": sum(
                1 for line in log_text.splitlines()
                if re.search(r'^L .*"[^<]+<\d+><[^>]*><[^>]*>" triggered a "dod_capture_area"', line)
            ),
            "flag_position": log_text.count("KTP_FLAG_POSITION "),
            # The ownership poll can observe a final control-point change just
            # after KTP_MATCH_END. The daemon deliberately rejects that marker
            # because match context is already closed, so compare persisted
            # rows only with markers inside the same ordered match window.
            "flag_state": (
                log_invariants.count_in_match(log_text, "KTP_FLAG_STATE ")
                if report.get("match") else log_text.count("KTP_FLAG_STATE ")
            ),
            "position_sample": position_sample_match,
            "position_sample_total": position_sample_total,
            "life_boundary": log_text.count('triggered "life_boundary"'),
            "life_boundary_match": life_match_emitted,
            # Canonical ktp_assist_events is deliberately match-only.  Keep
            # this separate from the generic PPA count above, which also
            # includes diagnostic/warmup assist actions.
            "assist_context": assist_context_emitted,
        }
        expected_frag_diagnostics = frag_diagnostic_evidence[
            "expected_synthetic_unmatched"
        ]
        observed_frag_diagnostics = frag_diagnostic_evidence[
            "observed_unmatched"
        ]
        report["frag_context_diagnostics"] = {
            **frag_diagnostic_evidence,
            "claimed_expected_rows": (
                report["emitted"]["frag_context"] - expected_frag_diagnostics
            ),
            "producer_clock_expected_rows": (
                report["emitted"]["frag_context_match"]
                - expected_frag_diagnostics
            ),
        }
        report["lines_fed"] = daemon.lines_fed
        real_sql, benign_sql = daemon.classify_sql_errors()
        report["sql_errors"] = real_sql[:20]
        report["sql_errors_benign"] = benign_sql[:5]
        report["rows"] = assertions.summarise(
            db, match_id=(report["match"]["match_id"]
                          if report.get("match") else None))

        # Attribution negatives, from the log rather than the database: the log
        # is what capture emitted, so a violation here is a plugin bug and not
        # something the daemon did. Deployment plan Unit 2 steps 4-5 and Unit 3.
        report["log_invariants"] = log_invariants.summarise(log_text)
        for kind in (
            "assist_violations", "break_violations",
            "frag_context_teamkill_violations",
            "kill_classification_violations",
        ):
            for v in report["log_invariants"][kind]:
                failures.append(v)

        # Two separate verdicts. `failures` are defects; `gaps` are scenarios
        # the bots never produced, which say nothing either way and must not be
        # dressed up as either a pass or a defect.
        carried = [
            assertions.check_capture_clock_schema(db),
            assertions.check_carried(db, "assist", emitted=report["emitted"]["assist"],
                                     table="hlstats_Events_PlayerPlayerActions",
                                     other_table="hlstats_Events_PlayerActions"),
            assertions.check_assist_context(
                db,
                emitted=report["emitted"]["assist_context"],
                match_id=((report.get("match") or {}).get("match_id")),
                half=((report.get("match") or {}).get("half")),
            ),
            assertions.check_carried(db, "cap_break", emitted=report["emitted"]["cap_break"],
                                     table="hlstats_Events_PlayerActions",
                                     other_table="hlstats_Events_PlayerPlayerActions"),
            assertions.check_suicides_carried(db, emitted=report["emitted"]["suicide"]),
            assertions.check_headshots_carried(db, emitted=report["emitted"]["headshot"]),
            assertions.check_frag_context_diagnostics(
                expected=expected_frag_diagnostics,
                observed=observed_frag_diagnostics,
                expected_identities=frag_diagnostic_evidence[
                    "expected_identities"
                ],
                observed_identities=frag_diagnostic_evidence[
                    "observed_identities"
                ],
                unresolved_expected=frag_diagnostic_evidence[
                    "unresolved_expected"
                ],
                unparsed_observed=frag_diagnostic_evidence[
                    "unparsed_observed"
                ],
            ),
            assertions.check_frag_context_claimed(
                db,
                emitted=report["emitted"]["frag_context"],
                expected_unmatched=expected_frag_diagnostics,
            ),
            assertions.check_frag_producer_clocks(
                db,
                emitted=report["emitted"]["frag_context_match"],
                match_id=((report.get("match") or {}).get("match_id")),
                half=((report.get("match") or {}).get("half")),
                expected_unmatched=expected_frag_diagnostics,
            ),
            assertions.check_damage_ledger(db, emitted=report["emitted"]["damage"]),
            assertions.check_damage_producer_clocks(
                db,
                emitted=report["emitted"]["damage_match"],
                match_id=((report.get("match") or {}).get("match_id")),
                half=((report.get("match") or {}).get("half")),
            ),
            assertions.check_flag_captures(
                db, emitted=report["emitted"]["flag_capture"]),
            assertions.check_flag_positions(
                db, emitted=report["emitted"]["flag_position"]),
            assertions.check_position_samples(
                db, emitted=report["emitted"]["position_sample"],
                match_id=(report["match"]["match_id"]
                          if report.get("match") else None)),
            assertions.check_flag_states(
                db, emitted=report["emitted"]["flag_state"]),
            assertions.check_life_events(
                db, emitted=report["emitted"]["life_boundary"]),
            assertions.check_life_event_context(
                db,
                emitted=report["emitted"]["life_boundary_match"],
                match_id=((report.get("match") or {}).get("match_id")),
                half=((report.get("match") or {}).get("half")),
            ),
            assertions.check_capture_buffer(log_text),
            assertions.check_capture_health(
                db,
                match_id=((report.get("match") or {}).get("match_id")),
                half=((report.get("match") or {}).get("half")),
                # BreakDrive deliberately emits unmatched synthetic frag
                # markers to prove correlation failures are observable. They
                # are expected test evidence, not organic capture loss.
                expected_frag_correlation_failures=expected_frag_diagnostics,
            ),
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
                db, match_id=m["match_id"], kill_window=win))

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
        if report.get("match"):
            try:
                generated = generate_lane_b_report(
                    db, report["match"]["match_id"], args.match_report_dir,
                    expected_players=args.per_team * 2,
                    profile_path=args.report_profile,
                    objectives_path=args.map_objectives,
                )
                report["v5_match_report"] = summary_for_lane(generated)
            except Exception as exc:
                detail = f"{type(exc).__name__}: {exc}"
                report["v5_match_report"] = {
                    "status": "FAIL", "bundle_path": "match-report",
                    "detail": detail,
                }
                failures.append(f"v5_match_report: {detail}")
        if args.database_dump is not None:
            args.database_dump.parent.mkdir(parents=True, exist_ok=True)
            dump_args = [
                "mysqldump", "--no-defaults", f"--socket={db.socket_path}",
                "-u", "root", "--complete-insert", "--skip-extended-insert",
                "--no-tablespaces", db.database,
            ]
            with args.database_dump.open("wb") as dump_file:
                dumped = subprocess.run(
                    dump_args, stdout=dump_file, stderr=subprocess.PIPE,
                    text=False)
            if dumped.returncode != 0:
                raise SystemExit(
                    "mysqldump failed: "
                    + dumped.stderr.decode(errors="replace")[-1200:])
            report["database_dump"] = {
                "path": str(args.database_dump),
                "bytes": args.database_dump.stat().st_size,
            }

    report["failures"] = failures
    print("\n=== emitted in log vs recorded in db ===")
    e, rows = report["emitted"], report["rows"]
    for code in ("assist", "cap_break"):
        r = rows[code]
        print(f"  {code:<12} log={e[code]:<4} ppa={r['ppa']:<4} pa={r['pa']}")
    print(f"  {'assist ctx':<12} log={e['assist_context']:<4} "
          f"canonical={rows['assist_context']}")
    print(f"  {'frags':<12} log={e['frags']:<4} frags={rows['frags']}")
    print(f"  {'teamkills':<12} log={e['teamkills']:<4} "
          f"teamkills={rows['teamkills']}")
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
    summary = render_markdown(report)
    if report.get("bundle_provenance"):
        summary += "\n" + render_bundle_provenance_markdown(
            report["bundle_provenance"]
        )
    args.summary_out.write_text(summary, encoding="utf-8")
    print(f"wrote {args.out}")
    print(f"wrote {args.summary_out}")
    incomplete_release_evidence = args.require_complete_coverage and bool(gaps)
    return 1 if failures or incomplete_release_evidence else 0


if __name__ == "__main__":
    raise SystemExit(main())
