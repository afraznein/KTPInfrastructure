"""Bot adapter for the stats-capture e2e lane.

## Why an adapter and not just "call addbot"

DoD ships no bot AI. `addbot` creates a fake-client slot that never joins a
team or spawns (CHANGELOG 1.5.25 — five tests were skip-marked over exactly
this). Anything that needs a body in the world needs a third-party bot mod.

Sturmbot, the operator's first choice, is not usable on a Linux runner: its
current release (1.9) is a Windows installer only, and the legacy Linux build
targets DoD 3.1B rather than 1.3 and does not load against modern glibc. The
Linux-viable DoD 1.3 bots are Marine Bot and new_bot, both Metamod plugins
loaded via `+localinfo mm_gamedll <bot>/<bot>.so`.

Marine Bot is the primary. new_bot is the fallback and can convert Sturmbot
waypoints, which matters if Marine Bot's per-map coverage is thin.

The bot is the least-certain component in this lane, so it is isolated behind
a small config object. Swapping bots is data, not a rewrite.

## The command names here are CANDIDATES, not verified facts

Every bot exposes its own console verbs, and this code has not yet been run
against either mod. `BotSpec.add_commands` is an ordered list of things to
try; `probe_add_command` finds the one that works and reports it. Phase 0's
job is to turn these candidates into one known-good value per bot — see
`scripts/spike_bot_lane.py`. Until then, treat a hardcoded command name in
this file as a hypothesis.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

# `status` lines look like:
#   #  1 "BotName" 12 STEAM_ID  0:23  67  0  ...
# We only need the quoted name and the leading slot to tell "someone is
# connected" from "nobody is". Keep the pattern loose — status output has
# drifted across engine builds and a strict pattern is how this silently
# starts reporting zero players.
_STATUS_LINE = re.compile(r'^#\s*(\d+)\s+"(?P<name>[^"]*)"', re.MULTILINE)


@dataclass(frozen=True)
class BotSpec:
    """Everything bot-specific in one place."""

    name: str
    # Path *inside* the serverfiles tree where the .so must land, and the
    # value passed to +localinfo mm_gamedll (engine resolves it relative to
    # the game dir).
    so_rel_path: str
    # For bots loaded as the Metamod game DLL (`+localinfo mm_gamedll <x>`).
    # Empty when the bot loads some other way.
    gamedll_localinfo: str
    # For bots that are Metamod PLUGINS: the line to add to metamod's
    # plugins.ini. Mutually exclusive with gamedll_localinfo in practice.
    metamod_plugin_line: str = ""
    # Where waypoints live inside the tree, if the mod uses them.
    waypoint_rel_dir: str | None = None
    # Ordered candidates for "add one bot". `{team}` is substituted when the
    # command takes a team argument; a candidate with no placeholder is tried
    # as-is.
    add_commands: Sequence[str] = field(default_factory=tuple)
    # Ordered candidates for "how many bots should exist" (quota-style mods).
    fill_commands: Sequence[str] = field(default_factory=tuple)
    # Commands to make bots play the objective rather than only deathmatch,
    # where the mod distinguishes. Best-effort; failures are not fatal.
    objective_commands: Sequence[str] = field(default_factory=tuple)


MARINEBOT = BotSpec(
    name="marinebot",
    so_rel_path="dod/addons/marinebot/marinebot.so",
    gamedll_localinfo="marinebot/marinebot.so",
    waypoint_rel_dir="dod/addons/marinebot/wps",
    add_commands=("mb_addbot", "mb_add", "mb_addbot {team}", "addbot"),
    fill_commands=("mb_minbots {n}", "mb_bots {n}", "mb_quota {n}"),
    objective_commands=("mb_objective 1", "mb_skill 3"),
)

# new_bot 0.2.2. These values are FACTS, read out of the shipped
# `_README.txt` / `_COMMANDS.txt`, not candidates — unlike MARINEBOT above.
#
# Two corrections to earlier guesses worth keeping visible:
#   * the binary is `new_bot_mm.so`, not `new_bot.so`, and it lives at
#     `dod/new_bot/`, not under `dod/addons/`.
#   * the `_mm` suffix is literal: it is a **Metamod plugin**, loaded from
#     metamod's `plugins.ini`, NOT via `+localinfo mm_gamedll`. Its README:
#     "new_bot is a metamod plugin, so you need to add it to the plugins.ini
#     file in your metamod install and not config.ini or it will crash".
NEW_BOT = BotSpec(
    name="new_bot",
    so_rel_path="dod/new_bot/new_bot_mm.so",
    # Empty: this bot is not loaded through mm_gamedll. See metamod_plugin_line.
    gamedll_localinfo="",
    metamod_plugin_line="linux new_bot/new_bot_mm.so",
    waypoint_rel_dir="dod/new_bot/waypoints",
    # `addbot {team} {class} {skill} {name}`; team accepts allies/axis or 1-2,
    # skill 1-5. Listed team-first because a bare `addbot` picks a random team
    # and we want both sides populated deterministically.
    add_commands=("addbot {team}", "addbot"),
    # `target_players {0-32}` — "Will add/remove bots to try reach this number".
    fill_commands=("target_players {n}",),
    # Objective play, which is what cap-break capture needs. Defaults are
    # flag_priority 70 / wait_for_cap 75; pushed up so bots go to flags and
    # stay on them rather than wandering to guard points.
    objective_commands=(
        "flag_priority_percent 100",
        "wait_for_cap_percent 100",
        "balance teams on",
        "bot_skill 3",
    ),
)

SPECS = {s.name: s for s in (MARINEBOT, NEW_BOT)}


class BotUnavailable(RuntimeError):
    """The bot kit is configured but the bot did not become usable.

    Deliberately an error rather than a skip. The five skip-marked addbot
    tests sat green-looking for months; a configured-but-broken bot must not
    read as coverage. Same rule conftest.py already applies to a configured
    but unreachable KTP_HLDS_HOST.
    """


@dataclass
class BotKit:
    """An on-disk bot installation, outside any fleet-matching tree.

    Layout expected under `root`:
        <root>/<botname>/<botname>.so
        <root>/<botname>/wps|waypoints/...     (optional)

    Never committed to this repo and never in a deploy manifest — see the
    quarantine rules in tests/integration/STATS_CAPTURE_E2E_DESIGN.md.
    """

    root: Path
    spec: BotSpec

    @classmethod
    def locate(cls, root: Path, bot: str = "marinebot") -> "BotKit":
        if bot not in SPECS:
            raise ValueError(f"unknown bot {bot!r}; known: {sorted(SPECS)}")
        root = Path(root).resolve()
        if not root.is_dir():
            raise BotUnavailable(
                f"bot kit root does not exist: {root}\n"
                "Install Marine Bot (or new_bot) there — it must live OUTSIDE "
                "the fleet-matching serverfiles tree. See "
                "tests/e2e_stats/README.md."
            )
        kit = cls(root=root, spec=SPECS[bot])
        if not kit.so_path.is_file():
            raise BotUnavailable(f"bot shared object not found: {kit.so_path}")
        return kit

    @property
    def so_path(self) -> Path:
        return self.root / self.spec.name / Path(self.spec.so_rel_path).name

    @property
    def waypoint_path(self) -> Path | None:
        if self.spec.waypoint_rel_dir is None:
            return None
        for candidate in ("wps", "waypoints"):
            p = self.root / self.spec.name / candidate
            if p.is_dir():
                return p
        return None

    def stage_into(self, tree) -> None:
        """Overlay the bot into an EphemeralTree. Never call with a
        fleet-matching tree."""
        tree.overlay_file(self.so_path, self.spec.so_rel_path)
        wps = self.waypoint_path
        if wps is not None and self.spec.waypoint_rel_dir:
            tree.overlay_dir(wps, self.spec.waypoint_rel_dir)

    def hlds_extra_args(self) -> list[str]:
        """Command-line arguments that activate this bot, if any.

        For an mm_gamedll-style bot the activation is entirely on the command
        line, so nothing persisted in the tree enables it and a copy of that
        tree booted normally has no bot. That is a quarantine property worth
        preserving; don't move it into a cfg file.

        Metamod-*plugin* bots (new_bot) return nothing here — they activate via
        metamod's plugins.ini instead, which is a file in the tree. The
        quarantine then rests on the tree being ephemeral rather than on the
        activation being transient.
        """
        if not self.spec.gamedll_localinfo:
            return []
        return ["+localinfo", "mm_gamedll", self.spec.gamedll_localinfo]

    def activation_blocker(self) -> str | None:
        """Why this bot cannot be activated in the KTP stack, or None.

        The KTP stack runs **Metamod-free**: `dod/addons/extensions.ini` loads
        `ktpamx_i386.so` through ReHLDS's extension mechanism, and
        `liblist.gam` still points `gamedll_linux` at the stock `dlls/dod.so`.
        There is no metamod directory and no plugins.ini anywhere in the image.

        A Metamod-plugin bot therefore has nothing to load it. Returning the
        reason (rather than raising here) lets the spike report it as a fact
        instead of a crash, which is what a Phase 0 run is for.
        """
        if self.spec.metamod_plugin_line and not self.spec.gamedll_localinfo:
            return (
                f"{self.spec.name} is a Metamod plugin, but the KTP stack is "
                "Metamod-free (ReHLDS extension mode: addons/extensions.ini "
                "loads ktpamx directly, liblist.gam keeps gamedll_linux at "
                "dlls/dod.so). Loading it needs Metamod installed and inserted "
                "between the engine and dod.so, which changes the stack under "
                "test and is an explicit decision, not a build detail."
            )
        return None

    def waypoints_for_map(self, map_name: str) -> bool:
        """Whether any waypoint file mentions this map. Coverage per map is a
        real constraint — a map with no waypoints typically yields bots that
        connect and then stand still, which looks like 'the pipeline is
        broken' rather than 'the map is unwaypointed'."""
        wps = self.waypoint_path
        if wps is None:
            return False
        return any(map_name in p.name for p in wps.rglob("*") if p.is_file())


