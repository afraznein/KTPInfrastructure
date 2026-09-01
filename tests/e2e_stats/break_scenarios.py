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
    r"owner_before=(-?\d+)(?: isolated=(\d+))?")
_WALKOFF_RE = re.compile(
    r"\[BD\] walkoff flag=(\d+) mover=(\d+) mname=(\S+) anchor=(\d+) "
    r"capteam=(-?\d+) count_before=(-?\d+)")
_AFTER_RE = re.compile(
    r"\[BD\] after flag=(\d+) allies=(-?\d+) axis=(-?\d+) capping=(-?\d+) "
    r"owner=(-?\d+)")
_ABORT_RE = re.compile(r"\[BD\] (\w+) ABORT flag=(-?\d+) (.*)")
_ISOLATION_END_RE = re.compile(r"\[BD\] isolation END\b")
_CLEAN_CAPTURE_BEGIN_RE = re.compile(
    r"\[BD\] clean_capture BEGIN flag=(?P<flag>\d+) "
    r"fname=(?P<flag_name>\S+) capteam=(?P<capteam>[12]) "
    r"owner_before=(?P<owner_before>-?\d+) "
    r"required=(?P<required>\d+) isolated=(?P<isolated>\d+) "
    r"roster=(?P<roster>\d+) "
    r"cappers=(?P<cappers>\d+(?:,\d+)*) "
    r"quiet_ms=(?P<quiet_ms>\d+) flushed=(?P<flushed>[01]) "
    r"userid_epoch=(?P<userid_epoch>\d+)")
_CLEAN_CAPTURE_RESULT_RE = re.compile(
    r"\[BD\] clean_capture RESULT flag=(?P<flag>\d+) "
    r"fname=(?P<flag_name>\S+) capteam=(?P<capteam>[12]) "
    r"owner_before=(?P<owner_before>-?\d+) "
    r"owner_after=(?P<owner_after>-?\d+) "
    r"required=(?P<required>\d+) isolated=(?P<isolated>\d+) "
    r"roster=(?P<roster>\d+) cappers=(?P<cappers>\d+(?:,\d+)*) "
    r"count_after=(?P<count_after>-?\d+) "
    r"deaths=(?P<deaths>\d+) flushed=(?P<flushed>[01]) "
    r"contaminated=(?P<contaminated>[01])")
_CANONICAL_FRAG_BEGIN_RE = re.compile(
    r"\[BD\] canonical_frag BEGIN killer=(?P<killer>\d+) "
    r"killer_userid=(?P<killer_userid>\d+) victim=(?P<victim>\d+) "
    r"victim_userid=(?P<victim_userid>\d+) roster=(?P<roster>\d+) "
    r"isolated=(?P<isolated>\d+) preflushed=(?P<preflushed>[01])")
_CANONICAL_FRAG_POSTFLUSH_RE = re.compile(
    r"\[BD\] canonical_frag POSTFLUSH killer=(?P<killer>\d+) "
    r"killer_userid=(?P<killer_userid>\d+) victim=(?P<victim>\d+) "
    r"victim_userid=(?P<victim_userid>\d+) weapon=(?P<weapon>\d+) "
    r"death_count=(?P<death_count>\d+) flush_ack=(?P<flush_ack>[01])")
_CANONICAL_FRAG_FACT_RE = re.compile(
    r"\[BD\] canonical_frag FACT killer=(?P<killer>\d+) "
    r"killer_userid=(?P<killer_userid>\d+) victim=(?P<victim>\d+) "
    r"victim_userid=(?P<victim_userid>\d+) weapon=(?P<weapon>\d+) "
    r"death_observed=(?P<death_observed>[01]) "
    r"preflushed=(?P<preflushed>[01]) postflushed=(?P<postflushed>[01])")
_CANONICAL_FRAG_RESULT_RE = re.compile(
    r"\[BD\] canonical_frag RESULT killer=(?P<killer>\d+) "
    r"killer_userid=(?P<killer_userid>\d+) victim=(?P<victim>\d+) "
    r"victim_userid=(?P<victim_userid>\d+) roster=(?P<roster>\d+) "
    r"isolated=(?P<isolated>\d+) respawned=(?P<respawned>[01]) "
    r"death_count=(?P<death_count>\d+) preflushed=(?P<preflushed>[01]) "
    r"postflushed=(?P<postflushed>[01])")
_CANONICAL_FRAG_ABORT_RE = re.compile(r"\[BD\] canonical_frag ABORT (?P<reason>.*)")
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
_SERIES_BEGIN_RE = re.compile(
    r"\[BD\] series BEGIN activation=(?P<activation>\d+) "
    r"userid_epoch=(?P<userid_epoch>\d+)")
