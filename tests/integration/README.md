# KTP Tier 2 Match-Flow Integration Tests

Pytest suite that boots `hlds_linux` with a test-mode KTPMatchHandler.amxx
+ KTPWitness.amxx and exercises the match-flow state machine via the
`amx_ktp_test_*` RCON commands shipped in KTPMatchHandler 0.10.122
(current fleet build 0.10.143 — the spine test pins the exact expected
version; the layout sketch below predates several later test files).

Asserts on three observable surfaces:

1. **`amx_ktp_test_get_state` JSON** — in-memory state of the state machine
   (matchType, currentHalf, matchLive, matchId, scores, captains).
2. **`log_ktp` event lines** in `addons/ktpamx/logs/L<MMDD>.log` — write-
   through audit trail of state transitions.
3. **`addons/ktpamx/logs/witness.jsonl`** — KTPWitness.amxx records every
   `ktp_match_start` / `ktp_match_end` forward dispatch as proof that the
   forward reached at least one downstream consumer (same dispatch path
   KTPHLTVRecorder uses in production).

## Layout

```
tests/integration/
├── __init__.py
├── conftest.py              # session-scoped hlds fixture + autouse reset
├── match_flow.py            # MatchDriver class wrapping amx_ktp_test_* rcons
├── log_tail.py              # log_ktp + witness.jsonl polling helpers
├── fake_relay.py            # stdlib HTTP mock of the Discord relay (Session 3 prep)
├── test_match_flow_spine.py # tests 1 / 3 / 4 / 6 (Session 2 — the spine)
├── test_fake_relay.py       # mock-side smoke of fake_relay (Session 3 prep)
├── witness/                 # KTPWitness.amxx source + compile.sh
└── README.md
```

## Prerequisites

### Build artifacts

1. **Test-mode KTPMatchHandler.amxx** — this is the
   `compiled/test/KTPMatchHandler.amxx` artifact, NOT the production
   `compiled/KTPMatchHandler.amxx`:

   ```bash
   cd KTPMatchHandler
   KTP_TEST_MODE=1 bash compile.sh
   ```

2. **KTPWitness.amxx**:

   ```bash
   cd KTPInfrastructure/tests/integration/witness
   bash compile.sh
   ```

### Server tree

The hlds server needs a `serverfiles/` tree with:

- `hlds_linux` + the dod/ tree (extract from KTP DoD Server staging,
  or use the same `extract-artifacts` make target Tier 1 smoke uses)
- KTPAMXX dlls + modules already in place (per the standard `clone-ktp-stack`
  layout)
- `dod/addons/ktpamx/plugins/` containing:
  - `KTPMatchHandler.amxx` — the test-mode build (replace the production one)
  - `KTPWitness.amxx`
  - `KTPHudObserver.amxx` — required for `test_hud_observer_contract.py`
    (build with the standard amxxpc Docker invocation in
    `DoD-hud-observer/CLAUDE.md` § "Compiling the AMXX Plugin")
- `dod/addons/ktpamx/configs/plugins.ini` listing them:

  ```
  admin.amxx
  KTPMatchHandler.amxx debug
  KTPWitness.amxx debug
  KTPHudObserver.amxx debug   ; required for test_hud_observer_contract.py
  ```

  (Strip everything else for the tightest signal — production plugins
  pull in services that fail-loud when their server endpoints aren't
  reachable from the test host.)

  KTPHudObserver's `dod_hud_url` and `dod_hud_key` cvars are overridden
  per-session by the `_hud_cvars_setup` fixture (writes to `dod/server.cfg`).
  The plugin POSTs every event to a `FakeIngest` loopback listener; the
  contract tests assert the JSON envelope shape downstream consumers expect.

### Filesystem

**WSL caveat (memory `wsl_drvfs_hlds_incompatibility.md`)**: hlds_linux
core-dumps when booted from a `/mnt/...` DrvFs mount. Subprocess-boot
mode requires the serverfiles tree on a real ext4 mount.

