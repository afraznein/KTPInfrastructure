"""Discord relay config — catches typos in keys that cause silent no-op
posts (KTPMatchHandler treats missing keys as 'feature disabled')."""

from __future__ import annotations

from pathlib import Path

import pytest

from .conftest import COMPLETE_PROFILES, resolve_config
from .parsers import parse_kv_file

# Required keys per the entrypoint + KTPMatchHandler / KTPAdminAudit
# Discord-posting paths. Empty values are valid for local profile (Discord
# disabled); online must have non-empty relay_url + auth_secret.
REQUIRED_KEYS = {
    "relay_url",
    "auth_secret",
    "match_channel",
    "admin_channel",
    "status_channel",
}


@pytest.fixture(params=COMPLETE_PROFILES)
def discord_ini(request) -> Path:
    return resolve_config(request.param, "discord.ini")


def test_discord_ini_parses(discord_ini):
    cfg = parse_kv_file(discord_ini)
    assert cfg, f"{discord_ini} produced no key/value pairs"


def test_required_keys_present(discord_ini):
    cfg = parse_kv_file(discord_ini)
    missing = REQUIRED_KEYS - set(cfg.keys())
    assert not missing, f"{discord_ini.name} missing required keys: {sorted(missing)}"


def test_relay_url_shape_when_set(discord_ini):
    """If relay_url has a value, it must look like an HTTP(S) URL. Online
    profile is a template (empty placeholders filled in at deploy time), so
    we check format-when-set rather than mandating non-empty."""
    cfg = parse_kv_file(discord_ini)
    url = cfg.get("relay_url", "")
    if url:
        assert url.startswith(("http://", "https://")), (
            f"{discord_ini.name}: relay_url should be an HTTP(S) URL, got {url!r}"
        )
