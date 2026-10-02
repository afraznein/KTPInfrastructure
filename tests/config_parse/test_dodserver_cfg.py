"""dodserver.cfg — Source-engine cvar config. Catches missing critical cvars
and dangerous values (e.g. an empty rcon_password leaving production servers
exposed)."""

from __future__ import annotations

from pathlib import Path

import pytest

from .conftest import CONFIG_ROOT
from .parsers import parse_dodserver_cfg

# Online profile ships dodserver.cfg.example only — actual prod cfg is
# .gitignore'd because it carries the real rcon password. Test the example
# file as the prod-shape source of truth, and the local cfg as the dev-shape
# source of truth.
PROFILE_FILES: list[tuple[str, Path]] = [
    ("local", CONFIG_ROOT / "local" / "dodserver.cfg"),
    ("online_example", CONFIG_ROOT / "online" / "dodserver.cfg.example"),
]


@pytest.fixture(params=PROFILE_FILES, ids=[p[0] for p in PROFILE_FILES])
def cfg_path(request) -> Path:
    label, path = request.param
    if not path.exists():
        pytest.skip(f"{label}: {path} not present")
    return path


def test_dodserver_cfg_parses(cfg_path):
    cvars = parse_dodserver_cfg(cfg_path)
    assert cvars, f"{cfg_path} produced no cvar entries"


def test_required_cvars_present(cfg_path):
    """Critical cvars that production servers depend on. Missing any of
    these silently changes server behaviour. sv_lan is intentionally NOT in
    this set — online profile omits it (defaults to 0 = production); local
    profile sets it explicitly to 1. Tested separately per profile."""
    cvars = parse_dodserver_cfg(cfg_path)
    required = {"hostname", "rcon_password", "mp_timelimit", "sys_ticrate"}
    missing = required - set(cvars.keys())
    assert not missing, f"{cfg_path.name} missing required cvars: {sorted(missing)}"


def test_local_profile_has_lan_mode():
    cvars = parse_dodserver_cfg(CONFIG_ROOT / "local" / "dodserver.cfg")
    assert cvars["sv_lan"] == "1", (
        f"local/dodserver.cfg should set sv_lan 1 (Steam auth disabled for "
        f"local dev), got {cvars['sv_lan']!r}"
    )


def test_online_example_has_production_shape():
    """The online example file documents the prod cfg shape. It MUST set
    sv_lan 0 (production servers want Steam auth) and have a non-empty
    rcon_password placeholder so operators know to fill it in."""
    example = CONFIG_ROOT / "online" / "dodserver.cfg.example"
    if not example.exists():
        pytest.skip("online/dodserver.cfg.example not present")
    cvars = parse_dodserver_cfg(example)
    assert cvars.get("sv_lan") in {"0", None}, (
        f"online/dodserver.cfg.example: sv_lan should be 0 or unset for production, "
        f"got {cvars.get('sv_lan')!r}"
    )
    rcon = cvars.get("rcon_password", "")
    assert rcon, (
        "online/dodserver.cfg.example: rcon_password must be set "
        "(can be a placeholder like CHANGEME, but not empty)"
    )


def test_online_example_keeps_the_operator_tail():
    """Guards the settings that only ever existed on the live servers.

    On 2026-08-06 a `sed -i` was run against /home/dod/distribute/dodserver.cfg.
    That path is the KTPFileDistributor watch-dir ROOT and its WatchPatterns
    include *.cfg, so the edit fanned the file to all 25 instances
    ("Distribution complete: 25/25 servers") straight over each server's live
    config. The distributed copy had never carried the block below, so the whole
    fleet silently lost it — surfacing only at the 03:00 restart the next day,
    when the HUD went blind because its exec line was gone.

    These are cheap to lose and expensive to notice, so pin them here: this
    example file is the shape any distributed copy should be built from.

    Online profile only. The local profile sets dod_hud_url directly in
    dodserver.cfg instead of exec'ing a separate file.
    """
    example = CONFIG_ROOT / "online" / "dodserver.cfg.example"
    if not example.exists():
        pytest.skip("online/dodserver.cfg.example not present")

    cvars = parse_dodserver_cfg(example)
    # sv_allow_dlfile 0 prevents a 2+ second SERVER-WIDE freeze when a client
    # without the map joins; the profiling cvars are the fleet's frame-spike
    # telemetry. Values matter, not just presence.
    for cvar, expected in (
        ("sv_allow_dlfile", "0"),
        ("sv_send_logos", "1"),
        ("ktp_profile_frame", "1"),
    ):
        assert cvars.get(cvar) == expected, (
            f"online/dodserver.cfg.example: {cvar} should be {expected!r}, "
            f"got {cvars.get(cvar)!r} — see the 2026-08-06 distributor incident"
        )

    # Asserted on raw text, not the parsed dict: parse_dodserver_cfg collapses
    # every `exec` line onto one key, so a dict lookup would only ever see the
    # last one and would pass or fail depending on line order.
    hud_exec = "exec addons/ktpamx/configs/hud_observer.cfg"
    assert hud_exec in example.read_text(encoding="utf-8"), (
        f"online/dodserver.cfg.example: missing {hud_exec!r} — without it the "
        f"HUD plugin keeps its compiled-in localhost defaults and ingest goes dark"
    )


