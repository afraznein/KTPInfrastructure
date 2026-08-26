import inspect
from pathlib import Path

import pytest

from scripts.lane_b_e2e import (gamerules_clock_preflight,
                                 match_epoch_interval,
                                 persist_preflight_failure,
                                replay_boot_flag_positions, run_match,
                                stage_objective_wire_witness, stage_tree)


ROOT = Path(__file__).resolve().parents[2]


def test_objective_wire_witness_stages_exact_lifecycles_and_health():
    class FakeDb:
        def __init__(self):
            self.statements = []

        def scalar(self, query):
            assert "hlstats_Servers" in query
            return 1

        def sql(self, query):
            self.statements.append(query)

    class FakeDaemon:
        def __init__(self):
            self.lines = []

        def feed_line(self, line):
            self.lines.append(line)

    db, daemon = FakeDb(), FakeDaemon()
    evidence = stage_objective_wire_witness(db, daemon, map_name="dod_anzio")

    assert evidence["scenarios"] == [
        "start_complete", "start_stop_capture_stopped",
        "start_stop_context_reset", "left_censored_complete",
    ]
    assert evidence["evidence_scope"] == (
        "synthetic_wire_to_real_daemon_to_ephemeral_mysql"
    )
    assert evidence["production_polling_scope"] == (
        "separate_live_bot_capture_health_only"
    )
    assert len(db.statements) == 1
    assert "objective-witness-TEST" in db.statements[0]
    assert len(daemon.lines) == 18
    assert sum("KTP_CAPTURE_MANIFEST " in line for line in daemon.lines) == 1
    objectives = [line for line in daemon.lines if "KTP_OBJECTIVE_ATTEMPT " in line]
    assert len(objectives) == 7
    assert sum('(kind "start")' in line for line in objectives) == 3
    assert sum('(kind "complete")' in line for line in objectives) == 2
    assert sum('(kind "stop")' in line for line in objectives) == 2
    assert sum('(stop_reason "capture_stopped")' in line for line in objectives) == 1
    assert sum('(stop_reason "context_reset")' in line for line in objectives) == 1
    assert any(
        '(kind "complete")' in line and '(attempt_id "1")' in line
        and '(sequence "8")' in line for line in objectives
    )
    health = [line for line in daemon.lines if "KTP_CAPTURE_HEALTH " in line]
    assert len(health) == 10
    objective_health = next(
        line for line in health if '(event_type "objective_attempt")' in line
    )
    assert '(attempted "7")' in objective_health
    assert '(enqueued "7")' in objective_health
    assert '(emitted "7")' in objective_health


def test_full_lane_builds_test_core_from_the_exact_amxx_checkout():
    workflow = (ROOT / ".github/workflows/lane-b-stats-e2e.yml").read_text()
    action = (ROOT / ".github/actions/build-ktpamx-laneb/action.yml").read_text()
    script = (ROOT / "scripts/build_ktpamx_laneb.sh").read_text()
    runner = (ROOT / "scripts/lane_b_e2e.py").read_text()

    assert "ref: feat/lane-b-fakeclient-players" not in workflow
    assert "repo: ${{ github.workspace }}/KTPAMXX" in workflow
    assert "          ref: HEAD" in workflow
    assert "CORE_AMXX_SHA" in workflow
    assert 'if [ "$CORE_AMXX_SHA" != "$BUNDLE_AMXX_SHA" ]' in workflow
    assert '-v "${PWD}/.github:/work/.github:ro"' in workflow
    assert '-v "${PWD}/sql:/work/sql:ro"' in workflow
    assert "    default: preprod" in action
    assert 'REF="${LANEB_REF:-preprod}"' in script
    assert "dodx-so-path:" in action
    assert "--dodx-so /work/build/dodx_ktp_i386.so" in workflow
    assert "--amxx-gamedata /work/build/artifacts/gamedata" in workflow
    assert '-v "${PWD}/config:/work/config:ro"' in workflow
    assert 'tree.overlay_file(dodx_so, "dod/addons/ktpamx/modules/dodx_ktp_i386.so")' in runner


def test_manual_lane_accepts_and_records_all_four_bundle_refs():
    workflow = (ROOT / ".github/workflows/lane-b-stats-e2e.yml").read_text()
    runner = (ROOT / "scripts/lane_b_e2e.py").read_text()

    assert "infrastructure_ref:" in workflow
    assert "matchhandler_ref:" in workflow
    assert "ref: ${{ env.INFRASTRUCTURE_REF }}" in workflow
    assert "ref: ${{ env.MATCHHANDLER_REF }}" in workflow
    assert "--amxx-ref   '${AMXX_SHA}'" in workflow
    assert "--daemon-ref '${DAEMON_SHA}'" in workflow
    assert "Record immutable four-repository bundle provenance" in workflow
    for name in ("infrastructure", "matchhandler", "amxx", "hlstatsx"):
        assert f"--repository {name} " in workflow
    assert "--artifact-manifest /work/build/artifacts/artifact-manifest.json" in workflow
    assert 'ap.add_argument("--artifact-manifest"' in runner
    assert "--require-complete-coverage" in workflow
    assert 'ap.add_argument("--require-complete-coverage"' in runner
    assert "args.require_complete_coverage and bool(gaps)" in runner


