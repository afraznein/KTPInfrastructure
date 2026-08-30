# Runbook: which `ktp-scheduled-restart.sh` is authoritative

**What:** the three copies of the 03:00 restart script, what each has that the
others do not, and which one a change goes into.

**When:** before editing any of them. They are not one file with drift; they are
separate lineages, and both of the obvious ways to "just sync them" destroy
something.

**This document changes nothing on the fleet.** Everything below was measured on
**5 of 5 game hosts** on 2026-08-27, and every count names the hosts it came from.

⛔ Deploying any restart script is a separate, explicitly-approved act. The
scheduled script *is* the `0 3 * * *` cron on all five hosts.

> The **manual** script, `~/restart-all-servers.sh`, is a different problem with
> its own procedure — see [`FLEET_MANAGEMENT_SCRIPTS.md`](FLEET_MANAGEMENT_SCRIPTS.md).
> A short summary of where the fleet stands on it is at the bottom of this page.

---

## The three lineages

**L1 — the fleet.** `~/ktp-scheduled-restart.sh`, **one md5 across 5 of 5
hosts**, redeployed 2026-08-27 04:27. Carries the live relay `AUTH_SECRET` and
channel IDs, derives its instance list at run time from `~/dod-*`, and carries
#164's swap-failure escalation.

**L2 — the gitignored working copy.** `scripts/ktp-scheduled-restart.sh`, ignored
`@secret` because it holds the live relay secret. **It is not a canonical.** It
stopped tracking anything on 2026-08-04: no #164, and a relay secret that does
not match what the fleet runs.

**L3 — the tracked `.example`.** `scripts/ktp-scheduled-restart.sh.example`.
Structurally the **most complete** of the three — #164's escalation *and* the
warmup/LAN work that never went to the fleet — with three placeholder values.

## Why both obvious syncs are destructive

- **L2 → fleet reverts #164.** The named unswapped files, the forced-off-green
  Discord embed and the non-zero exit all disappear, restoring the silent "restart
  complete, all green" outcome while a wave sits half-applied. It also installs a
  relay secret the fleet is not using.
- **L3 → fleet blanks the relay secret and both channel IDs**, so the 03:00
  notification stops and nothing else about the restart looks wrong. This is why
  #164 was deployed as a delta against the live script's own anchors rather than
  by copying `.example`.
- **Fleet → L3 deletes the warmup work.** This is the one that is easy to talk
  yourself into, because it sounds like "make the repo match reality". `.example`
  is *ahead* of the fleet, not behind it; regenerating it from a host would drop
  the warmup legs, the relay-blank guards and the `SWAP_BASES` refactor — a
  replay of the 2026-08-04 regression its own header was written to prevent.

## They disagree on names, so a hunk-level merge pairs unrelated lines

| Concept | L1 (fleet) | L2 (gitignored) | L3 (`.example`) |
|---|---|---|---|
| verify denominator | `NUM_SERVERS` | `EXPECTED_RUNNING` | `EXPECTED_RUNNING` |
| swap target list | inline `BASE=~/dod-$port/serverfiles` | `SWAP_BASES` array | `SWAP_BASES` array |
| unswapped-file record | `SWAP_FAILED_FILES` | *(absent)* | `SWAP_FAILED_FILES` |
| warmup instance | *(absent)* | `WARMUP_DIR` / `WARMUP_PRESENT` | `WARMUP_DIR` / `WARMUP_PRESENT` |

## The reconciled shape: L3, unchanged

`.example` already **is** the union. The fix is not a new script — it is to stop
treating L2 as a lineage. L2 becomes what its ignore tag says it is: a local
working copy, regenerated from L3 by filling three placeholders.

That L3 loses nothing relative to L1 is checkable, and was checked. Every hunk L3
has and L1 lacks is inert on a fleet host as it stands:

