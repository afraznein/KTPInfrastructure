"""Discord relay config — catches typos in keys that cause silent no-op
posts (KTPMatchHandler treats missing keys as 'feature disabled')."""

from __future__ import annotations

from pathlib import Path

import pytest

from .conftest import COMPLETE_PROFILES, resolve_config
from .parsers import parse_kv_file

# Required keys = the union of what the two real parsers read:
#   ktp_discord.inc (AdminAudit/FileChecker/ScoreTracker/HLTVRecorder/...):
#     discord_relay_url / discord_auth_secret / discord_channel_id /
#     _12man / _scrim / _draft / _admin, plus any key containing
#     "discord_channel_id_audit" (collected into the audit set).
#   ktp_matchhandler_discord.inc (KTPMatchHandler): same core set plus
#     discord_channel_id_default (and no _admin/_audit).
# Empty values are valid for local/lan (Discord disabled); online fills them
# at deploy time. _12man matters: the plugin has NO fallback for it — a config
# missing the key silently drops every 12-man embed.
# NB: the pre-2026-07-07 version of this test required relay_url/auth_secret/
# match_channel/admin_channel — the OLD template keys the plugins never read,
# so a green test validated a config the stack would silently no-op on. Keys
# realigned to what actually gets parsed.
REQUIRED_KEYS = {
    "discord_relay_url",
    "discord_auth_secret",
    "discord_channel_id",
    "discord_channel_id_default",
    "discord_channel_id_12man",
    "discord_channel_id_scrim",
    "discord_channel_id_draft",
    "discord_channel_id_admin",
    "discord_channel_id_audit",
    "discord_channel_id_audit_external",
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


def test_values_not_quoted(discord_ini):
    """The plugin parsers (ktp_discord.inc / ktp_matchhandler_discord.inc) do
    copy+trim with NO quote stripping — a quoted "" is a real 2-char value that
    defeats the empty-value skip and enables Discord with garbage config, and a
    quoted real value ships the quotes into the URL/secret/channel id. Values
    must be bare in the raw file (parse_kv_file strips quotes, so this check
    reads the raw text)."""
    for lineno, raw in enumerate(discord_ini.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.split(";", 1)[0].strip()
        if not line or "=" not in line:
            continue
        value = line.partition("=")[2].strip()
        assert not (value.startswith('"') or value.endswith('"')), (
            f"{discord_ini.name}:{lineno}: quoted value {value!r} — the plugin "
            f"parsers do not strip quotes; write it bare (empty = nothing after '=')"
        )


def test_relay_url_shape_when_set(discord_ini):
    """If discord_relay_url has a value, it must be an HTTP(S) URL ending in
    /reply (the plugin POSTs to it verbatim and derives /health by swapping
    /reply). Online profile is a template with empty placeholders filled in at
    deploy time, so we check format-when-set rather than mandating non-empty."""
    cfg = parse_kv_file(discord_ini)
    url = cfg.get("discord_relay_url", "").strip('"')
    if url:
        assert url.startswith(("http://", "https://")), (
            f"{discord_ini.name}: discord_relay_url should be an HTTP(S) URL, got {url!r}"
        )
        assert url.endswith("/reply"), (
            f"{discord_ini.name}: discord_relay_url must end in /reply, got {url!r}"
        )
