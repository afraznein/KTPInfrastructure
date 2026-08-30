"""Unit tests for scripts/sync-runner-stack.py.

No SSH: only the pure half is exercised -- which files the tool would
overwrite on the Tier-2 runner, and which it refuses to touch. That split
is the whole safety property. Overwriting a KTP_TEST_MODE plugin with the
fleet's production build leaves a suite that cannot drive itself, and the
failure looks like a broken harness rather than a bad sync.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / filename)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


pytest.importorskip("paramiko", reason="sync-runner-stack imports paramiko at module scope")
sync = _load("sync_runner_stack", "sync-runner-stack.py")
drift = _load("ktp_tier2_stack_drift", "ktp-tier2-stack-drift.py")


def test_sync_set_covers_everything_the_tripwire_alerts_on():
    """The synced set is the alerted set, or the tripwire alerts on something
    nothing can fix -- which is exactly the gap this tool was written to close."""
    paths, _ = sync.sync_set()
    for path in drift.STACK_FILES + drift.PLUGINS_STRICT:
        assert path in paths


def test_test_mode_plugins_are_never_synced():
    paths, excluded = sync.sync_set()
    for path in drift.PLUGINS_TESTMODE:
        assert path in excluded
        assert path not in paths


def test_hud_observer_is_never_synced():
    """It is rebuilt from upstream by tier2-integration.yml on every run, so a
    copy from the fleet is overwritten within one run anyway -- and would mask
    the version the contract test asserts against in the meantime."""
    paths, excluded = sync.sync_set()
    hud = "dod/addons/ktpamx/plugins/KTPHudObserver.amxx"
    assert hud in excluded
    assert hud not in paths


def test_sync_and_excluded_are_disjoint():
    paths, excluded = sync.sync_set()
    assert not excluded.intersection(paths)


def test_no_duplicate_paths():
    """A path listed twice is copied twice, and the second copy's backup
    overwrites the first -- so the pre-sync artifact is silently lost."""
    paths, _ = sync.sync_set()
    assert len(paths) == len(set(paths))
