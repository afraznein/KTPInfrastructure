from scripts import metric_confidence as confidence


def config():
    return confidence.load_config()


def test_synthetic_fact_separates_capture_from_interpretation():
    result = confidence.exact_fact(available=True, synthetic=True)
    assert result == {
        "level": "synthetic",
        "source_complete": True,
        "publishable": True,
        "reason": (
            "The count is observed exactly, but bot behavior has no competitive "
            "interpretation."
        ),
    }


def test_player_rate_thresholds_use_the_correct_denominator():
    player = {
        "damage_per_minute": 90.0,
        "damage_per_life": 150.0,
        "headshot_rate": 0.25,
        "raw_accuracy": 0.2,
        "duration_seconds": 360,
        "deaths": 2,
        "kills": 8,
        "shots": 24,
    }
    assert confidence.player_rate(
        "damage_per_minute", player, synthetic=False, config=config()
    )["level"] == "descriptive"
    assert confidence.player_rate(
        "damage_per_life", player, synthetic=False, config=config()
    )["level"] == "low_sample"
    assert confidence.player_rate(
        "headshot_rate", player, synthetic=False, config=config()
    )["level"] == "descriptive"
    assert confidence.player_rate(
        "raw_accuracy", player, synthetic=False, config=config()
    )["level"] == "low_sample"


def test_human_baseline_maturity_bands_are_explicit():
    cfg = config()
    assert confidence.baseline(4, synthetic=False, config=cfg)["level"] == "low_sample"
    assert confidence.baseline(5, synthetic=False, config=cfg)["level"] == "emerging"
    assert confidence.baseline(20, synthetic=False, config=cfg)["level"] == "reviewable"
    assert confidence.baseline(50, synthetic=False, config=cfg)["level"] == "established"
    assert confidence.baseline(500, synthetic=True, config=cfg)["level"] == "synthetic"


def test_position_points_never_gain_production_confidence():
    assert confidence.position_points(available=True)["level"] == "shadow_only"
    assert confidence.position_points(available=False)["level"] == "unavailable"
