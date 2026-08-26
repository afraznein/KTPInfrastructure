# Backup scope — what actually has to leave the data server

A backup whose scope was never enumerated is a restore that discovers what it is missing. This
document is the enumeration, and it precedes the pusher rather than following it: building a push
script against a number someone sampled quietly defines the surface as whatever they happened to
measure.

Everything below is measured on the data server (2026-08-25) with a positive control on every probe.
Sizes are `du -sb`, counts are `find -type f`. **Re-derive before acting.** A path that does not
exist reports ABSENT here rather than contributing a silent zero — a wrong path returns a clean zero
that is indistinguishable from "there is nothing there", and that is the failure mode this whole
document exists to avoid.

No host addresses or credentials appear here. Targets come from `/etc/ktp/offsite.conf`; the scripts
refuse to run with them unset.

---

## 1. What is actually wired today

`/etc/cron.d/ktp-offsite` runs two jobs on Sunday: `ktp-db-offsite.sh` at 04:00 and
`ktp-demo-offsite.sh` at 05:00. Both read `KTP_OFFSITE_HOSTS`, and that variable names **two**
provider-diverse hosts we already own. The most recent run reports every file present on every
target.

The archive box bought for exactly this purpose is **wired to nothing**. Nothing on the data server
references it — no script, no config, no cron entry — and it holds only the `.ssh` directory that
was created when access was proven. Access itself is fine; a purchased, reachable, empty box reads
as "offsite is handled" on every document that mentions it, which is why it is stated here first.

> ⚠️ **Two copies on hosts we run are not the same protection as one copy outside the estate.** The
> two current targets are real and verified. They are also both boxes we administer with the same
> keys and the same habits, so a bad sync, a mistaken `rm`, or a compromised workstation reaches
> both. That is the gap the archive box was bought to close and has not closed yet.

## 2. Why "add it as a third target" does not work

The obvious fix is to append the archive box to `KTP_OFFSITE_HOSTS`. **Measured: it breaks both
scripts,** because the loop body is not one rsync line. Each iteration runs three things over SSH,
and the archive box answers on a **restricted shell** that accepts a single command and nothing else.

| Loop step | Form used today | On the archive box |
|---|---|---|
| create the destination | `ssh H "mkdir -p '$DEST'"` | **works** |
| copy | `rsync -a --files-from=… SRC/ H:DEST/` | works, but needs a non-default port, key and `-4` |
| verify (db) | `ssh H "cd '$DEST' && md5sum \$(cat)"` | **fails** — `Command not found`, rc 8 |
| verify (demos) | `ssh H "cat > /tmp/…; while …; [ -f … ]"` | **fails** — same |

`md5sum` and `mkdir` exist there and work fine **as single commands**. It is the compound — `cd X &&
…`, `[ -f … ] && …`, `a; b` — that the shell rejects.

⛔ **The dangerous half is that it does not always reject.** A compound whose *first* token is a
permitted command runs that command, silently discards the rest, and exits **0**. `cat > /tmp/x;
echo done` returned rc 0, wrote nothing, and printed neither "done" nor an error. So a naive third
target would not fail loudly — the db script would report every dump "missing or corrupt on arrival"
(a false alarm), while a verification step written in the wrong shape could report success having
checked nothing.

Three further constraints, all measured:

- **Every connection must force IPv4.** The box publishes A and AAAA records; this data server has an
  IPv6 default route and zero global IPv6 addresses, so the resolver hands back the AAAA and the
  connection fails. It presents as "DNS broken", then "ports filtered", then "external reachability
  not enabled" — all three wrong.
- **The key authenticates on the rsync/SSH port and is rejected on port 22.** Placing
  `authorized_keys` in the sub-account home enables the former only; port 22's key store is
  console-managed. The symptom is `Permission denied (publickey,password)` on one port while the
  other authenticates in the same second, which reads as an intermittent key fault and is not one.
- **The destination is the sub-account's own root, `:./`.** Spelling it as an absolute path creates a
  nested directory inside that root and the backup looks like it worked. Confirmed: the sub-account
  is confined — `ls ..` returns Permission denied — and its root is the same directory the main
  account sees one level down, so `pwd` reports the same string for two different directories.

➡️ **The archive push is therefore a separate script, in the shape of `ktp-db-offsite.sh`:** rsync
over the dedicated port with `-4` and the dedicated key, far-side verification issued as **one
`md5sum` invocation with many arguments** (permitted, and one round trip instead of N on a ~100 ms
link), never deleting, and an empty source treated as a failure rather than a no-op.

⚠️ **Automatic snapshots on the archive box are still off.** Until they are on, the sub-account can
delete its own files, and the append-only property the box was chosen for does not exist. A verified
copy that a bad sync can overwrite is a second copy, not a second *generation*.

## 3. The surface

### 3.1 Demos — the large half

The archive is organised by **host directory** at the top level (`ATL1`…`NY5`, plus
`LAN-PHILLY2026`), with match type as a subdirectory. Aggregated by type across the whole tree:

| Type | Files | Size | Ruling |
|---|---:|---:|---|
| `12man` | 1,051 | 81.01 GiB | discard |
| `scrim` | 497 | 40.69 GiB | discard |
| `ktp` / `ktpOT` | 358 | 26.82 GiB | **retain** |
| `draft` | 46 | 2.62 GiB | **retain** |
| **all `.dem`** | **1,952** | **151.14 GiB** | |

The retain set is the union of "league demos anywhere" and "everything under `LAN-PHILLY2026`", not
the sum of those rows — the LAN directory contains its own `ktp` and `draft` subdirectories, so
adding the two figures double-counts roughly 13 GiB.

