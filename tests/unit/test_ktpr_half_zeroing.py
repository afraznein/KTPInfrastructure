"""`load_half_player_stats` must not publish a zero for a half the HUD never summarised.

The loader's `hud` dict is built by iterating the is_final SUMMARY rows, so a
(player, match, half) with no summary row gets no entry and the main loop falls
through to `hud.get(key, (0.0, 0.0, None))`. The roster fallback then supplies
`side`, so the half IS published -- and before #810 it was published with
assists and breaks at zero, although `_hud_event_stats` had already computed
the real values from hud_kill_assists / hud_kills and hud_flag_events, which
are independent of hud_player_stats. Measured on the S9 cohort: 49 such halves,
201 assists and 14 cap-breaks discarded.

#810 fixed it and was verified by reading. Nothing exercised the loader, so the
fix rested on the claim that the fallback's `hud_ev` lookup uses the same key
shape as the loop -- the exact thing a key-form change would break silently,
and KTPR would go quietly wrong again rather than fail. This runs the loader.

No DB: run_sql is replaced with the TSV the remote mysql CLI would have
printed. The stub RAISES on a query it does not recognise rather than
returning "", so a loader that grows a query fails loudly instead of being fed
an empty result that reads as a measurement.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "docs" / "ktpr_mcp"))

import ktpr_mysql  # noqa: E402

MATCH = "1754000000-1"

# Three players, two halves each. A is fully summarised; B and C are missing
# their half-2 summary row, which is the shape the 49 lost halves have (all 49
# are half 2). B's lost half carries real events; C's carries none, so the two
# together separate "restores the events" from "makes everything non-zero".
A, B, C = "0:11111", "0:22222", "0:33333"
SID = {A: "STEAM_0:" + A, B: "STEAM_0:" + B, C: "STEAM_0:" + C}
PID = {"101": A, "202": B, "303": C}

# ktp_match_players.team, the fallback's side source. 1=Allies/2=Axis at the
# last tracking pass; _side_from_match_team flips it for half 1.
KMP_TEAM = {A: 1, B: 2, C: 1}

# The summary rows that DO exist. `team` here is the side string the loader
# reads out of hud_player_stats; its assist/break columns are deliberately
# WRONG (the summaries under-report) so the test fails if they are ever used.
SUMMARY = [
    (SID[A], 1, 2, 0, "axis"),
    (SID[A], 2, 3, 1, "allies"),
    (SID[B], 1, 1, 0, "allies"),
    (SID[C], 1, 9, 9, "axis"),
]

# What the event tables actually hold, per (player, half).
EV_ASSISTS = {(SID[A], 1): 4, (SID[A], 2): 5, (SID[B], 1): 2, (SID[B], 2): 3}
EV_BREAKS = {(SID[A], 1): 1, (SID[B], 2): 2}


def _tsv(rows):
    return "".join("\t".join(str(c) for c in r) + "\n" for r in rows)


def _fake_run_sql(sql, database=None):
    s = " ".join(sql.split())
    if "FROM hud_kill_assists" in s:
        return _tsv([(sid, MATCH, half, n) for (sid, half), n in EV_ASSISTS.items()])
    if "FROM hud_flag_events" in s and "'cap_break'" in s:
        return _tsv([(sid, MATCH, half, n) for (sid, half), n in EV_BREAKS.items()])
    if "FROM hud_flag_events" in s and "'captured'" in s:
        return _tsv([(SID[B], MATCH, 2, 1)])
    if "FROM hud_player_stats" in s:
        return _tsv([(sid, MATCH, half, a, b, team) for sid, half, a, b, team in SUMMARY])
    if "FROM hud_spawns" in s:
        return ""                                   # no roles; role falls back to "?"
    if "FROM hud_events" in s:
        return MATCH + "\n"                         # the tournament match-id list
    if "FROM hlstats_PlayerUniqueIds" in s:
        return _tsv(PID.items())
    if "hlstats_Events_Frags" in s:
        return _tsv([("101", MATCH, 1, 10, 5), ("101", MATCH, 2, 8, 6),
                     ("202", MATCH, 1, 7, 7), ("202", MATCH, 2, 9, 4),
                     ("303", MATCH, 1, 6, 3), ("303", MATCH, 2, 5, 8)])
    if "FROM ktp_match_stats" in s:
        return _tsv([(pid, MATCH, half, 1000) for pid in PID for half in (1, 2)])
    if "FROM ktp_match_players" in s:
        # Two callers, different column orders: _infer_teams asks for
        # (match_id, team, steam_id); the fallback asks for (steam_id, match_id,
        # team). Both store the BARE tail, not the STEAM_0: form.
        if s.startswith("SELECT match_id, team, steam_id"):
            return _tsv([(MATCH, KMP_TEAM[u], u) for u in (A, B, C)])
        return _tsv([(u, MATCH, KMP_TEAM[u]) for u in (A, B, C)])
    raise AssertionError(f"unstubbed query -- returning '' here would read as a measurement:\n{s}")


class HalfZeroing(unittest.TestCase):
    def setUp(self):
        real = ktpr_mysql.run_sql
        self.addCleanup(setattr, ktpr_mysql, "run_sql", real)
        ktpr_mysql.run_sql = _fake_run_sql
        self.rows = {(r.name, r.side): r for r in ktpr_mysql.load_half_player_stats()}

    def test_every_player_half_is_published(self):
        # Six spine halves in, six rows out: the fallback resolves a side for
        # all four unsummarised halves, so none is dropped.
        self.assertEqual(len(self.rows), 6)

    def test_lost_half_keeps_its_real_assists_and_breaks(self):
        # THE REGRESSION. B's half 2 has no summary row; pre-#810 this was
        # (0.0, 0.0). Side is axis: team 2, half 2, orientation +1.
        row = self.rows[(f"[{SID[B]}]", "axis")]
        self.assertEqual(row.assists_half, 3.0)
        self.assertEqual(row.breaks_half, 2.0)

    def test_a_genuinely_eventless_lost_half_still_reads_zero(self):
        # Control, and the one that makes the test above mean something: C's
        # half 2 is equally unsummarised but has no events, so zero is the
        # correct answer. 4 of the measured 49 are this case.
        row = self.rows[(f"[{SID[C]}]", "allies")]
        self.assertEqual(row.assists_half, 0.0)
        self.assertEqual(row.breaks_half, 0.0)

    def test_a_summarised_half_also_uses_the_event_values(self):
        # The summaries under-report even when present, so the numbers come from
        # the events on both paths. A's half-2 summary says 3 assists / 1 break
        # against 5 / 0 in the events.
        row = self.rows[(f"[{SID[A]}]", "allies")]
        self.assertEqual(row.assists_half, 5.0)
        self.assertEqual(row.breaks_half, 0.0)

    def test_no_summary_assist_figure_reaches_the_output(self):
        # Guards the whole class of regression rather than one row: 9 appears
        # only in C's deliberately-wrong summary, and 9.0 assists would mean the
        # loader had gone back to trusting hud_player_stats.
        self.assertNotIn(9.0, [r.assists_half for r in self.rows.values()])


class EventKeyShape(unittest.TestCase):
    """The fallback's lookup and the main loop must build the same key.

    This is what #810 rested on and nothing held: `_hud_event_stats` keys on the
    steam_id as STORED (prefixed), while the loop builds `"STEAM_0:" + uid` from
    hlstats_PlayerUniqueIds, which stores the bare tail. Three tables in this
    database hold the same identity in two forms, so a change that picks one
    looks correct and matches nothing.
    """

    def setUp(self):
        real = ktpr_mysql.run_sql
        self.addCleanup(setattr, ktpr_mysql, "run_sql", real)
        ktpr_mysql.run_sql = _fake_run_sql
        self.ev = ktpr_mysql._hud_event_stats(f"'{MATCH}'", "half")

    def test_the_lost_halfs_key_is_present(self):
        self.assertEqual(self.ev[(SID[B], MATCH, 2)], (3.0, 2.0))

    def test_a_nonsense_key_is_absent(self):
        # Without this, a dict that answered for everything would pass above.
        self.assertIsNone(self.ev.get((SID[B], "zqwb1107nosuchmatch", 2)))
        self.assertIsNone(self.ev.get(("STEAM_0:zqwb1107nosuchid", MATCH, 2)))

    def test_half_is_an_int_in_the_key(self):
        # The loop keys on int(half); a str would miss every lookup silently.
        self.assertNotIn((SID[B], MATCH, "2"), self.ev)


if __name__ == "__main__":
    unittest.main()
