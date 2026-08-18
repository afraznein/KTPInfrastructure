# Match analytics retention

For the complete ordered production rollout, migration, verification, and
rollback procedure, see
[Stats and retention production deployment](STATS_RETENTION_PRODUCTION_DEPLOY.md).

Official KTP, KTP OT, draft, and draft OT analytics are retained permanently.
Scrim (`match_type=1`), 12man (`match_type=2`), and `*-TEST` match analytics
expire after 14 days.

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
