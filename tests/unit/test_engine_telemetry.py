from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.e2e_stats import engine_telemetry  # noqa: E402

STAMP = "L 09/09/2026 - 14:03:11: "
NET = (STAMP + "[KTP_PROFILE] net: clients=0 unlag=1 lagcomp_off=0 "
       "ignorecmd_hits=0 drops=0 latzero=0 choke_peak=0 loss_worst=0 "
       "latency_worst=0.0ms jitter_worst=0.0ms maxunlag=300ms maxunlag_hits=0 "
       "maxunlag_excess_worst=0.0ms shadow=0ms shadow_hits=0 shadow_worst=0.0ms")
REWIND = (STAMP + "[KTP_PROFILE] rewind: attempts=0 miss=0 skip=0 "
          "depth_worst=0.0ms dist_worst=0.0u")
DETAIL = (STAMP + "[KTP_PROFILE] net_detail: lagcomp_first=-1(-) "
          "latency_worst=-1(-) jitter_worst=-1(-) maxunlag_excess_worst=-1(-) "
          "shadow_worst=-1(-) drops_worst=-1(-) drops_worst_n=0 "
          "latzero_worst=-1(-) latzero_worst_n=0")

HEALTHY = "\n".join([NET, DETAIL, REWIND])


def test_a_healthy_pair_of_records_passes():
    evidence = engine_telemetry.summarise(HEALTHY, expect_maxunlag_ms=300.0)
    assert evidence["status"] == "ok"
    assert evidence["net_records"] == 1
    assert evidence["rewind_records"] == 1
    assert evidence["missing_fields"] == []


def test_the_detail_row_is_not_mistaken_for_a_net_row():
    # It carries several of the same keys, so a prefix match on "net" would
    # count it and then pass the field check against the wrong line.
    assert engine_telemetry.parse(DETAIL, engine_telemetry.NET_MARKER) == []
    assert engine_telemetry.summarise(
        "\n".join([DETAIL, REWIND]))["status"] == "failed"


def test_an_engine_that_emits_nothing_fails():
    evidence = engine_telemetry.summarise("boot ok\nmap loaded\n")
    assert evidence["status"] == "failed"
    assert "no '[KTP_PROFILE] net:'" in evidence["detail"]


def test_a_dropped_instrumentation_field_is_named():
    stripped = NET.replace(" maxunlag_hits=0", "")
    evidence = engine_telemetry.summarise("\n".join([stripped, REWIND]))
    assert evidence["status"] == "failed"
    assert evidence["missing_fields"] == ["maxunlag_hits"]


def test_a_missing_rewind_record_fails_even_when_net_is_intact():
    assert engine_telemetry.summarise(NET)["status"] == "failed"


def test_maxunlag_must_echo_the_configured_ceiling():
    # Without this a record of frozen constants satisfies every other check.
    assert engine_telemetry.summarise(
        HEALTHY, expect_maxunlag_ms=500.0)["status"] == "failed"
    assert engine_telemetry.summarise(
        HEALTHY, expect_maxunlag_ms=300.0)["maxunlag_ms_echoed"] is True


def test_counters_are_recorded_not_asserted():
    # SV_SetupMove is skipped for fakeclients, so Lane B's bots cannot move
    # these. An all-zero record is the correct result, not a failure.
    evidence = engine_telemetry.summarise(HEALTHY, expect_maxunlag_ms=300.0)
    assert evidence["status"] == "ok"
    assert evidence["observed"]["maxunlag_hits"] == 0.0
    assert evidence["observed"]["clients"] == 0.0
    assert evidence["observed"]["rewind_attempts"] == 0.0


def test_populated_counters_are_reported_when_they_do_occur():
    populated = NET.replace("clients=0", "clients=10").replace(
        "maxunlag_hits=0", "maxunlag_hits=18").replace(
        "maxunlag_excess_worst=0.0ms", "maxunlag_excess_worst=412.7ms")
    evidence = engine_telemetry.summarise(
        "\n".join([populated, REWIND.replace("attempts=0", "attempts=4812")]),
        expect_maxunlag_ms=300.0)
    assert evidence["status"] == "ok"
    assert evidence["observed"]["clients"] == 10.0
    assert evidence["observed"]["maxunlag_hits"] == 18.0
    assert evidence["observed"]["maxunlag_excess_worst"] == 412.7
    assert evidence["observed"]["rewind_attempts"] == 4812.0


def test_repeated_intervals_are_all_collected():
    evidence = engine_telemetry.summarise(
        "\n".join([NET, REWIND] * 4), expect_maxunlag_ms=300.0)
    assert (evidence["net_records"], evidence["rewind_records"]) == (4, 4)
