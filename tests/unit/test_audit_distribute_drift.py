"""Guards for scripts/audit-distribute-drift.py.

The check exists because the file distributor never reconciles: it pushes on a
filesystem event and nothing else, so an edit made straight onto the instances
lives until the next touch of the source and is then overwritten fleet-wide.
Two properties decide whether the check is worth anything, and both are easy to
lose to a well-meaning tidy-up:

  1. Its scope comes from the distributor's OWN config. If the port of
     PatternMatcher drifts from PatternMatcher.cs, or the excludePatterns leg
     stops being honoured, the check audits a fleet nobody deploys to.
  2. It can actually fire. Every assertion that something is clean is paired
     here with the same fixture mutated, so a vacuous pass is visible.

Nothing here touches a host, a credential, or the network. Every fixture value
is obviously synthetic.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "audit-distribute-drift.py"


def _load():
    sys.modules.setdefault("paramiko", types.ModuleType("paramiko"))
    spec = importlib.util.spec_from_file_location("_ktp_distribute_drift", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def drift():
    return _load()


# ----------------------------------------------------------------- the port
# Each case is lifted from the XML docs on PatternMatcher.MatchesAny: "*.*"
# matches anything, "*.ext" matches a path ending in ".ext" case-insensitively
# in any subdirectory, anything else must equal the whole watch-relative path.
@pytest.mark.parametrize("path,patterns,expected", [
    ("addons/ktpamx/configs/ktp.ini", ["*.ini"], True),
    ("addons/ktpamx/configs/ktp.ini", ["*.cfg"], False),
    ("cached.WAD", ["*.wad"], True),               # case-insensitive suffix
    ("maps/x.bsp", ["*.*"], True),
    ("dodserver.cfg", ["dodserver.cfg"], True),    # exact relative path
    ("sub/dodserver.cfg", ["dodserver.cfg"], False),
    ("anything", [], False),                       # MatchesAny, not the gate
])
def test_matches_any_mirrors_the_shipped_matcher(drift, path, patterns, expected):
    assert drift.matches_any(path, patterns) is expected


def test_empty_watch_patterns_watches_everything(drift):
    """The gate and MatchesAny disagree on an empty list, exactly as in C#."""
    assert drift.matches_watch_patterns("logs/L1221000.log", []) is True
    assert drift.matches_any("logs/L1221000.log", []) is False


def test_watch_patterns_exclude_the_log_class(drift):
    """The live WatchPatterns do not carry *.log, which is why the stale logs in
    the tree are inert -- and why deleting them does not propagate."""
    live = ["*.bsp", "*.txt", "*.bmp", "*.cfg", "*.wad", "*.res", "*.mdl",
            "*.spr", "*.wav", "*.ini", "*.tga"]
    assert drift.matches_watch_patterns("addons/ktpamx/logs/ktp_match.log", live) is False
    assert drift.matches_watch_patterns("addons/ktpamx/configs/ktp.ini", live) is True


def test_exclude_beats_include(drift):
    server = {"includePatterns": ["*.cfg"], "excludePatterns": ["configs/servernamedefault.cfg"]}
    assert drift.accepts(server, "configs/ktpbasic.cfg") is True
    assert drift.accepts(server, "configs/servernamedefault.cfg") is False


def test_no_include_list_accepts_everything_not_excluded(drift):
    assert drift.accepts({}, "anything/at/all.cfg") is True


# --------------------------------------------------- refusing a narrowed scan
@pytest.mark.parametrize("pattern", ["maps/*", "**/*.cfg", "*cfg", "*.cfg*", "*.*"])
def test_unsupported_wildcard_shapes_have_no_extension(drift, pattern):
    assert drift.extension_of(pattern) is None


def test_supported_shape_yields_its_extension(drift):
    assert drift.extension_of("*.cfg") == "cfg"


