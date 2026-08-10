"""Database assertions for Lane B — what the daemon actually wrote.

## Posture: existence and plausibility, not exact counts

Bot AI decides how many kills happen. A test that asserts "7 assists" fails
when new_bot's pathing changes and passes when the pipeline is broken but
lucky. What Lane B is qualified to prove is that events *emitted by the game*
*arrive in the database with the right shape*, so that is what these assert.

Two things are nevertheless exact, because they are invariants rather than
outcomes:

- **`assist` writes to PlayerPlayerActions and NOT to PlayerActions.** The
  dispatcher calls both handlers for one log line, each gated on its own flag.
  Both flags set means every assist is recorded twice and its reward applied
  twice — a silent rating corruption with no error anywhere. `cap_break` is the
  mirror image.
- **Positions are not all-zero.** `ksc_origin_str` omits the property when the
  origin read fails, specifically so a failure surfaces as NULL rather than as
  a plausible-looking map origin. A table full of `0 0 0` means that guard was
  bypassed.

## Why `AssertionError` with long messages

These run in CI at 06:00 with nobody watching. The message has to carry enough
to diagnose from the log alone, because the ephemeral database is gone by the
time anyone reads it.
"""

from __future__ import annotations

from dataclasses import dataclass

# `hlstats_Events_PlayerPlayerActions` and `_PlayerActions` both carry pos_x/y/z
# on a KTP schema; upstream HLStatsX has them only on some tables. Lane B runs
# against a production-derived schema, so they are present.
_PPA = "hlstats_Events_PlayerPlayerActions"
_PA = "hlstats_Events_PlayerActions"


@dataclass(frozen=True)
class ActionRows:
    """What landed for one action code, across both event tables."""

    code: str
    ppa: int
    pa: int

    @property
    def total(self) -> int:
        return self.ppa + self.pa


def count_action(db, code: str, *, game: str = "dod") -> ActionRows:
    """Rows recorded for `code`, joined through `hlstats_Actions`.

    Joins rather than filtering on a hardcoded id: the seed migrations
    deliberately let AUTO_INCREMENT assign, so the id differs per install.
    """
    def _n(table: str) -> int:
        return db.count(
            f"SELECT COUNT(*) FROM {table} e "
            f"JOIN hlstats_Actions a ON a.id = e.actionId "
            f"WHERE a.code = '{code}' AND a.game = '{game}'"
        )
    return ActionRows(code=code, ppa=_n(_PPA), pa=_n(_PA))


def check_carried(db, code: str, *, emitted: int, table: str,
                  other_table: str) -> dict:
    """Did every emitted line become exactly one row?

    This is the assertion Lane B actually wants, and it needs the log-side
    count to state it. Three outcomes, deliberately distinct:

    - **ok** — `rows == emitted`. Exact, not `>= 1`. The daemon should carry
      every line, so equality is the real invariant, and it catches *partial*
      loss that a `>= 1` check waves through. The unflushed-queue bug produced
      39 rows for 47 kills; `>= 1` called that a pass.
    - **not_exercised** — nothing was emitted. The pipeline was not tested, so
      it cannot have passed. Bot AI decides whether a cap_break happens at all,
      and calling that a pipeline failure trains people to ignore the run.
    - **pipeline** — lines were emitted and the rows do not match. This is a
      real defect and the only one that should stop anybody.

    The flag invariant (`other_table` must be empty) is checked in every case
    where rows exist, because it is about configuration rather than volume.
    """
    rows = count_action(db, code)
    here = rows.pa if table == _PA else rows.ppa
    there = rows.ppa if table == _PA else rows.pa

    if there != 0:
        return {"code": code, "status": "pipeline", "emitted": emitted,
                "rows": here, "detail":
                f"{there} {code} row(s) in {other_table}, expected 0. The "
                f"hlstats_Actions flags for dod/{code} are the wrong way "
                f"round, so every one is recorded twice and any reward applied "
                f"twice — a silent rating corruption, not an error."}
    if emitted == 0:
        return {"code": code, "status": "not_exercised", "emitted": 0,
                "rows": here, "detail":
                f"no `triggered \"{code}\"` lines in the game log, so this run "
                f"says nothing about whether the pipeline carries them. Not a "
                f"defect — the bots did not produce the scenario. Lengthen "
                f"--play-seconds or check waypoint coverage for the map."}
    if here != emitted:
        return {"code": code, "status": "pipeline", "emitted": emitted,
                "rows": here, "detail":
                f"{emitted} `{code}` line(s) in the game log but {here} row(s) "
                f"in {table}. Lines are being lost between the game and the "
                f"database. Check the daemon output for `(IGNORED) BOT:` "
                f"(IgnoreBots not 0), `(IGNORED) NOTMINPLAYERS:`, or a forced "
                f"shutdown that cut the final flush short."}
    return {"code": code, "status": "ok", "emitted": emitted, "rows": here,
            "detail": f"{here}/{emitted} carried"}