_SERIES_ABORT_RE = re.compile(r"\[BD\] series ABORT reason=(?P<reason>\S+)")
_PLUGIN_LOAD_RE = re.compile(r"\[BD\] loaded")
_ENGINE_LOG_PREFIX = (
    r"^L \d{2}/\d{2}/\d{4} - \d{2}:\d{2}:\d{2}: "
)
_PLAYER_CAPTURE_RE = re.compile(
    _ENGINE_LOG_PREFIX
    + r'"(?P<name>[^"<]*)<(?P<userid>\d+)><[^<>]*>'
    + r'<(?P<team>[^<>]*)>" triggered a "dod_capture_area" - '
    + r'"(?P<flag_name>[^"]+)"\r?$',
    re.MULTILINE,
)
_ENGINE_KILL_RE = re.compile(
    _ENGINE_LOG_PREFIX
    + r'"(?P<killer_name>[^"<]*)<(?P<killer_userid>\d+)><[^<>]*>'
    + r'<(?P<killer_team>[^<>]*)>" killed '
    + r'"(?P<victim_name>[^"<]*)<(?P<victim_userid>\d+)><[^<>]*>'
    + r'<(?P<victim_team>[^<>]*)>" with "(?P<weapon>[^"]+)"',
    re.MULTILINE,
)
_FRAG_CONTEXT_RE = re.compile(
    _ENGINE_LOG_PREFIX
    + r'"(?P<killer_name>[^"<]*)<(?P<killer_userid>\d+)><[^<>]*>'
    + r'<(?P<killer_team>[^<>]*)>" triggered "frag_context" against '
    + r'"(?P<victim_name>[^"<]*)<(?P<victim_userid>\d+)><[^<>]*>'
    + r'<(?P<victim_team>[^<>]*)>" with "(?P<weapon>[^"]+)"',
    re.MULTILINE,
)
_MANIFEST_RE = re.compile(
    _ENGINE_LOG_PREFIX
    + r'KTP_CAPTURE_MANIFEST \(matchid "(?P<match_id>[^"\r\n]+)"\) '
    + r'\(half "(?P<half>\d+)"\) '
    + r'\(map "(?P<map>[^"\r\n]+)"\) '
    + r'\(producer "stats_logging"\) '
    + r'\(producer_version "(?P<producer_version>[^"\r\n]+)"\) '
    + r'\(schema "(?P<schema>\d+)"\) '
    + r'\(capabilities "(?P<capabilities>[^"\r\n]+)"\) '
    + r'\(position_interval "(?P<position_interval>\d+(?:\.\d+)?)"\) '
    + r'\(buffer_entries "(?P<buffer_entries>\d+)"\) '
    + r'\(life_buffer_entries "(?P<life_buffer_entries>\d+)"\) '
    # Schema 23 appends immutable map-revision provenance before the
    # sequence/epoch pair.  Keep the schema-22 shape valid while accepting
    # the two schema-23 fields only as a complete, ordered pair.
    + r'(?:\(map_revision_algorithm "sha256"\) '
    + r'\(map_revision "[0-9a-f]{64}"\) )?'
    + r'\(sequence "(?P<sequence>\d+)"\) '
    + r'\(event_epoch "(?P<event_epoch>\d+)"\)\r?$',
    re.MULTILINE,
)
_MATCH_START_RE = re.compile(
    _ENGINE_LOG_PREFIX
    + r'KTP_MATCH_START \(matchid "(?P<match_id>[^"\r\n]+)"\) '
    + r'\(map "(?P<map>[^"\r\n]+)"\) '
    + r'\(half "(?P<half>[^"\r\n]+)"\) '
    + r'\(type "(?P<match_type>-?\d+)"\)\r?$',
    re.MULTILINE,
)
_LIFECYCLE_BOUNDARIES = (
    ("half_end", re.compile(r"\bKTP_HALF_END\b")),
    ("match_end", re.compile(r"\bKTP_MATCH_END\b")),
    ("pfn_changelevel", re.compile(r"event=PFN_CHANGELEVEL_FIRED\b")),
    ("changelevel", re.compile(
        r"event=(?:CHANGELEVEL_HOOK_FIRED|PLUGIN_END_START)\b")),
)

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
REQUIRED_SYNTHETIC_SCENARIOS = (
    "negative_off_point_kill",
    "positive_kill_on_point",
    "negative_round_restart",
)


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
    # BreakDrive now creates the real capture precondition itself by freezing
    # the bot world and placing the required cappers inside one live capture
    # area. These waits are only a fail-closed allowance for the engine's area
    # poll; they are not a license to wait for random bot objective play.
    FAR_STAGE_TIMEOUT = 15.0
    KILL_STAGE_TIMEOUT = 15.0
    KILL_DISARM_TIMEOUT = 2.0
    MANIFEST_WAIT_TIMEOUT = 10.0
    SERIES_TIMEOUT = 300.0

    def __init__(self, handle, log_path):
        self.handle = handle
        self.log_path = log_path
        self.last_kill_disarm_ack: bool | None = None
        self.series_started = False
        self.series_mark = 0
        self.series_deadline: float | None = None
        self.series_manifest: tuple[str, int, int] | None = None
        self.series_abort_reason: str | None = None
        self.series_abort_ack: bool | None = None

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

    @staticmethod
    def _manifest_identity(log_text: str) -> tuple[str, int, int] | None:
        manifests = list(_MANIFEST_RE.finditer(log_text))
        if not manifests:
            return None
        latest = manifests[-1]
        return (
            latest.group("match_id"),
            int(latest.group("half")),
            int(latest.group("event_epoch")),
        )

    @staticmethod
    def _match_start_half(label: str) -> int | None:
        number = re.search(r"\d+", label)
        if not number:
            return None
        half = int(number.group())
        return 100 + half if "ot" in label.casefold() and half < 100 else half

    @classmethod
    def _current_diagnostic_manifest(
            cls, log_text: str) -> tuple[tuple[str, int, int] | None, str]:
        """Return the manifest bound to the latest diagnostic match start.

        AMXX 1.18.0 emitted the manifest before KTP_MATCH_START, while 1.18.1
        can emit start then manifest. Bind either order, but only inside the
        same plugin/match lifecycle interval. Foreign or duplicate manifests
        make the activation ambiguous and therefore cannot authorize any
        destructive BreakDrive command.
        """
        starts = list(_MATCH_START_RE.finditer(log_text))
        if not starts:
            return None, "current_match_start_missing"
        start = starts[-1]
        match_id = start.group("match_id")
        half = cls._match_start_half(start.group("half"))
        if half is None:
            return None, "current_match_half_unrecognized"
        if not match_id.endswith("-TEST"):
            return None, "current_match_not_diagnostic"

        boundary_matches = [
            match
            for _reason, pattern in _LIFECYCLE_BOUNDARIES
            for match in pattern.finditer(log_text)
        ]
        boundary_matches.extend(_PLUGIN_LOAD_RE.finditer(log_text))
        if any(boundary.start() >= start.end()
               for boundary in boundary_matches):
            return None, "current_match_lifecycle_closed"

        # The last lifecycle marker before this start is the earliest point at
        # which a manifest-before-start candidate can belong to this activation.
        # This excludes manifests left by a prior match or plugin activation.
        interval_start = max(
            (boundary.end() for boundary in boundary_matches
             if boundary.end() <= start.start()),
            default=0,
        )
        manifests = list(_MANIFEST_RE.finditer(log_text, interval_start))
        matching = []
        foreign = []
        for manifest in manifests:
            identity = (
                manifest.group("match_id"),
                int(manifest.group("half")),
                int(manifest.group("event_epoch")),
            )
            if identity[:2] == (match_id, half):
                matching.append(identity)
            else:
                foreign.append(identity)

        if len(matching) > 1:
            return None, "current_manifest_ambiguous"
        if foreign:
            return None, "current_manifest_foreign"
        if not matching:
            return None, "current_manifest_missing"
        return matching[0], ""

    def begin_series(self) -> bool:
        """Bind every diagnostic command to one live match/plugin/user epoch."""
        manifest_deadline = time.monotonic() + self.MANIFEST_WAIT_TIMEOUT
        manifest_reason = "current_manifest_missing"
        while True:
            full = self._read()
            self.series_manifest, manifest_reason = (
                self._current_diagnostic_manifest(full)
            )
            if self.series_manifest is not None:
                break
            if time.monotonic() >= manifest_deadline:
                self.series_abort_reason = manifest_reason
                return False
            time.sleep(0.05)

        self.series_mark = len(full)
        self.series_deadline = time.monotonic() + self.SERIES_TIMEOUT
        output = self.handle.rcon("ktp_bd_begin_series")
        if "KTP_BD_SERIES_BEGUN" in str(output or ""):
            self.series_started = True
            return True

        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if _SERIES_BEGIN_RE.search(_tail(self._read(), self.series_mark)):
                self.series_started = True
                return True
            time.sleep(0.05)
        self.series_abort_reason = "begin_not_acknowledged"
        return False

    def _boundary_reason(self) -> str | None:
        if not self.series_started:
            return self.series_abort_reason
        if (self.series_deadline is not None and
                time.monotonic() >= self.series_deadline):
            return "series_deadline"

        tail = _tail(self._read(), self.series_mark)
        boundaries: list[tuple[int, str]] = []
        for plugin_abort in _SERIES_ABORT_RE.finditer(tail):
            boundaries.append((
                plugin_abort.start(), plugin_abort.group("reason")
            ))
        # A second load marker after BEGIN proves that commands would be sent
        # to a different plugin activation, even if the map name is unchanged.
        plugin_load = tail.find("[BD] loaded")
        if plugin_load >= 0:
            boundaries.append((plugin_load, "plugin_reload"))
        for reason, pattern in _LIFECYCLE_BOUNDARIES:
            for boundary in pattern.finditer(tail):
                boundaries.append((boundary.start(), reason))

        for manifest in _MANIFEST_RE.finditer(tail):
            identity = (
                manifest.group("match_id"),
                int(manifest.group("half")),
                int(manifest.group("event_epoch")),
            )
            if identity != self.series_manifest:
                boundaries.append((
                    manifest.start(), "manifest_activation_epoch_change"
                ))
        return min(boundaries)[1] if boundaries else None

    def _request_series_abort(self, reason: str) -> bool:
        """Stop every in-plugin task and require the explicit cleanup ack."""
        if self.series_abort_reason is None:
            self.series_abort_reason = reason
        mark = len(self._read())
        output = self.handle.rcon(f"ktp_bd_abort_series {reason}")
        if "KTP_BD_SERIES_ABORTED" in str(output or ""):
            self.series_abort_ack = True
            return True
        deadline = time.monotonic() + self.KILL_DISARM_TIMEOUT
        while time.monotonic() < deadline:
            if "[BD] series ABORT" in _tail(self._read(), mark):
                self.series_abort_ack = True
                return True
            time.sleep(0.05)
        self.series_abort_ack = False
        return False

    def _series_live(self) -> bool:
        reason = self._boundary_reason()
        if reason is None:
            return True
        self._request_series_abort(reason)
        return False

    def _series_deadline_for(self, timeout: float) -> float:
        local = time.monotonic() + timeout
        return min(local, self.series_deadline) if self.series_deadline else local

    def _series_sleep(self, seconds: float, *, poll: float = 0.1) -> bool:
        deadline = self._series_deadline_for(seconds)
        while time.monotonic() < deadline:
            if not self._series_live():
                return False
            time.sleep(min(poll, max(0.0, deadline - time.monotonic())))
        return self._series_live()

    def _scenario_abort(self, scenario: Scenario) -> Scenario:
        scenario.detail = (
            f"diagnostic series aborted: {self.series_abort_reason or 'unknown'}"
        )
        scenario.extra.update({
            "series_abort": self.series_abort_reason or "unknown",
            "series_abort_ack": self.series_abort_ack,
        })
        return scenario

    def end_series(self) -> bool:
        if not self.series_started or self.series_abort_reason is not None:
            return self.series_abort_ack is not False
        output = self.handle.rcon("ktp_bd_end_series")
        self.series_started = False
        return "KTP_BD_SERIES_ENDED" in str(output or "")

    def canonical_diagnostic_frag(self, *, timeout: float = 35.0) -> Scenario:
        """Require one engine kill and its canonical producer marker.

        The plugin freezes the exact roster and drives one real bot weapon
        attack. A producer preflush closes prior play; its acknowledged
        postflush closes this factual window. The marker is allowed to appear
        after FACT in the file because stats_logging output is buffered, but it
        must exist exactly once before RESULT with the exact engine identity.
        """
        s = Scenario("canonical_diagnostic_frag")
        if self.series_started and not self._series_live():
            return self._scenario_abort(s)
        mark = len(self._read())
        self.handle.rcon("ktp_bd_stage_canonical_frag")
        deadline = self._series_deadline_for(timeout)
        tail = ""
        while time.monotonic() < deadline:
            if self.series_started and not self._series_live():
                return self._scenario_abort(s)
            tail = _tail(self._read(), mark)
            if (_CANONICAL_FRAG_RESULT_RE.search(tail)
                    or _CANONICAL_FRAG_ABORT_RE.search(tail)):
                break
            time.sleep(0.1)
        else:
            s.detail = "canonical engine frag produced no bounded result"
            return s

        abort = _CANONICAL_FRAG_ABORT_RE.search(tail)
        begins = list(_CANONICAL_FRAG_BEGIN_RE.finditer(tail))
        postflushes = list(_CANONICAL_FRAG_POSTFLUSH_RE.finditer(tail))
        facts = list(_CANONICAL_FRAG_FACT_RE.finditer(tail))
        results = list(_CANONICAL_FRAG_RESULT_RE.finditer(tail))
        if (len(begins) != 1 or len(postflushes) != 1
                or len(facts) != 1 or len(results) != 1):
            s.detail = (f"plugin aborted: {abort.group('reason')}" if abort else
                        "canonical frag did not emit one exact "
                        "begin/postflush/fact/result")
            return s

        begin, postflush, fact, result = (
            begins[0], postflushes[0], facts[0], results[0]
        )
        identity = ("killer", "killer_userid", "victim", "victim_userid")
        if any(begin.group(key) != postflush.group(key)
               or begin.group(key) != fact.group(key)
               or begin.group(key) != result.group(key)
               for key in identity):
            s.detail = ("canonical frag begin/postflush/fact/result identity "
                        "did not reconcile")
            return s
        if (begin.group("preflushed") != "1"
                or begin.group("roster") != begin.group("isolated")
                or postflush.group("flush_ack") != "1"
                or postflush.group("death_count") != "1"
                or postflush.group("weapon") != fact.group("weapon")
                or fact.group("death_observed") != "1"
                or fact.group("preflushed") != "1"
                or fact.group("postflushed") != "1"
                or result.group("respawned") != "1"
                or result.group("death_count") != "1"
                or result.group("preflushed") != "1"
                or result.group("postflushed") != "1"
                or int(result.group("roster")) < 2
                or result.group("roster") != result.group("isolated")
                or result.group("roster") != begin.group("roster")):
            s.detail = ("canonical frag flush/death contract did not restore "
                        "and freeze the exact roster")
            return s
        if not (begin.start() < postflush.start() < fact.start() < result.start()):
            s.detail = "canonical frag flush acknowledgment ordering was invalid"
            return s

        # The product buffer may append frag_context after FACT even though the
        # synchronous postflush call was acknowledged before FACT. RESULT is
        # therefore the closed evidence boundary, not FACT.
        factual_window = tail[begin.start():result.end()]
        kills = list(_ENGINE_KILL_RE.finditer(factual_window))
        contexts = list(_FRAG_CONTEXT_RE.finditer(factual_window))
        killer_userid = int(begin.group("killer_userid"))
        victim_userid = int(begin.group("victim_userid"))
        matching_kills = [row for row in kills
                          if int(row.group("killer_userid")) == killer_userid
                          and int(row.group("victim_userid")) == victim_userid]
        if len(kills) != 1 or len(matching_kills) != 1:
            s.detail = "diagnostic window did not contain one exact engine frag"
            return s
        kill = matching_kills[0]
        matching_contexts = [
            row for row in contexts
            if int(row.group("killer_userid")) == killer_userid
            and int(row.group("victim_userid")) == victim_userid
            and row.group("weapon") == kill.group("weapon")
        ]
        if (kill.start() <= 0 or any(row.start() <= kill.start()
                                    for row in matching_contexts)):
            s.detail = "canonical marker did not follow its factual engine frag"
            return s
        s.extra = {
            "killer_userid": killer_userid,
            "victim_userid": victim_userid,
            "weapon": kill.group("weapon"),
            "engine_frag_facts": len(matching_kills),
            "canonical_frag_markers": len(matching_contexts),
            "roster_players": int(result.group("roster")),
            "isolated_players": int(result.group("isolated")),
            "preflush_ack": True,
            "postflush_ack": True,
            "death_count": 1,
        }
        if len(contexts) != 1 or len(matching_contexts) != 1:
            s.status = "violation"
            s.detail = ("one factual engine frag did not emit one exact canonical "
                        "frag_context marker")
            return s
        s.status = "ok"
        s.detail = (f"one factual engine frag {killer_userid}->{victim_userid}:"
                    f"{kill.group('weapon')} emitted one canonical marker; exact "
                    f"{result.group('roster')}-player roster respawned and froze")
        return s

    def scan(self) -> list[dict]:
        """Current flag state, as the plugin sees it."""
        if self.series_started and not self._series_live():
            return []
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

    def _arm_kill(self, mode: str, *, timeout: float | None = None,
                  poll: float = 0.1) -> bool:
        """Ask the diagnostic plugin to stage a kill on the next live cap.

        The plugin polls and executes inside HLDS, so observing a capture and
        killing its capper are no longer separated by two RCON round trips.
        Return only after the staged-kill or explicit-abort line is visible;
        the caller's settle window must begin when the kill actually happened,
        not when the arm command was sent.
        """
        if timeout is None:
            timeout = (
                self.FAR_STAGE_TIMEOUT if mode == "far"
                else self.KILL_STAGE_TIMEOUT
            )
        self.last_kill_disarm_ack = None
        if self.series_started and not self._series_live():
            self.last_kill_disarm_ack = self._disarm_kill()
            return False
        mark = len(self._read())
        self.handle.rcon(f"ktp_bd_arm_kill {mode}")
        deadline = self._series_deadline_for(timeout)
        while time.monotonic() < deadline:
            if self.series_started and not self._series_live():
                self.last_kill_disarm_ack = self._disarm_kill()
                return False
            tail = _tail(self._read(), mark)
            if _KILL_RE.search(tail):
                return True
            if _ABORT_RE.search(tail):
                self.last_kill_disarm_ack = self._disarm_kill()
                return False
            time.sleep(poll)
        self.last_kill_disarm_ack = self._disarm_kill()
        return False

    def _disarm_kill(self) -> bool:
        """Stop the in-plugin poller and require an explicit acknowledgement."""
        mark = len(self._read())
        output = self.handle.rcon("ktp_bd_disarm_kill")
        if "KTP_BD_KILL_DISARMED" in str(output or ""):
            return True
        deadline = time.monotonic() + self.KILL_DISARM_TIMEOUT
        while time.monotonic() < deadline:
            if "[BD] kill DISARMED" in _tail(self._read(), mark):
                return True
            time.sleep(0.05)
        return False

    def _wait_for_isolation_end(self, since: int, *, timeout: float = 2.0,
                                poll: float = 0.05) -> tuple[bool, str]:
        """Wait for the diagnostic to restore bots after a closed window.

        Staged-kill isolation intentionally outlives ``SETTLE``. Waiting for
        its explicit end marker prevents adjudication from accepting organic
        play after restore and the next scenario from racing held bots.
        """
        deadline = time.monotonic() + timeout
        tail = _tail(self._read(), since)
        while not _ISOLATION_END_RE.search(tail) and time.monotonic() < deadline:
            if self.series_started and not self._series_live():
                return False, tail
            time.sleep(poll)
            tail = _tail(self._read(), since)
        closed = _ISOLATION_END_RE.search(tail)
        # The close marker is the exact evidence boundary. A single filesystem
        # read can also contain resumed organic play after restoration; never
        # let those later lines contaminate the adjudicated far-kill window.
        return bool(closed), tail[:closed.end()] if closed else tail

    # -- scenarios ---------------------------------------------------------

    def positive_kill_on_point(self) -> Scenario:
        """A capper on the point is killed. A break must be emitted, and must
        name the killer we injected."""
        s = Scenario("positive_kill_on_point")
        mark = len(self._read())
        if not self._arm_kill("near"):
            if self.series_abort_reason is not None:
                self.last_kill_disarm_ack = (
                    self.last_kill_disarm_ack
                    if self.last_kill_disarm_ack is not None
                    else self._disarm_kill()
                )
                s.extra["kill_disarm_ack"] = self.last_kill_disarm_ack
                return self._scenario_abort(s)
            tail = _tail(self._read(), mark)
            s.detail = (self._abort_reason(tail)
                        or "armed near kill did not stage within the wait")
            s.extra["kill_disarm_ack"] = self.last_kill_disarm_ack
            if self.last_kill_disarm_ack is not True:
                s.detail += "; kill poller disarm was not acknowledged"
            return s
        if self.series_started and not self._series_sleep(self.SETTLE):
            return self._scenario_abort(s)
        if not self.series_started:
            time.sleep(self.SETTLE)
        isolation_closed, tail = self._wait_for_isolation_end(mark)
        if self.series_abort_reason is not None:
            return self._scenario_abort(s)

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
                   "breakers": breakers,
                   "isolated_players": int(staged.group(11) or 0)}

        if s.extra["isolated_players"] < 2:
            s.detail = ("positive evidence window was not isolated from "
                        "organic bot play")
            return s

        if not isolation_closed:
            s.detail = ("positive evidence window did not emit its isolation "
                        "close marker; bots may still be held")
            return s

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
            if self.series_abort_reason is not None:
                self.last_kill_disarm_ack = (
                    self.last_kill_disarm_ack
                    if self.last_kill_disarm_ack is not None
                    else self._disarm_kill()
                )
                s.extra["kill_disarm_ack"] = self.last_kill_disarm_ack
                return self._scenario_abort(s)
            tail = _tail(self._read(), mark)
            s.detail = (self._abort_reason(tail)
                        or "armed far kill did not stage within the wait")
            s.extra["kill_disarm_ack"] = self.last_kill_disarm_ack
            if self.last_kill_disarm_ack is not True:
                s.detail += "; kill poller disarm was not acknowledged"
            return s
        if self.series_started and not self._series_sleep(self.SETTLE):
            return self._scenario_abort(s)
        if not self.series_started:
            time.sleep(self.SETTLE)
        isolation_closed, tail = self._wait_for_isolation_end(mark)
        if self.series_abort_reason is not None:
            return self._scenario_abort(s)

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
                   "capping_team_deaths": deaths,
                   "isolated_players": int(staged.group(11) or 0)}

        if s.extra["isolated_players"] < 2:
            s.detail = ("off-point evidence window was not isolated from "
                        "organic bot play")
            return s

        if not isolation_closed:
            s.detail = ("off-point evidence window did not emit its isolation "
                        "close marker; bots may still be held")
            return s

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
        if self.series_started and not self._series_live():
            return self._scenario_abort(s)
        mark = len(self._read())
        # Arm one in-process poller rather than scan then issue a second RCON.
        # Captures can finish inside that round trip. The plugin now observes
        # and moves the capper in the same server frame.
        self.handle.rcon("ktp_bd_arm_walkoff")
        ack_deadline = time.monotonic() + 3.0
        while time.monotonic() < ack_deadline:
            if self.series_started and not self._series_live():
                return self._scenario_abort(s)
            if "[BD] walkoff ARMED" in _tail(self._read(), mark):
                break
            time.sleep(0.1)
        else:
            s.detail = ("walkoff arm produced no acknowledgment; diagnostic "
                        "plugin is not running")
            return s
        deadline = self._series_deadline_for(15.0)
        while time.monotonic() < deadline:
            if self.series_started and not self._series_live():
                return self._scenario_abort(s)
            tail = _tail(self._read(), mark)
            if _WALKOFF_RE.search(tail) or "[BD] walkoff ABORT" in tail:
                break
            time.sleep(0.25)
        else:
            s.detail = "deterministic walkoff produced no result within 15s"
            return s
        if self.series_started and not self._series_sleep(self.SETTLE):
            return self._scenario_abort(s)
        if not self.series_started:
            time.sleep(self.SETTLE)
        isolation_closed, tail = self._wait_for_isolation_end(mark)
        if self.series_abort_reason is not None:
            return self._scenario_abort(s)
        full = self._read()

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
                   "mover": staged.group(3), "breakers": breakers,
                   "isolation_closed": isolation_closed}

        if not isolation_closed:
            s.detail = ("walkoff evidence window did not emit its isolation "
                        "close marker; bots may still be held")
            return s

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

    def negative_clean_capture(self, *, timeout: float = 45.0) -> Scenario:
        """Stage a real engine ownership transition in a frozen bot world."""
        s = Scenario("negative_clean_capture")
        if self.series_started and not self._series_live():
            return self._scenario_abort(s)
        mark = len(self._read())
        self.handle.rcon("ktp_bd_arm_clean_capture")
        deadline = self._series_deadline_for(timeout)
        while time.monotonic() < deadline:
            if self.series_started and not self._series_live():
                return self._scenario_abort(s)
            tail = _tail(self._read(), mark)
            if (_CLEAN_CAPTURE_RESULT_RE.search(tail)
                    or "[BD] clean_capture ABORT" in tail):
                break
            time.sleep(0.1)
        else:
            s.detail = "deterministic clean capture produced no result"
            return s

        isolation_closed, tail = self._wait_for_isolation_end(mark)
        if self.series_abort_reason is not None:
            return self._scenario_abort(s)
        if not isolation_closed:
            s.detail = ("clean-capture evidence window did not emit its "
                        "isolation close marker; bots may still be held")
            return s

        begins = list(_CLEAN_CAPTURE_BEGIN_RE.finditer(tail))
        results = list(_CLEAN_CAPTURE_RESULT_RE.finditer(tail))
        if len(begins) != 1 or len(results) != 1:
            s.detail = (self._abort_reason(tail)
                        or "clean capture did not emit one exact begin/result")
            return s
        begin, result = begins[0], results[0]
        evidence = tail[begin.start():result.end()]
        identity_keys = (
            "flag", "flag_name", "capteam", "owner_before", "required",
            "isolated", "roster", "cappers",
        )
        if any(begin.group(key) != result.group(key)
               for key in identity_keys):
            s.detail = "clean-capture begin/result identity did not reconcile"
            return s

        flag = int(result.group("flag"))
        flag_name = result.group("flag_name")
        capper_team = int(result.group("capteam"))
        team_name = _TEAM_NAME[capper_team]
        required = int(result.group("required"))
        pinned_userids = [int(value) for value in
                          result.group("cappers").split(",")]
        all_capture_facts = [
            match.groupdict() for match in _PLAYER_CAPTURE_RE.finditer(evidence)
        ]
        capture_facts = [fact for fact in all_capture_facts
                         if fact["team"] == team_name
                         and fact["flag_name"] == flag_name]
        capture_userids = [int(fact["userid"]) for fact in capture_facts]
        deaths = [
            match.group(4) for line in evidence.splitlines()
            if (match := _KILLED_RE.match(line))
            and match.group(5) == team_name
        ]
        breakers = _BREAK_RE.findall(evidence)
        s.breaks_seen = len(breakers)
        s.extra = {
            "flag": flag, "flag_name": flag_name,
            "new_owner": int(result.group("owner_after")),
            "required_cappers": required,
            "capture_facts": len(capture_facts), "breakers": breakers,
            "pinned_capper_userids": pinned_userids,
            "capture_marker_userids": capture_userids,
            "deaths_in_window": len(deaths),
            "isolated_players": int(result.group("isolated")),
            "roster_players": int(result.group("roster")),
        }

        if (int(begin.group("quiet_ms")) < 3000
                or int(begin.group("flushed")) != 1
                or int(result.group("flushed")) != 1):
            s.detail = "clean-capture quiet/flush boundary was not exact"
            return s
        if (int(result.group("owner_after")) != capper_team
                or int(result.group("owner_before")) == capper_team
                or int(result.group("count_after")) != 0):
            s.detail = "clean-capture engine ownership/count transition was not exact"
            return s
        if int(result.group("isolated")) != int(result.group("roster")):
            s.detail = "clean-capture evidence did not isolate the exact combat roster"
            return s
        if (int(result.group("deaths")) != 0
                or int(result.group("contaminated")) != 0 or deaths):
            s.detail = ("clean-capture evidence contains a capping-team death "
                        "or plugin contamination")
            return s
        if (len(pinned_userids) != required
                or len(set(pinned_userids)) != required):
            s.detail = "clean-capture pinned capper userids were not exact/distinct"
            return s
        if (len(all_capture_facts) != required
                or len(capture_userids) != required
                or len(set(capture_userids)) != required
                or set(capture_userids) != set(pinned_userids)):
            s.detail = ("real ownership changed but factual dod_capture_area "
                        "markers did not exactly match the distinct pinned "
                        f"capper userids {pinned_userids}")
            return s
        if breakers:
            s.status = "violation"
            s.detail = (f"real clean capture of {flag_name} emitted factual "
                        f"capture markers with zero capping-team deaths, but "
                        f"{breakers} were credited with cap_break. FALSE "
                        "POSITIVE: the ownership clear did not suppress the "
                        "post-capture count drop.")
        else:
            s.status = "ok"
            s.detail = (f"real clean capture of {flag_name} completed "
                        f"{result.group('owner_before')} -> {capper_team}; "
                        f"{len(capture_facts)} factual capture markers, zero "
                        "capping-team deaths, zero cap_break")
        return s

    def negative_round_restart(self) -> Scenario:
        """Queue a near candidate, then prove a neutral round reset is clean.

        The diagnostic owns queueing and restart in one server frame. It
        drains the capture buffer before its queue marker and again before its
        result marker, making those markers a closed evidence window.
        """
        s = Scenario("negative_round_restart")
        if self.series_started and not self._series_live():
            return self._scenario_abort(s)
        mark = len(self._read())
        self.handle.rcon("ktp_bd_arm_restart")

        ack_deadline = time.monotonic() + 3.0
        while time.monotonic() < ack_deadline:
            if self.series_started and not self._series_live():
                return self._scenario_abort(s)
            if "[BD] restart ARMED" in _tail(self._read(), mark):
                break
            time.sleep(0.1)
        else:
            s.detail = ("restart arm produced no acknowledgment; diagnostic "
                        "plugin is not running")
            return s

        deadline = self._series_deadline_for(22.0)
        tail = ""
        while time.monotonic() < deadline:
            if self.series_started and not self._series_live():
                return self._scenario_abort(s)
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

    Retries because a fail-closed engine precondition can still be transient.
    A verdict of ok or violation is final and stops the loop immediately —
    retrying past a violation would be shopping for a green run. The three
    factual canonical frag runs first, followed by the three unmatched-frag
    diagnostics that use a real capture created deterministically from the
    map's capture-area bounds. Every command is also bound to one five-minute
    series epoch; a half end, changelevel, plugin/manifest activation, userid
    change, or deadline aborts all remaining commands. The strict downstream
    contract still requires the one accepted factual frag and exact three
    synthetic diagnostics to stage and reconcile.
    """
    d = BreakDriver(handle, log_path)
    if not d.begin_series():
        return [{
            "name": "diagnostic_series",
            "status": "not_staged",
            "detail": "diagnostic series begin was not acknowledged",
            "breaks_seen": 0,
            "series_abort": d.series_abort_reason,
            "series_abort_ack": d.series_abort_ack,
            "attempts": 1,
        }]
    out = []
    # Deliberately create one ordinary engine frag before the closed-world
    # scenarios.  The plugin acknowledges it only after the exact full roster
    # respawns and freezes, so the diagnostic match always exercises accepted
    # producer clocks and ktp_match_stats without depending on bot luck.
    canonical = d.canonical_diagnostic_frag()
    canonical.extra["attempts"] = 1
    print(f"  scenario {canonical.name:<28} {canonical.status:<12} "
          f"{canonical.detail}", flush=True)
    out.append({"name": canonical.name, "status": canonical.status,
                "detail": canonical.detail,
                "breaks_seen": canonical.breaks_seen, **canonical.extra})

    # The three scenarios that intentionally dispatch unmatched synthetic
    # deaths still run before optional capture observations. This guarantees
    # that exact-three reconciliation is never held hostage by the latter.
    # The canonical frag above is factual and accepted, so it is not part of
    # this intentionally rejected diagnostic set.
    scenarios = () if canonical.status != "ok" else (
        (d.negative_off_point_kill, 1),
        (d.positive_kill_on_point, attempts),
        (d.negative_round_restart, attempts),
        (d.negative_voluntary_walkoff, attempts),
        (d.negative_clean_capture, attempts),
    )
    if canonical.status != "ok":
        print("  diagnostics HARD STOP: canonical factual frag did not "
              "stage and reconcile exactly", flush=True)
    for fn, scenario_attempts in scenarios:
        if canonical.extra.get("series_abort"):
            break
        s = None
        for attempt in range(1, scenario_attempts + 1):
            s = fn()
            # Once restart_queue exists the diagnostic has already issued a
            # real round restart. An inconclusive result is fail-closed and
            # one-shot; retrying would silently shop for a cleaner reset.
            if s.status != "not_staged" or s.extra.get("restart_issued"):
                break
            if s.extra.get("kill_disarm_ack") is False:
                # Without the plugin's explicit ack, the periodic kill poller
                # may still be live. No later diagnostic may issue commands
                # into an environment that can be mutated by that stale task.
                break
            if s.extra.get("series_abort"):
                break
            print(f"  scenario {s.name:<28} attempt "
                  f"{attempt}/{scenario_attempts} "
                  f"did not stage: {s.detail}", flush=True)
            time.sleep(4.0)
        s.extra["attempts"] = attempt
        print(f"  scenario {s.name:<28} {s.status:<12} {s.detail}", flush=True)
        out.append({"name": s.name, "status": s.status, "detail": s.detail,
                    "breaks_seen": s.breaks_seen, **s.extra})
        if s.extra.get("kill_disarm_ack") is False:
            print("  diagnostics HARD STOP: kill poller disarm was not "
                  "acknowledged", flush=True)
            break
        if s.extra.get("series_abort"):
            print("  diagnostics HARD STOP: lifecycle/deadline boundary "
                  f"{s.extra['series_abort']}", flush=True)
            break
    if not d.end_series():
        print("  diagnostics HARD STOP: series cleanup was not acknowledged",
              flush=True)
        out.append({
            "name": "diagnostic_series_cleanup",
            "status": "not_staged",
            "detail": "diagnostic series cleanup was not acknowledged",
            "breaks_seen": 0,
            "series_abort": d.series_abort_reason,
            "series_abort_ack": d.series_abort_ack,
            "attempts": 1,
        })
    return out
