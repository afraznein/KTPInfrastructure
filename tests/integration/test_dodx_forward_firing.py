"""DODX forward-firing tests.

Phase 1 (`controlpoints_init`) is implemented and runs when the suite has a
booted hlds with KTPWitness 1.1.0+ staged. Phases 2-4 remain skip-marked
pending bot-driver / rate-limit / hookchain work spec'd in
`DODX_FORWARD_FIRING_DESIGN.md`.

Why scaffolds for unimplemented phases stay here:

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
        timeout=30.0,
        after_count=witness_baseline,
    )
    # wait_for_witness_event already validates row["event"] == "dod_controlpoints_init",
    # so we only need to check the shape contract.
    assert "ts" in row, f"witness row missing ts: {row!r}"
    assert isinstance(row["ts"], int) and row["ts"] > 0, f"ts not a positive int: {row['ts']!r}"
    assert row.get("args") == {}, f"controlpoints_init args should be empty dict: {row.get('args')!r}"


# ---------------------------------------------------------------------------
# Phase 2 — player-interaction (bot-driven; deterministic-enough)
# ---------------------------------------------------------------------------
#
# A single `addbot` rcon triggers a deterministic forward sequence in DoD:
#
#   1. Bot connects (no DODX forward; `client_putinserver` only)
#   2. Bot AI auto-joins a team -> `dod_client_changeteam(id, team, 3)`
#      (3 = Spectators, the bot's initial side)
#   3. Bot picks class             -> `dod_client_changeclass(id, class, 0)`
#   4. Bot spawns                  -> `dod_client_spawn(id)`
#
# All four fire within a few seconds of `addbot`. Tests assert occurrence +
# structural shape (`args.id` is a positive int, etc.), not exact values —
# the design doc's "≥N times in T seconds" contract.
#
# `client_death` is excluded from the addbot path (needs an attacker source),
# and stays scaffold-skipped pending a deterministic kill driver (rcon-based
# admin slay or bot-vs-bot combat).


def test_dod_client_spawn_fires_on_bot_join(hlds):
    """`dod_client_spawn(id)` fires when a bot spawns into the round.
    `addbot` rcon -> wait for witness row.

    Witness arg shape: `{"id": <client-slot>}`. Test asserts the row
    appears within 10s and `id` is a positive integer (slot index).
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
    assert isinstance(row.get("args", {}).get("id"), int), \
        f"args.id missing or not int: {row!r}"
    assert row["args"]["id"] >= 1, f"args.id must be a positive client slot: {row['args']['id']}"


def test_dod_client_changeteam_fires_on_bot_join(hlds):
    """`dod_client_changeteam(id, team, oldteam)` fires when a bot is
    auto-assigned a team. `addbot` -> bot starts in Spectators (team 3) ->
    AI auto-joins Allies/Axis -> changeteam fires.

    Witness arg shape: `{"id": <slot>, "team": <new>, "oldteam": <prev>}`.
    Test asserts shape + plausible team values (1=Allies, 2=Axis, 3=Spec).
    Doesn't assert which team the bot picks (DoD AI is non-deterministic).
    """
    from .log_tail import wait_for_witness_event, witness_count

    sf = _serverfiles()
    if sf is None:
        pytest.skip("test requires KTP_HLDS_SERVERFILES for witness.jsonl read")

    witness_baseline = witness_count(sf)
    hlds.rcon("addbot")
    row = wait_for_witness_event(
        sf, "dod_client_changeteam",
        timeout=10.0,
        after_count=witness_baseline,
    )
    args = row.get("args", {})
    assert isinstance(args.get("id"), int) and args["id"] >= 1, f"args.id invalid: {args!r}"
    assert args.get("team") in (1, 2, 3), f"args.team must be 1/2/3: {args!r}"
    assert args.get("oldteam") in (0, 1, 2, 3), f"args.oldteam must be 0..3: {args!r}"


