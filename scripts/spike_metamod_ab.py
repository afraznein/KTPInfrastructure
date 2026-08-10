#!/usr/bin/env python3
"""A/B differential: does adding Metamod + new_bot perturb the KTP stack?

This is the honest answer to "can we build a wall between ktpamx and Metamod".
No, we cannot — `ktpamx_i386.so` and `new_bot_mm.so` both export
`GiveFnptrsToDll` / `GetEntityAPI2` / `GetEngineFunctions` / `Meta_Attach`, so
they are the same kind of thing hooking the same tables in one address space.
Metamod is by design a chain where every plugin sees the same calls.

And a wall would be self-defeating anyway: the bots have to be visible to DODX
as real players, or every emit path in `ktp_stats_capture.inc` bails at
`is_user_connected()` and the lane captures nothing. The interaction is the
feature.

So this measures instead of assuming:

    Boot A — production topology: extensions.ini → ktpamx, gamedll = dod.so
    Boot B — bot topology:        metamod → {ktpamx, new_bot}, gamedll = metamod

and diffs the module set, the plugin set and their statuses. Empty diff means
non-interference on everything production depends on. A non-empty diff is the
interference, named and located — and is worth more than a bot run, because it
would be the thing that silently corrupts every later result.

Precedent for bothering: DODX forwards once stopped firing entirely under
KTPAMXX 2.7.12 and went unnoticed in production until someone looked by hand
(`DODX_FORWARD_FIRING_DESIGN.md`). Engine-layer interference here is
demonstrated, not hypothetical.

Usage (inside the Lane B image):

    python3 scripts/spike_metamod_ab.py --serverfiles /opt/hlds --in-place \\
        --bot new_bot --out /work/build/metamod-ab.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tests.e2e_stats import metamod  # noqa: E402
from tests.e2e_stats.bot_driver import SPECS  # noqa: E402
from tests.e2e_stats.ephemeral_tree import EphemeralTree  # noqa: E402
from tests.e2e_stats.fingerprint import capture, diff  # noqa: E402
from tests.smoke.boot_subprocess import booted_subprocess  # noqa: E402


def install_configs(tree, profile: Path) -> list[str]:
    """Copy a KTPAMXX config profile into the tree.

    The runtime base image ships NO `modules.ini` / `plugins.ini` — the
    production entrypoint copies them in from a mounted `/config`. Without them
    AMXX boots with zero modules and zero plugins, which fingerprints as an
    empty stack: the two topologies then compare *equal* and the differential
    reports non-interference having compared nothing at all.

    That is the failure mode this function exists to prevent, and it is why
    `fingerprint.diff()` also asserts the three production modules are present
    in absolute terms rather than only that A and B match.
    """
    dest = "dod/addons/ktpamx/configs"
    for required in ("modules.ini", "plugins.ini"):
        if not (profile / required).is_file():
            raise FileNotFoundError(f"config profile missing {required}: {profile}")

    # ALL of them, matching the production entrypoint's `for f in /config/*.ini`.
    # Copying only modules/plugins leaves ktp_cvar.amxx without ktp.ini and the
    # rest without theirs; the cvar checker then enforces its built-in
    # production defaults, which include Steam-authenticated play, and the boot
    # dies with "FATAL ERROR: Unable to initialize Steam" long after the point
    # where anyone would still suspect a missing config file.
    installed = []
    for src in sorted(profile.glob("*.ini")):
        tree.overlay_file(src, f"{dest}/{src.name}")
        installed.append(src.name)
    return installed


def boot_and_fingerprint(tree, *, label, map_name, extra_args, cfg_name,
                         boot_timeout, log_dir, port=None, attempts=3):
    """Boot, read the stack's self-report, tear down. Retries a Steam-init race.

    The **first** hlds boot in a fresh container reliably dies with

        [S_API FAIL] SteamAPI_Init() failed; SteamAPI_IsSteamRunning() failed.
        FATAL ERROR (shutting down): Unable to initialize Steam.        (SIGSEGV)

    while the second and third, with byte-identical arguments, come up fine and
    report "VAC secure mode disabled". Isolated by running the same command
    three times in one container: attempt 1 failed, 2 and 3 passed. It is not
    the arguments, not the port, not the plugin set, and not `sv_lan` — the cfg
    is not even read that early. Something the first attempt leaves behind
    (Steam client state under ~/.steam, the crash-dump path) lets later ones
    through.

    Retrying is the honest fix available at this layer, and it is bounded and
    logged rather than silent: a boot that needs all three attempts still says
    so in the report. Papering over it with a single retry-forever loop would
    hide a genuine regression, which in a nightly lane is worse than a flake.
    """
    log_file = Path(log_dir) / f"hlds-{label}.log"
    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with booted_subprocess(
                tree.path,
                map_name=map_name,
                port=port,
                maxplayers=14,
                rcon_password="smoketest",
                server_cfg=cfg_name,
                log_file=log_file,
                boot_timeout=boot_timeout,
                extra_args=extra_args,
            ) as handle:
                fp = capture(handle, label)
            return fp, log_file, attempt
        except Exception as e:  # noqa: BLE001 — retry the known race, then give up
            last = e
            print(f"    boot {label}: attempt {attempt}/{attempts} failed ({e}); "
                  "retrying" if attempt < attempts else "", flush=True)
    raise RuntimeError(
        f"{label} failed to boot after {attempts} attempts; see {log_file}"
    ) from last


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--serverfiles", type=Path, default=Path("/opt/hlds"))
    ap.add_argument("--in-place", action="store_true",
                    help="Write directly to --serverfiles (containerised lane only)")
    ap.add_argument("--bot", default="new_bot", choices=sorted(SPECS))
    ap.add_argument("--map", default="dod_anzio")
    ap.add_argument("--boot-timeout", type=float, default=180.0)
    # Fixed, low ports by default. hlds was observed failing Steam init on
    # randomised high ports while booting cleanly on 27015-range ones with
    # otherwise identical arguments.
    ap.add_argument("--port-a", type=int, default=27015)
    ap.add_argument("--port-b", type=int, default=27017)
    # `local` rather than `online`: it is the profile built for a
    # non-Steam-authenticated box (`sv_lan 1`, "no Steam auth" per
    # config/README.md) and it ships the full .ini set the plugins expect.
    # `online` enforces production cvars, which a container cannot satisfy.
    ap.add_argument("--config-profile", type=Path,
                    default=_REPO_ROOT / "config" / "local",
                    help="KTPAMXX config profile supplying modules.ini + plugins.ini + the rest")
    ap.add_argument("--split-layers", action="store_true",
                    help="Metamod hosts ONLY the bot; ktpamx keeps loading via "
                         "extensions.ini as production does. Each loads once, at "
                         "its own hook point.")
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()

    report: dict = {"steps": []}

    def step(name, ok, detail, **extra):
        report["steps"].append({"step": name, "ok": ok, "detail": detail, **extra})
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}", flush=True)

    rc = 0
    try:
        tree = (EphemeralTree.in_place(args.serverfiles) if args.in_place
                else EphemeralTree.build(args.serverfiles))

        installed = install_configs(tree, args.config_profile)
        step("configs", True,
             f"installed {installed} from {args.config_profile} — without these "
             "AMXX loads 0 modules/plugins and the diff compares two empty stacks",
             profile=str(args.config_profile))

        base_cfg = (_REPO_ROOT / "tests" / "smoke" / "fixtures" / "test_server.cfg").read_text()
        # sv_lan 1 lives in this cfg and is what keeps the engine from trying
        # (and failing) to reach Steam in a container. Booting with the
        # production dodserver.cfg instead ends in
        # "FATAL ERROR: Unable to initialize Steam".
        tree.write_text("dod/ab_server.cfg", base_cfg + "\nmp_timelimit 0\n")

        # Logs go beside --out, not into the tree: the containerised lane runs
        # in-place, so tree-local logs die with the container and a failed boot
        # leaves nothing to read.
        log_dir = args.out.parent if args.out else tree.path

        # ---- Boot A: production topology --------------------------------
        topo_a = metamod.restore_production(tree)
        step("topology-A", True,
             f"gamedll_linux={topo_a.gamedll_linux}, extensions.ini enabled",
             config=metamod.describe(tree))

        fp_a, log_a, tries_a = boot_and_fingerprint(
            tree, label="production", map_name=args.map,
            extra_args=[], cfg_name="ab_server.cfg",
            boot_timeout=args.boot_timeout, log_dir=log_dir, port=args.port_a)
        step("boot-A", not fp_a.failed,
             f"{len(fp_a.modules)} modules, {len(fp_a.plugins)} plugins"
             + (f" (boot took {tries_a} attempt(s))" if tries_a > 1 else "")
             + (f", FAILED: {fp_a.failed}" if fp_a.failed else ""),
             fingerprint=fp_a.to_dict(), boot_attempts=tries_a)

        # ---- Boot B: Metamod + bot --------------------------------------
        spec = SPECS[args.bot]
        topo_b = metamod.enable_metamod(tree, bot_spec=spec,
                                        host_ktpamx=not args.split_layers)
        step("topology-B", True,
             f"[{topo_b.name}] gamedll_linux={topo_b.gamedll_linux}, "
             f"plugins={topo_b.plugins}, extensions.ini "
             + ("ENABLED (ktpamx loads at its own layer)"
                if topo_b.extensions_enabled
                else "disabled (prevents ktpamx loading twice)"),
             config=metamod.describe(tree))

        fp_b, log_b, tries_b = boot_and_fingerprint(
            tree, label="metamod", map_name=args.map,
            extra_args=topo_b.extra_args, cfg_name="ab_server.cfg",
            boot_timeout=args.boot_timeout, log_dir=log_dir, port=args.port_b)
        step("boot-B", not fp_b.failed,
             f"{len(fp_b.modules)} modules, {len(fp_b.plugins)} plugins"
             + (f" (boot took {tries_b} attempt(s))" if tries_b > 1 else "")
             + (f", FAILED: {fp_b.failed}" if fp_b.failed else ""),
             fingerprint=fp_b.to_dict(), boot_attempts=tries_b)

        # ---- The actual question ----------------------------------------
        d = diff(fp_a, fp_b)
        report["diff"] = d
        if d["missing_required_modules"]:
            # Non-zero: an empty stack makes the non-interference check
            # vacuously true, so this must not exit 0 on the strength of it.
            rc = 1
            step("required-modules", False,
                 "; ".join(d["missing_required_modules"])
                 + " — the non-interference result below is VACUOUS")
        else:
            step("required-modules", True,
                 "amxxcurl + reapi + dodx present under BOTH topologies")

        if d["differences"]:
            step("non-interference", False,
                 f"{len(d['differences'])} difference(s): " + "; ".join(d["differences"][:6]))
            rc = 1
        else:
            step("non-interference", True,
                 "module and plugin sets/statuses identical across topologies")

        if d["extra_plugins_under_bot_topology"]:
            step("bot-plugin-visible", True,
                 f"extra under Metamod (expected): {d['extra_plugins_under_bot_topology']}")

        # Always restore, so a tree left behind is production-shaped.
        metamod.restore_production(tree)
        step("restored", True, "tree returned to production topology")

    except Exception as e:  # noqa: BLE001 — a spike reports rather than crashes
        step("spike", False, f"{type(e).__name__}: {e}")
        rc = 2

    text = json.dumps(report, indent=2, default=str)
    if args.out:
        args.out.write_text(text, encoding="utf-8")
        print(f"\nreport written to {args.out}")
    ok = sum(1 for s in report["steps"] if s["ok"])
    print(f"\n{ok}/{len(report['steps'])} steps ok, exit {rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
