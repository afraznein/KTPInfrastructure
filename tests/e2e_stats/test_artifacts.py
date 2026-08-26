"""Unit tests for the Lane B artifact build.

The property worth protecting here is that artifacts come from the **commit**,
not the working tree. If that slips, "Lane B passed on this branch" quietly
becomes "Lane B passed on whatever was lying around on the runner", and the
lane stops gating anything. `test_extract_ignores_working_tree_edits` is the
one to keep.

No amxxpc, no hlds, no MySQL — just git and the filesystem.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from .artifacts import (
    ArtifactSet,
    BuildError,
    DEFAULT_SCHEMA_FILES,
    directory_tree_provenance,
    extract,
    load_gamedata_provenance,
    load_bundle_provenance,
    record_bundle_provenance,
    render_bundle_provenance_markdown,
    resolve_ref,
    validate_gamedata_bundle_source,
)


def _git(repo, *args):
    subprocess.run(["git", "-C", str(repo), *args], check=True,
                   capture_output=True, text=True)


@pytest.fixture
def amxx_repo(tmp_path):
    """A fake KTPAMXX with two commits, so 'which ref' is a real question."""
    repo = tmp_path / "KTPAMXX"
    (repo / "plugins" / "dod").mkdir(parents=True)
    (repo / "plugins" / "include").mkdir(parents=True)
    _git(repo.parent, "init", "-q", "KTPAMXX")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")

    (repo / "plugins" / "dod" / "stats_logging.sma").write_text("// v1\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "v1 without capture")
    _git(repo, "branch", "base")

    # CRLF on purpose — every one of these repos is CRLF, and the compile step
    # normalises. Encoding it in the fixture keeps that path honest.
    (repo / "plugins" / "dod" / "stats_logging.sma").write_bytes(
        b"// v2\r\n#include \"ktp_stats_capture.inc\"\r\n")
    (repo / "plugins" / "dod" / "ktp_stats_capture.inc").write_bytes(
        b"// capture v2\r\nstock ksc_init() {}\r\n")
    for rel in (
        "common.games/master.games.txt",
        "common.games/functions.engine.txt",
        "common.games/globalvars.engine.txt",
        "common.games/gamerules.games/master.games.txt",
        "common.games/gamerules.games/dod/offsets-cdodteamplay.txt",
    ):
        path = repo / "gamedata" / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(("committed " + rel + "\n").encode())
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "v2 with capture")
    _git(repo, "branch", "feat/stats-positions")
    return repo


@pytest.fixture
def daemon_repo(tmp_path):
    repo = tmp_path / "KTPHLStatsX"
    (repo / "scripts").mkdir(parents=True)
    (repo / "sql").mkdir(parents=True)
    _git(repo.parent, "init", "-q", "KTPHLStatsX")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "scripts" / "hlstats.pl").write_text("#!/usr/bin/perl\n")
    (repo / "sql" / "ktp_schema.sql").write_text("CREATE TABLE hlstats_Actions (id INT);\n")
    (repo / "sql" / "migrate_003_assist_action.sql").write_text(
        "INSERT IGNORE INTO hlstats_Actions VALUES (1);\n")
    (repo / "sql" / "migrate_004_cap_break_action.sql").write_text(
        "INSERT IGNORE INTO hlstats_Actions VALUES (2);\n")
    for number, name in (
        (5, "frag_context_columns"),
        (6, "damage_ledger"),
        (7, "break_context"),
        (8, "position_samples"),
        (9, "disable_connect_announcements"),
        (10, "flag_captures"),
        (11, "match_player_identity_width"),
        (12, "frag_context_correlation"),
        (13, "ktp_table_collation"),
        (14, "match_type_retention"),
        (15, "flag_state_events"),
        (16, "life_events"),
        (17, "capture_clocks_and_assists"),
        (18, "break_context_correlation"),
        (19, "clear_uncertified_frag_context"),
        (20, "frag_context_certified"),
        (21, "capture_observability"),
        (22, "objective_attempts_grenade_entities"),
    ):
        (repo / "sql" / f"migrate_{number:03d}_{name}.sql").write_text(
            f"-- migration {number}\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "daemon")
    _git(repo, "branch", "feat/seed-cap-break-action")
    return repo


def test_collect_gathers_every_artifact(amxx_repo, daemon_repo, tmp_path):
    arts = ArtifactSet.collect(
        tmp_path / "out",
        amxx_repo=amxx_repo, amxx_ref="feat/stats-positions",
        daemon_repo=daemon_repo, daemon_ref="feat/seed-cap-break-action",
    )
    assert arts.plugin_sma.is_file()
    assert arts.plugin_inc.is_file()
    assert arts.gamedata_dir.is_dir()
    assert arts.hlstats_pl.is_file()
    assert len(arts.schema_sql) == 19
    assert len(arts.seed_sql) == 2


def test_default_schema_sequence_includes_retention_through_telemetry22():
    assert DEFAULT_SCHEMA_FILES[-9:] == (
        "sql/migrate_014_match_type_retention.sql",
        "sql/migrate_015_flag_state_events.sql",
        "sql/migrate_016_life_events.sql",
        "sql/migrate_017_capture_clocks_and_assists.sql",
        "sql/migrate_018_break_context_correlation.sql",
        "sql/migrate_019_clear_uncertified_frag_context.sql",
        "sql/migrate_020_frag_context_certified.sql",
        "sql/migrate_021_capture_observability.sql",
        "sql/migrate_022_objective_attempts_grenade_entities.sql",
    )


def test_sma_and_inc_land_in_the_same_directory(amxx_repo, daemon_repo, tmp_path):
    """stats_logging.sma #includes the .inc by relative path. The production
    Docker build needed a dedicated COPY line for exactly this; if the two ever
    land in different directories here, amxxpc fails with 'cannot read
    ktp_stats_capture.inc'."""
    arts = ArtifactSet.collect(
        tmp_path / "out",
        amxx_repo=amxx_repo, amxx_ref="feat/stats-positions",
        daemon_repo=daemon_repo, daemon_ref="feat/seed-cap-break-action",
    )
    assert arts.plugin_sma.parent == arts.plugin_inc.parent


