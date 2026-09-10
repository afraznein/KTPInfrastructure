"""Guards for `scripts/ktp-timezone-drift.py`.

The fleet agrees on America/New_York today, so every live run of that check
passes, and a check that has only ever been seen to pass is a check nobody has
tested. These tests inject the drift the fleet does not have: a host stamping
its log lines in UTC, a database that stopped following the host clock, a
daemon with TZ pinned in its environment -- and the ways the probe itself can
fail while looking clean, which on this estate has repeatedly been the more
expensive direction.

The fixtures are built from a real measurement: Atlanta's dod-27015 log at
`L 09/09/2026 - 17:17:01` with mtime 1788988621. Drift is produced by moving
one reading and leaving the other alone, which is exactly what a mis-provisioned
host does.

Loaded by path, with `paramiko` stubbed: the script imports it at module scope
but nothing under test opens a connection.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "ktp-timezone-drift.py"

TZ = "America/New_York"
try:
    ZONE = ZoneInfo(TZ)
except ZoneInfoNotFoundError:  # a machine with no tz database
    ZONE = None

pytestmark = pytest.mark.skipif(
    ZONE is None,
    reason="no tz database here; ktp-timezone-drift.py refuses to run on such a "
           "machine too, so there is nothing meaningful to assert")

# 2026-09-09 17:17:01 EDT, off Atlanta's dod-27015.
CLEAN_EPOCH = 1788988621
CLEAN_STAMP = "L 09/09/2026 - 17:17:01: [KTP_PROFILE] net: clients=0"


def _load_module():
    sys.modules.setdefault("paramiko", types.ModuleType("paramiko"))
    spec = importlib.util.spec_from_file_location("_ktp_timezone_drift", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def tzd():
    return _load_module()


@pytest.fixture
def ref(tzd):
    return tzd.zone_reference(TZ, CLEAN_EPOCH)


def game_probe(instances=None, complete=True, negative_control_rc="2", **host):
    """A game host's probe output. Defaults describe a correct host."""
    fields = {
        "clock_epoch": str(CLEAN_EPOCH),
        "clock_offset": "-0400",
        "clock_abbrev": "EDT",
        "localtime_target": "/usr/share/zoneinfo/America/New_York",
        "timedatectl_Timezone": "America/New_York",
        "timedatectl_NTP": "yes",
        "timedatectl_NTPSynchronized": "yes",
    }
    fields.update(host)
    lines = ["PROBE_BEGIN"]
    lines += ["%s=%s" % kv for kv in fields.items()]
    lines.append("negative_control_rc=%s" % negative_control_rc)
    if instances is None:
        instances = {"27015": {}}
    for port, over in instances.items():
        inst = {
            "hostname_lines": "1",
            "logfile": "/home/dodserver/dod-%s/serverfiles/dod/logs/L0909100.log" % port,
            "log_mtime": str(CLEAN_EPOCH),
            "log_lastline": CLEAN_STAMP,
            "probe_epoch": str(CLEAN_EPOCH),
        }
        inst.update(over)
        lines.append("instance=%s" % port)
        lines += ["%s=%s" % kv for kv in inst.items() if kv[1] is not None]
    if complete:
        lines.append("PROBE_END")
    return "\n".join(lines) + "\n"


def data_probe(mysql_row=None, **host):
    fields = {
        "clock_epoch": str(CLEAN_EPOCH),
        "clock_offset": "-0400",
        "clock_abbrev": "EDT",
        "localtime_target": "/usr/share/zoneinfo/America/New_York",
        "timedatectl_Timezone": "America/New_York",
        "timedatectl_NTP": "yes",
        "timedatectl_NTPSynchronized": "yes",
        "daemon_mainpid": "2532879",
        "daemon_env_vars": "8",
        "daemon_tz_vars": "0",
        "mysql_rc": "0",
        "mysql_row": mysql_row or "EDT|SYSTEM|SYSTEM|-14400|0|159",
    }
    fields.update(host)
    lines = ["PROBE_BEGIN"] + ["%s=%s" % kv for kv in fields.items()] + ["PROBE_END"]
    return "\n".join(lines) + "\n"


def evaluate_game(tzd, ref, raw, auditor_epoch=CLEAN_EPOCH):
    findings = []
    probe = tzd.parse_probe(raw)
    tzd.evaluate_clock("H", probe, ref, 5, auditor_epoch, findings)
    tzd.evaluate_instances("H", probe, ref, 2, findings)
    return findings


def evaluate_data(tzd, ref, raw, auditor_epoch=CLEAN_EPOCH):
    findings = []
    probe = tzd.parse_probe(raw)
    tzd.evaluate_clock("D", probe, ref, 5, auditor_epoch, findings)
    tzd.evaluate_data_server("D", probe, ref, findings)
    return findings


