#!/usr/bin/env python3
"""How much of its half does an HLTV demo actually contain?

THE TAILS ARE COMPLETE. This script used to say the opposite, and the earlier
claim -- "26.5-58.5 s missing, median 48.9" -- was this script measuring its own
anchor. It is refuted (`afraznein/KTPAMXX`#160) and the replacement is below.

What the old `loss` column did: it anchored every demo at a hardcoded
`DEMO_T0_GAME_TIME = 3.0` and reported `half_end - (3.0 + track_time)`. A demo
written through the play-out path does not start at game_time 3. The proxy
broadcasts `delay` seconds behind live, so when `record` is issued the demo's
first frame carries whatever the delay buffer is holding, and the demo's t=0
sits at the game_time of that frame -- MEASURED at a median of 52.3 s over 48
official halves. The constant charged that head offset to the tail, which is
where the "~49 s of missing play" came from.

AND THERE IS NO RIGHT CONSTANT, which is why this is not a different number.
`t0` is the buffer depth at the moment recording started, and that genuinely
varies: 38 of those 48 halves sit in [50,60), but four sit at ~0 (a proxy that
reconnected at the changelevel and had nothing to drain, so the demo covers the
whole level) and four sit between 20 and 40 (a partial drain). The old column's
NEGATIVE losses, impossible for a lost tail, were the ~0 cases.

So t0 is DERIVED per half rather than assumed: `t0 = half_end - track_time`.
That is only sound if the demo really does run to the half end, and the tail
check below is what licenses it -- it uses the filesystem and the file name, so
it shares no term with the game clock it is vouching for.

THE TAIL CHECK, which is the one that can fail. `tail_s =
(close_mtime - record_stamp) - track_time`. The stamp is the `YYMMDDHHMM` in the
demo's own name, so it is minute-granular and the test is a BAND, not a figure:
[0,60) is a complete tail, [60,120) is a 60 s tail freed unwritten at the level
change. Measured 2026-10-17 over the last 45 days: 105 of 105 official halves in
[0,60), median 33.0, none at or above 60. Independently reproduces #160's
2,292 of 2,294 across the whole corpus back to April.

A WRONG TIMEZONE FAILS THIS LOUDLY AND THAT IS DELIBERATE. The stamp carries no
zone; it is the recording host's local time. At the wrong offset every demo lands
out of band at once, so this script refuses rather than reporting a fleet of lost
tails -- see `--demo-tz`. A real tail loss is a minority of halves; an hour-sized
offset is all of them.

WHAT IS ACTUALLY MISSING IS THE HEAD, and `head_margin` is the column for it:
`live_at - t0`, how much of the demo sits in front of the moment play went live.
Measured over 46 halves: min 55.2 s, median 358.9 s, and NONE at or below zero,
because warmup is long. A half that went live within t0 of the map change would
begin un-recorded with nothing anywhere saying so, and `--max-head-gap` is the
gate for that.

    # local archive, official demos filed in the last 3 days
    python3 -m scripts.demo_coverage --demos-root /home/hltvserver/hlds/dod/demos \\
        --types ktp --since-days 3 --database hlstatsx

    # a published demo, without downloading it: two HTTP range reads
    python3 -m scripts.demo_coverage --database hlstatsx \\
        --demos https://fastdl.ktpdod.com/demos/CHI1/ktp/ktp_1789953053-CHI1_h2-...dem

    # gate: fail if a half began live with less than 30 s of demo in front of it
    python3 -m scripts.demo_coverage ... --max-head-gap 30

`--types` defaults to the official demos and a PROXY COMPARISON must not: the one
instance carrying a patched proxy is a practice box, so `ktp` alone gave it 2 halves
against 16 across all four types, and the question read as unanswerable.

Playback length comes from the `.dem` directory entry at the tail of the file,
so a remote demo costs one range read for the 544-byte header and one for the
directory -- not a transfer. A remote demo has no mtime, so `tail_s` comes from
`Last-Modified`; without that header the tail is reported unknown rather than
guessed, and `t0` is withheld with it.

The half's end is taken from the ENGINE clock: every score row (schema 25,
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
overtime or a short half, because the half length is assumed. A `t0` derived
against an `assumed` end inherits all of that, so it prints with the same flag.

A NEGATIVE t0 is the half-end model failing, not a demo that over-ran. Two of the
48 came back at -143.9 and -64.4 (live_at 1148 and 866 -- very late go-live), where
`track_time` exceeds the engine end. Those are the pause/overtime shapes the 1200 s
model never described, and they are reported rather than clamped.
"""
from __future__ import annotations

import argparse
import datetime as dt
import statistics
import struct
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo

try:  # direct script execution
    from demo_team_score import DemoLabelError, parse_demo_name
    from team_score_telemetry import MysqlCli, MysqlCommandError
