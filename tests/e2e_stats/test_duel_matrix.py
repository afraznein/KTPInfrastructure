"""Unit tests for the duel matrix (definition v1)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.match_analytics import build_duel_matrix, duel_matrix_markdown

PLAYERS = [
    {"player_id": 1, "player_name_at_match": "Alfa", "team": 1},
    {"player_id": 2, "player_name_at_match": "Bravo", "team": 1},
    {"player_id": 3, "player_name_at_match": "Zulu", "team": 2},
]


def frag(killer, victim):
    return {"killer_id": killer, "victim_id": victim}


def test_cells_count_pairings_and_mark_cross_team():
    matrix = build_duel_matrix(
        [frag(1, 3), frag(1, 3), frag(3, 2), frag(1, 2)], PLAYERS)
    cells = {(c["killer_id"], c["victim_id"]): c for c in matrix["cells"]}
    assert cells[(1, 3)]["kills"] == 2
    assert cells[(1, 3)]["cross_team"] is True
    assert cells[(1, 2)]["kills"] == 1
    assert cells[(1, 2)]["cross_team"] is False
    assert matrix["frags_outside_roster"] == 0


def test_player_order_groups_teams_then_names():
    matrix = build_duel_matrix([frag(1, 3)], PLAYERS)
    assert matrix["player_order"] == [1, 2, 3]


def test_frags_outside_roster_are_counted_not_guessed():
    matrix = build_duel_matrix(
        [frag(1, 99), frag(None, 3)], PLAYERS)
    assert matrix["cells"] == []
    assert matrix["frags_outside_roster"] == 2


def test_matrix_total_reconciles_with_kills():
    frags = [frag(1, 3), frag(1, 3), frag(3, 1), frag(2, 3), frag(1, 2)]
    matrix = build_duel_matrix(frags, PLAYERS)
    assert sum(c["kills"] for c in matrix["cells"]) == len(frags)


def test_markdown_grid_shape_and_empty_cells():
    matrix = build_duel_matrix([frag(1, 3)], PLAYERS)
    text = duel_matrix_markdown(matrix, PLAYERS)
    lines = text.strip().splitlines()
    assert len(lines) == 2 + len(PLAYERS)
    assert lines[0].startswith("| Killer \\ Victim | Alfa | Bravo | Zulu |")
    assert "| Alfa | · | · | 1 |" in text


def test_markdown_handles_empty_matrix():
    matrix = build_duel_matrix([], PLAYERS)
    assert duel_matrix_markdown(matrix, PLAYERS) == "_No rows._\n"
