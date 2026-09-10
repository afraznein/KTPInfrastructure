"""Sandbagging detector, pass 2 design: the SHIFT in relative performance
across a division move, not just a high z-score in a low division.

User correction (2026-09-07): playing in Silver after Gold is not itself a
signal. Playing averagely in Gold, then becoming a dominant outlier after
dropping to Silver, is. So the flag is a DELTA between two snapshots of the
same player's performance-within-population z-score, not a single snapshot.

Not runnable against real data yet: this needs the same player's performance
in two different divisions across two seasons (or a mid-season move), which
requires the website's division history (ktp.legacy_season_team /
ktp.season_team_member) -- S9 alone only gives one division per player.
The function below is the mechanism, validated by the self-check in main(),
ready to point at real two-snapshot data the moment it exists.
"""
from dataclasses import dataclass


@dataclass
class Snapshot:
    division_rank: int  # lower number = higher division, e.g. Gold=1, Silver=2, Bronze=3
    z: float            # this player's performance z-score within that snapshot's population


def flag(before: Snapshot, after: Snapshot, min_z_after: float = 1.0, min_delta: float = 1.0):
    """True if the player got MORE dominant after moving to a LOWER division.
    Both conditions matter: a big delta with an unremarkable z_after is a
    player who was quietly underperforming Gold, not a sandbagger; a high
    z_after with no delta (they were already this dominant before the move)
    is just a strong player, not evidence of picking weak opponents."""
    moved_down = after.division_rank > before.division_rank
    delta = after.z - before.z
    return moved_down and after.z >= min_z_after and delta >= min_delta, delta


def _selfcheck():
    # Sandbagger: average in Gold (z=0.2), dominant after dropping to Silver (z=2.1).
    is_flag, delta = flag(Snapshot(1, 0.2), Snapshot(2, 2.1))
    assert is_flag and abs(delta - 1.9) < 1e-9, (is_flag, delta)

    # Already-dominant player who moved down: not new evidence of sandbagging.
    is_flag, _ = flag(Snapshot(1, 2.0), Snapshot(2, 2.2))
    assert not is_flag

    # Moved UP a division and got relatively worse: not a sandbagging shape at all.
    is_flag, _ = flag(Snapshot(2, 0.5), Snapshot(1, -0.5))
    assert not is_flag

    # Stayed in the same division, got much better: not a division-move signal
    # (could be real improvement or an unrelated stat outlier -- different flag).
    is_flag, _ = flag(Snapshot(2, 0.1), Snapshot(2, 2.5))
    assert not is_flag


if __name__ == "__main__":
    _selfcheck()
    print("self-check passed: flag() correctly distinguishes a real division-drop "
          "dominance jump from an already-strong player, an upward move, and a "
          "same-division improvement. Waiting on website division history to run "
          "for real.")