def check_suicides_carried(db, *, emitted: int) -> dict:
    """Did every `committed suicide with` line become a row?

    Suicides do not go through `hlstats_Actions` — they have their own table
    and their own dispatch branch — so they need their own check rather than
    `check_carried`.

    This is Unit 1 of the deployment plan. `hlstats_Events_Suicides` was empty
    fleet-wide because the only call site sat behind a regex requiring CS:GO's
    bracketed `[x y z]` block, which DoD never emits. The handler, schema and
    aggregation were always correct, so the fix is one `elsif` — and the risk
    the plan flags is that a wrong verb string compiles, deploys, and silently
    does nothing. That is exactly what this catches.
    """
    rows = db.count("SELECT COUNT(*) FROM hlstats_Events_Suicides")
    if emitted == 0:
        return {"code": "suicide", "status": "not_exercised", "emitted": 0,
                "rows": rows, "detail":
                "no `committed suicide with` lines in the game log. Bots do "
                "suicide (grenade, grenade2, world) but not on every run."}
    if rows != emitted:
        return {"code": "suicide", "status": "pipeline", "emitted": emitted,
                "rows": rows, "detail":
                f"{emitted} suicide line(s) in the game log but {rows} row(s) "
                f"in hlstats_Events_Suicides. If rows is 0, the dispatch branch "
                f"is not matching — check the verb string in hlstats.pl against "
                f"the actual line, which is the failure mode Unit 1 warns about."}
    return {"code": "suicide", "status": "ok", "emitted": emitted, "rows": rows,
            "detail": f"{rows}/{emitted} carried"}


def assert_assists_recorded(db, *, minimum: int = 1) -> ActionRows:
    """Assists reached PlayerPlayerActions, and only PlayerPlayerActions."""
    rows = count_action(db, "assist")
    if rows.ppa < minimum:
        raise AssertionError(
            f"{rows.ppa} assist rows in {_PPA}, expected >= {minimum}.\n"
            "If the game log HAS `triggered \"assist\"` lines, the loss is in "
            "the daemon leg — check for `(IGNORED) BOT:` (IgnoreBots not 0), "
            "`(IGNORED) NOTMINPLAYERS:` (too few bots), or no hlstats_Actions "
            "row (seeded after the daemon started).\n"
            "If the log has NO assist lines, the loss is upstream of the "
            "daemon and this is a capture-side failure."
        )
    if rows.pa != 0:
        raise AssertionError(
            f"{rows.pa} assist rows in {_PA}, expected exactly 0.\n"
            "for_PlayerActions is set on the dod/assist row. Every assist is "
            "being recorded twice — once with victim attribution, once "
            "without — and any reward applied twice."
        )
    return rows


def assert_breaks_recorded(db, *, minimum: int = 1) -> ActionRows:
    """Cap-breaks reached PlayerActions, and only PlayerActions."""
    rows = count_action(db, "cap_break")
    if rows.pa < minimum:
        raise AssertionError(
            f"{rows.pa} cap_break rows in {_PA}, expected >= {minimum}.\n"
            "A break needs a capper killed mid-capture, which is rarer than an "
            "assist — confirm the game log carried `triggered \"cap_break\"` "
            "before treating this as a pipeline failure. If it did, see the "
            "assist message for the daemon-side gates."
        )
    if rows.ppa != 0:
        raise AssertionError(
            f"{rows.ppa} cap_break rows in {_PPA}, expected exactly 0.\n"
            "for_PlayerPlayerActions is set on the dod/cap_break row — breaks "
            "have no victim, so this is double-recording against a meaningless "
            "second player."
        )
    return rows


