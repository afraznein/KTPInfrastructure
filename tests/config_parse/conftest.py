"""Pytest fixtures + path constants for config-parse tests."""

from __future__ import annotations

from pathlib import Path

import pytest

# tests/config_parse/conftest.py → KTPInfrastructure/
INFRA_ROOT = Path(__file__).resolve().parents[2]
CONFIG_ROOT = INFRA_ROOT / "config"

# Profiles that ship complete real configs (not just .example).
# Online profile holds production-critical files; LAN is a partial profile
# tested separately if/when needed.
COMPLETE_PROFILES = ("local", "online")


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
