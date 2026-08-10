"""Capture what the stack looks like at runtime, so two topologies can be diffed.

The question this exists to answer: *does adding Metamod + new_bot perturb the
stack under test?* Not "is it isolated" — it cannot be, since both ktpamx and
new_bot hook the same `GetEntityAPI2` / `GetEngineFunctions` tables in one
process — but "does anything production depends on come out different?"

That is a measurable question, and this is the measurement.

## Why it is worth measuring rather than assuming

`DODX_FORWARD_FIRING_DESIGN.md` records the precedent: DODX forwards stopped
firing entirely under KTPAMXX 2.7.12 (FNullEnt mishandling on the world entity)
and the regression went unnoticed in production until someone investigated by
hand. Engine-layer interference in this stack is a demonstrated failure mode,
not a theoretical one. A loader change is exactly the kind of thing that could
reproduce it.

## What is compared, and what is deliberately not

Compared: the module set and their statuses, the plugin set and their statuses,
and whether anything reports a failed load. These are the things production
depends on and that a misbehaving loader would disturb.

Not compared: `meta list` (only exists under Metamod, so it can only ever
differ), plugin *ordering* (Metamod and extension mode legitimately differ
here), and anything bot-related. A diff that flags known-and-expected
differences trains people to ignore it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# `amxx modules` / `amxx plugins` are fixed-column. tests/smoke/parse.py already
# has truncation-aware parsers keyed off KTPAMXX's srvcmd.cpp format strings;
# this is deliberately looser because it only needs name + status, and a strict
# parser that drifts silently reports "no modules", which reads as catastrophe.
_NAME_STATUS = re.compile(r"^\s*\[?\s*\d*\s*\]?\s*(\S.*?)\s{2,}(\S.*?)\s*$")

_STATUS_WORDS = ("running", "loaded", "debug", "bad load", "error", "failed",
                 "stopped", "paused")


def _extract(block: str) -> dict[str, str]:
    """Map name -> status line fragment, tolerantly."""
    out: dict[str, str] = {}
    for raw in block.splitlines():
        line = raw.rstrip()
        low = line.lower()
        if not line.strip() or low.startswith(("currently", "num ", "name ", "-")):
            continue
        status = next((w for w in _STATUS_WORDS if w in low), "")
        if not status:
            continue
        m = _NAME_STATUS.match(line)
        name = (m.group(1) if m else line.split()[0]).strip()
        # Drop a leading index column if the regex kept one.
        name = re.sub(r"^\[?\d+\]?\s+", "", name).strip()
        if name:
            out[name] = status
    return out


@dataclass
class Fingerprint:
    topology: str
    modules: dict[str, str] = field(default_factory=dict)
    plugins: dict[str, str] = field(default_factory=dict)
    raw: dict[str, str] = field(default_factory=dict)

    @property
    def failed(self) -> list[str]:
        bad = ("bad load", "error", "failed")
        return sorted(
            [f"module:{n}" for n, s in self.modules.items() if s in bad]
            + [f"plugin:{n}" for n, s in self.plugins.items() if s in bad]
        )

    def to_dict(self) -> dict:
        return {
            "topology": self.topology,
            "modules": self.modules,
            "plugins": self.plugins,
            "failed": self.failed,
        }


def capture(handle, topology: str) -> Fingerprint:
    """Read the stack's self-report over rcon."""
    mods = handle.rcon("amxx modules")
    plugs = handle.rcon("amxx plugins")
    fp = Fingerprint(topology=topology)
    fp.modules = _extract(mods)
    fp.plugins = _extract(plugs)
    fp.raw = {"amxx modules": mods.strip(), "amxx plugins": plugs.strip()}
    return fp


# The three modules production runs. Named explicitly: "the sets are equal" is
# satisfied by both being empty, which is exactly what a broken loader looks
# like.
REQUIRED_MODULES = ("amxxcurl", "reapi", "dodx")


def diff(a: Fingerprint, b: Fingerprint) -> dict:
    """Compare two topologies. Empty `differences` means non-interference on
    everything checked."""
    differences: list[str] = []

    a_mods, b_mods = set(a.modules), set(b.modules)
    for name in sorted(a_mods - b_mods):
        differences.append(f"module missing under {b.topology}: {name}")
    for name in sorted(b_mods - a_mods):
        differences.append(f"module only under {b.topology}: {name}")
    for name in sorted(a_mods & b_mods):
        if a.modules[name] != b.modules[name]:
            differences.append(
                f"module {name}: {a.topology}={a.modules[name]!r} "
                f"{b.topology}={b.modules[name]!r}")

    a_plugs, b_plugs = set(a.plugins), set(b.plugins)
    for name in sorted(a_plugs - b_plugs):
        differences.append(f"plugin missing under {b.topology}: {name}")
    for name in sorted(a_plugs & b_plugs):
        if a.plugins[name] != b.plugins[name]:
            differences.append(
                f"plugin {name}: {a.topology}={a.plugins[name]!r} "
                f"{b.topology}={b.plugins[name]!r}")
    # Extra plugins under Metamod are expected (the bot). Reported, not flagged.
    extra_plugins = sorted(b_plugs - a_plugs)

    # Absolute checks, not just symmetry: two empty stacks compare equal.
    missing_required = []
    for fp in (a, b):
        joined = " ".join(fp.modules).lower()
        for req in REQUIRED_MODULES:
            if req not in joined:
                missing_required.append(f"{req} absent under {fp.topology}")

    return {
        "differences": differences,
        "extra_plugins_under_bot_topology": extra_plugins,
        "failed_a": a.failed,
        "failed_b": b.failed,
        "missing_required_modules": missing_required,
        "interference_detected": bool(differences or missing_required
                                      or a.failed or b.failed),
    }
