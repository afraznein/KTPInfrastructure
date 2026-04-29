"""HLTV recorder config — catches port typos and missing API URL/key that
would silently disable demo recording during competitive matches."""

from __future__ import annotations

from pathlib import Path

import pytest

from .conftest import COMPLETE_PROFILES, resolve_config
from .parsers import parse_kv_file

REQUIRED_KEYS = {"hltv_api_url", "hltv_api_key", "hltv_port"}

# HLTV port mapping per region (CLAUDE.md): Atlanta 27020, Dallas 27025,
# Denver 27030, NY 27035, Chicago 27040 (each +0..4 for 5 instances).
# So the configured base port should land in 27020-27044 inclusive.
HLTV_PORT_MIN = 27020
HLTV_PORT_MAX = 27044


@pytest.fixture(params=COMPLETE_PROFILES)
def hltv_ini(request) -> Path:
    return resolve_config(request.param, "hltv_recorder.ini")


def test_hltv_ini_parses(hltv_ini):
    cfg = parse_kv_file(hltv_ini)
    assert cfg, f"{hltv_ini} produced no key/value pairs"


def test_required_keys_present(hltv_ini):
    cfg = parse_kv_file(hltv_ini)
    missing = REQUIRED_KEYS - set(cfg.keys())
    assert not missing, f"{hltv_ini.name} missing required keys: {sorted(missing)}"


def test_hltv_port_is_valid_int(hltv_ini):
    cfg = parse_kv_file(hltv_ini)
    port_str = cfg["hltv_port"]
    try:
        port = int(port_str)
    except ValueError:
        pytest.fail(f"{hltv_ini.name}: hltv_port must be an integer, got {port_str!r}")
    assert 1024 <= port <= 65535, f"{hltv_ini.name}: hltv_port {port} out of valid range"


def test_online_hltv_port_in_known_range():
    """Online profile must use a port in the production HLTV range so the
    recorder hits the correct paired HLTV proxy on the data server."""
    cfg = parse_kv_file(resolve_config("online", "hltv_recorder.ini"))
    port = int(cfg["hltv_port"])
    assert HLTV_PORT_MIN <= port <= HLTV_PORT_MAX, (
        f"online/hltv_recorder.ini: hltv_port {port} outside production "
        f"range {HLTV_PORT_MIN}-{HLTV_PORT_MAX}. Region map: ATL 27020-24, "
        "DAL 27025-29, DEN 27030-34, NY 27035-39, CHI 27040-44."
    )


def test_hltv_api_url_shape_when_set(hltv_ini):
    """If hltv_api_url has a value, it must look like an HTTP(S) URL.
    Online profile is a template — empty values filled in at deploy time."""
    cfg = parse_kv_file(hltv_ini)
    url = cfg.get("hltv_api_url", "")
    if url:
        assert url.startswith(("http://", "https://")), (
            f"{hltv_ini.name}: hltv_api_url should be an HTTP(S) URL, got {url!r}"
        )