| Retain set | Files | Size |
|---|---:|---:|
| league (`ktp`/`ktpOT`) ∪ all of `LAN-PHILLY2026` | 556 | 35.20 GiB |
| …including standalone `draft` | 563 | 35.43 GiB |

🔻 **A previously-circulated figure of ~49.5 G for this set is the double-counted sum.** It is not a
different measurement of the same thing; it is the same demos counted twice.

### 3.2 What the deployed demo job selects, and what it misses

`ktp-demo-offsite.sh` selects league demos plus everything recorded inside a LAN window read from the
database. Today that is **464 files / ~33 GB**, against a ruled retain set of 563 / 35.43 GiB. Two
gaps, both structural rather than accidental:

- **It matches `*.dem` only.** `LAN-PHILLY2026` holds **102 non-demo files totalling 2.91 GiB** — 90
  player-upload archives, the event photos, and the generated index pages. **None of it is in any
  offsite copy.**
- **Standalone `draft` demos outside a LAN window are not selected**, although the retain ruling
  keeps them.

### 3.3 Everything else

| Path | Files | Size | Offsite today? |
|---|---:|---:|---|
| AC upload archive | 465 | 0.90 GiB | **no** |
| LAN metadata archive (see below) | 602 | 443.30 MiB | **no** |
| DB dumps (+ `configs_*.tar.gz`) | 17 | 0.59 GiB | yes |
| HLTV configs (per-port + the shared base one level up) | 80 | 29 KB | **no** |
| nginx vhosts | 18 | 56 KB | **no** |
| TLS material | 76 | 129 KB | **no** |
| systemd units and timers (local) | 63 | 42 KB | **no** |
| `cron.d` | 23 | 20 KB | **no** |
| `/etc/ktp` (the offsite/relay conf) | 19 | 13 KB | **no** |
| `/usr/local/bin` (the operational scripts) | 82 | 1.2 MB | **no** |
| admin bot | 2,956 | 0.06 GiB | **no** |
| `lan-web` | 3,433 | 0.09 GiB | **no** |
| `support-web` | 3,094 | 0.07 GiB | **no** |
| bundles docroot | 15 | 0.7 MB | **no** |
| file distributor (config + key) | 39 | 0.15 GiB | **no** |
| `/home/dod/distribute` (live deploy path) | 4,108 | 1.21 GiB | **no** |

The bottom half of that table is small enough that arguing about it costs more than copying it. The
config, unit, cron and script paths together are under 2 MB and are the difference between rebuilding
this host in an afternoon and reverse-engineering it.

⚠️ **`/opt/ktp-ac-api` (8.93 GiB) and `hud-observer` (3.04 GiB) are mostly application payload**, not
state. Back up their configuration and data, not their trees, and decide that deliberately rather
than by whether a `du` number looked alarming.

### 3.4 The LAN metadata archive

`philly-2026` under the LAN archive path: **443.30 MiB, 602 files, zero demos.** It holds the
source-side and destination-side md5 manifests, the demo index, match windows, team and clan-tag
maps, the LAN database dump, and the console logs.

🔑 **It matters far more than its size suggests: it is the only surviving record of what the 2026-08
reclaim removed.** The demos it indexes are gone from this host and reachable only from a box that
will not boot. Losing the manifests turns "we know exactly which 1,668 files went, and their
checksums" into "some demos used to exist".

📌 It **is** present at that path. A search by filename pattern (`*manifest*`) does not find it,
because nothing in it is named "manifest" — that is a fact about the probe, not about the archive.

## 4. Deliberately excluded

- **`12man` and `scrim` demos** — the discard half of the retention ruling, and the fast-growing half.
- **Extracted replay bundles, analysis intermediates and scratch directories** from the AC corpus.
  Only top-level example archives are ever published; the rest may carry detection thresholds. Do not
  "complete" an upload by adding them.
- **The code-signing passphrase file.** It sits in plaintext beside the `.pfx`. Any encrypted bundle
  that includes it makes the encryption decorative.

## 5. Order of work

1. **Push script**, in the shape of `ktp-db-offsite.sh`: never deletes, verifies on the remote, and
   treats an empty source as a failure rather than a no-op.
2. **Seed and verify the retain set byte-exact on the far side** — verify by listing and hashing what
   arrived, never by a clean exit code.
3. **Turn on the archive box's automatic snapshots** before anything is deleted anywhere.
4. **Only then** the `12man`/`scrim` retention pass.
5. Runbook.

⛔ **Nothing is deleted until the keep-set is verified on the far side.**
⛔ **Retention keys on type and date, never size.** Demo size tracks duration, so a size filter
deletes real matches.

## 6. Provider diversity, since it is the point

A copy is only diverse if it lands somewhere the primary provider cannot lose. Most of the estate —
including the data server itself — is with one provider whose terms state it keeps no backups and
offers no compensation for lost data. A second box there protects against a disk, not against an
account.

⚠️ **`sys_vendor` identifies the provider only on virtual machines**, where it reports the
hypervisor. Every baremetal here reports its motherboard maker, so that probe is useless on four of
the six hosts. Identify a baremetal's provider by IP block or whois.

⚠️ **A copy nothing refreshes is not a backup.** The AC replay corpus spent four days being described
as a provider-diverse backup while its sync tool was download-only and no writer existed. **Derive
freshness from the directory mtime**, which stays readable even where the contents are not, and state
for every copy *what writes it and how often*. As of 2026-08-25 that corpus is still refreshed by
hand: its host carries no cron entry and no unit for it.