def assert_positions_populated(db, code: str, *, table: str,
                               world_limit: int = 16384) -> dict:
    """Positions are present, varied, and inside the GoldSrc world.

    `world_limit` is GoldSrc's ±16384 coordinate bound. A value outside it is
    not a big map, it is a misread — usually a struct offset or a truncated
    string, both of which produce numbers that look fine in isolation.
    """
    out = db.sql(
        f"SELECT COUNT(*), "
        f"       SUM(e.pos_x IS NULL OR e.pos_y IS NULL OR e.pos_z IS NULL), "
        f"       SUM(e.pos_x = 0 AND e.pos_y = 0 AND e.pos_z = 0), "
        f"       COUNT(DISTINCT CONCAT_WS(',', e.pos_x, e.pos_y, e.pos_z)), "
        f"       MAX(GREATEST(ABS(e.pos_x), ABS(e.pos_y), ABS(e.pos_z))) "
        f"FROM {table} e JOIN hlstats_Actions a ON a.id = e.actionId "
        f"WHERE a.code = '{code}' AND a.game = 'dod'"
    ).strip().splitlines()
    if len(out) < 2:
        raise AssertionError(f"position query returned nothing for {code}")

    def _int(v: str) -> int:
        return 0 if v in ("NULL", "") else int(float(v))

    total, nulls, zeros, distinct, extreme = (_int(v) for v in out[1].split("\t")[:5])
    stats = {"rows": total, "null": nulls, "all_zero": zeros,
             "distinct": distinct, "max_abs": extreme}

    if total == 0:
        raise AssertionError(f"no {code} rows to check positions on")
    if nulls == total:
        raise AssertionError(
            f"all {total} {code} rows have NULL positions. That is "
            "`ksc_origin_str` failing its read on every event and omitting the "
            "property — the plugin is emitting, the origin lookup is not."
        )
    if zeros == total:
        raise AssertionError(
            f"all {total} {code} rows are at 0 0 0. `ksc_origin_str` returns "
            "false rather than zeros on a failed read, so this is not that "
            "guard firing — it is being bypassed, or the origin is being read "
            "from an unspawned entity."
        )
    if total > 1 and distinct == 1:
        raise AssertionError(
            f"all {total} {code} rows share one position. Real play does not "
            "produce that; suspect a stale cached origin."
        )
    if extreme > world_limit:
        raise AssertionError(
            f"{code} position magnitude {extreme} exceeds the GoldSrc world "
            f"bound of {world_limit} — a misread, not a large map."
        )
    return stats


def assert_baseline_still_flows(db) -> dict:
    """Frags and weapon stats are still being written.

    Lane B's purpose is new stats, but the failure mode worth catching is a
    change that adds assists while breaking the frag path. This is the
    regression half.
    """
    frags = db.count("SELECT COUNT(*) FROM hlstats_Events_Frags")
    players = db.count("SELECT COUNT(*) FROM hlstats_Players")
    # Players first, deliberately. When both are zero, no players is the cause
    # and no frags is the symptom — reporting the symptom sends the reader to
    # the capture code when the problem is the server row.
    if players == 0:
        raise AssertionError(
            "0 rows in hlstats_Players. No player was ever created, so every "
            "event had nothing to attach to. Usually a missing/mismatched "
            "hlstats_Servers row rather than anything to do with capture."
        )
    if frags == 0:
        raise AssertionError(
            f"0 rows in hlstats_Events_Frags with {players} player(s) on "
            "record. Nothing about the new stats can be trusted from this run "
            "— the baseline path the fleet already depends on is not "
            "recording."
        )
    return {"frags": frags, "players": players}