def test_extract_ignores_working_tree_edits(amxx_repo, tmp_path):
    """THE load-bearing test. A dirty working tree must not leak into a run."""
    (amxx_repo / "plugins" / "dod" / "stats_logging.sma").write_text(
        "// UNCOMMITTED GARBAGE\n")
    out = extract(amxx_repo, "feat/stats-positions",
                  "plugins/dod/stats_logging.sma", tmp_path / "got.sma")
    body = out.read_bytes()
    assert b"UNCOMMITTED" not in body
    assert b"v2" in body


def test_gamedata_tree_is_commit_extracted_and_manifest_bound(
        amxx_repo, daemon_repo, tmp_path):
    dirty = amxx_repo / "gamedata/common.games/globalvars.engine.txt"
    dirty.write_bytes(b"UNCOMMITTED GAMEDATA\x00")
    arts = ArtifactSet.collect(
        tmp_path / "out",
        amxx_repo=amxx_repo, amxx_ref="feat/stats-positions",
        daemon_repo=daemon_repo, daemon_ref="feat/seed-cap-break-action",
    )
    assert b"UNCOMMITTED" not in (
        arts.gamedata_dir / "common.games/globalvars.engine.txt"
    ).read_bytes()
    expected = arts.provenance["amxx"]["gamedata"]
    loaded = load_gamedata_provenance(arts.write_manifest())
    assert loaded["tree_sha256"] == expected["tree_sha256"]
    assert loaded["file_count"] == 5
    assert loaded["bytes"] == sum(item["bytes"] for item in loaded["files"])


def test_gamedata_manifest_rejects_byte_or_tree_digest_tampering(
        amxx_repo, daemon_repo, tmp_path):
    arts = ArtifactSet.collect(
        tmp_path / "out",
        amxx_repo=amxx_repo, amxx_ref="feat/stats-positions",
        daemon_repo=daemon_repo, daemon_ref="feat/seed-cap-break-action",
    )
    manifest = arts.write_manifest()
    body = json.loads(manifest.read_text())
    body["provenance"]["amxx"]["gamedata"]["files"][0]["bytes"] += 1
    manifest.write_text(json.dumps(body))
    with pytest.raises(BuildError, match="byte total|tree SHA"):
        load_gamedata_provenance(manifest)


