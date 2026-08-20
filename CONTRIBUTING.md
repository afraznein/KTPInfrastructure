# Contributing to KTP Infrastructure

Thanks for looking. This repo is the tooling, configuration and operational documentation
behind KTP's competitive Day of Defeat server estate — build automation, deployment scripts,
provisioning recipes, monitoring daemons, config profiles, the test harnesses, and the LAN/event
web properties under `sites/`.

**What it is not:**

- Not the game code. The engine, scripting platform, modules and match plugins live in their own
  repos (see *Related Projects* in [README.md](README.md)).
- Not a self-contained deployment. Several live scripts are deliberately absent — see
  [What is missing on purpose](#what-is-missing-on-purpose).
- Not the anti-cheat. Detection logic is kept out of public repos entirely; nothing here should
  describe how a detection works or what would trip it.

Read [docs/DEPLOYMENT_TARGETS.md](docs/DEPLOYMENT_TARGETS.md) before anything else. It separates
the paths that are load-bearing for the live fleet from the ones that only exist for local
development, and that distinction decides how much care a change needs.

---

## Two rules that come before everything

### 1. Never restart, stop or otherwise interrupt a game server

The fleet is production with active players and live matches. Restarts happen on the nightly
schedule (03:00 ET) and nowhere else. Do not run LinuxGSM control commands, restart scripts, or
anything that stops a running instance — not to test a change, not to "pick up" a config, not
because a server looks idle. If a change genuinely needs an activation restart, say so in the PR
and let a maintainer schedule it.

Staged binaries are picked up by the nightly restart. That is the only activation path; a map
change does not reload plugins.

The same applies to the `deploy-*` and `configure-names-*` Makefile targets and anything in
`deploy/` or `provision/` pointed at real hosts. Contributors develop against the local Docker
stack (`make local-up`), never against the fleet.

### 2. This repository is public — treat every commit as published

Never commit anything that looks like:

- a password, token, API key, shared secret, or private key
- an IP address or hostname of KTP infrastructure
- an internal service endpoint or admin URL
- a database or table name from the private schemas
- anti-cheat detection logic, thresholds, or anything that describes what a check measures

This is not a hypothetical. SSH, RCON and MySQL passwords were committed to this repo once
before and had to be rotated across the entire fleet. That is why so much of the tree ships as
`.example`.

If your change needs a secret, the secret is supplied at run time — from a config file on the
host, or an environment variable — and the repo carries only a template. Adding a new hardcoded
value is not an option, even temporarily, even on a branch you plan to rebase.

---

## What is missing on purpose

Files that embed credentials or fleet addresses are gitignored, and only their `.example`
templates are tracked. `.gitignore` documents each entry and why it is there; read it rather than
guessing.

A fresh clone therefore does not contain a runnable copy of, among others, the scheduled-restart
script, the HLTV API, the backup script, the fleet-audit tooling, or the private
infrastructure reference docs. Copy the `.example` to the real filename locally and fill in your
own values:

```bash
cp deploy/config.yaml.example deploy/config.yaml
cp config/online/discord.ini.example config/online/discord.ini
cp scripts/hltv-api.py.example scripts/hltv-api.py
```

Two consequences worth knowing up front:

- **Tests must pass without the real files.** `tests/config_parse/conftest.py` falls back to the
  `.example` sibling when the real config is absent, so the schema is still validated against
  what the repo actually ships. Keep that property — if you add a config test, make sure it works
  on a clean clone.
- **A change to a gitignored script is invisible to reviewers.** If you fix one, the fix has to
  land in the tracked `.example` too, or it does not exist for anyone else. The better move is to
  refactor the script so it *sources* its secrets (as `scripts/ktp-hltv-liveness.sh` does) and
  then track it properly. Shrinking the ignore list that way is welcome; deleting lines from it
  is not.

---

## Verifying you are not about to leak something

Do this before every push, not just the first one.

**Review what is actually staged**, file by file:

```bash
git status --porcelain          # not `git diff` — that ignores the index
git diff --cached               # read it, do not skim it
```

**Search the tree with `grep -rn`, not `rg`.** `rg` (and `git grep`) respect `.gitignore`, so
they skip exactly the files that hold secrets. A clean `rg` sweep of this repo proves nothing —
it can report zero hits while a credential sits in a gitignored script two directories away.

```bash
grep -rn --exclude-dir=.git 'some-value-you-are-checking-for' .
```

**Check against `origin/main`, not your working tree.** Whether something is *published* is a
question about the remote. A file can look committed locally and never have existed on any
remote ref, and the reverse — a value you deleted locally is still in history:

```bash
git log --oneline --remotes -- path/to/file      # has this ever been pushed?
git log -S'value' --oneline --all                # was this value ever committed?
```

**Match values, not keywords.** A keyword scan is not a clearance. `scripts/hltv-api.py` was
called clean twice by keyword grep before a value-based check found a live key in it.

If you find that a secret has already been pushed, do not quietly force-push over it. Say so
immediately — it needs rotating, and rewriting history does not un-publish it.

---

## Getting set up

The build system expects this repo to sit **alongside** the other KTP repos in one parent
directory. `KTP_PROJECT_ROOT` defaults to the parent of `KTPInfrastructure`, the Docker builds
mount sibling checkouts, and the shared lint hooks in `scripts/hooks/` are resolved by sibling
path. A standalone clone will build nothing.

```
<parent>/
├── KTPInfrastructure/     <- you are here
├── KTPAMXX/
├── KTPReHLDS/
└── ...
```

Then:

```bash
pip install -r deploy/requirements.txt          # deployment tooling
pip install -r sites/lan-web/requirements.txt   # only if touching sites/lan-web
pip install pytest
scripts/install-hooks.sh                        # installs the pre-push hook
```

CI runs Python 3.12; match it if you can. Docker is required for builds and the local stack.

`scripts/install-hooks.sh` installs a pre-push hook that runs a full `make build` in Docker.
It is slow on a cold cache. `KTP_SKIP_PREPUSH=1` or `git push --no-verify` bypasses it — fine for
a docs-only branch, not fine for anything that compiles.

**Line endings matter.** `.gitattributes` pins shell scripts, Python, systemd units, ini files,
cron payloads and SQL to LF, because these files are copied byte-for-byte onto Linux hosts and a
stray `\r` fails in ways that are genuinely hard to read (`$'\r': command not found`, a config
value that parses as a one-character string and passes a required-key check). If you are on
Windows, let git's attributes do their job — do not re-normalize files to CRLF, and do not add a
new deployable file type without an entry there.

---

## Branches and pull requests

- **The default branch is `main`.** PRs merge into it.
- **`preprod` is the integration branch for test/CI-lane work.** The Tier-2 lane series lands
  there first and reaches `main` afterwards. If your change is to `tests/`, the CI workflows or
  the test runner plumbing, ask which base you should target; otherwise target `main`.
- **Never commit to `main` or `preprod` directly.** Branch, push the branch, open a PR.
- **Branch naming** follows the prefix the work belongs to: `feat/`, `fix/`, `ci/`, `docs/`,
  `config/`, `test/`, `audit/`, plus a short kebab-case description —
  `fix/monitor-rcon-runtime`, `ci/zlib-pin`, `docs/preprod-card-reconcile`.
- **External contributors work from a fork** and open a PR from the fork branch to `main`. That
  is the established path here and it works fine.
- One reviewable change per PR. A mixed branch cannot be reverted without taking the safe half
  out with the risky half.

### Required checks

Both `main` and `preprod` require two status checks, and require your branch to be up to date
with the base before merging:

| Check | Workflow | Where it runs |
|---|---|---|
| `Config parse + assertions` | `.github/workflows/config-tests.yml` | GitHub-hosted |
| `integration` | `.github/workflows/tier2-integration.yml` | Self-hosted runner |

Two things about this that trip people up:

- Both workflows fire on **every** push and PR with no `paths:` filter, and each job decides for
  itself whether to run pytest. A job that self-skips still reports green so the required check
  is satisfied. So a green check does not always mean tests ran — read the job log if it matters.
- Tier 2 boots a real game server on a **self-hosted** runner that only maintainers control. On a
  fork PR it may not run until a maintainer approves the workflow run. A check that never
  reported is not a check that passed; do not read a missing Tier 2 as a green one.

The lan-web suite (`.github/workflows/lan-web-tests.yml`) is not a required check but it does run,
and it is the gate for anything under `sites/lan-web/`.

---

## Testing before you open a PR

Run what applies. All of these work on a clean clone.

```bash
# Tier 1 — config parse + harness/unit tests. Sub-second. Run this always.
python -m pytest tests/config_parse/ tests/smoke/test_parse.py tests/smoke/test_asserts.py tests/unit/ -v

# Config lint — catches a `debug` flag reaching the online plugin load,
# which would take the JIT off every production server.
make lint-configs

# lan-web, if you touched sites/lan-web/
cd sites/lan-web && python -m pytest tests/ -v

# A real build, if you touched build/, the Makefile, or anything compiled
make build VERSION=$(date +%Y%m%d)
```

Tier 2 (`tests/integration/`) needs a staged serverfiles tree and a Linux filesystem; see
`tests/integration/CI_RUNNER_SETUP.md`. Most contributors will not run it locally, and that is
expected — say in the PR that you did not, rather than implying you did.

A few expectations that are cheap to meet and save reviewer time:

- **Prove the negative case.** A check that passes for everything is not a check. If you add a
  guard, show it rejecting something as well as accepting something. If you add a probe, carry a
  control that should fail and does.
- **Assert your test suite is non-empty.** A collection error, a renamed directory or a bad
  rootdir all exit 0 with "no tests ran", which is indistinguishable from a pass in a green
  check. The lan-web workflow asserts a collected-test floor for exactly this reason.
- **Say what you verified and how.** "Ran the Tier 1 suite, added two cases covering X, did not
  run Tier 2" is a useful PR body. "Tested" is not.

---

## Commit messages and CHANGELOG

House style is a lowercase area prefix, then what changed — stated as a fact, not a category:

```
lan-web: an audit row now commits with the mutation it records
hltv: alert when a proxy stops being bound, not when systemd says so
gitignore: drop three dead rules, state why the rest exist
```

Prefixes in use include the directory or subsystem (`lan-web:`, `wsdod:`, `hltv:`, `config:`,
`ci:`, `docs:`, `ops:`). PR titles sometimes use `fix:` / `test:` / `ci:` instead; either is fine.

- Put the reasoning in the commit body. Long explanations belong there, not in code comments.
- If you used an AI assistant, omit attribution trailers. House practice on public repos is no
  `Co-Authored-By` for tooling and no session links.
- Anything a future operator would need to know — why a threshold is what it is, what a change
  was verified against, what it deliberately does not do — goes in [CHANGELOG.md](CHANGELOG.md)
  under `## [Unreleased]`, as a dated, area-prefixed entry. The existing entries are the format
  guide. Skip it for pure refactors; do not skip it for behaviour changes to anything the fleet
  runs.

---

## Code style

Python and shell here are plain and boring on purpose — these scripts run unattended on
production hosts at 03:00, and clever is expensive at 03:00.

- Match the surrounding file. Existing scripts use `set -euo pipefail` in bash and stdlib Python
  wherever it is practical; new dependencies need a reason.
- Fail loudly rather than continuing in a half-state, except where a monitoring script is
  explicitly guarded so a broken sub-check cannot take down the checks riding alongside it.
- Never silence errors to make output tidy. `2>/dev/null` on a probe turns a broken probe into a
  clean-looking zero, and that pattern has produced more than one false all-clear here.

### Comments

This is a house convention and reviewers do enforce it.

- **Default to none.** Write code that says what it does. A comment restating the line is noise —
  delete it rather than improve it.
- **Explain *why*, never *what*.**
- **One line. Three is the ceiling.** If it needs a paragraph, it is a commit message or a doc
  wearing the wrong hat: put the reasoning there and leave the fact in the code.
- **No counts, and no "N of M".** A number in prose is a claim with no test holding it true, so it
  rots silently and then misleads. Describe the property instead — "one round-trip per entry",
  not "23 entries". This applies to docs as much as code; the README used to pin a version string
  in its header and it drifted.
- **No internal ticket, plan or review IDs** in shipped code. Reference them in the commit or the
  PR.
- **Preserve tripwires.** Some comments encode a fact someone paid for — a CRLF hazard, a lock
  ordering, a cvar that must not be raised. Shorten the prose if you like, but never delete the
  warning.

---

## Questions, and where things go

- **Open an issue** for a bug, a question about intended behaviour, or anything you want a
  decision on before writing code. Issues are enabled and low-traffic; use them.
- **Ask in the PR** for review-level questions once you have code.
- **Ask before writing** if the change touches deployment paths, configuration the fleet runs, or
  anything under `provision/`. A wrong answer there reaches every live instance at once, and the
  cheap version of that conversation happens before the branch, not after.
- **Do not open a public issue for a suspected leaked secret or a security problem.** Contact the
  maintainer ([@afraznein](https://github.com/afraznein)) directly.

The README names MIT, but no `LICENSE` file is currently committed — if licensing matters for
your contribution, ask first rather than assuming terms.
