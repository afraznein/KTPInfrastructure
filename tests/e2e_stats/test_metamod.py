"""Unit tests for topology switching.

The one that matters is `test_enable_metamod_disables_extensions`: leaving both
loaders active loads `ktpamx_i386.so` twice in one process — once as a ReHLDS
engine extension, once as a Metamod plugin — and two copies of AMXX registering
the same natives, forwards and cvars would poison every result the lane
produced.

Pure filesystem; no hlds, no Docker.
"""

from __future__ import annotations

import pytest

from .bot_driver import MARINEBOT, NEW_BOT
from .ephemeral_tree import EphemeralTree
from .metamod import (EXTENSIONS, LIBLIST, PLUGINS_INI, TopologyError,
                      current_gamedll, describe, enable_metamod,
                      restore_production)

_LIBLIST = 'game "Day of Defeat"\nversion "1.3"\ngamedll_linux "dlls/dod.so"\n'
_EXTENSIONS = "addons/ktpamx/dlls/ktpamx_i386.so\n"


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "hlds"
    (root / "dod" / "addons" / "metamod").mkdir(parents=True)
    (root / "hlds_linux").write_text("#!/bin/sh\n")
    (root / "dod" / "liblist.gam").write_text(_LIBLIST)
    (root / "dod" / "liblist.gam.production").write_text(_LIBLIST)
    (root / "dod" / "addons" / "extensions.ini").write_text(_EXTENSIONS)
    (root / "dod" / "addons" / "extensions.ini.production").write_text(_EXTENSIONS)
    (root / "dod" / "addons" / "metamod" / "metamod_i386.so").write_bytes(b"\x7fELF")
    return EphemeralTree.in_place(root)


def test_starts_in_production_topology(tree):
    assert current_gamedll(tree) == "dlls/dod.so"


def test_enable_metamod_points_gamedll_at_metamod(tree):
    topo = enable_metamod(tree, bot_spec=NEW_BOT)
    assert current_gamedll(tree) == "addons/metamod/metamod_i386.so"
    assert topo.extra_args == ["+localinfo", "mm_gamedll", "dlls/dod.so"]


def test_enable_metamod_disables_extensions(tree):
    """THE load-bearing one — see the module docstring."""
    enable_metamod(tree, bot_spec=NEW_BOT)
    body = (tree.path / EXTENSIONS).read_text()
    active = [ln for ln in body.splitlines() if ln.strip() and not ln.startswith(";")]
    assert active == [], f"extensions.ini still active: {active} — ktpamx would load twice"


def test_plugins_ini_lists_ktpamx_first_then_bot(tree):
    """AMXX has to be up before the bot registers against it."""
    enable_metamod(tree, bot_spec=NEW_BOT)
    lines = [ln for ln in (tree.path / PLUGINS_INI).read_text().splitlines()
             if ln.strip() and not ln.startswith(";")]
    assert lines == ["linux addons/ktpamx/dlls/ktpamx_i386.so",
                     "linux new_bot/new_bot_mm.so"]


def test_enable_metamod_without_a_bot_still_works(tree):
    """Boot B minus the bot is a useful third data point: it separates
    'Metamod perturbs the stack' from 'the bot perturbs the stack'."""
    enable_metamod(tree)
    lines = [ln for ln in (tree.path / PLUGINS_INI).read_text().splitlines()
             if ln.strip() and not ln.startswith(";")]
    assert lines == ["linux addons/ktpamx/dlls/ktpamx_i386.so"]


def test_rejects_a_bot_that_is_not_a_metamod_plugin(tree):
    """Marine Bot loads via mm_gamedll, not as a plugin; putting it in
    plugins.ini would silently do nothing."""
    with pytest.raises(TopologyError, match="not a Metamod plugin"):
        enable_metamod(tree, bot_spec=MARINEBOT)


def test_restore_is_byte_exact(tree):
    """Boot A must be production-identical or the differential measures our own
    edits rather than Metamod's effect."""
    before = (tree.path / LIBLIST).read_bytes()
    enable_metamod(tree, bot_spec=NEW_BOT)
    assert (tree.path / LIBLIST).read_bytes() != before
    restore_production(tree)
    assert (tree.path / LIBLIST).read_bytes() == before
    assert (tree.path / EXTENSIONS).read_text() == _EXTENSIONS


def test_restore_removes_plugins_ini(tree):
    """A stale plugins.ini would let a later run load a bot it never asked for."""
    enable_metamod(tree, bot_spec=NEW_BOT)
    assert (tree.path / PLUGINS_INI).is_file()
    restore_production(tree)
    assert not (tree.path / PLUGINS_INI).exists()


def test_round_trip_is_idempotent(tree):
    for _ in range(3):
        enable_metamod(tree, bot_spec=NEW_BOT)
        restore_production(tree)
    assert current_gamedll(tree) == "dlls/dod.so"


def test_enable_requires_metamod_present(tree):
    (tree.path / "dod" / "addons" / "metamod" / "metamod_i386.so").unlink()
    with pytest.raises(TopologyError, match="not present"):
        enable_metamod(tree, bot_spec=NEW_BOT)


def test_restore_requires_pristine_copies(tree):
    (tree.path / "dod" / "liblist.gam.production").unlink()
    with pytest.raises(TopologyError, match="pristine copy"):
        restore_production(tree)


def test_describe_reports_both_loaders(tree):
    enable_metamod(tree, bot_spec=NEW_BOT)
    d = describe(tree)
    assert d["gamedll_linux"] == "addons/metamod/metamod_i386.so"
    assert d["extensions_ini_active_lines"] == []
    assert "linux new_bot/new_bot_mm.so" in d["metamod_plugins"]
