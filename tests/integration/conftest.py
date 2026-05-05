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

import os
import sys
from pathlib import Path

import pytest

# Reach into the Tier 1 smoke harness for ServerHandle, boot_subprocess.
# Path adjustment: tests/integration/ is a sibling of tests/smoke/.
_SMOKE_DIR = Path(__file__).resolve().parent.parent / "smoke"
if str(_SMOKE_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_SMOKE_DIR.parent))

from smoke import ServerHandle  # noqa: E402
from smoke.boot_subprocess import booted_subprocess  # noqa: E402

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

# Stable secret for the test session. Real production secret is in
# /etc/ktp/discord-relay.conf on the data server; this is fixture-internal.
_TEST_DISCORD_SECRET = "test-discord-secret-fixture-Mq8Xp7tNkBz"


@pytest.fixture(scope="session")
def discord_relay():
    """Session-scoped FakeRelay loopback listener. Tests that want to
    assert "a Discord embed POSTed" use `discord_relay.received` /
    `discord_relay.assert_post_count()`.

    Started before the `hlds` fixture (via `_discord_ini_setup`'s
    dependency) so the relay's URL is known at config-write time.
    """
    r = FakeRelay(expected_secret=_TEST_DISCORD_SECRET)
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
    # (KTPMatchHandler/ktp_matchhandler_discord.inc:898-919). Per the
    # SESSION_3_DISCORD_EMISSION_AUDIT.md, get_discord_channel_id() picks
    # different keys per match type (12man/scrim/draft require explicit
    # channels with no fallback). Pointing every per-type channel at the
    # same fake ID ensures ANY match-type-driven test routes its POST to
    # the same mock — fixture stays match-type-agnostic.
    fake_channel = "1234567890123456789"
    test_config = (
        "; AUTO-GENERATED by tests/integration/conftest.py — do not commit\n"
        "; Restored to original on session teardown.\n"
        f"discord_relay_url={discord_relay.reply_url}\n"
        f"discord_channel_id={fake_channel}\n"
        f"discord_channel_id_default={fake_channel}\n"
        f"discord_channel_id_12man={fake_channel}\n"
        f"discord_channel_id_scrim={fake_channel}\n"
        f"discord_channel_id_draft={fake_channel}\n"
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
def hlds(request, _discord_ini_setup):
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
            pytest.skip(
                f"KTP_HLDS_HOST set but server at {external.host}:{external.port} "
                f"didn't answer rcon: {ex}"
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