except ModuleNotFoundError:  # package import in tests/tooling
    from scripts.demo_team_score import DemoLabelError, parse_demo_name
    from scripts.team_score_telemetry import MysqlCli, MysqlCommandError

HEADER_SIZE = 544
ENTRY_SIZE = 92
DIRECTORY_OFFSET = 540  # last field of the header

# The demo name's stamp is YYMMDDHHMM in the recording host's local time, so the
# tail test resolves to a minute and is read as a band of this width.
TAIL_BAND_SECONDS = 60.0

# The fleet records in US Eastern. Overridable, because the stamp itself carries
# no zone and a wrong one is indistinguishable from a lost tail on any single
# demo -- only the all-at-once shape tells them apart.
DEMO_STAMP_TZ = "America/New_York"

# Fallback only, for halves with no engine clock: the configured timelimit
# assumed, which is wrong for an overtime or short half.
HALF_SECONDS = 1200.0


class DemoFormatError(Exception):
    pass


def stamp_epoch(stamp: str, tz: ZoneInfo) -> float:
    """`YYMMDDHHMM` in the recording host's local time -> epoch seconds.

    DST is resolved per DATE rather than by one offset, so a demo from January
    and one from July both decode correctly. A fixed offset is what makes half
    the year read as a lost tail.
    """
    naive = dt.datetime.strptime(stamp, "%y%m%d%H%M")
    return naive.replace(tzinfo=tz).timestamp()


@dataclass(frozen=True)
class Coverage:
    match_id: str
    half: int
    name: str
    track_time: float
    live_game_time: float | None
    half_seconds: float = HALF_SECONDS
    engine_half_end: float | None = None
    recorded_at: float | None = None   # epoch, decoded from the name's stamp
    closed_at: float | None = None     # epoch, the file's mtime or Last-Modified

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
    def tail_s(self) -> float | None:
        """Wall-clock span of the recording minus what the demo plays back.

        Shares no term with the game clock, which is the point: it is what
        licenses reading `t0` off the engine end.
        """
        if self.recorded_at is None or self.closed_at is None:
            return None
        return (self.closed_at - self.recorded_at) - self.track_time

    @property
    def tail_verdict(self) -> str:
        tail = self.tail_s
        if tail is None:
            return "unknown"
        if tail < 0:
            return "early"            # closed before it could have recorded that much
        if tail < TAIL_BAND_SECONDS:
            return "complete"
        return "short"

    @property
    def t0(self) -> float | None:
        """game_time of the demo's first frame, derived rather than assumed.

        Withheld unless the tail is known complete: against a short tail this
        subtraction reports the lost tail as head offset and reads plausible.
        """
        end = self.half_ends_at
        if end is None or self.tail_verdict != "complete":
            return None
        return end - self.track_time

    @property
    def head_margin(self) -> float | None:
        """Seconds of demo in front of the moment play went live.

        At or below zero, live play began before the recording covers it.
        """
        t0 = self.t0
        return None if t0 is None or self.live_game_time is None else self.live_game_time - t0


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


def closed_at(source: str | Path) -> float | None:
    """When the recording was closed: mtime locally, `Last-Modified` remotely.

    None rather than a guess -- a missing header withholds the tail check and
    `t0` with it, instead of inventing a close time that would read as a verdict.
    """
    if isinstance(source, str) and source.startswith(("http://", "https://")):
        try:
            request = urllib.request.Request(source, method="HEAD")
            with urllib.request.urlopen(request, timeout=30) as response:
                header = response.headers.get("Last-Modified")
        except OSError:
            return None
        if not header:
            return None
        try:
            return dt.datetime.strptime(header, "%a, %d %b %Y %H:%M:%S %Z").replace(
                tzinfo=dt.timezone.utc).timestamp()
        except ValueError:
            return None
    try:
        return Path(source).stat().st_mtime
    except OSError:
        return None


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
        # nDirectoryOffset 0 is a recording killed mid-match, not a level change:
        # 3 of 2,297 demos in the corpus. The real tail losses all look like this.
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


