### Lane B: untracked capture must resume after a clean match end (2026-11-18)
- New scenario `untracked_capture_resumes_after_match_end`. Right after the report match's
  test-mode end, `KTPAssistDrive` dispatches one self-inflicted hit through the real
  `client_damage` forward (`ktp_ad_postmatch_damage`). The run fails as `pipeline` unless exactly
  one `damage` line for that hit lands between the drive's markers carrying the untracked
  `(matchid "-") (half "0") (sequence "0")`. A drive that aborts or runs outside the
  end-to-next-start window is reported `not_exercised`.
- Real bot damage cannot prove this: the test-mode end pauses DODX stats, so post-match fights
  reach no damage forward, and a zero would read the same with the gate open or shut. Self-damage
  earns no assist credit, so the hit leaves the diagnostic match alone.
- ⚠️ This fails against `stats_logging` 1.39.0 and earlier, which keep the gate shut after any
  context closes until the next match start. Merge the KTPAMXX fix (`stats_logging` 1.39.1)
  first, or the nightly `full` run goes red on this scenario.