For Windows dev: `cp -r '/mnt/n/Nein_/KTP Git Projects/KTP DoD Server/serverfiles/.' ~/ktphlds-test/`
once, then drop the test-mode binaries into `~/ktphlds-test/dod/addons/...`
and point `KTP_HLDS_SERVERFILES` at it.

For the data server (real Linux ext4): the existing `/home/dodserver/dod-27015/serverfiles/`
works directly. Or stage a separate copy under `/tmp/integration-test/`
to avoid touching production trees.

### Steam runtime requirement (verified 2026-05-04 attempt)

**hlds_linux refuses to boot without a working Steam authentication
runtime**, even with `+sv_lan 1` (the boot-subprocess driver passes
this; doesn't help). The engine logs:

```
[S_API FAIL] SteamAPI_Init() failed; SteamAPI_IsSteamRunning() failed.
dlopen failed trying to load: steamclient.so
[S_API FAIL] SteamAPI_Init() failed; unable to locate a running instance
of Steam, or a local steamclient.dll.
FATAL ERROR (shutting down): Unable to initialize Steam.
```

What's needed:
1. **`steamclient.so` reachable** — engine looks at `~/.steam/sdk32/steamclient.so`
   AND in the serverfiles cwd as bare `steamclient.so`. Both must resolve.
   On production game servers this is set up by `steamcmd` install.
2. **A live Steam authentication context** — even the dlopen-success path
   gates on `SteamAPI_IsSteamRunning()`, which checks for an actual
   running steam daemon / shared-mem segment.

A 2026-05-04 attempt confirmed the rest of the test path works:
- `KTPMatchHandler.amxx` (test-mode) loaded cleanly
- `KTPWitness.amxx` loaded cleanly
- KTPAMXX extension mode initialized; ReAPI / DODX / amxxcurl modules
  attached
- Plugins.ini surgery worked
- 3 plugins precached, plugin_init deferred to server-activate

… but Steam init blocks final boot. Workaround paths:

- **Install `steamcmd` in WSL** (~100MB; needs network access; one-time
  setup): `sudo apt install steamcmd` then run `steamcmd +login anonymous +quit`
  to populate `~/.steam/sdk32/steamclient.so` symlinks correctly.
- **Run on the data server** (`/tmp/integration-test/` tree per above)
  where steamcmd is already installed.
- **External-server mode** (`KTP_HLDS_HOST` set) against an instance
  with test-mode plugins staged. Caution: don't confound an instance
  that's currently part of a canary experiment (e.g., ATL:27019 is
  perpetually in something).
- **Session 5's CI-runner registration** — long-term resolution.

## Running

Three modes (priority order — first one configured wins):

### Mode 1: External server (fastest iteration)

Operator boots hlds once, leaves it running. Tests connect to its rcon.
Each test calls `amx_ktp_test_reset` between runs for clean state.

```bash
export KTP_HLDS_HOST=127.0.0.1
export KTP_HLDS_PORT=27999
export KTP_HLDS_RCON_PASSWORD=integration
export KTP_HLDS_SERVERFILES=$HOME/ktphlds-test  # for log/witness reads

cd KTPInfrastructure
pytest tests/integration -v
```

### Mode 2: Subprocess boot (CI / one-shot)

Each test session boots hlds fresh. ~10s startup cost amortized over
the session (session-scoped fixture).

```bash
export KTP_HLDS_SERVERFILES=$HOME/ktphlds-test

cd KTPInfrastructure
pytest tests/integration -v
```

### Mode 3: Skip (no env)

If neither `KTP_HLDS_HOST` nor `KTP_HLDS_SERVERFILES` is set, all tests
skip cleanly with a message pointing at this README. Useful for `pytest`
runs on a dev box without the hlds environment.

## Test surface (Session 2 — spine)