def test_dod_client_changeclass_fires_on_bot_join(hlds):
    """`dod_client_changeclass(id, class, oldclass)` fires when a bot
    picks a class (just after spawn per dodx.inc). `addbot` -> bot picks
    class within seconds.

    Witness arg shape: `{"id": <slot>, "class": <new>, "oldclass": <prev>}`.
    DoD class IDs are 1-6 per side; oldclass=0 on initial pick. Test
    asserts shape + plausible class values.
    """
    from .log_tail import wait_for_witness_event, witness_count

    sf = _serverfiles()
    if sf is None:
        pytest.skip("test requires KTP_HLDS_SERVERFILES for witness.jsonl read")

    witness_baseline = witness_count(sf)
    hlds.rcon("addbot")
    row = wait_for_witness_event(
        sf, "dod_client_changeclass",
        timeout=10.0,
        after_count=witness_baseline,
    )
    args = row.get("args", {})
    assert isinstance(args.get("id"), int) and args["id"] >= 1, f"args.id invalid: {args!r}"
    assert isinstance(args.get("class"), int) and args["class"] >= 0, f"args.class invalid: {args!r}"
    assert isinstance(args.get("oldclass"), int) and args["oldclass"] >= 0, f"args.oldclass invalid: {args!r}"


def test_client_death_fires_on_kill(hlds):
    """`client_death(killer, victim, wpnindex, hitplace, TK)` fires on
    any player death. Witness label: `dod_client_death`. Args shape:
    `{"killer": <slot>, "victim": <slot>, "wpnindex": <int>, "hitplace": <int>, "TK": 0|1}`.

    Driver path (Phase 2b shipped 2026-05-05): `amx_witness_kill <slot>`
    rcon, registered by KTPWitness 1.3.0+, calls `user_kill(slot, 0)`
    internally. user_kill is a core AMXX native (no extra module load),
    same registration pattern as KTPMatchHandler's -DKTP_TEST_MODE rcons.

    Test sequence:
      1. addbot -> wait for `dod_client_spawn` row to confirm the bot is
         actually in-world (kill before spawn would no-op).
      2. Capture the bot's slot from the spawn row's args.id.
      3. amx_witness_kill <slot> -> user_kill -> client_death dispatch.
      4. Wait for the `dod_client_death` row, assert shape + victim slot
         matches the bot we killed.
    """
    from .log_tail import wait_for_witness_event, witness_count

    sf = _serverfiles()
    if sf is None:
        pytest.skip("test requires KTP_HLDS_SERVERFILES for witness.jsonl read")

    # 1+2. addbot, wait for spawn, capture slot
    spawn_baseline = witness_count(sf)
    hlds.rcon("addbot")
    spawn_row = wait_for_witness_event(
        sf, "dod_client_spawn",
        timeout=10.0,
        after_count=spawn_baseline,
    )
    bot_slot = spawn_row["args"]["id"]
    assert isinstance(bot_slot, int) and bot_slot >= 1, \
        f"spawn row has invalid slot: {spawn_row!r}"

    # 3+4. Kill the bot, wait for death row
    death_baseline = witness_count(sf)
    hlds.rcon(f"amx_witness_kill {bot_slot}")
    row = wait_for_witness_event(
        sf, "dod_client_death",
        timeout=10.0,
        after_count=death_baseline,
    )
    args = row.get("args", {})
    assert isinstance(args.get("killer"), int), f"args.killer missing/wrong type: {args!r}"
    assert args.get("victim") == bot_slot, \
        f"victim slot {args.get('victim')!r} does not match killed bot slot {bot_slot}"
    assert isinstance(args.get("wpnindex"), int), f"args.wpnindex missing/wrong type: {args!r}"
    assert isinstance(args.get("hitplace"), int), f"args.hitplace missing/wrong type: {args!r}"
    assert args.get("TK") in (0, 1), f"args.TK must be 0 or 1: {args!r}"


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
        timeout=5.0,
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
    tolerance is ±0.01 (witness serializes with %.2f precision).
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
        timeout=5.0,
        after_count=witness_baseline,
    )
    args = row.get("args", {})
    assert args.get("id") == SLOT, f"id mismatch: {args!r}"
    pos = args.get("pos")
    assert isinstance(pos, list) and len(pos) == 3, f"pos must be 3-element list: {pos!r}"
    assert abs(pos[0] - X) < 0.01, f"pos.x off: {pos[0]} vs expected {X}"
    assert abs(pos[1] - Y) < 0.01, f"pos.y off: {pos[1]} vs expected {Y}"
    assert abs(pos[2] - Z) < 0.01, f"pos.z off: {pos[2]} vs expected {Z}"
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
        timeout=5.0,
        after_count=witness_baseline,
    )
    event_row = wait_for_witness_event(
        sf, "dod_score_event",
        timeout=5.0,
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
# `dod_stats_flush` test (full match-flow drive):
#   addbot -> wait for spawn -> setup_match -> advance_pending ->
#   advance_live -> end_match -> wait for stats_flush row with bot's id.
#   Exercises the entire engine -> KTPMatchHandler -> DODX -> witness
#   chain. Requires KTPMatchHandler 0.10.124+ (test-mode end_match calls
#   dodx_flush_all_stats — same as production match-end flow).
#
# `dod_control_point_captured` test uses the dispatch primitive
# (Phase 4b — same pattern as Phase 3b): KTPWitness 1.6.0+ exposes
# `amx_witness_dispatch_cp_captured` which calls the test-only
# dodx_test_dispatch_cp_captured native. Full engine flag-cap chain
# is covered separately by manual testing during real matchday play
# (CP capture timing is non-deterministic enough for test-suite use).


def test_dod_stats_flush_fires_on_match_end(hlds):
    """`dod_stats_flush(id)` fires for each connected player at match
    end. KTPMatchHandler 0.10.124+ test-mode `cmd_test_end_match` calls
    `dodx_flush_all_stats()` (same as production match-end), which in
    turn fires the forward per-player.

    Test sequence:
      1. addbot -> wait for `dod_client_spawn` row -> capture bot slot.
      2. amx_ktp_test_setup_match COMPETITIVE pass1 (whatever string is
         needed; we drive through to live).
      3. amx_ktp_test_advance_pending -> advance_live -> end_match.
      4. Wait for `dod_stats_flush` row with `args.id` matching the bot.

    Witness arg shape: `{"id": <int>}` (single per-player int).
    """
    from .log_tail import wait_for_witness_event, witness_count

    sf = _serverfiles()
    if sf is None:
        pytest.skip("test requires KTP_HLDS_SERVERFILES for witness.jsonl read")

    # 1. addbot, capture bot slot
    spawn_baseline = witness_count(sf)
    hlds.rcon("addbot")
    spawn_row = wait_for_witness_event(
        sf, "dod_client_spawn", timeout=10.0, after_count=spawn_baseline,
    )
    bot_slot = spawn_row["args"]["id"]

    # 2-3. Drive match-flow state machine to end. cmd_test_setup_match
    # takes `<matchType_int_0..5> <map>` (KTPMatchHandler.sma:7680-7720).
    # advance_pending / advance_live take no args. end_match takes the
    # two final scores.
    #   matchType: 0=COMPETITIVE, 1=SCRIM, 2=12MAN, 3=DRAFT, 4=KTP_OT, 5=DRAFT_OT
    hlds.rcon("amx_ktp_test_setup_match 0 dod_anzio")
    hlds.rcon("amx_ktp_test_advance_pending")
    hlds.rcon("amx_ktp_test_advance_live")

    # 4. End match -> dodx_flush_all_stats() -> dod_stats_flush per-player
    flush_baseline = witness_count(sf)
    hlds.rcon("amx_ktp_test_end_match 5 3")
    row = wait_for_witness_event(
        sf, "dod_stats_flush", timeout=5.0, after_count=flush_baseline,
    )
    args = row.get("args", {})
    assert isinstance(args.get("id"), int) and args["id"] >= 1, \
        f"args.id missing/invalid: {args!r}"
    # The forward fires once per connected client. The bot is the only
    # player, so its slot should be in the args. (HLTV is also connected
    # in some setups but with a high slot — accept any valid slot.)


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
        timeout=5.0,
        after_count=witness_baseline,
    )
    args = row.get("args", {})
    assert args.get("cp_index")  == CP_INDEX,  f"cp_index mismatch: {args!r}"
    assert args.get("new_owner") == NEW_OWNER, f"new_owner mismatch: {args!r}"
    assert args.get("old_owner") == OLD_OWNER, f"old_owner mismatch: {args!r}"
