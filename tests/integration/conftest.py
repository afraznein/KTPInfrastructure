"""pytest fixtures for Tier 2 match-flow integration tests.

Three operating modes for the `hlds` fixture, in priority order:

  1. **External server** (KTP_HLDS_HOST + KTP_HLDS_PORT + KTP_HLDS_RCON_PASSWORD
     env vars set) — connect to an already-running hlds. Fastest iteration
     loop; the operator brings up the server once, runs the tests many times.
     The fixture issues `amx_ktp_test_reset` between tests to guarantee a
     clean state machine, but does NOT teardown the process.

  2. **Subprocess boot** (KTP_HLDS_SERVERFILES env var pointing at a properly-
     staged `serverfiles/` directory) — boots hlds_linux directly. Reuses
     the Tier 1 smoke harness's `boot_subprocess` driver. Per-test boot:
     ~10s on a warm filesystem, dominated by Steam-init + map-load.

  3. **Skip** — if neither env path is set up, tests skip with a clear
     message pointing at this file's docstring.

WSL caveat: hlds_linux core-dumps when booted from a `/mnt/...` DrvFs path
(memory `wsl_drvfs_hlds_incompatibility.md`). Subprocess mode requires the
serverfiles tree on a real ext4 mount (e.g., `~/ktphlds-test/`). This is
the same constraint Tier 1 smoke runs into; the workaround is identical:
copy the tree to ~/ before running.

Plugins.ini surgery is the operator's responsibility for now (Session 2):
the test-mode KTPMatchHandler.amxx (`compiled/test/`) and KTPWitness.amxx
(`tests/integration/witness/compiled/`) must be in the serverfiles tree's
plugins/ dir, listed in plugins.ini. Future Session: a fixture that
injects the test plugins automatically per-boot.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

# Reach into the Tier 1 smoke harness for ServerHandle, boot_subprocess.
# Path adjustment: tests/integration/ is a sibling of tests/smoke/.
_SMOKE_DIR = Path(__file__).resolve().parent.parent / "smoke"
if str(_SMOKE_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_SMOKE_DIR.parent))

from smoke import ServerHandle  # noqa: E402
from smoke.boot_subprocess import booted_subprocess  # noqa: E402

from .fake_ingest import FakeIngest
from .fake_relay import FakeRelay


def _from_env() -> ServerHandle | None:
    """Build a ServerHandle from KTP_HLDS_* env vars if all three are set."""
    host = os.environ.get("KTP_HLDS_HOST")
    port = os.environ.get("KTP_HLDS_PORT")
    pw = os.environ.get("KTP_HLDS_RCON_PASSWORD")
    if host and port and pw:
        return ServerHandle(host=host, port=int(port), rcon_password=pw)
    return None


def _serverfiles_path() -> Path | None:
    """Return KTP_HLDS_SERVERFILES if set + the dir exists."""
    p = os.environ.get("KTP_HLDS_SERVERFILES")
    if not p:
        return None
    path = Path(p).resolve()
    return path if path.is_dir() else None


# ---------------------------------------------------------------------------
# Discord-relay test wiring (Session 3 prep)
# ---------------------------------------------------------------------------
#
# KTPMatchHandler reads `addons/ktpamx/configs/discord.ini` once at plugin_init
# and POSTs match-event embeds to that URL. Tests that want to assert "a
# Discord embed fired during ktp_match_start" need:
#
#   1. A loopback HTTP listener that captures POSTs (FakeRelay from
#      tests/integration/fake_relay.py).
#   2. A test discord.ini pointing at that listener's URL, written into the
#      serverfiles tree BEFORE hlds boots so plugin_init reads the test config
#      not the production one.
#
# Both fixtures are session-scoped — one mock + one config-write per pytest
# session is sufficient. Teardown restores any pre-existing discord.ini so
# the test serverfiles tree round-trips cleanly.
#
# The `hlds` fixture takes `_discord_ini_setup` as a dependency so config is
# always written before boot — even tests that don't assert against the relay
# benefit from any errant Discord POST being routed to a no-op mock instead
# of leaking to production. In external-server mode (KTP_HLDS_HOST set), the
# config-write fixture is a no-op — operator is responsible for whatever
# discord.ini lives on the live server.

# Stable secrets for the test session. Real production secrets live in
# /etc/ktp/discord-relay.conf and ac.ini on the data server respectively;
# these are fixture-internal.
_TEST_DISCORD_SECRET = "test-discord-secret-fixture-Mq8Xp7tNkBz"
_TEST_AC_SECRET = "test-ac-server-secret-fixture-Vc4kRz9pBwJqX"

# Distinct fake Discord channel IDs per match type. Tests that exercise
# alt match types (Session 4) assert the plugin routes its POST to the
# correct channel by matching on these. The `competitive` ID is kept at
# the original "1234567890123456789" value so existing Session 3 tests
# (test 9, 9b, 13/14/15/16) don't need to update their assertions —
# COMPETITIVE matches route via `discord_channel_id` (base) which now
# maps to this same value.
#
# Format: 19-digit Discord-snowflake-shaped strings with unique tails so
# a routing mismatch in test-failure output points clearly at which
# channel the plugin actually picked.
DISCORD_CHANNELS = {
    "competitive": "1234567890123456789",
    "default":     "9999000000000000002",
    "12man":       "9999000000000000003",
    "scrim":       "9999000000000000004",
    "draft":       "9999000000000000005",
}


@pytest.fixture(scope="session")
def discord_relay():
    """Session-scoped FakeRelay loopback listener. Despite the name, it
    handles BOTH the Discord-relay routes (`/reply` + `/edit`) AND the
    KTPAntiCheat API route (`/api/match/end`) — single mock listener with
    multi-route routing keeps the fixture set small.

    Tests that want to assert "a Discord embed POSTed" use
    `discord_relay.received` / `assert_post_count()`. Tests that want to
    assert "an AC match-end POSTed" use `discord_relay.received_ac_match_end`.

    Started before the `hlds` fixture (via `_discord_ini_setup`'s
    dependency) so the relay's URL is known at config-write time.
    """
    r = FakeRelay(
        expected_secret=_TEST_DISCORD_SECRET,
        expected_ac_secret=_TEST_AC_SECRET,
    )
    r.start()
    try:
        yield r
    finally:
        r.stop()


@pytest.fixture(scope="session")
def _discord_ini_setup(discord_relay):
    """Write a test discord.ini in the serverfiles tree pointing
    KTPMatchHandler at the FakeRelay endpoint. Backs up any existing
    discord.ini and restores it on session teardown.

    No-op in external-server mode (KTP_HLDS_HOST set, no
    KTP_HLDS_SERVERFILES) — the operator's running server has its own
    config and we don't touch it.

    The `hlds` fixture takes this as a dep, so the config is in place
    before plugin_init fires on first hlds boot.
    """
    serverfiles = _serverfiles_path()
    if serverfiles is None:
        # External-server mode (or no env at all): nothing to write.
        # The discord_relay listener is still up; tests that try to
        # assert against it in external mode will see zero POSTs since
        # the live server's discord.ini points at the production relay.
        yield None
        return

    config_dir = serverfiles / "dod" / "addons" / "ktpamx" / "configs"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "discord.ini"
    backup_path = config_dir / "discord.ini.test-backup"

    had_existing = config_path.exists()
    if had_existing:
        backup_path.write_bytes(config_path.read_bytes())

    # Write ALL 7 keys recognized by load_discord_config()
    # (KTPMatchHandler/ktp_matchhandler_discord.inc:898-919).
    # get_discord_channel_id() (ktp_matchhandler_discord.inc:12-51) picks
    # different keys per match type:
    #   COMPETITIVE / KTP_OT  → discord_channel_id (base)
    #   12MAN                  → discord_channel_id_12man (no fallback)
    #   SCRIM                  → discord_channel_id_scrim (no fallback) +
    #                            g_disableDiscord=true blocks all POSTs
    #   DRAFT / DRAFT_OT       → discord_channel_id_draft (no fallback)
    #   default (non-match)    → discord_channel_id_default → fallback base
    #
    # Distinct IDs per key let Session 4 match-type tests assert that
    # plugin code routed each match type to the correct channel. Format:
    # 19 digits (Discord snowflake length), unique tail per type so
    # mismatched routing is obvious in assertion-error output.
    test_config = (
        "; AUTO-GENERATED by tests/integration/conftest.py — do not commit\n"
        "; Restored to original on session teardown.\n"
        f"discord_relay_url={discord_relay.reply_url}\n"
        f"discord_channel_id={DISCORD_CHANNELS['competitive']}\n"
        f"discord_channel_id_default={DISCORD_CHANNELS['default']}\n"
        f"discord_channel_id_12man={DISCORD_CHANNELS['12man']}\n"
        f"discord_channel_id_scrim={DISCORD_CHANNELS['scrim']}\n"
        f"discord_channel_id_draft={DISCORD_CHANNELS['draft']}\n"
        f"discord_auth_secret={discord_relay.expected_secret}\n"
    )
    config_path.write_text(test_config)

    yield None

    # Teardown: restore or remove
    try:
        if had_existing and backup_path.exists():
            config_path.write_bytes(backup_path.read_bytes())
            backup_path.unlink()
        elif config_path.exists() and not had_existing:
            config_path.unlink()
    except Exception:
        # Best-effort restore — failures here shouldn't fail tests
        pass


@pytest.fixture(scope="session")
def _ac_ini_setup(discord_relay):
    """Write a test ac.ini in the serverfiles tree pointing
    KTPMatchHandler's `send_ac_match_end()` at the FakeRelay's AC route.
    Backs up any existing ac.ini and restores it on session teardown.

    No-op in external-server mode (KTP_HLDS_SERVERFILES unset). The hlds
    fixture takes this as a dep, so the config is in place before
    plugin_init's `load_ac_config()` fires.
    """
    serverfiles = _serverfiles_path()
    if serverfiles is None:
        yield None
        return

    config_dir = serverfiles / "dod" / "addons" / "ktpamx" / "configs"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "ac.ini"
    backup_path = config_dir / "ac.ini.test-backup"

    had_existing = config_path.exists()
    if had_existing:
        backup_path.write_bytes(config_path.read_bytes())

    # ac.ini keys per load_ac_config() (KTPMatchHandler.sma:2252-2263):
    # only `api_base_url` and `server_secret` are recognized. The plugin
    # also reads `g_acServerEndpoint` from a separate cvar (server-startup
    # parameter); we don't override that here — the plugin's default is
    # fine for test routing since the mock doesn't filter by endpoint.
    test_config = (
        "; AUTO-GENERATED by tests/integration/conftest.py — do not commit\n"
        "; Restored to original on session teardown.\n"
        f"api_base_url={discord_relay.ac_api_base_url}\n"
        f"server_secret={discord_relay.expected_ac_secret}\n"
    )
    config_path.write_text(test_config)

    yield None

    # Teardown — same restore-or-remove pattern as discord.ini
    try:
        if had_existing and backup_path.exists():
            config_path.write_bytes(backup_path.read_bytes())
            backup_path.unlink()
        elif config_path.exists() and not had_existing:
            config_path.unlink()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# HUD-ingest test wiring — DRAFT for review
# ---------------------------------------------------------------------------
#
# KTPHudObserver.amxx (DoD-hud-observer plugin) POSTs every game event to
# the URL in cvar `dod_hud_url`, with `X-Auth-Key: <dod_hud_key>`. In
# production the URL points at the data-server backend; in tests we
# point it at a FakeIngest loopback listener and assert on captured posts.
#
# The cvars are read ONCE per process by the plugin's `task_init_config`
# (KTPHudObserver.sma:201-233) — the curl headers slist is built once and
# reused for the lifetime of the process (slist UAF prevention, see memory
# `project_amxxcurl_segfault_pr2_missing.md`). Cvars set after first
# init don't take effect until next server restart.
#
# Implication for the fixture: cvars must be in place BEFORE the plugin's
# `task_init_config` fires (~+0.1s after plugin_cfg, which fires after
# server.cfg auto-exec on map load). We write `dod/server.cfg` with the
# cvar overrides — hlds auto-execs it during map load, before AMXX
# completes plugin precache → plugin_cfg → task_init_config.
#
# OPEN DESIGN QUESTION FOR REVIEW: writing dod/server.cfg is the same
# backup-and-restore pattern _discord_ini_setup uses, but hits a
# better-known config file. Alternative considered + rejected:
#   - Append `exec cfg/ktp_hud_test.cfg` to tests/smoke/fixtures/
#     test_server.cfg → write the cvar fragment to a separate file. Less
#     intrusive on dod/server.cfg, but couples Tier 1's smoke cfg to a
#     Tier 2 concern. Open to reconsidering on review.

# Stable secret for the test session. Real production secret lives in
# the per-server `dod_hud_key` cvar set in server.cfg on the data server;
# this is fixture-internal and never reaches a real network.
_TEST_HUD_AUTH_KEY = "test-hud-auth-fixture-Bz3pT9rQwKxN"


@pytest.fixture(scope="session")
def fake_ingest():
    """Session-scoped FakeIngest loopback listener. Tests assert that
    KTPHudObserver POSTed an event of the expected shape during a state-
    machine transition.

    Started before the `hlds` fixture (via `_hud_cvars_setup`'s
    dependency) so the listener URL is known at config-write time.
    """
    i = FakeIngest(expected_auth_key=_TEST_HUD_AUTH_KEY)
    i.start()
    try:
        yield i
    finally:
        i.stop()


@pytest.fixture(scope="session")
def _hud_cvars_setup(fake_ingest):
    """Write a test `dod/server.cfg` setting `dod_hud_url` + `dod_hud_key`
    to the FakeIngest listener BEFORE the plugin's `task_init_config`
    builds its persistent curl headers slist.

    Backs up any existing dod/server.cfg and restores it on session
    teardown. No-op in external-server mode (no KTP_HLDS_SERVERFILES).
    """
    serverfiles = _serverfiles_path()
    if serverfiles is None:
        # External-server mode: operator's server has its own server.cfg
        # and dod_hud_url/key cvars; we don't touch them. Tests that try
        # to assert against fake_ingest in external mode will see zero
        # POSTs since the live plugin points at the production backend.
        yield None
        return

    cfg_path = serverfiles / "dod" / "server.cfg"
    backup_path = serverfiles / "dod" / "server.cfg.test-backup"

    had_existing = cfg_path.exists()
    existing_text = cfg_path.read_text() if had_existing else ""
    if had_existing:
        backup_path.write_bytes(cfg_path.read_bytes())

    # Append cvar overrides to whatever was already in server.cfg
    # (preserve operator settings; only the HUD cvars are managed here).
    # Use semicolon comments — hlds engine strips lines starting with `//`
    # but `;` is also a comment per goldsrc `Cmd_Cmds_f` (engine source).
    test_block = (
        "\n"
        "// AUTO-GENERATED by tests/integration/conftest.py — do not commit.\n"
        "// Restored to original on session teardown.\n"
        f"dod_hud_url \"{fake_ingest.url}\"\n"
        f"dod_hud_key \"{fake_ingest.expected_auth_key}\"\n"
    )
    cfg_path.write_text(existing_text + test_block)

    yield None

    # Teardown — restore or remove
    try:
        if had_existing and backup_path.exists():
            cfg_path.write_bytes(backup_path.read_bytes())
            backup_path.unlink()
        elif cfg_path.exists() and not had_existing:
            cfg_path.unlink()
    except Exception:
        pass


@pytest.fixture(scope="session")
def hlds(request, _discord_ini_setup, _ac_ini_setup, _hud_cvars_setup):
    """Yield a ServerHandle to a hlds running with KTPMatchHandler test-mode
    + KTPWitness loaded. Session-scoped — boots once per test session.

    The `_resetting_handle` indirection wraps the ServerHandle so each test
    can call `.reset()` (or rely on the autouse `_clean_state` fixture below)
    to clear the match-flow state machine. We don't restart hlds between
    tests — the cost is too high for a 4-test spine and the test-mode rcons
    can fully reset state in <100ms.
    """
    external = _from_env()
    if external is not None:
        try:
            external.wait_ready(timeout=5.0, poll_interval=0.5)
        except Exception as ex:
            # FAIL, don't skip: the operator EXPLICITLY pointed the suite at a
            # server (KTP_HLDS_HOST set). Skipping here turned a down/wrong
            # server into a green run with zero tests executed — the same
            # skip-as-pass channel as the sql/migrations CI incident.
            pytest.fail(
                f"KTP_HLDS_HOST is set but the server at {external.host}:{external.port} "
                f"didn't answer rcon: {ex} — refusing to skip (a down target must not "
                f"read as a green run); unset KTP_HLDS_HOST to use subprocess mode",
                pytrace=False,
            )
        yield external
        return

    serverfiles = _serverfiles_path()
    if serverfiles is None:
        pytest.skip(
            "Tier 2 integration tests skipped — neither KTP_HLDS_HOST nor "
            "KTP_HLDS_SERVERFILES is set. See "
            "KTPInfrastructure/tests/integration/README.md for environment "
            "setup."
        )

    # Subprocess boot. Map dod_anzio is the cheapest stock map (smallest
    # entdata, fastest precache) — fine for state-machine tests that don't
    # care about the running map. test_server.cfg is shared with Tier 1.
    smoke_cfg = _SMOKE_DIR / "fixtures" / "test_server.cfg"
    # Copy/link cfg into dod/ if not already present. Idempotent.
    target_cfg = serverfiles / "dod" / smoke_cfg.name
    if not target_cfg.exists():
        target_cfg.write_text(smoke_cfg.read_text())

    with booted_subprocess(
        serverfiles,
        map_name="dod_anzio",
        # Must match the rcon_password set in test_server.cfg — the cfg
        # executes after +rcon_password CLI processing and overrides it.
        rcon_password="smoketest",
        server_cfg=smoke_cfg.name,
        boot_timeout=120.0,
    ) as handle:
        yield handle


@pytest.fixture(autouse=True)
def _reset_match_state(request):
    """Auto-fired before every test: clear match-flow state machine via
    `amx_ktp_test_reset` so each test starts from idle. Cheaper than a full
    server reboot per test, and the test-mode reset is comprehensive enough
    to act as a clean slate for the spine tests (Sessions 3-5 may need
    finer cleanup if they touch localinfo or other persistent state).

    LAZY on `hlds`: only resolves the hlds fixture for tests that already
    declared a dependency on it. Pure mock-side tests (e.g. test_fake_relay)
    that don't touch hlds skip the reset entirely — without this guard the
    autouse fixture would force-skip every integration test in env-less mode.
    """
    if "hlds" not in request.fixturenames:
        yield
        return
    # Pre-test reset — handle the case where a prior test left the state
    # machine partway through.
    try:
        hlds = request.getfixturevalue("hlds")
        hlds.rcon("amx_ktp_test_reset")
    except Exception:
        # Best-effort: if rcon is briefly unresponsive, the test itself
        # will surface the problem rather than the fixture silently failing.
        pass
    yield
    # Post-test reset is intentionally omitted — leaves state visible to
    # an operator inspecting a failed-test server. Pre-test reset on the
    # next test handles cleanup.


@pytest.fixture(autouse=True)
def _reset_fake_ingest(request):
    """Auto-fired before every test that uses fake_ingest: clear the
    captured-posts list so each test starts from an empty state.

    Lazy on the fixture name like `_reset_match_state` — tests not
    depending on fake_ingest skip the reset entirely. Mock-side
    `test_fake_ingest.py` uses a function-scoped fixture and is naturally
    isolated; this reset only matters for the session-scoped fixture
    shared across `test_hud_observer_contract.py` tests.
    """
    if "fake_ingest" not in request.fixturenames:
        yield
        return
    try:
        request.getfixturevalue("fake_ingest").reset()
    except Exception:
        # Best-effort, same rationale as _reset_match_state's try/except.
        pass
    yield


# ──────────────────────────────────────────────────────────────────────────
# Tier 2 post-run reporting (1.5.22 sub-followup of Session 5 finishing)
# ──────────────────────────────────────────────────────────────────────────
#
# When KTP_TIER2_REPORT_PATH is set (CI workflow), pytest_sessionfinish
# writes a session-summary JSON for the post-pytest workflow step to read
# and POST as a Discord embed. The hook is a no-op when the env var is
# unset — preserves the dev-loop's "no extra files written" behavior.
#
# Failure-list shape: each failed test contributes its node_id (e.g.,
# "tests/integration/test_match_flow_spine.py::test_3_setup_match_enters_prestart")
# to a list. The first 5 land in the embed body; longer lists get a
# "…and N more" sentinel. Errors (collection failures, fixture errors)
# land in a separate list — Discord shows them as a unified "Failed tests"
# field but the JSON keeps them distinct so future enhancements can split.

def pytest_sessionstart(session):
    """Record session start time on the session object — load-bearing for
    `pytest_sessionfinish`'s duration calculation. Previously we read
    `terminalreporter._sessionstarttime` (a private attribute), which would
    silently fall back to `time.time()` (= zero duration) on a future pytest
    bump if the attribute name changes. Recording on the public session
    object is forward-compatible."""
    session.config._ktp_session_start = time.time()


def pytest_sessionfinish(session, exitstatus):
    """Emit tier2-report.json with pass/fail/skip/error counts + duration +
    failed-test node IDs. Skipped if KTP_TIER2_REPORT_PATH is unset."""
    out_path = os.environ.get("KTP_TIER2_REPORT_PATH")
    if not out_path:
        return

    # Duration via our own session-start hook (forward-compat) with a
    # defensive fallback for the case where pytest_sessionstart didn't
    # run (e.g., conftest reload mid-session — exotic but cheap to guard).
    started = getattr(session.config, "_ktp_session_start", None)
    duration_sec = (time.time() - started) if started is not None else None

    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is None:
        # Defensive — terminalreporter is a built-in plugin and should always
        # be loaded under normal pytest invocation. If it isn't (very minimal
        # config), write a degraded report rather than crashing the session.
        report = {
            "passed": 0, "failed": 0, "skipped": 0, "errors": 0, "rerun": 0,
            "total": session.testscollected,
            "duration_sec": duration_sec if duration_sec is not None else 0.0,
            "exitstatus": int(exitstatus),
            "failures": [],
            "error_tests": [],
            "_note": "terminalreporter unavailable — counts degraded",
        }
    else:
        stats = reporter.stats
        failures = [r.nodeid for r in stats.get("failed", [])]
        errors = [r.nodeid for r in stats.get("error", [])]
        report = {
            "passed": len(stats.get("passed", [])),
            "failed": len(failures),
            "skipped": len(stats.get("skipped", [])),
            "errors": len(errors),
            "rerun": len(stats.get("rerun", [])),
            "total": session.testscollected,
            "duration_sec": duration_sec if duration_sec is not None else 0.0,
            "exitstatus": int(exitstatus),
            "failures": failures,
            "error_tests": errors,
        }

    try:
        Path(out_path).write_text(json.dumps(report, indent=2), encoding="utf-8")
    except OSError as e:
        # Don't fail the session on a report-write error — just log and move on.
        # The pytest run's own pass/fail status is the load-bearing signal.
        reporter and reporter.write_line(
            f"WARNING: failed to write Tier 2 report to {out_path}: {e}",
            yellow=True,
        )
