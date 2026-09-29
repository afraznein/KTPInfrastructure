"""Interrupted captures: which stops count, who gets credit, which band."""
from __future__ import annotations

import unittest

from scripts.interruptions import (InterruptionConfig, band_for,
                                   build_interruptions)


def stop(half=1, t=100.0, team=1, peak=60, flag="the street",
         allies_in=2, axis_in=1, reason="capture_stopped", kind="stop"):
    return {"half": half, "game_time": t, "capturing_team": team,
            "peak_progress": peak, "flag_name": flag, "event_kind": kind,
            "stop_reason": reason, "allies_in_zone": allies_in,
            "axis_in_zone": axis_in}


def frag(t, killer, victim, half=1):
    return {"half": half, "game_time": t, "killer_id": killer, "victim_id": victim}


def life(pid, team, half=1):
    return {"half": half, "player_id": pid, "team": team}


ROSTER = [life(1, 1), life(2, 1), life(9, 2), life(8, 2)]


class WhichRowsCount(unittest.TestCase):
    def test_a_stopped_capture_is_an_interruption(self):
        out = build_interruptions([stop()], [], ROSTER)
        self.assertEqual(len(out["rows"]), 1)
        self.assertEqual(out["rows"][0]["capturing_team"], 1)
        self.assertEqual(out["rows"][0]["defending_team"], 2)

    def test_a_completed_capture_is_not(self):
        self.assertEqual(build_interruptions([stop(kind="complete")], [], ROSTER)["rows"], [])

    def test_a_start_is_not(self):
        self.assertEqual(build_interruptions([stop(kind="start")], [], ROSTER)["rows"], [])

    def test_a_context_reset_is_not_a_play(self):
        # Round resets neutralise everything; nobody stopped anything.
        out = build_interruptions([stop(reason="context_reset")], [], ROSTER)
        self.assertEqual(out["rows"], [])

    def test_a_missing_feed_is_unavailable_not_empty(self):
        out = build_interruptions(None, [], ROSTER)
        self.assertEqual(out["status"], "unavailable")
        out = build_interruptions([stop()], [], ROSTER, source_status="unavailable")
        self.assertEqual(out["status"], "unavailable")

    def test_zone_counts_are_read_from_the_capturing_side(self):
        row = build_interruptions([stop(team=1, allies_in=3, axis_in=1)], [], ROSTER)["rows"][0]
        self.assertEqual((row["attackers_in_zone"], row["defenders_in_zone"]), (3, 1))
        row = build_interruptions([stop(team=2, allies_in=3, axis_in=1)], [], ROSTER)["rows"][0]
        self.assertEqual((row["attackers_in_zone"], row["defenders_in_zone"]), (1, 3))


class WhoStoppedIt(unittest.TestCase):
    def test_a_defender_who_killed_the_capper_is_credited(self):
        out = build_interruptions([stop(t=100.0)], [frag(98.5, 9, 1)], ROSTER)
        self.assertEqual(out["rows"][0]["credited"], [9])

    def test_several_defenders_can_share_one_stop(self):
        out = build_interruptions([stop(t=100.0)],
                                  [frag(98.0, 9, 1), frag(99.0, 8, 2)], ROSTER)
        self.assertEqual(sorted(out["rows"][0]["credited"]), [8, 9])

    def test_a_kill_before_the_window_does_not_count(self):
        out = build_interruptions([stop(t=100.0)], [frag(90.0, 9, 1)], ROSTER,
                                  InterruptionConfig(credit_window_seconds=4.0))
        self.assertEqual(out["rows"][0]["credited"], [])

    def test_a_kill_after_the_stop_does_not_count(self):
        out = build_interruptions([stop(t=100.0)], [frag(101.0, 9, 1)], ROSTER)
        self.assertEqual(out["rows"][0]["credited"], [])

    def test_killing_your_own_side_is_not_a_stop(self):
        # 2 is on the capturing side; teamkilling a capper does not credit.
        out = build_interruptions([stop(t=100.0)], [frag(99.0, 2, 1)], ROSTER)
        self.assertEqual(out["rows"][0]["credited"], [])

    def test_a_stop_nobody_is_credited_for_is_still_recorded(self):
        # The capper may have walked off, or died to something the frag feed
        # does not carry. Dropping the row would lose a real interruption.
        out = build_interruptions([stop()], [], ROSTER)
        self.assertEqual(out["rows"][0]["credited"], [])
        self.assertEqual(out["by_band"]["substantial"], {"events": 1, "attributed": 0})

    def test_sides_come_from_the_half_not_the_roster(self):
        # Player 1 is allied in half 1 and axis in half 2 (a half-time swap or
        # a leaver). The half-2 stop must read half-2 sides.
        roster = ROSTER + [life(1, 2, half=2), life(9, 1, half=2)]
        out = build_interruptions([stop(half=2, t=50.0, team=2)],
                                  [frag(49.0, 9, 1, half=2)], roster)
        self.assertEqual(out["rows"][0]["credited"], [9])


class Bands(unittest.TestCase):
    """Named, never priced -- the top bands rest on n=22 and n=10."""

    def test_bands_follow_measured_progress(self):
        self.assertEqual(band_for(0)["band"], "negligible")
        self.assertEqual(band_for(24)["band"], "negligible")
        self.assertEqual(band_for(25)["band"], "partial")
        self.assertEqual(band_for(60)["band"], "substantial")
        self.assertEqual(band_for(75)["band"], "decisive")
        self.assertEqual(band_for(100)["band"], "decisive")

    def test_a_band_carries_its_evidence_not_a_price(self):
        got = band_for(80)
        self.assertEqual(got["measured_lift"], 0.0)
        self.assertEqual(got["measured_n"], 10)
        self.assertNotIn("value", got)
        self.assertNotIn("points", got)

    def test_unknown_progress_lands_in_the_control_band(self):
        self.assertEqual(band_for(None)["band"], "negligible")

    def test_the_block_prices_nothing(self):
        out = build_interruptions([stop()], [], ROSTER)
        self.assertFalse(out["rating_effect"])
        self.assertEqual(out["visibility"], "private_shadow_only")


if __name__ == "__main__":
    unittest.main()