@pytest.mark.parametrize("bad_path", [
    "../escape", r"..\escape", "C:/escape", "a//b", "a/./b",
])
def test_gamedata_manifest_rejects_noncanonical_paths(
        amxx_repo, daemon_repo, tmp_path, bad_path):
    arts = ArtifactSet.collect(
        tmp_path / "out",
        amxx_repo=amxx_repo, amxx_ref="feat/stats-positions",
        daemon_repo=daemon_repo, daemon_ref="feat/seed-cap-break-action",
    )
    manifest = arts.write_manifest()
    body = json.loads(manifest.read_text())
    body["provenance"]["amxx"]["gamedata"]["files"][0]["path"] = bad_path
    manifest.write_text(json.dumps(body))
    with pytest.raises(BuildError, match="invalid/duplicate"):
        load_gamedata_provenance(manifest)


def test_gamedata_source_label_must_match_bundle_amxx_commit():
    bundle = {"repositories": {"amxx": {"sha": "a" * 40}}}
    validate_gamedata_bundle_source(
        bundle, {"source": f"{'a' * 40}:gamedata"}
    )
    with pytest.raises(BuildError, match="expected"):
        validate_gamedata_bundle_source(
            bundle, {"source": f"{'b' * 40}:gamedata"}
        )


def test_tree_digest_changes_on_same_length_byte_change_and_path_change(tmp_path):
    tree = tmp_path / "tree"
    (tree / "nested").mkdir(parents=True)
    payload = tree / "nested/data.bin"
    payload.write_bytes(b"abc\x00")
    first = directory_tree_provenance(tree)
    payload.write_bytes(b"abd\x00")
    second = directory_tree_provenance(tree)
    assert first["bytes"] == second["bytes"] == 4
    assert first["files"][0]["sha256"] != second["files"][0]["sha256"]
    assert first["tree_sha256"] != second["tree_sha256"]
    payload.rename(tree / "nested/renamed.bin")
    third = directory_tree_provenance(tree)
    assert second["tree_sha256"] != third["tree_sha256"]


def test_collect_at_an_older_ref_omits_the_include(amxx_repo, daemon_repo, tmp_path):
    """At `base` the include does not exist yet, so collection must fail loudly
    rather than produce a set that compiles into a plugin without capture."""
    with pytest.raises(BuildError, match="ktp_stats_capture.inc"):
        ArtifactSet.collect(
            tmp_path / "out",
            amxx_repo=amxx_repo, amxx_ref="base",
            daemon_repo=daemon_repo, daemon_ref="feat/seed-cap-break-action",
        )


def test_collect_without_plugin_does_not_require_amxx_sources(
        amxx_repo, daemon_repo, tmp_path):
    """Corpus replay is daemon-only. It must work even when the counterpart
    AMXX ref predates stats capture (or is otherwise irrelevant to replay)."""
    arts = ArtifactSet.collect(
        tmp_path / "out",
        amxx_repo=amxx_repo, amxx_ref="no/such/branch",
        daemon_repo=daemon_repo, daemon_ref="feat/seed-cap-break-action",
        include_plugin=False,
    )
    assert arts.plugin_sma is None
    assert arts.plugin_inc is None
    assert arts.hlstats_pl.is_file()
    assert arts.provenance["amxx"]["sha"] is None


def test_missing_ref_is_a_build_error(amxx_repo, daemon_repo, tmp_path):
    with pytest.raises(BuildError):
        ArtifactSet.collect(
            tmp_path / "out",
            amxx_repo=amxx_repo, amxx_ref="no/such/branch",
            daemon_repo=daemon_repo, daemon_ref="feat/seed-cap-break-action",
        )