def test_full_and_corpus_lanes_apply_context_migrations_in_order():
    workflow = (ROOT / ".github/workflows/lane-b-stats-e2e.yml").read_text()
    life = "/work/build/artifacts/sql/migrate_016_life_events.sql"
    clocks = "/work/build/artifacts/sql/migrate_017_capture_clocks_and_assists.sql"
    breaks = "/work/build/artifacts/sql/migrate_018_break_context_correlation.sql"
    correction = "/work/build/artifacts/sql/migrate_019_clear_uncertified_frag_context.sql"
    certification = "/work/build/artifacts/sql/migrate_020_frag_context_certified.sql"
    observability = "/work/build/artifacts/sql/migrate_021_capture_observability.sql"
    telemetry = "/work/build/artifacts/sql/migrate_022_objective_attempts_grenade_entities.sql"

    migrations = (
        life, clocks, breaks, correction, certification, observability, telemetry,
    )
    for migration in migrations[:-1]:
        assert workflow.count(migration) == 2
    # Migration 022 also appears once in the dedicated production-parity
    # migration self-test step; its final two uses are the full/corpus lists.
    assert workflow.count(telemetry) == 3

    def occurrences(value):
        indexes, offset = [], 0
        while (found := workflow.find(value, offset)) >= 0:
            indexes.append(found)
            offset = found + 1
        return indexes

    migration_indexes = {
        migration: occurrences(migration)[-2:] for migration in migrations
    }
    first = [migration_indexes[migration][0] for migration in migrations]
    second = [migration_indexes[migration][1] for migration in migrations]
    assert first == sorted(first)
    assert second == sorted(second)
    assert first[-1] < second[0]


def test_full_lane_carries_target_producer_clock_release_gates():
    runner = (ROOT / "scripts/lane_b_e2e.py").read_text()
    workflow = (ROOT / ".github/workflows/lane-b-stats-e2e.yml").read_text()

    assert "/work/config/analytics/accumulation_v6_schema22_2s.toml" in workflow
    assert "--report-profile /work/config/analytics/accumulation_v5_momentum.toml" not in workflow

    for emitted_key in (
        '"frag_context_match"', '"damage_match"', '"life_boundary_match"'
    ):
        assert emitted_key in runner
    for check in (
        "assertions.check_frag_producer_clocks(",
        "assertions.check_damage_producer_clocks(",
        "assertions.check_life_event_context(",
    ):
        assert check in runner
    assert "log_invariants.count_in_match" in runner
    assert "args.require_complete_coverage and bool(gaps)" in runner


def test_full_lane_strictly_accounts_for_breakdrive_frag_diagnostics():
    runner = (ROOT / "scripts/lane_b_e2e.py").read_text()
    invariants = (ROOT / "tests/e2e_stats/log_invariants.py").read_text()

    assert "frag_context_diagnostic_evidence(" in runner
    assert '"frag_context_diagnostics"' in runner
    assert "assertions.check_frag_context_diagnostics(" in runner
    assert runner.count("expected_unmatched=expected_frag_diagnostics") == 2
    assert "[KTPBreakDrive.amxx] [BD] kill flag=" in invariants
    assert "lines[start:stop]" in invariants
    assert "expected_identities" in runner
    assert "observed_identities" in runner


def test_match_epoch_interval_is_exactly_match_and_half_scoped():
    class FakeDb:
        def __init__(self):
            self.query = ""

        def sql(self, query):
            self.query = query
            return "start_epoch\tend_epoch\tactivation_epoch\n105\t120\t107\n"

    db = FakeDb()
    interval = match_epoch_interval(
        db, match_id="diagnostic-TEST", half=1
    )

    assert interval == {
        "start_epoch": 105, "end_epoch": 120, "activation_epoch": 107,
    }
    assert "BINARY 'diagnostic-TEST'" in db.query
    assert "half=1" in db.query
    assert "ktp_capture_manifests" in db.query


