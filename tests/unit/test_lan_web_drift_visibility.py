"""The lan-web drift check has to see everything rsync --delete can delete.

It once compared seven file suffixes while --delete saw the whole tree, so 29
.bak-* fossils on /opt/lan-web were invisible and the pre-flight reported clean.
These tests pin the shape of the fix: an unknown file is VISIBLE, and the only
blind spots are the ones written down in provision/lan-web-sync.exclude.

Both directions matter. A walker that returns every path passes half of this
file; the exclusion assertions are what stop "sees everything" from meaning
"refuses everything".
"""
from __future__ import annotations

import importlib.util
import os
import sys

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DRIFT_PY = os.path.join(REPO_ROOT, "scripts", "ktp-lan-web-drift.py")
EXCLUDE_FILE = os.path.join(REPO_ROOT, "provision", "lan-web-sync.exclude")


def _load():
    spec = importlib.util.spec_from_file_location("ktp_lan_web_drift", DRIFT_PY)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ktp_lan_web_drift"] = mod
    spec.loader.exec_module(mod)
    return mod


drift = _load()


@pytest.fixture()
def excludes():
    return drift.load_excludes(EXCLUDE_FILE)


def test_committed_exclude_file_parses(excludes):
    dir_globs, file_globs = excludes
    assert "__pycache__" in dir_globs
    assert "venv" in dir_globs
    assert "*.pyc" in file_globs


def test_bak_files_are_not_excluded(excludes):
    """The regression itself. rsync deletes these, so the check must see them."""
    _, file_globs = excludes
    for name in ("schedule.py.bak-20260801-173346",
                 "routes/admin_routes.py.bak-publishgate-20260701".split("/")[-1],
                 "dossier.css.bak-regfix"):
        assert not drift._excluded_file(name, file_globs), name


def test_unsupported_pattern_refuses_rather_than_guessing(tmp_path):
    """A misparsed pattern hides files from the check, and only loudly failing
    to parse it is safe."""
    bad = tmp_path / "bad.exclude"
    bad.write_text("routes/secret/\n", encoding="utf-8")
    with pytest.raises(drift.ExcludeError):
        drift.load_excludes(str(bad))


def test_empty_exclude_file_refuses(tmp_path):
    empty = tmp_path / "empty.exclude"
    empty.write_text("# only a comment\n", encoding="utf-8")
    with pytest.raises(drift.ExcludeError):
        drift.load_excludes(str(empty))


def _tree(root):
    """A tree holding one of everything the old allowlist could not see."""
    (root / "routes").mkdir()
    (root / "__pycache__").mkdir()
    (root / "venv" / "lib").mkdir(parents=True)
    (root / ".deploy-bak-20260101").mkdir()

    (root / "main.py").write_text("x", encoding="utf-8")
    (root / "schedule.py.bak-20260801-173346").write_text("x", encoding="utf-8")
    (root / "routes" / "public.py.bak-publishgate-20260701").write_text("x", encoding="utf-8")
    (root / "logo.png").write_bytes(b"\x89PNG\x00\x01")
    (root / "NOTES").write_text("no suffix at all", encoding="utf-8")
    (root / "notes.md").write_text("x", encoding="utf-8")

    (root / "__pycache__" / "main.cpython-312.pyc").write_bytes(b"\x00")
    (root / "main.cpython-312.pyc").write_bytes(b"\x00")
    (root / "venv" / "lib" / "thing.py").write_text("x", encoding="utf-8")
    (root / ".deploy-bak-20260101" / "old.py").write_text("x", encoding="utf-8")


def test_walker_sees_what_the_allowlist_missed(tmp_path, excludes):
    _tree(tmp_path)
    seen = drift.local_manifest(str(tmp_path), *excludes)
    for rel in ("main.py",
                "schedule.py.bak-20260801-173346",
                "routes/public.py.bak-publishgate-20260701",
                "logo.png",
                "NOTES",
                "notes.md"):
        assert rel in seen, rel


def test_walker_still_skips_the_generated_tree(tmp_path, excludes):
    _tree(tmp_path)
    seen = drift.local_manifest(str(tmp_path), *excludes)
    for rel in ("__pycache__/main.cpython-312.pyc",
                "main.cpython-312.pyc",
                "venv/lib/thing.py",
                ".deploy-bak-20260101/old.py"):
        assert rel not in seen, rel


def test_text_normalises_line_endings_and_binary_does_not(tmp_path, excludes):
    crlf, lf = b"a\r\nb\r\n", b"a\nb\n"
    assert drift._digest(crlf) == drift._digest(lf)
    # A NUL means the bytes are not lines; rewriting them to decide whether two
    # files match is how a real difference gets called a match.
    assert drift._digest(b"\x00a\r\nb") != drift._digest(b"\x00a\nb")
