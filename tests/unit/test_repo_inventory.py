"""ktp-repo-inventory.py: its own selftest, plus proof that selftest can fail.

The script carries `--selftest` so it can be run from a terminal without a
token, and this file is what makes that selftest run in CI at all. The second
test is the one that matters: a selftest wired to `return 0` passes forever and
reads identically to a real one, so one check here breaks a fixture on purpose
and requires the selftest to notice.

`test_public_listing_omits_private_repos` is the trap that made this script
worth writing. The first live run read 24 of the estate's 34 repos and printed a
complete-looking table; `users/<owner>/repos` had quietly dropped every private
one, and the branch-count control could not see it because the repos it did read
answered normally.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "ktp_repo_inventory", _ROOT / "scripts" / "ktp-repo-inventory.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ktp_repo_inventory"] = mod
    spec.loader.exec_module(mod)
    return mod


ri = _load()


def test_selftest_passes():
    assert ri.selftest() == 0


def test_selftest_can_fail(monkeypatch):
    """Break one fixture's premise; the selftest must go red."""
    monkeypatch.setattr(ri, "GUARDED_REFS", {})
    assert ri.selftest() != 0


def test_public_listing_omits_private_repos():
    """The authenticated listing is used for one's own repos, not the public one."""
    api = ri._fake_api({
        "users/o/repos?per_page=100&type=owner": [[{"name": "KTPPub"}]],
        "user/repos?per_page=100&affiliation=owner": [[{"name": "KTPPub"},
                                                       {"name": "KTPPriv"}]],
    })
    names, complete, _ = ri.repo_set(api, "o", "KTP", (), include_foreign=False,
                                     viewer="o")
    assert complete is True
    assert names == ["o/KTPPub", "o/KTPPriv"]


def test_listing_that_drops_a_public_repo_is_not_counted():
    api = ri._fake_api({
        "users/o/repos?per_page=100&type=owner": [[{"name": "KTPPub"}]],
        "user/repos?per_page=100&affiliation=owner": [[{"name": "KTPPriv"}]],
    })
    _, complete, lines = ri.repo_set(api, "o", "KTP", (), include_foreign=False,
                                     viewer="o")
    assert complete is False
    assert any("not a subset" in line for line in lines)


def test_a_repo_that_errors_is_not_a_zero():
    """read_repo raises; main turns that into ERROR and exit 2, never an empty row."""
    api = ri._fake_api({})
    with pytest.raises(ri.ApiError):
        ri.read_repo(api, "o/gone")


def test_orphan_compare_is_a_finding_not_a_failed_probe():
    api = ri._fake_api({
        "repos/o/r/compare/main...orph": ri.ApiError(
            404, "HTTP 404: No common ancestor between main and orph"),
    })
    assert ri.compare_branch(api, "o/r", "main", "orph")["state"] == "ORPHAN"


def test_foreign_repos_are_in_the_sweep_and_are_the_only_typed_names():
    """An owner listing cannot produce another account's repo, so those are named."""
    api = ri._fake_api({
        "users/o/repos?per_page=100&type=owner": [[{"name": "KTPPub"}]],
        "user/repos?per_page=100&affiliation=owner": [[{"name": "KTPPub"}]],
    })
    names, _, _ = ri.repo_set(api, "o", "KTP", (), viewer="o")
    for foreign in ri.FOREIGN_REPOS:
        assert foreign in names
    assert all("/" in name for name in names)
