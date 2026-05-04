"""Pure-Python unit tests for scripts/spike_signatures.

No I/O, no MySQL, no hlds dependency. Runnable on any Python 3.10+ box
without setup. Designed to be wired into Tier 1 smoke alongside the
existing `tests/smoke/config_parse/` pytest gate (one more line in
the smoke caller workflow).

Test data is real production output sampled 2026-05-04 across the ATL
fleet. When the engine instrumentation format changes, these golden-
line fixtures must update in lockstep — the tests catch silent
regex drift early.
"""
from __future__ import annotations

import sys
from pathlib import Path

# scripts/ is a sibling of tests/, so reach in via path injection.
# Same pattern the integration tests use to import smoke harness modules.
_SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent / "scripts"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import pytest

from spike_signatures import (
    PHASES,
    ParsedSpike,
    magnitude_bucket,
    parse_spike_line,
)


# ---------------------------------------------------------------------------
# Real-production golden lines (sampled 2026-05-04 from ATL ports 27015-27019)
# ---------------------------------------------------------------------------

# Read-dominated, sub-5ms — the most common spike pattern in production.
LINE_READ_DOM_3MS = (
    "L 05/04/2026 - 13:45:58: [KTP_SPIKE] full=3.055ms read=3.039ms "
    "phys=0.007ms misc1=0.000ms send=0.008ms post=0.000ms steam=0.000ms "
    "gap=0.000ms"
)

# Steam-dominated, 5-10ms. Notable: NO `[KTP_SPIKE_STEAM]` per-phase line
# follows in production logs — confirms the umbrella line is the only
# reliable categorization source.
LINE_STEAM_DOM_7MS = (
    "L 05/04/2026 - 14:13:48: [KTP_SPIKE] full=7.054ms read=0.001ms "
    "phys=0.008ms misc1=0.000ms send=0.001ms post=0.000ms steam=7.044ms "
    "gap=0.000ms"
)

# Read-dominated with negative gap (rounding artifact, accepted by parser).
LINE_NEG_GAP = (
    "L 05/04/2026 - 14:06:06: [KTP_SPIKE] full=3.201ms read=3.181ms "
    "phys=0.010ms misc1=0.000ms send=0.009ms post=0.000ms steam=0.000ms "
    "gap=-0.000ms"
)

# Synthetic phys-dominated 158ms spike (matches the 2026-04-17 ATL2 incident
# that motivated the spike instrumentation in the first place — see
# CHANGES_SUMMARY-04-17 § "v917 Spike-Frame Phys Sub-Phase Instrumentation").
LINE_PHYS_158MS = (
    "L 05/04/2026 - 12:00:00: [KTP_SPIKE] full=158.761ms read=0.005ms "
    "phys=158.000ms misc1=0.000ms send=0.001ms post=0.000ms steam=0.000ms "
    "gap=0.755ms"
)


# ---------------------------------------------------------------------------
# parse_spike_line — happy path
# ---------------------------------------------------------------------------

def test_parses_read_dominated_3ms():
    s = parse_spike_line(LINE_READ_DOM_3MS)
    assert s is not None
    assert isinstance(s, ParsedSpike)
    assert s.full_ms == pytest.approx(3.055)
    assert s.dominant_phase == "READ"
    assert s.magnitude_bucket == "0-5ms"
    assert s.fingerprint == "READ:0-5ms"


def test_parses_steam_dominated_7ms():
    """The 14:13:48 production line — pure-stdlib categorization correctly
    identifies STEAM as dominant despite no per-phase line being emitted."""
    s = parse_spike_line(LINE_STEAM_DOM_7MS)
    assert s is not None
    assert s.full_ms == pytest.approx(7.054)
    assert s.dominant_phase == "STEAM"
    assert s.magnitude_bucket == "5-10ms"
    assert s.fingerprint == "STEAM:5-10ms"


def test_parses_phys_158ms():
    s = parse_spike_line(LINE_PHYS_158MS)
    assert s is not None
    assert s.dominant_phase == "PHYS"
    assert s.magnitude_bucket == "100-250ms"
    assert s.fingerprint == "PHYS:100-250ms"


def test_negative_gap_doesnt_break_parser():
    """Engine occasionally emits `gap=-0.000ms` on rounding artifacts —
    parser accepts the leading minus."""
    s = parse_spike_line(LINE_NEG_GAP)
    assert s is not None
    assert s.fingerprint == "READ:0-5ms"


