"""Switch a serverfiles tree between the production and bot loader topologies.

## The two topologies

**Production (extension mode)** — what the fleet runs:

    engine  →  addons/extensions.ini  →  ktpamx_i386.so
    engine  →  liblist.gam gamedll_linux "dlls/dod.so"

**Bot lane (Metamod)** — what new_bot needs:

    engine  →  liblist.gam gamedll_linux "addons/metamod/metamod_i386.so"
    metamod →  plugins.ini  →  ktpamx_i386.so, new_bot_mm.so
    metamod →  +localinfo mm_gamedll dlls/dod.so  →  the real game DLL

`ktpamx_i386.so` carries `Meta_Attach`/`Meta_Query`/`Meta_Detach`, so it loads
either way — AMX Mod X is a Metamod plugin by construction, and KTP simply runs
it through ReHLDS's extension mechanism instead. That is what makes the second
topology ordinary rather than exotic.

## The one thing that must not happen

`extensions.ini` is **disabled** when Metamod is enabled. Leaving both active
would load `ktpamx_i386.so` twice — once as an engine extension and once as a
Metamod plugin — in a single process. Two copies of AMXX registering the same
natives, forwards and cvars is not a subtle failure mode, but it is a confusing
one, and it would poison every result the lane produced. `enable_metamod()`
therefore always neutralises it, and `restore_production()` always puts it back.

## What this costs, stated plainly

The bot topology is not production's. Under Metamod, `fakemeta` becomes
available, and several of this stack's constraints — no `CreateFakeClient`, the
DODX `dodx_test_dispatch_*` primitives — exist *because* extension mode lacks
it. A Lane B pass therefore means "works under Metamod", which is close to but
not identical with "works in production".

`scripts/spike_metamod_ab.py` is what bounds that gap: boot both topologies,
fingerprint each, and report the difference as the primary output.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

# Paths inside the game dir (everything here is relative to <tree>/dod).
LIBLIST = "dod/liblist.gam"
LIBLIST_PRISTINE = "dod/liblist.gam.production"
EXTENSIONS = "dod/addons/extensions.ini"
EXTENSIONS_PRISTINE = "dod/addons/extensions.ini.production"
METAMOD_SO = "dod/addons/metamod/metamod_i386.so"
PLUGINS_INI = "dod/addons/metamod/plugins.ini"

# plugins.ini paths are relative to the game dir, matching new_bot's README
# ("win32 new_bot/new_bot_mm.dll" → the linux form below).
KTPAMX_PLUGIN_LINE = "linux addons/ktpamx/dlls/ktpamx_i386.so"

_GAMEDLL_LINUX = re.compile(r'^\s*gamedll_linux\s+"([^"]*)"', re.MULTILINE)


class TopologyError(RuntimeError):
    """The tree is not in a state this module can switch. Always fatal — a
    half-applied topology produces results nobody can interpret."""


@dataclass
class Topology:
    """What was applied, for the run report."""

    name: str
    gamedll_linux: str
    extensions_enabled: bool
    plugins: list[str]
    extra_args: list[str]


def _read(tree, rel: str) -> str:
    p = tree.path / rel
    if not p.is_file():
        raise TopologyError(f"missing {rel} in {tree.path}")
    return p.read_text(encoding="utf-8", errors="replace")


def current_gamedll(tree) -> str:
    m = _GAMEDLL_LINUX.search(_read(tree, LIBLIST))
    if not m:
        raise TopologyError(f"no gamedll_linux line in {LIBLIST}")
    return m.group(1)


def _set_gamedll(tree, value: str) -> None:
    body = _read(tree, LIBLIST)
    if not _GAMEDLL_LINUX.search(body):
        raise TopologyError(f"no gamedll_linux line in {LIBLIST}")
    tree.write_text(LIBLIST, _GAMEDLL_LINUX.sub(f'gamedll_linux "{value}"', body, count=1))


def enable_metamod(tree, *, bot_spec=None, real_gamedll: str = "dlls/dod.so",
                   host_ktpamx: bool = True) -> Topology:
    """Point the engine at Metamod, list ktpamx (+ the bot) as its plugins, and
    disable extension mode so ktpamx is not loaded twice.

    Returns the extra hlds arguments needed — Metamod has to be told which real
    game DLL to load underneath, and `liblist.gam` can no longer say (it now
    points at Metamod itself, so reading it would be circular).
    """
    if not (tree.path / METAMOD_SO).is_file():
        raise TopologyError(
            f"{METAMOD_SO} not present — build the image with Metamod-R "
            "(build/lane-b/Dockerfile installs it)"
        )

    # host_ktpamx=False is the "split layers" variant: ktpamx keeps loading via
    # extensions.ini as production does, and Metamod hosts ONLY the bot. Worth
    # trying because the combined topology crashed: ktpamx, even when loaded as
    # a Metamod plugin, still logs "ReHLDS extension mode detected" and installs
    # ReHLDS hookchains — so it ends up hooking from inside Metamod's chain as
    # well as at the engine layer. Splitting them means each loads once, at its
    # own hook point.
    plugins = [KTPAMX_PLUGIN_LINE] if host_ktpamx else []
    if bot_spec is not None:
        line = getattr(bot_spec, "metamod_plugin_line", "")
        if not line:
            raise TopologyError(
                f"{bot_spec.name} has no metamod_plugin_line; it is not a "
                "Metamod plugin and does not belong in this topology"
            )
        plugins.append(line)

    tree.write_text(
        PLUGINS_INI,
        "; AUTO-GENERATED by tests/e2e_stats/metamod.py — test topology only.\n"
        "; Order matters: ktpamx first so AMXX is up before the bot registers.\n"
        + "\n".join(plugins) + "\n",
    )

    if host_ktpamx:
        # Disable extension mode. Without this ktpamx loads twice — once via the
        # engine extension list, once via Metamod — in one process.
        tree.write_text(
            EXTENSIONS,
            "; DISABLED by tests/e2e_stats/metamod.py for the Metamod topology.\n"
            "; ktpamx is loaded via addons/metamod/plugins.ini instead; leaving\n"
            "; both active would load it TWICE in a single process.\n",
        )
    else:
        # Split-layer variant: leave extension mode exactly as production has
        # it, so ktpamx loads once, where it always does.
        src = tree.path / EXTENSIONS_PRISTINE
        if src.is_file():
            tree.write_bytes(EXTENSIONS, src.read_bytes())

    _set_gamedll(tree, "addons/metamod/metamod_i386.so")

    return Topology(
        name="metamod" if host_ktpamx else "metamod-split",
        gamedll_linux="addons/metamod/metamod_i386.so",
        extensions_enabled=not host_ktpamx,
        plugins=plugins,
        extra_args=["+localinfo", "mm_gamedll", real_gamedll],
    )


def restore_production(tree) -> Topology:
    """Put the tree back to extension mode, byte for byte.

    Boot A of the differential has to be exactly what production runs, or the
    A/B diff measures our own edits instead of Metamod's effect. Restores from
    the pristine copies the image kept rather than trying to reverse the edits.
    """
    for live, pristine in ((LIBLIST, LIBLIST_PRISTINE),
                           (EXTENSIONS, EXTENSIONS_PRISTINE)):
        src = tree.path / pristine
        if not src.is_file():
            raise TopologyError(
                f"pristine copy {pristine} missing — cannot guarantee boot A is "
                "production-identical, so the differential would be meaningless"
            )
        tree.write_bytes(live, src.read_bytes())

    # Metamod ignores a missing plugins.ini, but leaving a stale one behind
    # invites a later run to load a bot it did not ask for.
    p = tree.path / PLUGINS_INI
    if p.is_file():
        p.unlink()

    return Topology(
        name="production",
        gamedll_linux=current_gamedll(tree),
        extensions_enabled=True,
        plugins=[],
        extra_args=[],
    )


def describe(tree) -> dict:
    """Snapshot of the loader configuration, for the report."""
    ext = tree.path / EXTENSIONS
    ext_body = ext.read_text(encoding="utf-8", errors="replace") if ext.is_file() else ""
    ext_active = [ln.strip() for ln in ext_body.splitlines()
                  if ln.strip() and not ln.strip().startswith(";")]
    pi = tree.path / PLUGINS_INI
    pi_lines = []
    if pi.is_file():
        pi_lines = [ln.strip() for ln in pi.read_text().splitlines()
                    if ln.strip() and not ln.strip().startswith(";")]
    return {
        "gamedll_linux": current_gamedll(tree),
        "extensions_ini_active_lines": ext_active,
        "metamod_plugins": pi_lines,
    }