def test_manifest_records_shas_and_md5s(amxx_repo, daemon_repo, tmp_path):
    arts = ArtifactSet.collect(
        tmp_path / "out",
        amxx_repo=amxx_repo, amxx_ref="feat/stats-positions",
        daemon_repo=daemon_repo, daemon_ref="feat/seed-cap-break-action",
    )
    path = arts.write_manifest()
    m = json.loads(path.read_text())
    assert m["provenance"]["amxx"]["sha"] == resolve_ref(amxx_repo, "feat/stats-positions")
    assert m["provenance"]["daemon"]["ref"] == "feat/seed-cap-break-action"
    assert len(m["files"]["hlstats.pl"]["md5"]) == 32
    # Every SQL file is fingerprinted — the plan verifies deploys by md5 and a
    # test run should be as traceable as a deploy.
    for name in ("ktp_schema.sql", "migrate_003_assist_action.sql",
                 "migrate_004_cap_break_action.sql",
                 "migrate_005_frag_context_columns.sql",
                 "migrate_006_damage_ledger.sql",
                 "migrate_007_break_context.sql",
                 "migrate_008_position_samples.sql",
                 "migrate_009_disable_connect_announcements.sql",
                 "migrate_010_flag_captures.sql",
                 "migrate_011_match_player_identity_width.sql",
                 "migrate_012_frag_context_correlation.sql",
                 "migrate_013_ktp_table_collation.sql",
                 "migrate_014_match_type_retention.sql",
                 "migrate_015_flag_state_events.sql",
                 "migrate_016_life_events.sql",
                 "migrate_017_capture_clocks_and_assists.sql",
                 "migrate_018_break_context_correlation.sql",
                 "migrate_019_clear_uncertified_frag_context.sql",
                 "migrate_020_frag_context_certified.sql",
                 "migrate_021_capture_observability.sql",
                 "migrate_022_objective_attempts_grenade_entities.sql"):
        assert len(m["files"][name]["md5"]) == 32


def _bundle_repositories(amxx_repo, daemon_repo):
    amxx_sha = resolve_ref(amxx_repo, "feat/stats-positions")
    daemon_sha = resolve_ref(daemon_repo, "feat/seed-cap-break-action")
    return {
        "infrastructure": {
            "repository": "afraznein/KTPInfrastructure",
            "requested_ref": "feat/fps-stats-exploration-bundle",
            "sha": "1" * 40,
        },
        "matchhandler": {
            "repository": "afraznein/KTPMatchHandler",
            "requested_ref": "e27afc7",
            "sha": "2" * 40,
        },
        "amxx": {
            "repository": "afraznein/KTPAMXX",
            "requested_ref": "feat/stats-positions",
            "sha": amxx_sha,
        },
        "hlstatsx": {
            "repository": "afraznein/KTPHLStatsX",
            "requested_ref": "feat/seed-cap-break-action",
            "sha": daemon_sha,
        },
    }


def test_bundle_provenance_records_all_four_full_shas(
        amxx_repo, daemon_repo, tmp_path):
    arts = ArtifactSet.collect(
        tmp_path / "out",
        amxx_repo=amxx_repo, amxx_ref="feat/stats-positions",
        daemon_repo=daemon_repo, daemon_ref="feat/seed-cap-break-action",
    )
    manifest = arts.write_manifest()
    repositories = _bundle_repositories(amxx_repo, daemon_repo)
    bundle = record_bundle_provenance(
        manifest,
        repositories,
        workflow_context={
            "workflow_ref": "afraznein/KTPInfrastructure/.github/workflows/"
                            "lane-b-stats-e2e.yml@refs/heads/main",
            "event_sha": "3" * 40,
            "run_url": "https://github.com/afraznein/KTPInfrastructure/actions/runs/1",
        },
    )

    loaded = load_bundle_provenance(manifest)
    assert loaded == bundle
    assert set(loaded["repositories"]) == {
        "infrastructure", "matchhandler", "amxx", "hlstatsx",
    }
    assert all(len(item["sha"]) == 40
               for item in loaded["repositories"].values())
    saved = json.loads(manifest.read_text())
    assert saved["provenance"]["bundle"] == bundle
    rendered = render_bundle_provenance_markdown(bundle)
    assert repositories["infrastructure"]["sha"] in rendered
    assert repositories["matchhandler"]["sha"] in rendered
    assert repositories["amxx"]["sha"] in rendered
    assert repositories["hlstatsx"]["sha"] in rendered


def test_bundle_provenance_refuses_an_incomplete_repository_set(
        amxx_repo, daemon_repo, tmp_path):
    arts = ArtifactSet.collect(
        tmp_path / "out",
        amxx_repo=amxx_repo, amxx_ref="feat/stats-positions",
        daemon_repo=daemon_repo, daemon_ref="feat/seed-cap-break-action",
    )
    manifest = arts.write_manifest()
    repositories = _bundle_repositories(amxx_repo, daemon_repo)
    repositories.pop("matchhandler")
    with pytest.raises(BuildError, match="exactly infrastructure"):
        record_bundle_provenance(manifest, repositories)


