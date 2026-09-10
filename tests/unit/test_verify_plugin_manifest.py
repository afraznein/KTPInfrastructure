"""Guard the guard: verify-plugin-manifest.sh must be able to fail AND to pass.

Regression this exists for (2026-09-10): the plugin builder swallowed an
amxxpc failure, published a base image with no `stats_logging.amxx`, and the
shared Tier 1 gate went red for every consumer naming a truncated plugin that
was not the change under test.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "verify-plugin-manifest.sh"

def _sh(p: Path) -> str:
    # Git Bash eats backslashes in argv; forward slashes work everywhere.
    return str(p).replace("\\", "/")


def _find_bash() -> str | None:
    """First bash that can actually see this repo.

    On Windows `bash` often resolves to WSL, which cannot open a `C:/` path —
    the script then reports "No such file or directory" and every assertion
    fails for a reason that has nothing to do with the script.
    """
    candidates = [shutil.which("bash")]
    if shutil.which("git"):
        git_root = Path(shutil.which("git")).resolve().parents[1]
        candidates.append(str(git_root / "bin" / "bash.exe"))
    for cand in candidates:
        if not cand or not Path(cand).exists():
            continue
        probe = subprocess.run(
            [cand, "-c", f'test -f "{_sh(SCRIPT)}"'], capture_output=True
        )
        if probe.returncode == 0:
            return cand
    return None


BASH = _find_bash()

pytestmark = pytest.mark.skipif(
    BASH is None, reason="no bash that can read this repo path"
)


def run(
    plugins_dir: Path, *manifests: Path, sources: Path | None = None
) -> subprocess.CompletedProcess:
    argv = [BASH, _sh(SCRIPT)]
    if sources is not None:
        argv += ["--sources", _sh(sources)]
    argv += [_sh(plugins_dir), *[_sh(m) for m in manifests]]
    return subprocess.run(argv, capture_output=True, text=True)


@pytest.fixture
def tree(tmp_path: Path):
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    profile = tmp_path / "local"
    profile.mkdir()
    return plugins, profile


def test_script_exists():
    assert SCRIPT.is_file(), f"{SCRIPT} missing"


def test_passes_when_every_entry_is_present(tree):
    plugins, profile = tree
    (plugins / "admin.amxx").write_bytes(b"x")
    (plugins / "ktp_cvar.amxx").write_bytes(b"x")
    manifest = profile / "plugins.ini"
    manifest.write_text("; comment\nadmin.amxx\nktp_cvar.amxx debug\n")

    result = run(plugins, manifest)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "2 entries checked" in result.stdout


def test_fails_and_names_the_missing_plugin(tree):
    plugins, profile = tree
    (plugins / "admin.amxx").write_bytes(b"x")
    manifest = profile / "plugins.ini"
    manifest.write_text("admin.amxx\nstats_logging.amxx debug\n")

    result = run(plugins, manifest)
    assert result.returncode == 1
    assert "stats_logging.amxx" in result.stderr
    assert "admin.amxx" not in result.stderr.split("Present in")[0]


def test_commented_out_entry_is_not_required(tree):
    plugins, profile = tree
    (plugins / "admin.amxx").write_bytes(b"x")
    manifest = profile / "plugins.ini"
    manifest.write_text("admin.amxx\n; KTPScoreTracker.amxx\n")

    result = run(plugins, manifest)
    assert result.returncode == 0, result.stdout + result.stderr


def test_crlf_manifest_is_parsed(tree):
    plugins, profile = tree
    (plugins / "admin.amxx").write_bytes(b"x")
    manifest = profile / "plugins.ini"
    manifest.write_bytes(b"admin.amxx\r\n")

    result = run(plugins, manifest)
    assert result.returncode == 0, result.stdout + result.stderr


def test_empty_manifest_fails_rather_than_passing_vacuously(tree):
    """A parse that yields nothing is a broken probe, not a clean profile."""
    plugins, profile = tree
    manifest = profile / "plugins.ini"
    manifest.write_text("; every line a comment\n")

    result = run(plugins, manifest)
    assert result.returncode == 1
    assert "ZERO plugin entries" in result.stderr


def test_missing_plugins_dir_fails(tmp_path: Path):
    profile = tmp_path / "local"
    profile.mkdir()
    manifest = profile / "plugins.ini"
    manifest.write_text("admin.amxx\n")

    result = run(tmp_path / "nope", manifest)
    assert result.returncode == 1
    assert "plugins dir does not exist" in result.stderr


def test_real_repo_profiles_parse(tmp_path: Path):
    """The committed profiles must parse — catches a path or format drift."""
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    manifests = [
        REPO_ROOT / "config" / p / "plugins.ini" for p in ("local", "online", "lan")
    ]
    for m in manifests:
        assert m.is_file(), f"{m} missing"

    result = run(plugins, *manifests)
    # Empty plugins dir, so this must FAIL — and it must fail by naming
    # missing plugins, not by failing to parse.
    assert result.returncode == 1
    assert "ZERO plugin entries" not in result.stderr
    assert "stats_logging.amxx" in result.stderr


# --sources: build/plugins/Dockerfile SKIPs an absent .sma and exits 0, so
# nothing in the image build fails when a plugin repo is not checked out.


@pytest.fixture
def sourced(tmp_path: Path):
    """A tree where every manifest entry is both built and has a source."""
    plugins = tmp_path / "plugins"
    plugins.mkdir()
    profile = tmp_path / "local"
    profile.mkdir()
    src = tmp_path / "src"
    (src / "KTPCvarChecker").mkdir(parents=True)
    (src / "amxx-stock").mkdir(parents=True)
    for name in ("ktp_cvar", "admin"):
        (plugins / f"{name}.amxx").write_bytes(b"x")
    (src / "KTPCvarChecker" / "ktp_cvar.sma").write_text("//")
    (src / "amxx-stock" / "admin.sma").write_text("//")
    manifest = profile / "plugins.ini"
    manifest.write_text("admin.amxx\nktp_cvar.amxx debug\n")
    return plugins, manifest, src


def test_sources_mode_passes_when_every_source_exists(sourced):
    plugins, manifest, src = sourced

    result = run(plugins, manifest, sources=src)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "has a source under" in result.stdout


def test_sources_mode_fails_on_a_missing_sma(sourced):
    """The gap the Dockerfile leaves: source gone, build still green."""
    plugins, manifest, src = sourced
    (src / "KTPCvarChecker" / "ktp_cvar.sma").unlink()

    result = run(plugins, manifest, sources=src)
    assert result.returncode == 1
    assert "whose source is absent" in result.stderr
    assert "ktp_cvar.sma" in result.stderr
    # The .amxx is still on disk, so this must NOT be reported as "not built".
    assert "were not built" not in result.stderr


def test_sources_mode_is_opt_in(sourced):
    """Without --sources a missing .sma is not consulted at all."""
    plugins, manifest, src = sourced
    (src / "KTPCvarChecker" / "ktp_cvar.sma").unlink()

    result = run(plugins, manifest)
    assert result.returncode == 0, result.stdout + result.stderr
    # Substring-match the phrase, not the word: pytest's tmp path for this
    # test contains "sources".
    assert "has a source under" not in result.stdout
    assert "whose source is absent" not in result.stderr


def test_sources_root_must_exist(sourced):
    plugins, manifest, src = sourced

    result = run(plugins, manifest, sources=src / "nope")
    assert result.returncode == 1
    assert "sources root does not exist" in result.stderr


def test_sources_root_with_no_sma_at_all_is_an_error(sourced, tmp_path: Path):
    """An index that finds nothing is a wrong root, not 11 missing plugins."""
    plugins, manifest, _ = sourced
    empty = tmp_path / "empty-root"
    empty.mkdir()

    result = run(plugins, manifest, sources=empty)
    assert result.returncode == 1
    assert "no .sma found anywhere" in result.stderr