def measure(demos: list[str | Path], cli: MysqlCli | None, half_seconds: float = HALF_SECONDS,
            tz_name: str = DEMO_STAMP_TZ) -> list[Coverage]:
    tz = ZoneInfo(tz_name)
    parsed = []
    for demo in demos:
        # A URL always splits on "/"; a local path given as a string must not,
        # or every demo on a Windows invocation reads as an unrecognised name.
        if isinstance(demo, str):
            name = demo.rsplit("/", 1)[-1] if demo.startswith(("http://", "https://")) else Path(demo).name
        else:
            name = demo.name
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
        try:
            recorded = stamp_epoch(meta.stamp, tz)
        except ValueError as exc:
            print(f"skip: {name}: stamp {meta.stamp!r} is not YYMMDDHHMM ({exc})", file=sys.stderr)
            continue
        out.append(Coverage(meta.match_id, meta.half, name, track_time,
                            live.get((meta.match_id, meta.half)), half_seconds,
                            clock.get((meta.match_id, meta.half)),
                            recorded, closed_at(demo)))
    return out


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_argument_group("demos")
    src.add_argument("--demos", nargs="*", default=[], help="demo paths or https URLs")
    src.add_argument("--demos-root", type=Path, help="archive root laid out as <root>/<SERVER>/<type>/*.dem")
    src.add_argument("--types", default="ktp", help="comma-separated types under --demos-root (default: ktp = official)")
    src.add_argument("--since-days", type=float, help="with --demos-root: only files modified in the last N days")
    src.add_argument("--demo-tz", default=DEMO_STAMP_TZ,
                     help=f"zone the name's YYMMDDHHMM stamp is in (default: {DEMO_STAMP_TZ})")
    db = ap.add_argument_group("database")
    db.add_argument("--database", default="hlstatsx", help="schema holding ktp_life_events (default: hlstatsx)")
    db.add_argument("--defaults-extra-file", type=Path, help="MySQL option file with the credentials")
    db.add_argument("--no-database", action="store_true", help="report playback length and the tail check only")
    ap.add_argument("--half-seconds", type=float, default=HALF_SECONDS,
                    help=f"fallback half length for halves with no engine clock (default: {HALF_SECONDS:.0f})")
    ap.add_argument("--max-head-gap", type=float,
                    help="exit 1 if any half went live with less than this many seconds of demo in front of it")
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
        rows = measure(demos, cli, args.half_seconds, args.demo_tz)
    except MysqlCommandError as exc:
        print(f"database: {exc}", file=sys.stderr)
        return 2

    if not rows:
        print("nothing measurable", file=sys.stderr)
        return 2

    # live_at is printed beside t0 because head_margin is the difference between a
    # producer-written row and a derived one; folding them leaves a producer-side
    # shift of context_live looking like a recording that started later.
    print(f"{'match':24} {'half':>4} {'live_at':>9} {'track_s':>9} {'half_ends':>10} "
          f"{'end_src':>8} {'tail_s':>7} {'tail':>9} {'t0':>7} {'head_margin':>12}")
    for row in sorted(rows, key=lambda r: (r.match_id, r.half)):
        live_at = "" if row.live_game_time is None else f"{row.live_game_time:9.1f}"
        end = "" if row.half_ends_at is None else f"{row.half_ends_at:10.1f}"
        tail = "" if row.tail_s is None else f"{row.tail_s:7.1f}"
        t0 = "" if row.t0 is None else f"{row.t0:7.1f}"
        margin = "" if row.head_margin is None else f"{row.head_margin:12.1f}"
        print(f"{row.match_id:24} {row.half:>4} {live_at:>9} {row.track_time:9.1f} {end:>10} "
              f"{row.end_source or '':>8} {tail:>7} {row.tail_verdict:>9} {t0:>7} {margin:>12}")

    known = [r for r in rows if r.tail_verdict != "unknown"]
    bad = [r for r in known if r.tail_verdict != "complete"]
    if known:
        print(f"\ntail: {len(known) - len(bad)} of {len(known)} complete "
              f"(wall span minus playback in [0,{TAIL_BAND_SECONDS:.0f}))")
    # Every demo out of band at once is a clock problem, not a fleet of lost
    # tails: the stamp carries no zone and an hour-sized offset moves all of them.
    # Refusing here is the difference between a bug report and a wrong headline.
    if known and len(bad) == len(known) and len(known) > 1:
        print(f"REFUSING: all {len(known)} halves are out of the tail band, which is what a wrong "
              f"--demo-tz looks like (currently {args.demo_tz}). A real tail loss is a minority.",
              file=sys.stderr)
        return 2
    for row in bad:
        print(f"tail {row.tail_verdict}: {row.name} ({row.tail_s:.1f} s)", file=sys.stderr)

    margins = [r.head_margin for r in rows if r.head_margin is not None]
    if margins:
        print(f"{len(margins)} halves with a derived t0: head margin min {min(margins):.1f} s, "
              f"median {statistics.median(margins):.1f} s, max {max(margins):.1f} s")
        assumed = sum(r.end_source == "assumed" and r.t0 is not None for r in rows)
        print(f"half end: {len(margins) - assumed} from the engine round clock, "
              f"{assumed} assumed (context_live + {args.half_seconds:.0f} s, no clock on those rows)")
        if args.max_head_gap is not None and min(margins) < args.max_head_gap:
            print(f"FAIL: {sum(m < args.max_head_gap for m in margins)} halves went live with less "
                  f"than {args.max_head_gap:.1f} s of demo in front of them", file=sys.stderr)
            return 1
    if bad:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
