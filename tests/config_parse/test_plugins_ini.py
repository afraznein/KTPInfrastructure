"""Catch the regression class where a plugins.ini edit breaks runtime load.

Examples this catches:
- Typo in a plugin filename (`KTPMatchHandle.amxx` → bad load at runtime)
- Duplicate entry (KTPAMXX commands-dedup at registration but still wastes
  a slot)
- `debug` flag accidentally promoted to online profile (kills JIT fleet-wide;
  the Makefile has a separate hard guard for this — we test it separately
  here for clarity)
- Required base plugin missing (admin.amxx)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from .conftest import COMPLETE_PROFILES, CONFIG_ROOT
from .parsers import parse_plugins_ini

# Plugin filenames the runtime currently expects across profiles. Update
# alongside any production rollout. Source of truth for the canonical
# expected set; the actual file may have a subset.
KNOWN_PLUGINS: set[str] = {
    "admin.amxx",
    "stats_logging.amxx",
    "KTPAdminAudit.amxx",
    "ktp_cvar.amxx",
    "ktp_file.amxx",
    "KTPMatchHandler.amxx",
    "KTPHLTVRecorder.amxx",
    "KTPPracticeMode.amxx",
    "KTPGrenadeLoadout.amxx",
    "KTPGrenadeDamage.amxx",
    "KTPHudObserver.amxx",  # external repo; loaded on local and online
    "KTPScoreTracker.amxx",
}


@pytest.fixture(params=COMPLETE_PROFILES)
def plugins_ini(request) -> Path:
    return CONFIG_ROOT / request.param / "plugins.ini"


def test_plugins_ini_parses(plugins_ini):
    entries = parse_plugins_ini(plugins_ini)
    assert entries, f"{plugins_ini} produced no plugin entries — empty or all-comments"


def test_admin_amxx_present(plugins_ini):
    entries = parse_plugins_ini(plugins_ini)
    files = [e.filename for e in entries]
    assert "admin.amxx" in files, (
        "admin.amxx is required (provides admin flag infrastructure for "
        f"every other plugin). Missing in {plugins_ini}"
    )


def test_no_duplicate_entries(plugins_ini):
    entries = parse_plugins_ini(plugins_ini)
    seen: dict[str, int] = {}
    for e in entries:
        if e.filename in seen:
            pytest.fail(
                f"{plugins_ini.name}: duplicate plugin {e.filename!r} on "
                f"lines {seen[e.filename]} and {e.line_number}"
            )
        seen[e.filename] = e.line_number


def test_all_referenced_plugins_known(plugins_ini):
    entries = parse_plugins_ini(plugins_ini)
    unknown = [e.filename for e in entries if e.filename not in KNOWN_PLUGINS]
    if unknown:
        pytest.fail(
            f"{plugins_ini.name} references plugin(s) not in KNOWN_PLUGINS: {unknown}\n"
            "If this is intentional, add to KNOWN_PLUGINS in test_plugins_ini.py."
        )


def test_online_profile_has_no_debug_flag():
    """Production-critical: a single `debug` flag in online disables AMXX
    JIT for ALL plugins fleet-wide. The Makefile has a separate lint guard;
    we duplicate the assertion here so the failure mode is tested even when
    the Makefile is bypassed (e.g. someone deploys via a different path)."""
    entries = parse_plugins_ini(CONFIG_ROOT / "online" / "plugins.ini")
    debug_entries = [e for e in entries if "debug" in e.flags]
    if debug_entries:
        names = ", ".join(f"{e.filename}:line{e.line_number}" for e in debug_entries)
        pytest.fail(
            f"online/plugins.ini has `debug` flag on {len(debug_entries)} plugin(s): {names}\n"
            "This kills the AMXX JIT globally on production. Move debug flags to "
            "local/plugins.ini only."
        )


def test_local_profile_has_hud_observer():
    """KTPHudObserver is an external repo, deployed via local/plugins/ mount
    locally. Catches accidental drop in local profile."""
    entries = parse_plugins_ini(CONFIG_ROOT / "local" / "plugins.ini")
    files = [e.filename for e in entries]
    assert "KTPHudObserver.amxx" in files, (
        "local/plugins.ini should list KTPHudObserver.amxx (smoke workflow "
        "strips it for CI; production deploy does not). If you intentionally "
        "removed it from local, update this test."
    )
