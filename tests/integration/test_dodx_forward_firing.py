"""DODX forward-firing tests.

All phases are now executable — no skip-marked scaffolds remain:

  Phase 1  — `controlpoints_init`, engine-driven on map load.
  Phase 2c — the five formerly bot-gated forwards (spawn / changeteam /
             changeclass / client_death / stats_flush), dispatch-driven
             since 2026-07-04 (KTPAMXX 127f39fc + KTPWitness 1.7.0), plus
             the 2.7.18 `dod_client_weapon_fire` per-shot forward.
  Phase 3  — hot-path forwards via dodx_test_dispatch_* (2026-05-05).
  Phase 4  — dod_control_point_captured via dispatch (2026-05-05).

Environment: needs dodx_ktp_i386.so from the KTPAMXX 2.7.19+ tree and
KTPWitness 1.7.0+ staged (see CI_RUNNER_SETUP.md).
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from ._timing import WITNESS_TIMEOUT, scaled


def _serverfiles() -> Path | None:
    p = os.environ.get("KTP_HLDS_SERVERFILES")
    return Path(p).resolve() if p else None


# ---------------------------------------------------------------------------
# Phase 1 — controlpoints_init (deterministic, no client interaction)
# ---------------------------------------------------------------------------

def test_controlpoints_init_fires_on_map_load(hlds):
    """`controlpoints_init` forward fires when hlds loads a DoD map.
    KTPWitness 1.1.0+ records the dispatch to witness.jsonl with a
    `{"event": "dod_controlpoints_init", "ts": ..., "args": {}}` row.
    We baseline the row count, issue `changelevel dod_anzio`, and assert
    a fresh dispatch row appears within 30s.

    Why this forward first:
    - Fires deterministically on map load (no flake)
    - No client/player interaction required
    - Production-critical (KTPHLStatsX consumes it; a regression here
      silently breaks per-cap stats — see memory entry
      `ktpamxx_2.7.13_dodx_fix_2026-04-23.md` for prior incident)
    - Args dict is empty — simplest assertion shape

    Field shape note: existing match-flow witness rows use `event`/`ts`
    keys; this row uses the same conventions plus a nested `args: {}` for
    forward arguments (empty here; populated by Phase 2+ hooks). The
    `wait_for_witness_event` filter is on the `event` field so the
    nested `args` shape doesn't affect lookup.
    """
    from .log_tail import wait_for_witness_event, witness_count

    sf = _serverfiles()
    if sf is None:
        pytest.skip("test requires KTP_HLDS_SERVERFILES for witness.jsonl read")

    witness_baseline = witness_count(sf)
    hlds.rcon("changelevel dod_anzio")
    row = wait_for_witness_event(
        sf, "dod_controlpoints_init",
        timeout=scaled(30.0),
        after_count=witness_baseline,
    )
    # wait_for_witness_event already validates row["event"] == "dod_controlpoints_init",
    # so we only need to check the shape contract.
    assert "ts" in row, f"witness row missing ts: {row!r}"
    assert isinstance(row["ts"], int) and row["ts"] > 0, f"ts not a positive int: {row['ts']!r}"
    assert row.get("args") == {}, f"controlpoints_init args should be empty dict: {row.get('args')!r}"


# ---------------------------------------------------------------------------
# Phase 2c — formerly bot-gated forwards, now dispatch-driven
# ---------------------------------------------------------------------------
#
# These five forwards (`dod_client_spawn`, `dod_client_changeteam`,
# `dod_client_changeclass`, `client_death`, `dod_stats_flush`) were
# skip-marked from 2026-05-06 to 2026-07-04 because their only driver was a
# real player chain: `addbot` creates a fake-client slot but DoD ships no
# bot AI, so the client never joins/spawns/dies. The bot-mod path was
# empirically closed 2026-05-24 — Marine Bot's gamedll-wrapper breaks
# DODX's g_pGameRules symbol scan (see TODO.md "bot AI mod install").
#
# KTPAMXX 2.7.19+ (commit 127f39fc) added dodx_test_dispatch_* natives for
# all five, and KTPWitness 1.7.0 wraps them in amx_witness_dispatch_* rcons
# — the same Phase 3b pattern the hot-path tests below already use. Same
# honest caveat as Phase 3b: this exercises DODX's forward-dispatch
# primitive and the consumer contract, NOT the natural engine→DODX event
# chain (which has no test driver without bots).
#
# Deterministic dispatch means exact round-trip assertions (vs the old
# scaffolds' "plausible shape" checks).


def test_dod_client_spawn_via_dispatch(hlds):
    """`dod_client_spawn(id)` round-trips through dispatch → witness.

    Driver: `amx_witness_dispatch_client_spawn <id>` rcon ->
    `dodx_test_dispatch_client_spawn` native -> MF_ExecuteForward ->
    witness public dod_client_spawn handler -> JSONL row.
    """
    from .log_tail import wait_for_witness_event, witness_count

    sf = _serverfiles()
    if sf is None:
        pytest.skip("test requires KTP_HLDS_SERVERFILES for witness.jsonl read")

    SLOT = 5

    witness_baseline = witness_count(sf)
    hlds.rcon(f"amx_witness_dispatch_client_spawn {SLOT}")
    row = wait_for_witness_event(
        sf, "dod_client_spawn",
        timeout=WITNESS_TIMEOUT,
        after_count=witness_baseline,
    )
    assert row.get("args", {}).get("id") == SLOT, f"id mismatch: {row!r}"


def test_dod_client_changeteam_via_dispatch(hlds):
    """`dod_client_changeteam(id, team, oldteam)` round-trips through
    dispatch → witness. Values mirror the initial spectator->Allies
    transition a real join produces (team=1, oldteam=3).
    """
    from .log_tail import wait_for_witness_event, witness_count

    sf = _serverfiles()
    if sf is None:
        pytest.skip("test requires KTP_HLDS_SERVERFILES for witness.jsonl read")

    SLOT, TEAM, OLDTEAM = 5, 1, 3

    witness_baseline = witness_count(sf)
    hlds.rcon(f"amx_witness_dispatch_changeteam {SLOT} {TEAM} {OLDTEAM}")
    row = wait_for_witness_event(
        sf, "dod_client_changeteam",
        timeout=WITNESS_TIMEOUT,
        after_count=witness_baseline,
    )
    args = row.get("args", {})
    assert args.get("id")      == SLOT,    f"id mismatch: {args!r}"
    assert args.get("team")    == TEAM,    f"team mismatch: {args!r}"
    assert args.get("oldteam") == OLDTEAM, f"oldteam mismatch: {args!r}"


def test_dod_client_changeclass_via_dispatch(hlds):
    """`dod_client_changeclass(id, class, oldclass)` round-trips through
    dispatch → witness. Values mirror an initial class pick (oldclass=0).
    """
    from .log_tail import wait_for_witness_event, witness_count

    sf = _serverfiles()
    if sf is None:
        pytest.skip("test requires KTP_HLDS_SERVERFILES for witness.jsonl read")

    SLOT, NEWCLASS, OLDCLASS = 5, 4, 0

    witness_baseline = witness_count(sf)
    hlds.rcon(f"amx_witness_dispatch_changeclass {SLOT} {NEWCLASS} {OLDCLASS}")
    row = wait_for_witness_event(
        sf, "dod_client_changeclass",
        timeout=WITNESS_TIMEOUT,
        after_count=witness_baseline,
    )
    args = row.get("args", {})
    assert args.get("id")       == SLOT,     f"id mismatch: {args!r}"
    assert args.get("class")    == NEWCLASS, f"class mismatch: {args!r}"
    assert args.get("oldclass") == OLDCLASS, f"oldclass mismatch: {args!r}"


def test_client_death_via_dispatch(hlds):
    """`client_death(killer, victim, wpnindex, hitplace, TK)` round-trips
    through dispatch → witness (label `dod_client_death`). Killer-first
    arg order matches the production dispatch sites (NBase.cpp:561,
    usermsg.cpp:761).
    """
    from .log_tail import wait_for_witness_event, witness_count

    sf = _serverfiles()
    if sf is None:
        pytest.skip("test requires KTP_HLDS_SERVERFILES for witness.jsonl read")

    KILLER, VICTIM, WPNIDX, HITPLACE, TK = 7, 8, 13, 2, 0

    witness_baseline = witness_count(sf)
    hlds.rcon(f"amx_witness_dispatch_client_death {KILLER} {VICTIM} {WPNIDX} {HITPLACE} {TK}")
    row = wait_for_witness_event(
        sf, "dod_client_death",
        timeout=WITNESS_TIMEOUT,
        after_count=witness_baseline,
    )
    args = row.get("args", {})
    assert args.get("killer")   == KILLER,   f"killer mismatch: {args!r}"
    assert args.get("victim")   == VICTIM,   f"victim mismatch: {args!r}"
    assert args.get("wpnindex") == WPNIDX,   f"wpnindex mismatch: {args!r}"
    assert args.get("hitplace") == HITPLACE, f"hitplace mismatch: {args!r}"
    assert args.get("TK")       == TK,       f"TK mismatch: {args!r}"


# ---------------------------------------------------------------------------
# Phase 3 — hot-path forwards (driven by dodx_test_dispatch_* primitives)
# ---------------------------------------------------------------------------
#
# Hot-path forwards (`client_damage`, `dod_grenade_explosion`, `client_score`,
# `dod_score_event`) fire at cadences where bot-vs-bot combat is too
# unreliable for test-suite timing. Phase 3b (shipped 2026-05-05) added
# three deterministic-dispatch natives to the DODX module:
#
#   dodx_test_dispatch_damage(attacker, victim, damage, wpnindex, hitplace, TA)
#   dodx_test_dispatch_grenade_explosion(id, Float:pos[3], wpnid)
#   dodx_test_dispatch_score(id, score_delta, total, cp_index)
#       -> fires BOTH client_score AND dod_score_event (matches production
#          dispatch pattern in moduleconfig.cpp:276-278).
#
# Each native calls MF_ExecuteForward directly — bypassing the engine event
# chain but exercising the same forward-dispatch primitive DODX uses for
# real engine events. The natives are TEST-ONLY (production plugins MUST
# NOT call them); KTPWitness 1.5.0+ wraps each in an rcon
# (`amx_witness_dispatch_damage`, `amx_witness_dispatch_grenade`,
# `amx_witness_dispatch_score`) so tests drive them via the standard
# rcon path.
#
# Test environment requires:
#   - KTPWitness 1.5.0+ (#include <dodx>, three new rcon handlers)
#   - dodx_ktp_i386.so with the new natives (built from KTPAMXX as part
#     of Phase 3b)
#
# Coverage these tests provide:
#   - Forward dispatch primitive itself works (catches "DODX ExecuteForward
#     stalled" regressions like the KTPAMXX 2.7.13 silent-stall, on the
#     forward-side; engine-side coverage is provided by Phase 1
#     controlpoints_init + Phase 4 stats_flush).
#   - Witness handler shape matches the forward signature.
#   - JSONL output is well-formed.


def test_client_damage_fires_with_full_args(hlds):
    """`client_damage(attacker, victim, damage, wpnindex, hitplace, TA)`
    fires after every player-to-player attack. Witness label
    `dod_client_damage`.

    Driver: `amx_witness_dispatch_damage <attacker> <victim> <damage>
    <wpnindex> <hitplace> <TA>` rcon -> `dodx_test_dispatch_damage` native
    -> `MF_ExecuteForward(iFDamage, ...)` -> witness public client_damage
    handler -> JSONL row.

    Test asserts the row appears within 5s and the round-tripped args
    match exactly (deterministic dispatch, so we can check exact values).
    """
    from .log_tail import wait_for_witness_event, witness_count

    sf = _serverfiles()
    if sf is None:
        pytest.skip("test requires KTP_HLDS_SERVERFILES for witness.jsonl read")

    # Sentinel values chosen to be obviously synthetic — any production
    # code path firing a real client_damage would not produce this exact
    # tuple, so we can sanity-check that the row we're reading is ours.
    ATTACKER, VICTIM, DAMAGE, WPNIDX, HITPLACE, TA = 7, 8, 42, 13, 5, 1

    witness_baseline = witness_count(sf)
    hlds.rcon(f"amx_witness_dispatch_damage {ATTACKER} {VICTIM} {DAMAGE} {WPNIDX} {HITPLACE} {TA}")
    row = wait_for_witness_event(
        sf, "dod_client_damage",
        timeout=WITNESS_TIMEOUT,
        after_count=witness_baseline,
    )
    args = row.get("args", {})
    assert args.get("attacker") == ATTACKER, f"attacker mismatch: {args!r}"
    assert args.get("victim")   == VICTIM,   f"victim mismatch: {args!r}"
    assert args.get("damage")   == DAMAGE,   f"damage mismatch: {args!r}"
    assert args.get("wpnindex") == WPNIDX,   f"wpnindex mismatch: {args!r}"
    assert args.get("hitplace") == HITPLACE, f"hitplace mismatch: {args!r}"
    assert args.get("TA")       == TA,       f"TA mismatch: {args!r}"


def test_dod_grenade_explosion_fires_with_full_args(hlds):
    """`dod_grenade_explosion(id, Float:pos[3], wpnid)` fires when a grenade
    detonates. Witness arg shape:
    `{"id": <int>, "pos": [<float>, <float>, <float>], "wpnid": <int>}`.

    Driver: `amx_witness_dispatch_grenade <slot> <x> <y> <z> <wpnid>` rcon
    -> `dodx_test_dispatch_grenade_explosion` native. pos round-trip
    tolerance is one %.2f grid step plus slack: AMXX's float formatter
    truncates rather than rounds, and the parsed float can land an ulp
    below the literal (build-env-dependent — surfaced 2026-07-04 when the
    2.7.19 core rebuild serialized 88.00 as "87.99"), so a full hundredth
    of error is legitimate.
    """
    from .log_tail import wait_for_witness_event, witness_count

    sf = _serverfiles()
    if sf is None:
        pytest.skip("test requires KTP_HLDS_SERVERFILES for witness.jsonl read")

    SLOT = 3
    X, Y, Z = 1234.50, -567.25, 88.00
    WPNID = 13  # DODW_HANDGRENADE

    witness_baseline = witness_count(sf)
    hlds.rcon(f"amx_witness_dispatch_grenade {SLOT} {X} {Y} {Z} {WPNID}")
    row = wait_for_witness_event(
        sf, "dod_grenade_explosion",
        timeout=WITNESS_TIMEOUT,
        after_count=witness_baseline,
    )
    args = row.get("args", {})
    assert args.get("id") == SLOT, f"id mismatch: {args!r}"
    pos = args.get("pos")
    assert isinstance(pos, list) and len(pos) == 3, f"pos must be 3-element list: {pos!r}"
    assert abs(pos[0] - X) < 0.011, f"pos.x off: {pos[0]} vs expected {X}"
    assert abs(pos[1] - Y) < 0.011, f"pos.y off: {pos[1]} vs expected {Y}"
    assert abs(pos[2] - Z) < 0.011, f"pos.z off: {pos[2]} vs expected {Z}"
    assert args.get("wpnid") == WPNID, f"wpnid mismatch: {args!r}"


def test_dispatch_score_fires_both_client_score_and_dod_score_event(hlds):
    """A single `dodx_test_dispatch_score` call fires BOTH the
    `client_score` (3 args: id, score, total) AND `dod_score_event`
    (4 args: id, score_delta, total, cp_index) forwards — matching
    DODX's production tandem-dispatch pattern.

    The witness records two rows from one rcon call, with labels
    `dod_client_score` and `dod_score_event`. Test asserts both appear,
    have matching id/total, and `dod_score_event` has the expected
    cp_index (which `client_score` doesn't carry).
    """
    from .log_tail import wait_for_witness_event, witness_count

    sf = _serverfiles()
    if sf is None:
        pytest.skip("test requires KTP_HLDS_SERVERFILES for witness.jsonl read")

    ID, DELTA, TOTAL, CP_IDX = 4, 1, 42, 2

    witness_baseline = witness_count(sf)
    hlds.rcon(f"amx_witness_dispatch_score {ID} {DELTA} {TOTAL} {CP_IDX}")

    # Both forwards fire from the same rcon — wait for each. They land in
    # write-order from the witness (client_score first, then dod_score_event)
    # but we filter by event label so order doesn't matter for the assertion.
    score_row = wait_for_witness_event(
        sf, "dod_client_score",
        timeout=WITNESS_TIMEOUT,
        after_count=witness_baseline,
    )
    event_row = wait_for_witness_event(
        sf, "dod_score_event",
        timeout=WITNESS_TIMEOUT,
        after_count=witness_baseline,
    )

    score_args = score_row.get("args", {})
    assert score_args.get("id")    == ID,    f"client_score id: {score_args!r}"
    assert score_args.get("score") == DELTA, f"client_score score (delta): {score_args!r}"
    assert score_args.get("total") == TOTAL, f"client_score total: {score_args!r}"

    event_args = event_row.get("args", {})
    assert event_args.get("id")          == ID,     f"score_event id: {event_args!r}"
    assert event_args.get("score_delta") == DELTA,  f"score_event delta: {event_args!r}"
    assert event_args.get("total_score") == TOTAL,  f"score_event total: {event_args!r}"
    assert event_args.get("cp_index")    == CP_IDX, f"score_event cp_index: {event_args!r}"


# ---------------------------------------------------------------------------
# Phase 4 — match-flow-coupled (rcon-driven via test-mode KTPMatchHandler)
# ---------------------------------------------------------------------------
#
# Phase 4 covers two forwards: `dod_stats_flush(id)` (engine-driven via
# KTPMatchHandler's match-end calling `dodx_flush_all_stats()`) and
# `dod_control_point_captured(cp_index, new_owner, old_owner)`
# (engine-driven via DoD's flag-cap usermsg path).
#
# `dod_stats_flush` moved to the Phase 2c dispatch driver above (2026-07-04)
# — the full match-flow variant (end_match -> dodx_flush_all_stats -> per-
# connected-player fan-out) needs a connected client and stays untestable
# without bots; see the coverage note on test_dod_stats_flush_via_dispatch.
#
# `dod_control_point_captured` test uses the dispatch primitive
# (Phase 4b — same pattern as Phase 3b): KTPWitness 1.6.0+ exposes
# `amx_witness_dispatch_cp_captured` which calls the test-only
# dodx_test_dispatch_cp_captured native. Full engine flag-cap chain
# is covered separately by manual testing during real matchday play
# (CP capture timing is non-deterministic enough for test-suite use).


def test_dod_stats_flush_via_dispatch(hlds):
    """`dod_stats_flush(id)` round-trips through dispatch → witness.

    Coverage note: production fires this via `dodx_flush_all_stats()`
    looping every CONNECTED player at match end — with zero players that
    loop fires zero forwards, so the full match-end chain stays untestable
    without a connected client. The per-player dispatch native covers the
    forward-delivery contract (dispatch → subscribed plugins) that the
    match-end variant would have exercised; the flush-all loop itself is
    plain NRank.cpp iteration.
    """
    from .log_tail import wait_for_witness_event, witness_count

    sf = _serverfiles()
    if sf is None:
        pytest.skip("test requires KTP_HLDS_SERVERFILES for witness.jsonl read")

    SLOT = 6

    witness_baseline = witness_count(sf)
    hlds.rcon(f"amx_witness_dispatch_stats_flush {SLOT}")
    row = wait_for_witness_event(
        sf, "dod_stats_flush", timeout=WITNESS_TIMEOUT, after_count=witness_baseline,
    )
    assert row.get("args", {}).get("id") == SLOT, f"id mismatch: {row!r}"


def test_dod_client_weapon_fire_via_dispatch(hlds):
    """`dod_client_weapon_fire(id, weapon, Float:gametime)` — the KTPAMXX
    2.7.18 per-shot forward (dormant in production until the Season-10
    Rule 4.6 cadence consumer) round-trips through dispatch → witness.

    gametime is a Pawn Float cell passed through unchanged by the native
    (pre-encoded IEEE 754 — see the native's comment); witness serializes
    %.2f, so assert with ±0.01 tolerance like the grenade pos check.
    """
    from .log_tail import wait_for_witness_event, witness_count

    sf = _serverfiles()
    if sf is None:
        pytest.skip("test requires KTP_HLDS_SERVERFILES for witness.jsonl read")

    SLOT, WEAPON, GAMETIME = 4, 7, 123.25  # 7 = a rifle-class weapon id

    witness_baseline = witness_count(sf)
    hlds.rcon(f"amx_witness_dispatch_weapon_fire {SLOT} {WEAPON} {GAMETIME}")
    row = wait_for_witness_event(
        sf, "dod_client_weapon_fire",
        timeout=WITNESS_TIMEOUT,
        after_count=witness_baseline,
    )
    args = row.get("args", {})
    assert args.get("id")     == SLOT,   f"id mismatch: {args!r}"
    assert args.get("weapon") == WEAPON, f"weapon mismatch: {args!r}"
    assert isinstance(args.get("gametime"), (int, float)) and \
        abs(args["gametime"] - GAMETIME) < 0.011, f"gametime off: {args!r}"


def test_dod_control_point_captured_via_dispatch(hlds):
    """`dod_control_point_captured(cp_index, new_owner, old_owner)`
    fires when a flag/CP changes ownership. Production engine path is
    DoD usermsg-driven; for test-suite timing we use the Phase 3b/4b
    pattern: `amx_witness_dispatch_cp_captured` rcon -> witness's
    dodx_test_dispatch_cp_captured native -> MF_ExecuteForward.

    Witness arg shape: `{"cp_index": <int>, "new_owner": 0|1|2,
    "old_owner": 0|1|2}`. Owner values: 0=neutral, 1=allies, 2=axis.

    Test passes specific values and asserts exact round-trip.
    """
    from .log_tail import wait_for_witness_event, witness_count

    sf = _serverfiles()
    if sf is None:
        pytest.skip("test requires KTP_HLDS_SERVERFILES for witness.jsonl read")

    CP_INDEX, NEW_OWNER, OLD_OWNER = 2, 1, 0  # neutral CP captured by Allies

    witness_baseline = witness_count(sf)
    hlds.rcon(f"amx_witness_dispatch_cp_captured {CP_INDEX} {NEW_OWNER} {OLD_OWNER}")
    row = wait_for_witness_event(
        sf, "dod_control_point_captured",
        timeout=WITNESS_TIMEOUT,
        after_count=witness_baseline,
    )
    args = row.get("args", {})
    assert args.get("cp_index")  == CP_INDEX,  f"cp_index mismatch: {args!r}"
    assert args.get("new_owner") == NEW_OWNER, f"new_owner mismatch: {args!r}"
    assert args.get("old_owner") == OLD_OWNER, f"old_owner mismatch: {args!r}"
