"""Regression tests for scripts/ktp-hud-archive-retention.sh.

The HUD observer writes one directory per match under /opt/hud-observer/matches,
holding metadata.json and events.jsonl. Two properties of that archive decide
what this script may delete, and both are pinned here:

  * metadata.json says matchType 0 / half 0 for every match the recorder
    auto-started, and 0 is COMPETITIVE. Most of those are pickups, so a script
    trusting metadata would keep them on the long tier. The type comes from the
    first event's match_type instead.
  * metadata.json is rewritten on reap and on a count repair, so its mtime can
    be younger than the match. Age is read from events.jsonl.

Everything the script is told not to touch -- .noprune, an open match, a match
from a non-fleet server, an unknown type, a dir with a file it does not know --
is exercised against a delete run, not only a dry run.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / "scripts" / "ktp-hud-archive-retention.sh"

pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or shutil.which("jq") is None or os.name == "nt",
    reason="needs bash, jq and GNU find",
)

DAY = 86400

COMPETITIVE, SCRIM, TWELVE, DRAFT, KTP_OT, DRAFT_OT = range(6)


def _age(path: Path, days: float) -> None:
    stamp = time.time() - days * DAY
    os.utime(path, (stamp, stamp))


def _match(root: Path, name: str, *, age: float, match_type: int | None, half: int = 1,
           event_type: int | None = "same", ended: bool = True,
           source: str = "KTP - New York 1", meta_age: float | None = None,
           size: int = 1000) -> Path:
    d = root / name
    d.mkdir(parents=True)
    meta = {
        "matchId": name, "map": "dod_anzio", "matchType": match_type, "half": half,
        "startedAt": "2026-01-01T00:00:00.000Z",
        "endedAt": "2026-01-01T01:00:00.000Z" if ended else None,
        "eventCount": 1, "sourceServer": source,
    }
    (d / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    first = {"event": "ktp_match_start", "match_id": name}
    if event_type == "same":
        event_type = match_type
    if event_type is not None:
        first["match_type"] = event_type
    line = json.dumps(first) + "\n"
    (d / "events.jsonl").write_text(line + "x" * max(0, size - len(line)), encoding="utf-8")
    _age(d / "events.jsonl", age)
    _age(d / "metadata.json", age if meta_age is None else meta_age)
    return d


def _run(root: Path, mode: str = "delete", **env_extra) -> subprocess.CompletedProcess:
    env = dict(os.environ, HUD_MATCHES_DIR=str(root), SKIP_DISCORD="1", **env_extra)
    return subprocess.run(["bash", str(SCRIPT), mode],
                          capture_output=True, text=True, env=env, timeout=120)


def _names(root: Path) -> list[str]:
    return sorted(p.name for p in root.iterdir())


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    root = tmp_path / "matches"
    root.mkdir()
    _match(root, "official-old", age=200, match_type=COMPETITIVE)
    _match(root, "official-mid", age=100, match_type=COMPETITIVE)
    _match(root, "ot-old", age=200, match_type=KTP_OT)
    _match(root, "draftot-mid", age=100, match_type=DRAFT_OT)
    _match(root, "twelve-old", age=100, match_type=TWELVE)
    _match(root, "scrim-fresh", age=50, match_type=SCRIM)
    # Auto-started placeholders: metadata says 0/0, the events say what it was.
    _match(root, "1.3-111-NY1", age=100, match_type=COMPETITIVE, half=0, event_type=TWELVE)
    _match(root, "1.3-222-NY1", age=100, match_type=COMPETITIVE, half=0, event_type=COMPETITIVE)
    return root


def test_dry_run_counts_by_tier_and_deletes_nothing(tree: Path):
    before = _names(tree)
    r = _run(tree, DRY_RUN="1")
    assert r.returncode == 0, r.stderr
    assert "ktp would delete 2 matches" in r.stdout
    assert "12man would delete 2 matches" in r.stdout
    assert "draft" not in r.stdout.split("delete: total")[0]
    assert "total 4 matches" in r.stdout
    assert _names(tree) == before


def test_placeholder_is_typed_from_its_events_not_its_metadata(tree: Path):
    """The 12man placeholder goes at 90 days; the competitive one waits for 180."""
    r = _run(tree)
    assert r.returncode == 0, r.stderr
    assert not (tree / "1.3-111-NY1").exists()
    assert (tree / "1.3-222-NY1").exists()


def test_delete_removes_exactly_the_counted_set(tree: Path):
    dry = _run(tree, DRY_RUN="1")
    assert "total 4 matches" in dry.stdout
    r = _run(tree)
    assert r.returncode == 0, r.stderr
    assert _names(tree) == ["1.3-222-NY1", "draftot-mid", "official-mid", "scrim-fresh"]


def test_age_is_read_from_events_not_metadata(tmp_path: Path):
    root = tmp_path / "matches"
    _match(root, "reaped-late", age=100, meta_age=1, match_type=SCRIM)
    r = _run(root)
    assert r.returncode == 0, r.stderr
    assert _names(root) == []


@pytest.mark.parametrize("kwargs, reason", [
    (dict(ended=False), "open"),
    (dict(source="KTP - LAN 1"), "nonfleet"),
    (dict(source=""), "nonfleet"),
    (dict(match_type=9), "untyped"),
    (dict(match_type=COMPETITIVE, half=0, event_type=None), "untyped"),
    (dict(match_type=SCRIM, event_type=COMPETITIVE), "conflict"),
])
def test_ineligible_matches_survive_a_delete_run(tmp_path: Path, kwargs, reason):
    root = tmp_path / "matches"
    args = dict(age=900, match_type=TWELVE)
    args.update(kwargs)
    _match(root, "keep", **args)
    r = _run(root)
    assert r.returncode == 0, r.stderr
    assert (root / "keep" / "events.jsonl").exists()
    assert f"{reason}=1" in r.stdout


def test_noprune_marker_protects_the_match(tmp_path: Path):
    root = tmp_path / "matches"
    d = _match(root, "kept-by-hand", age=900, match_type=TWELVE)
    (d / ".noprune").touch()
    r = _run(root)
    assert r.returncode == 0, r.stderr
    assert (d / "events.jsonl").exists()
    assert "noprune=1" in r.stdout


def test_unknown_file_in_a_match_dir_blocks_its_removal(tmp_path: Path):
    root = tmp_path / "matches"
    d = _match(root, "has-extra", age=900, match_type=TWELVE)
    (d / "notes.txt").write_text("keep me", encoding="utf-8")
    r = _run(root)
    assert r.returncode == 0, r.stderr
    assert (d / "notes.txt").exists() and (d / "events.jsonl").exists()
    assert "unexpected=1" in r.stdout


def test_player_state_keeps_its_own_short_clock(tmp_path: Path):
    root = tmp_path / "matches"
    old = _match(root, "with-old-ps", age=40, match_type=COMPETITIVE)
    (old / "player_state.jsonl").write_text("{}\n", encoding="utf-8")
    _age(old / "player_state.jsonl", 40)
    new = _match(root, "with-new-ps", age=20, match_type=COMPETITIVE)
    (new / "player_state.jsonl").write_text("{}\n", encoding="utf-8")
    _age(new / "player_state.jsonl", 20)
    gone = _match(root, "whole-match-due", age=200, match_type=SCRIM)
    (gone / "player_state.jsonl").write_text("{}\n", encoding="utf-8")
    _age(gone / "player_state.jsonl", 200)

    r = _run(root)
    assert r.returncode == 0, r.stderr
    assert not (old / "player_state.jsonl").exists()
    assert (old / "events.jsonl").exists()
    assert (new / "player_state.jsonl").exists()
    assert not gone.exists()
    assert "player_state deleting 1 files" in r.stdout


def test_preview_reports_what_falls_due_and_deletes_nothing(tmp_path: Path):
    root = tmp_path / "matches"
    _match(root, "due-in-3d", age=87, match_type=TWELVE)
    _match(root, "due-later", age=60, match_type=TWELVE)
    _match(root, "already-due", age=100, match_type=TWELVE)
    r = _run(root, "preview")
    assert r.returncode == 0, r.stderr
    assert "`12man` (90d) — 1 —" in r.stdout
    assert "<:KTP:1002382703020212245>" in r.stdout
    assert _names(root) == ["already-due", "due-in-3d", "due-later"]


def test_preview_with_nothing_due_says_so(tmp_path: Path):
    root = tmp_path / "matches"
    _match(root, "fresh", age=5, match_type=TWELVE)
    r = _run(root, "preview")
    assert r.returncode == 0, r.stderr
    assert "nothing due" in r.stdout


def test_missing_matches_dir_fails_loudly(tmp_path: Path):
    r = _run(tmp_path / "not-there")
    assert r.returncode == 1
    assert "matches dir missing" in r.stderr


def test_unknown_mode_is_a_usage_error(tmp_path: Path):
    root = tmp_path / "matches"
    root.mkdir()
    r = _run(root, "zqwbw1110mode")
    assert r.returncode == 2
