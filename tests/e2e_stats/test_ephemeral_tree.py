"""Unit tests for the ephemeral-tree write-through guard.

These are the tests that matter most in this package, because the failure they
guard against is silent and expensive: a hardlinked copy plus a careless
`open(path, "w")` edits the *fleet-matching* serverfiles tree in place, and
`help.md` says re-syncing that tree is deliberately manual work.

Runs anywhere — no hlds, no bot, no MySQL. Pure filesystem.
"""

from __future__ import annotations

import os
import pytest

from .ephemeral_tree import EphemeralTree, TreeIntegrityError


def _fake_serverfiles(root):
    """Minimal tree shaped enough for EphemeralTree.build to accept it."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "hlds_linux").write_text("#!/bin/sh\n")
    dod = root / "dod"
    (dod / "addons" / "amxmodx" / "configs").mkdir(parents=True)
    (dod / "test_server.cfg").write_text("hostname original\n")
    (dod / "addons" / "amxmodx" / "configs" / "plugins.ini").write_text("stock.amxx\n")
    (dod / "liblist.gam").write_text("gamedll original\n")
    return root


@pytest.fixture
def source(tmp_path):
    return _fake_serverfiles(tmp_path / "serverfiles")


@pytest.mark.parametrize("copy_mode", ["hardlink", "full"])
def test_write_text_does_not_touch_source(source, tmp_path, copy_mode):
    """The core guarantee, asserted for both copy modes.

    In hardlink mode this only holds because `_prepare` unlinks first. Delete
    that unlink and this test fails — which is the whole point of it existing.
    """
    with EphemeralTree.build(source, copy_mode=copy_mode, parent=tmp_path) as tree:
        tree.write_text("dod/test_server.cfg", "hostname overwritten\n")
        assert (tree.path / "dod" / "test_server.cfg").read_text() == "hostname overwritten\n"
        # The source must be exactly as it was.
        assert (source / "dod" / "test_server.cfg").read_text() == "hostname original\n"


def test_hardlink_mode_actually_links(source, tmp_path):
    """Guard the performance property too.

    If this ever fails, hardlink mode has silently degraded to copying (usually
    a cross-filesystem `parent`), and a per-run 2 GB tree becomes a per-run 2 GB
    copy. Correct, but slow enough to make the lane unaffordable — worth
    knowing rather than discovering as 'the nightly got slow'.
    """
    tree = EphemeralTree.build(source, copy_mode="hardlink", parent=tmp_path, keep=True)
    try:
        src_stat = (source / "dod" / "liblist.gam").stat()
        dst_stat = (tree.path / "dod" / "liblist.gam").stat()
        assert dst_stat.st_ino == src_stat.st_ino, "hardlink mode did not link"
    finally:
        tree._keep = False
        tree.cleanup()


def test_overlay_file_does_not_touch_source(source, tmp_path):
    external = tmp_path / "marinebot.so"
    external.write_bytes(b"\x7fELF fake bot")
    with EphemeralTree.build(source, parent=tmp_path) as tree:
        tree.overlay_file(external, "dod/addons/marinebot/marinebot.so")
        assert (tree.path / "dod/addons/marinebot/marinebot.so").read_bytes() == b"\x7fELF fake bot"
    assert not (source / "dod/addons/marinebot").exists(), \
        "bot leaked into the fleet-matching tree"


def test_overlay_file_shadowing_an_existing_file_leaves_source_intact(source, tmp_path):
    """Overlaying a path that already exists in the source is the dangerous
    case — that is where write-through would actually bite."""
    external = tmp_path / "plugins.ini"
    external.write_text("test-mode.amxx\nKTPWitness.amxx\n")
    with EphemeralTree.build(source, parent=tmp_path) as tree:
        tree.overlay_file(external, "dod/addons/amxmodx/configs/plugins.ini")
        assert "KTPWitness" in (tree.path / "dod/addons/amxmodx/configs/plugins.ini").read_text()
    assert (source / "dod/addons/amxmodx/configs/plugins.ini").read_text() == "stock.amxx\n"


def test_verify_source_untouched_catches_a_leak(source, tmp_path):
    """Simulate the regression the guard exists for: something writes to the
    source after the tree recorded its hash. Teardown must fail loudly rather
    than leave a quietly-drifted tree behind."""
    tree = EphemeralTree.build(source, parent=tmp_path, keep=True)
    try:
        tree.write_text("dod/test_server.cfg", "hostname ephemeral\n")
        # A leak, by whatever route.
        (source / "dod" / "test_server.cfg").write_text("hostname CLOBBERED\n")
        with pytest.raises(TreeIntegrityError) as ei:
            tree.verify_source_untouched()
        assert "dod/test_server.cfg" in str(ei.value)
        assert "tripwire" in str(ei.value).lower()
    finally:
        tree._keep = False
        tree.cleanup_ignoring_integrity()


def test_refuses_a_tree_without_hlds(tmp_path):
    empty = tmp_path / "not-serverfiles"
    empty.mkdir()
    with pytest.raises(FileNotFoundError, match="hlds_linux"):
        EphemeralTree.build(empty, parent=tmp_path)


def test_refuses_writes_outside_the_tree(source, tmp_path):
    with EphemeralTree.build(source, parent=tmp_path) as tree:
        with pytest.raises(ValueError, match="outside the ephemeral tree"):
            tree.write_text("../escaped.cfg", "nope")


def test_cleanup_removes_the_tree(source, tmp_path):
    tree = EphemeralTree.build(source, parent=tmp_path)
    path = tree.path
    assert path.is_dir()
    tree.cleanup()
    assert not path.exists()
    # Source survives teardown.
    assert (source / "hlds_linux").exists()


def test_keep_preserves_the_tree(source, tmp_path):
    tree = EphemeralTree.build(source, parent=tmp_path, keep=True)
    path = tree.path
    tree.cleanup()
    assert path.is_dir(), "--keep should leave the tree for inspection"
    tree._keep = False
    tree.cleanup()
    assert not path.exists()


def test_excluded_patterns_are_not_copied(source, tmp_path):
    """Prior runs' logs and rollback copies are large and useless here."""
    (source / "old.log").write_text("noise\n")
    (source / "stack-bak-20260101").mkdir()
    (source / "stack-bak-20260101" / "junk").write_text("x\n")
    with EphemeralTree.build(source, parent=tmp_path) as tree:
        assert not (tree.path / "old.log").exists()
        assert not (tree.path / "stack-bak-20260101").exists()


