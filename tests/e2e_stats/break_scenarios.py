"""Drive cap-break scenarios and judge them, using KTPBreakDrive.

The deployment plan's Unit 3 lists one positive and four negatives, and says
plainly that the negatives matter more: a false-positive break silently
inflates a player's objective rating and nothing ever contradicts it. Bots
produce the positive by luck about half the time and the negatives never, so
this stages them.

## The invariant being tested

The detector's claim, stated as something checkable:

    a break is emitted for a flag **iff** a player of the capping team died
    while inside that flag's zone, causing the in-zone count to drop.

Each scenario makes one side of that true and asserts the other follows.

## Attribution, not counting — this file's main lesson

The first version counted `cap_break` lines inside a time window. That is
wrong, and it produced a confident report of a detector defect that did not
exist: a bot had killed a capper one second before the staged walk-off, so the
break in the window was entirely legitimate.

Two rules follow, and both are load-bearing:

1. **Match the breaker by name.** The staged kill logs the killer it injected;
   a break only counts as ours if it names that player. Unrelated breaks by
   other bots are noise and are ignored explicitly.
2. **Reject contaminated windows.** For the walk-off, which injects no killer
   at all and so has nothing to match on, the window is discarded unless the
   count dropped by exactly the one player moved AND nobody on the capping team
   died nearby. The lookback reaches backwards as well as forwards, because the
   detector holds a candidate for ~2.5s and a kill just *before* the walk-off is
   precisely what produces a legitimate break during it.

## Why scenarios report their own preconditions

A `near` kill that did not drop the in-zone count means the victim was not
really in the zone, so no break was owed and scoring it as missing would blame
the detector for a setup that never happened. Those are `not_staged` — neither
pass nor fail. Bot-driven setups fail to materialise often enough that treating
them as failures would drown the signal.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

_KILL_RE = re.compile(
    r"\[BD\] kill flag=(\d+) capteam=(-?\d+) mode=(\w+) victim=(\d+) "
    r"vname=(\S+) killer=(\d+) kname=(\S+) dist=(-?\d+) count_before=(-?\d+) "
    r"owner_before=(-?\d+)")
_WALKOFF_RE = re.compile(
    r"\[BD\] walkoff flag=(\d+) mover=(\d+) mname=(\S+) anchor=(\d+) "
    r"capteam=(-?\d+) count_before=(-?\d+)")
_AFTER_RE = re.compile(
    r"\[BD\] after flag=(\d+) allies=(-?\d+) axis=(-?\d+) capping=(-?\d+) "
    r"owner=(-?\d+)")
_ABORT_RE = re.compile(r"\[BD\] (\w+) ABORT flag=(-?\d+) (.*)")
_SCAN_RE = re.compile(
    r"\[BD\] flag (\d+) name=(\S+) owner=(-?\d+) capping=(-?\d+) "
    r"capteam=(-?\d+) allies=(-?\d+) axis=(-?\d+)")
_RESTART_QUEUE_RE = re.compile(
    r"\[BD\] restart_queue seq=(?P<seq>\d+) flag=(?P<flag>\d+) "
    r"fname=(?P<flag_name>\S+) capteam=(?P<capteam>-?\d+) "
    r"victim=(?P<victim>\d+) vname=(?P<victim_name>\S+) "
    r"killer=(?P<killer>\d+) killer_userid=(?P<killer_userid>\d+) "
    r"kname=(?P<killer_name>\S+) "
    r"dist=(?P<dist>-?\d+) count_before=(?P<count_before>-?\d+) "
    r"count_queued=(?P<count_queued>-?\d+) "
    r"frozen=(?P<frozen>\d+) "
    r"owner_before=(?P<owner_before>-?\d+) "
    r"restart_timer=(?P<restart_timer>-?\d+(?:\.\d+)?) "
    r"round_before=(?P<round_before>-?\d+(?:\.\d+)?) "
    r"drained=(?P<drained>[01])")
_RESTART_RESULT_RE = re.compile(
    r"\[BD\] restart_result seq=(?P<seq>\d+) flag=(?P<flag>\d+) "
    r"fname=(?P<flag_name>\S+) killer=(?P<killer>\d+) "
    r"killer_userid=(?P<killer_userid>\d+) "
    r"kname=(?P<killer_name>\S+) rebase=(?P<rebase>[01]) "
    r"completion=(?P<completion>[01]) "
    r"restart_timer=(?P<restart_timer>-?\d+(?:\.\d+)?) "
    r"round_before=(?P<round_before>-?\d+(?:\.\d+)?) "
    r"round_peak=(?P<round_peak>-?\d+(?:\.\d+)?) "
    r"round_after=(?P<round_after>-?\d+(?:\.\d+)?) "
    r"round_limit=(?P<round_limit>-?\d+(?:\.\d+)?) "
    r"count_before=(?P<count_before>-?\d+) "
    r"count_queued=(?P<count_queued>-?\d+) "
    r"count_after=(?P<count_after>-?\d+) "
    r"frozen=(?P<frozen>\d+) "
    r"owner_before=(?P<owner_before>-?\d+) "
    r"owner_after=(?P<owner_after>-?\d+) "
    r"contaminated=(?P<contaminated>[01]) flushed=(?P<flushed>[01])")
_RESTART_CONTAMINATION_RE = re.compile(
    r"\[BD\] restart_contamination seq=(?P<seq>\d+) "
    r"kind=(?P<kind>\w+)")

# Breaker NAME, so a break can be attributed to the kill that caused it.
_BREAK_RE = re.compile(r'"([^"<]*)<\d+><[^<>]*><[^<>]*>" triggered "cap_break"')
_BREAK_DETAIL_RE = re.compile(
    r'"(?P<breaker>[^"<]*)<(?P<userid>\d+)><[^<>]*><[^<>]*>" triggered '
    r'"cap_break" \(flag "(?P<flag>[^"]+)"\)')
# victim name and victim team, for the contamination check.
_KILLED_RE = re.compile(
    r'^L \S+ - (\d\d):(\d\d):(\d\d): "[^"<]*<\d+><[^<>]*><[^<>]*>" killed '
    r'"([^"<]*)<\d+><[^<>]*><([^<>]*)>"')
_TS_RE = re.compile(r"^L \S+ - (\d\d):(\d\d):(\d\d):")

TEAM_ALLIES, TEAM_AXIS = 1, 2
_TEAM_NAME = {TEAM_ALLIES: "Allies", TEAM_AXIS: "Axis"}


@dataclass
class Scenario:
    """One staged attempt and what came of it."""

    name: str
    status: str = "not_staged"      # ok | violation | not_staged
    detail: str = ""
    breaks_seen: int = 0
    extra: dict = field(default_factory=dict)


def _tail(log_text: str, since: int) -> str:
    return log_text[since:]


def _line_seconds(line: str) -> int | None:
    """Wall-clock seconds from the engine timestamp prefix."""
    m = _TS_RE.match(line)
    if not m:
        return None
    h, mi, sec = (int(v) for v in m.groups())
    return h * 3600 + mi * 60 + sec


class BreakDriver:
    """Stages scenarios over rcon and reads the verdict out of the game log."""

    # The detector emits on a 0.5s poll, then stats_logging may retain the
    # marker until its next 5s buffer flush.  The former 6s boundary raced that
    # flush in a real FULL run: the correct cap_break appeared in the very
    # second the harness declared it missing.  Seven seconds covers the full
    # production pipeline plus scheduler jitter without widening attribution.
    SETTLE = 7.0

    def __init__(self, handle, log_path):
        self.handle = handle
        self.log_path = log_path

    def _read(self) -> str:
        # Docker Desktop can expose a short ENODATA window while HLDS turns a
        # bind-mounted console log over. The file is readable again almost
        # immediately; retry instead of aborting a staged scenario.
        for attempt in range(10):
            try:
                return self.log_path.read_text(errors="replace")
            except OSError:
                if attempt == 9:
                    raise
                time.sleep(0.1)
        raise AssertionError("unreachable")

    def scan(self) -> list[dict]:
        """Current flag state, as the plugin sees it."""
        mark = len(self._read())
        self.handle.rcon("ktp_bd_scan")
        # Do not burn a fixed second here. A DoD capture can begin and finish
        # in only a few seconds, and that delay was enough for the positive
        # scenario to observe capping=1 but reach the kill command after the
        # capture had already completed. The scan terminator is emitted after
        # every flag row, so it is also the precise readiness signal we need.
        deadline = time.monotonic() + 1.5
        tail = ""
        while time.monotonic() < deadline:
            tail = _tail(self._read(), mark)
            if "[BD] scan done flags=" in tail:
                break
            time.sleep(0.05)
        out = []
        for m in _SCAN_RE.finditer(tail):
            f, name, owner, capping, capteam, allies, axis = m.groups()
            out.append({"flag": int(f), "name": name, "owner": int(owner),
                        "capping": int(capping), "capteam": int(capteam),
                        "allies": int(allies), "axis": int(axis)})
        return out

    def find_capturing_flag(self, *, timeout: float = 120.0,
                            poll: float = 4.0) -> dict | None:
        """Wait for a flag with a cap actually in progress. Diagnostic only —
        staged-kill scenarios use `_arm_kill` to avoid an RCON race."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for flag in self.scan():
                if flag["capping"] and flag["capteam"] in (TEAM_ALLIES, TEAM_AXIS):
                    occupants = (flag["allies"] if flag["capteam"] == TEAM_ALLIES
                                 else flag["axis"])
                    if occupants >= 1:
                        return flag
            time.sleep(poll)
        return None

    def _arm_kill(self, mode: str, *, timeout: float = 65.0,
                  poll: float = 0.1) -> bool:
        """Ask the diagnostic plugin to stage a kill on the next live cap.

        The plugin polls and executes inside HLDS, so observing a capture and
        killing its capper are no longer separated by two RCON round trips.
        Return only after the staged-kill or explicit-abort line is visible;
        the caller's settle window must begin when the kill actually happened,
        not when the arm command was sent.
        """
        mark = len(self._read())
        self.handle.rcon(f"ktp_bd_arm_kill {mode}")
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            tail = _tail(self._read(), mark)
            if _KILL_RE.search(tail):
                return True
            if _ABORT_RE.search(tail):
                return False
            time.sleep(poll)
        return False

    # -- scenarios ---------------------------------------------------------

    def positive_kill_on_point(self) -> Scenario:
        """A capper on the point is killed. A break must be emitted, and must
        name the killer we injected."""
        s = Scenario("positive_kill_on_point")
        mark = len(self._read())
        if not self._arm_kill("near"):
            tail = _tail(self._read(), mark)
            s.detail = (self._abort_reason(tail)
                        or "armed near kill did not stage within the wait")
            return s
        time.sleep(self.SETTLE)
        tail = _tail(self._read(), mark)

        staged = _KILL_RE.search(tail)
        if not staged:
            s.detail = self._abort_reason(tail) or "no kill was staged"
            return s

        capteam = int(staged.group(2))
        killer = staged.group(7)
        before = int(staged.group(9))
        owner_before = int(staged.group(10))
        after = self._count_after(tail, capteam)
        owner_after = self._owner_after(tail)
        breakers = _BREAK_RE.findall(tail)
        s.breaks_seen = len(breakers)
        s.extra = {"count_before": before, "count_after": after,
                   "owner_before": owner_before, "owner_after": owner_after,
                   "dist": int(staged.group(8)), "killer": killer,
                   "breakers": breakers}

        if after is None or after >= before:
            s.detail = (f"in-zone count did not drop ({before} -> {after}), so "
                        f"no break was owed - scenario did not stage")
            return s
        if owner_after is not None and owner_after != owner_before:
            # A completed capture deliberately suppresses the break: the
            # detector clears its queue on an owner flip so cappers leaving a
            # point they just took are not credited to whoever last got a kill
            # there. No break here is correct, not missing.
            s.detail = (f"the flag changed owner ({owner_before} -> "
                        f"{owner_after}) during the window, so the cap completed "
                        f"and the break is suppressed by design - scenario "
                        f"did not stage")
            return s
        if before - after != 1:
            # More than our victim left. The extra departures have unknown
            # causes, so neither a break nor its absence can be attributed.
            s.detail = (f"count dropped by {before - after} but only one player "
                        f"was killed, so others left for reasons this cannot "
                        f"account for - scenario contaminated")
            return s

        if killer in breakers:
            s.status = "ok"
            s.detail = (f"count {before} -> {after}; break credited to the "
                        f"injected killer {killer}")
        else:
            s.status = "violation"
            s.detail = (f"{killer} killed a capper on the point and the in-zone "
                        f"count dropped {before} -> {after}, but no cap_break "
                        f"names {killer}. MISSED break. Breaks this window: "
                        f"{breakers or 'none'}")
        return s

    def negative_off_point_kill(self) -> Scenario:
        """A capping-team player far from the point is killed.

        A candidate is queued and must age out. A break naming our killer would
        mean any kill during any cap is credited as a break.
        """
        s = Scenario("negative_off_point_kill")
        mark = len(self._read())
        if not self._arm_kill("far"):
            tail = _tail(self._read(), mark)
            s.detail = (self._abort_reason(tail)
                        or "armed far kill did not stage within the wait")
            return s
        time.sleep(self.SETTLE)
        tail = _tail(self._read(), mark)

        staged = _KILL_RE.search(tail)
        if not staged:
            s.detail = self._abort_reason(tail) or "no distant player to kill"
            return s

        capteam = int(staged.group(2))
        killer = staged.group(7)
        dist = int(staged.group(8))
        deaths = self._capping_deaths_near(
            tail, capteam, marker="[BD] kill flag=")
        breakers = _BREAK_RE.findall(tail)
        s.breaks_seen = len(breakers)
        s.extra = {"dist": dist, "count_before": int(staged.group(9)),
                   "killer": killer, "breakers": breakers,
                   "capping_team_deaths": deaths}

        if deaths:
            s.detail = ("off-point evidence window contains a real death on "
                        f"the capping team ({deaths}); an organic break "
                        "candidate could own any observed cap_break")
            return s

        if killer in breakers:
            s.status = "violation"
            s.detail = (f"killing a capping-team player {dist} units from the "
                        f"point credited {killer} with a cap_break. FALSE "
                        f"POSITIVE - the candidate is not ageing out, so any "
                        f"kill during any cap counts as a break.")
        else:
            s.status = "ok"
            s.detail = (f"kill {dist} units off the point produced no break for "
                        f"{killer}"
                        + (f"; unrelated breaks by {breakers} ignored"
                           if breakers else ""))
        return s

    def negative_voluntary_walkoff(self) -> Scenario:
        """A capper leaves the point alive. The count drops with no death.

        The plan calls this the hardest case, and it is also the easiest to
        mis-judge: there is no injected killer to attribute against, so the
        window has to be proven clean instead. See the module docstring.
        """
        s = Scenario("negative_voluntary_walkoff")
        mark = len(self._read())
        # Arm one in-process poller rather than scan then issue a second RCON.
        # Captures can finish inside that round trip. The plugin now observes
        # and moves the capper in the same server frame.
        self.handle.rcon("ktp_bd_arm_walkoff")
        ack_deadline = time.monotonic() + 3.0
        while time.monotonic() < ack_deadline:
            if "[BD] walkoff ARMED" in _tail(self._read(), mark):
                break
            time.sleep(0.1)
        else:
            s.detail = ("walkoff arm produced no acknowledgment; diagnostic "
                        "plugin is not running")
            return s
        deadline = time.monotonic() + 245.0
        while time.monotonic() < deadline:
            tail = _tail(self._read(), mark)
            if _WALKOFF_RE.search(tail) or "[BD] walkoff ABORT" in tail:
                break
            time.sleep(0.25)
        else:
            s.detail = "armed walkoff produced no result within 245s"
            return s
        time.sleep(self.SETTLE)
        full = self._read()
        tail = _tail(full, mark)

        staged = _WALKOFF_RE.search(tail)
        if not staged:
            s.detail = self._abort_reason(tail) or "nobody could be moved"
            return s

        capteam = int(staged.group(5))
        before = int(staged.group(6))
        after = self._count_after(tail, capteam)
        breakers = _BREAK_RE.findall(tail)
        s.breaks_seen = len(breakers)
        s.extra = {"count_before": before, "count_after": after,
                   "mover": staged.group(3), "breakers": breakers}

        if after is None or after >= before:
            s.detail = (f"the mover did not leave the zone ({before} -> "
                        f"{after}) - scenario did not stage")
            return s
        if before - after != 1:
            s.detail = (f"count dropped by {before - after} but only one player "
                        f"was moved, so the others left for reasons this cannot "
                        f"account for - scenario contaminated")
            return s

        deaths = self._capping_deaths_near(full, capteam)
        if deaths:
            s.extra["contaminating_deaths"] = deaths
            s.detail = (f"{len(deaths)} player(s) on the capping team "
                        f"({_TEAM_NAME.get(capteam, capteam)}) died within the "
                        f"window ({'; '.join(deaths)}), so a break here could "
                        f"be legitimate - scenario contaminated")
            return s

        if breakers:
            s.status = "violation"
            s.detail = (f"a capper walked off the point, nobody on that team "
                        f"died, the count dropped {before} -> {after}, and "
                        f"{breakers} were credited with a cap_break. FALSE "
                        f"POSITIVE - a count drop with no death behind it is "
                        f"being credited.")
        else:
            s.status = "ok"
            s.detail = (f"count dropped {before} -> {after} with no death on "
                        f"that team and no break, as required")
        return s

    def negative_clean_capture(self, *, timeout: float = 240.0) -> Scenario:
        """A cap completes with nobody killed; the cappers then walk off.

        Deployment plan Unit 3 step 2, and it exercises the `CA_owning_team`
        clear: when ownership flips the detector drops its queued candidates,
        so cappers leaving a point they just took are not credited to whoever
        last got a kill there. If that clear is not firing, **every successful
        capture produces a phantom break** — which is the highest-volume way
        this feature could be wrong.

        Observed rather than staged. Caps complete constantly under bots, and
        forcing one adds machinery without adding truth. The scenario is only
        scored when a completed capture is found whose window is clean of
        capping-team deaths — otherwise a break in that window could be
        perfectly legitimate and would be blamed on the clear.
        """
        s = Scenario("negative_clean_capture")
        before = {f["flag"]: f["owner"] for f in self.scan()}
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            time.sleep(6.0)
            mark = len(self._read())
            now = self.scan()
            flipped = [f for f in now
                       if f["flag"] in before and f["owner"] != before[f["flag"]]
                       and f["owner"] in (TEAM_ALLIES, TEAM_AXIS)]
            if not flipped:
                before = {f["flag"]: f["owner"] for f in now}
                continue

            flag = flipped[0]
            # The team that just took the point is the team whose players might
            # now be leaving it, so theirs are the deaths that matter.
            capper_team = flag["owner"]
            time.sleep(self.SETTLE)
            full = self._read()
            tail = _tail(full, mark)

            deaths = self._capping_deaths_near(full, capper_team,
                                               marker="ktp_bd_scan")
            breakers = _BREAK_RE.findall(tail)
            s.breaks_seen = len(breakers)
            s.extra = {"flag": flag["flag"], "new_owner": capper_team,
                       "breakers": breakers, "deaths_in_window": len(deaths)}

            if deaths:
                before = {f["flag"]: f["owner"] for f in now}
                s.detail = (f"flag {flag['flag']} changed hands but "
                            f"{len(deaths)} capping-team death(s) were nearby, "
                            f"so a break here could be legitimate — retrying")
                continue

            if breakers:
                s.status = "violation"
                s.detail = (f"flag {flag['flag']} was captured cleanly with no "
                            f"death on the capturing team, and {breakers} were "
                            f"credited with a cap_break. FALSE POSITIVE — the "
                            f"CA_owning_team clear is not firing, so every "
                            f"successful capture produces a phantom break.")
            else:
                s.status = "ok"
                s.detail = (f"flag {flag['flag']} captured cleanly (owner -> "
                            f"{capper_team}), no deaths on that team, no break")
            return s

        s.detail = "no capture completed cleanly within the wait"
        return s

    def negative_round_restart(self) -> Scenario:
        """Queue a near candidate, then prove a neutral round reset is clean.

        The diagnostic owns queueing and restart in one server frame. It
        drains the capture buffer before its queue marker and again before its
        result marker, making those markers a closed evidence window.
        """
        s = Scenario("negative_round_restart")
        mark = len(self._read())
        self.handle.rcon("ktp_bd_arm_restart")

        ack_deadline = time.monotonic() + 3.0
        while time.monotonic() < ack_deadline:
            if "[BD] restart ARMED" in _tail(self._read(), mark):
                break
            time.sleep(0.1)
        else:
            s.detail = ("restart arm produced no acknowledgment; diagnostic "
                        "plugin is not running")
            return s

        deadline = time.monotonic() + 68.0
        tail = ""
        while time.monotonic() < deadline:
            tail = _tail(self._read(), mark)
            queued = _RESTART_QUEUE_RE.search(tail)
            if queued:
                seq = queued.group("seq")
                if any(m.group("seq") == seq
                       for m in _RESTART_RESULT_RE.finditer(tail)):
                    break
            elif _ABORT_RE.search(tail):
                s.detail = self._abort_reason(tail) or "restart probe aborted"
                return s
            time.sleep(0.1)
        else:
            s.detail = ("restart probe did not produce a complete queue/result "
                        "evidence pair")
            if "[BD] restart_queue" in tail:
                s.extra["restart_issued"] = True
            return s

        return self._judge_round_restart(tail)

    @staticmethod
    def _judge_round_restart(tail: str) -> Scenario:
        """Judge one closed restart window and fail closed on ambiguity."""
        s = Scenario("negative_round_restart")
        queues = list(_RESTART_QUEUE_RE.finditer(tail))
        if len(queues) != 1:
            s.detail = (f"expected exactly one restart_queue marker, found "
                        f"{len(queues)}")
            if queues:
                s.extra["restart_issued"] = True
            return s
        queued = queues[0]
        seq = queued.group("seq")
        all_results = list(_RESTART_RESULT_RE.finditer(tail))
        results = [m for m in all_results
                   if m.group("seq") == seq and m.start() > queued.end()]
        if len(results) != 1 or len(all_results) != 1:
            s.detail = (f"expected exactly one restart_result for seq {seq}, "
                        f"found {len(results)} matching / "
                        f"{len(all_results)} total")
            s.extra = {"restart_issued": True, "seq": int(seq)}
            return s
        result = results[0]
        window = tail[queued.start():result.start()]

        all_breakers = _BREAK_RE.findall(window)
        breaks = [m.groupdict() for m in _BREAK_DETAIL_RE.finditer(window)]
        killed_lines = [line.strip() for line in window.splitlines()
                        if _KILLED_RE.match(line)]
        contamination = [m.group("kind")
                         for m in _RESTART_CONTAMINATION_RE.finditer(window)
                         if m.group("seq") == seq]
        s.breaks_seen = len(breaks)

        qints = {name: int(queued.group(name)) for name in (
            "flag", "killer", "killer_userid", "dist", "count_before",
            "count_queued", "frozen", "owner_before", "drained")}
        rints = {name: int(result.group(name)) for name in (
            "flag", "killer", "killer_userid", "rebase", "completion",
            "count_before", "count_queued", "count_after", "owner_before",
            "owner_after", "frozen", "contaminated", "flushed")}
        clocks = {name: float(result.group(name)) for name in (
            "restart_timer", "round_before", "round_peak", "round_after",
            "round_limit")}
        candidate = (queued.group("killer_name"),
                     queued.group("killer_userid"),
                     queued.group("flag_name"))
        exact = [b for b in breaks
                 if (b["breaker"], b["userid"], b["flag"]) == candidate]

        s.extra = {
            "restart_issued": True,
            "seq": int(seq),
            "flag": qints["flag"],
            "flag_name": queued.group("flag_name"),
            "killer": queued.group("killer_name"),
            "killer_userid": qints["killer_userid"],
            "breakers": breaks,
            "unparsed_breaks": len(all_breakers) - len(breaks),
            "contamination": contamination,
            "organic_kills": killed_lines,
            **clocks,
            **{f"queue_{k}": v for k, v in qints.items()},
            **{f"result_{k}": v for k, v in rints.items()},
        }

        repeated = ("flag", "killer", "killer_userid", "count_before",
                    "count_queued", "frozen", "owner_before")
        mismatched = [name for name in repeated
                      if qints[name] != rints[name]]
        if (queued.group("flag_name") != result.group("flag_name") or
                queued.group("killer_name") != result.group("killer_name") or
                float(queued.group("restart_timer")) !=
                clocks["restart_timer"] or
                float(queued.group("round_before")) != clocks["round_before"]):
            mismatched.append("snapshot")
        if mismatched:
            s.detail = ("restart queue/result identity mismatch: "
                        f"{', '.join(mismatched)}")
            return s
        if not qints["drained"] or not rints["flushed"]:
            s.detail = ("restart evidence window was not synchronously drained "
                        "at both boundaries")
            return s
        if contamination or killed_lines or rints["contaminated"]:
            s.detail = ("restart evidence window was contaminated by organic "
                        f"play (markers={contamination or 'none'}, "
                        f"kills={len(killed_lines)})")
            return s
        if len(all_breakers) != len(breaks):
            s.detail = ("restart evidence window contains a cap_break whose "
                        "actor/flag identity could not be parsed")
            return s
        if not (0 < qints["dist"] <= 512):
            s.detail = (f"queued candidate was not inside the production "
                        f"512-unit break radius (dist={qints['dist']})")
            return s
        if (qints["count_before"] < 1 or
                qints["count_queued"] != qints["count_before"]):
            s.detail = ("synthetic queue dispatch changed the engine capture "
                        f"count ({qints['count_before']} -> "
                        f"{qints['count_queued']})")
            return s
        if qints["frozen"] < qints["count_queued"]:
            s.detail = ("restart probe did not freeze enough capping-team "
                        f"players ({qints['frozen']} frozen for "
                        f"{qints['count_queued']} occupants)")
            return s
        if not rints["rebase"] or not rints["completion"]:
            s.detail = ("no authoritative dodx round-clock rebase/completion "
                        "was observed; mp_clan_restartround may have been ignored")
            return s
        projected_countdown = clocks["round_peak"] - clocks["round_limit"]
        if not (0.99 <= clocks["restart_timer"] <= 1.01
                and 0.01 < projected_countdown < 2.5):
            s.detail = ("tested restart countdown was not shorter than the "
                        "2.5-second break-candidate lifetime: "
                        f"timer={clocks['restart_timer']:.2f}, "
                        f"projected={projected_countdown:.2f}")
            return s
        if not (clocks["round_peak"] > clocks["round_limit"] + 0.01
                and clocks["round_peak"] > clocks["round_before"] + 0.01
                and clocks["round_limit"] - 5.0 <= clocks["round_after"]
                <= clocks["round_limit"] + 0.01):
            s.detail = ("restart clock markers do not prove a projected rebase "
                        "followed by authoritative completion")
            return s
        if rints["count_after"] != 0:
            s.detail = ("authoritative restart completed but the staged flag "
                        f"did not collapse to zero ({qints['count_queued']} -> "
                        f"{rints['count_after']})")
            return s
        if qints["owner_before"] != 0 or rints["owner_after"] != 0:
            s.detail = ("probe did not exercise the neutral 0 -> 0 owner case "
                        f"({qints['owner_before']} -> {rints['owner_after']}); "
                        "an owner-change clear would make this inconclusive")
            return s

        unrelated = [b for b in breaks if b not in exact]
        if unrelated:
            s.detail = ("restart evidence window contains cap_break activity "
                        f"unrelated to the exact queued actor/flag: {unrelated}")
            return s
        if exact:
            s.status = "violation"
            s.detail = (f"verified neutral restart collapsed flag "
                        f"{candidate[2]} {qints['count_queued']} -> 0 and "
                        f"credited queued actor {candidate[0]}<{candidate[1]}> "
                        "with cap_break. FALSE POSITIVE")
        else:
            s.status = "ok"
            s.detail = (f"authoritative neutral 0 -> 0 restart collapsed flag "
                        f"{candidate[2]} {qints['count_queued']} -> 0 with no "
                        "cap_break for the exact queued actor")
        return s

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _count_after(tail: str, capteam: int) -> int | None:
        m = _AFTER_RE.search(tail)
        if not m:
            return None
        return int(m.group(2)) if capteam == TEAM_ALLIES else int(m.group(3))

    @staticmethod
    def _owner_after(tail: str) -> int | None:
        m = _AFTER_RE.search(tail)
        return int(m.group(5)) if m else None

    @staticmethod
    def _capping_deaths_near(full_log: str, capteam: int,
                            window: int = 4,
                            marker: str = "[BD] walkoff") -> list[str]:
        """Deaths of capping-team players around the staged walk-off.

        Anchored on real timestamps rather than file offsets, and symmetric:
        the detector holds a candidate for ~2.5s, so a kill shortly *before*
        the walk-off is exactly what produces a legitimate break during it.
        """
        team = _TEAM_NAME.get(capteam)
        if not team:
            return []
        lines = full_log.splitlines()
        anchor = None
        for line in lines:
            if marker in line:
                anchor = _line_seconds(line) or anchor
        if anchor is None:
            return []

        out = []
        for line in lines:
            m = _KILLED_RE.match(line)
            if not m:
                continue
            t = _line_seconds(line)
            if t is None or abs(t - anchor) > window:
                continue
            if m.group(5) == team:
                out.append(f"{m.group(4)} at {m.group(1)}:{m.group(2)}:{m.group(3)}")
        return out

    @staticmethod
    def _abort_reason(tail: str) -> str | None:
        m = _ABORT_RE.search(tail)
        return f"plugin aborted: {m.group(3)}" if m else None


