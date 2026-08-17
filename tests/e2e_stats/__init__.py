"""End-to-end stats-capture lane (Lane B) — bots play, MySQL is asserted on.

Separate package from `tests/integration/` on purpose. That suite is the
merge-gating, deterministic lane; this one is bot-driven, non-deterministic,
and must never gate a merge. Keeping them in one directory would invite a
nightly flake into the required status check.

See `tests/integration/STATS_CAPTURE_E2E_DESIGN.md` for the design and
`tests/e2e_stats/README.md` for setup.
"""
