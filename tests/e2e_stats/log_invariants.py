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


def summarise(log_text: str) -> dict:
    """Counts plus violations, for the run report."""
    return {
        "kills": len(_KILL_RE.findall(log_text)),
        "assists": len(_ASSIST_RE.findall(log_text)),
        "breaks": len(_BREAK_RE.findall(log_text)),
        "headshot_markers": log_text.count('triggered "headshot_kill"'),
        "assist_violations": check_assist_attribution(log_text),
        "break_violations": check_break_attribution(log_text),
    }
