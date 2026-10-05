### `monitoring`: every official player-half is ranked weekly against the player's own history (2026-10-05)

kroD-'s 10-kill half on `1791141012-NY2` (anzio, 2026-10-04) took a day of hand queries to
reduce to "worst MP44 half, inside his own variance; the server's own traces say 14.8% of
his shots were on a hitbox against his usual 19–26%, and the traced hits registered at his
normal rate — aim, not registration". Coordination `infra-weekly-outliers` is the lane; the
questions asked by hand that day are the metrics here.

- **`scripts/weekly_outliers.py`** scores every official player-half since the season floor on
  kills per 100 shots, server-traced on-target rate, traced→registered rate, hs%, damage per
  shot and deaths, plus ping and the share of 10 s windows where the player was the server's
  worst client for jitter, latency, drops and rewind misses. Each gets a z against the player's
  own other halves (leave-one-out, league spread blended in as 4 pseudo-halves so a five-point
  baseline cannot manufacture z=11 — it did, on the first run) and against every half on that
  map. Halves in the window are ranked by their largest own-z; matches get a line (players
  below their own hs%, where the match's hs% sits among all halves, mean on-target z).
  Shots come from `ktp_ac_weapon_fires`, which exists for every official match and matches
  `ktp_shot_events` exactly where both exist. Read-only over the local socket, no credentials.
- **`ktp-weekly-outliers.timer` / `.service`** run it Monday 06:00, keep `latest.md` and a
  dated copy under `/var/lib/ktp-weekly-outliers/`, and exit 1 when a half scores at or above
  `--alert-z` (3.0) so the existing `OnFailure` wiring carries the week's outliers to Discord.
  The timer joins `CRITICAL_TIMERS` and both units are in `ALERT_COVERAGE.md`.
- Known limits, recorded in the lane: `ktp_net_intervals` keeps only the worst client per
  window, so there is no per-player jitter series; shot-detail traces are off for officials
  (ruled ON from the next league night); `ktp_ac_weapon_hits` omits killing blows, so the
  registration column is a per-player relative signal, never a rate.
