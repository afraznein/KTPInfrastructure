### `scripts`: the corpus-integrity guard asks directly instead of parsing (2026-10-14)

The guard shipped in `#705` pulled a named metric out of `mysql --table` text. **That
cannot work**, and a trial run before it was ever scheduled proved it: the two pinned
reports do not share an output shape. `position_corpus_integrity.sql` is **row-oriented
key/value** — `| 9 | rows_max_id | 6684393 |`, where the metric name is a *value* in a
name column — while `producer_clock_corpus_integrity.sql` is **column-oriented per
stream**. One parser keyed on column names cannot read both.

What it actually produced, which is how it was caught rather than reasoned about:

- `orphan_max_id=9` — while every real `orphan_max_id` cell reads `NULL`. The `9` was the
  **row number** from `| 9 | B2 orphan_half_pairs | 0 |`.
- `epoch_zero_rows=58442` — against a true population of **326,429**.
- The **same watermark** for two different tables.

⛔ It also read a cumulative state count as accrual, which is the exact trap `dpl-570e`
already carries a warning about. On the schedule it would have posted garbage every
morning — and a daily false alarm is how you train everyone to ignore the one real one.

**So the parsing is deleted and the question is asked directly.** Two trivial indexed
`SELECT`s per stream: `COALESCE(MAX(id),0)` for the watermark, and a `COUNT(*)` above the
previous watermark per defect. The predicate is the reports' own, verified against them —
`event_time = FROM_UNIXTIME(0)` returns exactly **326,429** position rows and **2,771**
`flag_state` rows, which are the populations those files and the ledger record.

- **The pinned reports still run — but only on accrual.** A clean day costs two `COUNT`s;
  an accrual day pays for the full definition, which is precisely when its sections,
  controls and watermarks are worth having in the log. That also keeps the daily off the
  position corpus, which the unscoped report scans for minutes.
- **A sentinel now guards the orphan predicate.** An ungranted or empty `ktp_matches`
  turns *every* row into an orphan, so the guard refuses (exit 2, which always posts)
  rather than reporting a corpus-wide false finding — the same thing the `.sql` files halt
  on. Measured live: `ktp_matches has 5105 rows`.
- **The orphan predicate excludes NULL and empty `match_id`.** `rows_match_id_null` is
  72,062 on the position corpus and the reports flag it explicitly *not* a defect; without
  those guards every one would have scored.
- `FROM_UNIXTIME(0)` rather than a literal. It renders `1969-12-31 19:00:00` on this
  ET-clocked server, and hardcoding either that or a UTC literal is how it breaks
  elsewhere.

**Measured against the live box, seeded to current max ids:** `epoch_zero=0 orphan=0` on
both streams, watermarks correctly **distinct** (6,684,393 and 71,683), exit 0, silent,
and it completes in **under a second** against the parsing version's ~6 minutes.

**Tests:** 20 pass. The parser's absence is now itself a regression test — `metric_of` and
`awk` must not reappear, because that failure did not error, it returned the wrong number
for the right-looking metric. Also asserted: the predicates use the function not a
literal, the NULL/empty guards are present, the sentinel refuses in both directions, the
pinned report call sits inside the accrual branch, and cron, logrotate and the health check
all name the same log.

⚠️ **One test failed on its own explanation first** — it forbade the string `1969-12-31`
and the comment forbidding that literal contains it. It now asserts on code lines and
separately asserts the warning comment survives.