def check_headshots_carried(db, *, emitted: int) -> dict:
    """Did the `headshot_kill` markers reach `hlstats_Events_Frags.headshot`?

    Unit 2's regression check, and the sharp one. That unit edits a file
    carrying load-bearing stock stats, and the headshot marker rides the same
    generic player-vs-player dispatch path the new assist action does — so a
    change that breaks attribution there takes headshots with it.

    The marker is not an ordinary event: it is emitted *after* the kill line
    and makes the daemon flush the frag queue and UPDATE the most recent
    matching frag. That means a mismatch here can also mean the UPDATE failed
    to find its row, which is a different bug from the marker not arriving —
    hence reporting both numbers rather than a bare pass/fail.
    """
    rows = db.count("SELECT COUNT(*) FROM hlstats_Events_Frags WHERE headshot = 1")
    if emitted == 0:
        return {"code": "headshot", "status": "not_exercised", "emitted": 0,
                "rows": rows, "detail":
                "no `headshot_kill` markers in the game log, so the marker "
                "path was not exercised this run."}
    if rows != emitted:
        return {"code": "headshot", "status": "pipeline", "emitted": emitted,
                "rows": rows, "detail":
                f"{emitted} headshot marker(s) in the game log but {rows} frag "
                f"row(s) with headshot=1. The marker makes the daemon flush "
                f"the frag queue and UPDATE the most recent matching frag, so "
                f"a shortfall is either the marker not arriving or the UPDATE "
                f"matching no row (killer/victim/weapon mismatch)."}
    return {"code": "headshot", "status": "ok", "emitted": emitted,
            "rows": rows, "detail": f"{rows}/{emitted} carried"}


def assert_no_dropped_lines(log_text: str) -> None:
    """The plugin's ring buffer never overflowed.

    A drop is not a test failure in the usual sense — the pipeline works, it
    just could not keep up. It still fails the run, because every assertion
    above becomes a lower bound on an unknown quantity once lines are missing.
    """
    dropped = [ln for ln in log_text.splitlines() if "[KTP-STATS] dropped" in ln]
    if dropped:
        raise AssertionError(
            f"{len(dropped)} buffer-overflow line(s) in the game log — capture "
            "could not keep up and an unknown number of events never reached "
            "the daemon:\n  " + "\n  ".join(dropped[:5])
        )


def summarise(db) -> dict:
    """Everything Lane B measured, for the run report. Raises nothing."""
    def _safe(fn, *a, **kw):
        try:
            return fn(*a, **kw)
        except Exception as e:  # noqa: BLE001
            return {"error": str(e).splitlines()[0]}

    return {
        "assist": vars(count_action(db, "assist")),
        "cap_break": vars(count_action(db, "cap_break")),
        # Raw table totals alongside the joined counts. When the two disagree
        # the problem is the action row or the join, not the pipeline — and
        # without both numbers that is indistinguishable from nothing arriving.
        "ppa_rows_total": db.count(f"SELECT COUNT(*) FROM {_PPA}"),
        "pa_rows_total": db.count(f"SELECT COUNT(*) FROM {_PA}"),
        "suicides": db.count("SELECT COUNT(*) FROM hlstats_Events_Suicides"),
        "suicide_weapons": db.sql(
            "SELECT weapon, COUNT(*) FROM hlstats_Events_Suicides "
            "GROUP BY weapon").strip(),
        "actions_seeded": db.sql(
            "SELECT id, code, for_PlayerActions, for_PlayerPlayerActions "
            "FROM hlstats_Actions WHERE game='dod'").strip(),
        "action_ids_seen": db.sql(
            f"SELECT actionId, COUNT(*) FROM {_PA} GROUP BY actionId "
            f"UNION ALL SELECT actionId, COUNT(*) FROM {_PPA} GROUP BY actionId"
        ).strip(),
        "frags": db.count("SELECT COUNT(*) FROM hlstats_Events_Frags"),
        "players": db.count("SELECT COUNT(*) FROM hlstats_Players"),
        "bots": db.count("SELECT COUNT(*) FROM hlstats_Players "
                         "WHERE playerId IN (SELECT playerId FROM hlstats_PlayerUniqueIds "
                         "WHERE uniqueId LIKE 'BOT:%')"),
        "assist_positions": _safe(assert_positions_populated, db, "assist", table=_PPA),
        "break_positions": _safe(assert_positions_populated, db, "cap_break", table=_PA),
    }