# ---------------------------------------------------------------------------
# Driving
# ---------------------------------------------------------------------------


def connected_players(rcon: Callable[[str], str]) -> list[str]:
    """Names of everyone the engine currently reports as connected."""
    out = rcon("status")
    return [m.group("name") for m in _STATUS_LINE.finditer(out)]


def probe_add_command(
    rcon: Callable[[str], str],
    spec: BotSpec,
    *,
    team: str = "allies",
    settle: float = 6.0,
) -> str:
    """Try each add-bot candidate until the connected count rises.

    Returns the command that worked. Raises BotUnavailable if none did — which
    is the honest outcome, since the whole lane rests on this working.
    """
    tried: list[str] = []
    for candidate in spec.add_commands:
        cmd = candidate.format(team=team) if "{team}" in candidate else candidate
        before = len(connected_players(rcon))
        rcon(cmd)
        deadline = time.monotonic() + settle
        while time.monotonic() < deadline:
            if len(connected_players(rcon)) > before:
                return cmd
            time.sleep(0.5)
        tried.append(cmd)
    raise BotUnavailable(
        f"none of {spec.name}'s add-bot candidates produced a connected player: "
        f"{tried}. The command set in bot_driver.BotSpec is a hypothesis — read "
        f"the mod's own docs and correct it, or try the fallback bot."
    )


