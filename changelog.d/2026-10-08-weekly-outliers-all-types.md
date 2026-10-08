### `monitoring`: the weekly outlier report covers every match type and answers four more questions (2026-10-08)

`scripts/weekly_outliers.py` (2026-10-05) scored official halves only. Scrims and 12-mans are
where most of the league's halves are (7,854 player-halves since 09-13 across all types vs 942
official), and where a player's connection shows first.

- **Every match type by default** (`--types` narrows it). The type is a column in every table,
  so a scrim half and an official half sit side by side against the same player baseline.
- **Short-term movers**: each player's last `--change-days` (14) against their own earlier
  halves on jitter-worst share, drops-worst share, on-target rate and kills/100 shots, in units
  of their own earlier spread. Chronic never shows here; a relapse or a fix does. First run
  named a player at 47% jitter-worst for two weeks from 0% before.
- **Servers, within-player**: each player's mean on a server minus their mean across all their
  servers, averaged per server. Who plays where cancels out — the raw per-server average puts
  New York last because it hosts the far teams, while within-player every box sits inside
  ±3 points. A box that starts degrading shows as a trend, not a feeling.
- **`--pick-server a,b,c`**: rank the servers for a given roster by each player's own measured
  ping there (worst player first, then mean), naming who the worst ping belongs to and which
  players have no history on a box. League-wide the boxes are within 2 ms of each other
  within-player; the same box is 15–28 ms better for one player and worse for another, so
  "best location" only has an answer per roster. This is that answer.

All types takes ~3 min on the data server (the registration join over the AC fires ledger);
still well inside a Monday-morning timer.
