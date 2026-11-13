### `sql/analytics`: the death_group link query uses its indexes again (2026-11-12)

`death_group_link_fact.sql` (schema 39) compared match ids only as
`BINARY a = BINARY b`, which cannot use an index on a `_ci` column. Inside the
correlated `EXISTS` into `hlstats_Events_Frags` that made every assist row scan
the frag table by `serverId`: about 58 million rows and five minutes per report.
`hlstats_Events_Frags` is MyISAM, so for the whole query the stats daemon's frag
`UPDATE` waited on the table lock, stopped reading its UDP socket and dropped
log lines. Every daemon lock wait over a minute since 2026-11-10 ends at the same
instant as one of these queries, including the 2026-11-11 18:05–18:10 ET stall
(314 s wait, 623 datagrams dropped mid-match).

- Each BINARY match-id test now sits beside a plain equality, so the subqueries
  and both outer reads use `idx_frag_producer_context`, `uk_life_boundary` and
  `idx_match_timeline`. The BINARY test is kept, so the result is unchanged.
  Measured on one match: 316.9 s before, under 0.5 s after, identical counts.
- `tests/unit/test_analytics_sql_index_usable.py` fails any correlated `EXISTS`
  into an `hlstats_Events_*` table whose BINARY match test has no plain twin.
