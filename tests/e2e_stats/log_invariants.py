"""Negative checks on the game log itself — the ones the deployment plan asks
a human to eyeball.

Units 2 and 3 of `KTPR_DEPLOYMENT_PLAN.md` list negatives that matter more than
the positives:

- the killer must not be credited an assist on their own kill
- a *teammate* who damaged the victim must not be credited
- a false-positive cap_break is worse than a missed one, because it silently
  inflates a player's objective rating and nothing ever contradicts it

All three are decidable from the log alone, which is better than deciding them
from the database: the log is what capture actually emitted, so a violation
here is an attribution bug in the plugin rather than anything the daemon did.
It also means the same check runs over a replayed capture, so a regression can
be caught without waiting for bots to reproduce the scenario.

Parsing is deliberately narrow. These read the exact line shapes
`ktp_stats_capture.inc` emits and the engine's kill line; anything else is
ignored rather than guessed at, because a loose parser that silently matches
nothing would report "no violations" forever.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

# "Name<userid><authid><Team>" — the authid is BOT or 0 for bots, STEAM_x:y:z
# for humans, and is not needed here. Name may contain anything except a quote.
_PLAYER = r'"([^"<]*)<(\d+)><[^<>]*><([^<>]*)>"'

_KILL_RE = re.compile(rf'{_PLAYER} killed {_PLAYER} with "([^"]*)"')
_ASSIST_RE = re.compile(rf'{_PLAYER} triggered "assist" against {_PLAYER}')
_BREAK_RE = re.compile(rf'{_PLAYER} triggered "cap_break"')
_FRAG_CONTEXT_RE = re.compile(
    rf'{_PLAYER} triggered "frag_context" against {_PLAYER} with "([^"]+)"'
)
_MARKER_PROPERTY_RE = re.compile(r'\((?P<key>[a-z_]+) "(?P<value>[^"]*)"\)')
_TS_RE = re.compile(r"^L \d\d/\d\d/\d{4} - (\d\d):(\d\d):(\d\d):")
_ENGINE_DATETIME_RE = re.compile(
    r"^L (?P<date>\d\d/\d\d/\d{4}) - (?P<time>\d\d:\d\d:\d\d):"
)
_DAEMON_DATETIME_RE = re.compile(
    r"^(?P<date>\d{4}-\d\d-\d\d) (?P<time>\d\d:\d\d:\d\d):"
)
_ENGINE_MATCH_END_RE = re.compile(
    r"^L \d\d/\d\d/\d{4} - \d\d:\d\d:\d\d: KTP_MATCH_END "
)
_ENGINE_CAPTURE_MANIFEST_RE = re.compile(
    r"^L \d\d/\d\d/\d{4} - \d\d:\d\d:\d\d: KTP_CAPTURE_MANIFEST "
)
_COMBAT_TEAMS = frozenset({"Allies", "Axis"})

# KTPBreakDrive's kill and restart-queue scenarios deliberately call the DODX
# test death dispatcher. Capture therefore emits a truthful frag_context marker
# for the dispatched death, but HLStatsX has no corresponding ordinary frag row
# to claim. Keep both successful marker shapes narrow: an ABORT, scan, arm, or
# similarly-worded line from another plugin must never buy an exception.
_BREAKDRIVE_SYNTHETIC_KILL = "[KTPBreakDrive.amxx] [BD] kill flag="
_BREAKDRIVE_SYNTHETIC_KILL_RE = re.compile(
    r"\[KTPBreakDrive\.amxx\] \[BD\] kill flag=\d+ capteam=-?\d+ "
    r"mode=\w+ victim=\d+ vname=(?P<victim_name>\S+) killer=\d+ "
    r"kname=(?P<killer_name>\S+)"
)
_BREAKDRIVE_SYNTHETIC_RESTART_RE = re.compile(
    r"\[KTPBreakDrive\.amxx\] \[BD\] restart_queue seq=\d+ flag=\d+ "
    r"fname=\S+ capteam=-?\d+ victim=\d+ "
    r"vname=(?P<victim_name>\S+) killer=\d+ killer_userid=\d+ "
    r"kname=(?P<killer_name>\S+)"
)
_BREAKDRIVE_SYNTHETIC_RES = (
    _BREAKDRIVE_SYNTHETIC_KILL_RE,
    _BREAKDRIVE_SYNTHETIC_RESTART_RE,
)
_DAEMON_PLAYER_RE = re.compile(
    r'"(?P<name>[^"]+)" <P:(?P<player_id>\d+),U:\d+,W:[^,>]+,T:[^>]*>'
)
_FRAG_NO_ROW_RE = re.compile(
    r"KTP_NO_ROW_MATCHED: frag_context: .*?killer=(?P<killer>\d+) "
    r"victim=(?P<victim>\d+) weapon=(?P<weapon>\S+)"
)


@dataclass(frozen=True)
class Actor:
    name: str
    userid: str
    team: str

    def __str__(self) -> str:
        return f"{self.name}<{self.userid}><{self.team}>"


def _seconds(line: str) -> int | None:
    """Wall-clock seconds from the engine's `L mm/dd/yyyy - hh:mm:ss:` prefix.

    Date is dropped on purpose: these checks only ever compare events seconds
    apart, and a run that straddles midnight would produce one bogus pairing
    rather than a wrong verdict — the window check treats a negative delta as
    out of window.
    """
    m = _TS_RE.match(line)
    if not m:
        return None
    h, mi, s = (int(v) for v in m.groups())
    return h * 3600 + mi * 60 + s


def _event_second(line: str) -> int | None:
    """Comparable integral timestamp for engine and daemon evidence lines."""
    engine = _ENGINE_DATETIME_RE.match(line)
    daemon = _DAEMON_DATETIME_RE.match(line)
    try:
        if engine:
            value = datetime.strptime(
                f"{engine.group('date')} {engine.group('time')}",
                "%m/%d/%Y %H:%M:%S",
            )
        elif daemon:
            value = datetime.strptime(
                f"{daemon.group('date')} {daemon.group('time')}",
                "%Y-%m-%d %H:%M:%S",
            )
        else:
            return None
    except ValueError:
        return None
    return (
        value.toordinal() * 86400
        + value.hour * 3600
        + value.minute * 60
        + value.second
    )


def _actor(groups: tuple, offset: int) -> Actor:
    return Actor(name=groups[offset], userid=groups[offset + 1],
                 team=groups[offset + 2])


def _combat_relation(killer: Actor, victim: Actor) -> str:
    """Classify only exact engine combat-team labels; never guess unknowns."""
    if killer.userid == victim.userid:
        return "unclassified"
    if killer.team not in _COMBAT_TEAMS or victim.team not in _COMBAT_TEAMS:
        return "unclassified"
    return "teamkills" if killer.team == victim.team else "frags"


def kill_classification(log_text: str) -> dict:
    """Split engine ``killed`` lines into frag/teamkill/unclassified counts."""
    evidence = {"frags": 0, "teamkills": 0, "unclassified": 0,
                "unclassified_lines": []}
    for line in log_text.splitlines():
        match = _KILL_RE.search(line)
        if not match:
            continue
        killer = _actor(match.groups(), 0)
        victim = _actor(match.groups(), 3)
        relation = _combat_relation(killer, victim)
        evidence[relation] += 1
        if relation == "unclassified":
            evidence["unclassified_lines"].append(line.strip())
    evidence["kills"] = (
        evidence["frags"] + evidence["teamkills"] + evidence["unclassified"]
    )
    return evidence


def frag_context_classification(log_text: str, *, match_only: bool = False) -> dict:
    """Classify context markers; teamkill/unknown markers are product defects."""
    lines = log_text.splitlines()
    if match_only:
        start = end = None
        for index, line in enumerate(lines):
            if start is None and "KTP_MATCH_START" in line:
                start = index
            elif start is not None and end is None and "KTP_MATCH_END" in line:
                end = index
        if start is None:
            lines = []
        else:
            lines = lines[start:end if end is not None else len(lines)]

    evidence = {"frags": 0, "teamkills": 0, "unclassified": 0,
                "headshots": 0, "violations": []}
    for line in lines:
        match = _FRAG_CONTEXT_RE.search(line)
        if not match:
            continue
        killer = _actor(match.groups(), 0)
        victim = _actor(match.groups(), 3)
        relation = _combat_relation(killer, victim)
        evidence[relation] += 1
        if relation == "frags":
            if '(headshot "1")' in line:
                evidence["headshots"] += 1
        elif relation == "teamkills":
            evidence["violations"].append(
                f"teamkill emitted frag_context: {killer} and {victim} are both "
                f"{killer.team}; teamkills must be suppressed from canonical "
                f"frag context\n    {line.strip()}"
            )
        else:
            evidence["violations"].append(
                f"unclassifiable frag_context teams: {killer} against {victim}; "
                f"only exact Allies/Axis opponents may emit canonical frag "
                f"context\n    {line.strip()}"
            )
    evidence["total"] = (
        evidence["frags"] + evidence["teamkills"] + evidence["unclassified"]
    )
    return evidence


def producer_markers_for_match(
        log_text: str, needle: str, *, match_id: str, half: int,
        start_epoch: int, end_epoch: int | None = None) -> dict:
    """Classify text-window markers by their structured producer context.

    A buffered capture line can be printed after ``KTP_MATCH_START`` even though
    it was produced before that match.  Text order alone would then assign the
    old fact to the new match.  Exact producer match/half and the persisted
    match interval are authoritative.  Only the producer's exact no-context
    sentinel (matchid ``-``, half ``0``) may be classified as a buffered
    pre-interval fact; every real foreign context, malformed marker, or clock
    mismatch fails closed for the caller.
    """
    included: list[str] = []
    buffered_pre_interval: list[str] = []
    context_mismatches: list[str] = []

    lines = log_text.splitlines()
    start = next(
        (index for index, line in enumerate(lines)
         if "KTP_MATCH_START" in line),
        None,
    )
    if start is None:
        return {
            "markers": included,
            "buffered_pre_interval": buffered_pre_interval,
            "context_mismatches": context_mismatches,
        }
    end = next(
        (index for index, line in enumerate(lines[start + 1:], start + 1)
         if "KTP_MATCH_END" in line),
        len(lines),
    )

    for line in lines[start:end]:
        if needle not in line:
            continue
        properties = {
            match.group("key"): match.group("value")
            for match in _MARKER_PROPERTY_RE.finditer(line)
        }
        try:
            marker_half = int(properties["half"])
            event_epoch = int(properties["event_epoch"])
            marker_match_id = properties["matchid"]
        except (KeyError, TypeError, ValueError):
            context_mismatches.append(line.strip())
            continue

        exact_context = marker_match_id == match_id and marker_half == int(half)
        inside_interval = (
            event_epoch >= int(start_epoch)
            and (end_epoch is None or event_epoch <= int(end_epoch))
        )
        if exact_context and inside_interval:
            included.append(line.strip())
        elif (marker_match_id == "-" and marker_half == 0
              and event_epoch < int(start_epoch)):
            buffered_pre_interval.append(line.strip())
        else:
            context_mismatches.append(line.strip())

    return {
        "markers": included,
        "buffered_pre_interval": buffered_pre_interval,
        "context_mismatches": context_mismatches,
    }


def producer_marker_scopes(
        log_text: str, needle: str, *, contexts: dict[str, dict],
        allow_transition_sentinels: bool = True) -> dict:
    """Classify every producer marker by persisted structured context.

    The console's textual ``KTP_MATCH_START``/``KTP_MATCH_END`` order is not a
    producer-time boundary: a buffered marker can be printed either side of a
    later start line.  Persisted match intervals plus the marker's exact
    ``matchid``/``half``/``event_epoch`` tuple are authoritative instead.

    Exact pending sentinels (``matchid '-'``, half ``0``, sequence ``0``) are
    transition evidence only through the following context's confirmed
    manifest activation epoch. At the activation second, the sentinel must
    precede the exact unique sequence-one manifest line in log order. They are
    assigned to that following context so a corresponding daemon no-row
    warning can be accounted without exempting a real marker from it.
    Sentinels after activation, same-second sentinels after the manifest,
    nonzero sequences, and exact-context markers outside their own interval
    fail closed via ``context_mismatches``. Valid markers for an unrequested
    real context are returned separately and never counted for a requested
    scope.
    """
    lines = log_text.splitlines()
    normalized: dict[str, dict] = {}
    for name, raw in contexts.items():
        normalized[name] = {
            "match_id": str(raw["match_id"]),
            "half": int(raw["half"]),
            "start_epoch": int(raw["start_epoch"]),
            "end_epoch": int(raw["end_epoch"]),
            "activation_epoch": int(raw.get(
                "activation_epoch", raw["start_epoch"]
            )),
            "manifest_line_index": None,
            "manifest_line_count": 0,
            "markers": [],
            "buffered_pre_interval": [],
            "context_mismatches": [],
        }

    ordered = sorted(
        normalized.items(), key=lambda item: item[1]["start_epoch"]
    )
    malformed: list[str] = []
    foreign_context: list[str] = []
    context_mismatches: list[str] = []

    for line_index, line in enumerate(lines):
        if not _ENGINE_CAPTURE_MANIFEST_RE.match(line):
            continue
        properties = {
            match.group("key"): match.group("value")
            for match in _MARKER_PROPERTY_RE.finditer(line)
        }
        try:
            manifest_half = int(properties["half"])
            manifest_epoch = int(properties["event_epoch"])
            manifest_sequence = int(properties["sequence"])
        except (KeyError, TypeError, ValueError):
            continue
        for scope in normalized.values():
            if (properties.get("matchid") == scope["match_id"]
                    and manifest_half == scope["half"]
                    and manifest_epoch == scope["activation_epoch"]
                    and manifest_sequence == 1):
                scope["manifest_line_count"] += 1
                scope["manifest_line_index"] = line_index

    for line_index, line in enumerate(lines):
        if needle not in line:
            continue
        stripped = line.strip()
        properties = {
            match.group("key"): match.group("value")
            for match in _MARKER_PROPERTY_RE.finditer(line)
        }
        try:
            marker_match_id = properties["matchid"]
            marker_half = int(properties["half"])
            event_epoch = int(properties["event_epoch"])
        except (KeyError, TypeError, ValueError):
            malformed.append(stripped)
            context_mismatches.append(stripped)
            continue

        exact = next((
            (name, scope) for name, scope in ordered
            if marker_match_id == scope["match_id"]
            and marker_half == scope["half"]
        ), None)
        if exact is not None:
            name, scope = exact
            if scope["start_epoch"] <= event_epoch <= scope["end_epoch"]:
                scope["markers"].append(stripped)
            else:
                scope["context_mismatches"].append(stripped)
                context_mismatches.append(stripped)
            continue

        if marker_match_id == "-" and marker_half == 0:
            try:
                marker_sequence = int(properties["sequence"])
            except (KeyError, TypeError, ValueError):
                context_mismatches.append(stripped)
                malformed.append(stripped)
                continue
            if not allow_transition_sentinels or marker_sequence != 0:
                context_mismatches.append(stripped)
                continue
            assigned = False
            previous_end: int | None = None
            for _name, scope in ordered:
                # Pending DODX facts can flush before or after the textual and
                # persisted match start. The first exact manifest confirms the
                # activation boundary; only sequence-zero sentinels through
                # that inclusive epoch belong to the following context.
                after_previous = (
                    previous_end is None or event_epoch >= previous_end
                )
                before_activation = event_epoch < scope["activation_epoch"]
                at_activation_before_manifest = (
                    event_epoch == scope["activation_epoch"]
                    and scope["manifest_line_count"] == 1
                    and line_index < scope["manifest_line_index"]
                )
                if (after_previous and (
                        before_activation or at_activation_before_manifest)):
                    scope["buffered_pre_interval"].append(stripped)
                    assigned = True
                    break
                previous_end = scope["end_epoch"]
            if not assigned:
                context_mismatches.append(stripped)
            continue

        foreign_context.append(stripped)

    return {
        "scopes": normalized,
        "context_mismatches": context_mismatches,
        "malformed": malformed,
        "foreign_context": foreign_context,
    }


def objective_attempt_marker_scopes(
        log_text: str, *, contexts: dict[str, dict],
        report_scope: str = "report") -> dict:
    """Scope objective facts, admitting one narrowly proven teardown tail.

    Normal objective facts must fall inside their exact persisted interval.
    Teardown may print a contiguous block of report-context ``context_reset``
    stops at end/end+1 immediately after the exact ``KTP_MATCH_END``. Every
    terminal must map one-to-one to a distinct prior same-context attempt
    start. Known diagnostic context remains visible but is never counted as
    report evidence; callers fail duplicates, interposition, or any remaining
    foreign/malformed marker.
    """
    evidence = producer_marker_scopes(
        log_text, "KTP_OBJECTIVE_ATTEMPT ", contexts=contexts,
        allow_transition_sentinels=False,
    )
    report = evidence["scopes"].get(report_scope)
    if not report:
        return evidence

    lines = log_text.splitlines()
    report_identity = f'(matchid "{report["match_id"]}")'
    report_half = report["half"]
    end_epoch = report["end_epoch"]
    exact_end_indexes = [
        index for index, line in enumerate(lines)
        if _ENGINE_MATCH_END_RE.match(line) and report_identity in line
    ]

    starts: dict[str, list[int]] = {}
    parsed_markers: dict[int, dict[str, str]] = {}
    for line_index, line in enumerate(lines):
        if "KTP_OBJECTIVE_ATTEMPT " not in line:
            continue
        properties = {
            match.group("key"): match.group("value")
            for match in _MARKER_PROPERTY_RE.finditer(line)
        }
        parsed_markers[line_index] = properties
        try:
            same_context = (
                properties["matchid"] == report["match_id"]
                and int(properties["half"]) == report_half
            )
            event_epoch = int(properties["event_epoch"])
        except (KeyError, TypeError, ValueError):
            continue
        if (same_context and properties.get("kind") == "start"
                and report["start_epoch"] <= event_epoch <= end_epoch
                and properties.get("attempt_id")):
            starts.setdefault(properties["attempt_id"], []).append(line_index)

    teardown_boundary = (
        exact_end_indexes[0] if exact_end_indexes else None
    )
    contiguous_indexes: set[int] = set()
    if len(exact_end_indexes) == 1:
        cursor = exact_end_indexes[0] + 1
        while (cursor < len(lines)
               and "KTP_OBJECTIVE_ATTEMPT " in lines[cursor]):
            contiguous_indexes.add(cursor)
            cursor += 1

    post_end: list[tuple[int, str, dict[str, str], int | None]] = []
    if teardown_boundary is not None:
        for index, properties in parsed_markers.items():
            if index <= teardown_boundary:
                continue
            try:
                exact_report_context = (
                    properties["matchid"] == report["match_id"]
                    and int(properties["half"]) == report_half
                )
                event_epoch = int(properties["event_epoch"])
            except (KeyError, TypeError, ValueError):
                continue
            if exact_report_context:
                post_end.append(
                    (index, lines[index].strip(), properties, event_epoch)
                )

    # Producer epoch=end still falls inside the persisted interval, but once
    # printed after structural match end it is teardown evidence and must meet
    # the same strict block contract as end+1. Remove every post-end report
    # marker before deciding which complete block can be admitted.
    for _index, stripped, _properties, _event_epoch in post_end:
        if stripped in report["markers"]:
            report["markers"].remove(stripped)

    candidate_attempts: dict[str, int] = {}
    basic_candidates: dict[int, str] = {}
    for index, _stripped, properties, event_epoch in post_end:
        try:
            attempt_id = properties["attempt_id"]
            basic = (
                index in contiguous_indexes
                and event_epoch in (end_epoch, end_epoch + 1)
                and properties.get("kind") == "stop"
                and properties.get("stop_reason") == "context_reset"
                and len(starts.get(attempt_id, [])) == 1
                and starts[attempt_id][0] < teardown_boundary
            )
        except (KeyError, TypeError, ValueError):
            basic = False
            attempt_id = ""
        if basic:
            basic_candidates[index] = attempt_id
            candidate_attempts[attempt_id] = (
                candidate_attempts.get(attempt_id, 0) + 1
            )

    # The immediately-following objective block must contain only valid exact
    # report terminals. A foreign marker, wrong kind/reason/epoch, duplicate
    # attempt id, or ambiguous prior start invalidates the whole block.
    block_is_pure = (
        bool(contiguous_indexes)
        and set(basic_candidates) == contiguous_indexes
        and all(count == 1 for count in candidate_attempts.values())
    )
    admitted: list[str] = []
    admitted_end_plus_one: list[str] = []
    for index, stripped, _properties, event_epoch in post_end:
        candidate = (
            block_is_pure
            and index in basic_candidates
            and candidate_attempts[basic_candidates[index]] == 1
        )
        if candidate:
            admitted.append(stripped)
            if event_epoch == end_epoch + 1:
                admitted_end_plus_one.append(stripped)
            report["markers"].append(stripped)
            if stripped in report["context_mismatches"]:
                report["context_mismatches"].remove(stripped)
            if stripped in evidence["context_mismatches"]:
                evidence["context_mismatches"].remove(stripped)
        else:
            if stripped not in report["context_mismatches"]:
                report["context_mismatches"].append(stripped)
            if stripped not in evidence["context_mismatches"]:
                evidence["context_mismatches"].append(stripped)

    report["admitted_context_reset_teardown"] = admitted
    report["admitted_context_reset_end_plus_one"] = admitted_end_plus_one
    return evidence


def count_after_match(log_text: str, needle: str) -> int:
    """Count source markers after match end and before the next match start.

    ``match_log_segment`` already trims at the next real start.  Keeping this
    helper independent makes the StatsMe invariant testable from a small log
    fixture and ensures a second match's valid flush is never counted here.
    """
    lines = log_text.splitlines()
    end = next(
        (index for index, line in enumerate(lines) if "KTP_MATCH_END" in line),
        None,
    )
    if end is None:
        return 0
    stop = next(
        (index for index, line in enumerate(lines[end + 1:], end + 1)
         if "KTP_MATCH_START" in line and "[test-mode mirror]" not in line),
        len(lines),
    )
    return sum(1 for line in lines[end + 1:stop] if needle in line)


def check_frag_context_teamkills(log_text: str) -> list[str]:
    return frag_context_classification(log_text)["violations"]


def check_assist_attribution(log_text: str, *, window: int = 10) -> list[str]:
    """Violations of who may be credited an assist. Empty list means clean.

    `window` is how far back to look for the kill an assist belongs to. The
    plugin emits the assist immediately after the death it is attached to, so
    10s is generous; widening it further would start pairing an assist with an
    *earlier, unrelated* death of the same victim and invent violations.
    """
    violations: list[str] = []
    # Last kill per victim userid: (seconds, killer, line)
    last_kill: dict[str, tuple[int, Actor, str]] = {}

    for line in log_text.splitlines():
        t = _seconds(line)

        k = _KILL_RE.search(line)
        if k:
            g = k.groups()
            killer, victim = _actor(g, 0), _actor(g, 3)
            if t is not None:
                last_kill[victim.userid] = (t, killer, line)
            continue

        a = _ASSIST_RE.search(line)
        if not a:
            continue
        g = a.groups()
        assister, victim = _actor(g, 0), _actor(g, 3)

        if assister.userid == victim.userid:
            violations.append(
                f"self-assist: {assister} credited an assist against "
                f"themselves\n    {line.strip()}")
            continue

        # Teams are read off the line, so this needs no state and holds even
        # for an assist whose kill line was lost.
        if assister.team and victim.team and assister.team == victim.team:
            violations.append(
                f"team-mate assist: {assister} credited against {victim} on "
                f"the SAME team ({assister.team}). Friendly damage must not "
                f"count.\n    {line.strip()}")

        prior = last_kill.get(victim.userid)
        if prior and t is not None:
            when, killer, kill_line = prior
            if 0 <= t - when <= window and killer.userid == assister.userid:
                violations.append(
                    f"killer credited an assist on their own kill: "
                    f"{assister} killed {victim} and was also credited an "
                    f"assist\n    {kill_line.strip()}\n    {line.strip()}")
    return violations


def check_break_attribution(log_text: str) -> list[str]:
    """Cap-break lines name a real player on a real team.

    Deliberately weak. Whether a break was *legitimate* needs zone state that
    the log does not carry, so this only catches the shapes that are wrong on
    their face — an unassigned or spectating breaker, which would mean the
    detector fired on someone who could not have been contesting.
    """
    violations: list[str] = []
    for line in log_text.splitlines():
        m = _BREAK_RE.search(line)
        if not m:
            continue
        breaker = _actor(m.groups(), 0)
        if breaker.team.lower() in ("", "spectator", "unassigned"):
            violations.append(
                f"cap_break credited to {breaker} with team "
                f"{breaker.team!r} — nobody on that team can be contesting a "
                f"point\n    {line.strip()}")
    return violations


def match_window(log_text: str) -> dict:
    """Kills inside the driven match, taken from the log's own markers.

    The obvious way to bound a match — sample a counter before the play window
    and after it — is off by however many kills land between the state machine
    going live and the sample being taken. That produced a confident
    "context is not being cleared" report on a run where nothing had leaked:
    37 rows were tagged and the sampled bound said 36.

    `KTP_MATCH_START` and `KTP_MATCH_END` are written by the plugin into the
    same stream as the kills, so counting between them has no sampling race at
    all. `during` is then an exact upper bound on how many frag rows may carry
    the match id.

    Returns zeros when no match was driven, which the caller must treat as
    "not exercised" rather than "nothing leaked".
    """
    lines = log_text.splitlines()
    start = end = None
    for i, line in enumerate(lines):
        # The plugin also emits a `[test-mode mirror]` copy; take the first of
        # each so the window is the real one.
        if start is None and "KTP_MATCH_START" in line:
            start = i
        elif start is not None and end is None and "KTP_MATCH_END" in line:
            end = i

    zero_window = {"before": 0, "during": 0, "after": 0}
    if start is None:
        return {"found": False, "during": 0, "after": 0, "before": 0,
                "frags": dict(zero_window), "teamkills": dict(zero_window),
                "unclassified": dict(zero_window)}
    stop = end if end is not None else len(lines)

    def classified(seq):
        return kill_classification("\n".join(seq))

    before = classified(lines[:start])
    during = classified(lines[start:stop])
    after = classified(lines[stop:])

    return {"found": True,
            "before": before["kills"],
            "during": during["kills"],
            "after": after["kills"],
            "frags": {"before": before["frags"],
                      "during": during["frags"],
                      "after": after["frags"]},
            "teamkills": {"before": before["teamkills"],
                          "during": during["teamkills"],
                          "after": after["teamkills"]},
            "unclassified": {"before": before["unclassified"],
                             "during": during["unclassified"],
                             "after": after["unclassified"]},
            "ended": end is not None}


def count_in_match(log_text: str, needle: str) -> int:
    """Count literal markers inside the first driven match window.

    Periodic capture begins at map load, before Lane B starts the daemon or
    drives `.testmatch`. Comparing the whole console log with match-scoped
    database rows therefore fabricates loss from warmup markers the daemon was
    never meant to ingest. The match markers share the same ordered log stream,
    so they provide the race-free boundary for non-kill events too.
    """
    lines = log_text.splitlines()
    start = end = None
    for i, line in enumerate(lines):
        if start is None and "KTP_MATCH_START" in line:
            start = i
        elif start is not None and end is None and "KTP_MATCH_END" in line:
            end = i
    if start is None:
        return 0
    stop = end if end is not None else len(lines)
    return sum(1 for line in lines[start:stop] if needle in line)


def breakdrive_synthetic_frag_diagnostics(log_text: str) -> list[str]:
    """Successful BreakDrive synthetic deaths inside the driven match.

    Each returned marker is expected to produce exactly one
    ``KTP_NO_ROW_MATCHED: frag_context:`` diagnostic.  Returning the marker
    text as well as a count leaves enough evidence in the Lane B report to
    distinguish the intentional test injection from a genuine dropped frag.
    This includes restart_queue's queue-only dispatch. Events outside the first
    KTP_MATCH_START/END window are never exempted.
    """
    lines = log_text.splitlines()
    start = end = None
    for i, line in enumerate(lines):
        if start is None and "KTP_MATCH_START" in line:
            start = i
        elif start is not None and end is None and "KTP_MATCH_END" in line:
            end = i
    if start is None:
        return []
    stop = end if end is not None else len(lines)
    return [
        line.strip()
        for line in lines[start:stop]
        if any(pattern.search(line) for pattern in _BREAKDRIVE_SYNTHETIC_RES)
    ]


def frag_context_diagnostic_evidence(
        log_text: str, daemon_text: str, *,
        ignored_producer_markers: list[str] | tuple[str, ...] = (),
        all_producer_text: str | None = None) -> dict:
    """Build identity-level evidence for intentional unmatched frag contexts.

    BreakDrive reports client names while the daemon warning reports HLStatsX
    player ids.  The daemon's ordinary actor diagnostics carry both, allowing
    us to map each synthetic ``killer -> victim -> amerknife`` to the same
    identity used by ``KTP_NO_ROW_MATCHED``.  Lists intentionally retain
    duplicates: two injections for the same pair require two warnings for that
    same pair, not one matching warning plus one unrelated loss.

    There is no cross-log event UUID. Transition exceptions therefore require
    a unique same-identity warning within a two-second timestamp window and
    preserve order across the two logs. Identity overlap with an expected
    BreakDrive warning, any ordinary producer frag of that identity in the
    same window, or any ambiguous candidate fails closed; a global multiset
    cancellation is never sufficient.
    """
    markers = breakdrive_synthetic_frag_diagnostics(log_text)
    all_warnings = [
        line.strip()
        for line in daemon_text.splitlines()
        if "KTP_NO_ROW_MATCHED: frag_context:" in line
    ]

    player_ids_by_name: dict[str, set[int]] = {}
    for line in daemon_text.splitlines():
        actor = _DAEMON_PLAYER_RE.search(line)
        if actor:
            player_ids_by_name.setdefault(actor.group("name"), set()).add(
                int(actor.group("player_id"))
            )

    def producer_identity(marker: str) -> tuple[str | None, str | None]:
        parsed = _FRAG_CONTEXT_RE.search(marker)
        if not parsed:
            return None, "producer marker shape was not parseable"
        killer_name, victim_name, weapon = (
            parsed.group(1), parsed.group(4), parsed.group(7)
        )
        killer_ids = player_ids_by_name.get(killer_name, set())
        victim_ids = player_ids_by_name.get(victim_name, set())
        if len(killer_ids) != 1 or len(victim_ids) != 1:
            return None, (
                f"daemon identity mapping is not unique: killer "
                f"{killer_name!r} -> {sorted(killer_ids)}, victim "
                f"{victim_name!r} -> {sorted(victim_ids)}"
            )
        return (
            f"{next(iter(killer_ids))}->{next(iter(victim_ids))}:{weapon}",
            None,
        )

    ignored_identities: list[str] = []
    ignored_marker_pairs: list[tuple[str, str, int | None]] = []
    unresolved_ignored: list[dict] = []
    for marker in ignored_producer_markers:
        identity, reason = producer_identity(marker)
        if identity is None:
            unresolved_ignored.append({"marker": marker, "reason": reason})
        else:
            ignored_identities.append(identity)
            ignored_marker_pairs.append((marker, identity, _event_second(marker)))

    non_sentinel_frag_identities: list[tuple[str, str, int | None]] = []
    producer_text = (
        all_producer_text if all_producer_text is not None else log_text
    )
    for line in producer_text.splitlines():
        if 'triggered "frag_context"' not in line:
            continue
        properties = {
            match.group("key"): match.group("value")
            for match in _MARKER_PROPERTY_RE.finditer(line)
        }
        try:
            is_sentinel = (
                properties.get("matchid") == "-"
                and int(properties.get("half", "")) == 0
                and int(properties.get("sequence", "")) == 0
            )
        except ValueError:
            is_sentinel = False
        if is_sentinel:
            continue
        identity, _reason = producer_identity(line)
        if identity is not None:
            non_sentinel_frag_identities.append(
                (line.strip(), identity, _event_second(line))
            )

    expected_identities: list[str] = []
    unresolved_expected: list[dict] = []
    for marker in markers:
        parsed = next((pattern.search(marker)
                       for pattern in _BREAKDRIVE_SYNTHETIC_RES
                       if pattern.search(marker)), None)
        if not parsed:
            unresolved_expected.append({
                "marker": marker,
                "reason": "successful BreakDrive marker shape was not parseable",
            })
            continue
        killer_name = parsed.group("killer_name")
        victim_name = parsed.group("victim_name")
        killer_ids = player_ids_by_name.get(killer_name, set())
        victim_ids = player_ids_by_name.get(victim_name, set())
        if len(killer_ids) != 1 or len(victim_ids) != 1:
            unresolved_expected.append({
                "marker": marker,
                "reason": (
                    f"daemon identity mapping is not unique: killer "
                    f"{killer_name!r} -> {sorted(killer_ids)}, victim "
                    f"{victim_name!r} -> {sorted(victim_ids)}"
                ),
            })
            continue
        expected_identities.append(
            f"{next(iter(killer_ids))}->{next(iter(victim_ids))}:amerknife"
        )

    warning_identities: list[str | None] = []
    warning_seconds: list[int | None] = []
    for warning in all_warnings:
        parsed = _FRAG_NO_ROW_RE.search(warning)
        warning_identities.append(
            f"{parsed.group('killer')}->{parsed.group('victim')}:"
            f"{parsed.group('weapon')}"
            if parsed else None
        )
        warning_seconds.append(_event_second(warning))

    ignored_warning_indexes: set[int] = set()
    ignored_markers: list[str] = []
    last_warning_index = -1
    expected_identity_set = set(expected_identities)
    for marker, identity, marker_second in ignored_marker_pairs:
        if identity in expected_identity_set:
            unresolved_ignored.append({
                "marker": marker,
                "reason": (
                    "transition identity overlaps expected BreakDrive "
                    "diagnostic; no warning exception granted"
                ),
            })
            continue
        if marker_second is None:
            unresolved_ignored.append({
                "marker": marker,
                "reason": "transition marker has no parseable engine timestamp",
            })
            continue
        conflicting_producer_markers = [
            producer_marker
            for producer_marker, producer_identity_value, producer_second
            in non_sentinel_frag_identities
            if producer_identity_value == identity
            and (producer_second is None
                 or abs(producer_second - marker_second) <= 2)
        ]
        if conflicting_producer_markers:
            unresolved_ignored.append({
                "marker": marker,
                "reason": (
                    "transition identity overlaps a non-sentinel producer "
                    "frag within the correlation window; no warning "
                    "exception granted"
                ),
                "conflicting_markers": conflicting_producer_markers,
            })
            continue
        candidates = [
            index for index, (warning_identity, warning_second) in enumerate(
                zip(warning_identities, warning_seconds)
            )
            if index not in ignored_warning_indexes
            and warning_identity == identity
            and warning_second is not None
            and abs(warning_second - marker_second) <= 2
        ]
        if not candidates:
            # The marker may have claimed an ordinary frag row, in which case
            # no no-row warning exists and no exception is needed.
            continue
        if len(candidates) != 1 or candidates[0] <= last_warning_index:
            unresolved_ignored.append({
                "marker": marker,
                "reason": (
                    "transition warning correlation is ambiguous or out of "
                    f"order: candidates={candidates}"
                ),
            })
            continue
        warning_index = candidates[0]
        ignored_warning_indexes.add(warning_index)
        last_warning_index = warning_index
        ignored_markers.append(marker)

    warnings = [
        warning for index, warning in enumerate(all_warnings)
        if index not in ignored_warning_indexes
    ]
    ignored_warnings = [
        warning for index, warning in enumerate(all_warnings)
        if index in ignored_warning_indexes
    ]

    observed_identities: list[str] = []
    unparsed_observed: list[str] = []
    for warning in warnings:
        parsed = _FRAG_NO_ROW_RE.search(warning)
        if not parsed:
            unparsed_observed.append(warning)
            continue
        observed_identities.append(
            f"{parsed.group('killer')}->{parsed.group('victim')}:"
            f"{parsed.group('weapon')}"
        )

    return {
        "expected_synthetic_unmatched": len(markers),
        "observed_unmatched": len(warnings),
        "expected_identities": expected_identities,
        "observed_identities": observed_identities,
        "unresolved_expected": unresolved_expected,
        "unparsed_observed": unparsed_observed,
        "synthetic_kill_markers": markers,
        "unmatched_warnings": warnings,
        "ignored_pre_interval_identities": ignored_identities,
        "ignored_pre_interval_markers": ignored_markers,
        "ignored_pre_interval_warnings": ignored_warnings,
        "unresolved_ignored_pre_interval": unresolved_ignored,
    }


def summarise(log_text: str) -> dict:
    """Counts plus violations, for the run report."""
    kill_evidence = kill_classification(log_text)
    frag_evidence = frag_context_classification(log_text)
    return {
        "kills": kill_evidence["kills"],
        "frags": kill_evidence["frags"],
        "teamkills": kill_evidence["teamkills"],
        "unclassified_kills": kill_evidence["unclassified"],
        "unclassified_kill_lines": kill_evidence["unclassified_lines"],
        "kill_classification_violations": [
            "unclassifiable engine kill teams; expected exact Allies/Axis:\n    "
            + line
            for line in kill_evidence["unclassified_lines"]
        ],
        "assists": len(_ASSIST_RE.findall(log_text)),
        "breaks": len(_BREAK_RE.findall(log_text)),
        # Phase 5 retired the dedicated "headshot_kill" marker in favour of
        # `(headshot "1")` as one property on the canonical "frag_context"
        # marker every non-teamkill player frag emits. The old string
        # will never appear again; a plugin built before Phase 5 landed would
        # correctly show 0 here, which is the accurate answer for that build.
        "headshot_markers": frag_evidence["headshots"],
        "damage_markers": log_text.count('triggered "damage"'),
        "assist_violations": check_assist_attribution(log_text),
        "break_violations": check_break_attribution(log_text),
        "frag_context_teamkill_violations": frag_evidence["violations"],
    }
