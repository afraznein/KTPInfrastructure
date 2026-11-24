### `tests`: Lane B had no apply position for `migrate_054`, so the migration's own pull request could never go green (2026-11-05)

`plan_schema_files` treats any `sql/migrate_*.sql` present in the daemon ref but listed in neither
`DEFAULT_SCHEMA_FILES` nor `NOT_APPLIED_MIGRATIONS` as a build error. That is deliberate: a migration
the harness has no position for would otherwise be applied in some runs and not others, depending on
list order. The consequence is that adding a migration to KTPHLStatsX fails `corpus-regression` on
every pull request in that repo until this list learns about it, so the migration cannot turn its own
check green and the harness has to move first.

`sql/migrate_054_causal_parent_links.sql` is the one that hit it, in afraznein/KTPHLStatsX#183. It
adds nullable `causal_parent_*_sequence` columns to `hlstats_Events_Frags` and `ktp_assist_events`,
recording which life-end a frag closed and which frag an assist fed.

It goes in `DEFAULT_SCHEMA_FILES` rather than `NOT_APPLIED_MIGRATIONS` because the daemon will write
those columns once the producer leg lands. The not-applied set holds redundancies already in
`ktp_schema.sql` and report-store tables the daemon never writes, and this is neither, so parking it
there would mean moving it again and would leave the harness building a schema that no longer matches
production once the migration is applied.

The ordinal skips 053, which is unused in KTPHLStatsX: a sibling migration staged for the operator
carries 053 in its title only and has landed in no git tree, and taking the same number here would
put two unrelated changes under one ordinal.
