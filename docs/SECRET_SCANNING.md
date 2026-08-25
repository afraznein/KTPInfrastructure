# Secret scanning

Value-based credential scanning for the KTP repos, and the anti-rot properties that
keep it honest.

## Why this exists

On 2026-08-06 the data-server root password was committed into two `lan-stats`
scripts alongside the host address. On 2026-08-09 it was removed from the tip. The
removal took it out of `HEAD`; it did not take it out of history, and the parent
blobs stayed reachable from `origin/main` on a **public** repository.

Two protections were already switched on and neither fired:

- **GitHub secret scanning** and **push protection** are both enabled here. They
  match *registered provider formats* — AWS keys, GitHub tokens, Stripe keys. A
  ten-character random password has no such format, so it passed. The repository
  security tab reads "protected" the whole time, which is worse than nothing
  reading at all.
- The `.gitignore` credential list is filename-based. The leak was in a **new**
  file no rule had ever named.

The gap both share: they look for things that *look like* secrets. This scanner
looks for the **actual values**.

## The contract

> A clean result must carry proof it could have been dirty.

`clean` is never inferred from "found nothing". Exit 0 requires **all** of:

1. the canary was found in **every** file format the walker claims to read,
2. the inventory loaded and holds at least one live value,
3. the scan scope enumerated to something non-empty.

Any of those failing is **exit 2**, deliberately not exit 0. A probe that cannot
fire must never read as a passing gate — that is how a test gate with a hardcoded
import path reported ALL PASS on a branch it never opened, and how
`ktp-verify-deploy.py` reported green on an identically-wrong fleet.

| Exit | Meaning |
|-----:|---------|
| 0 | clean, and every self-check passed |
| 1 | findings, or an ignore tag that no longer says something true |
| 2 | **BROKEN** — the scan proves nothing; do not treat as a pass |
| 9 | usage error |

## The inventory

Never lives in this repo. Resolution order:

```
$KTP_SECRET_INVENTORY   →   ~/.ktp/secret-inventory.txt
```

One `tag<TAB>value` per line; `#` comments and blanks ignored.

| Tag | Meaning |
|---|---|
| `live` | authenticates something today. A leak means **rotate**. |
| `retired` | no longer authenticates, but still marks a commit as having leaked. **Stays forever.** |
| `hostinfo` | fleet address or topology. Not a credential; still not for a public repo. |

Rotation is a one-line edit here and nowhere else. That is the same lesson
`ktp_hosts.py` already carries in its docstring: every helper used to hold its own
copy of the fleet password, and when it rotated, `deploy_ac_ini_fleet.py` sat
broken for ten weeks because `AuthenticationException` reads like a host problem.

⚠️ **A scan is only as complete as the inventory.** A live credential missing from
it is a blind spot no amount of scanning finds. When you add a credential class
anywhere in the estate, add it here in the same change.

## The four surfaces

Each surface differs in *who can hold the values*, which is why one tool cannot
cover all four the same way.

### 1. Pre-push hook — workstation, full recall

```bash
make secrets-install-hooks
```

Scans the **commit range being pushed**, not staged content. That distinction is
the whole point: the leak entered on 08-06 and left the tip on 08-09, and a
staged-content hook would have waved through every push in between.

The hook blocks on exit 1 **and** exit 2. `git push --no-verify` bypasses it and
leaves no record, so say why in the PR if you use it.

Hooks do not travel with a clone — a fresh checkout is unprotected until someone
runs the installer. That is a rot mode, and the CI gate below is the backstop that
does not depend on anyone remembering.

### 2. CI — `.github/workflows/secret-scan.yml`

Required check, **no `paths:` filter**. Every other workflow here narrows its
triggers so unrelated refactors don't pay the round-trip; this one must not. A
path filter turns the gate into a check that silently passes on exactly the commit
that put a secret somewhere nobody predicted.

The inventory arrives as the `KTP_SECRET_INVENTORY` repository secret.

⚠️ **Fork PRs get no secrets.** GitHub withholds them from `pull_request` runs
originating in a fork, so the scan there loads no inventory and reports BROKEN
rather than a false green. A maintainer re-runs from a branch on this repo. Do
**not** "fix" this with `pull_request_target`, which would hand a fork's code the
inventory.

### 3. Retroactive sweep — every repo, every ref

```bash
make secrets-history
```

Catches what has already landed, and repos created after the hooks were written.
Enumerate repos live (`gh repo list`), never from a list in a file — a hardcoded
scope goes stale the first time someone creates a repo.

Baseline, swept 2026-08-18 across every local repo and ref with a validated
positive and negative control: one hit, the known `lan-stats` leak. Nothing else
in the estate.

### 4. Live hosts

Ignored files exist on the servers, and the `.gitignore` names the scenario
directly: *"a `git add` from a data-server checkout would have published the
webhook."* The check is — per host, find git checkouts, then list files that are
**untracked and not ignored**.

