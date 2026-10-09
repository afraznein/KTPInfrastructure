#!/usr/bin/env python3
"""How much of its half does an HLTV demo actually contain?

An HLTV demo is NOT a complete record of its half. The proxy broadcasts
`delay` seconds behind live and the demo client writes the delayed stream, so
whatever is still in the world buffer when the level changes is freed unwritten
(`World::NewGame` -> `Reset`). A map-rotation change leaves the proxy idle long
enough to play its buffer out; a match `changelevel` at half end does not.
Measured 2026-09-26 over 24 S10 halves: 26.5-58.5 s missing, median 48.9.

This is the re-runnable form of that measurement -- the acceptance check for
the proxy-side fix, and the thing to point at when a demo-derived FINAL value
(score, winner, last capture) disagrees with the engine feed.

    # local archive, official demos filed in the last 3 days
    python3 -m scripts.demo_coverage --demos-root /home/hltvserver/hlds/dod/demos \\
        --types ktp --since-days 3 --database hlstatsx

    # a published demo, without downloading it: two HTTP range reads
    python3 -m scripts.demo_coverage --database hlstatsx \\
        --demos https://fastdl.ktpdod.com/demos/CHI1/ktp/ktp_1789953053-CHI1_h2-...dem

    # gate: fail if any half is short by more than 5 s
    python3 -m scripts.demo_coverage ... --max-loss 5

Playback length comes from the `.dem` directory entry at the tail of the file,
so a remote demo costs one range read for the 544-byte header and one for the
directory -- not a transfer.

LOSS IS A DIFFERENCE BETWEEN TWO SOURCES AND ONLY ONE OF THEM IS THE DEMO. The
half's end is taken from the ENGINE clock: every score row (schema 25,
stats_logging 1.26.1+) carries `round_time_left`, read off the game's own
mp_timelimit countdown, so `game_time + round_time_left` is the half end in the
same game_time frame the demo model uses. It holds to 0.1 s across a half and
nothing the producer decides about baselining can move it. `ktp_flag_state_events`
carries the same column and is used when a half has no score rows.

The old reference -- `ktp_life_events.reason='context_live'` plus --half-seconds
-- is kept ONLY as the fallback for halves with no clock (a producer before
1.26.1), and those rows print `assumed` in the `end_src` column. That reference is
written by the producer, not the engine: KTPMatchHandler 0.10.176 moved go-live
onto the real RoundState=1 and with it the first context_live row, which read as
a fleet-wide +10 s of demo loss with no demo changed. It also cannot see an
overtime or a short half, because the half length is assumed.

`live_at` is still printed so a producer-side move of context_live stays visible
beside the demo's own number.
"""
from __future__ import annotations

import argparse
import statistics
import struct
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

try:  # direct script execution
    from demo_team_score import DemoLabelError, parse_demo_name
    from team_score_telemetry import MysqlCli, MysqlCommandError
except ModuleNotFoundError:  # package import in tests/tooling
    from scripts.demo_team_score import DemoLabelError, parse_demo_name
    from scripts.team_score_telemetry import MysqlCli, MysqlCommandError

HEADER_SIZE = 544
ENTRY_SIZE = 92
DIRECTORY_OFFSET = 540  # last field of the header

# The demo's t=0 sits at this game_time: the proxy has been receiving for a few
# seconds by the time the first frame is written. Measured on S10 demos
# (infra-hidden-value-plays, 2026-09-26); it is a property of connect timing,
# not of the delay, so the fix does not move it.
DEMO_T0_GAME_TIME = 3.0

# Fallback only, for halves with no engine clock: the configured timelimit
# assumed, which is wrong for an overtime or short half.
HALF_SECONDS = 1200.0


class DemoFormatError(Exception):
    pass


@dataclass(frozen=True)
class Coverage:
    match_id: str
    half: int
    name: str
    track_time: float
    live_game_time: float | None
    half_seconds: float = HALF_SECONDS
    engine_half_end: float | None = None

    @property
    def covers_to(self) -> float:
        return DEMO_T0_GAME_TIME + self.track_time

    @property
    def end_source(self) -> str | None:
        if self.engine_half_end is not None:
            return "clock"
        return None if self.live_game_time is None else "assumed"

    @property
    def half_ends_at(self) -> float | None:
        if self.engine_half_end is not None:
            return self.engine_half_end
        return None if self.live_game_time is None else self.live_game_time + self.half_seconds

    @property
    def loss(self) -> float | None:
        end = self.half_ends_at
        return None if end is None else end - self.covers_to


