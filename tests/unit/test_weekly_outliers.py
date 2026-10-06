"""weekly_outliers.py: the z-score shrinkage and the alert exit, with no database.

The first live run (2026-10-05) ranked a 22-kill half at z=11.6 because the player's five
prior halves happened to sit within a point of each other. The fix blends the league's
spread into every player's own spread as PSEUDO pseudo-halves; these pin that behaviour
so a tidy baseline can never again out-rank a real three-sigma half.
"""
from __future__ import annotations

import importlib.util
import pathlib

SCRIPT = pathlib.Path(__file__).resolve().parents[2] / "scripts" / "weekly_outliers.py"
spec = importlib.util.spec_from_file_location("weekly_outliers", SCRIPT)
wo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(wo)


def half(pid, mid, h, **m):
    row = {"match_id": mid, "half": h, "map": "dod_anzio", "server": 1, "start": "2026-10-04",
           "player_id": pid, "player": f"p{pid}", "kills": 20, "deaths": 20, "headshots": 4,
           "damage": 3000, "shots": 300}
    for k in wo.CORE + wo.NET:
        row[k] = 1.0
    row.update(m)
    return row


def test_tight_own_baseline_is_shrunk_toward_the_league():
    # Player 1: five halves all exactly k100=10, then one at 12. Raw own sd = 0 -> z = inf/0.
    # The league (players 2-9) spreads k100 over 4..16, so the blended sd must be well
    # above zero and the half must land as a modest positive, not a headline.
    rows = [half(1, f"m{i}", 1, k100=10.0) for i in range(5)] + [half(1, "m9", 1, k100=12.0)]
    for p in range(2, 10):
        for i in range(5):
            rows.append(half(p, f"m{i}", 2, k100=4.0 + (p + i) % 13))
    wo.zscores(rows, min_prior=4)
    z = rows[5]["z_own_k100"]
    assert z is not None and 0.5 < z < 2.5, z


def test_real_three_sigma_half_still_flags():
    rows = [half(1, f"m{i}", 1, k100=10.0 + (i % 3)) for i in range(7)] + [half(1, "m9", 1, k100=25.0)]
    for p in range(2, 10):
        for i in range(5):
            rows.append(half(p, f"m{i}", 2, k100=8.0 + (p + i) % 5))
    wo.zscores(rows, min_prior=4)
    assert rows[7]["z_own_k100"] >= 3.0
    assert rows[7]["driver"] == "k100"
    assert rows[7]["score"] == abs(rows[7]["z_own_k100"])


def test_unscored_without_enough_prior_halves():
    rows = [half(1, f"m{i}", 1, k100=10.0) for i in range(3)]
    rows += [half(2, f"m{i}", 1, k100=10.0 + i) for i in range(6)]
    wo.zscores(rows, min_prior=4)
    assert all(r["score"] is None for r in rows[:3])
    assert all(r["score"] is not None for r in rows[3:])


def test_missing_metric_does_not_poison_the_score():
    rows = [half(1, f"m{i}", 1) for i in range(6)]
    rows[5]["reg"] = None  # no traced fires that half
    rows[5]["k100"] = 40.0
    for p in range(2, 8):
        for i in range(5):
            rows.append(half(p, f"m{i}", 2, k100=1.0 + i))
    wo.zscores(rows, min_prior=4)
    assert rows[5]["z_own_reg"] is None
    assert rows[5]["driver"] == "k100"


def test_chronic_ranks_the_always_bad_connection_not_the_one_off():
    rows = []
    # Player 1: worst-jitter client in 60% of windows every half (kroD- shape).
    rows += [half(1, f"m{i}", 1, jit_share=0.6, drop_share=0.0, lat_share=0.0, rewind_share=0.0) for i in range(6)]
    # Player 2: clean except one half at 60% -- a network event, not a connection.
    rows += [half(2, f"m{i}", 1, jit_share=0.6 if i == 0 else 0.02, drop_share=0.0, lat_share=0.0, rewind_share=0.0) for i in range(6)]
    for p in range(3, 15):
        rows += [half(p, f"m{i}", 2, jit_share=0.03, drop_share=0.02, lat_share=0.05, rewind_share=0.0) for i in range(6)]
    wo.zscores(rows, min_prior=4)
    chron = wo.chronic(rows, min_prior=4)
    assert [p["player_id"] for p in chron] == [1]
    assert chron[0]["net_driver"] == "jit_share"
    # ...while the one-off half is what the per-half own-z catches instead.
    assert rows[6]["z_own_jit_share"] > 2.0

