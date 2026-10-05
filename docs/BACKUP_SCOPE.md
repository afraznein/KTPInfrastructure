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

`/etc/cron.d/ktp-offsite` runs three jobs on Sunday: `ktp-db-offsite.sh` at 04:00,
`ktp-demo-offsite.sh` at 05:00 and `ktp-corpus-offsite.sh --commit` at 06:00 (added 2026-09-25;
it carries the AC weapon-context sidecars as a second source since 2026-10-05, section 1.2).
The first two read `KTP_OFFSITE_HOSTS`, and that variable names **two** provider-diverse hosts we
already own. The most recent run reports every file present on every target.

> 🔑 **The corpus leg is the one that cannot verify its own backup, and that is deliberate.** It
> encrypts every bundle to public `age` recipients before it leaves and holds no private half, so
> it proves the bytes ARRIVED and can never prove they decrypt. `ktp-corpus-drill.sh` is the other
> half and it runs where a key is — **not on this host, not in cron here**. A schedule for the leg
> without a standing owner for the drill is a backup nobody has read. ⛔ **`--commit` is not
> optional in that cron line:** without it the script dry-runs, prints its OK lines and ships
> nothing, which is the exact shape of a backup that reports success while writing no bytes.

> ⚠️ **"Present on every target" is a presence claim, not a content claim.** The Denver/Chicago
> path (`ssh H "... [ -f $DEST/$f ] ..."`, `ktp-demo-offsite.sh`) only asks whether a name exists
> at the destination — a demo truncated mid-copy still satisfies `[ -f ]` and reports as
> transferred. The newer Storage Box path, added when that target turned out to have no shell
> (`ktp-demo-offsite.sh`'s rsync-only branch), verifies with an `rsync -ani --checksum` itemize
> instead: any itemized line is a size/checksum mismatch, and an empty result means every file
> matches byte-for-byte. That is **strictly stronger**, and it exists only because a shell-less
> target forced a different verification method — not because anyone decided the presence check
> was insufficient. The gap is documented inline at `ktp-demo-offsite.sh` (the comment above the
> rsync-only loop) but the two targets still run genuinely different strength checks today.

🔻 **CORRECTED — the archive box is now wired, and this section said the opposite for a month.** It
was **wired to nothing** when this was written: no script, no config, no cron entry, and only the
`.ssh` directory created when access was proven. The shell-less rsync path in section 2 landed
2026-08-28 and gave it the DB dumps and the demo archive; the corpus leg landed 2026-09-25 and it
now holds all three. ⚠️ **A purchased, reachable, EMPTY box reads as "offsite is handled" on every
document that mentions it** — which is why the original sentence led this section, and why the
correction has to be dated rather than swapped in silently.

> ⚠️ **Two copies on hosts we run are not the same protection as one copy outside the estate.** The
> two `KTP_OFFSITE_HOSTS` targets are real and verified. They are also both boxes we administer with
> the same keys and the same habits, so a bad sync, a mistaken `rm`, or a compromised workstation
> reaches both. That is the gap the archive box was bought to close, and for the DB dumps, the demo
> archive and the corpus it now closes it. ⚠️ **What it does NOT close: all three legs land in the
> same sub-account, so one account loss takes all three at once.** Accepted, not overlooked.

### 1.1 What the corpus leg reads from the conf

`/etc/ktp/offsite.conf` is not in this repository and must not be — it names the targets. The corpus
leg adds three variables to it, and this is their shape so the install is recoverable from here
rather than from one box's disk:

```sh
# Its OWN destination directory. The script REFUSES a value equal to the demo or
# DB one: sharing a directory interleaves two archives whose retention and restore
# audiences differ, and the symptom would be no error anywhere. Relative, like its
# siblings -- an absolute path nests a directory inside the sub-account root and
# the backup still looks like it worked.
export KTP_OFFSITE_RSYNC_CORPUS_DIR="ktp-ac-corpus"

# PUBLIC age recipients, whitespace separated. Public keys: safe in the conf and
# safe in a log. TWO, because one key is a single point of PERMANENT loss -- the
# corpus cannot be regenerated, so a lost private half leaves ciphertext that
# decrypts for nobody. A private key here is REFUSED, not ignored.
export KTP_CORPUS_AGE_RECIPIENTS="age1__RECIPIENT_1__ age1__RECIPIENT_2__"

# Local ciphertext cache, one .age per bundle, so it is sized like the corpus.
# Deliberately NOT under the source: a cache inside it would be swept into the
# next selection and re-encrypted forever. The script refuses that too.
export KTP_CORPUS_ENC_CACHE="/var/lib/ktp-corpus-offsite/enc"
```

🔴 **The private halves are the whole design and they are NOT here, NOT on the data server and NOT on
the archive box.** They are the operator's, in two places that do not fail together. ⛔ **Never write
one into this repo, the conf, a log or a ticket** — and note that GitHub's secret scanning matches
registered provider formats only, so it would not stop you.

⚠️ **Real data does something the synthetic drill cannot produce: byte-identical bundles collapse.**
Objects are named for the sha256 of the plaintext, so two bundles with the same content in the same
day-dir share one remote object. The first real run selected 854 bundles and wrote 842 objects, and
both numbers are correct. The restore handles it (it fetches `sort -u` objects and writes every
manifest row). 🔻 **CORRECTED 2026-10-05:** the leg's log line used to call the cache `$COUNT
object(s)` when it held fewer; it now prints the distinct-object count beside the bundle count.
**The drill's `OBJS -eq N` assert would still fail on real data** — it passes only because the
drill's bundles are random bytes, and it never runs on real data.

### 1.2 The second source: AC weapon-context sidecars (added 2026-10-05)

**Operator ruling 2026-10-05:** back up the weapon-context store off-provider, encrypted, through
the corpus leg — same `age` recipients, same Sunday 06:00 run, retention **unbounded** like the
bundles. Before this, `/opt/ktp-ac-api/weapon-context` had no copy anywhere: not in the corpus leg
(bundles only) and not in `ktp-backup.sh`.

🔑 **Why it matters more than its size suggests.** The store keeps each session's weapon timeline as
`<shard>/<session>.weapons.json`. The database rows it is cut from are swept nightly, so **once a
session's rows are gone its sidecar is the only copy** of which weapon was in hand. The files carry
victim SteamIDs, so they get exactly the bundles' treatment: encrypted before they leave, an
encrypted manifest, and counts — never names — in the log.

**Far-side layout.** Its own prefix under the corpus directory, so a bundle restore and a sidecar
restore never read each other's objects. The bundle layout is unchanged:

```
<corpus dir>/<YYYY-MM-DD>/<sha256>.age                                  bundles
<corpus dir>/ktp-corpus-manifest.txt.age                                bundle manifest
<corpus dir>/weapon-context/objects/<sha256-of-plaintext>.age           sidecars, every version
<corpus dir>/weapon-context/ktp-weapon-context-manifest.txt.age         CURRENT versions
<corpus dir>/weapon-context/manifests/ktp-weapon-context-manifest-<UTC>.txt.age
```

⚠️ **Sidecars are rewritten in place, and the far side is append-only.** The API rewrites a
sidecar by rename whenever a later hydrate is more complete. A rewrite has a new hash and therefore
lands as a **new** object, and the old object stays — that is correct for a far side that never
deletes. What says which object is the **current** version of each file is the stable manifest,
rewritten every run from what that run read; a restore reads it and so takes the latest version of
every sidecar. The dated manifests are the only map to the older versions. Two details follow from
the rewriting:

- **The sidecars are copied into the run's work dir before they are hashed.** The writer can replace
  a file between the hash and the encryption, and a hash taken from one version must never name the
  ciphertext of the next.
- **The current manifest is verified on the far side by content**, like the objects. A stale one
  restores old sidecars with no error at all. (The manifest ships with `--ignore-times`: two runs in
  one second write a same-size manifest with the same mtime, and rsync's quick check kept the old
  one — found by the tests, not in production, where runs are a week apart.)

**No new conf variable.** The source defaults to `/opt/ktp-ac-api/weapon-context`
(`KTP_WEAPON_CONTEXT_SRC` overrides it) and the prefix is fixed, so the install is the scripts
alone. ⚠️ **Selection is strict, like the bundles':** only `<digits>/<digits>.weapons.json` one
level deep is copied, the in-flight `tmp/` is never selected, anything else under the store is
**counted in a WARNING and not copied**, and **an empty or missing store fails the whole run before
anything ships** — the same "refuse an empty selection rather than report success" rule. A store
that is switched off will therefore stop the bundle leg too, and that is deliberate: it is the
operator's ruling that this data leaves, and a silent skip is how it would stop leaving.

📌 **Measured 2026-10-05 (counts only):** 121 files, 15,045,625 bytes, every one matching the shape
and 121 distinct sha256, store mode 0750 root. Re-derive before acting.

➡️ **Restore:** `ktp-corpus-restore.sh --set weapon-context --src <archive> --dest <empty dir> --key
<identity>`; `--day` does not apply. **The drill** now builds a synthetic store too, rewrites one
sidecar in place between two runs, and asserts the archive gained exactly one object and that the
restore returns the **current** bytes of every sidecar.

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

1. ✅ **Push script**, in the shape of `ktp-db-offsite.sh`: never deletes, verifies on the remote, and
   treats an empty source as a failure rather than a no-op. *(Demos and DB dumps 2026-08-28; the
   encrypted corpus leg 2026-09-25.)*
2. ✅ **Seed and verify the retain set byte-exact on the far side** — verify by listing and hashing what
   arrived, never by a clean exit code. *(Corpus: seeded and checksum-verified 2026-09-25, and a
   sample day pulled back, decrypted and diffed against source. Demos: still the size+mtime claim.)*
3. ⬜ **Turn on the archive box's automatic snapshots** before anything is deleted anywhere.
4. ⬜ **Only then** the `12man`/`scrim` retention pass.
5. ⬜ Runbook.

🔑 **One item this list never had, and the corpus leg makes unavoidable: a standing owner for the
restore drill.** Nothing scheduled anywhere decrypts, by design, so a wrong recipient or a lost
identity file stays invisible until the corpus is needed. ⛔ **It cannot be cron'd on the data server**
— that would put a private key on the one host the design keeps it off. It is a quarterly act on the
machine that holds a key.

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
