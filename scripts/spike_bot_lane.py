#!/usr/bin/env python3
"""Phase 0 spike for the stats-capture bot lane. Produces facts, not assertions.

Run this on the Tier 2 runner BEFORE any of the e2e assertions get written.

## Why a spike rather than just writing the tests

This repo has already paid for the alternative. `DODX_FORWARD_FIRING_DESIGN.md`
Phase 2 was written on the belief that `addbot` yields a playing bot, and three
tests shipped on it. They were skip-marked a day later (CHANGELOG 1.5.25) once
a real run showed DoD ships no bot AI at all. Everything downstream of "the
bots actually play" is cheap to write and worthless if the premise is wrong.

So this script answers the premise, in order, and stops at the first step that
fails. Its only output is what was observed.

## What it does NOT do

- Never touches the fleet-matching serverfiles tree (copies it; see
  ephemeral_tree.py for why that is load-bearing and how it is enforced).
- Never touches production MySQL. The database check spins a private mysqld.
- Never leaves a bot-enabled tree behind unless you pass --keep.

## Usage

    python3 scripts/spike_bot_lane.py \
        --serverfiles /opt/ktp-tier2-runner/serverfiles \
        --bot-kit ~/ktp-bot-kit \
        --bot marinebot \
        --map dod_anzio \
        --play-seconds 180 \
        --out spike-report.json

Add --skip-server to check only the MySQL/daemon half, or --skip-mysql for
only the bot half.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tests.e2e_stats import bot_driver  # noqa: E402
from tests.e2e_stats.bot_driver import BotKit, BotUnavailable  # noqa: E402
from tests.e2e_stats.ephemeral_mysql import EphemeralMysql, MysqlUnavailable  # noqa: E402
from tests.e2e_stats.ephemeral_tree import EphemeralTree  # noqa: E402
from tests.smoke.boot_subprocess import booted_subprocess  # noqa: E402

# Game-log line shapes we count to tell "bots are playing" from "bots exist".
# Deliberately loose: a strict pattern that drifts silently reports zero, which
# would read as "bots don't fight" when the truth is "the regex broke".
_PAT = {
    "connect":   re.compile(r'" connected, address'),
    "entered":   re.compile(r'" entered the game'),
    "joined":    re.compile(r'" joined team "'),
    "class":     re.compile(r'" changed role to "'),
    "killed":    re.compile(r'" killed "'),
    "attacked":  re.compile(r'" attacked "'),
    "triggered": re.compile(r'" triggered "'),
    "cap":       re.compile(r'triggered "(?:dod_)?(?:Allies|Axis)?_?[Cc]ap'),
    "suicide":   re.compile(r'committed suicide'),
    "ktpstats":  re.compile(r'\[KTP-STATS\]'),
    "dropped":   re.compile(r'\[KTP-STATS\] dropped'),
}


class SpikeFailure(RuntimeError):
    """A step answered 'no'. Recorded, then the run stops."""


class Report:
    def __init__(self) -> None:
        self.steps: list[dict] = []
        self.facts: dict = {}

    def step(self, name: str, ok: bool, detail: str, **facts) -> None:
        self.steps.append({"step": name, "ok": ok, "detail": detail, **facts})
        marker = "PASS" if ok else "FAIL"
        print(f"[{marker}] {name}: {detail}", flush=True)

    def dump(self, path: Path | None) -> None:
        payload = {"steps": self.steps, "facts": self.facts}
        text = json.dumps(payload, indent=2)
        if path:
            path.write_text(text, encoding="utf-8")
            print(f"\nreport written to {path}", flush=True)
        else:
            print("\n" + text, flush=True)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def _counts(text: str) -> dict[str, int]:
    return {k: len(p.findall(text)) for k, p in _PAT.items()}


def _spike_cfg(base_cfg: str, *, play: bool) -> str:
    """The smoke cfg plus what bot play needs.

    friendlyfire stays 0 (assist attribution only counts enemy damage, and TK
    handling is a separate concern). timelimit is pushed out so the map cannot
    cycle mid-observation, which would zero the counters and look like the
    bots stopped.
    """
    extra = [
        "",
        "// --- spike additions (scripts/spike_bot_lane.py) ---",
        "mp_timelimit 0",
        "mp_friendlyfire 0",
        "mp_limitteams 0",
        # Make sure the new capture code is on; it is cvar-gated and defaults
        # to 1, but a spike that silently ran with it off would be misleading.
        "ktp_stats_capture 1",
    ]
    return base_cfg + "\n".join(extra) + "\n"


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


def check_bot_kit(report: Report, kit_root: Path, bot: str, map_name: str) -> BotKit:
    kit = BotKit.locate(kit_root, bot)
    wp = kit.waypoint_path
    has_map_wp = kit.waypoints_for_map(map_name)
    report.step(
        "bot-kit-present", True,
        f"{kit.spec.name} .so at {kit.so_path} "
        f"(waypoints: {wp if wp else 'NONE'})",
        so_path=str(kit.so_path),
        waypoint_dir=str(wp) if wp else None,
        waypoints_for_map=has_map_wp,
    )
    if not has_map_wp:
        # Not fatal — some mods ship a single combined file, or auto-generate.
        # But it is the single likeliest explanation for bots that connect and
        # then stand still, so it must be visible in the report.
        report.step(
            "waypoints-for-map", False,
            f"no waypoint file mentions {map_name}. Bots may connect and not "
            f"move. If later steps show connects but no kills, start here.",
            map_name=map_name,
        )
    return kit


def check_stack_loads(report: Report, handle, tree_log: Path) -> None:
    """Bot loads as mm_gamedll — confirm Metamod is happy AND the production
    3-module set is still intact. A bot that loads by breaking amxx is not a
    usable test environment."""
    meta = handle.rcon("meta list")
    modules = handle.rcon("amxx modules")
    plugins = handle.rcon("amxx plugins")

    bad = [ln for ln in (meta + modules).splitlines()
           if re.search(r"bad load|fail", ln, re.I)]
    for name in ("amxxcurl", "reapi", "dodx"):
        if name not in modules.lower():
            raise SpikeFailure(
                f"module {name} missing from `amxx modules` with the bot loaded — "
                f"the bot is displacing the production module set:\n{modules}"
            )
    if bad:
        raise SpikeFailure("bad load / failure lines present:\n" + "\n".join(bad))

    report.step(
        "stack-intact-with-bot", True,
        "metamod up, amxxcurl+reapi+dodx all present, no bad loads",
        meta_list=meta.strip()[:2000],
        amxx_modules=modules.strip()[:2000],
        amxx_plugins=plugins.strip()[:2000],
    )


def check_bots_join(report: Report, handle, kit: BotKit, per_team: int) -> str:
    """The step `addbot` failed at: do bots connect, pick a team, and spawn?"""
    add_cmd = bot_driver.probe_add_command(handle.rcon, kit.spec)
    report.step("bot-add-command", True, f"{add_cmd!r} produces a connected player",
                add_command=add_cmd)

    players = bot_driver.fill_teams(
        handle.rcon, kit.spec, add_command=add_cmd, per_team=per_team,
    )
    report.step("bots-connected", True,
                f"{len(players)} connected: {players}",
                connected=players)

    hints = bot_driver.apply_objective_hints(handle.rcon, kit.spec)
    report.step("objective-hints", True,
                f"applied {hints}" if hints else "none accepted (non-fatal)",
                applied=hints)
    return add_cmd


def observe_play(report: Report, log_path: Path, seconds: int) -> dict[str, int]:
    """Watch the game log and count what the bots actually do.

    This is the fact the whole lane rests on. `entered`/`joined`/`class` prove
    bodies are in the world (what addbot could never do); `killed`/`attacked`
    prove combat, which is what assists need; `cap`/`triggered` prove objective
    play, which is what cap breaks need.
    """
    print(f"\n--- observing {seconds}s of bot play ---", flush=True)
    start_counts = _counts(_read(log_path))
    deadline = time.monotonic() + seconds
    last_print = 0.0
    while time.monotonic() < deadline:
        time.sleep(5.0)
        now = _counts(_read(log_path))
        delta = {k: now[k] - start_counts.get(k, 0) for k in now}
        if time.monotonic() - last_print > 20:
            print(f"    {delta}", flush=True)
            last_print = time.monotonic()

    final = _counts(_read(log_path))
    delta = {k: final[k] - start_counts.get(k, 0) for k in final}
    per_min = {k: round(v / (seconds / 60.0), 1) for k, v in delta.items()}

    report.facts["event_counts"] = delta
    report.facts["events_per_minute"] = per_min
    report.facts["observed_seconds"] = seconds

    if delta.get("entered", 0) == 0 and delta.get("joined", 0) == 0:
        raise SpikeFailure(
            "no bot entered the game or joined a team. This is precisely where "
            "`addbot` failed. Try the fallback bot (--bot new_bot) before "
            "changing anything else."
        )
    report.step("bots-in-world", True,
                f"{delta.get('joined', 0)} team joins, {delta.get('class', 0)} class picks, "
                f"{delta.get('entered', 0)} entered")

    if delta.get("killed", 0) == 0:
        raise SpikeFailure(
            f"bots are in the world but produced 0 kills in {seconds}s. Assists "
            "and cap breaks both key off deaths, so the lane cannot work yet. "
            "Check waypoint coverage for this map and the bot's skill/objective "
            "cvars."
        )
    report.step("bots-fight", True,
                f"{delta['killed']} kills, {delta.get('attacked', 0)} attack lines "
                f"({per_min['killed']}/min)")

    cap_activity = delta.get("cap", 0) + delta.get("triggered", 0)
    report.step("bots-play-objective", cap_activity > 0,
                f"{delta.get('cap', 0)} cap-ish lines, {delta.get('triggered', 0)} "
                f"triggered lines"
                + ("" if cap_activity else " — cap-break coverage NOT reachable yet"))

    if delta.get("dropped", 0):
        report.step("capture-buffer", False,
                    f"{delta['dropped']} [KTP-STATS] dropped line(s) — "
                    f"KSC_BUF_MAX_ENTRIES needs raising for this volume")
    else:
        report.step("capture-buffer", True, "no dropped capture lines")

    report.step("ktp-stats-lines", delta.get("ktpstats", 0) > 0,
                f"{delta.get('ktpstats', 0)} [KTP-STATS] log lines seen")
    return delta


def check_mysql(report: Report, schema_files: list[Path], seed_files: list[Path]) -> None:
    """Can a private mysqld run as this user, and does the migration SQL apply
    to an empty database?"""
    try:
        with EphemeralMysql.start() as db:
            report.step("mysqld-private-instance", True,
                        f"up on {db.socket_path} (port {db.port}), db={db.database}",
                        socket=str(db.socket_path), port=db.port)
            if not schema_files:
                report.step("schema-load", False,
                            "no schema files given (--schema); skipped the apply check")
                return
            db.prepare(schema_files=schema_files, seed_files=seed_files)
            report.step("schema-load", True,
                        f"applied {len(schema_files)} schema + {len(seed_files)} seed file(s) "
                        "to an empty database")
            tables = db.count(
                "SELECT COUNT(*) FROM information_schema.tables "
                f"WHERE table_schema='{db.database}'")
            report.facts["table_count"] = tables
            report.step("schema-tables", tables > 0, f"{tables} tables present")

            for code, pa, ppa in (("assist", "0", "1"), ("cap_break", "1", "0")):
                try:
                    db.assert_action_seeded(code, for_pa=pa, for_ppa=ppa)
                    report.step(f"seed-{code}", True,
                                f"one row, for_PlayerActions={pa} "
                                f"for_PlayerPlayerActions={ppa}, reward 0")
                except AssertionError as e:
                    report.step(f"seed-{code}", False, str(e))
    except MysqlUnavailable as e:
        report.step("mysqld-private-instance", False, str(e))
        raise SpikeFailure(str(e)) from e


# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--serverfiles", type=Path,
                    default=Path("/opt/ktp-tier2-runner/serverfiles"),
                    help="PRISTINE fleet-matching tree. Copied, never modified.")
    ap.add_argument("--bot-kit", type=Path, default=Path.home() / "ktp-bot-kit")
    ap.add_argument("--bot", default="marinebot", choices=sorted(bot_driver.SPECS))
    ap.add_argument("--map", default="dod_anzio")
    ap.add_argument("--per-team", type=int, default=3)
    ap.add_argument("--play-seconds", type=int, default=180)
    ap.add_argument("--copy-mode", default="hardlink", choices=("hardlink", "full"))
    ap.add_argument("--tree-parent", type=Path, default=None,
                    help="Where to build the ephemeral tree; must share a "
                         "filesystem with --serverfiles for hardlinks to work.")
    ap.add_argument("--schema", type=Path, nargs="*", default=[],
                    help="HLStatsX schema then migration .sql files, in order.")
    ap.add_argument("--seed", type=Path, nargs="*", default=[],
                    help="Action seed .sql files (assist, cap_break).")
    ap.add_argument("--skip-server", action="store_true")
    ap.add_argument("--skip-mysql", action="store_true")
    ap.add_argument("--keep", action="store_true",
                    help="Leave the ephemeral tree + datadir behind for inspection.")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    report = Report()
    report.facts["args"] = {k: str(v) for k, v in vars(args).items()}
    rc = 0

    try:
        if not args.skip_mysql:
            check_mysql(report, list(args.schema), list(args.seed))

        if not args.skip_server:
            kit = check_bot_kit(report, args.bot_kit, args.bot, args.map)

            base_cfg = (_REPO_ROOT / "tests" / "smoke" / "fixtures" / "test_server.cfg").read_text()
            with EphemeralTree.build(
                args.serverfiles,
                copy_mode=args.copy_mode,
                parent=args.tree_parent,
                keep=args.keep,
            ) as tree:
                report.step("ephemeral-tree", True,
                            f"{tree.path} ({args.copy_mode} from {tree.source})",
                            tree=str(tree.path))
                kit.stage_into(tree)
                tree.write_text("dod/spike_server.cfg", _spike_cfg(base_cfg, play=True))

                log_path = tree.path / "spike-hlds.log"
                with booted_subprocess(
                    tree.path,
                    map_name=args.map,
                    maxplayers=max(14, args.per_team * 2 + 2),
                    rcon_password="smoketest",
                    server_cfg="spike_server.cfg",
                    log_file=log_path,
                    boot_timeout=180.0,
                    extra_args=kit.hlds_extra_args(),
                ) as handle:
                    report.step("server-boot", True,
                                f"hlds up on :{handle.port} with "
                                f"{' '.join(kit.hlds_extra_args())}")
                    check_stack_loads(report, handle, log_path)
                    check_bots_join(report, handle, kit, args.per_team)
                    observe_play(report, log_path, args.play_seconds)

                    top = Counter(
                        re.findall(r'" killed "([^"]+)"', _read(log_path))
                    ).most_common(5)
                    report.facts["top_victims"] = top

    except (SpikeFailure, BotUnavailable) as e:
        report.step("spike", False, f"stopped: {e}")
        rc = 1
    except Exception as e:  # noqa: BLE001 — a spike reports, it doesn't crash
        report.step("spike", False, f"unexpected {type(e).__name__}: {e}")
        rc = 2

    report.dump(args.out)
    ok = sum(1 for s in report.steps if s["ok"])
    print(f"\n{ok}/{len(report.steps)} steps ok, exit {rc}", flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
