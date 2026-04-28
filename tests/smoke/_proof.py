"""End-to-end harness proof — Session 1 / Tier 1.

NOT a real test. Exists to validate that the harness can:
  1. Boot hlds_linux from the local KTP DoD Server tree (via WSL on Windows)
  2. Reach rcon
  3. Successfully assert against `amx modules` and `amx plugins` output

Once Tier 1 ships properly, replace this file with the real per-project
pytest suites it informs.

Run from KTPInfrastructure root:
    python -m tests.smoke._proof
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from tests.smoke.asserts import assert_modules_loaded, assert_plugins_running
from tests.smoke.boot_subprocess import booted_subprocess

REPO_ROOT = Path(__file__).resolve().parents[3]
SERVERFILES = REPO_ROOT / "KTP DoD Server" / "serverfiles"
FIXTURE_CFG = Path(__file__).parent / "fixtures" / "test_server.cfg"

EXPECTED_MODULES = [
    "amxxcurl",
    "reapi",
    "dodx",
    "dodfun",
    "fun",
    "engine",
    "fakemeta",
    "hamsandwich",
]

EXPECTED_PLUGINS = [
    "admin.amxx",
    "KTPMatchHandler.amxx",
    "KTPHLTVRecorder.amxx",
]


def main() -> int:
    if not (SERVERFILES / "hlds_linux").exists():
        print(f"FAIL: hlds_linux not found at {SERVERFILES}", file=sys.stderr)
        return 2

    # Stage the fixture cfg into dod/. Engine looks for it there.
    target_cfg = SERVERFILES / "dod" / "test_server.cfg"
    shutil.copy(FIXTURE_CFG, target_cfg)
    print(f"staged {target_cfg.name} into {target_cfg.parent}")

    try:
        with booted_subprocess(
            SERVERFILES,
            map_name="dod_anzio",
            rcon_password="smoketest",
            server_cfg="test_server.cfg",
        ) as handle:
            print(f"booted; rcon at {handle.host}:{handle.port}")

            print(handle.rcon("version"))

            assert_modules_loaded(handle, EXPECTED_MODULES)
            print(f"OK assert-modules ({len(EXPECTED_MODULES)} expected)")

            assert_plugins_running(handle, EXPECTED_PLUGINS)
            print(f"OK assert-plugins ({len(EXPECTED_PLUGINS)} expected)")

            print("\nSession 1 proof: GREEN")
        return 0
    finally:
        try:
            target_cfg.unlink()
        except FileNotFoundError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
