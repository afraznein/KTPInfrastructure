### Changed
- `--require-complete-coverage` no longer fails the run on `voice_menu_slots`. Ruled 2026-11-03:
  an all-bot lane has never produced a `#Voice_subtitle_*`, so that check can only answer
  `not_exercised`, and the flag made the nightly red on coverage the lane cannot reach. The gap is
  still reported in `report["coverage_gaps"]` and marked **waived** in the step summary; the exit
  code reads the new `report["coverage_gaps_gating"]`, which `lane_b_e2e.gating_coverage_gaps()`
  derives by name from `UNEXERCISABLE_IN_ALL_BOT_LANE`. A `pipeline` verdict on the same check
  still fails the job — the waiver covers `not_exercised` only.
- The exit decision moved into `lane_b_e2e.run_exit_code()`, so the two guards that had asserted
  the source line `args.require_complete_coverage and bool(gaps)` now ask the behaviour instead.

### Documented
- Why a synthetic subtitle was declined rather than deferred, and the two unsettled causes of the
  missing TextMsg — `dod.so` may not emit for a fake-client SPEAKER, or only to non-fake
  RECIPIENTS, which would make this a harness shape and not a coverage floor. In
  `tests/e2e_stats/voice_menu_scenario.py` and `docs/handover/CI_CD_LANE_B.md` § 5.
