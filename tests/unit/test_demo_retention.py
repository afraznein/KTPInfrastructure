"""Regression tests for scripts/ktp-demo-retention.sh.

The excludes built from `.noprune` markers were once flattened into a single
string and re-parsed by `eval`, so the trailing `/*` glob-expanded against the
real filesystem before find ever saw it. Two silent failure modes came out of
that, and which one you got depended only on how many children the protected
directory happened to have:

  one child   the glob collapses to that one exact path with no wildcard, so
              `-not -path .../KEEPME/ktp` excluded the directory and not the
              demos under it, and protected demos entered the counts and the
              Sunday preview embed.
  two or more several paths land after `-path`, find aborts with "paths must
              precede expression", stderr was discarded, the count read 0 and
              the tier was skipped -- logged as "nothing past retention",
              exit 0.

Both are reproduced below against a tmp tree. Selection is by age and directory
only; nothing here asserts on file size, because demo size tracks duration and a
size threshold would delete real matches.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / "scripts" / "ktp-demo-retention.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or os.name == "nt",
    reason="needs bash and GNU find",
)

DAY = 86400


def _demo(path: Path, age_days: int, size: int = 1024) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\0" * size)
    stamp = time.time() - age_days * DAY
    os.utime(path, (stamp, stamp))
    return path


def _run(root: Path, mode: str = "delete", **env_extra) -> subprocess.CompletedProcess:
    env = dict(os.environ, DEMO_ROOT=str(root), SKIP_DISCORD="1", **env_extra)
    return subprocess.run(
        ["bash", str(SCRIPT), mode],
        capture_output=True, text=True, env=env, timeout=120,
    )


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """ATL1 with sweepable + fresh demos, an event archive, and a .noprune dir."""
    root = tmp_path / "demos"
    _demo(root / "ATL1" / "ktp" / "old_a.dem", 400)
    _demo(root / "ATL1" / "ktp" / "old_b.dem", 300)
    _demo(root / "ATL1" / "ktp" / "fresh.dem", 10)
    _demo(root / "ATL1" / "12man" / "old_c.dem", 200)
    _demo(root / "ATL1" / "12man" / "fresh_c.dem", 10)
    _demo(root / "LAN-PHILLY2026" / "ktp" / "lan.dem", 500)
    _demo(root / "KEEPME" / "ktp" / "keep.dem", 500)
    (root / "KEEPME" / ".noprune").touch()
    return root


def test_dry_run_counts_only_what_is_past_retention(tree: Path):
    """The .noprune subtree has exactly one child -- the over-match trigger."""
    assert len(list((tree / "KEEPME").iterdir())) == 2  # ktp/ + .noprune
    r = _run(tree, DRY_RUN="1")
    assert r.returncode == 0, r.stderr
    assert "ktp/ would delete 2 files" in r.stdout
    assert "12man/ would delete 1 files" in r.stdout
    assert "total 3 files" in r.stdout


def test_protected_subtree_with_several_children_does_not_zero_the_pass(tmp_path: Path):
    """The under-match trigger: >1 child made find abort and the tier vanish."""
    root = tmp_path / "demos"
    _demo(root / "ATL1" / "ktp" / "old_a.dem", 400)
    _demo(root / "ATL1" / "ktp" / "old_b.dem", 300)
    _demo(root / "EVENT" / "ktp" / "event.dem", 500)
    (root / "EVENT" / "notes").mkdir(parents=True)
    (root / "EVENT" / "notes" / "readme.txt").touch()
    (root / "EVENT" / ".noprune").touch()
    assert len(list((root / "EVENT").iterdir())) == 3

    r = _run(root, DRY_RUN="1")
    assert r.returncode == 0, r.stderr
    assert "nothing past retention" not in r.stdout
    assert "ktp/ would delete 2 files" in r.stdout


def test_delete_removes_exactly_the_counted_set(tree: Path):
    """Counted set == deleted set. They were assembled separately once."""
    dry = _run(tree, DRY_RUN="1")
    assert "total 3 files" in dry.stdout

    r = _run(tree)
    assert r.returncode == 0, r.stderr
    survivors = sorted(p.relative_to(tree).as_posix() for p in tree.rglob("*.dem"))
    assert survivors == [
        "ATL1/12man/fresh_c.dem",
        "ATL1/ktp/fresh.dem",
        "KEEPME/ktp/keep.dem",
        "LAN-PHILLY2026/ktp/lan.dem",
    ]


def test_unenrolled_subdir_is_never_swept(tmp_path: Path):
    """Only ktp/draft/12man/scrim are enrolled; anything else is left alone."""
    root = tmp_path / "demos"
    _demo(root / "ATL1" / "playoffs" / "ancient.dem", 900)
    r = _run(root)
    assert r.returncode == 0, r.stderr
    assert (root / "ATL1" / "playoffs" / "ancient.dem").exists()


def test_preview_reports_the_tiers_and_does_not_delete(tree: Path):
    r = _run(tree, "preview", PREVIEW_WINDOW_DAYS="400")
    assert r.returncode == 0, r.stderr
    assert "`ktp` (180d)" in r.stdout
    assert "`12man` (90d)" in r.stdout
    assert len(list(tree.rglob("*.dem"))) == 7


def test_embed_title_uses_the_live_discord_emoji(tree: Path):
    """The old <:ktp:...> token was retired fleet-wide and renders as raw text."""
    r = _run(tree, "preview", PREVIEW_WINDOW_DAYS="400")
    assert "<:KTP:1002382703020212245>" in r.stdout
    assert "<:ktp:" not in r.stdout


def test_event_archive_in_the_delete_set_aborts_before_deleting(tmp_path: Path):
    """Last line of defence, exercised with the inline LAN-* filter removed."""
    root = tmp_path / "demos"
    _demo(root / "LAN-X" / "ktp" / "g.dem", 400)
    patched = tmp_path / "patched.sh"
    patched.write_text(
        SCRIPT.read_text(encoding="utf-8").replace('-not -path "*/LAN-*/*"', ""),
        encoding="utf-8",
    )
    env = dict(os.environ, DEMO_ROOT=str(root), SKIP_DISCORD="1")
    r = subprocess.run(["bash", str(patched), "delete"],
                       capture_output=True, text=True, env=env, timeout=120)
    assert r.returncode == 3, (r.returncode, r.stdout, r.stderr)
    assert (root / "LAN-X" / "ktp" / "g.dem").exists()


def test_missing_demo_root_fails_loudly(tmp_path: Path):
    r = _run(tmp_path / "not-there")
    assert r.returncode == 1
    assert "demo root missing" in r.stderr
