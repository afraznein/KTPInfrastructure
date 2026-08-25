from scripts.compare_v5_match_reports import _percentile, _spearman


def test_comparison_statistics_are_deterministic_and_tie_safe():
    assert _percentile([1, 2, 3, 4], 0.25) == 1.75
    assert _spearman([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0
    assert _spearman([1, 2, 2, 4], [40, 30, 30, 10]) == -1.0
