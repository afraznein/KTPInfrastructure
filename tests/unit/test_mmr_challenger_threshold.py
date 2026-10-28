"""When the weekly digest is allowed to say a challenger beat the champion.

Three digests in a row (#550, #725, #757) reported it, two are still open, and the
rule behind them was a flat 0.01 log-loss margin on a ten-match holdout -- about a
tenth of the standard error at that sample size, so it fired on differences the
sample could not resolve.

The replacement pairs: every variant scores the same matches in the same order, so
the per-match difference carries far less variance than either series. These tests
pin the distinction, including a case the old rule got wrong and a control proving
the decision reads the paired spread rather than the two averages.

`openskill` importorskips -- run_weekly imports ladder, which needs it.
"""
import importlib.util
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts" / "mmr"))

OLD_FLAT_MARGIN = 0.01


def arm(name, diffs, base=0.50):
    """An arm whose per-match log-loss sits `diffs` BELOW the champion's."""
    return dict(name=name, n=len(diffs), seeded=False,
                ll_series=[base - d for d in diffs],
                log_loss=base - sum(diffs) / len(diffs), brier=0.0, acc=0.0)


def champion(n, base=0.50):
    from run_weekly import CHAMPION
    return dict(name=CHAMPION, n=n, seeded=True, ll_series=[base] * n,
                log_loss=base, brier=0.0, acc=0.0)


# Mean +0.011, so it clears the old flat margin, but the per-match differences
# swing by +/-0.8 -- the shape of a ten-match holdout.
NOISY = [0.811] * 10 + [-0.789] * 10
# Both built around one mean so the pair genuinely has equal averages -- the
# earlier spelling was 0.0555 against 0.055 and the control it anchors was vacuous.
EDGE = 0.055
# Almost no spread: a real, consistent edge.
STEADY = [EDGE + 0.0005, EDGE - 0.0005] * 10
# Same mean, spread like NOISY. Identical averages, different evidence.
NOISY_SAME_MEAN = [EDGE + 0.8, EDGE - 0.8] * 10


@unittest.skipIf(importlib.util.find_spec("openskill") is None, "openskill not installed")
class ChallengerThreshold(unittest.TestCase):

    def fired(self, *arms):
        from run_weekly import beats_champion
        n = len(arms[0]["ll_series"])
        return [r["name"] for r in beats_champion([champion(n), *arms])]

    def test_a_gap_the_sample_cannot_resolve_does_not_fire(self):
        self.assertEqual(self.fired(arm("noisy", NOISY)), [])

    def test_the_old_flat_margin_would_have_fired_on_it(self):
        """Without this, the test above could pass for the wrong reason.

        It is the discrimination control: the case has to be one the old rule
        reported, or it proves nothing about the change.
        """
        gap = sum(NOISY) / len(NOISY)
        self.assertGreater(gap, OLD_FLAT_MARGIN)

    def test_a_consistent_edge_does_fire(self):
        self.assertEqual(self.fired(arm("steady", STEADY)), ["steady"])

    def test_it_reads_the_paired_spread_not_the_two_averages(self):
        """The control that makes this a paired test rather than a renamed one.

        Both arms sit the same distance below the champion on average, so any rule
        comparing aggregate log-loss must treat them alike. Only one is evidence.
        """
        steady, noisy = arm("steady", STEADY), arm("noisy-same-mean", NOISY_SAME_MEAN)
        self.assertAlmostEqual(steady["log_loss"], noisy["log_loss"], places=12)
        self.assertEqual(self.fired(steady, noisy), ["steady"])

    def test_a_worse_challenger_never_fires(self):
        self.assertEqual(self.fired(arm("worse", [-0.2] * 20)), [])

    def test_no_champion_row_means_no_verdict(self):
        from run_weekly import beats_champion
        self.assertEqual(beats_champion([arm("orphan", STEADY)]), [])

    def test_an_identical_challenger_does_not_fire(self):
        """Zero gap and zero spread. Fires only on a gap, so this must stay quiet."""
        self.assertEqual(self.fired(arm("tie", [0.0] * 20)), [])

    def test_a_gap_with_no_spread_is_certain_and_fires(self):
        """Skipping a zero-variance gap would suppress the clearest case there is."""
        from run_weekly import beats_champion
        out = beats_champion([champion(20), arm("exact", [0.05] * 20)])
        self.assertEqual([r["name"] for r in out], ["exact"])
        self.assertEqual(out[0]["sigmas"], float("inf"))

    def test_the_reported_gap_carries_its_uncertainty(self):
        """The digest prints these, so a wrong unit here is a wrong published claim."""
        from run_weekly import beats_champion
        out = beats_champion([champion(20), arm("steady", STEADY)])[0]
        self.assertAlmostEqual(out["gap"], sum(STEADY) / len(STEADY), places=12)
        self.assertGreater(out["gap_se"], 0)
        self.assertAlmostEqual(out["sigmas"], out["gap"] / out["gap_se"], places=9)

    def test_the_bar_is_the_number_of_standard_errors(self):
        """Loosening min_sigmas must be what admits a borderline arm -- nothing else."""
        from run_weekly import beats_champion
        rows = [champion(20), arm("borderline", [0.06, -0.02] * 10)]
        strict = [r["name"] for r in beats_champion(rows, min_sigmas=99.0)]
        loose = [r["name"] for r in beats_champion(rows, min_sigmas=0.5)]
        self.assertEqual(strict, [])
        self.assertEqual(loose, ["borderline"])


if __name__ == "__main__":
    unittest.main()
