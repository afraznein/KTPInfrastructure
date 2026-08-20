from pathlib import Path

from scripts.lane_b_e2e import replay_boot_flag_positions, stage_tree


ROOT = Path(__file__).resolve().parents[2]


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


def test_full_and_corpus_lanes_apply_capture_clock_migration_after_life():
    workflow = (ROOT / ".github/workflows/lane-b-stats-e2e.yml").read_text()
    life = "/work/build/artifacts/sql/migrate_016_life_events.sql"
    clocks = "/work/build/artifacts/sql/migrate_017_capture_clocks_and_assists.sql"

    assert workflow.count(life) == 2
    assert workflow.count(clocks) == 2
    first_life = workflow.index(life)
    first_clocks = workflow.index(clocks)
    second_life = workflow.index(life, first_life + 1)
    second_clocks = workflow.index(clocks, first_clocks + 1)
    assert first_life < first_clocks < second_life < second_clocks


def test_full_lane_carries_target_producer_clock_release_gates():
    runner = (ROOT / "scripts/lane_b_e2e.py").read_text()

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

    core = tmp_path / "ktpamx_i386.so"
    dodx = tmp_path / "dodx_ktp_i386.so"
    plugin = tmp_path / "stats_logging.amxx"
    server_cfg = tmp_path / "server.cfg"
    core.write_bytes(b"lane-b core")
    dodx.write_bytes(b"lane-b dodx")
    plugin.write_bytes(b"plugin")
    server_cfg.write_text("sv_lan 1\n")

    tree, _ = stage_tree(
        hlds,
        ktpamx_so=core,
        dodx_so=dodx,
        plugin=plugin,
        config_dir=config,
        server_cfg_fixture=server_cfg,
    )

    staged = tree.path / "dod/addons/ktpamx/modules/dodx_ktp_i386.so"
    assert staged.read_bytes() == b"lane-b dodx"
