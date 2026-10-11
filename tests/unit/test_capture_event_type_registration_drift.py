"""Drift guard for the capture EVENT-TYPE set, and for the guard itself.

The manifest grammar guard next door covers the shape of one log line. It is
structurally blind to this: `capabilities` reaches it as a `%s` conversion, so
whatever the producer lists inside that string is never read. The set of streams
the producer can emit lives in its own `g_kscEventNames` table, the daemon-side
registry that must know them is `scripts/match_analytics.py`'s
`CAPTURE_EVENT_TYPES`, and until this file nothing compared the two.

It has cost two outages with the same signature. `move` entered the producer on
2026-09-26 (KTPAMXX `fad90c84`) and the registry on 2026-09-29
(`aa02a823`) -- three days in which `ksc_emit_health` loops over the plugin's
whole enum, emits a health row for a type the daemon calls unknown, and
`capture_health` fails for every half of every match. `aim_vis` was the second.
Both were repaired by editing a list by hand after the fact.

The authoritative leg is `ArtifactSet.collect()`, which runs this against the
`.inc` extracted at the amxx sha under test -- so nothing here can go stale
behind KTPAMXX. What this file adds is the leg that runs on every PR, because
config-tests.yml runs tests/unit/ while tests/e2e_stats/ runs only inside a
Lane B job, and Lane B's corpus caller takes the `--no-plugin` branch that skips
collect's plugin checks entirely.

The producer text below is an EXERCISE CORPUS, not the contract. Its being out
of date costs nothing and proves nothing -- freshness lives in `collect()`.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts.match_analytics import (  # noqa: E402
    CAPTURE_EVENT_TYPES, CAPTURE_EVENT_TYPES_OPTIONAL)
from tests.e2e_stats import artifacts, manifest_contract  # noqa: E402

# Verbatim from KTPAMXX plugins/dod/ktp_stats_capture.inc at 0864ba4e, both
# halves of the pair this module reads: the enum the table is sized by, and the
# table. Comments kept, because stripping them is one of the things under test.
PRODUCER_SNAPSHOT = '''
enum {
	KSC_EVENT_LIFE = 0,
	KSC_EVENT_DAMAGE,
	KSC_EVENT_POSITION,
	KSC_EVENT_FRAG,
	KSC_EVENT_ASSIST,
	KSC_EVENT_BREAK,
	KSC_EVENT_FLAG_STATE,
	KSC_EVENT_FLAG_POSITION,
	KSC_EVENT_OBJECTIVE_ATTEMPT,
	// Keep membership before grenade_entity: schema-22/23 health finalizes after
	// grenade_entity, so every stream is reconciled before state is cleared.
	KSC_EVENT_TEAM_MEMBERSHIP,
	KSC_EVENT_GRENADE_ENTITY,
	KSC_EVENT_SHOT,
	KSC_EVENT_SCORE,
	KSC_EVENT_DUEL,
	KSC_EVENT_PLAYER_STATE,
	KSC_EVENT_GRENADE_THROW,
	// Crouch-input and footstep-emission census, appended so no index shifts.
	KSC_EVENT_MOVE,
	KSC_EVENT_COUNT
}

#define KSC_EVENT_UNTRACKED -1

new const g_kscEventNames[KSC_EVENT_COUNT][] = {
	"life", "damage", "position", "frag", "assist", "break",
	"flag_state", "flag_position", "objective_attempt", "team_membership",
	"grenade_entity", "shot", "score", "duel", "player_state", "grenade_throw",
	"move"
}
'''

REGISTRY = "match_analytics.CAPTURE_EVENT_TYPES"


def _assert(source, required=CAPTURE_EVENT_TYPES, optional=CAPTURE_EVENT_TYPES_OPTIONAL):
    manifest_contract.assert_event_types_registered(
        source, required, optional, registry_name=REGISTRY)


# -- 1. the machinery works, and the corpus is not vacuous --------------------

def test_the_extractors_find_something():
    """An extractor that matches nothing turns every check below into a pass."""
    names = manifest_contract.producer_event_types(PRODUCER_SNAPSHOT)
    members = manifest_contract.producer_event_enum(PRODUCER_SNAPSHOT)
    assert len(names) >= 11
    assert names[:3] == ("life", "damage", "position")
    assert len(members) == len(names)
    assert "KSC_EVENT_COUNT" not in members
    assert "KSC_EVENT_UNTRACKED" not in members


@pytest.mark.parametrize("renamed", ["g_kscEventNames", "KSC_EVENT_COUNT"])
def test_a_rename_reads_as_found_zero_not_as_a_pass(renamed):
    """Anchored, so a renamed table or sentinel refuses instead of vacuuming."""
    with pytest.raises(manifest_contract.ManifestContractError) as exc:
        _assert(PRODUCER_SNAPSHOT.replace(renamed, renamed + "2"))
    assert "found 0" in str(exc.value)


def test_two_tables_refuse_rather_than_pick_one():
    with pytest.raises(manifest_contract.ManifestContractError) as exc:
        _assert(PRODUCER_SNAPSHOT + PRODUCER_SNAPSHOT.replace('"move"', '"move2"'))
    assert "found 2" in str(exc.value)


# -- 2. the real registry and the snapshot agree today -----------------------

def test_todays_registry_covers_the_snapshot():
    _assert(PRODUCER_SNAPSHOT)


# -- 3. both directions, each named ------------------------------------------

def test_the_move_window_replayed():
    """The 2026-09-26..09-29 configuration: producer has `move`, registry does not.

    This is the outage, not a hypothetical: the producer snapshot is real and
    the registry is reduced to the set it held before `aa02a823`.
    """
    optional = tuple(t for t in CAPTURE_EVENT_TYPES_OPTIONAL if t != "move")
    assert len(optional) == len(CAPTURE_EVENT_TYPES_OPTIONAL) - 1
    with pytest.raises(manifest_contract.ManifestContractError) as exc:
        _assert(PRODUCER_SNAPSHOT, optional=optional)
    message = str(exc.value)
    assert "does not know: ['move']" in message
    assert "CAPTURE_EVENT_TYPES_OPTIONAL" in message


def test_a_dropped_required_stream_is_named():
    with pytest.raises(manifest_contract.ManifestContractError) as exc:
        _assert(PRODUCER_SNAPSHOT.replace('"damage", ', "")
                                 .replace("KSC_EVENT_DAMAGE,\n", ""))
    assert "no longer emits: ['damage']" in str(exc.value)


def test_an_optional_stream_with_no_producer_is_fine():
    """`aim_vis` is registered ahead of any build that emits it, on purpose."""
    assert "aim_vis" in CAPTURE_EVENT_TYPES_OPTIONAL
    assert "aim_vis" not in manifest_contract.producer_event_types(PRODUCER_SNAPSHOT)
    _assert(PRODUCER_SNAPSHOT)


def test_an_enum_member_with_no_name_is_named():
    """Pawn zero-fills the short tail, so the new type emits under an empty name."""
    widened = PRODUCER_SNAPSHOT.replace(
        "\tKSC_EVENT_COUNT", "\tKSC_EVENT_AIM_VIS,\n\tKSC_EVENT_COUNT")
    assert widened != PRODUCER_SNAPSHOT
    with pytest.raises(manifest_contract.ManifestContractError) as exc:
        _assert(widened)
    assert "name table" in str(exc.value)


# -- 4. collect() still calls it ---------------------------------------------

def test_collect_still_calls_the_check():
    """The leg both earlier class fixes lacked: nothing may quietly drop the call."""
    source = inspect.getsource(artifacts.ArtifactSet.collect)
    assert "assert_capture_event_types_registered(" in source
    assert "assert_capture_manifest_grammar(" in source


def test_the_collect_wrapper_raises_build_error(tmp_path):
    """A contract failure has to be fatal at collect time, never a degraded run."""
    inc = tmp_path / "ktp_stats_capture.inc"
    inc.write_text(PRODUCER_SNAPSHOT.replace('"move"', '"not_a_real_stream"'),
                   encoding="utf-8")
    with pytest.raises(artifacts.BuildError) as exc:
        artifacts.assert_capture_event_types_registered(inc)
    assert "not_a_real_stream" in str(exc.value)


def test_the_collect_wrapper_passes_the_real_shape(tmp_path):
    inc = tmp_path / "ktp_stats_capture.inc"
    inc.write_text(PRODUCER_SNAPSHOT, encoding="utf-8")
    artifacts.assert_capture_event_types_registered(inc)