def run_all(handle, log_path, *, attempts: int = 3) -> list[dict]:
    """Every scenario, negatives first, retried until each one stages.

    Negatives first because a false positive is the failure that matters, and
    running the positive first would leave its break sitting in the window the
    negatives read.

    Retries because `not_staged` is common and cheap to fix by trying again.
    A verdict of ok or violation is final and stops the loop immediately —
    retrying past a violation would be shopping for a green run. The walkoff
    runs first and has a longer in-process watcher because it needs a naturally
    active capture; once found, the diagnostic isolates its evidence window
    from unrelated bot deaths.

    `attempts` dropped from 8 to 3 when the kill scenarios started arming an
    in-process poll for up to 60s rather than firing blind. The old 8×~10s
    outer schedule did the waiting badly: DoD's active-capture window can be
    only a few seconds, so a fixed retry mostly landed between captures.
    """
    d = BreakDriver(handle, log_path)
    out = []
    # negative_round_restart is LAST on purpose: it restarts the round out
    # from under everything else, so anything after it would be measuring a
    # server it did not set up.
    for fn in (d.negative_voluntary_walkoff,
               d.negative_off_point_kill,
               d.negative_clean_capture,
               d.positive_kill_on_point,
               d.negative_round_restart):
        s = None
        for attempt in range(1, attempts + 1):
            s = fn()
            # Once restart_queue exists the diagnostic has already issued a
            # real round restart. An inconclusive result is fail-closed and
            # one-shot; retrying would silently shop for a cleaner reset.
            if s.status != "not_staged" or s.extra.get("restart_issued"):
                break
            print(f"  scenario {s.name:<28} attempt {attempt}/{attempts} "
                  f"did not stage: {s.detail}", flush=True)
            time.sleep(4.0)
        s.extra["attempts"] = attempt
        print(f"  scenario {s.name:<28} {s.status:<12} {s.detail}", flush=True)
        out.append({"name": s.name, "status": s.status, "detail": s.detail,
                    "breaks_seen": s.breaks_seen, **s.extra})
    return out
