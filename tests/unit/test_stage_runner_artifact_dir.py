"""Unit tests for stage-runner.py's artifact_dir().

Regression cover for two "everything .so is a module" traps: the fix that
landed 2026-08-14 (6b22c4d) split modules from plugins by extension but
still routed the KTPAMXX core (dod/addons/ktpamx/dlls/ktpamx_i386.so,
confirmed by ktp-tier2-stack-drift.py's STACK_FILES) into MODULE_DIR --
the same "not in the dir I swept" failure one level deeper.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

# stage-runner.py sys.exit()s at import when paramiko is absent, which pytest
# surfaces as a collection INTERNALERROR that takes the whole tier-1 job down.
# artifact_dir() never touches paramiko, so a stub is enough for these tests.
if "paramiko" not in sys.modules:
    try:
        import paramiko  # noqa: F401
    except ImportError:
        sys.modules["paramiko"] = types.ModuleType("paramiko")

SCRIPT = Path(__file__).parents[2] / "scripts" / "stage-runner.py"
SPEC = importlib.util.spec_from_file_location("stage_runner", SCRIPT)
assert SPEC and SPEC.loader
stage_runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stage_runner)


def test_plugin_resolves_to_plugin_dir():
    assert stage_runner.artifact_dir("KTPMatchHandler.amxx") == "dod/addons/ktpamx/plugins"


def test_module_resolves_to_module_dir():
    assert stage_runner.artifact_dir("dodx_ktp_i386.so") == "dod/addons/ktpamx/modules"
    assert stage_runner.artifact_dir("reapi_ktp_i386.so") == "dod/addons/ktpamx/modules"
    assert stage_runner.artifact_dir("amxxcurl_ktp_i386.so") == "dod/addons/ktpamx/modules"


def test_core_resolves_to_dlls_dir_not_module_dir():
    assert stage_runner.artifact_dir("ktpamx_i386.so") == "dod/addons/ktpamx/dlls"
