#!/usr/bin/env python3
"""Replay a captured game log through hlstats.pl into an ephemeral MySQL.

The daemon leg of Lane B, without the bots. A full bot run costs four minutes
of wall clock and a container; this costs seconds and is deterministic, because
the input is a file someone already captured. Use it to answer "did the row
land?" while iterating, and to reproduce a nightly failure from its artifact
without re-rolling the dice on bot AI.

    scripts/replay_daemon.py \
        --log      build/patched.log \
        --hlstats  /repos/KTPHLStatsX/scripts/hlstats.pl \
        --schema   build/base-schema.sql \
        --seed     build/artifacts/sql/migrate_003_assist_action.sql \
                   build/artifacts/sql/migrate_004_cap_break_action.sql

Exits non-zero if the assertions fail, so it is usable as a check and not only
as a probe. `--no-assert` reports counts without judging them, which is what
you want when the question is "what DID happen".
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.e2e_stats import assertions, log_invariants  # noqa: E402
from tests.e2e_stats.ephemeral_mysql import EphemeralMysql  # noqa: E402
from tests.e2e_stats.hlstats_daemon import HlstatsDaemon  # noqa: E402


def _emitted(log_text: str) -> dict[str, int]:
    """What the game log itself contains, before the daemon sees it.

    Reported alongside the row counts because the two numbers together say
    *which side* lost an event. Lines present but rows absent is a daemon
    problem; neither present is a capture problem. Without both, a zero is
    ambiguous and the first hour of debugging goes to the wrong repo.
    """
    return {
        "kills": log_text.count('" killed "'),
        "assist": log_text.count('triggered "assist"'),
        "cap_break": log_text.count('triggered "cap_break"'),
        # Unit 1. The verb string is confirmed against real DoD logs:
        #   "Kazooie<10><0><Allies>" committed suicide with "grenade"
        "suicide": log_text.count('committed suicide with'),
        # Phase 5 retired the dedicated "headshot_kill" marker for
        # `(headshot "1")` as one property on the unconditional "frag_context"
        # marker every kill now emits.
        "headshot": log_text.count('(headshot "1")'),
        "damage": log_text.count('triggered "damage"'),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log", type=Path, required=True,
                    help="captured game log to replay")
    ap.add_argument("--hlstats", type=Path, required=True,
                    help="path to hlstats.pl")
    ap.add_argument("--schema", type=Path, nargs="+", required=True,
                    help="base schema; a production `mysqldump --no-data`")
    ap.add_argument("--seed", type=Path, nargs="*", default=[],
                    help="action seed migrations, applied before the daemon starts")
    ap.add_argument("--server-ip", default="127.0.0.1")
    ap.add_argument("--server-port", type=int, default=27015)
    ap.add_argument("--min-players", type=int, default=2)
    ap.add_argument("--rate", type=float, default=0.0,
                    help="seconds between lines; 0 feeds as fast as the daemon reads")
    ap.add_argument("--debug", type=int, default=1,
                    help="hlstats.pl debug level; 1 prints each event with its "
                         "(IGNORED) reason, which is what explains a zero")
    ap.add_argument("--no-assert", action="store_true",
                    help="report counts without failing on them")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--database-dump", type=Path, default=None,
                    help="write the replayed isolated database as SQL before teardown")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    log_text = args.log.read_text(encoding="utf-8", errors="replace")
    emitted = _emitted(log_text)
    print(f"replaying {args.log} — {len(log_text.splitlines())} lines, "
          f"{emitted['kills']} kills / {emitted['assist']} assist / "
          f"{emitted['cap_break']} cap_break")

    report: dict = {"log": str(args.log), "emitted": emitted,
                    "asserted": not args.no_assert}
    failures: list[str] = []

    with EphemeralMysql.start(keep=args.keep) as db:
        # Order is load-bearing: hlstats.pl caches hlstats_Actions and the
        # per-server config in memory at startup. Anything inserted after it
        # boots is not live, and the lines it would have matched are dropped
        # without an error.
        db.prepare(schema_files=list(args.schema), seed_files=list(args.seed))
        db.assert_action_seeded("assist", for_pa="0", for_ppa="1")
        db.assert_action_seeded("cap_break", for_pa="1", for_ppa="0")
        repairs = HlstatsDaemon.repair_reconstructed_schema(db)
        if repairs["columns"] or repairs["collation"]:
            print(f"repaired reconstructed hlstats_Servers: {repairs}")
        report["schema_repairs"] = repairs
        server_id = HlstatsDaemon.ensure_server_row(
            db, address=args.server_ip, port=args.server_port,
            min_players=args.min_players)
        print(f"seeded actions + server row (serverId={server_id}, IgnoreBots=0, "
              f"MinPlayers={args.min_players})")

        stdout_path = (args.out.parent if args.out else Path.cwd()) / "hlstats-replay.out"
        daemon = HlstatsDaemon(
            script=args.hlstats,
            db_socket=db.socket_path,
            db_name=db.database,
            db_user="root",
            server_ip=args.server_ip,
            server_port=args.server_port,
            # No file to tail — lines are pushed in below. Pointing log_source
            # at the replay file would double-feed it.
            log_source=Path("/nonexistent"),
            stdout_path=stdout_path,
            debug=args.debug,
        )
        daemon.start()
        daemon.stop_pump()
        print("daemon up")

        # Blank lines are not fed — the daemon has nothing to do with them, and
        # counting them would make a clean run look like it lost input.
        feedable = [ln for ln in log_text.splitlines() if ln.strip()]
        for line in feedable:
            daemon.feed_line(line)
            if args.rate:
                time.sleep(args.rate)
        print(f"fed {daemon.lines_fed}/{len(feedable)} non-blank lines "
              f"({len(log_text.splitlines())} in file); draining")
        daemon.drain(quiet_for=6.0, timeout=120.0)
        # stop() before reading died_early: the shutdown flush is where most
        # of the low-volume rows are actually written, and a shutdown that has
        # to be forced is itself a reason not to trust the counts.
        daemon.stop()
        died = daemon.died_early

        report["lines_fed"] = daemon.lines_fed
        if died:
            failures.append(died)

        sql_errors = daemon.sql_errors()
        report["sql_errors"] = sql_errors[:20]
        report["ignored"] = _ignored_reasons(stdout_path)
        report["rows"] = assertions.summarise(db)

        # Attribution negatives, from the log rather than the database: the log
        # is what capture emitted, so a violation here is a plugin bug and not
        # something the daemon did. Deployment plan Unit 2 steps 4-5 and Unit 3.
        report["log_invariants"] = log_invariants.summarise(log_text)
        for kind in ("assist_violations", "break_violations"):
            for v in report["log_invariants"][kind]:
                failures.append(v)

        # Two separate verdicts. `failures` are defects; coverage gaps are
        # scenarios the captured log never contained, which say nothing either
        # way and must not be dressed up as a pass or a defect.
        carried = [
            assertions.check_carried(db, "assist", emitted=emitted["assist"],
                                     table="hlstats_Events_PlayerPlayerActions",
                                     other_table="hlstats_Events_PlayerActions"),
            assertions.check_carried(db, "cap_break", emitted=emitted["cap_break"],
                                     table="hlstats_Events_PlayerActions",
                                     other_table="hlstats_Events_PlayerPlayerActions"),
            assertions.check_suicides_carried(db, emitted=emitted["suicide"]),
            assertions.check_headshots_carried(db, emitted=emitted["headshot"]),
            assertions.check_damage_ledger(db, emitted=emitted["damage"]),
        ]
        report["carried"] = carried
        report["coverage_gaps"] = [f"{c['code']}: {c['detail']}" for c in carried
                                   if c["status"] == "not_exercised"]

        if not args.no_assert:
            failures += [f"{c['code']}: {c['detail']}" for c in carried
                         if c["status"] == "pipeline"]
            for check in (
                lambda: assertions.assert_baseline_still_flows(db),
                lambda: assertions.assert_no_dropped_lines(log_text),
            ):
                try:
                    check()
                except AssertionError as e:
                    failures.append(str(e))
            if sql_errors:
                failures.append(f"{len(sql_errors)} SQL error(s) from the daemon:\n  "
                                + "\n  ".join(sql_errors[:5]))
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
    _print_report(report)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, indent=2, default=str))
        print(f"\nwrote {args.out}")
    return 1 if failures else 0


def _ignored_reasons(stdout_path: Path) -> dict[str, int]:
    """Tally the daemon's own `(IGNORED) <reason>:` output.

    This is the daemon telling you exactly why it dropped an event, and it is
    the difference between "capture is broken" and "IgnoreBots is 1".
    """
    tally: dict[str, int] = {}
    try:
        body = stdout_path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return tally
    for line in body.splitlines():
        if "(IGNORED)" not in line:
            continue
        reason = line.split("(IGNORED)", 1)[1].strip().split(":")[0].strip() or "unqualified"
        tally[reason] = tally.get(reason, 0) + 1
    return tally


def _print_report(report: dict) -> None:
    e, rows = report["emitted"], report["rows"]
    print("\n=== emitted in log vs recorded in db ===")
    print(f"  {'':<12} {'log':>6} {'ppa':>6} {'pa':>6}")
    for code in ("assist", "cap_break"):
        r = rows[code]
        print(f"  {code:<12} {e[code]:>6} {r['ppa']:>6} {r['pa']:>6}")
    print(f"  {'kills':<12} {e['kills']:>6} {rows['frags']:>6} (frags)")
    print(f"  {'suicide':<12} {e['suicide']:>6} {rows['suicides']:>6} (suicides)")
    print(f"  players {rows['players']} ({rows['bots']} bot)")

    for label, key in (("assist positions", "assist_positions"),
                       ("break positions", "break_positions")):
        print(f"  {label}: {rows[key]}")

    if report["ignored"]:
        print("\n=== daemon (IGNORED) reasons ===")
        for reason, n in sorted(report["ignored"].items(), key=lambda kv: -kv[1]):
            print(f"  {n:>5}  {reason}")

    gaps = report.get("coverage_gaps") or []
    if gaps:
        print(f"\n=== {len(gaps)} NOT EXERCISED ===")
        for g in gaps:
            print("  - " + g.replace("\n", "\n    "))
    if report["failures"]:
        print(f"\n=== {len(report['failures'])} FAILURE(S) ===")
        for f in report["failures"]:
            print("  - " + f.replace("\n", "\n    "))
    elif report.get("asserted") is False:
        # Without this the probe mode prints "all assertions passed" having run
        # none of them, which is the most misleading thing a test tool can say.
        print("\nassertions SKIPPED (--no-assert) — counts above are unjudged")
    elif gaps:
        print("\nno defects found, but this replay is INCOMPLETE — see above")
    else:
        print("\nall assertions passed")


if __name__ == "__main__":
    raise SystemExit(main())
