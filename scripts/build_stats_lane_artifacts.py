#!/usr/bin/env python3
"""Build the artifact set for a Lane B stats-capture run, from branch refs.

This is the build step of "test a branch before it reaches main". It takes refs
across the two repos that matter, extracts every artifact **from the commit**
(never from a working tree — "the tests passed" has to mean "passed against
this commit"), compiles the plugin, and writes a manifest of md5s so a later
result is traceable to exact bytes.

## Three ways to get the compiled plugin, in order of preference

1. `--amxxpc` + `--includes` — compile here. Needs the KTP fork's amxxpc and
   its `plugins/include`, not stock AMXX 1.10's: the production build compiles
   these stock plugins against the fork's includes, so upstream includes would
   produce a plugin nobody ships.
2. `--prebuilt-plugin` — adopt a `.amxx` built elsewhere (the Docker build, or
   a CI artifact from the GHCR base-image compile path). Recorded by md5 like
   anything else.
3. `--no-plugin` — collect only the daemon + SQL side. Useful because that half
   needs no toolchain at all, so the database lane can be exercised on any box.

The Tier 2 runner is Docker-free, so option 1 or 2 is what runs there; the
Docker plugin build stays on a Docker-capable machine or a GH-hosted runner.

## Examples

    # Full set, compiling locally
    python3 scripts/build_stats_lane_artifacts.py \\
        --amxx-repo ../branches/KTPAMXX      --amxx-ref feat/stats-positions \\
        --daemon-repo ../branches/KTPHLStatsX --daemon-ref feat/seed-cap-break-action \\
        --amxxpc ~/ktpamx/scripting/amxxpc \\
        --includes ../branches/KTPAMXX/plugins/include \\
        --out build/lane-b

    # Daemon + SQL only (no AMXX toolchain needed)
    python3 scripts/build_stats_lane_artifacts.py \\
        --amxx-repo ../branches/KTPAMXX      --amxx-ref feat/stats-positions \\
        --daemon-repo ../branches/KTPHLStatsX --daemon-ref feat/seed-cap-break-action \\
        --no-plugin --out build/lane-b
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tests.e2e_stats.artifacts import (  # noqa: E402
    ArtifactSet,
    BuildError,
    DEFAULT_SCHEMA_FILES,
)


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--amxx-repo", type=Path, required=True,
                    help="KTPAMXX checkout (any ref; read via git show)")
    ap.add_argument("--amxx-ref", required=True,
                    help="e.g. feat/stats-positions")
    ap.add_argument("--daemon-repo", type=Path, required=True,
                    help="KTPHLStatsX checkout")
    ap.add_argument("--daemon-ref", required=True,
                    help="e.g. feat/seed-cap-break-action")
    ap.add_argument("--out", type=Path, default=Path("build/lane-b"))

    grp = ap.add_mutually_exclusive_group()
    grp.add_argument("--amxxpc", type=Path, default=None,
                     help="Compile with this amxxpc (KTP fork's, not stock)")
    grp.add_argument("--prebuilt-plugin", type=Path, default=None,
                     help="Adopt an externally-built stats_logging.amxx")
    grp.add_argument("--no-plugin", action="store_true",
                     help="Collect daemon + SQL only; skip the plugin entirely")
    ap.add_argument("--includes", type=Path, default=None,
                    help="KTPAMXX plugins/include dir (required with --amxxpc)")
    ap.add_argument("--define", action="append", default=[],
                    help="Compile-time NAME=VALUE passed to amxxpc; repeatable")

    ap.add_argument("--schema", nargs="*", default=list(DEFAULT_SCHEMA_FILES),
                    help="Schema files, repo-relative, in apply order")
    ap.add_argument("--seed", nargs="*",
                    default=["sql/migrate_003_assist_action.sql",
                             "sql/migrate_004_cap_break_action.sql"],
                    help="Action seed files, repo-relative, in apply order")
    args = ap.parse_args()

    if args.amxxpc and not args.includes:
        ap.error("--amxxpc requires --includes (the KTP fork's plugins/include)")

    try:
        arts = ArtifactSet.collect(
            args.out,
            amxx_repo=args.amxx_repo, amxx_ref=args.amxx_ref,
            daemon_repo=args.daemon_repo, daemon_ref=args.daemon_ref,
            include_plugin=not args.no_plugin,
            schema_files=tuple(args.schema),
            seed_files=tuple(args.seed),
        )
        print(f"collected sources into {arts.build_dir}")
        for label, sha in (
            ("KTPAMXX", arts.provenance["amxx"]["sha"]),
            ("KTPHLStatsX", arts.provenance["daemon"]["sha"]),
        ):
            print(f"  {label:14} {sha[:12] if sha else 'not collected'}")

        if args.amxxpc:
            out = arts.compile_plugin(
                amxxpc=args.amxxpc, include_dir=args.includes,
                defines=tuple(args.define))
            warn = arts.provenance.get("build", {}).get("warnings", 0)
            print(f"compiled {out.name} ({warn} warning(s))")
        elif args.prebuilt_plugin:
            out = arts.use_prebuilt_plugin(args.prebuilt_plugin)
            print(f"adopted prebuilt {out.name}")
        else:
            print("plugin skipped (--no-plugin) — daemon + SQL only")

        manifest_path = arts.write_manifest()
        manifest = json.loads(manifest_path.read_text())
        print(f"\nmanifest: {manifest_path}")
        for name, meta in sorted(manifest["files"].items()):
            print(f"  {meta['md5']}  {meta['bytes']:>8}  {name}")

        if args.no_plugin or (not args.amxxpc and not args.prebuilt_plugin):
            print("\nNOTE: no plugin in this set — a Lane B run with it would "
                  "exercise the daemon and schema only, not the capture code.")
        return 0

    except BuildError as e:
        print(f"BUILD FAILED: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
