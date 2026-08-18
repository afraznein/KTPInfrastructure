from pathlib import Path

from scripts.lane_b_e2e import replay_boot_flag_positions, stage_tree


ROOT = Path(__file__).resolve().parents[2]


def test_full_lane_builds_test_core_from_preprod():
    workflow = (ROOT / ".github/workflows/lane-b-stats-e2e.yml").read_text()
    action = (ROOT / ".github/actions/build-ktpamx-laneb/action.yml").read_text()
    script = (ROOT / "scripts/build_ktpamx_laneb.sh").read_text()
    runner = (ROOT / "scripts/lane_b_e2e.py").read_text()

    assert "ref: feat/lane-b-fakeclient-players" not in workflow
    assert "          ref: preprod" in workflow
    assert '-v "${PWD}/.github:/work/.github:ro"' in workflow
    assert '-v "${PWD}/sql:/work/sql:ro"' in workflow
    assert "    default: preprod" in action
    assert 'REF="${LANEB_REF:-preprod}"' in script
    assert "dodx-so-path:" in action
    assert "--dodx-so /work/build/dodx_ktp_i386.so" in workflow
    assert 'tree.overlay_file(dodx_so, "dod/addons/ktpamx/modules/dodx_ktp_i386.so")' in runner


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