def test_full_lane_scopes_statsme_and_frag_markers_per_match():
    runner = (ROOT / "scripts/lane_b_e2e.py").read_text()

    assert "log_invariants.producer_marker_scopes(" in runner
    assert "log_invariants.objective_attempt_marker_scopes(" in runner
    assert "ignored_producer_markers=buffered_frag_markers" in runner
    assert '"objective_attempt_marker_scope"' in runner
    assert "log_invariants.count_in_match(" in runner
    assert "source_rows_by_context=statsme_source_rows" in runner
    assert "diagnostic_match_log" in runner
    assert "assertions.check_statsme_unattributed_replay(" in runner
    assert "log_invariants.count_after_match(" in runner


def test_build_refuses_partial_lane_b_core_support():
    script = (ROOT / "scripts/build_ktpamx_laneb.sh").read_text()

    assert "amxmodx/meta_api.cpp" in script
    assert "modules/dod/dodx/moduleconfig.cpp" in script
    assert "build produced no dodx_ktp_i386.so" in script
    assert "the lane would either run blind or emit no bot weaponstats" in script


def test_daemon_starts_only_after_hlds_is_rcon_ready():
    runner = (ROOT / "scripts/lane_b_e2e.py").read_text()

    ready = 'print(f"server up (attempt {attempt})", flush=True)'
    daemon_start = "daemon.start()"
    assert runner.count(daemon_start) == 1
    assert runner.index(ready) < runner.index(daemon_start)
    assert "failed-attempt rows can neither be ingested" in runner


def test_only_static_flag_positions_are_replayed_from_boot(tmp_path):
    log = tmp_path / "server.log"
    log.write_text(
        'L 01/01/2026 - 00:00:00: boot noise\n'
        'L 01/01/2026 - 00:00:01: KTP_FLAG_POSITION (flag_index "0")\n'
        'L 01/01/2026 - 00:00:02: "Bot<1><BOT><Allies>" killed "Other<2><BOT><Axis>"\n'
        'L 01/01/2026 - 00:00:03: KTP_FLAG_POSITION (flag_index "1")\n'
    )

    class FakeDaemon:
        def __init__(self):
            self.lines = []

        def feed_line(self, line):
            self.lines.append(line)

    daemon = FakeDaemon()
    assert replay_boot_flag_positions(daemon, log) == 2
    assert len(daemon.lines) == 2
    assert all("KTP_FLAG_POSITION " in line for line in daemon.lines)


def test_stage_tree_overlays_lane_b_dodx(tmp_path):
    hlds = tmp_path / "hlds"
    hlds.mkdir()
    (hlds / "hlds_linux").write_text("runner")

    config = tmp_path / "config"
    config.mkdir()
    (config / "plugins.ini").write_text("stats_logging.amxx\n")
    dod_configs = config / "dod-configs"
    dod_configs.mkdir()
    (dod_configs / "ktpbasic.cfg").write_text(
        "mp_clan_match 1\nmp_timelimit 20\n")
    (dod_configs / "ktp_anzio.cfg").write_text(
        "exec configs/ktpbasic.cfg\n")

    core = tmp_path / "ktpamx_i386.so"
    dodx = tmp_path / "dodx_ktp_i386.so"
    plugin = tmp_path / "stats_logging.amxx"
    server_cfg = tmp_path / "server.cfg"
    core.write_bytes(b"lane-b core")
    dodx.write_bytes(b"lane-b dodx")
    plugin.write_bytes(b"plugin")
    server_cfg.write_text("sv_lan 1\n")
    gamedata = tmp_path / "gamedata"
    for rel in (
        "common.games/master.games.txt",
        "common.games/functions.engine.txt",
        "common.games/globalvars.engine.txt",
        "common.games/gamerules.games/master.games.txt",
        "common.games/gamerules.games/dod/offsets-cdodteamplay.txt",
    ):
        path = gamedata / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((rel + "\n").encode())
    stale = hlds / "dod/addons/ktpamx/data/gamedata/stale.txt"
    stale.parent.mkdir(parents=True)
    stale.write_text("baked stale data")

    tree, _, provenance = stage_tree(
        hlds,
        ktpamx_so=core,
        dodx_so=dodx,
        amxx_gamedata=gamedata,
        plugin=plugin,
        config_dir=config,
        server_cfg_fixture=server_cfg,
    )

    staged = tree.path / "dod/addons/ktpamx/modules/dodx_ktp_i386.so"
    assert staged.read_bytes() == b"lane-b dodx"
    assert (tree.path / "dod/configs/ktpbasic.cfg").read_text() == (
        "mp_clan_match 1\nmp_timelimit 20\n")
    assert (tree.path / "dod/configs/ktp_anzio.cfg").read_text() == (
        "exec configs/ktpbasic.cfg\n")
    staged_gamedata = tree.path / "dod/addons/ktpamx/data/gamedata"
    assert not (staged_gamedata / "stale.txt").exists()
    assert (staged_gamedata / "common.games/globalvars.engine.txt").read_bytes() == (
        gamedata / "common.games/globalvars.engine.txt").read_bytes()
    assert provenance["tree_sha256"] == provenance["staged_tree_sha256"]
    assert provenance["file_count"] == 5


