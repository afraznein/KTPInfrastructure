#!/usr/bin/env python3
"""Play a series of full KTP-shaped matches and persist the database.

Produces a **fixture** for KTPR work, not a pass/fail run. `lane_b_e2e.py`
answers "does the pipeline carry events"; this answers "here is a database
that looks like several real matches happened", so rating work has something
to read that was produced by the actual stack rather than hand-written.

## What a match here is

Two halves with the sides swapped between them, which is the KTP shape:

    setup -> pending -> live(half 1) -> [PLAY] -> end_first_half
          -> SWAP TEAMS -> live(half 2) -> [PLAY] -> end_match

One `match_id` spans both halves — that is production's shape, and it is what
makes per-half aggregation a real question rather than a synonym for
per-match.

## Why the roster is kept and the sides are swapped

The same bots play every match, changing sides at each halftime. A fixture
where a player only ever appears on one team cannot exercise the things KTPR
actually does: splitting one player's stats across two teams inside a match,
aggregating by half rather than by team, or joining a player to the side they
were on at the time. Keeping the roster also means the fixture has players
with history across several matches, which is what a rating consumes.

## Persistence

At the end, before the ephemeral MySQL is destroyed, the whole schema+data is
dumped alongside the game logs and a JSON manifest. The dump is the artifact;
the logs are there because every diagnosis in this project has started from
them, and `replay_daemon.py` can rebuild the database from a log without
re-running bots.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.e2e_stats import containment, log_invariants, metamod  # noqa: E402
from tests.e2e_stats.bot_driver import NEW_BOT  # noqa: E402
from tests.e2e_stats.ephemeral_mysql import EphemeralMysql  # noqa: E402
from tests.e2e_stats.hlstats_daemon import HlstatsDaemon  # noqa: E402
from tests.integration.match_flow import MatchDriver, MatchType  # noqa: E402
from tests.smoke.boot_subprocess import booted_subprocess  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lane_b_e2e import (BOOT_ATTEMPTS, add_bots, build_test_mode_matchhandler,  # noqa: E402
                        compile_sma, stage_tree)

_ROSTER_RE = re.compile(r"\[MD\] roster allies=(\d+) axis=(\d+) total=(\d+)")
_PLAYER_RE = re.compile(r"\[MD\] player id=(\d+) name=(\S+) team=(-?\d+)")


def read_roster(handle, log_path: Path, *, settle: float = 2.0) -> dict:
    """Ask the diagnostic who is on which team, and read the answer back."""
    mark = len(log_path.read_text(errors="replace"))
    handle.rcon("ktp_md_roster")
    time.sleep(settle)
    tail = log_path.read_text(errors="replace")[mark:]
    players = {m.group(2): int(m.group(3)) for m in _PLAYER_RE.finditer(tail)}
    totals = _ROSTER_RE.search(tail)
    return {"players": players,
            "allies": int(totals.group(1)) if totals else 0,
            "axis": int(totals.group(2)) if totals else 0}


def swap_teams(handle, log_path: Path) -> dict:
    """Swap sides and PROVE it took.

    The native can decline — a dead player, a team the mod refuses — and a
    silent no-op would produce a fixture that claims a halftime swap and does
    not have one. Comparing the roster before and after is the only way to
    know, so the result is returned rather than assumed.
    """
    before = read_roster(handle, log_path)
    handle.rcon("ktp_md_swap")
    time.sleep(4.0)
    after = read_roster(handle, log_path)

    moved = [n for n, t in after["players"].items()
             if n in before["players"] and before["players"][n] != t]
    stayed = [n for n, t in after["players"].items()
              if n in before["players"] and before["players"][n] == t]
    return {"before": before, "after": after,
            "moved": len(moved), "stayed": len(stayed),
            "stayed_names": stayed[:6]}


def play_half(*, seconds: int, log_path: Path, label: str,
              progress_every: int = 120) -> dict:
    """Run one half, reporting as it goes so a 20-minute half is not silent."""
    started = time.monotonic()
    body = log_path.read_text(errors="replace")
    start_kills = body.count('" killed "')

    elapsed = 0
    while elapsed < seconds:
        step = min(progress_every, seconds - elapsed)
        time.sleep(step)
        elapsed += step
        body = log_path.read_text(errors="replace")
        print(f"    {label} t+{elapsed // 60:>2}m  "
              f"kills={body.count(chr(34) + ' killed ' + chr(34)) - start_kills:<4} "
              f"assist={body.count('triggered ' + chr(34) + 'assist' + chr(34)):<4} "
              f"cap_break={body.count('triggered ' + chr(34) + 'cap_break' + chr(34)):<3}",
              flush=True)

    body = log_path.read_text(errors="replace")
    return {"seconds": round(time.monotonic() - started, 1),
            "kills": body.count('" killed "') - start_kills}


def run_one_match(handle, *, index: int, half_seconds: int, log_path: Path,
                  map_name: str, bot_skill: int | None = None) -> dict:
    """One match: two halves, sides swapped between them, one match_id."""
    driver = MatchDriver(handle)
    out: dict = {"index": index, "map": map_name}

    if bot_skill is not None:
        # Varied per match so the fixture contains a spread of per-player
        # performance rather than one difficulty. A rating that cannot tell a
        # strong player from a weak one is untestable against data where
        # everybody plays the same.
        handle.rcon(f"bot_skill {bot_skill}")
        out["bot_skill"] = bot_skill

    out["match_id"] = containment.assert_test_match_id(
        driver.setup_match(MatchType.COMPETITIVE, map_name))
    driver.advance_pending()
    driver.advance_live(1)
    driver.fire_match_start_log()
    print(f"  match {index}: {out['match_id']} live, half 1", flush=True)
    time.sleep(5.0)

    out["half1"] = play_half(seconds=half_seconds, log_path=log_path,
                             label=f"m{index}h1")

    # Halftime. end_first_half carries the half-1 scores into the plugin's own
    # state, which is what makes the second half a continuation rather than a
    # fresh match.
    driver.end_first_half(2, 1)
    out["swap"] = swap_teams(handle, log_path)
    print(f"  match {index}: halftime — {out['swap']['moved']} swapped, "
          f"{out['swap']['stayed']} stayed", flush=True)

    driver.advance_live(2)
    print(f"  match {index}: half 2 live", flush=True)
    time.sleep(5.0)
    out["half2"] = play_half(seconds=half_seconds, log_path=log_path,
                             label=f"m{index}h2")

    driver.end_match(2, 3)
    print(f"  match {index}: ended "
          f"({out['half1']['kills']} + {out['half2']['kills']} kills)", flush=True)
    return out


def dump_database(db, out_dir: Path) -> dict:
    """mysqldump the ephemeral instance before it is destroyed.

    Schema AND data: the point is a database someone can load and query, not a
    schema they would then have to populate. `--complete-insert` so a later
    schema change does not silently shift columns on load, which is the kind of
    corruption that looks like a rating bug.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    dump = out_dir / "hlstatsx-fixture.sql"
    argv = ["mysqldump", "--no-defaults", f"--socket={db.socket_path}",
            "-u", "root", "--complete-insert", "--skip-extended-insert",
            "--no-tablespaces", db.database]
    with dump.open("wb") as fh:
        r = subprocess.run(argv, stdout=fh, stderr=subprocess.PIPE, text=False)
    if r.returncode != 0:
        raise SystemExit(f"mysqldump failed: {r.stderr.decode(errors='replace')[-800:]}")
    return {"path": str(dump), "bytes": dump.stat().st_size,
            "inserts": dump.read_text(errors="replace").count("INSERT INTO")}


