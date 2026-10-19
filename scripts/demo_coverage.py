#!/usr/bin/env python3
"""How much of its half does an HLTV demo actually contain?

THE TAILS ARE COMPLETE AND THE HEAD IS WHAT IS MISSING. Two earlier instruments
here got this wrong in opposite directions and both read plausible, so the
reasoning is stated rather than assumed.

WHAT A PROXY DEMO LOOKS LIKE. The proxy broadcasts `delay` seconds behind live.
On a `changelevel` a master proxy with a delay set does not reconnect at once:
`Server::ParseStuffText` fires a world signal under `m_DelayReconnect` and
`Proxy::RunFrame` reconnects only once the spectator clock passes world time --
after the delay buffer has drained into the file through the ordinary write
path. So the recording rejoins about `delay` seconds into the new level, and the
demo's first frame carries that level age. That is the missing play, and it sits
at the HEAD. Nothing is freed unwritten at the tail.

THE RETIRED TAIL BAND, and why no band on those terms could have worked.
`tail_s = (close_mtime - record_stamp) - playback_length` was read as a verdict.
But `playback_length` is the directory's `fTrackTime`, which is wall time since
the demo's first write, so the expression reduces to `first_write - stamp` --
the stamp's own minute rounding and nothing else. A recording killed mid-half
shortens `close` and `fTrackTime` by the same amount and the difference does not
move, so the one failure it claimed to detect could not change its value. Its
observed spread filled the band edge to edge, which is the rounding
distribution, not a measurement of a demo.

THE TAIL TEST THAT CAN FAIL IS STRUCTURAL. `nDirectoryOffset` is written when
`DemoFile::Close()` writes the directory, so a recording killed before close has
no directory at all -- and such files are the only genuine tail losses in the
corpus. That is what `tail_verdict` now reads, and a truncated demo is a finding
rather than a skipped line on stderr. It needs no clock, no timezone and no
band, so it cannot be fooled by rounding.

T0 IS FITTED FROM TWO CLOCKS AND ASSUMES NO CONSTANT ANCHOR. The event tables
carry `event_epoch` beside `game_time`, so the offset between wall and game time
is recoverable from the half's own rows: `epoch_offset`, fitted at the START of
the half (see below), gives

    t0 = (closed_at - playback_length) - epoch_offset - broadcast_delay

where `closed_at - playback_length` is the wall moment of the first write and
`broadcast_delay` carries it back to the game time that frame was generated at.
Every term but the delay is measured per half. The delay is the proxy's
configured `delay`, not a residual fitted to make t0 come out, and the mechanism
above predicts `t0` itself lands near it -- so a wrong delay shows up in the
reported `t0`, which is the self-check printed at the end.

WHY THE FIT IS TAKEN AT THE START OF THE HALF. A tech pause freezes game time
while the wall clock runs, so `event_epoch - game_time` steps up at every pause
and is not one offset across a half. `t0` maps the FIRST write, so the fit
belongs in the half's opening window, where it is also before any pause. The
spread inside that window is the control: above `MAX_EPOCH_FIT_SPREAD` the two
clocks do not track, and `t0` is withheld instead of being averaged over a step.

WHAT REPLACED `loss`, and why that column could not be repaired. It anchored
every demo at a hardcoded `DEMO_T0_GAME_TIME = 3.0` and reported
`half_end - (3.0 + playback_length)`, so it measured the head offset and
reported it as the tail; its impossible NEGATIVE values were the halves whose
proxy had little to drain. There is no right constant, because t0 is the buffer
depth at reconnect and genuinely varies -- a half following a short map starts
much earlier in the level than one following a full-length map. `--max-loss` is
gone and stays gone.

WHY NOT `half_end - playback_length`. That was the previous derivation and it is
biased LOW, because the demo stops at the `changelevel` rather than at the
engine half end and the gap between them is not zero. Measured against demo
content -- every `DeathMsg` matched to `hlstats_Events_Frags` on killer and
victim SteamID -- it reads seconds under the truth, in the direction that makes
`head_margin` look safer than it is. The two-clock fit shares no term with the
half-end model and needs no engine clock at all, so it also covers halves whose
producer predates `round_time_left`.

HEAD MARGIN IS THE GATE. `head_margin = live_at - t0` is how much of the demo
sits in front of the moment play went live. At or below zero, live play began
before the recording covers it, with nothing else anywhere reporting it. On the
measured population it has never been near zero, because warmup is long -- the
exposure is a half that goes live within a delay's worth of a map change.
A half whose `head_margin` cannot be computed is NOT a pass: `--max-head-gap`
fails on it and names the reason, unless `--allow-unmeasured` says otherwise.

A NEGATIVE t0 means the recording began before this level loaded, so the half is
covered outright. It is reported, not clamped.

    # local archive, official demos filed in the last 3 days
    python3 -m scripts.demo_coverage --demos-root /home/hltvserver/hlds/dod/demos \
        --types ktp --since-days 3 --database hlstatsx

    # a published demo, without downloading it: two HTTP range reads
    python3 -m scripts.demo_coverage --database hlstatsx \
        --demos https://fastdl.ktpdod.com/demos/CHI1/ktp/ktp_1789953053-CHI1_h2-...dem

    # gate: fail if a half began live with less than 30 s of demo in front of it
    python3 -m scripts.demo_coverage ... --max-head-gap 30

`--types` defaults to the official demos, and two things follow from that. A
PROXY COMPARISON must not use it -- the one instance carrying a patched proxy is
a practice box, so `ktp` alone leaves the question unanswerable. And the
truncated demos in this corpus are mostly NOT official, which is exactly why the
old tail band was never exercised against a positive case: the positive set sat
outside the default scope.

Playback length comes from the `.dem` directory entry at the tail of the file,
so a remote demo costs one range read for the 544-byte header and one for the
directory -- not a transfer. A remote demo has no mtime, so `closed_at` comes
from `Last-Modified`; without that header `t0` is withheld rather than guessed.

The half's end is taken from the ENGINE clock where one exists: every score row
(schema 25, stats_logging 1.26.1+) carries `round_time_left` off the game's own
mp_timelimit countdown, so `game_time + round_time_left` is the half end in the
same frame the demo model uses. It is reported for context and no longer anchors
`t0`. `ktp_flag_state_events` carries the same column and is used when a half
has no score rows; the `context_live + --half-seconds` fallback prints `assumed`
and cannot see an overtime or a short half.
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

try:  # direct script execution
    from demo_team_score import DemoLabelError, parse_demo_name
    from team_score_telemetry import MysqlCli, MysqlCommandError
except ModuleNotFoundError:  # package import in tests/tooling
    from scripts.demo_team_score import DemoLabelError, parse_demo_name
    from scripts.team_score_telemetry import MysqlCli, MysqlCommandError

HEADER_SIZE = 544
ENTRY_SIZE = 92
DIRECTORY_OFFSET = 540  # last field of the header

# The proxy's configured broadcast delay, which carries the wall moment of the
# first write back to the game time that frame was generated at. A real cvar,
# uniform on this fleet -- not a residual fitted to make t0 come out.
BROADCAST_DELAY_SECONDS = 60.0

# The fit window at the start of a half, in game_time. Wide enough to hold
# warmup rows, early enough to be before any tech pause.
EPOCH_FIT_WINDOW_SECONDS = 120.0

# event_epoch is whole seconds against a sub-second game_time, so the offset's
# spread inside the window is about one second when the clocks track. Anything
# wider is a pause or a clock step, and t0 is withheld rather than averaged.
MAX_EPOCH_FIT_SPREAD = 2.0

# Fallback only, for halves with no engine clock: the configured timelimit
# assumed, which is wrong for an overtime or short half.
HALF_SECONDS = 1200.0


class DemoFormatError(Exception):
    pass


class DemoTruncatedError(DemoFormatError):
    """No usable directory: the recording was killed before it was closed.

    Separate from DemoFormatError because this one is a FINDING about a demo,
    not a file that was never a demo. Collapsing the two is how the real tail
    losses spent months as a skipped line on stderr.
    """


@dataclass(frozen=True)
class Coverage:
    match_id: str
    half: int
    name: str
    track_time: float | None           # None when the demo has no directory
    live_game_time: float | None
    half_seconds: float = HALF_SECONDS
    engine_half_end: float | None = None
    closed_at: float | None = None     # epoch, the file's mtime or Last-Modified
    epoch_offset: float | None = None  # fitted wall-minus-game offset for the half
    epoch_offset_spread: float | None = None
    broadcast_delay: float = BROADCAST_DELAY_SECONDS

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
    def tail_verdict(self) -> str:
        """Structural, from the directory the writer only writes at close."""
        return "truncated" if self.track_time is None else "complete"

    @property
    def unmeasured_reason(self) -> str | None:
        """Why t0 is withheld, so a half the gate cannot judge says which term is missing."""
        if self.track_time is None:
            return "no directory"
        if self.closed_at is None:
            return "no close time"
        if self.epoch_offset is None:
            return "no event rows"
        if self.epoch_offset_spread is not None and self.epoch_offset_spread > MAX_EPOCH_FIT_SPREAD:
            return f"clocks diverge by {self.epoch_offset_spread:.0f}s"
        return None

    @property
    def t0(self) -> float | None:
        """game_time of the demo's first frame, fitted rather than anchored.

        Negative means the recording began before this level loaded, which
        covers the half outright.
        """
        if self.unmeasured_reason is not None:
            return None
        return (self.closed_at - self.track_time) - self.epoch_offset - self.broadcast_delay

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

    None rather than a guess -- a missing header withholds `t0` instead of
    inventing a close time that would read as a verdict.
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
        raise DemoTruncatedError(f"{source}: nDirectoryOffset {offset}, killed before close")

    directory = read(target, offset, None)
    if len(directory) < 4:
        raise DemoTruncatedError(f"{source}: directory at {offset} is truncated")

    (count,) = struct.unpack_from("<i", directory, 0)
    if not 1 <= count <= 8 or len(directory) < 4 + count * ENTRY_SIZE:
        raise DemoTruncatedError(
            f"{source}: directory claims {count} entries, has {len(directory) - 4} bytes")

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


def epoch_offsets(cli: MysqlCli, match_ids: list[str],
                  window: float = EPOCH_FIT_WINDOW_SECONDS
                  ) -> dict[tuple[str, int], tuple[float, float]]:
    """(match_id, half) -> (wall-minus-game offset, its spread) at the half's start.

    `event_epoch` is whole seconds and `game_time` is not, so the offset over
    many rows approaches its true value from below: the MAX is the estimator and
    the spread is about one second when the clocks track. The window keeps the
    fit ahead of any tech pause, which steps the offset up mid-half.
    """
    if not match_ids:
        return {}
    quoted = _quoted(match_ids)
    rows = cli.execute(
        "SELECT e.match_id, e.half, MAX(e.event_epoch - e.game_time), "
        "       MAX(e.event_epoch - e.game_time) - MIN(e.event_epoch - e.game_time) "
        "FROM ktp_life_events e "
        "JOIN (SELECT match_id, half, MIN(game_time) AS g0 FROM ktp_life_events "
        f"      WHERE match_id IN ({quoted}) GROUP BY match_id, half) b "
        "  ON b.match_id = e.match_id AND b.half = e.half "
        f"WHERE e.match_id IN ({quoted}) AND e.game_time <= b.g0 + {window:.1f} "
        "GROUP BY e.match_id, e.half;"
    )
    out = {}
    for line in rows.splitlines():
        if not line.strip():
            continue
        match_id, half, offset, spread = line.split("\t")
        out[(match_id, int(half))] = (float(offset), float(spread))
    return out


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
            broadcast_delay: float = BROADCAST_DELAY_SECONDS) -> list[Coverage]:
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
    offsets = epoch_offsets(cli, ids) if cli else {}

    out = []
    for demo, name, meta in parsed:
        try:
            track_time = read_track_time(demo)
        except DemoTruncatedError as exc:
            # A row, not a skip: this IS the tail loss the script is looking for.
            print(f"truncated: {exc}", file=sys.stderr)
            track_time = None
        except (OSError, DemoFormatError) as exc:
            print(f"skip: {exc}", file=sys.stderr)
            continue
        offset, spread = offsets.get((meta.match_id, meta.half), (None, None))
        out.append(Coverage(meta.match_id, meta.half, name, track_time,
                            live.get((meta.match_id, meta.half)), half_seconds,
                            clock.get((meta.match_id, meta.half)),
                            closed_at(demo), offset, spread, broadcast_delay))
    return out


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_argument_group("demos")
    src.add_argument("--demos", nargs="*", default=[], help="demo paths or https URLs")
    src.add_argument("--demos-root", type=Path, help="archive root laid out as <root>/<SERVER>/<type>/*.dem")
    src.add_argument("--types", default="ktp",
                     help="comma-separated types under --demos-root (default: ktp = official)")
    src.add_argument("--since-days", type=float, help="with --demos-root: only files modified in the last N days")
    db = ap.add_argument_group("database")
    db.add_argument("--database", default="hlstatsx", help="schema holding ktp_life_events (default: hlstatsx)")
    db.add_argument("--defaults-extra-file", type=Path, help="MySQL option file with the credentials")
    db.add_argument("--no-database", action="store_true", help="report playback length and the tail check only")
    ap.add_argument("--half-seconds", type=float, default=HALF_SECONDS,
                    help=f"fallback half length for halves with no engine clock (default: {HALF_SECONDS:.0f})")
    ap.add_argument("--broadcast-delay", type=float, default=BROADCAST_DELAY_SECONDS,
                    help="the proxy's configured delay, which sets how far into a level a recording "
                         f"rejoins (default: {BROADCAST_DELAY_SECONDS:.0f})")
    gate = ap.add_argument_group("gate")
    gate.add_argument("--max-head-gap", type=float,
                      help="exit 1 if any half went live with less than this many seconds of demo in front of it")
    gate.add_argument("--allow-unmeasured", action="store_true",
                      help="with --max-head-gap: pass halves whose head margin could not be computed "
                           "(default: they fail, because an unjudged half is not a judged one)")
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
        rows = measure(demos, cli, args.half_seconds, args.broadcast_delay)
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
          f"{'end_src':>8} {'tail':>10} {'fit_sd':>7} {'t0':>7} {'head_margin':>12}")
    for row in sorted(rows, key=lambda r: (r.match_id, r.half)):
        live_at = "" if row.live_game_time is None else f"{row.live_game_time:9.1f}"
        track = "" if row.track_time is None else f"{row.track_time:9.1f}"
        end = "" if row.half_ends_at is None else f"{row.half_ends_at:10.1f}"
        spread = "" if row.epoch_offset_spread is None else f"{row.epoch_offset_spread:7.1f}"
        t0 = "" if row.t0 is None else f"{row.t0:7.1f}"
        margin = "" if row.head_margin is None else f"{row.head_margin:12.1f}"
        print(f"{row.match_id:24} {row.half:>4} {live_at:>9} {track:>9} {end:>10} "
              f"{row.end_source or '':>8} {row.tail_verdict:>10} {spread:>7} {t0:>7} {margin:>12}")

    truncated = [r for r in rows if r.tail_verdict == "truncated"]
    print(f"\ntail: {len(rows) - len(truncated)} of {len(rows)} closed with a directory "
          f"(a recording killed before close has none)")
    for row in truncated:
        print(f"tail truncated: {row.name}", file=sys.stderr)

    margins = [r.head_margin for r in rows if r.head_margin is not None]
    unmeasured = [r for r in rows if r.head_margin is None]
    if margins:
        print(f"head margin over {len(margins)} halves: min {min(margins):.1f} s, "
              f"median {statistics.median(margins):.1f} s, max {max(margins):.1f} s")
        fitted = [r.t0 for r in rows if r.t0 is not None]
        # The self-check: the delayed-reconnect path puts the first frame about a
        # delay into the level, so a wrong --broadcast-delay shows up right here.
        print(f"t0 median {statistics.median(fitted):.1f} s against a broadcast delay of "
              f"{args.broadcast_delay:.1f} s -- the delayed-reconnect path predicts these agree; "
              f"{sum(t < 0 for t in fitted)} halves began recording before the level loaded")
    # An unjudged half is not a judged one. Naming the missing term is what stops
    # this reading as a pass, which is how the retired band stayed invisible.
    if unmeasured:
        print(f"no head margin on {len(unmeasured)} of {len(rows)} halves:")
        for row in unmeasured:
            print(f"    {row.name}: {row.unmeasured_reason or 'no go-live row'}")

    failed = False
    if args.max_head_gap is not None:
        tight = [r for r in rows if r.head_margin is not None and r.head_margin < args.max_head_gap]
        if tight:
            print(f"FAIL: {len(tight)} halves went live with less than {args.max_head_gap:.1f} s "
                  f"of demo in front of them", file=sys.stderr)
            failed = True
        if unmeasured and not args.allow_unmeasured:
            print(f"FAIL: {len(unmeasured)} halves could not be judged against --max-head-gap "
                  f"(--allow-unmeasured to accept them)", file=sys.stderr)
            failed = True
    return 1 if failed or truncated else 0


if __name__ == "__main__":
    sys.exit(main())