def test_bundle_provenance_refuses_artifact_checkout_mismatch(
        amxx_repo, daemon_repo, tmp_path):
    arts = ArtifactSet.collect(
        tmp_path / "out",
        amxx_repo=amxx_repo, amxx_ref="feat/stats-positions",
        daemon_repo=daemon_repo, daemon_ref="feat/seed-cap-break-action",
    )
    manifest = arts.write_manifest()
    repositories = _bundle_repositories(amxx_repo, daemon_repo)
    repositories["amxx"]["sha"] = "f" * 40
    with pytest.raises(BuildError, match="collected artifact came from"):
        record_bundle_provenance(manifest, repositories)


def test_bundle_provenance_requires_immutable_full_shas(
        amxx_repo, daemon_repo, tmp_path):
    arts = ArtifactSet.collect(
        tmp_path / "out",
        amxx_repo=amxx_repo, amxx_ref="feat/stats-positions",
        daemon_repo=daemon_repo, daemon_ref="feat/seed-cap-break-action",
    )
    manifest = arts.write_manifest()
    repositories = _bundle_repositories(amxx_repo, daemon_repo)
    repositories["matchhandler"]["sha"] = "preprod"
    with pytest.raises(BuildError, match="40-character Git commit SHA"):
        record_bundle_provenance(manifest, repositories)


def test_use_prebuilt_plugin_records_provenance(amxx_repo, daemon_repo, tmp_path):
    arts = ArtifactSet.collect(
        tmp_path / "out",
        amxx_repo=amxx_repo, amxx_ref="feat/stats-positions",
        daemon_repo=daemon_repo, daemon_ref="feat/seed-cap-break-action",
    )
    prebuilt = tmp_path / "stats_logging.amxx"
    prebuilt.write_bytes(b"AMXX fake compiled")
    arts.use_prebuilt_plugin(prebuilt)
    m = arts.manifest()
    assert m["files"]["stats_logging.amxx"]["md5"] == "0d1e0c9b4f9f0b9d1d0a4c6f7e2b8a31" or \
        len(m["files"]["stats_logging.amxx"]["md5"]) == 32
    assert m["provenance"]["build"]["prebuilt_from"] == str(prebuilt)


def test_use_prebuilt_plugin_rejects_a_missing_file(amxx_repo, daemon_repo, tmp_path):
    arts = ArtifactSet.collect(
        tmp_path / "out",
        amxx_repo=amxx_repo, amxx_ref="feat/stats-positions",
        daemon_repo=daemon_repo, daemon_ref="feat/seed-cap-break-action",
    )
    with pytest.raises(BuildError, match="prebuilt plugin not found"):
        arts.use_prebuilt_plugin(tmp_path / "nope.amxx")


def test_compile_plugin_rejects_a_missing_amxxpc(amxx_repo, daemon_repo, tmp_path):
    arts = ArtifactSet.collect(
        tmp_path / "out",
        amxx_repo=amxx_repo, amxx_ref="feat/stats-positions",
        daemon_repo=daemon_repo, daemon_ref="feat/seed-cap-break-action",
    )
    inc = tmp_path / "include"
    inc.mkdir()
    with pytest.raises(BuildError, match="amxxpc not found"):
        arts.compile_plugin(amxxpc=tmp_path / "nope", include_dir=inc)


def test_compile_plugin_fails_loudly_on_a_failing_compiler(
        amxx_repo, daemon_repo, tmp_path, monkeypatch):
    """The Docker build swallows compile errors with `|| echo WARNING`. This
    lane must not: a run that proceeds with a stale plugin reports on the wrong
    artifact."""
    arts = ArtifactSet.collect(
        tmp_path / "out",
        amxx_repo=amxx_repo, amxx_ref="feat/stats-positions",
        daemon_repo=daemon_repo, daemon_ref="feat/seed-cap-break-action",
    )
    fake = tmp_path / "amxxpc"
    fake.write_text("")
    inc = tmp_path / "include"
    inc.mkdir()

    class Result:
        returncode = 1
        stdout = "stats_logging.sma(12) : error 017: undefined symbol\n"
        stderr = ""

    monkeypatch.setattr("tests.e2e_stats.artifacts.subprocess.run",
                        lambda *a, **k: Result())
    with pytest.raises(BuildError, match="amxxpc failed"):
        arts.compile_plugin(amxxpc=fake, include_dir=inc)


