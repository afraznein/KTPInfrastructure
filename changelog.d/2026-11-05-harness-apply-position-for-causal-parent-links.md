Lane B's schema builder now has an apply position for `sql/migrate_054_causal_parent_links.sql`.

`plan_schema_files` treats any `sql/migrate_*.sql` in the daemon ref that is listed in neither
`DEFAULT_SCHEMA_FILES` nor `NOT_APPLIED_MIGRATIONS` as a build error, so the migration opened in
afraznein/KTPHLStatsX#183 fails `corpus-regression` on every pull request there until it is
registered here. That is the gate working as intended: a migration the harness has no position for
would otherwise be applied in some runs and not others, depending on list order.

It goes in `DEFAULT_SCHEMA_FILES` rather than `NOT_APPLIED_MIGRATIONS` because the daemon will write
these columns once the producer leg lands. The three entries in the not-applied set are either
redundancies already in `ktp_schema.sql` or tables the daemon never writes, and this is neither.

The ordinal skips 053, which is unused in KTPHLStatsX. A sibling migration staged for the operator
carries 053 in its title only; taking the same number in git would put two unrelated changes under
one ordinal.