class _PreflightHandle:
    def __init__(self, output):
        self.output = output
        self.commands = []

    def rcon(self, command):
        self.commands.append(command)
        return self.output


def _preflight(tmp_path, output, *, log_extra="", crc_path="/opt/hlds/dod/dlls/dod.so"):
    log = tmp_path / "server.log"
    crc = (f"GameConfig CRC computed server=89ABCDEF ({crc_path})\n"
           if crc_path is not None else "")
    log.write_text(crc + log_extra)
    handle = _PreflightHandle(output)
    result = gamerules_clock_preflight(handle, log)
    assert handle.commands == ["ktp_bd_clock_preflight"]
    return result


def test_clock_preflight_accepts_exact_server_crc_and_live_clock(tmp_path):
    result = _preflight(
        tmp_path,
        "KTP_BD_CLOCK_PREFLIGHT gamerules=1 round=1195.25 limit=1200.00",
    )
    assert result["status"] == "ok"
    assert result["server_crc"][0]["path"].endswith("/dod/dlls/dod.so")


@pytest.mark.parametrize("output", [
    "KTP_BD_CLOCK_PREFLIGHT gamerules=0 round=-1.00 limit=1200.00",
    "KTP_BD_CLOCK_PREFLIGHT gamerules=1 round=-1.00 limit=1200.00",
    "KTP_BD_CLOCK_PREFLIGHT gamerules=1 round=nan limit=1200.00",
    "KTP_BD_CLOCK_PREFLIGHT gamerules=1 round=10.00 limit=0.00",
    "unrelated output",
    ("KTP_BD_CLOCK_PREFLIGHT gamerules=1 round=10.00 limit=1200.00 "
     "KTP_BD_CLOCK_PREFLIGHT gamerules=1 round=10.00 limit=1200.00"),
])
def test_clock_preflight_fails_closed_on_bad_or_ambiguous_marker(tmp_path, output):
    assert _preflight(tmp_path, output)["status"] == "pipeline"


def test_clock_preflight_rejects_warning_missing_crc_and_wrong_library(tmp_path):
    marker = "KTP_BD_CLOCK_PREFLIGHT gamerules=1 round=10.00 limit=1200.00"
    for message in (
        'Unable to prove declared mm_gamedll "dlls/dod.so"',
        'Unable to load library "server"',
        'GameConfig CRC mismatch for library "server"',
    ):
        warning = _preflight(tmp_path, marker, log_extra=message + "\n")
        assert warning["status"] == "pipeline"
        assert warning["resolver_warnings"]
    assert _preflight(tmp_path, marker, crc_path=None)["status"] == "pipeline"
    assert _preflight(
        tmp_path, marker, crc_path="/opt/hlds/metamod/metamod.so"
    )["status"] == "pipeline"


def test_clock_preflight_runs_after_config_settle_and_before_play_hooks():
    source = inspect.getsource(run_match)
    assert source.index("time.sleep(5.0)") < source.index("after_live()")
    assert source.index("after_live()") < source.index("before_play()")


def test_clock_preflight_parser_is_bound_to_pawn_producer_and_no_boot_retry():
    pawn = (ROOT / "tests/e2e_stats/diagnostics/KTPBreakDrive.sma").read_text()
    runner = (ROOT / "scripts/lane_b_e2e.py").read_text()
    assert 'register_srvcmd("ktp_bd_clock_preflight"' in pawn
    assert "dodx_has_gamerules()" in pawn
    assert "dodx_get_round_time()" in pawn
    assert 'server_print("KTP_BD_CLOCK_PREFLIGHT gamerules=%d round=%.2f limit=%.2f"' in pawn
    assert 'handle.rcon("ktp_bd_clock_preflight")' in runner
    assert "if server_started:\n                    run_error = e\n                    break" in runner


def test_strict_preflight_failure_is_persisted_before_exception_exit(tmp_path):
    report = {
        "map": "dod_anzio",
        "gamerules_clock_preflight": {
            "status": "pipeline", "detail": "gamerules unavailable",
            "server_crc": [],
        },
    }
    failures = []
    out = tmp_path / "lane-b.json"
    summary = tmp_path / "lane-b.md"
    persist_preflight_failure(
        report, failures, "strict preflight failed",
        out_path=out, summary_path=summary,
    )
    assert '"gamerules_clock_preflight"' in out.read_text()
    assert '"strict preflight failed"' in out.read_text()
    assert "GameRules / round-clock preflight" in summary.read_text()
    assert "FAIL" in summary.read_text()
