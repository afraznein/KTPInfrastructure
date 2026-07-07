"""Catch the modules.ini regression class.

Examples this catches:
- Typo in a module name (`amxxxcurl` instead of `amxxcurl` → module won't load,
  cascades ALL plugins relying on `ktp_discord.inc` into bad-load — same shape
  as the 2026-04-14 incident, caught one tier earlier than smoke)
- Module referenced by name that doesn't ship with KTPAMXX
- Duplicate entries
"""

from __future__ import annotations

from pathlib import Path

import pytest

from .conftest import COMPLETE_PROFILES, CONFIG_ROOT
from .parsers import parse_modules_ini

# Modules that exist in the KTPAMXX codebase (typo guard only — see
# EXTENSION_MODE_MODULES for what a profile is actually ALLOWED to load).
KNOWN_MODULES: set[str] = {
    # Metamod-era AMXX core (NOT shipped in extension-mode artifacts)
    "fun",
    "engine",
    "fakemeta",
    "hamsandwich",
    # KTP-specific
    "dodx",
    "reapi",
    "amxxcurl",
    # Supporting (optional in any given profile)
    "sqlite",
    "sockets",
    "regex",
    "json",
    "geoip",
    "nvault",
}

# The ONLY modules an extension-mode profile may load. KTP runs AMXX as a
# ReHLDS extension (no Metamod); fun/engine/fakemeta/hamsandwich don't exist
# in the extension-mode artifacts, so listing them breaks server startup —
# config/online/modules.ini's own header says exactly this, yet the old
# whitelist above would have green-lit that edit (and config/lan shipped it
# for months, untested).
EXTENSION_MODE_MODULES: set[str] = {"reapi", "dodx", "amxxcurl"}


@pytest.fixture(params=COMPLETE_PROFILES)
def modules_ini(request) -> Path:
    return CONFIG_ROOT / request.param / "modules.ini"


def test_modules_ini_parses(modules_ini):
    names = parse_modules_ini(modules_ini)
    assert names, f"{modules_ini} produced no module entries"


def test_no_duplicate_modules(modules_ini):
    names = parse_modules_ini(modules_ini)
    seen: dict[str, int] = {}
    for i, n in enumerate(names, 1):
        if n in seen:
            pytest.fail(f"{modules_ini.name}: duplicate module {n!r}")
        seen[n] = i


def test_all_modules_known(modules_ini):
    names = parse_modules_ini(modules_ini)
    unknown = [n for n in names if n not in KNOWN_MODULES]
    if unknown:
        pytest.fail(
            f"{modules_ini.name} references unknown module(s): {unknown}\n"
            "If a new module was added to KTPAMXX, update KNOWN_MODULES."
        )


def test_required_modules_present(modules_ini):
    """KTP plugins universally depend on dodx + reapi + amxxcurl. Stripping
    any of them makes the entire plugin fleet 'bad load' — same blast radius
    as the 04-14 incident."""
    names = set(parse_modules_ini(modules_ini))
    missing = {"dodx", "reapi", "amxxcurl"} - names
    assert not missing, f"{modules_ini.name} missing required modules: {sorted(missing)}"


def test_only_extension_mode_modules(modules_ini):
    """Every KTP profile runs extension mode — a Metamod-era module in ANY
    profile's modules.ini tries to load a .so that isn't in the artifacts and
    breaks server startup outright."""
    names = set(parse_modules_ini(modules_ini))
    forbidden = names - EXTENSION_MODE_MODULES
    assert not forbidden, (
        f"{modules_ini.name} loads non-extension-mode module(s): {sorted(forbidden)} — "
        "extension-mode artifacts ship ONLY reapi/dodx/amxxcurl; anything else "
        "fails to load and kills startup"
    )