def summarise_db(db) -> dict:
    """The counts a KTPR author will want to sanity-check the fixture against."""
    def n(q):
        return db.count(q)
    return {
        "players": n("SELECT COUNT(*) FROM hlstats_Players"),
        "frags": n("SELECT COUNT(*) FROM hlstats_Events_Frags"),
        "frags_tagged": n("SELECT COUNT(*) FROM hlstats_Events_Frags "
                          "WHERE match_id IS NOT NULL"),
        "suicides": n("SELECT COUNT(*) FROM hlstats_Events_Suicides"),
        "teamkills": n("SELECT COUNT(*) FROM hlstats_Events_Teamkills"),
        "player_actions": n("SELECT COUNT(*) FROM hlstats_Events_PlayerActions"),
        "player_player_actions": n(
            "SELECT COUNT(*) FROM hlstats_Events_PlayerPlayerActions"),
        "matches_seen": db.sql(
            "SELECT match_id, half, COUNT(*) FROM hlstats_Events_Frags "
            "WHERE match_id IS NOT NULL GROUP BY match_id, half "
            "ORDER BY match_id, half").strip(),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--serverfiles", type=Path, default=Path("/opt/hlds"))
    ap.add_argument("--ktpamx-so", type=Path, required=True)
    ap.add_argument("--plugin", type=Path, required=True)
    ap.add_argument("--config-dir", type=Path, required=True)
    ap.add_argument("--server-cfg", type=Path,
                    default=Path("/work/tests/smoke/fixtures/test_server.cfg"))
    ap.add_argument("--hlstats", type=Path, required=True)
    ap.add_argument("--schema", type=Path, nargs="+", required=True)
    ap.add_argument("--seed", type=Path, nargs="*", default=[])
    ap.add_argument("--matchhandler-src", type=Path,
                    default=Path("/src/KTPMatchHandler"))
    ap.add_argument("--match-drive-sma", type=Path,
                    default=Path("/work/tests/e2e_stats/diagnostics/KTPMatchDrive.sma"))
    ap.add_argument("--map", default="dod_anzio")
    ap.add_argument("--matches", type=int, default=3)
    ap.add_argument("--half-seconds", type=int, default=1200,
                    help="length of each half; 1200 = the 20 minutes a real "
                         "KTP half runs")
    ap.add_argument("--per-team", type=int, default=6)
    ap.add_argument("--skills", default="",
                    help="comma-separated bot_skill per match, e.g. 3,5,7. "
                         "Cycles if shorter than --matches; empty leaves the "
                         "default alone")
    ap.add_argument("--port", type=int, default=27015)
    ap.add_argument("--log", type=Path, default=Path("/work/build/match-series.log"))
    ap.add_argument("--out-dir", type=Path,
                    default=Path("/work/build/ktpr-fixture"))
    args = ap.parse_args()

    total_min = args.matches * 2 * args.half_seconds / 60
    print(f"{args.matches} match(es), 2 x {args.half_seconds}s halves "
          f"= {total_min:.0f} minutes of play", flush=True)

    args.log.parent.mkdir(parents=True, exist_ok=True)
    args.log.unlink(missing_ok=True)
    report: dict = {"map": args.map, "matches_requested": args.matches,
                    "half_seconds": args.half_seconds, "matches": []}

    with EphemeralMysql.start() as db:
        db.prepare(schema_files=list(args.schema), seed_files=list(args.seed))
        db.assert_action_seeded("assist", for_pa="0", for_ppa="1")
        db.assert_action_seeded("cap_break", for_pa="1", for_ppa="0")
        HlstatsDaemon.repair_reconstructed_schema(db)
        HlstatsDaemon.ensure_server_row(db, address="127.0.0.1", port=args.port,
                                        min_players=2)

        report["containment"] = {
            "config_keys_checked": containment.assert_no_outbound_config(
                args.config_dir)}

        scripting = args.serverfiles / "dod/addons/ktpamx/scripting"
        mh = build_test_mode_matchhandler(
            args.matchhandler_src, Path("/tmp/KTPMatchHandler.amxx"),
            scripting=scripting)
        drive = compile_sma(args.match_drive_sma,
                            Path("/tmp/KTPMatchDrive.amxx"), scripting=scripting)
        print(f"compiled test-mode KTPMatchHandler + {drive.name}", flush=True)

        tree, dropped = stage_tree(
            args.serverfiles, ktpamx_so=args.ktpamx_so, plugin=args.plugin,
            config_dir=args.config_dir, server_cfg_fixture=args.server_cfg,
            break_drive=drive, matchhandler=mh)
        report["containment"]["plugins_dropped"] = dropped
        # stage_tree appends whatever it is handed as `break_drive` to
        # plugins.ini under its own filename, so the diagnostic loads.
        topo = metamod.enable_metamod(tree, bot_spec=NEW_BOT, host_ktpamx=False)

        daemon = HlstatsDaemon(
            script=args.hlstats, db_socket=db.socket_path, db_name=db.database,
            db_user="root", server_ip="127.0.0.1", server_port=args.port,
            log_source=args.log,
            stdout_path=args.out_dir / "hlstats.out", debug=1)
        daemon.start()

        booted = False
        for attempt in range(1, BOOT_ATTEMPTS + 1):
            try:
                with booted_subprocess(args.serverfiles, map_name=args.map,
                                       port=args.port,
                                       maxplayers=args.per_team * 2,
                                       rcon_password="smoketest",
                                       server_cfg="lane_b_server.cfg",
                                       log_file=args.log, boot_timeout=90.0,
                                       extra_args=topo.extra_args) as handle:
                    booted = True
                    print(f"server up (attempt {attempt})", flush=True)
                    add_bots(handle, per_team=args.per_team)
                    report["initial_roster"] = read_roster(handle, args.log)
                    print(f"roster: {report['initial_roster']['allies']} allies / "
                          f"{report['initial_roster']['axis']} axis", flush=True)

                    skills = [int(x) for x in args.skills.split(",") if x.strip()]
                    for i in range(1, args.matches + 1):
                        report["matches"].append(run_one_match(
                            handle, index=i, half_seconds=args.half_seconds,
                            log_path=args.log, map_name=args.map,
                            bot_skill=skills[(i - 1) % len(skills)] if skills else None))
                        # Between matches too, so a player's side is not
                        # correlated with match number across the fixture.
                        if i < args.matches:
                            swap_teams(handle, args.log)
                break
            except Exception as e:  # noqa: BLE001
                print(f"boot attempt {attempt} failed: {e}", flush=True)
        if not booted:
            daemon.stop()
            raise SystemExit("server never booted")

        daemon.drain(quiet_for=10.0, timeout=180.0)
        daemon.stop()

        log_text = args.log.read_text(errors="replace")
        report["emitted"] = {
            "kills": log_text.count('" killed "'),
            "assist": log_text.count('triggered "assist"'),
            "cap_break": log_text.count('triggered "cap_break"'),
            "suicide": log_text.count("committed suicide with"),
        }
        report["log_invariants"] = log_invariants.summarise(log_text)
        real_sql, benign_sql = daemon.classify_sql_errors()
        report["sql_errors"] = real_sql[:20]
        report["sql_errors_benign"] = benign_sql[:5]
        report["db"] = summarise_db(db)
        report["dump"] = dump_database(db, args.out_dir)

        # The log is part of the fixture: replay_daemon.py can rebuild the
        # database from it without bots, so the dump can be regenerated after a
        # schema change instead of re-running two hours of play.
        (args.out_dir / "match-series.log").write_text(log_text, errors="replace")

    (args.out_dir / "manifest.json").write_text(
        json.dumps(report, indent=2, default=str))

    print("\n=== fixture ===")
    for k, v in report["db"].items():
        if k != "matches_seen":
            print(f"  {k:<24} {v}")
    print("  match_id / half / frags:")
    for line in report["db"]["matches_seen"].splitlines()[1:]:
        print("    " + line)
    print(f"\n  dump: {report['dump']['path']} "
          f"({report['dump']['bytes']} bytes, "
          f"{report['dump']['inserts']} INSERTs)")
    if report["sql_errors"]:
        print(f"\n  {len(report['sql_errors'])} SQL error(s) — see manifest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
