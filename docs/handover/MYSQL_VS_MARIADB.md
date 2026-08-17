# Handover: `ktp_schema.sql` does not run on MySQL

**For:** an AI agent or engineer picking this up cold.
**Repo:** `KTPHLStatsX`, file `sql/ktp_schema.sql`.
**Status:** known-broken, documented in its own header, never fixed.
**Risk:** silent. Nothing fails today; it fails the next time someone
provisions a fresh database.

---

## The problem in one paragraph

`sql/ktp_schema.sql` is the KTP schema overlay — it adds `match_id` and `half`
to the event tables and creates the three `ktp_*` tables. It is written in
**MariaDB** syntax. Production is **MySQL 8.0.46**. MySQL rejects the first
offending statement with `ERROR 1064` and, because the file is applied as one
batch, **aborts before every statement after it**.

## Exactly what is wrong

Two MariaDB-only forms, at these lines:

```sql
-- lines 22-43: ADD COLUMN IF NOT EXISTS  (MariaDB only)
ALTER TABLE hlstats_Events_Frags
ADD COLUMN IF NOT EXISTS match_id VARCHAR(64) DEFAULT NULL AFTER map;

-- lines 25-43: CREATE INDEX IF NOT EXISTS  (MariaDB only)
CREATE INDEX IF NOT EXISTS idx_match_id ON hlstats_Events_Frags (match_id);
```

Four tables get the `match_id` treatment — `hlstats_Events_Frags`,
`_Teamkills`, `_Suicides`, `_PlayerActions` — so eight offending statements in
total, at lines 22-43.

`CREATE TABLE IF NOT EXISTS` (lines 61, 85, 104) is **valid in both** and needs
no change.

The `half` columns at lines 51-54 are already plain `ALTER TABLE ... ADD
COLUMN`, and line 48 carries a comment saying MySQL does not support the
`IF NOT EXISTS` form — so someone already knew, fixed half the file, and left
the rest.

## Why nobody has noticed

The fleet's databases were built incrementally. The columns already exist, so
nobody re-runs this file. Its own header names the hazard:

> a FRESH install (LAN data-server provisioning) is where it silently applies
> almost nothing

That is the exposure. The next LAN provision, or any disaster-recovery rebuild,
gets a database missing `match_id` on four tables and missing all three `ktp_*`
tables — and the daemon will run against it happily, writing rows that quietly
lose their match attribution.

## The trap that hid it

Lane B originally used **MariaDB** in its container, because it was the easy
apt package. Under MariaDB the file applies perfectly. A MariaDB-backed test
lane goes **green on exactly the migration hazard it exists to catch**, and
would keep doing so right up until someone provisioned a real server.

The Lane B image was switched to MySQL 8.0.46 for production parity, and the
`ERROR 1064` surfaced immediately. **Do not switch it back**, and do not
"fix" a future failure by loosening the image — see
`build/lane-b/Dockerfile`, which explains this at the `mysql-server` line.

## What "done" looks like

1. `sql/ktp_schema.sql` applies cleanly to an **empty MySQL 8** database.
2. It is still **idempotent** — re-running it on a database that already has
   the columns must not error. This is the whole reason `IF NOT EXISTS` was
   used, and the replacement has to preserve it, not drop it.
3. Lane B's `--apply-ktp-schema` path passes rather than reproducing the 1064.

### The shape of the fix

MySQL 8 has no conditional `ADD COLUMN`. The three usual options, in the order
worth considering:

| Approach | Notes |
|---|---|
| Guard each `ALTER` with a check against `information_schema.columns`, executed via a prepared statement | Verbose but plain SQL, no privileges beyond what the migration already needs. The harness does exactly this in `HlstatsDaemon.repair_reconstructed_schema` — worth reading as a working reference. |
| A stored procedure that loops the checks and `DROP PROCEDURE`s itself | Compact; needs `CREATE ROUTINE`, which the migration account may not have. Check before choosing it. |
| Split into numbered one-way migrations (`migrate_005_...`) and track applied state | Cleanest long-term and matches how `migrate_002/003/004` already work in this repo. Biggest change. |

The third is most consistent with the repo's existing direction. Confirm with
the maintainer before restructuring — the second and third change the operator
runbook, not just the file.

## How to verify without touching production

Lane B gives you a disposable MySQL 8.0.46 with production's real schema:

```bash
# One-off: the ephemeral instance, the production-derived base schema, and
# then the file under test.
scripts/replay_daemon.py \
    --log <any captured game log> \
    --hlstats <daemon tree>/hlstats.pl \
    --schema base-schema.sql sql/ktp_schema.sql \
    --seed migrate_003_assist_action.sql migrate_004_cap_break_action.sql
```

If `ktp_schema.sql` still has the defect, `EphemeralMysql.load_file` raises with
MySQL's own error text attached. See `tests/e2e_stats/README.md` for how to get
`base-schema.sql`.

Test **both** directions, because idempotency is the requirement most likely to
be lost in the fix:

- against an empty database (fresh-install path) — must apply everything
- against a database that has already had it applied — must be a no-op, not an
  error

The second is the one a naive "just remove IF NOT EXISTS" fix breaks, and it is
the path production actually takes.

## Files to read first

| File | Why |
|---|---|
| `KTPHLStatsX/sql/ktp_schema.sql` | the subject; its header already documents the defect |
| `KTPHLStatsX/sql/migrate_002_half_damage_score.sql` | the house style for a migration in this repo |
| `KTPInfrastructure/tests/e2e_stats/hlstats_daemon.py` | `repair_reconstructed_schema` — a working information_schema-guarded ALTER in this codebase |
| `KTPInfrastructure/build/lane-b/Dockerfile` | why the test database is MySQL and must stay MySQL |
| `KTPInfrastructure/scripts/fetch_base_schema.sh` | how to take a fresh schema-only dump of production |

## One thing not to do

Do not make Lane B apply `ktp_schema.sql` by default as part of "fixing" this.
It is deliberately excluded: the production-derived base schema already has
every column it would add, so applying it proves nothing about a normal run and
only re-tests the migration. `scripts/lane_b_local.sh` has an
opt-in (`LANE_B_APPLY_KTP_SCHEMA=1`) for reproducing the failure on purpose.
Keep that shape — the migration deserves its own targeted test, not a
permanent tax on every lane run.
