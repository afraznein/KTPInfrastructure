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

# "Name<userid><authid><Team>" — the authid is BOT or 0 for bots, STEAM_x:y:z
# for humans, and is not needed here. Name may contain anything except a quote.
_PLAYER = r'"([^"<]*)<(\d+)><[^<>]*><([^<>]*)>"'

_KILL_RE = re.compile(rf'{_PLAYER} killed {_PLAYER} with "([^"]*)"')
_ASSIST_RE = re.compile(rf'{_PLAYER} triggered "assist" against {_PLAYER}')
_BREAK_RE = re.compile(rf'{_PLAYER} triggered "cap_break"')
_TS_RE = re.compile(r"^L \d\d/\d\d/\d{4} - (\d\d):(\d\d):(\d\d):")

# KTPBreakDrive's kill scenarios deliberately call the DODX test death
# dispatcher and then kill the victim with a self-kill.  Capture therefore
# emits a truthful frag_context marker for the dispatched death, but HLStatsX
# has no corresponding ordinary frag row to claim.  Keep the marker narrow:
# an ABORT, scan, walkoff, or a similarly-worded line from another plugin must
# never buy an exception from the strict frag reconciliation gate.
_BREAKDRIVE_SYNTHETIC_KILL = "[KTPBreakDrive.amxx] [BD] kill flag="
_BREAKDRIVE_SYNTHETIC_KILL_RE = re.compile(
    r"\[KTPBreakDrive\.amxx\] \[BD\] kill flag=\d+ capteam=-?\d+ "
    r"mode=\w+ victim=\d+ vname=(?P<victim_name>\S+) killer=\d+ "
    r"kname=(?P<killer_name>\S+)"
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


def _actor(groups: tuple, offset: int) -> Actor:
    return Actor(name=groups[offset], userid=groups[offset + 1],
                 team=groups[offset + 2])


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

    if start is None:
        return {"found": False, "during": 0, "after": 0, "before": 0}
    stop = end if end is not None else len(lines)

    def kills(seq):
        return sum(1 for ln in seq if _KILL_RE.search(ln))

    return {"found": True,
            "before": kills(lines[:start]),
            "during": kills(lines[start:stop]),
            "after": kills(lines[stop:]),
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
    Events outside the first KTP_MATCH_START/END window are never exempted.
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
        if _BREAKDRIVE_SYNTHETIC_KILL in line
    ]


def frag_context_diagnostic_evidence(log_text: str, daemon_text: str) -> dict:
    """Build identity-level evidence for intentional unmatched frag contexts.

    BreakDrive reports client names while the daemon warning reports HLStatsX
    player ids.  The daemon's ordinary actor diagnostics carry both, allowing
    us to map each synthetic ``killer -> victim -> amerknife`` to the same
    identity used by ``KTP_NO_ROW_MATCHED``.  Lists intentionally retain
    duplicates: two injections for the same pair require two warnings for that
    same pair, not one matching warning plus one unrelated loss.

    There is no cross-log event UUID, so identity multiset is the strongest
    practical correlation available without changing AMXX/HLStatsX.  Ambiguous
    or absent name-to-player mappings fail closed via ``unresolved_expected``.
    """
    markers = breakdrive_synthetic_frag_diagnostics(log_text)
    warnings = [
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

    expected_identities: list[str] = []
    unresolved_expected: list[dict] = []
    for marker in markers:
        parsed = _BREAKDRIVE_SYNTHETIC_KILL_RE.search(marker)
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
    }


def summarise(log_text: str) -> dict:
    """Counts plus violations, for the run report."""
    return {
        "kills": len(_KILL_RE.findall(log_text)),
        "assists": len(_ASSIST_RE.findall(log_text)),
        "breaks": len(_BREAK_RE.findall(log_text)),
        # Phase 5 retired the dedicated "headshot_kill" marker in favour of
        # `(headshot "1")` as one property on the unconditional "frag_context"
        # marker every kill now emits -- count that instead. The old string
        # will never appear again; a plugin built before Phase 5 landed would
        # correctly show 0 here, which is the accurate answer for that build.
        "headshot_markers": log_text.count('(headshot "1")'),
        "damage_markers": log_text.count('triggered "damage"'),
        "assist_violations": check_assist_attribution(log_text),
        "break_violations": check_break_attribution(log_text),
    }