def levels(findings):
    return [f.level for f in findings]


# --------------------------------------------------------------- positive control

def test_module_exposes_the_functions_under_test(tzd):
    """If the loader produced a stub, every assertion below passes vacuously."""
    for name in ("parse_probe", "zone_reference", "log_stamp_epoch",
                 "evaluate_clock", "evaluate_instances", "evaluate_data_server",
                 "exit_code"):
        assert callable(getattr(tzd, name, None)), "%s missing from module" % name


def test_the_reference_zone_is_derived_not_written_down(tzd):
    """EDT in September, EST in January, from the same call."""
    summer = tzd.zone_reference(TZ, CLEAN_EPOCH)
    winter = tzd.zone_reference(TZ, CLEAN_EPOCH + 150 * 86400)
    assert (summer["abbrev"], summer["offset"], summer["offset_seconds"]) == \
        ("EDT", "-0400", -14400)
    assert (winter["abbrev"], winter["offset"], winter["offset_seconds"]) == \
        ("EST", "-0500", -18000)


# ------------------------------------------------------------- the fleet as it is

def test_a_correct_host_produces_no_findings(tzd, ref):
    assert evaluate_game(tzd, ref, game_probe()) == []


def test_a_correct_data_server_reports_only_the_timezone_tables(tzd, ref):
    findings = evaluate_data(tzd, ref, data_probe())
    assert levels(findings) == ["INFO"]
    assert "time_zone_name" in findings[0].message
    assert tzd.exit_code(findings) == 0


# ------------------------------------------------- injected drift: the whole point

def test_a_host_stamping_in_utc_is_caught_loudly(tzd, ref):
    """The arrival path: a rebuilt host left on UTC. Its log stamp reads four
    hours ahead of the same instant in Eastern, while mtime is absolute."""
    utc_line = "L 09/09/2026 - 21:17:01: [KTP_PROFILE] net: clients=0"
    findings = evaluate_game(tzd, ref, game_probe(
        instances={"27015": {"log_lastline": utc_line}}))
    assert levels(findings) == ["DRIFT"]
    assert "+14400s" in findings[0].message
    assert tzd.exit_code(findings) == 2


def test_the_load_bearing_check_fires_even_when_timedatectl_is_perfect(tzd, ref):
    """timedatectl reads config; this reads what the engine actually wrote. A
    host can satisfy the first and fail the second, which is why the config
    checks are secondary."""
    utc_line = "L 09/09/2026 - 21:17:01: x"
    probe = tzd.parse_probe(game_probe(instances={"27015": {"log_lastline": utc_line}}))
    assert probe["host"]["timedatectl_Timezone"] == "America/New_York"
    findings = []
    tzd.evaluate_clock("H", probe, ref, 5, CLEAN_EPOCH, findings)
    assert findings == []
    tzd.evaluate_instances("H", probe, ref, 2, findings)
    assert levels(findings) == ["DRIFT"]


def test_one_bad_instance_among_good_ones_is_reported_alone(tzd, ref):
    findings = evaluate_game(tzd, ref, game_probe(instances={
        "27015": {},
        "27016": {"log_lastline": "L 09/09/2026 - 21:17:01: x"},
        "27017": {},
    }))
    assert levels(findings) == ["DRIFT"]
    assert findings[0].subject == "dod-27016"


def test_a_host_whose_clock_is_wrong_but_zone_is_right_is_still_caught(tzd, ref):
    """Stamp and mtime come off the same clock, so they agree with each other
    while both being hours from reality. The clock comparison is the leg that
    covers this."""
    findings = evaluate_game(tzd, ref, game_probe(), auditor_epoch=CLEAN_EPOCH - 3600)
    assert levels(findings) == ["DRIFT"]
    assert "host clock" in findings[0].message


def test_unsynchronised_ntp_is_drift(tzd, ref):
    findings = evaluate_game(tzd, ref, game_probe(timedatectl_NTPSynchronized="no"))
    assert levels(findings) == ["DRIFT"]


def test_a_relocated_localtime_symlink_is_drift(tzd, ref):
    findings = evaluate_game(tzd, ref, game_probe(
        localtime_target="/usr/share/zoneinfo/Etc/UTC",
        clock_offset="+0000", clock_abbrev="UTC",
        timedatectl_Timezone="Etc/UTC"))
    assert levels(findings) == ["DRIFT", "DRIFT", "DRIFT"]