def _read_local(path: Path, offset: int, length: int | None) -> bytes:
    with path.open("rb") as fh:
        fh.seek(offset)
        return fh.read() if length is None else fh.read(length)


def _read_http(url: str, offset: int, length: int | None) -> bytes:
    end = "" if length is None else str(offset + length - 1)
    request = urllib.request.Request(url, headers={"Range": f"bytes={offset}-{end}"})
    with urllib.request.urlopen(request, timeout=30) as response:
        if response.status != 206:
            # A server that ignores Range hands back the whole file; refusing is
            # better than silently pulling 200 MB per demo.
            raise DemoFormatError(f"{url}: range request returned {response.status}, not 206")
        return response.read()


def read_track_time(source: str | Path) -> float:
    """Playback length in seconds, from the demo's directory entry.

    Two reads, wherever the demo lives: the fixed-size header carries the
    directory's offset, and the directory is the tail of the file.
    """
    read = _read_http if isinstance(source, str) and source.startswith(("http://", "https://")) else _read_local
    target = source if read is _read_http else Path(source)

    header = read(target, 0, HEADER_SIZE)
    if len(header) < HEADER_SIZE or not header.startswith(b"HLDEMO"):
        raise DemoFormatError(f"{source}: not an HLDEMO file")

    (offset,) = struct.unpack_from("<i", header, DIRECTORY_OFFSET)
    if offset < HEADER_SIZE:
        raise DemoFormatError(f"{source}: directory offset {offset} inside the header")

    directory = read(target, offset, None)
    if len(directory) < 4:
        raise DemoFormatError(f"{source}: truncated directory")

    (count,) = struct.unpack_from("<i", directory, 0)
    if not 1 <= count <= 8 or len(directory) < 4 + count * ENTRY_SIZE:
        raise DemoFormatError(f"{source}: directory claims {count} entries, has {len(directory) - 4} bytes")

    # Entry 0 is the loading segment (signon, no elapsed time); the playback
    # segment is what a viewer sees. Take the longest rather than trusting the
    # type field, which some writers leave at 0 for both.
    times = [struct.unpack_from("<f", directory, 4 + i * ENTRY_SIZE + 76)[0] for i in range(count)]
    return max(times)


def live_game_times(cli: MysqlCli, match_ids: list[str]) -> dict[tuple[str, int], float]:
    """(match_id, half) -> game_time the half went live, from the engine feed."""
    if not match_ids:
        return {}
    quoted = _quoted(match_ids)
    rows = cli.execute(
        "SELECT match_id, half, MIN(game_time) FROM ktp_life_events "
        f"WHERE reason='context_live' AND match_id IN ({quoted}) "
        "GROUP BY match_id, half;"
    )
    out = {}
    for line in rows.splitlines():
        if not line.strip():
            continue
        match_id, half, game_time = line.split("\t")
        out[(match_id, int(half))] = float(game_time)
    return out


def _quoted(match_ids: list[str]) -> str:
    return ",".join("'" + m.replace("'", "''") + "'" for m in sorted(set(match_ids)))


def engine_half_ends(cli: MysqlCli, match_ids: list[str]) -> dict[tuple[str, int], float]:
    """(match_id, half) -> game_time the round clock reaches zero, from the engine.

    Median of `game_time + round_time_left` over the half's score rows, else its
    flag-state rows. A clock at 0 is excluded (an award after expiry reads late)
    and so is the producer's -1 for "no time limit".
    """
    if not match_ids:
        return {}
    quoted = _quoted(match_ids)
    rows = cli.execute(
        "SELECT 'score', match_id, half, game_time + round_time_left FROM ktp_score_events "
        f"WHERE match_id IN ({quoted}) AND round_time_left > 0 "
        "UNION ALL "
        "SELECT 'flag', match_id, half, game_time + round_time_left FROM ktp_flag_state_events "
        f"WHERE match_id IN ({quoted}) AND round_time_left > 0 AND is_initial = 0;"
    )
    ends: dict[tuple[str, int], dict[str, list[float]]] = {}
    for line in rows.splitlines():
        if not line.strip():
            continue
        source, match_id, half, end = line.split("\t")
        ends.setdefault((match_id, int(half)), {}).setdefault(source, []).append(float(end))
    return {key: statistics.median(by_source.get("score") or by_source["flag"])
            for key, by_source in ends.items()}


