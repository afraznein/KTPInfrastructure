#!/usr/bin/env python3
"""Replay a captured game log through hlstats.pl and dump the resulting DB.

replay_daemon.py's offline-replay logic, plus lane_b_match_series.py's
mysqldump step. Exists for one reason: recovering a fixture from a raw game
log after the live run that produced it never reached its own dump step (e.g.
the host went away mid-run), without re-running hlds/bots.

    scripts/replay_and_dump.py \
        --log      build/match1-recovered.log \
        --hlstats  build/shared_daemon/hlstats.pl \
        --schema   build/base-schema.sql \
        --seed     build/artifacts/sql/migrate_003_assist_action.sql ... \
        --out-dir  build/recovered-fixture
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
    return {
        "kills": log_text.count('" killed "'),
        "assist": log_text.count('triggered "assist"'),
        "cap_break": log_text.count('triggered "cap_break"'),
        "suicide": log_text.count('committed suicide with'),
        "headshot": log_text.count('(headshot "1")'),
        "damage": log_text.count('triggered "damage"'),
    }


def dump_database(db, out_dir: Path) -> dict:
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--log", type=Path, required=True)
    ap.add_argument("--hlstats", type=Path, required=True)
    ap.add_argument("--schema", type=Path, nargs="+", required=True)
    ap.add_argument("--seed", type=Path, nargs="*", default=[])
    ap.add_argument("--server-ip", default="127.0.0.1")
    ap.add_argument("--server-port", type=int, default=27015)
    ap.add_argument("--min-players", type=int, default=2)
    ap.add_argument("--debug", type=int, default=1)
    ap.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args()

    log_text = args.log.read_text(encoding="utf-8", errors="replace")
    emitted = _emitted(log_text)
    print(f"replaying {args.log} — {len(log_text.splitlines())} lines, "
          f"{emitted['kills']} kills / {emitted['assist']} assist / "
          f"{emitted['cap_break']} cap_break")

    report: dict = {"log": str(args.log), "emitted": emitted}

    with EphemeralMysql.start(keep=True) as db:
        db.prepare(schema_files=list(args.schema), seed_files=list(args.seed))
        repairs = HlstatsDaemon.repair_reconstructed_schema(db)
        print(f"repaired reconstructed hlstats_Servers: {repairs}")
        server_id = HlstatsDaemon.ensure_server_row(
            db, address=args.server_ip, port=args.server_port,
            min_players=args.min_players)
        print(f"seeded actions + server row (serverId={server_id})")

        args.out_dir.mkdir(parents=True, exist_ok=True)
        daemon = HlstatsDaemon(
            script=args.hlstats,
            db_socket=db.socket_path,
            db_name=db.database,
            db_user="root",
            server_ip=args.server_ip,
            server_port=args.server_port,
            log_source=Path("/nonexistent"),
            stdout_path=args.out_dir / "hlstats-replay.out",
            debug=args.debug,
        )
        daemon.start()
        daemon.stop_pump()
        print("daemon up")

        feedable = [ln for ln in log_text.splitlines() if ln.strip()]
        for line in feedable:
            daemon.feed_line(line)
        print(f"fed {daemon.lines_fed}/{len(feedable)} non-blank lines; draining")
        daemon.drain(quiet_for=6.0, timeout=120.0)
        daemon.stop()
        died = daemon.died_early
        if died:
            print(f"WARNING: daemon died early: {died}")

        report["lines_fed"] = daemon.lines_fed
        report["sql_errors"] = daemon.sql_errors()[:20]
        report["rows"] = assertions.summarise(db)
        report["log_invariants"] = log_invariants.summarise(log_text)

        print("\n=== rows recorded ===")
        print(json.dumps(report["rows"], indent=2, default=str))

        report["dump"] = dump_database(db, args.out_dir)

    (args.out_dir / "manifest.json").write_text(
        json.dumps(report, indent=2, default=str))
    print(f"\n  dump: {report['dump']['path']} "
          f"({report['dump']['bytes']} bytes, {report['dump']['inserts']} INSERTs)")
    print(f"  manifest: {args.out_dir / 'manifest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())