def test_compile_plugin_fails_when_compiler_exits_zero_but_writes_nothing(
        amxx_repo, daemon_repo, tmp_path, monkeypatch):
    """amxxpc has been observed exiting 0 without producing output. Trusting
    the exit code alone would stage a nonexistent plugin."""
    arts = ArtifactSet.collect(
        tmp_path / "out",
        amxx_repo=amxx_repo, amxx_ref="feat/stats-positions",
        daemon_repo=daemon_repo, daemon_ref="feat/seed-cap-break-action",
    )
    fake = tmp_path / "amxxpc"
    fake.write_text("")
    inc = tmp_path / "include"
    inc.mkdir()

    class Result:
        returncode = 0
        stdout = "Header size: 123 bytes\n"
        stderr = ""

    monkeypatch.setattr("tests.e2e_stats.artifacts.subprocess.run",
                        lambda *a, **k: Result())
    with pytest.raises(BuildError, match="amxxpc failed"):
        arts.compile_plugin(amxxpc=fake, include_dir=inc)


def test_compile_normalises_crlf_before_compiling(amxx_repo, daemon_repo, tmp_path,
                                                  monkeypatch):
    """These repos are CRLF in the working tree and the Docker build strips CR
    before amxxpc. Do the same, so a compile difference can never be a
    line-ending difference.

    Note the CRLF is injected *after* collection rather than relied on from the
    fixture: what `git show` emits depends on the repo's `core.autocrlf` and
    `.gitattributes`, so an extracted file may be LF even when the working tree
    is CRLF. The normalisation has to be robust to either, which is precisely
    why it is unconditional in `compile_plugin` instead of guarded.
    """
    arts = ArtifactSet.collect(
        tmp_path / "out",
        amxx_repo=amxx_repo, amxx_ref="feat/stats-positions",
        daemon_repo=daemon_repo, daemon_ref="feat/seed-cap-break-action",
    )
    arts.plugin_sma.write_bytes(b'// v2\r\n#include "ktp_stats_capture.inc"\r\n')
    arts.plugin_inc.write_bytes(b"// capture v2\r\nstock ksc_init() {}\r\n")
    assert b"\r\n" in arts.plugin_sma.read_bytes()

    fake = tmp_path / "amxxpc"
    fake.write_text("")
    inc = tmp_path / "include"
    inc.mkdir()
    out_path = arts.build_dir / "stats_logging.amxx"

    class Result:
        returncode = 0
        stdout = "ok\n"
        stderr = ""

    def fake_run(*a, **k):
        out_path.write_bytes(b"AMXX")
        return Result()

    monkeypatch.setattr("tests.e2e_stats.artifacts.subprocess.run", fake_run)
    arts.compile_plugin(amxxpc=fake, include_dir=inc)
    assert b"\r\n" not in arts.plugin_sma.read_bytes()
    assert b"\r\n" not in arts.plugin_inc.read_bytes()


def test_compile_plugin_passes_and_records_lane_b_defines(
        amxx_repo, daemon_repo, tmp_path, monkeypatch):
    arts = ArtifactSet.collect(
        tmp_path / "out",
        amxx_repo=amxx_repo, amxx_ref="feat/stats-positions",
        daemon_repo=daemon_repo, daemon_ref="feat/seed-cap-break-action",
    )
    fake = tmp_path / "amxxpc"
    fake.write_text("")
    inc = tmp_path / "include"
    inc.mkdir()
    out_path = arts.build_dir / "stats_logging.amxx"
    seen = {}

    class Result:
        returncode = 0
        stdout = "ok\n"
        stderr = ""

    def fake_run(argv, **kwargs):
        seen["argv"] = argv
        out_path.write_bytes(b"AMXX")
        return Result()

    monkeypatch.setattr("tests.e2e_stats.artifacts.subprocess.run", fake_run)
    define = "KTP_LANE_B_BOT_WEAPONSTATS=1"
    arts.compile_plugin(amxxpc=fake, include_dir=inc, defines=(define,))

    assert seen["argv"][-1] == define
    assert arts.provenance["build"]["defines"] == [define]