def collect_demos(args: argparse.Namespace) -> list[str | Path]:
    demos: list[str | Path] = list(args.demos)
    if args.demos_root:
        cutoff = None
        if args.since_days is not None:
            import time

            cutoff = time.time() - args.since_days * 86400
        for demo_type in args.types.split(","):
            for path in sorted(args.demos_root.glob(f"*/{demo_type.strip()}/*.dem")):
                if cutoff is None or path.stat().st_mtime >= cutoff:
                    demos.append(path)
    return demos


def measure(demos: list[str | Path], cli: MysqlCli | None, half_seconds: float = HALF_SECONDS) -> list[Coverage]:
    parsed = []
    for demo in demos:
        name = demo.rsplit("/", 1)[-1] if isinstance(demo, str) else demo.name
        try:
            meta = parse_demo_name(name)
        except DemoLabelError as exc:
            print(f"skip: {exc}", file=sys.stderr)
            continue
        parsed.append((demo, name, meta))

    ids = [m.match_id for _, _, m in parsed]
    live = live_game_times(cli, ids) if cli else {}
    clock = engine_half_ends(cli, ids) if cli else {}

    out = []
    for demo, name, meta in parsed:
        try:
            track_time = read_track_time(demo)
        except (OSError, DemoFormatError) as exc:
            print(f"skip: {exc}", file=sys.stderr)
            continue
        out.append(Coverage(meta.match_id, meta.half, name, track_time,
                            live.get((meta.match_id, meta.half)), half_seconds,
                            clock.get((meta.match_id, meta.half))))
    return out


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_argument_group("demos")
    src.add_argument("--demos", nargs="*", default=[], help="demo paths or https URLs")
    src.add_argument("--demos-root", type=Path, help="archive root laid out as <root>/<SERVER>/<type>/*.dem")
    src.add_argument("--types", default="ktp", help="comma-separated types under --demos-root (default: ktp = official)")
    src.add_argument("--since-days", type=float, help="with --demos-root: only files modified in the last N days")
    db = ap.add_argument_group("database")
    db.add_argument("--database", default="hlstatsx", help="schema holding ktp_life_events (default: hlstatsx)")
    db.add_argument("--defaults-extra-file", type=Path, help="MySQL option file with the credentials")
    db.add_argument("--no-database", action="store_true", help="report playback length only, no half clock")
    ap.add_argument("--half-seconds", type=float, default=HALF_SECONDS,
                    help=f"fallback half length for halves with no engine clock (default: {HALF_SECONDS:.0f})")
    ap.add_argument("--max-loss", type=float, help="exit 1 if any half loses more than this many seconds")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    demos = collect_demos(args)
    if not demos:
        print("no demos selected", file=sys.stderr)
        return 2

    cli = None
    if not args.no_database:
        cli = MysqlCli(database=args.database, defaults_extra_file=args.defaults_extra_file)

    try:
        rows = measure(demos, cli, args.half_seconds)
    except MysqlCommandError as exc:
        print(f"database: {exc}", file=sys.stderr)
        return 2

    if not rows:
        print("nothing measurable", file=sys.stderr)
        return 2

    # live_at is printed because loss is a difference between a producer-written
    # row and a demo; folding them leaves a producer-side shift of the reference
    # looking exactly like a demo regression.
    print(f"{'match':24} {'half':>4} {'live_at':>9} {'covers_to':>10} {'half_ends':>10} {'end_src':>8} {'loss_s':>8}")
    losses = []
    for row in sorted(rows, key=lambda r: (r.match_id, r.half)):
        live_at = "" if row.live_game_time is None else f"{row.live_game_time:9.1f}"
        end = "" if row.half_ends_at is None else f"{row.half_ends_at:10.1f}"
        loss = "" if row.loss is None else f"{row.loss:8.1f}"
        src = row.end_source or ""
        print(f"{row.match_id:24} {row.half:>4} {live_at:>9} {row.covers_to:10.1f} {end:>10} {src:>8} {loss:>8}")
        if row.loss is not None:
            losses.append(row.loss)

    if losses:
        print(f"\n{len(losses)} halves: min {min(losses):.1f} s, "
              f"median {statistics.median(losses):.1f} s, max {max(losses):.1f} s")
        assumed = sum(r.end_source == "assumed" for r in rows)
        print(f"half end: {len(losses) - assumed} from the engine round clock, "
              f"{assumed} assumed (context_live + {args.half_seconds:.0f} s, no clock on those rows)")
        if args.max_loss is not None and max(losses) > args.max_loss:
            print(f"FAIL: {sum(l > args.max_loss for l in losses)} halves lose more than "
                  f"{args.max_loss:.1f} s", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
