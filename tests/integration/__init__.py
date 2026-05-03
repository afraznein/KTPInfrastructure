"""KTP Tier 2 match-flow integration tests.

Boots hlds_linux with a test-mode KTPMatchHandler.amxx (-DKTP_TEST_MODE
build, see KTPMatchHandler/CHANGELOG.md § 0.10.122) + KTPWitness.amxx
(this directory's `witness/`) and exercises the match-flow state machine
via `amx_ktp_test_*` RCON commands. Asserts on:

- log_ktp event= lines (state transitions: TEST_SETUP, PENDING_BEGIN,
  TEST_ADVANCE_LIVE, etc.)
- KTPWitness.amxx's witness.jsonl rows (proof that ktp_match_start /
  ktp_match_end forwards actually fired and reached a downstream
  consumer — same forward-dispatch path KTPHLTVRecorder uses in prod)
- amx_ktp_test_get_state JSON output (matchType, currentHalf, matchLive,
  matchId, scores, etc.)

See README.md for run instructions + environment requirements.
"""