| # | Name | Asserts |
|---|------|---------|
| 1 | `test_1_plugin_load_and_version_pin` | `amx_ktp_versions` lists KTPMatchHandler at the version pinned in `EXPECTED_KTPMATCHHANDLER_VERSION` (currently 0.10.143). Catches the "source bumped, deployed binary stale" class. |
| 3 | `test_3_setup_match_enters_prestart` | `amx_ktp_test_setup_match 0` returns a `<systime>-TEST` match_id; state shows COMPETITIVE matchType + non-live + non-pending; synthetic captains in place; TEST_SETUP log line written. |
| 4 | `test_4_advance_pending_enters_pending` | `amx_ktp_test_advance_pending` flips `matchPending` 0 → 1; PENDING_BEGIN log line emitted (production-shape event downstream consumers gate on). |
| 6 | `test_6_advance_live_fires_match_start_forward` | `amx_ktp_test_advance_live 1` flips `matchLive` 0 → 1, sets `currentHalf=1`, fires `ktp_match_start` forward (witness.jsonl row with matching matchId/matchType/half). **The load-bearing test of the spine** — proves cross-plugin forward dispatch works end-to-end. |

## Test surface — KTPHudObserver contract (DRAFT)

`test_hud_observer_contract.py` adds a SECOND downstream consumer alongside
KTPWitness — instead of just proving "the forward dispatched", it proves
"HUD Observer's hook ran AND the JSON envelope it shipped matches the
contract `DoD-hud-observer/backend/src/handler/ingest.ts` reads from."

| Test | Asserts |
|------|---------|
| `test_hud_observer_loaded_and_version_pin` | `amx_ktp_versions` lists `KTP HUD Observer` at the version pinned in `EXPECTED_KTPHUDOBSERVER_VERSION`. Same shape as the spine `test_1`; catches stale-binary drift on the HUD Observer side. |
| `test_ktp_match_start_envelope_shape` | After `advance_live(1)`, fake_ingest captured a `ktp_match_start` POST with `match_id`/`map`/`match_type`/`half`/`tick`/`plugin_sent_at` envelope fields populated. **The contract-validation core** — catches silent data-loss regressions from forward-arg refactors. |
| `test_ktp_match_end_envelope_shape` | After `end_match(3, 1)`, fake_ingest captured a `ktp_match_end` POST with the same envelope + `allies_score=3`/`axis_score=1`. Asymmetric scores so a swap-bug surfaces. |

Follow-up PRs (out of first-cut scope): DODX-forward consumption, alt
match-type variants, half-2 transition + score carryover, flag events,
roster dump, auth-rejection path.

## Future sessions

- **Session 3 (~8h)** — Phase B/C/D fill-out: DODX context propagation,
  HLStatsX `KTP_MATCH_START` log line, Discord embed POST verification
  (the `fake_relay.py` mock + 11 mock-side smoke tests landed 2026-05-04
  as Session 3 prep), tech pause / resume, half/match-end. Remaining
  Session 3 work is wiring KTPMatchHandler at the mock URL via fixture-
  injected discord.ini override + writing the actual end-to-end Discord
  POST tests — the mock contract is now stable + reusable.
- **Session 4 (~8h)** — Phase E/F: alt match types (.scrim / .draft /
  .12man) + admin recovery (`ktp_forcereset`, `ktp_restarthalf`).
- **Session 5 (~6h)** — Phase G/H + flake hardening + CI wiring (self-
  hosted runner registration on data server + GitHub workflow + Allure
  publish).

See `KTPInfrastructure/TEST_INFRASTRUCTURE_PLAN.md` § Tier 2 for the full
roadmap.

## Cross-references

- `KTPMatchHandler/CHANGELOG.md` § 0.10.122 — test-mode build flag + RCON command set
- `KTPInfrastructure/tests/integration/witness/README.md` — why a separate
  witness plugin (vs scraping log_ktp lines)
- Memory `wsl_drvfs_hlds_incompatibility.md` — ext4 requirement
- Memory `extension_mode_no_fakemeta.md` — why we drive the state machine
  directly instead of synthesizing fake clients
- Memory `amxx_rcon_output_format.md` — `amx_ktp_versions` output shape
