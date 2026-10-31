"""own_weapon_kills.py: row shaping, the two boards and their per-match denominator, repeat pairs,
and that the markdown renders an empty night. No database.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

SCRIPTS = pathlib.Path(__file__).resolve().parents[2] / "scripts"
sys.path.insert(0, str(SCRIPTS))  # own_weapon_kills imports voice_taunts from its own directory
spec = importlib.util.spec_from_file_location("own_weapon_kills", SCRIPTS / "own_weapon_kills.py")
ow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ow)


def row(i, killer=1, kname="thief", victim=2, vname="owner", weapon="kar", tk="0", mid="M1", mtype=0,
        t="2026-11-01 20:00:00"):
    return [str(i), t, mid, str(mtype), "dod_anzio", str(killer), kname, str(victim), vname, weapon, tk]


def test_shape_reads_teamkill_flag_and_weapon():
    (k,) = ow.shape([row(1, weapon="garand", tk="1")])
    assert (k["weapon"], k["teamkill"], k["killer"], k["victim"]) == ("garand", True, "thief", "owner")


def test_robbed_board_counts_owners_and_divides_by_capable_matches():
    kills = ow.shape([row(1), row(2, mid="M2"), row(3, killer=3, kname="other", tk="1")])
    (r,) = ow.board(kills, {(2, 0): 4}, ow.vt.OFFICIAL, "victim")
    assert (r["name"], r["n"], r["teammate"], r["matches"], r["per_match"], r["top_other"]) == \
        ("owner", 3, 1, 4, 0.75, "thief")


def test_thieves_board_and_scope_filter():
    kills = ow.shape([row(1), row(2, mtype=2)])
    (r,) = ow.board(kills, {}, ow.vt.OFFICIAL, "killer")
    assert (r["name"], r["n"], r["per_match"]) == ("thief", 1, None)
    assert ow.board(kills, {}, (2,), "killer")[0]["n"] == 1


def test_pairs_only_repeat_offenders():
    kills = ow.shape([row(1), row(2), row(3, killer=3, kname="once")])
    S = ow.snapshot(kills, {}, "2026-09-13", "now", matches=2)
    assert S["pairs"] == [{"killer": "thief", "victim": "owner", "n": 2}]
    assert S["kills"] == 3 and S["recent"][0]["killer"] in ("thief", "once")


def test_league_names_replace_in_game_names():
    kills = ow.shape([row(1)])
    n = ow.resolve_names(kills, {1: {"0:123"}}, {"0:123": "LeagueThief"})
    assert n == 1 and kills[0]["killer"] == "LeagueThief" and kills[0]["victim"] == "owner"


def test_empty_night_renders():
    text = ow.render(ow.snapshot([], {}, "2026-09-13", "now"), 25)
    assert "0 own-weapon kills" in text and "none" in text
