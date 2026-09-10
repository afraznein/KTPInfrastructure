"""The spawn-ownership table must match what the maps actually author.

`config/analytics/spawn_ownership.toml` seeds every report's opening flag
position. It used to be a majority vote over HUD recordings, which asserted
home flags on five maps that author none -- including the two most-played maps
in the pool -- because the vote was taken after skipping each half's opening
readings and therefore measured possession rather than authorship.

It is now read from each map's own BSP (`point_default_owner`). These tests
pin the corrected content so a future re-derivation from play cannot quietly
reintroduce the same class of error.

Deliberately in `tests/unit/`: config-tests.yml runs this directory on every
PR, and this file needs nothing but the repo itself -- no database, no BSPs,
no network.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
TABLE = REPO / "config" / "analytics" / "spawn_ownership.toml"

ALLIES, AXIS = 1, 2

# Every map the BSPs say authors owned flags, with the flag_index each takes.
# Verified 2026-09-10 by parsing the shipped .bsp of each map in the pool.
EXPECTED = {
    "dod_armory_b6": {0: (ALLIES, "Allied First"), 3: (AXIS, "Axis First")},
    "dod_solitude2": {0: (ALLIES, "Allied First"), 3: (AXIS, "Axis First")},
    "dod_saints2_b3e": {
        0: (ALLIES, "Allied 1st"),
        1: (ALLIES, "Allied 2nd"),
        3: (AXIS, "Axis 2nd"),
        4: (AXIS, "Axis 1st"),
    },
}

# Authored all-neutral. Each of these was asserting home flags before
# 2026-09-10; an entry reappearing means someone re-derived from possession.
AUTHORED_NEUTRAL = [
    "dod_halle",
    "dod_lennon5_b1",
    "dod_railroad2_s9a",
    "dod_railyard_s9d",
    "dod_thunder2",
    "dod_anjou_a5",
    "dod_anzio",
    "dod_harrington",
    "dod_lennon2",
    "dod_railyard_s9a",
    "dod_saints2_b2",
]


def _maps() -> dict:
    with TABLE.open("rb") as handle:
        return tomllib.load(handle).get("maps", {})


def test_the_table_parses_and_is_not_empty():
    """Positive control: an empty parse would make every assertion vacuous."""
    maps = _maps()
    assert maps, "spawn_ownership.toml has no [maps] section"
    assert set(EXPECTED) <= set(maps)


@pytest.mark.parametrize("map_name", sorted(EXPECTED))
def test_authored_home_flags_match_the_map(map_name):
    flags = _maps()[map_name]["flags"]
    got = {int(index): int(entry["owner"]) for index, entry in flags.items()}
    want = {index: owner for index, (owner, _) in EXPECTED[map_name].items()}
    assert got == want

    for index, (_, flag_name) in EXPECTED[map_name].items():
        assert flags[str(index)]["flag_name"] == flag_name


@pytest.mark.parametrize("map_name", AUTHORED_NEUTRAL)
def test_authored_neutral_maps_assert_nothing(map_name):
    """A map that authors no owned flag must not appear.

    The file's contract is that absence means "not asserted" -- callers do not
    infer neutral from it -- so omission is both correct and non-lossy here.
    """
    assert map_name not in _maps(), (
        f"{map_name} authors no owned control point in its BSP, but the table "
        "asserts one. This is the possession-vs-authorship error the table was "
        "corrected for on 2026-09-10; regenerate with "
        "scripts/map_spawn_ownership.py rather than deriving from play.")


def test_saints2_bridge_is_the_neutral_centre_not_an_allied_home_flag():
    """The specific regression, pinned on its own.

    saints2 ships `point_index = -1` on every CP, so its index order comes from
    the game DLL rather than the BSP. The previous table had The Bridge -- the
    map's neutral centre flag -- at index 0 and owned by allies, and omitted
    Allied 2nd entirely.
    """
    flags = _maps()["dod_saints2_b3e"]["flags"]
    names = {index: entry["flag_name"] for index, entry in flags.items()}
    assert "The Bridge" not in names.values()
    assert names["0"] == "Allied 1st"
    assert names["1"] == "Allied 2nd"


def test_every_listed_owner_is_a_real_team():
    """`0` must never appear: the loader drops it, so it would be a silent no-op."""
    for map_name, entry in _maps().items():
        for index, flag in entry["flags"].items():
            assert int(flag["owner"]) in (ALLIES, AXIS), (map_name, index)
