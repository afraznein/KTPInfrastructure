"""Season-boundary continuity rehearsal.

There is only one real season of labeled matches (S9) so far -- nothing to
test a real season boundary against yet. This splits S9 in half
chronologically and treats the split as a STAND-IN season boundary, purely
to validate the widen_at_season_boundary() plumbing end to end and get a
first read on whether it helps before a real second season exists. Not a
claim about real season-to-season behavior -- there's no roster turnover or
skill drift across this fake boundary the way there would be across a real
off-season, so a null result here would not be surprising and a positive
result should be re-checked once S10 provides a real boundary.
"""
import json
from pathlib import Path

from ladder import Elo, OpenSkill, load_matches, metrics


def run(model, season_a, season_b, widen=None):
    for m in season_a:
        model.update(m["t1"], m["t2"], m["y"])
    if widen is not None:
        widen(model)
    preds, ys = [], []
    for m in season_b:
        preds.append(model.predict(m["t1"], m["t2"]))
        ys.append(m["y"])
        model.update(m["t1"], m["t2"], m["y"])
    return metrics(preds, ys)


def main():
    matches = load_matches()
    split = len(matches) // 2
    season_a, season_b = matches[:split], matches[split:]
    print(f"stand-in boundary at match {split} of {len(matches)} "
          f"({season_a[-1]['when']} | {season_b[0]['when']})")

    print("\nOpenSkill sigma-widen factor sweep (season B metrics):")
    for factor in (1.0, 1.5, 2.0, 3.0):
        m = run(OpenSkill(), season_a, season_b,
                widen=(None if factor == 1.0 else (lambda mdl, f=factor: mdl.widen_at_season_boundary(f))))
        print(f"  factor={factor:<4} n={m['n']:<3d} logloss={m['log_loss']:.4f} brier={m['brier']:.4f} acc={m['acc']:.3f}")

    print("\nElo provisional-carryover fraction sweep (season B metrics):")
    for fraction in (1.0, 0.5, 0.25, 0.0):
        m = run(Elo(), season_a, season_b,
                widen=(None if fraction == 1.0 else (lambda mdl, f=fraction: mdl.widen_at_season_boundary(f))))
        print(f"  fraction={fraction:<4} n={m['n']:<3d} logloss={m['log_loss']:.4f} brier={m['brier']:.4f} acc={m['acc']:.3f}")


if __name__ == "__main__":
    main()
