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


# --- runner-idle guard --------------------------------------------------------

TREE = "/opt/ktp-tier2-runner/serverfiles"


def _probe(*procs, tree=TREE):
    return "\n".join([f"TREE\t{tree}"] + ["\t".join(p) for p in procs])


def test_relative_launch_from_inside_the_tree_is_busy():
    """The harness runs `./hlds_linux` with cwd=serverfiles, so the tree path is
    in no command line -- only exe and cwd carry it."""
    out = _probe(("4242", f"{TREE}/hlds_linux", TREE))
    assert len(sync.runner_processes(out)) == 1


def test_a_game_server_elsewhere_is_not_the_runner():
    home = "/home/dodserver/dod-27015/serverfiles"
    assert sync.runner_processes(_probe(("77", f"{home}/hlds_linux", home))) == []


def test_a_sibling_directory_sharing_the_prefix_is_not_the_tree():
    other = TREE + "-old"
    assert sync.runner_processes(_probe(("5", f"{other}/hlds_linux", other))) == []


def test_a_replaced_binary_still_mapped_is_busy():
    assert len(sync.runner_processes(_probe(("9", f"{TREE}/hlds_linux (deleted)", "?")))) == 1


def test_an_unreadable_process_counts_as_busy():
    assert len(sync.runner_processes(_probe(("9", "?", "?")))) == 1


def test_no_hlds_linux_is_idle(monkeypatch):
    monkeypatch.setattr(sync, "run", lambda ssh, cmd, timeout=120: (_probe(), ""))
    assert sync.check_runner_idle(object()) is None


def test_a_busy_runner_blocks_behind_the_override_flag(monkeypatch, capsys):
    out = _probe(("4242", f"{TREE}/hlds_linux", TREE))
    monkeypatch.setattr(sync, "run", lambda ssh, cmd, timeout=120: (out, ""))
    blocker = sync.check_runner_idle(object())
    assert blocker is not None and blocker[1] == "--ignore-running"
    assert "4242" in capsys.readouterr().out


def test_an_unanswered_probe_is_not_an_idle_runner(monkeypatch):
    """A dropped session returns empty output; read as "no processes", the guard
    would wave through exactly the case it cannot see."""
    monkeypatch.setattr(sync, "run", lambda ssh, cmd, timeout=120: ("", ""))
    blocker = sync.check_runner_idle(object())
    assert blocker is not None and "could not probe" in blocker[0]


def test_the_probe_resolves_processes_not_command_lines():
    probe = sync._IDLE_PROBE.format(tree=TREE)
    assert "/proc/$p/exe" in probe and "/proc/$p/cwd" in probe
    assert "pgrep -af" not in probe


def test_the_probe_sees_a_relative_launch_on_a_real_kernel(tmp_path):
    """End to end: a process named hlds_linux started as `./hlds_linux` from inside
    the tree -- the exact shape the old command-line match never saw."""
    import shutil
    import subprocess
    import time

    if not sys.platform.startswith("linux") or not shutil.which("pgrep") or not shutil.which("sleep"):
        pytest.skip("needs Linux /proc, pgrep and sleep")
    tree = tmp_path / "serverfiles"
    tree.mkdir()
    shutil.copy(shutil.which("sleep"), tree / "hlds_linux")
    proc = subprocess.Popen(["./hlds_linux", "30"], cwd=tree)
    try:
        time.sleep(0.3)
        probe = lambda t: subprocess.run(["bash", "-c", sync._IDLE_PROBE.format(tree=t)],
                                         capture_output=True, text=True).stdout
        out = probe(tree)
        assert any(f"pid {proc.pid} " in b for b in sync.runner_processes(out)), out
        elsewhere = probe(tmp_path / "elsewhere")
        assert not any(f"pid {proc.pid} " in b for b in sync.runner_processes(elsewhere)), elsewhere
    finally:
        proc.kill()
        proc.wait()
