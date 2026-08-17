"""Tests for the containment preconditions.

These guard a failure with no feedback loop: a Lane B run that reaches a real
Discord channel or the HLTV API succeeds, looks green, and tells nobody. So
every check is tested in both directions, and the vacuous case — a check that
matched nothing and therefore proved nothing — is tested too, because that is
how this kind of guard rots.
"""

from __future__ import annotations

import pytest

from .containment import (ContainmentError, assert_no_outbound_config,
                          assert_test_match_id, strip_outbound_plugins)

BLANK_DISCORD = """\
; KTP Discord relay
discord_relay_url =
discord_auth_secret =
discord_channel_id =
"""

BLANK_HLTV = """\
hltv_api_url = ""
hltv_api_key = ""
hltv_port = 27020
"""


def _config(tmp_path, **files):
    for name, body in files.items():
        (tmp_path / name).write_text(body, encoding="utf-8")
    return tmp_path


# -- the happy path --------------------------------------------------------


def test_blank_config_passes(tmp_path):
    d = _config(tmp_path, **{"discord.ini": BLANK_DISCORD,
                             "hltv_recorder.ini": BLANK_HLTV})
    checked = assert_no_outbound_config(d)
    assert any("discord_relay_url" in c for c in checked)
    assert any("hltv_api_url" in c for c in checked)


def test_quoted_empty_counts_as_empty(tmp_path):
    """These files mix `key =` and `key = ""`. Treating the quoted form as a
    non-empty value would fail every clean run."""
    d = _config(tmp_path, **{"hltv_recorder.ini": BLANK_HLTV})
    assert assert_no_outbound_config(d)


# -- the failures it exists for --------------------------------------------


def test_a_real_discord_url_is_fatal(tmp_path):
    d = _config(tmp_path, **{
        "discord.ini": BLANK_DISCORD.replace(
            "discord_relay_url =",
            "discord_relay_url = https://relay.ktpdod.com/hook"),
        "hltv_recorder.ini": BLANK_HLTV})
    with pytest.raises(ContainmentError, match="reach a real service"):
        assert_no_outbound_config(d)


def test_a_populated_secret_is_fatal(tmp_path):
    """A URL with no secret may be harmless; a secret means someone pasted a
    working config in, and the URL is probably next."""
    d = _config(tmp_path, **{
        "discord.ini": BLANK_DISCORD.replace(
            "discord_auth_secret =", "discord_auth_secret = hunter2"),
        "hltv_recorder.ini": BLANK_HLTV})
    with pytest.raises(ContainmentError):
        assert_no_outbound_config(d)


def test_hltv_url_is_fatal(tmp_path):
    d = _config(tmp_path, **{
        "hltv_recorder.ini": 'hltv_api_url = "https://api.ktpdod.com"\n'})
    with pytest.raises(ContainmentError):
        assert_no_outbound_config(d)


def test_commented_out_url_is_not_a_violation(tmp_path):
    """Otherwise every config documenting its own format would fail."""
    d = _config(tmp_path, **{
        "discord.ini": BLANK_DISCORD + "; discord_relay_url = https://example\n",
        "hltv_recorder.ini": BLANK_HLTV})
    assert assert_no_outbound_config(d)


# -- the vacuous case ------------------------------------------------------


def test_a_directory_with_no_outbound_keys_is_fatal(tmp_path):
    """The rot this guards against: keys get renamed, the check matches
    nothing, and a run that reaches everything reports containment as passed.
    'Found nothing' must not read as 'found nothing bad'."""
    d = _config(tmp_path, **{"ktp.ini": "season_active = false\n"})
    with pytest.raises(ContainmentError, match="no outbound keys"):
        assert_no_outbound_config(d)


def test_an_empty_directory_is_fatal(tmp_path):
    with pytest.raises(ContainmentError):
        assert_no_outbound_config(tmp_path)


# -- plugin stripping ------------------------------------------------------


PLUGINS = """\
; KTP plugin list
admin.amxx
stats_logging.amxx
KTPMatchHandler.amxx debug
KTPHudObserver.amxx debug
"""


def test_hud_observer_is_dropped():
    text, dropped = strip_outbound_plugins(PLUGINS)
    assert dropped == ["KTPHudObserver.amxx"]
    assert "KTPHudObserver.amxx debug" not in text


def test_the_rest_of_the_list_is_untouched():
    """The lane must run production's plugin set minus the exceptions, not a
    different list — otherwise it stops testing the stack it claims to."""
    text, _ = strip_outbound_plugins(PLUGINS)
    for keep in ("admin.amxx", "stats_logging.amxx", "KTPMatchHandler.amxx debug"):
        assert keep in text


def test_the_removal_is_recorded_in_the_file():
    """A silently shorter list is the kind of difference that costs an hour
    later. Leave a comment saying what went and why."""
    text, _ = strip_outbound_plugins(PLUGINS)
    assert "[lane-b] removed KTPHudObserver.amxx" in text


def test_stripping_is_idempotent():
    once, _ = strip_outbound_plugins(PLUGINS)
    twice, dropped = strip_outbound_plugins(once)
    assert dropped == []
    assert once == twice


# -- match id --------------------------------------------------------------


def test_a_test_match_id_passes():
    assert assert_test_match_id("1754839201-TEST") == "1754839201-TEST"


def test_a_production_shaped_id_is_fatal():
    """If the id has no -TEST suffix then either this is not a test-mode build
    or the shape changed; either way the rows would be indistinguishable from
    a real match."""
    with pytest.raises(ContainmentError, match="-TEST"):
        assert_test_match_id("1754839201-DEN5")


def test_an_empty_id_is_fatal():
    with pytest.raises(ContainmentError, match="empty match_id"):
        assert_test_match_id("")