- **Warmup legs** are gated on `[ -d "$WARMUP_DIR" ] && [ -x … ]`, and
  `/srv/ktpdata/warmup` is **absent on 5 of 5 hosts**, so `WARMUP_PRESENT` is 0
  and every warmup leg is skipped. Warmup is a LAN-box instance.
- **`EXPECTED_RUNNING`** is `NUM_SERVERS + WARMUP_PRESENT`, which at
  `WARMUP_PRESENT=0` is the same number L1 compares against under another name.
- **`SWAP_BASES`** holds exactly the per-port `~/dod-$port/serverfiles` L1 builds
  inline, and the `port=$(basename …)` derivation reproduces L1's `[27015]` label.
- **Relay-blank guards** (`[ -z "$RELAY_URL" ] && return 0`) never fire: the relay
  URL is set on 5 of 5. They exist for the LAN box, where provisioning blanks it.
- **`\\n` vs `\n` in `FINAL_DESC`** produce the same two characters — inside
  double quotes bash only treats a backslash as special before ``$ ` " \`` and a
  newline. Verified, not assumed. L1 uses both spellings; L3 uses one.

So **filling L3's three placeholders with a host's existing values yields a
script that behaves identically to what that host runs today.** L2 has nothing
L3 lacks.

## Blast radius of deploying L3

| Host | Behaviour change at the next 03:00 |
|---|---|
| Atlanta, Dallas, Denver, New York, Chicago | **None.** Every added hunk is gated off on a fleet host, and `EXPECTED_RUNNING` resolves to the value the `NUM_SERVERS` it replaces already had. |

Real but latent: the fleet gains the legs it would need if a warmup instance were
ever added, and stops being a fourth lineage. The single thing that must not go
wrong is the fill — a deploy that leaves `YOUR_AUTH_SECRET_HERE` in place ends the
Discord notification silently.

## Regeneration direction

**L3 is the source of truth. L2 is derived from it.** Fill `AUTH_SECRET`,
`CHANNEL_KTP` and `CHANNEL_EXTERNAL`; change nothing else. The 2026-08-04 header
asserted the opposite direction, which is how the tracked file ended up ahead of
the thing it claimed to be a copy of.

## Detecting the next divergence

`scripts/ktp-restart-drift.py` — read-only, reads four files per host, writes
nothing, touches no server.

```bash
KTP_AUDIT_FLEET_CONFIG=/etc/ktp/audit-fleet.json python3 scripts/ktp-restart-drift.py
```

- The scheduled script is compared against `.example` with the **values** of
  `AUTH_SECRET`, `CHANNEL_*`, `RELAY_URL` and `EDIT_URL` masked on both sides, so
  no secret leaves the host and a rotation does not read as drift. Placeholders
  left in a deployed copy are reported separately.
- The manual script is checked by **property** after comments are stripped, never
  by string. `install-linuxgsm.sh`'s own warning comment contains `((running++))`
  once, so a literal grep reports the correct generator as broken — and the same
  trap once let a buggy host read as fixed, because the strings a note happened to
  name were the *other* variant's spelling.
- Hosts reached is printed beside every count, and an unreachable host is a
  failure rather than a skip. A sweep that silently drops a connection otherwise
  renders as a clean fleet.

---

## Where the manual script stands (context only — procedure lives elsewhere)

`~/restart-all-servers.sh`, measured the same day: **two variants, neither the
repo's.** Atlanta/Dallas/Denver share one md5, New York/Chicago another, and the
generator on `main` emits a third that no host runs. Every copy dates from
February–March 2026. `~/status.sh` exists on **2 of 5** (New York, Chicago).

`main`'s emission was re-derived rather than taken from a table — a sandboxed
`HOME` with `--regen-management-scripts` reproduces the pinned
`a7d23d9f46ed98b69badf736f85ad8ff` and `afa1dac15367b8dcad98598a852d86e0` exactly.

Procedure, rollback and the reasoning behind both fixed bugs:
[`FLEET_MANAGEMENT_SCRIPTS.md`](FLEET_MANAGEMENT_SCRIPTS.md).
