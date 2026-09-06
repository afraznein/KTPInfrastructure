"""Unit tests for the flag-swing calibration fitter."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.fit_flag_swing import extract_half_samples, fit_logistic

ROSTER = [{"player_id": pid, "team": 1 if pid <= 3 else 2}
          for pid in (1, 2, 3, 4, 5, 6)]


def test_fit_recovers_flag_dominance_from_separable_data():
    # Flag control decides everything: label follows sign of flag_term.
    samples = []
    for sign, label in ((1, 1), (-1, 0)):
        samples += [(0.4 * sign, 0.0, label)] * 50
        samples += [(0.8 * sign, 0.1 * sign, label)] * 50
    fit = fit_logistic(samples, halves=4)
    assert fit.flag_coefficient > fit.alive_coefficient
    assert fit.log_loss < 0.4
    assert "fitted_team_score_4_halves" in fit.as_config_json()


def test_fit_clamps_perverse_coefficients_to_zero():
    # Labels anti-correlated with flag control: coefficient clamps at 0.
    samples = [(0.5, 0.0, 0)] * 40 + [(-0.5, 0.0, 1)] * 40
    fit = fit_logistic(samples)
    assert fit.flag_coefficient == 0.0


def test_fit_refuses_empty_input():
    with pytest.raises(ValueError):
        fit_logistic([])


def test_extract_samples_labels_and_tracks_state():
    states = [{"half": 1, "flag_index": 0, "owner_team": 1,
               "game_time": 10.0}]
    frags = [{"half": 1, "game_time": 20.0, "killer_id": 1, "victim_id": 4}]
    spawns = [{"half": 1, "game_time": 30.0, "player_id": 4,
               "boundary_kind": "start"}]
    samples = extract_half_samples(states, frags, spawns, ROSTER,
                                   half=1, winner_team=1, flag_count=5)
    assert len(samples) == 3
    flag_terms = [s[0] for s in samples]
    alive_terms = [s[1] for s in samples]
    labels = {s[2] for s in samples}
    assert flag_terms == [0.2, 0.2, 0.2]
    assert alive_terms == [0.0, pytest.approx(1 / 6), 0.0]
    assert labels == {1}
    # Axis win labels 0; unknown winner is skipped entirely.
    assert {s[2] for s in extract_half_samples(
        states, [], [], ROSTER, half=1, winner_team=2)} == {0}
    assert extract_half_samples(states, [], [], ROSTER,
                                half=1, winner_team=0) == []
