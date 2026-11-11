"""Regression tests for scripts/ktp-demo-retention.sh.

The excludes built from `.noprune` markers were once flattened into a single
string and re-parsed by `eval`, so the trailing `/*` glob-expanded against the
real filesystem before find ever saw it. Two silent failure modes came out of
that, and which one you got depended only on how many children the protected
directory happened to have:

  one child   the glob collapses to that one exact path with no wildcard, so
              `-not -path .../KEEPME/draft` excluded the directory and not the
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


def _demo(path: Path, age_days: float, size: int = 1024) -> Path:
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
    _demo(root / "ATL1" / "draft" / "old_a.dem", 400)
    _demo(root / "ATL1" / "draft" / "old_b.dem", 300)
    _demo(root / "ATL1" / "draft" / "fresh.dem", 10)
    _demo(root / "ATL1" / "12man" / "old_c.dem", 200)
    _demo(root / "ATL1" / "12man" / "fresh_c.dem", 10)
    _demo(root / "LAN-PHILLY2026" / "draft" / "lan.dem", 500)
    _demo(root / "KEEPME" / "draft" / "keep.dem", 500)
    (root / "KEEPME" / ".noprune").touch()
    return root


def test_dry_run_counts_only_what_is_past_retention(tree: Path):
    """The .noprune subtree has exactly one child -- the over-match trigger."""
    assert len(list((tree / "KEEPME").iterdir())) == 2  # draft/ + .noprune
    r = _run(tree, DRY_RUN="1")
    assert r.returncode == 0, r.stderr
    assert "draft/ would delete 2 files" in r.stdout
    assert "12man/ would delete 1 files" in r.stdout
    assert "total 3 files" in r.stdout


def test_protected_subtree_with_several_children_does_not_zero_the_pass(tmp_path: Path):
    """The under-match trigger: >1 child made find abort and the tier vanish."""
    root = tmp_path / "demos"
    _demo(root / "ATL1" / "draft" / "old_a.dem", 400)
    _demo(root / "ATL1" / "draft" / "old_b.dem", 300)
    _demo(root / "EVENT" / "draft" / "event.dem", 500)
    (root / "EVENT" / "notes").mkdir(parents=True)
    (root / "EVENT" / "notes" / "readme.txt").touch()
    (root / "EVENT" / ".noprune").touch()
    assert len(list((root / "EVENT").iterdir())) == 3

    r = _run(root, DRY_RUN="1")
    assert r.returncode == 0, r.stderr
    assert "nothing past retention" not in r.stdout
    assert "draft/ would delete 2 files" in r.stdout


def test_delete_removes_exactly_the_counted_set(tree: Path):
    """Counted set == deleted set. They were assembled separately once."""
    dry = _run(tree, DRY_RUN="1")
    assert "total 3 files" in dry.stdout

    r = _run(tree)
    assert r.returncode == 0, r.stderr
    survivors = sorted(p.relative_to(tree).as_posix() for p in tree.rglob("*.dem"))
    assert survivors == [
        "ATL1/12man/fresh_c.dem",
        "ATL1/draft/fresh.dem",
        "KEEPME/draft/keep.dem",
        "LAN-PHILLY2026/draft/lan.dem",
    ]


def test_unenrolled_subdir_is_never_swept(tmp_path: Path):
    """Only draft/12man/scrim are enrolled; anything else is left alone."""
    root = tmp_path / "demos"
    _demo(root / "ATL1" / "playoffs" / "ancient.dem", 900)
    r = _run(root)
    assert r.returncode == 0, r.stderr
    assert (root / "ATL1" / "playoffs" / "ancient.dem").exists()


def test_preview_reports_the_tiers_and_does_not_delete(tree: Path):
    r = _run(tree, "preview", PREVIEW_WINDOW_DAYS="400")
    assert r.returncode == 0, r.stderr
    assert "`draft` (180d)" in r.stdout
    assert "`12man` (30d)" in r.stdout
    assert len(list(tree.rglob("*.dem"))) == 7


def test_embed_title_uses_the_live_discord_emoji(tree: Path):
    """The old <:ktp:...> token was retired fleet-wide and renders as raw text."""
    r = _run(tree, "preview", PREVIEW_WINDOW_DAYS="400")
    assert "<:KTP:1002382703020212245>" in r.stdout
    assert "<:ktp:" not in r.stdout


def test_event_archive_in_the_delete_set_aborts_before_deleting(tmp_path: Path):
    """Last line of defence, exercised with the inline LAN-* filter removed."""
    root = tmp_path / "demos"
    _demo(root / "LAN-X" / "draft" / "g.dem", 400)
    patched = tmp_path / "patched.sh"
    shutil.copy(SCRIPT.parent / "ktp-alert-routing.sh", tmp_path / "ktp-alert-routing.sh")
    patched.write_text(
        SCRIPT.read_text(encoding="utf-8").replace('-not -path "*/LAN-*/*"', ""),
        encoding="utf-8",
    )
    env = dict(os.environ, DEMO_ROOT=str(root), SKIP_DISCORD="1")
    r = subprocess.run(["bash", str(patched), "delete"],
                       capture_output=True, text=True, env=env, timeout=120)
    assert r.returncode == 3, (r.returncode, r.stdout, r.stderr)
    assert "event-archive path" in r.stderr
    assert (root / "LAN-X" / "draft" / "g.dem").exists()


def test_missing_demo_root_fails_loudly(tmp_path: Path):
    r = _run(tmp_path / "not-there")
    assert r.returncode == 1
    assert "demo root missing" in r.stderr


@pytest.fixture
def ktp_tree(tmp_path: Path) -> Path:
    """Official ktp demos far past every tier, beside a sweepable draft control."""
    root = tmp_path / "demos"
    _demo(root / "ATL1" / "ktp" / "s1_final.dem", 900)
    _demo(root / "DAL1" / "ktp" / "due_now.dem", 178)
    _demo(root / "ATL1" / "draft" / "old.dem", 400)
    _demo(root / "ATL1" / "draft" / "due_now.dem", 178)
    return root


def test_official_ktp_demos_are_never_deleted(ktp_tree: Path):
    r = _run(ktp_tree)
    assert r.returncode == 0, r.stderr
    assert (ktp_tree / "ATL1" / "ktp" / "s1_final.dem").exists()
    assert (ktp_tree / "DAL1" / "ktp" / "due_now.dem").exists()
    assert not (ktp_tree / "ATL1" / "draft" / "old.dem").exists()


def test_official_ktp_demos_are_absent_from_dry_run_counts(ktp_tree: Path):
    r = _run(ktp_tree, DRY_RUN="1")
    assert r.returncode == 0, r.stderr
    assert "ktp/" not in r.stdout
    assert "draft/ would delete 1 files" in r.stdout
    assert "total 1 files" in r.stdout


def test_official_ktp_demos_are_absent_from_the_preview(ktp_tree: Path):
    r = _run(ktp_tree, "preview", PREVIEW_WINDOW_DAYS="1000")
    assert r.returncode == 0, r.stderr
    assert "`draft` (180d)" in r.stdout
    assert "`ktp`" not in r.stdout
    assert len(list(ktp_tree.rglob("*.dem"))) == 4


@pytest.mark.parametrize("tier", ["12man", "scrim"])
def test_short_tiers_are_swept_at_thirty_days(tmp_path: Path, tier: str):
    root = tmp_path / "demos"
    over = _demo(root / "ATL1" / tier / "31d.dem", 31.5)
    under = _demo(root / "ATL1" / tier / "29d.dem", 29)
    r = _run(root)
    assert r.returncode == 0, r.stderr
    assert not over.exists()
    assert under.exists()
