### Write attribution on the deploy tree is now documented where people look (2026-10-06)

`provision/install-distribute-audit.sh` has installed an auditd watch on
`/home/dod/distribute` since 2026-08-27, keyed `ktp-distribute-cfg`. Nothing in
this repo referenced it: not a runbook, not `docs/SERVER_SETUP.md`, not a test,
not a workflow. The two documents a reader actually consults about that path —
the root `CLAUDE.md` and `infrastructure.md` — mention `auditd` zero times each.

So an estate sweep concluded the fleet deploy path had no write attribution at
all and nothing recording a decision against it, while the installer sat in
`provision/`. The near-identical `scripts/audit-distribute-drift.py` makes it
worse rather than better: a grep for `audit-distribute` returns that checker and
its sixteen references, and a drift checker reads plausibly enough as "audit
coverage" that the search stops there.

`docs/runbooks/DISTRIBUTE_DRIFT.md` now carries the read command (with the `-if`
that is not optional — without it `ausearch` hangs on this host and prints
nothing, which is indistinguishable from no writes), the reason neither the
distributor's logs nor sshd's can answer the question, the name collision, and
the installer's own point that there is no harmless way to self-test a rule whose
every trigger is a fleet-wide deploy.

Documentation only. No script, rule, service or host state changes here.
