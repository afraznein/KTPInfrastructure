"""Pytest fixtures + path constants for config-parse tests."""

from __future__ import annotations

from pathlib import Path

import pytest

# tests/config_parse/conftest.py → KTPInfrastructure/
INFRA_ROOT = Path(__file__).resolve().parents[2]
CONFIG_ROOT = INFRA_ROOT / "config"

# Profiles that ship complete real configs (not just .example).
# Online profile holds production-critical files. LAN was excluded until
# 2026-07-07 — which is exactly how its modules.ini shipped Metamod-era
# modules (boot-breaking in extension mode) and its plugins.ini omitted
# admin.amxx/stats_logging for months without a red test. resolve_config's
# .example fallback covers lan's dodserver.cfg.example.
COMPLETE_PROFILES = ("local", "online", "lan")


def resolve_config(profile: str, filename: str) -> Path:
    """Return the path to read for a (profile, filename) pair.

    The online profile's secret-bearing files (discord.ini, hltv_recorder.ini,
    dodserver.cfg) are gitignored — only the .example templates are checked
    in. In CI / fresh checkouts, fall back to the .example sibling so the
    schema is still validated against what the repo actually ships.
    """
    real = CONFIG_ROOT / profile / filename
    if real.exists():
        return real
    example = real.with_name(f"{filename}.example")
    if example.exists():
        return example
    return real  # let the test surface the missing-file error


@pytest.fixture(scope="session")
def config_root() -> Path:
    return CONFIG_ROOT
