### `ci`: the Lane B nightly tests `main`, and the dead preprod tag path is retired (2026-10-05)

KTPAMXX and KTPHLStatsX deleted `preprod` on 2026-10-05 (tips tagged `archive/preprod-20261005`), and
the scheduled Lane B run hardcoded `target_ref: preprod`, so it failed at "Checkout KTPAMXX at the
ref under test". Operator ruling 2026-10-05: the schedule now tests `main`. The `lane-b-preprod-*`
tag trigger, its five-run series fan-out and the `compare-series` job are removed — every component
ref that path resolved to is gone. `matchhandler_ref` defaults to `main` on both entry points, and
the dispatch defaults for `amxx_ref` / `daemon_ref` move to `main` for the same reason. The cron
comment no longer claims the run never overlaps Tier 2: GitHub starts scheduled runs hours late.
