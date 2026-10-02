"""scripts/audit-config-key-drift.py must fire on the 2026-08-19 revert.

A guard that cannot be shown to fire on the case that motivated it is not a
guard, and the case here is specific: on 2026-08-19 a seven-month-old
discord.ini was pushed to /home/dod/distribute with only its auth secret
changed, which reverted `discord_channel_id` to a dead channel and deleted
`discord_channel_id_default` outright on all 24 instances. Match-start embeds
stopped. It took six weeks and three missed Sundays to notice, because the
failing path is reachable only by competitive play.

The script carries that reconstruction as `--selftest` so it can also be run by
hand on the data server with no credentials; this file is what makes it run on
every PR. ⚠️ Asserting the exit code of a SUBPROCESS, never of a pipeline: a
`| head` would launder a failure to 0, and that is this estate's standing trap.

These tests touch no host and need no credential.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
CHECK = SCRIPTS / "audit-config-key-drift.py"

sys.path.insert(0, str(SCRIPTS))
from ktp_config_kv import parse_text  # noqa: E402


def _load_check():
    """Import the dashed script by path; a dashed filename is not importable."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("_ktp_cfg_key_drift", CHECK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ------------------------------------------------------------------- selftest
def test_selftest_passes_and_exits_zero():
    """The whole reconstruction, through the real entry point.

    `capture_output` rather than a pipe, so the returncode asserted below is the
    script's own and not a pipeline's last stage.
    """
    result = subprocess.run([sys.executable, str(CHECK), "--selftest"],
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "SELFTEST PASSED" in result.stdout
    assert "FAIL" not in result.stdout, result.stdout


# ------------------------------------------- the two directions, independently
@pytest.fixture(scope="module")
def check():
    return _load_check()


JANUARY_SOURCE = (
    "discord_relay_url = https://relay.example/reply\n"
    "discord_auth_secret = PLACEHOLDER\n"
    "discord_channel_id = DEAD_CHANNEL\n"
)
LIVE_ON_THE_FLEET = (
    "discord_relay_url = https://relay.example/reply\n"
    "discord_auth_secret = PLACEHOLDER\n"
    "discord_channel_id = LIVE_CHANNEL\n"
    "discord_channel_id_default = DEFAULT_CHANNEL\n"
)
NAMES = ["KTP - Atlanta %d" % n for n in range(1, 25)]


def _compare(check, source_text, fleet_text, names=None, total=24):
    names = names or NAMES
    _, source_keys = parse_text(source_text, "source")
    _, fleet_keys = parse_text(fleet_text, "fleet")
    return check.compare(source_keys, dict((n, fleet_keys) for n in names),
                         names, total=total)


def test_a_reverted_value_is_a_differs_finding(check):
    findings, _ = _compare(check, JANUARY_SOURCE, LIVE_ON_THE_FLEET)
    assert ("discord_channel_id", "differs") in findings


def test_a_key_deleted_from_the_source_is_named(check):
    """The half an md5 comparison cannot name, and the half that broke embeds.

    KTPMatchHandler reads a missing key as "feature disabled" and posts nothing,
    successfully -- so nothing anywhere logs an error.
    """
    findings, _ = _compare(check, JANUARY_SOURCE, LIVE_ON_THE_FLEET)
    assert ("discord_channel_id_default", "source-missing") in findings


def test_a_source_key_that_never_landed_is_the_other_direction(check):
    findings, _ = _compare(check, LIVE_ON_THE_FLEET, JANUARY_SOURCE)
    assert ("discord_channel_id_default", "instance-missing") in findings


def test_the_key_that_was_meant_to_change_is_not_a_finding(check):
    """The rotation itself was legitimate. A check that flagged it would be
    noise on every rotation, and noise is how the real finding gets skimmed."""
    findings, _ = _compare(check, JANUARY_SOURCE, LIVE_ON_THE_FLEET)
    assert ("discord_auth_secret", "differs") not in findings
    assert ("discord_relay_url", "differs") not in findings


def test_fleetwide_agreement_against_a_stale_source_is_uniform(check):
    """`uniform` is the shape on a timer: the fleet is right, the source is
    stale, and the next touch of the file destroys the fleet's copy. It is also
    exactly what a uniformity-only check (ktp-verify-deploy.py) reads as clean."""
    findings, _ = _compare(check, JANUARY_SOURCE, LIVE_ON_THE_FLEET)
    assert findings[("discord_channel_id", "differs")]["shape"] == "uniform"
    assert findings[("discord_channel_id", "differs")]["count"] == 24


def test_partial_coverage_never_reads_as_uniform(check):
    """A key seen on 20 of 24 is `partial`. `uniform` is read as "the whole
    fleet agrees", and letting it mean "the part we reached agrees" is the
    vacuous pass this check exists to refuse."""
    findings, _ = _compare(check, JANUARY_SOURCE, LIVE_ON_THE_FLEET,
                           names=NAMES[:20], total=24)
    assert findings[("discord_channel_id", "differs")]["shape"] == "partial"


# ------------------------------------------------------- vacuity and parsing
def test_an_unparsable_file_yields_no_key_set():
    """Mixed shapes must not be guessed. Reading `discord_auth_secret = x` with
    the cvar reader invents a key whose value starts with `=`, which compares
    equal to nothing and reports drift that is an artifact of the reader."""
    assert parse_text("discord_channel_id = 1\nmp_timelimit 30\n", "m")[1] is None


def test_an_emptied_source_is_compared_not_skipped(check):
    """The 2026-08-19 revert taken to its limit. Returning None for an empty
    source would skip the path in precisely the direction that matters."""
    _, keys = parse_text("; all content removed\n\n", "e")
    assert keys == {}
    findings, _ = _compare(check, "; all content removed\n", LIVE_ON_THE_FLEET)
    assert findings, "an emptied source against a populated fleet found nothing"
    assert all(kind == "source-missing" for _, kind in findings)


def test_two_empty_sides_make_zero_comparisons(check):
    """So the caller can count it as nothing-to-compare rather than agreement."""
    _, comparisons = check.compare({}, {"a": {}}, ["a"], total=1)
    assert comparisons == 0


def test_comments_are_not_keys():
    """The first live run reported `;` and `#` as drifting keys in plugins.ini
    and 28 map configs, and classified the same file as two different flavours
    on the two sides. A comment read as a key is a finding that can be neither
    fixed nor true, and three of them hid two armed hazards that were real."""
    assert parse_text("admin.amxx\t; admin base\n", "p")[1] == {"admin.amxx": ""}
    assert "#" not in (parse_text("# note\nmp_timelimit 30\n", "c")[1] or {})
    assert ";" not in (parse_text("; note\nmp_timelimit 30\n", "c")[1] or {})


def test_a_marker_inside_a_value_survives():
    assert (parse_text("discord_relay_url = https://relay.example/reply\n", "d")[1]
            ["discord_relay_url"] == "https://relay.example/reply")
    assert parse_text('hostname "KTP;1"\n', "c")[1]["hostname"] == "KTP;1"


def test_a_repeated_cvar_is_positional(check):
    """A dropped third `exec` line is a named finding. The last-wins collapse
    the Tier-1 parser uses would report it only if the SURVIVING exec differed,
    which for an append-only list it usually does not -- the existing
    dodserver.cfg test had to assert that one on raw text to route around it."""
    _, three = parse_text("exec a.cfg\nexec b.cfg\nexec c.cfg\n", "s")
    _, two = parse_text("exec a.cfg\nexec b.cfg\n", "i")
    findings, _ = check.compare(three, {"i": two}, ["i"], total=1)
    assert ("exec#3", "instance-missing") in findings


# ---------------------------------------------------------------- redaction
def test_no_value_reaches_the_report(check):
    """The weekly audit publishes its artifacts to a PUBLIC repository, and
    these files mix a fleet-wide secret with per-instance routing. The report
    carries key names and counts; values are compared by digest in memory and
    the digests are not printed either -- a digest of a 19-digit channel id or
    a short password is a brute-forceable oracle, and no finding needs one."""
    secret = "SUPER_SECRET_VALUE_abc123"
    findings, _ = _compare(
        check,
        "discord_auth_secret = OLD\n",
        "discord_auth_secret = %s\n" % secret)
    report, stable, headline = check.build_report(
        dict((("addons/ktpamx/configs/discord.ini",) + k, v)
             for k, v in findings.items()),
        {"source_root": "/home/dod/distribute", "instances_expected": 24,
         "instances_compared": 24, "paths_in_scope": 1, "paths_compared": 1,
         "keys_compared": 24, "paths_with_nothing_to_compare": 0},
        {}, [], {}, True)
    for blob in (report, "\n".join(stable), headline):
        assert secret not in blob
        assert "OLD" not in blob


def test_an_identity_shaped_key_name_is_redacted(check):
    """users.ini keys an admin by quoted name or SteamID, and that file is in
    the distributor's scope. Shape, not a denylist."""
    assert check.redact_key("STEAM_0:1:12345678").startswith("<key redacted")
    assert check.redact_key('"SomePlayer"').startswith("<key redacted")
    assert check.redact_key("76561198000000000").startswith("<key redacted")
    assert check.redact_key("discord_channel_id") == "discord_channel_id"


# -------------------------------------------------------------- headline shape
def test_the_headline_reports_work_done_not_just_findings(check):
    """"count of failures = 0" was the alert that missed this incident, and it
    was zero because the code path never ran. Every clean report must state how
    much it actually compared."""
    report, _, headline = check.build_report(
        {}, {"source_root": "/home/dod/distribute", "instances_expected": 24,
             "instances_compared": 24, "paths_in_scope": 100,
             "paths_compared": 97, "keys_compared": 34612,
             "paths_with_nothing_to_compare": 4},
        {}, [], {}, False)
    for token in ("instances compared: 24/24", "paths compared: 97/100",
                  "keys compared: 34612", "nothing-to-compare: 4"):
        assert token in headline, headline
    assert headline in report
