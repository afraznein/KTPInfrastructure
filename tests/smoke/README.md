# Tier 1 Smoke Test Harness

Shared boot + rcon + assertion harness for KTP plugin/module load-smoke tests.
Lives below `KTPInfrastructure/tests/smoke/` so per-project repos
(`KTPAmxxCurl`, `KTPMatchHandler`, `KTPAntiCheat`) can add a thin smoke test
on top without each duplicating the rcon plumbing.

See [`KTPInfrastructure/TEST_INFRASTRUCTURE_PLAN.md`](../../TEST_INFRASTRUCTURE_PLAN.md)
for the broader Tier 1/2/3 framework.

## What this catches

- The 04-14 `KTPAmxxCurl` class — a `.so` module silently fails to load and
  every plugin that depends on it falls over.
- A `.amxx` plugin file that compiles fine but fails to load (missing native,
  wrong AMXX ABI, truncated build artifact).
- A typo in `modules.ini` / `plugins.ini`.

## What this does NOT catch

- Per-plugin behavioural regressions (Tier 2's job).
- Performance regressions (Tier 3's job).
- Anything inside the closed-source DoD game DLL.

## Layout

```
tests/smoke/
├── __init__.py            public API re-exports
├── rcon.py                GoldSrc UDP rcon client (stdlib only)
├── server_handle.py       ServerHandle dataclass + wait_ready
├── boot.py                docker compose driver (sibling of boot_subprocess)
├── boot_subprocess.py     direct hlds_linux subprocess driver (CI / WSL)
├── parse.py               fixed-column parser for `amx modules` / `amx plugins`
├── asserts.py             high-level assertion helpers
├── cli.py                 command-line entrypoint
├── fixtures/
│   └── test_server.cfg    minimal sv_lan config the harness boots against
├── test_parse.py          unit tests — parser
├── test_asserts.py        unit tests — assertions against stubbed handle
└── _proof.py              one-shot live-boot smoke (run manually after setup)
```

## Running

### Unit tests (no server boot — runs anywhere Python runs)

```bash
cd KTPInfrastructure
python -m unittest tests.smoke.test_parse tests.smoke.test_asserts
```

### Against a server you already booted

```bash
# Bring up via existing local compose stack (one-time: `make local-up`)
cd KTPInfrastructure
python -m tests.smoke.cli wait-ready --port 27016
python -m tests.smoke.cli assert-modules --port 27016 \
    --expect amxxcurl,reapi,dodx,fakemeta,hamsandwich
python -m tests.smoke.cli assert-no-failed --port 27016
```

Default `--rcon-password` is `changeme` — matches `config/local/dodserver.cfg`.
For a manual subprocess boot pass whatever the harness used (`smoketest`).

Exit codes: `0` clean, `1` assertion fail, `2` infrastructure error.

### Live boot (Linux / CI)

`boot_subprocess.booted_subprocess(serverfiles)` is a context manager that
spawns hlds_linux, waits for rcon, yields a handle, and tears down on exit.
Best illustrated by `_proof.py` — uses the local `KTP DoD Server/serverfiles`
tree, asserts modules + plugins, prints GREEN.

```bash
# On a real Linux runner (CI, ext4 WSL home, native Linux):
cd KTPInfrastructure
python -m tests.smoke._proof
```

## Local-Windows note

`hlds_linux` cannot stat files served from `/mnt/<drive>` (WSL DrvFs) — the
engine's filesystem layer rejects the directory entries and core-dumps on
`liblist.gam`. To run the live path locally on Windows:

- Best: copy `KTP DoD Server/serverfiles/` into ext4 inside WSL
  (`~/ktp-smoke-tree`) and point `_proof.py` at that copy.
- Or: use the `boot.py` docker compose driver instead, which bind-mounts the
  artifacts inside a Linux container where DrvFs isn't involved. Requires
  Docker Desktop running and `make build && make extract-artifacts &&
  make local-build` once.
- CI runs on `ubuntu-latest` (real ext4) — neither workaround is needed there.

## Truncation gotcha

KTPAMXX prints `amx plugins` with `%-12.11s` for the file column — only the
first 11 chars survive. `KTPMatchHandler.amxx` shows up as `KTPMatchHan`.
The parser preserves the truncated output as-is; `assert_plugins_running`
matches expected names against parsed names with an 8-char prefix floor so
callers can pass the unstripped filename. `matches_truncated()` in `parse.py`
documents the rule.

## CI integration (shipped Sessions 2-3 — 2026-04-27)

The Tier 1 smoke is wired into per-project GitHub Actions workflows. The
heavy lifting lives in a single **reusable workflow** at
[`KTPInfrastructure/.github/workflows/smoke-callable.yml`](../../.github/workflows/smoke-callable.yml);
each per-project repo's workflow is a ~25-line caller that just configures
triggers + per-project assertions. Initial callers:

- [`KTPAmxxCurl/.github/workflows/smoke.yml`](../../../KTPAmxxCurl/.github/workflows/smoke.yml) — module test, asserts `amxxcurl` loads
- [`KTPMatchHandler/.github/workflows/smoke.yml`](../../../KTPMatchHandler/.github/workflows/smoke.yml) — plugin test, asserts `KTPMatchHandler` runs

### Workflow shape (in the reusable workflow)

The reusable workflow has TWO paths, selected by the caller's `use_base_image`
input (default `true`):

**FAST PATH (~3-5 min)** — pulls a nightly-rebuilt GHCR base image and
overlays only the change-under-test:

```
checkout caller repo + KTPInfrastructure (+ KTPAMXX/KTPhlsdk if cpp_module)
  → strip KTPHudObserver from plugins.ini
  → log in to GHCR + pull ghcr.io/<owner>/ktp-runtime-test-base:latest
  → build under-test only:
      amx_plugin: docker run base amxxpc src.sma -o output.amxx (~5 sec)
      cpp_module: make build-base build-<target> (~3 min)
  → docker build smoke overlay (FROM base + COPY new artifact, ~10 sec)
  → docker compose up --no-build ktp-game-1
  → smoke harness (wait-ready → assert-no-failed → assert-* → teardown)
```

**SLOW PATH (~12-20 min, fallback)** — full from-scratch build, used when
`use_base_image: false`:

```
checkout 14 KTP repos as siblings (skip the caller — already checked out)
  → strip KTPHudObserver from plugins.ini
  → make build (full stack — engine + amxx + reapi + curl + plugins)
  → docker compose build ktp-game-1
  → docker compose up ktp-game-1
  → smoke harness
```

Both paths produce the same `ktp-gameserver:ci` Docker image and run the
identical Python harness. The fast path is the default; slow path is the
fallback for rebuild-the-whole-thing scenarios (base image broken,
build-system changes, etc.).

Run time: ~12-20 min on `ubuntu-latest`. Dominated by SteamCMD HLDS install
(~500 MB) + KTPReHLDS + KTPAMXX compiles. Optimization-targetable in a follow-up
by publishing a `ktp-runtime:test-base` image to GHCR with everything-but-the-
under-test-component pre-installed; the per-project workflow then just builds
the one component and overlays.

### Multi-repo checkout pattern

Every KTP component lives in its own repo, but the `KTPInfrastructure/Makefile`
+ `build/docker-compose.yml` use sibling-directory paths
(`${KTP_PROJECT_ROOT:-./..}` as Docker build context). To match locally, the CI
workflow checks out each repo into the runner's workspace root:

| Path | Repo | Used for |
|---|---|---|
| `KTPAmxxCurl/` | this repo | the change under test |
| `KTPInfrastructure/` | infra | build orchestration + smoke harness |
| `KTPReHLDS/` | engine | game engine binary |
| `KTPAMXX/` | scripting | platform binary + amxxpc compiler |
| `KTPReAPI/` | engine bridge | reapi module |
| `KTPhlsdk/` | sdk | header dependency |
| `KTPMatchHandler/`, `KTPHLTVRecorder/`, `KTPCvarChecker/`, `KTPFileChecker/`, `KTPAdminAudit/`, `KTPGrenades/`, `KTPPracticeMode/`, `KTPScoreTracker/` | plugins | compiled into runtime by `make build-plugins` |

### Auth for cross-repo checkout

Plugin and engine repos may be private. The workflow uses the secret
`KTP_CHECKOUT_TOKEN` (a PAT with read-only `repo` scope on each KTP repo) when
set, falling back to `${{ github.token }}` for public/same-org access. The PAT
is required if any KTP repo is private — `${{ github.token }}` cannot reach
private repos outside the workflow's own.

To set up: GitHub → org settings → secrets → add `KTP_CHECKOUT_TOKEN` with a
classic PAT that has `repo` (read) on every KTP repo above. Configure as
either organization-level (preferred) or per-repo secret.

### One quirk: KTPHudObserver lives in an external repo

`config/local/plugins.ini` references `KTPHudObserver.amxx`, which is in
[`JimmyLockhart65616/DoD-hud-observer`](https://github.com/JimmyLockhart65616/DoD-hud-observer)
not under our org. The smoke workflow strips it from `plugins.ini` before
build (else the runtime image has the line referencing a missing file →
KTPAMXX reports "bad load" → smoke fails). To re-include it, add a
checkout step + adjust `config/local/plugins.ini` handling. Currently
disabled fleet-wide post the 2026-04-26 NY1 SEGV, so leaving it out of
smoke is also defensible on safety grounds.

### Debugging a red CI run

When the workflow fails:

1. **`Container logs on failure` step** dumps the last 400 lines of
   `ktp-game-1` stdout. Look here first — most failures are visible
   immediately (`bad load: <module>`, missing file, segfault).
2. **`Live amxx state on failure` step** runs `amx modules` + `amx plugins`
   via rcon and prints them. Useful for "server booted but X didn't load."
3. **`make build` failure** is usually a missing sibling repo (look for
   "no such file or directory" in the docker context) or a real compile
   error in the change under test.

### Adding a smoke workflow to another KTP repo

The reusable workflow handles the boilerplate. A new per-project caller is
~25 lines:

```yaml
# RepoName/.github/workflows/smoke.yml — AMX plugin example
name: Tier 1 Smoke
on:
  push:
    branches: ['**']
    paths-ignore: ['**.md', 'docs/**']
  pull_request:
    paths-ignore: ['**.md', 'docs/**']
  workflow_dispatch:

jobs:
  smoke:
    uses: ${{ github.repository_owner }}/KTPInfrastructure/.github/workflows/smoke-callable.yml@main
    with:
      under_test_label: RepoName
      under_test_kind: amx_plugin
      amxx_source: PluginName.sma
      artifact_container_path: /opt/hlds/dod/addons/ktpamx/plugins/PluginName.amxx
      assert_plugin: PluginName
    secrets:
      ktp_checkout_token: ${{ secrets.KTP_CHECKOUT_TOKEN }}
```

For a C++ module repo (KTPAmxxCurl shape), the inputs differ:

```yaml
    with:
      under_test_label: RepoName
      under_test_kind: cpp_module
      make_build_target: build-<target>      # e.g. build-curl, build-engine
      artifact_host_path: KTPInfrastructure/artifacts/ci/ktpamx/modules/<artifact>.so
      artifact_container_path: /opt/hlds/dod/addons/ktpamx/modules/<artifact>.so
      assert_module: <module-name>
```

Naming hints:
- `assert_module` matches against `amx modules` output. Use the short
  display name (e.g. `amxxcurl`, `reapi`, `dodx`); the parser normalises
  away `_ktp_i386.so` suffixes.
- `assert_plugin` matches against `amx plugins` output. Truncation-aware
  matcher means `KTPMatchHandler` matches the truncated `KTPMatchHan` that
  AMXX's `%-12.11s` format string produces.

The reusable workflow knows to skip checking out the caller's own repo
(it's already checked out by `actions/checkout@v4` against the trigger
context). Per-project repos do not need to special-case anything else.

The composite action `compile-amx` at `.github/actions/compile-amx/` is
available for workflows that need to invoke `amxxpc` directly outside
the `make build-plugins` flow — useful for a stricter under-test compile
with `fail-on-warning: 'true'`, or for selective rebuild without the full
stack. Not used by the smoke workflows above; kept available for future
sessions.

## Test bar

## Test bar

Per `TEST_INFRASTRUCTURE_PLAN.md`: flakes fixed or deleted in 48h, no
`@flaky` quarantine tier. Test code reviewed at the same standard as
production code — no "it's just a test" escape hatch.
