# Tier 2 Integration Tests — Self-Hosted Runner Setup

This doc walks the operator through registering and configuring a
GitHub Actions self-hosted runner to run the Tier 2 integration test
suite (`.github/workflows/tier2-integration.yml`).

## Why self-hosted (vs GitHub-hosted)

`hlds_linux` is a 32-bit binary that requires a real ext4 mount (per
memory `wsl_drvfs_hlds_incompatibility.md` — DrvFs `_stat` rejects
metadata and core-dumps the engine). It also needs ~50MB of game assets
+ `libsteam_api.so` + the KTPAMXX core stack pre-staged. Bundling all
that into a GitHub-hosted runner image would inflate setup time to >5
min per CI run; a self-hosted runner with the tree pre-staged drops that
to <30s.

## Prerequisites

- A Linux box with ext4 (NOT WSL DrvFs, NOT NTFS, NOT NFS). Bare metal,
  VPS, or LXC container. Memory: ~512MB free; disk: ~200MB for the test
  serverfiles tree. CPU: 2 vCPU minimum.
- 32-bit runtime libs installed:
  ```
  sudo apt install -y libc6:i386 libstdc++6:i386 libcurl4:i386
  ```
- Python 3.12+
- A GitHub account with admin access to the
  `afraznein/KTPInfrastructure` repo (to register the runner token).

## Runner registration

1. **Get the registration token** — GitHub admin only:
   - Repo `Settings` → `Actions` → `Runners` → `New self-hosted runner`
   - Select Linux x64
   - Copy the `./config.sh --url ... --token ...` line shown on the
     setup page (the token is single-use and expires in ~1h)

2. **Install the runner** on the box:
   ```bash
   mkdir -p ~/actions-runner && cd ~/actions-runner
   # Use the latest release URL from the GitHub setup page (changes)
   curl -o actions-runner-linux-x64.tar.gz -L \
     https://github.com/actions/runner/releases/download/<version>/<artifact>
   tar xzf actions-runner-linux-x64.tar.gz

   # Use the token from step 1. Add the `ktp-tier2` label so our
   # workflow's `runs-on: [self-hosted, ktp-tier2]` matches.
   ./config.sh --url https://github.com/afraznein/KTPInfrastructure \
               --token <TOKEN_FROM_STEP_1> \
               --labels ktp-tier2 \
               --name ktp-tier2-$(hostname) \
               --unattended
   ```

3. **Install as a systemd service** so it survives reboots:
   ```bash
   sudo ./svc.sh install $USER
   sudo ./svc.sh start
   sudo ./svc.sh status   # should show 'active (running)'
   ```

## Stage the test serverfiles tree

Tier 2 expects a writable serverfiles tree at
`$KTP_HLDS_SERVERFILES` (default: `/home/runner/ktphlds-test/serverfiles`).
The tree must contain:

| Path | Source artifact | Notes |
|---|---|---|
| `hlds_linux` | KTP DoD Server | binary, 32-bit |
| `engine_i486.so` | KTP-ReHLDS build output | engine extension |
| `libsteam_api.so` | KTP DoD Server | KTP-specific (76KB, NOT 375KB stock) |
| `dod/addons/ktpamx/dlls/ktpamx_i386.so` | KTPAMXX build output | scripting platform |
| `dod/addons/ktpamx/modules/dodx_ktp_i386.so` | KTPAMXX build output | **with test natives** |
| `dod/addons/ktpamx/modules/reapi_ktp_i386.so` | KTPReAPI build output | engine bridge |
| `dod/addons/ktpamx/modules/amxxcurl_ktp_i386.so` | KTPAmxxCurl build output | HTTP module |
| `dod/addons/ktpamx/plugins/KTPMatchHandler.amxx` | **TEST-MODE build** | from `compiled/test/` |
| `dod/addons/ktpamx/plugins/KTPWitness.amxx` | KTPInfrastructure | from `tests/integration/witness/compiled/` |
| `dod/addons/ktpamx/plugins/KTPHudObserver.amxx` | DoD-hud-observer build | required for `test_hud_observer_contract.py` |
| `dod/addons/ktpamx/plugins.ini` | (test-mode config) | must list KTPMatchHandler + KTPWitness + KTPHudObserver |
| `dod/addons/ktpamx/configs/dodserver.cfg` | (minimal test config) | rcon_password=`smoketest` per the conftest |

**Critical: KTPMatchHandler MUST be the test-mode build** (compiled with
`KTP_TEST_MODE=1 bash compile.sh`, output at `compiled/test/`) — production
build doesn't expose the `amx_ktp_test_*` rcons that drive the suite.

### Initial staging script (one-shot)

No staging script exists yet — it can be added as a follow-up if multiple
runners get registered. For the first (and likely only) runner, the
manual procedure below covers the bootstrap.

