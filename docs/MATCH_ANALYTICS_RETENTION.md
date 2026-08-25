# Match analytics retention

For the complete ordered production rollout, migration, verification, and
rollback procedure, see
[Stats and retention production deployment](STATS_RETENTION_PRODUCTION_DEPLOY.md).

Official KTP, KTP OT, draft, and draft OT analytics are retained permanently.
Scrim (`match_type=1`), 12man (`match_type=2`), and `*-TEST` match analytics
expire after 14 days.

An apply removes every known match-scoped fact before deleting the
`ktp_matches` metadata. This includes the generic HLStatsX event rows plus KTP
damage, captures, flag-ownership state, life boundaries, canonical assists,
match players/stats, and position samples. `ktp_flag_positions` is static
per-server map geometry rather than a match-scoped fact, so it is retained.

For `hlstats_Events_Frags` and `ktp_damage_events`, a non-NULL
`producer_match_id` is authoritative. Buffered delivery can make the legacy
receipt-time `match_id` disagree with the producer context. Retention therefore
deletes producer-scoped rows by `producer_match_id` first and falls back to
`match_id` only when `producer_match_id IS NULL`. The apply log reports those
producer and legacy deletion counts separately so the result remains
auditable.

`ktp-match-retention.py` is dry-run by default. Review candidates with:

```sh
sudo /usr/local/bin/ktp-match-retention.py --days 14
```

The systemd service is the only scheduled apply path. It runs daily at 05:20
UTC with up to ten minutes of jitter. Install the script and unit files, run a
dry-run, then explicitly enable the timer during an approved deployment.

Legacy rows with `match_type IS NULL` are retained. No heuristic backfill is
performed. Test matches remain identifiable by the `-TEST` suffix even though
the contained test driver uses the competitive match state internally.
