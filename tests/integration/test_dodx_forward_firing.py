"""DODX forward-firing tests — placeholder.

This file pins the intended test contract for the DODX forward-firing
test surface. Implementation is awaiting Phase 1 work spec'd in
`DODX_FORWARD_FIRING_DESIGN.md` (witness extension + hook for
`controlpoints_init` as the first forward).

Tests below are structurally complete but skip-marked with a reason that
points at the design doc. Once Phase 1 lands, remove the skip mark on
the corresponding test and the existing pytest run picks them up
automatically.

Why this scaffold lands now (separate from the implementation):

  1. Pins the fixture interface — future implementation work doesn't
     need to re-derive what shape the witness rows should take or what
     rcons drive the events.
  2. Documents the contract in version-controlled code, not just
     ephemeral session notes. A future contributor (or future Claude)
     can read this file and know exactly what's TBD.
  3. Forces the design doc + implementation to stay in sync — if
     `DODX_FORWARD_FIRING_DESIGN.md` adds a new phase, a corresponding
     test stub should land here in the same commit.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest


SKIP_REASON = (
    "DODX forward-firing tests are scaffolded but not yet executable. "
    "Phase 1 implementation (witness plugin extension to hook "
    "`controlpoints_init`) is documented in DODX_FORWARD_FIRING_DESIGN.md. "
    "Remove this skip mark once the witness extension lands + is staged "
    "to the test serverfiles tree."
)


def _serverfiles() -> Path | None:
    p = os.environ.get("KTP_HLDS_SERVERFILES")
    return Path(p).resolve() if p else None


# ---------------------------------------------------------------------------
# Phase 1 — controlpoints_init (deterministic, no client interaction)
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason=SKIP_REASON)
def test_controlpoints_init_fires_on_map_load(hlds):
    """`controlpoints_init` forward fires exactly once when hlds loads a
    DoD map. KTPWitness records the dispatch to witness.jsonl with a
    `{"forward": "dod_controlpoints_init", "ts_unix": ..., "args": {}}`
    row. We assert the row appears within 30s of the changelevel rcon.

    Why this forward first:
    - Fires deterministically on map load (no flake)
    - No client/player interaction required
    - Production-critical (KTPHLStatsX consumes it)
    - Args dict is empty — simplest assertion shape

    Witness extension required: hook `controlpoints_init` in KTPWitness.sma,
    write `{"forward": "dod_controlpoints_init", "ts_unix": <unix>, "args": {}}`
    to witness.jsonl. See DODX_FORWARD_FIRING_DESIGN.md § Phase 1.
    """
    from .log_tail import wait_for_witness_event, witness_count

    sf = _serverfiles()
    if sf is None:
        pytest.skip("test requires KTP_HLDS_SERVERFILES for witness.jsonl read")

    witness_baseline = witness_count(sf)
    hlds.rcon("changelevel dod_anzio")
    row = wait_for_witness_event(
        sf, "dod_controlpoints_init",
        timeout=30.0,
        after_count=witness_baseline,
    )
    assert "ts_unix" in row, f"witness row missing ts_unix: {row!r}"
    assert row.get("forward") == "dod_controlpoints_init"


# ---------------------------------------------------------------------------
# Phase 2 — player-interaction (bot-driven; deterministic-enough)
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason=SKIP_REASON + " (additionally needs bot driver — Phase 2)")
def test_dod_client_spawn_fires_on_bot_join(hlds):
    """`dod_client_spawn` fires when a bot spawns into the round. We
    assert via `addbot` rcon → wait for witness row.

    Witness arg shape: `{"id": <bot-edict>}`. Test asserts row appears
    within 10s + id is a positive integer matching a connected client
    slot.
    """
    from .log_tail import wait_for_witness_event, witness_count

    sf = _serverfiles()
    if sf is None:
        pytest.skip("test requires KTP_HLDS_SERVERFILES for witness.jsonl read")

    witness_baseline = witness_count(sf)
    hlds.rcon("addbot")
    row = wait_for_witness_event(
        sf, "dod_client_spawn",
        timeout=10.0,
        after_count=witness_baseline,
    )
    assert isinstance(row.get("args", {}).get("id"), int)
    assert row["args"]["id"] >= 1


# ---------------------------------------------------------------------------
# Phase 3 — hot-path forwards (rate-tested, structural assertions only)
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason=SKIP_REASON + " (needs rate-limit + bot grenade-throw — Phase 3)")
def test_dod_grenade_explosion_fires_with_full_args(hlds):
    """`dod_grenade_explosion(id, pos[3], wpnid)` fires when a grenade
    detonates. We assert structural shape only — bot grenade behavior
    is not deterministic enough for exact-value checks.

    Witness arg shape: `{"id": <int>, "pos": [<float>, <float>, <float>],
    "wpnid": <int>}`. Test waits up to 60s for ≥1 explosion event after
    spawning bots with grenades.
    """
    pytest.fail("Phase 3 not yet implemented — see DODX_FORWARD_FIRING_DESIGN.md")


# ---------------------------------------------------------------------------
# Phase 4 — match-flow-coupled (rcon-driven via test-mode KTPMatchHandler)
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason=SKIP_REASON + " (needs hookchain into match-flow rcons — Phase 4)")
def test_dod_stats_flush_fires_on_match_end(hlds):
    """`dod_stats_flush` should fire as part of the match-end sequence
    (KTPMatchHandler calls `dodx_flush_all_stats()` per CLAUDE.md
    'Match Flow' section). We drive the state machine via test-mode
    rcons + assert the witness row appears.

    Witness arg shape: `{"id": <int>}` — fires once per connected client.
    Test asserts ≥1 row appears within 5s of `amx_ktp_test_end_match`.
    """
    pytest.fail("Phase 4 not yet implemented — see DODX_FORWARD_FIRING_DESIGN.md")