```bash
# As the runner user
mkdir -p ~/ktphlds-test/serverfiles
cd ~/ktphlds-test/serverfiles

# Copy from local KTP dev tree (one-time bootstrap)
rsync -a /path/to/KTP\ DoD\ Server/serverfiles/ ./

# Override with test-mode KTPMatchHandler
cp /path/to/KTPMatchHandler/compiled/test/KTPMatchHandler.amxx \
   dod/addons/ktpamx/plugins/

# Override with KTPWitness
cp /path/to/KTPInfrastructure/tests/integration/witness/compiled/KTPWitness.amxx \
   dod/addons/ktpamx/plugins/

# Stage KTPHudObserver (required for test_hud_observer_contract.py).
# Build with the standard amxxpc Docker invocation in
# `DoD-hud-observer/CLAUDE.md` § "Compiling the AMXX Plugin", or pull
# from the KTPInfrastructure CI artifact (Tier 1 smoke produces it).
cp /path/to/DoD-hud-observer/compiled/KTPHudObserver.amxx \
   dod/addons/ktpamx/plugins/

# Set permissions
chmod 755 hlds_linux
```

### Per-run refresh (CI-driven, future enhancement)

Once the basic setup is stable, the workflow can add a "refresh
artifacts" step that pulls the latest test-mode KTPMatchHandler +
KTPWitness from the workflow's checkout into the staged tree. This
removes the manual step of re-staging on every test-mode rcon change.

For now, refresh manually whenever:
- KTPMatchHandler.sma's `-DKTP_TEST_MODE` block changes
- KTPWitness.sma changes
- DODX module's test natives change (less frequent — needs full KTPAMXX rebuild)
- DoD-hud-observer/KTPHudObserver.sma version bumps (also bump the pin
  in `tests/integration/test_hud_observer_contract.py:EXPECTED_KTPHUDOBSERVER_VERSION`)

## Set repository variables

The workflow reads `vars.KTP_HLDS_SERVERFILES` for the path to the
staged tree. Configure via repo `Settings` → `Secrets and variables`
→ `Actions` → `Variables` tab → `New repository variable`:

- **Name:** `KTP_HLDS_SERVERFILES`
- **Value:** `/home/runner/ktphlds-test/serverfiles` (or wherever you
  staged the tree)

## Verify the setup

1. Trigger the workflow manually:
   - Repo `Actions` → `Tier 2 Integration` → `Run workflow`
   - Branch: `main`
   - Optional: bump `timeout_multiplier` to 2.0 if the runner is
     resource-constrained

2. The workflow should:
   - Verify all required artifacts present in serverfiles
   - Run the pytest suite (~10s if env-conditional, longer if everything
     unblocks end-to-end)
   - Pass with the same test counts the operator sees locally

3. If artifacts are missing, the verification step prints which one and
   exits 1. Re-stage and retry.

## Maintenance

- **GitHub runner self-update**: auto-updates by default; verify periodically with
  `cat ~/actions-runner/RUNNER_VERSION`.
- **OS package upgrades**: standard `apt update && apt upgrade` cadence.
  After kernel updates, reboot and verify the runner service comes back
  via `sudo ./svc.sh status`.
- **Test serverfiles updates**: bump artifacts whenever KTPMatchHandler /
  KTPWitness / DODX test surfaces change. The workflow's "verify
  artifacts" step catches missing files but doesn't validate version /
  hash — drift surfaces as test failures.

## Troubleshooting

**"All required artifacts present" passes but tests skip**
→ The `KTP_HLDS_SERVERFILES` env var isn't being passed into the pytest
process. Check the workflow `env:` block; verify `vars.KTP_HLDS_SERVERFILES`
is set in repo settings.

**hlds_linux fails to boot** (`engine_i486.so: cannot open shared object`)
→ 32-bit runtime libs missing. Re-run the apt install line above.

**"DrvFs metadata rejected" / engine core dumps on boot**
→ The serverfiles tree is on a non-ext4 filesystem. Move it to ext4.

**Test 9c always passes (should be skip-marked)**
→ Test 9c is decorator-skipped as of KTPMatchHandler 0.10.123 with a
production-design rationale (`g_curlHeaders` persistent slist freezes
the auth header at boot-time secret per UAF-safety policy). If 9c isn't
skipping in your run, the test file's `@pytest.mark.skip(reason=
SKIP_REASON_9C)` decorator was lost during a merge — restore it.

## Cross-references

- `.github/workflows/tier2-integration.yml` — the workflow itself
- `tests/integration/conftest.py` — fixtures (hlds, discord_relay)
- `tests/smoke/boot_subprocess.py` — hlds boot helper used by the suite
- Memory: `wsl_drvfs_hlds_incompatibility.md`, `extension_mode_no_fakemeta.md`