def test_in_place_writes_directly_and_makes_no_copy(source):
    """The containerised lane's mode: /opt/hlds IS the working tree."""
    tree = EphemeralTree.in_place(source)
    assert tree.path == source
    assert tree.is_in_place
    tree.write_text("dod/test_server.cfg", "hostname in-place\n")
    assert (source / "dod" / "test_server.cfg").read_text() == "hostname in-place\n"


def test_in_place_teardown_does_not_report_integrity_failure(source):
    """In-place writes intentionally change 'the source', so the shadow-hash
    check must be disabled — otherwise every containerised run would end in a
    spurious TreeIntegrityError."""
    with EphemeralTree.in_place(source) as tree:
        tree.write_text("dod/test_server.cfg", "hostname in-place\n")
        tree.overlay_file(_fake_bot(source.parent), "dod/addons/marinebot/marinebot.so")
    # Exiting the context ran verify_source_untouched(); no exception is the
    # assertion. And the tree must still exist — deleting /opt/hlds would be
    # a spectacular own goal.
    assert (source / "hlds_linux").exists()


def _fake_bot(where):
    p = where / "marinebot.so"
    p.write_bytes(b"\x7fELF fake bot")
    return p


def test_in_place_refuses_a_tree_without_hlds(tmp_path):
    empty = tmp_path / "nope"
    empty.mkdir()
    with pytest.raises(FileNotFoundError, match="hlds_linux"):
        EphemeralTree.in_place(empty)


def test_in_place_still_refuses_writes_outside_the_tree(source):
    tree = EphemeralTree.in_place(source)
    with pytest.raises(ValueError, match="outside the ephemeral tree"):
        tree.write_text("../escaped.cfg", "nope")


def test_symlinks_are_preserved_not_dereferenced(source, tmp_path):
    """serverfiles trees carry symlinks (steam sdk paths). Dereferencing them
    would inflate the copy and can break dlopen resolution."""
    target = source / "dod" / "liblist.gam"
    link = source / "dod" / "liblist_link.gam"
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlink creation not permitted on this platform/user")
    with EphemeralTree.build(source, parent=tmp_path) as tree:
        assert (tree.path / "dod" / "liblist_link.gam").is_symlink()