def test_mysql_drifting_off_the_host_clock_is_caught(tzd, ref):
    findings = evaluate_data(tzd, ref, data_probe(mysql_row="UTC|UTC|SYSTEM|0|0|159"))
    assert sorted(levels(findings)) == ["DRIFT", "DRIFT", "DRIFT", "INFO"]
    assert tzd.exit_code(findings) == 2


def test_a_daemon_with_tz_pinned_in_its_environment_is_drift(tzd, ref):
    findings = evaluate_data(tzd, ref, data_probe(daemon_tz_vars="1"))
    assert "DRIFT" in levels(findings)
    assert tzd.exit_code(findings) == 2


# ------------------------------------- probes that fail while looking like a pass

def test_a_truncated_probe_is_an_error_not_a_clean_host(tzd, ref):
    """A killed probe emits a prefix that parses perfectly."""
    findings = evaluate_game(tzd, ref, game_probe(complete=False))
    assert levels(findings) == ["ERROR"]
    assert tzd.exit_code(findings) == 1


def test_a_negative_control_that_succeeded_invalidates_the_host(tzd, ref):
    """If listing a directory that does not exist returns success, a denied
    listing is indistinguishable from a clean one."""
    findings = evaluate_game(tzd, ref, game_probe(negative_control_rc="0"))
    assert "ERROR" in levels(findings)


def test_no_instance_directories_is_an_error_not_a_pass(tzd, ref):
    findings = evaluate_game(tzd, ref, game_probe(instances={}))
    assert levels(findings) == ["ERROR"]


def test_a_failed_positive_control_stops_that_instance_counting(tzd, ref):
    """A missing dodserver.cfg means the probe is reading the wrong tree; the
    instance must not then be graded clean on whatever it did read."""
    findings = evaluate_game(tzd, ref, game_probe(instances={
        "27015": {"hostname_lines": "NOFILE",
                  "log_lastline": "L 09/09/2026 - 21:17:01: x"}}))
    assert levels(findings) == ["ERROR"]


def test_an_absent_log_is_an_error_not_a_pass(tzd, ref):
    findings = evaluate_game(tzd, ref, game_probe(instances={
        "27015": {"logfile": "NONE", "log_mtime": None,
                  "log_lastline": None, "probe_epoch": None}}))
    assert levels(findings) == ["ERROR"]


def test_an_unparseable_last_line_is_an_error(tzd, ref):
    findings = evaluate_game(tzd, ref, game_probe(instances={
        "27015": {"log_lastline": "Permission denied"}}))
    assert levels(findings) == ["ERROR"]


def test_a_failed_mysql_query_is_an_error(tzd, ref):
    findings = evaluate_data(tzd, ref, data_probe(
        mysql_rc="1", mysql_row="ERROR 1045 (28000): Access denied"))
    assert levels(findings) == ["ERROR"]


def test_an_unreadable_daemon_environment_is_an_error_not_a_zero(tzd, ref):
    """`grep -c TZ=` returns 0 for both 'no TZ set' and 'could not read'."""
    findings = evaluate_data(tzd, ref, data_probe(
        daemon_mainpid="0", daemon_env_vars="UNREADABLE", daemon_tz_vars="0"))
    assert "ERROR" in levels(findings)


def test_a_schema_control_of_zero_invalidates_the_mysql_row(tzd, ref):
    findings = evaluate_data(tzd, ref, data_probe(mysql_row="UTC|UTC|UTC|0|0|0"))
    assert levels(findings) == ["ERROR"]


def test_error_outranks_drift_in_the_exit_code(tzd):
    both = [tzd.Finding("DRIFT", "H", "", "x"), tzd.Finding("ERROR", "H", "", "y")]
    assert tzd.exit_code(both) == 1
    assert tzd.exit_code([tzd.Finding("INFO", "H", "", "z")]) == 0


# ------------------------------------------------------------------ DST fall-back

def test_the_ambiguous_fall_back_hour_does_not_read_as_drift(tzd, ref):
    """01:30 on 2026-11-01 names two instants in Eastern. Resolving to the wrong
    one would report an hour of legitimate lines as drift every November."""
    second_pass = int(datetime(2026, 11, 1, 1, 30, 0,
                               tzinfo=ZONE, fold=1).timestamp())
    findings = evaluate_game(tzd, ref, game_probe(instances={
        "27015": {"log_lastline": "L 11/01/2026 - 01:30:00: x",
                  "log_mtime": str(second_pass),
                  "probe_epoch": str(second_pass)}}))
    assert findings == []


def test_log_stamp_epoch_rejects_a_line_it_cannot_read(tzd):
    assert tzd.log_stamp_epoch("no stamp here", ZONE) is None
    assert tzd.log_stamp_epoch("L 13/45/2026 - 99:99:99: x", ZONE) is None