def test_online_example_keeps_the_anti_lockout_settings():
    """Pins the three cvars that make a ban BOUNDED rather than permanent.

    All three were live on 24/24 and absent from this example, so rebuilding a
    distributed config from this file would have silently reverted them to stock
    engine behaviour. That is not a no-op:

      * sv_rcon_banpenalty defaults to 0, and SV_AddIPFilterInternal treats 0 as
        PERMANENT (banEndTime 0 never expires). RH-02 made the engine's rcon
        auto-bans live in .930, and HLStatsX plus all 24 HLTV proxies share the
        data server's IP -- a banned IP cannot rcon in to lift its own ban.
      * the *_avg_punish cvars default to 5, i.e. a 5-minute IP ban. Negative
        means kick-only. Omitting them does not disable punishment, it re-enables
        banning -- which is the opposite of the stated policy two lines above them
        in the example ("Kick-only (-1) instead of ban").

    The example already pinned the *burst* variants and not the *avg* ones, so
    the policy was half-applied. Values matter here, not just presence.
    """
    example = CONFIG_ROOT / "online" / "dodserver.cfg.example"
    if not example.exists():
        pytest.skip("online/dodserver.cfg.example not present")

    cvars = parse_dodserver_cfg(example)
    for cvar, expected in (
        ("sv_rcon_banpenalty", "10"),
        ("sv_rehlds_movecmdrate_avg_punish", "-1"),
        ("sv_rehlds_stringcmdrate_avg_punish", "-1"),
        # the burst siblings, so the pair can never drift apart again
        ("sv_rehlds_movecmdrate_burst_punish", "-1"),
        ("sv_rehlds_stringcmdrate_burst_punish", "-1"),
    ):
        assert cvars.get(cvar) == expected, (
            f"online/dodserver.cfg.example: {cvar} should be {expected!r}, got "
            f"{cvars.get(cvar)!r} -- these bound a ban's duration; losing them "
            f"restores stock permanent/5-minute IP banning"
        )



# Where each profile's launch command line is declared. sys_ticrate is only
# right or wrong relative to these flags, so the test reads both.
INFRA_ROOT = CONFIG_ROOT.parent
TICRATE_PROFILES: list[tuple[str, Path, list[Path]]] = [
    # LinuxGSM instance cfgs written by the provisioner, and the cloning recipe.
    ("online_example", CONFIG_ROOT / "online" / "dodserver.cfg.example",
     [INFRA_ROOT / "provision" / "install-linuxgsm.sh", INFRA_ROOT / "docs" / "LINUXGSM.md"]),
    # lan-deploy.sh provisions its instances through the same install-linuxgsm.sh.
    ("lan_example", CONFIG_ROOT / "lan" / "dodserver.cfg.example",
     [INFRA_ROOT / "provision" / "install-linuxgsm.sh"]),
    # Stock-engine warmup server, installed by hand from its README.
    ("lan_warmup", CONFIG_ROOT / "lan" / "warmup" / "dodserver.cfg",
     [CONFIG_ROOT / "lan" / "warmup" / "README.md"]),
    # docker-compose.local.yml mounts config/local and boots runtime/entrypoint.sh.
    ("local", CONFIG_ROOT / "local" / "dodserver.cfg",
     [INFRA_ROOT / "runtime" / "entrypoint.sh"]),
]


def _launch_lines(path: Path) -> list[list[str]]:
    """Every hlds command line declared in `path`, as token lists. A command
    line is any logical line (backslash continuations joined) carrying
    `-game dod`."""
    text = path.read_text(encoding="utf-8").replace("\\\r\n", " ").replace("\\\n", " ")
    return [
        [tok.strip("`\"'") for tok in line.split()]
        for line in text.splitlines()
        if "-game dod" in line
    ]


@pytest.mark.parametrize(
    "label,cfg,sources", TICRATE_PROFILES, ids=[p[0] for p in TICRATE_PROFILES]
)
def test_sys_ticrate_matches_the_profiles_launch_flags(label, cfg, sources):
    """`-absgrid` (KTP engine, 1 ms frame grid) needs sys_ticrate 1500: at 1000
    the Host_FilterTime gate rejects ~31% of grid frames (~690 fps); at 1500
    they all pass (~1000 fps). Without `-absgrid` the gate is the limiter and
    1000 is the setting. Pinning one number for every profile got this wrong
    in both directions."""
    lines = [(src, toks) for src in sources for toks in _launch_lines(src)]
    if not lines:
        pytest.fail(
            f"{label}: no `-game dod` launch line found in "
            f"{[str(s.relative_to(INFRA_ROOT).as_posix()) for s in sources]} -- this profile's "
            f"launch flags cannot be determined from the repo, so its sys_ticrate "
            f"cannot be checked. Point TICRATE_PROFILES at where it is launched."
        )
    absgrid = {("-absgrid" in toks) for _, toks in lines}
    assert len(absgrid) == 1, (
        f"{label}: launch declarations disagree on -absgrid: "
        + "; ".join(f"{s.relative_to(INFRA_ROOT).as_posix()}: {'-absgrid' in t}" for s, t in lines)
    )
    want = "1500" if absgrid.pop() else "1000"
    got = parse_dodserver_cfg(cfg).get("sys_ticrate")
    assert got == want, (
        f"{label}: launched {'with' if want == '1500' else 'without'} -absgrid, so "
        f"{cfg.relative_to(INFRA_ROOT).as_posix()} needs sys_ticrate {want}, got {got!r}"
    )