def fill_teams(
    rcon: Callable[[str], str],
    spec: BotSpec,
    *,
    add_command: str,
    per_team: int = 3,
    settle: float = 20.0,
) -> list[str]:
    """Get roughly `per_team` bots onto each side.

    Bot mods differ on whether they balance automatically. We add bodies and
    then verify the engine agrees they exist; which side each landed on is the
    mod's business. Team composition is checked separately by the caller via
    the witness/log stream, because `status` does not report team.
    """
    want = per_team * 2
    for _ in range(want):
        rcon(add_command)
        time.sleep(0.4)

    deadline = time.monotonic() + settle
    players: list[str] = []
    while time.monotonic() < deadline:
        players = connected_players(rcon)
        if len(players) >= want:
            return players
        time.sleep(1.0)
    if not players:
        raise BotUnavailable(
            f"asked for {want} bots, engine reports none connected after "
            f"{settle:.0f}s"
        )
    return players


def apply_objective_hints(rcon: Callable[[str], str], spec: BotSpec) -> list[str]:
    """Best-effort nudge toward objective play. Returns the commands accepted.

    Cap-break testing needs bots that walk onto flags, not bots that only
    duel. Failures here are non-fatal — an unrecognised cvar is just a
    console complaint — but a lane that gets zero cap activity should come
    back to this before concluding the detector is broken.
    """
    applied = []
    for cmd in spec.objective_commands:
        try:
            rcon(cmd)
            applied.append(cmd)
        except Exception:
            continue
    return applied