def test_phases_dict_contains_every_phase():
    """`ParsedSpike.phases` should have all six phase names regardless of
    which is dominant — downstream callers (e.g., a future digest builder)
    may want to read non-dominant values too."""
    s = parse_spike_line(LINE_READ_DOM_3MS)
    assert s is not None
    assert set(s.phases.keys()) == set(PHASES)
    assert s.phases["read"] == pytest.approx(3.039)
    assert s.phases["phys"] == pytest.approx(0.007)
    assert s.phases["steam"] == pytest.approx(0.000)


def test_dominant_phase_is_uppercase():
    """Fingerprint key uses uppercase phase to keep DB-side queries
    case-insensitive without depending on the column's collation."""
    s = parse_spike_line(LINE_READ_DOM_3MS)
    assert s.dominant_phase == "READ"  # not "Read", not "read"
    assert ":" in s.fingerprint  # phase:bucket form


# ---------------------------------------------------------------------------
# parse_spike_line — null returns
# ---------------------------------------------------------------------------

def test_returns_none_for_profile_line():
    line = "L 05/04/2026 - 13:45:58: [KTP_PROFILE] frames=9819 fps=981.9 edicts_max=245"
    assert parse_spike_line(line) is None


def test_returns_none_for_per_phase_phys_line():
    """[KTP_SPIKE_PHYS] / _READ / _STEAM / _SEND lines have a different
    shape (per-phase sub-fields) and are NOT the categorization signal —
    the umbrella `[KTP_SPIKE]` line is. This test pins the contract."""
    line = (
        "L 05/04/2026 - 13:45:58: [KTP_SPIKE_PHYS] startframe=0.001ms "
        "entloop=0.006ms paused_startframe=0.000ms paused_hud=0.000ms"
    )
    assert parse_spike_line(line) is None


def test_returns_none_for_per_phase_read_line():
    line = (
        "L 05/04/2026 - 13:45:58: [KTP_SPIKE_READ] pkts=1(cl=1,conn=0,frag=0) "
        "recv=0.004ms proc=3.035ms worst=3.035ms"
    )
    assert parse_spike_line(line) is None


def test_returns_none_for_garbage():
    assert parse_spike_line("garbage") is None
    assert parse_spike_line("") is None
    assert parse_spike_line("[KTP_SPIKE] full=") is None  # incomplete


def test_returns_none_for_match_lines():
    """Match-flow log lines (`[KTPMatchHandler.amxx] [KTP] event=…`) must
    not be misidentified — they're frequent and would pollute the
    categorizer table if matched."""
    line = (
        "L 05/04/2026 - 13:45:58: [KTPMatchHandler.amxx] [KTP] "
        "event=MATCH_END_PROCESSED allowing_changelevel=true map=dod_solitude2"
    )
    assert parse_spike_line(line) is None


# ---------------------------------------------------------------------------
# magnitude_bucket — boundary tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("ms,expected", [
    (0.0,        "0-5ms"),
    (0.001,      "0-5ms"),
    (4.999,      "0-5ms"),
    (5.0,        "5-10ms"),       # boundary: lower-inclusive, upper-exclusive
    (9.999,      "5-10ms"),
    (10.0,       "10-25ms"),
    (24.999,     "10-25ms"),
    (25.0,       "25-50ms"),
    (49.999,     "25-50ms"),
    (50.0,       "50-100ms"),
    (99.999,     "50-100ms"),
    (100.0,      "100-250ms"),
    (158.761,    "100-250ms"),    # the 2026-04-17 ATL2 incident
    (249.999,    "100-250ms"),
    (250.0,      "250-500ms"),
    (499.999,    "250-500ms"),
    (500.0,      "500ms-1s"),
    (999.999,    "500ms-1s"),
    (1000.0,     "1s+"),
    (5000.0,     "1s+"),
    (-0.5,       "0-5ms"),        # negative full_ms clamps to 0 first
])
def test_magnitude_bucket_boundaries(ms, expected):
    assert magnitude_bucket(ms) == expected


# ---------------------------------------------------------------------------
# Misc shape / API
# ---------------------------------------------------------------------------

def test_parsed_spike_is_frozen():
    """ParsedSpike is `@dataclass(frozen=True)` — mutation must raise.
    This protects callers that key dicts/sets on the instance."""
    s = parse_spike_line(LINE_READ_DOM_3MS)
    with pytest.raises(Exception):  # FrozenInstanceError or AttributeError
        s.full_ms = 999.0  # type: ignore[misc]


def test_phases_tuple_count_matches_regex_groups():
    """Defense-in-depth: if anyone adds/removes a phase from the regex,
    the PHASES tuple must update in lockstep, otherwise parse_spike_line
    will KeyError or silently lose a phase."""
    s = parse_spike_line(LINE_READ_DOM_3MS)
    assert len(s.phases) == len(PHASES) == 6