Measured 2026-08-18, with `find` validated by a positive control on each host
(`dodserver.cfg`: 15 per five-instance host, 12 on Chicago's four) and a negative
control returning zero:

- **Exactly one checkout across the fleet** — the tier-2 runner work dir on the
  data server, `/opt/ktp-tier2-runner/actions-runner/_work/...`.
- Its untracked entries are CI artifacts (`.tier2/`, `allure-results/`,
  `tier2-report.json`). No persisted push credential (`extraheader` absent).
- No checkouts on any of the five game hosts.

⚠️ Also watch `/home/dod/distribute/` — `ktp-file-distributor.service` pushes
anything created there to all 24 instances within ~15s. It is a deploy path, not a
staging area.

## The `.gitignore` credential tags

Rules withheld for secrecy, topology or privacy live in one tagged region and are
checked by `make secrets-audit`.

| Tag | Claim | How it is checked |
|---|---|---|
| `@secret` | file exists and carries credential values | must contain an inventory value |
| `@hostinfo` | file exists, carries fleet addresses, no credential | must contain a `hostinfo` value |
| `@guard` | file is **absent**; the rule exists so it can never be added | must **not** exist; needs `# why:` |
| `@privacy` | exists, no credential, withheld for a stated reason | needs `# why:` |
| `@local` | local stub or runtime artifact, no secrecy claim | — |

🔑 **A rule matching an absent file is doing its most valuable work, not its
least.** Five rules were commented out on 2026-08-18 for naming files that no
longer existed locally; two of those files had been deleted *precisely because*
they carried secrets, which made them the highest-value guards. `@guard` exists so
that judgement is never made by hand again.

🔑 **The way to shrink the list is to refactor**, as
`monitoring/ktp-server-monitor.py` did — it now resolves its rcon password at run
time, carries no secret, and is tracked. Deleting lines is not the same thing.

⚠️ **A tag must be its own line.** In `.gitignore` syntax `#` only opens a comment
at the **start** of a line, so `deploy/.env  # @guard` folds the comment into the
pattern and the rule silently stops matching anything.

⚠️ **Existence checks are worktree-local.** Ignored files are untracked by
definition, so a fresh clone or CI checkout holds none of them and every `@secret`
would read as "absent → retag `@guard`" — advice that is wrong everywhere the
files actually live. CI passes `--structure-only`; the content half runs on the
operator's box. If content mode finds that *none* of the tagged files exist, it
reports BROKEN rather than emitting a wall of false errors.

### Warnings vs errors

**Errors** fail the build — they are claims the repo can disprove on its own: an
untagged pattern, a `@guard` whose file exists, a missing `# why:`, a `@secret`
that is absent.

**Warnings** do not fail by default, because clearing them needs an inventory this
repo must never contain — chiefly "`@secret` X holds no inventory value". Run with
`--strict` once the inventory covers every credential class, and CI holds the line
from then on.

## Anti-rot properties

Each of these exists because of a specific way a check here has previously gone
quiet.

**The canary, one per format.** A planted fake value in `.py`, `.json`, `.ini`,
`.sh`, `.yml`, `.md`, `.conf`, `.cfg`. Every run must find all of them, and a miss
names the format. If someone swaps the matcher for something that cannot see JSON,
the build breaks instead of the scan quietly narrowing. `CANARY_FORMATS` is the
coverage claim; a test asserts the fixture dir is the evidence, so adding a format
to the tuple without a file cannot silently pass.

**Scope enumerated live, never listed.** `git ls-files`, `git rev-list --all`,
`gh repo list`. Then assert non-empty. Note the distinction that matters here: a
count in *prose* rots because nothing holds it true; a count *asserted in code* is
a test. `assert repos >= 30` is fine — it fails loudly. `# audited: 10 of 14 hit`
in a comment is the defect, and that exact line was already stale.

**Retired values are never removed.** They no longer need rotating, but they still
mark a commit as having leaked.

**Failure modes are tested by breaking them.** `tests/unit/test_secret_scan.py`
asserts the scanner *fails* when the inventory is missing, when a format stops
matching, when the region markers are gone, when the tree is empty. A scan that
cannot be made to fail is exactly the thing this guards against.

**Heartbeat, not just failure alerts.** A job that stops running is silent forever
— that is the shape of a CI gate dead on a branch while main is green. The
scheduled sweep should report "swept N repos, M refs, clean" on success, with a
watchdog that complains when no heartbeat arrives.

## What this does not do

- **It does not find secrets that are not in the inventory.** That is the blind
  spot, and it is why the inventory is the thing to keep current.
- **It does not rewrite history.** Finding a leak in a public repo means
  **rotate**; with forks and permanent `refs/pull/*`, a purge does not get the
  value back.
- **It is not entropy detection.** No guessing at what looks secret-shaped —
  that is the layer that already failed here.

## Running it

```bash
make secrets-selftest        # prove it can still fire
make secrets-scan            # tracked tree + this branch's range vs main
make secrets-history         # every value in every ref (slower)
make secrets-audit           # .gitignore tags, from a copy that HOLDS the files
make secrets-install-hooks   # pre-push gate for this clone
```
