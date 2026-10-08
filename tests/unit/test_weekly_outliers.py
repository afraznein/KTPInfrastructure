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



def test_match_anomalies_flag_the_night_not_the_week():
    def m(mid, start, **k):
        d = {"match_id": mid, "match_type": 2, "map": "dod_halle", "start": start, "server": "s", "windows": 400,
             "drops_win": 3.0, "drops_max": 40.0, "maxunlag_win": 1.0, "loss_worst": 2.0, "jitter_worst": 90.0,
             "lagcomp_off": 0}
        d.update(k)
        return d
    ms = [m(f"old{i}", "2026-09-14", drops_win=2.0 + i % 4) for i in range(20)]
    ms += [m("quiet", "2026-10-04"), m("disaster", "2026-10-04", drops_win=320.0, maxunlag_win=290.0),
           m("lagcomp", "2026-10-04", lagcomp_off=3)]
    out = wo.match_anomalies(ms, cutoff="2026-10-01")
    assert [x["match_id"] for x in out] == ["disaster", "lagcomp"]
    assert out[0]["net_driver"] in ("drops_win", "maxunlag_win")
    assert all(x["match_id"] != "old0" for x in out)  # outside the window, even if extreme


def test_recent_change_flags_a_relapse_not_a_chronic_connection():
    rows = []
    # Player 1: chronic 60% jitter-worst all season -- no change.
    rows += [half(1, f"m{i}", 1, start="2026-09-20", jit_share=0.6) for i in range(6)]
    rows += [half(1, f"n{i}", 1, start="2026-10-05", jit_share=0.6) for i in range(3)]
    # Player 2: 5% all season, 60% in the last three halves -- a relapse.
    rows += [half(2, f"m{i}", 1, start="2026-09-20", jit_share=0.05 + 0.01 * (i % 2)) for i in range(6)]
    rows += [half(2, f"n{i}", 1, start="2026-10-05", jit_share=0.6) for i in range(3)]
    for p in range(3, 12):
        rows += [half(p, f"m{i}", 2, start="2026-09-20", jit_share=0.02 + 0.01 * (i % 3)) for i in range(5)]
    out = wo.recent_change(rows, cutoff="2026-10-01", min_recent=3, min_prior=4)
    assert [p["player_id"] for p in out] == [2]
    assert out[0]["change_driver"] == "jit_share"
    assert out[0]["z_jit_share"] > 2


def test_server_offsets_cancel_the_roster():
    rows = []
    # Players 1-9 each play two servers; server 7 adds 0.3 to everyone's jitter share, server 8 adds nothing.
    for p in range(1, 10):
        base = 0.05 * p
        rows += [half(p, f"a{i}", 1, server=8, jit_share=base) for i in range(3)]
        rows += [half(p, f"b{i}", 1, server=7, jit_share=base + 0.3) for i in range(3)]
    out = {s["server"]: s for s in wo.server_offsets(rows, min_halves=2, min_pairs=8)}
    assert abs(out[7]["jit_share"] - 0.15) < 1e-9 and abs(out[8]["jit_share"] + 0.15) < 1e-9
    assert out[7]["pairs"] == 9


def test_rank_servers_worst_player_first_and_gaps_last():
    pings = {(1, 10): 30.0, (2, 10): 90.0, (1, 11): 50.0, (2, 11): 55.0, (1, 12): 10.0}
    out = wo.rank_servers(pings, [1, 2])
    assert [r["server"] for r in out] == [11, 10, 12]  # 11: worst 55; 10: worst 90; 12: player 2 unmeasured
    assert out[2]["missing"] == [2]
    assert out[1]["worst_pid"] == 2 and out[1]["worst"] == 90.0
