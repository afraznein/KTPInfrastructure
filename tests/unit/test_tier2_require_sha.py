"""`scripts/tier2-require-sha.sh` and its wiring into tier2-integration.yml.

The Tier-2 runner certifies the KTPMatchHandler build it compiles, so the build
must refuse any tree that is not the pinned reviewed commit. Before this gate
the build baked `git rev-parse --short HEAD` inside a printf argument, where a
failure produced an empty SHA and the step carried on.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "tier2-require-sha.sh"
WORKFLOW = REPO / ".github" / "workflows" / "tier2-integration.yml"

BASH = shutil.which("bash")
GIT = shutil.which("git")
needs_tools = pytest.mark.skipif(not (BASH and GIT), reason="needs bash and git")


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        [GIT, "-C", str(cwd), *args], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture
def checkout(tmp_path: Path) -> tuple[Path, str, str]:
    """A repo with two commits; HEAD is the second. Returns (dir, old, head)."""
    d = tmp_path / "src"
    d.mkdir()
    _git(d, "init", "-q")
    _git(d, "config", "user.email", "t@example.invalid")
    _git(d, "config", "user.name", "t")
    _git(d, "config", "core.autocrlf", "false")
    (d / "KTPMatchHandler.sma").write_text("old\n")
    _git(d, "add", "-A")
    _git(d, "commit", "-qm", "old")
    old = _git(d, "rev-parse", "HEAD")
    (d / "KTPMatchHandler.sma").write_text("new\n")
    _git(d, "commit", "-qam", "new")
    return d, old, _git(d, "rev-parse", "HEAD")


def _run(src: Path | str, want: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [BASH, str(SCRIPT), str(src), want], capture_output=True, text=True
    )


@needs_tools
def test_pinned_clean_checkout_passes_and_prints_short_sha(checkout):
    d, _, head = checkout
    r = _run(d, head)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == _git(d, "rev-parse", "--short", head)


@needs_tools
def test_checkout_at_another_commit_fails(checkout):
    d, old, head = checkout
    r = _run(d, old)
    assert r.returncode != 0
    assert "not the pinned" in r.stderr and head in r.stderr


@needs_tools
def test_dirty_checkout_fails(checkout):
    d, _, head = checkout
    (d / "KTPMatchHandler.sma").write_text("edited after checkout\n")
    r = _run(d, head)
    assert r.returncode != 0
    assert "uncommitted" in r.stderr


@needs_tools
def test_unresolvable_head_fails(tmp_path, checkout):
    _, _, head = checkout
    r = _run(tmp_path / "not-a-repo", head)
    assert r.returncode != 0
    assert "cannot resolve HEAD" in r.stderr
    assert r.stdout.strip() == "", "a failed gate must not print a SHA to bake"


@needs_tools
@pytest.mark.parametrize("want", ["main", "b3b3d93", "", "B3B3D93158110E2A9F45A8B444CABFEA27ACE1C4"])
def test_expected_must_be_a_full_sha(checkout, want):
    d, _, _ = checkout
    r = _run(d, want)
    assert r.returncode != 0
    assert "full 40-hex" in r.stderr


def _step_block(text: str, name_prefix: str) -> str:
    """The text of one step, from its `- name:` to the next. Text, not YAML:
    the CI job installs no YAML parser."""
    starts = [m.start() for m in re.finditer(r"^      - name: ", text, re.M)]
    (i,) = [i for i, at in enumerate(starts) if text.startswith(f"      - name: {name_prefix}", at)]
    end = starts[i + 1] if i + 1 < len(starts) else len(text)
    return text[starts[i]:end]


def test_workflow_checks_out_and_builds_the_same_pinned_sha():
    text = WORKFLOW.read_text(encoding="utf-8")
    (pin,) = re.findall(r"^      KTP_MATCHHANDLER_SHA: (\S+)$", text, re.M)
    assert re.fullmatch(r"[0-9a-f]{40}", pin)

    checkout = _step_block(text, "Checkout reviewed KTPMatchHandler")
    assert "ref: ${{ env.KTP_MATCHHANDLER_SHA }}" in checkout

    build = _step_block(text, "Build + install reviewed KTPMatchHandler")
    gate = 'BUILD_SHA="$(bash "$GITHUB_WORKSPACE/scripts/tier2-require-sha.sh" "$SRC" "$KTP_MATCHHANDLER_SHA")"'
    assert gate in build
    assert build.index(gate) < build.index("amxxpc"), "the gate must run before the compile"
    assert "rev-parse" not in build, "the baked SHA must come from the gate, not a second lookup"
    assert '"$BUILD_SHA"' in build