# --------------------------------------------------------- the remote command
def test_find_command_writes_nothing_and_is_niced(drift):
    cmd = drift.build_find_command("/home/dodserver/dod-27015/serverfiles/dod",
                                   ["cfg", "ini"], watch_everything=False)
    assert "ionice" in cmd and "nice -n19" in cmd
    assert "-iname '*.cfg'" in cmd and "-iname '*.ini'" in cmd
    # A scratch file or a redirection to a real path would be a write on a live
    # game host. `2>/dev/null` is not one, so it is excused by name rather than
    # by loosening the rule.
    residue = cmd.replace("2>/dev/null", "")
    for forbidden in (">", "tee", "mktemp", "rm ", "cp ", "mv "):
        assert forbidden not in residue, "remote command must be read-only"


def test_find_command_without_a_predicate_when_everything_is_watched(drift):
    cmd = drift.build_find_command("/base", [], watch_everything=True)
    assert "-iname" not in cmd
    assert "find . -type f" in cmd


def test_absent_base_path_is_not_an_empty_listing(drift):
    """A missing remote base must not parse as "no files here", which would
    render every path as drift and every target as reached."""
    assert drift.parse_md5_output("__NOBASE__\n") is None
    parsed = drift.parse_md5_output("d41d8cd98f00b204e9800998ecf8427e  ./a/b.cfg\n")
    assert parsed == {"a/b.cfg": "d41d8cd98f00b204e9800998ecf8427e"}


# ------------------------------------------------------------------- shapes
SRC = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def test_shape_per_instance_when_every_target_holds_its_own_copy(drift):
    per_target = {"S%d" % i: "%032x" % i for i in range(4)}
    assert drift.classify(per_target, SRC, total=4) == "per-instance"


def test_shape_uniform_when_the_fleet_agrees_and_the_source_does_not(drift):
    """The discord.ini shape: all 24 agreed with each other, and the source was
    the odd one out. Uniformity alone would have called this healthy."""
    per_target = dict(("S%d" % i, "%032x" % 7) for i in range(4))
    assert drift.classify(per_target, SRC, total=4) == "uniform"


def test_shape_partial_when_only_some_targets_diverge(drift):
    per_target = {"S0": "%032x" % 7, "S1": "%032x" % 7}
    assert drift.classify(per_target, SRC, total=4) == "partial"


def test_shape_partial_when_a_target_is_missing_the_file(drift):
    per_target = {"S0": None, "S1": None}
    assert drift.classify(per_target, SRC, total=4) == "partial"


def test_shape_absent_when_no_target_ever_received_it(drift):
    """A delivery that never started, told apart from one that went wrong: the
    two read identically in a count and call for opposite actions."""
    per_target = dict(("S%d" % i, None) for i in range(4))
    assert drift.classify(per_target, SRC, total=4) == "absent"


# ------------------------------------------------------------ source scanning
def test_source_inventory_honours_watch_patterns(drift, tmp_path):
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs" / "ktpbasic.cfg").write_bytes(b"mp_clan_match 1\n")
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "L1221000.log").write_bytes(b"not distributed\n")
    inventory = drift.source_inventory(tmp_path, ["*.cfg"])
    assert set(inventory) == {"configs/ktpbasic.cfg"}


def test_source_inventory_hashes_content(drift, tmp_path):
    (tmp_path / "a.cfg").write_bytes(b"x")
    first = drift.source_inventory(tmp_path, ["*.cfg"])["a.cfg"][0]
    (tmp_path / "a.cfg").write_bytes(b"y")
    second = drift.source_inventory(tmp_path, ["*.cfg"])["a.cfg"][0]
    assert first != second, "a content change must move the hash"


# ------------------------------------------------------------------- report
def _report(drift, findings, source, reached=("S0", "S1", "S2", "S3")):
    return drift.build_report(Path("/home/dod/distribute"), source, findings,
                              list(reached), list(reached), [], verbose=True)


def test_a_matching_fleet_reports_no_divergence(drift):
    text, stable, hazards = _report(drift, {}, {"a.cfg": (SRC, 0)})
    assert "No divergence" in text
    assert stable == [] and hazards == 0


def test_the_same_fixture_with_one_seeded_difference_fires(drift):
    """The control for the test above. Same inputs, one instance changed."""
    findings = {"a.cfg": {"S0": "%032x" % 9}}
    text, stable, hazards = _report(drift, findings, {"a.cfg": (SRC, 0)})
    assert "No divergence" not in text
    assert stable and stable[0].startswith("DRIFT: a.cfg")


