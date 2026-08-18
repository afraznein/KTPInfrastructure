"""Tests for the value-based secret scanner.

Most of these assert that the scanner FAILS when it should. A secret scan that
cannot be made to fail is the failure mode this whole thing exists to prevent --
`ktp-verify-deploy.py` reported green on an identically-wrong fleet, and a test
gate with a hardcoded import path reported ALL PASS on a branch it never read.
So every self-check gets a test that breaks it on purpose.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(SCRIPTS))

import ktp_secret_scan as scan  # noqa: E402


@pytest.fixture
def inventory(tmp_path, monkeypatch):
    """A minimal inventory, wired in via the documented env var."""
    path = tmp_path / "inv.txt"
    path.write_text(
        "# comment\n"
        "live\tSUPERSECRETVALUE123\n"
        "retired\tOLDVALUE456\n"
        "hostinfo\t203.0.113.7\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("KTP_SECRET_INVENTORY", str(path))
    return path


def test_inventory_parses_all_three_tags(inventory):
    live, retired = scan.load_inventory()
    assert live == ["SUPERSECRETVALUE123"]
    assert retired == ["OLDVALUE456"]
    assert scan.load_hostinfo() == ["203.0.113.7"]


def test_missing_inventory_is_broken_not_clean(tmp_path, monkeypatch):
    monkeypatch.setenv("KTP_SECRET_INVENTORY", str(tmp_path / "nope.txt"))
    with pytest.raises(scan.Broken):
        scan.load_inventory()


def test_inventory_with_no_live_values_is_broken(tmp_path, monkeypatch):
    path = tmp_path / "inv.txt"
    path.write_text("retired\tOLDVALUE456\n", encoding="utf-8")
    monkeypatch.setenv("KTP_SECRET_INVENTORY", str(path))
    with pytest.raises(scan.Broken):
        scan.load_inventory()


def test_unknown_inventory_tag_is_broken(tmp_path, monkeypatch):
    path = tmp_path / "inv.txt"
    path.write_text("maybe\tSOMETHING\n", encoding="utf-8")
    monkeypatch.setenv("KTP_SECRET_INVENTORY", str(path))
    with pytest.raises(scan.Broken):
        scan.load_inventory()


def test_selftest_passes_against_the_real_fixtures():
    scan.selftest(REPO)


def test_every_declared_format_has_a_canary_file():
    """CANARY_FORMATS is the coverage claim; the fixture dir is the evidence.
    Adding a format to the tuple without a fixture must not silently pass."""
    fixtures = REPO / "tests" / "fixtures" / "secret_canary"
    present = {p.suffix.lstrip(".") for p in fixtures.iterdir() if p.is_file()}
    assert set(scan.CANARY_FORMATS) <= present


def test_selftest_fails_when_a_format_stops_matching(tmp_path):
    """Drop one format and the selftest must name it rather than pass."""
    fixtures = tmp_path / "tests" / "fixtures" / "secret_canary"
    fixtures.mkdir(parents=True)
    for fmt in scan.CANARY_FORMATS:
        if fmt == "json":
            (fixtures / f"canary.{fmt}").write_text("{}", encoding="utf-8")
        else:
            (fixtures / f"canary.{fmt}").write_text(scan.CANARY, encoding="utf-8")
    with pytest.raises(scan.Broken, match="json"):
        scan.selftest(tmp_path)


def test_selftest_fails_when_fixtures_are_missing(tmp_path):
    with pytest.raises(scan.Broken, match="canary fixtures missing"):
        scan.selftest(tmp_path)


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True,
                   capture_output=True, text=True)


def _rev(root: Path, ref: str) -> str:
    out = subprocess.run(["git", "-C", str(root), "rev-parse", ref],
                         check=True, capture_output=True, text=True)
    return out.stdout.strip()


@pytest.fixture
def throwaway_repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    return root


def test_scan_tree_finds_a_planted_value(throwaway_repo, inventory):
    (throwaway_repo / "conf.py").write_text(
        'PASSWORD = "SUPERSECRETVALUE123"\n', encoding="utf-8")
    _git(throwaway_repo, "add", "conf.py")
    findings = scan.scan_tree(throwaway_repo, ["SUPERSECRETVALUE123"])
    assert [f[0] for f in findings] == ["conf.py"]


def test_scan_tree_is_clean_when_the_value_is_absent(throwaway_repo, inventory):
    (throwaway_repo / "conf.py").write_text("PASSWORD = os.environ['P']\n",
                                            encoding="utf-8")
    _git(throwaway_repo, "add", "conf.py")
    assert scan.scan_tree(throwaway_repo, ["SUPERSECRETVALUE123"]) == []


def test_scan_range_finds_a_value_removed_in_a_later_commit(throwaway_repo, inventory):
    """The whole reason the gate scans a RANGE. Deleting the line from the tip
    does not delete it from history, which is exactly how the data-server root
    password reached a public branch and stayed there."""
    (throwaway_repo / "README").write_text("start\n", encoding="utf-8")
    _git(throwaway_repo, "add", "README")
    _git(throwaway_repo, "commit", "-qm", "initial")

    target = throwaway_repo / "deploy.py"
    target.write_text('PW = "SUPERSECRETVALUE123"\n', encoding="utf-8")
    _git(throwaway_repo, "add", "deploy.py")
    _git(throwaway_repo, "commit", "-qm", "leak")
    target.write_text("PW = os.environ['PW']\n", encoding="utf-8")
    _git(throwaway_repo, "add", "deploy.py")
    _git(throwaway_repo, "commit", "-qm", "remove from tip")

    assert scan.scan_tree(throwaway_repo, ["SUPERSECRETVALUE123"]) == []
    findings = scan.scan_range(throwaway_repo, "HEAD~2..HEAD",
                               ["SUPERSECRETVALUE123"])
    assert findings, "range scan missed a value that is still in history"


def test_range_scan_separates_adding_from_removing(throwaway_repo, inventory):
    """`git log -S` matches the commit that ADDS a value and the one that
    REMOVES it. Both block, but they need different fixes, so the report must
    not call a removal commit 'present'."""
    (throwaway_repo / "README").write_text("start\n", encoding="utf-8")
    _git(throwaway_repo, "add", "README")
    _git(throwaway_repo, "commit", "-qm", "initial")
    target = throwaway_repo / "deploy.py"
    target.write_text('PW = "SUPERSECRETVALUE123"\n', encoding="utf-8")
    _git(throwaway_repo, "add", "deploy.py")
    _git(throwaway_repo, "commit", "-qm", "leak")
    added = _rev(throwaway_repo, "HEAD")
    target.write_text("PW = os.environ['PW']\n", encoding="utf-8")
    _git(throwaway_repo, "add", "deploy.py")
    _git(throwaway_repo, "commit", "-qm", "remove")
    removed = _rev(throwaway_repo, "HEAD")

    verdicts = {
        sha: in_tree
        for sha, _v, in_tree in scan.scan_range(
            throwaway_repo, "HEAD~2..HEAD", ["SUPERSECRETVALUE123"])
    }
    assert verdicts[added] is True
    assert verdicts[removed] is False


def test_scanning_only_the_removal_commit_still_blocks(throwaway_repo, inventory):
    """Pushing just the cleanup commit must not read as clean -- the value is
    in the parent, which is exactly the 2c18992 case."""
    (throwaway_repo / "README").write_text("start\n", encoding="utf-8")
    _git(throwaway_repo, "add", "README")
    _git(throwaway_repo, "commit", "-qm", "initial")
    target = throwaway_repo / "deploy.py"
    target.write_text('PW = "SUPERSECRETVALUE123"\n', encoding="utf-8")
    _git(throwaway_repo, "add", "deploy.py")
    _git(throwaway_repo, "commit", "-qm", "leak")
    target.write_text("PW = os.environ['PW']\n", encoding="utf-8")
    _git(throwaway_repo, "add", "deploy.py")
    _git(throwaway_repo, "commit", "-qm", "remove")

    findings = scan.scan_range(throwaway_repo, "HEAD~1..HEAD",
                               ["SUPERSECRETVALUE123"])
    assert findings, "a push of only the removal commit read as clean"
    assert findings[0][2] is False


def test_empty_tree_is_broken_not_clean(throwaway_repo, inventory):
    with pytest.raises(scan.Broken, match="scope is empty"):
        scan.scan_tree(throwaway_repo, ["SUPERSECRETVALUE123"])


def test_redact_never_echoes_the_whole_value():
    out = scan.redact("SUPERSECRETVALUE123")
    assert "SUPERSECRETVALUE123" not in out
    assert "len 19" in out


# ------------------------------------------------------------------ ignore audit

sys.path.insert(0, str(SCRIPTS))
import ktp_ignore_audit as ignore_audit  # noqa: E402


def _write_ignore(root: Path, body: str) -> None:
    (root / ".gitignore").write_text(
        f"{ignore_audit.REGION_START}\n{body}\n{ignore_audit.REGION_END}\n",
        encoding="utf-8",
    )


def test_untagged_pattern_is_an_error(tmp_path, inventory):
    _write_ignore(tmp_path, "some/path.conf")
    assert ignore_audit.audit(tmp_path, structure_only=True) == 1


def test_guard_without_why_is_an_error(tmp_path, inventory):
    _write_ignore(tmp_path, "# @guard\nsome/path.conf")
    assert ignore_audit.audit(tmp_path, structure_only=True) == 1


def test_guard_with_why_passes_structure_check(tmp_path, inventory):
    _write_ignore(tmp_path, "# @guard\n# why: it used to hold a token\nsome/path.conf")
    assert ignore_audit.audit(tmp_path, structure_only=True) == 0


def test_guard_whose_file_exists_is_an_error(tmp_path, inventory):
    _write_ignore(tmp_path, "# @guard\n# why: stated\npresent.conf")
    (tmp_path / "present.conf").write_text("hello", encoding="utf-8")
    assert ignore_audit.audit(tmp_path) == 1


def test_secret_tag_with_a_real_value_passes(tmp_path, inventory):
    _write_ignore(tmp_path, "# @secret\nreal.conf")
    (tmp_path / "real.conf").write_text("pw=SUPERSECRETVALUE123\n", encoding="utf-8")
    assert ignore_audit.audit(tmp_path) == 0


def test_secret_tag_without_a_value_warns_but_does_not_fail(tmp_path, inventory):
    _write_ignore(tmp_path, "# @secret\nempty.conf")
    (tmp_path / "empty.conf").write_text("pw=\n", encoding="utf-8")
    assert ignore_audit.audit(tmp_path) == 0
    assert ignore_audit.audit(tmp_path, strict=True) == 1


def test_missing_region_markers_report_blind(tmp_path, inventory):
    (tmp_path / ".gitignore").write_text("*.log\n", encoding="utf-8")
    assert ignore_audit.audit(tmp_path, structure_only=True) == 2


def test_fresh_checkout_refuses_content_mode(tmp_path, inventory):
    """None of the tagged files exist -> that is a fresh checkout, not 20 wrong
    tags. Emitting a wall of 'retag @guard' advice there would be wrong
    everywhere the files actually live."""
    _write_ignore(tmp_path, "# @secret\nabsent-a.conf\n\n# @secret\nabsent-b.conf")
    assert ignore_audit.audit(tmp_path) == 2


def test_repo_gitignore_passes_its_own_structure_audit(inventory):
    """The shipped .gitignore must satisfy the rules it documents."""
    assert ignore_audit.audit(REPO, structure_only=True) == 0


def test_structure_only_needs_no_inventory(tmp_path, monkeypatch):
    """The CI path. Structure checks read tags and why: lines -- no values -- so
    requiring an inventory there made the gate depend on a secret it never reads,
    and fork PRs (which get no secrets) could never pass it."""
    monkeypatch.setenv("KTP_SECRET_INVENTORY", str(tmp_path / "absent.txt"))
    _write_ignore(tmp_path, "# @guard\n# why: stated\nsome/path.conf")
    assert ignore_audit.audit(tmp_path, structure_only=True) == 0


def test_repo_structure_audit_passes_without_an_inventory(monkeypatch, tmp_path):
    """Exactly what CI runs, with no inventory present."""
    monkeypatch.setenv("KTP_SECRET_INVENTORY", str(tmp_path / "absent.txt"))
    assert ignore_audit.audit(REPO, structure_only=True) == 0


def test_cli_reports_broken_without_a_traceback(tmp_path, monkeypatch):
    """Running the file as a script makes __main__ a second copy of the module,
    so `except Broken` there stopped catching the class ktp_ignore_audit raised.
    A traceback is exit 1, which reads as 'findings' rather than 'broken'."""
    monkeypatch.setenv("KTP_SECRET_INVENTORY", str(tmp_path / "absent.txt"))
    out = subprocess.run(
        [sys.executable, str(SCRIPTS / "ktp_secret_scan.py"), "tree", "--repo", str(REPO)],
        capture_output=True, text=True,
    )
    assert out.returncode == scan.EXIT_BROKEN, out.stderr
    assert "Traceback" not in out.stderr
    assert "BROKEN" in out.stderr