def test_a_per_instance_path_is_counted_as_a_standing_hazard(drift):
    findings = {"configs/servernamedefault.cfg":
                dict(("S%d" % i, "%032x" % i) for i in range(4))}
    text, _stable, hazards = _report(drift, findings,
                                     {"configs/servernamedefault.cfg": (SRC, 0)})
    assert hazards == 1
    assert "excludePatterns" in text


def test_a_uniform_path_is_not_a_hazard_but_is_still_drift(drift):
    findings = {"configs/ktpbasic.cfg": dict(("S%d" % i, "%032x" % 7) for i in range(4))}
    text, stable, hazards = _report(drift, findings, {"configs/ktpbasic.cfg": (SRC, 0)})
    assert hazards == 0
    assert "uniform" in text and stable


def test_no_full_md5_reaches_the_report(drift):
    """audit_redact blanks any bare 32-hex run, so a full hash in the report
    would render as <redacted> and the report would say nothing. Truncating to
    16 is what keeps the evidence readable AND publishable."""
    findings = {"a.cfg": {"S0": "%032x" % 9}}
    text, stable, _ = _report(drift, findings, {"a.cfg": (SRC, 0)})
    assert SRC not in text and SRC not in "\n".join(stable)
    assert SRC[:16] in "\n".join(stable)


def test_unreachable_targets_are_named_in_the_report(drift):
    text, _stable, _hazards = drift.build_report(
        Path("/home/dod/distribute"), {}, {}, ["S0"], ["S0", "S1"],
        ["S1 (SSHException)"], verbose=False)
    assert "Unreachable: S1 (SSHException)" in text
    assert "targets reached: 1/2" in text


# --------------------------------------------------------------- config load
def _write_config(tmp_path, watch_patterns, servers):
    (tmp_path / "appsettings.json").write_text(json.dumps({
        "AppSettings": {"WatchDirectory": str(tmp_path / "tree"),
                        "WatchPatterns": watch_patterns}}), encoding="utf-8")
    (tmp_path / "servers.json").write_text(json.dumps(servers), encoding="utf-8")


def test_auth_fields_never_leave_the_config_loader(drift, tmp_path):
    """servers.json may carry a password on a password-auth install. Nothing
    downstream can print a credential it was never handed."""
    _write_config(tmp_path, ["*.cfg"], [
        {"name": "Example 1", "host": "10.0.0.1", "username": "synthetic-user",
         "password": "SYNTHETIC-NOT-A-REAL-PASSWORD",
         "privateKeyPath": "/dev/null", "privateKeyPassphrase": "synthetic",
         "remoteBasePath": "/srv/example/dod", "enabled": True},
    ])
    _watch_dir, _patterns, servers = drift.load_distributor_config(tmp_path)
    blob = json.dumps(servers)
    for leaked in ("password", "privateKey", "username", "SYNTHETIC"):
        assert leaked not in blob


def test_per_server_filters_survive_the_config_loader(drift, tmp_path):
    """The excludePatterns leg is the whole declaration mechanism -- dropping it
    here would make every declared per-instance file read as drift forever."""
    _write_config(tmp_path, ["*.cfg"], [
        {"name": "Example 1", "host": "10.0.0.1", "remoteBasePath": "/srv/example/dod",
         "enabled": True, "excludePatterns": ["configs/servernamedefault.cfg"],
         "includePatterns": ["*.cfg"]},
    ])
    _watch_dir, _patterns, servers = drift.load_distributor_config(tmp_path)
    assert servers[0]["excludePatterns"] == ["configs/servernamedefault.cfg"]
    assert drift.accepts(servers[0], "configs/servernamedefault.cfg") is False


def test_an_unparsable_distributor_config_is_fatal_not_empty(drift, tmp_path):
    (tmp_path / "appsettings.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "servers.json").write_text("[]", encoding="utf-8")
    with pytest.raises(SystemExit):
        drift.load_distributor_config(tmp_path)
