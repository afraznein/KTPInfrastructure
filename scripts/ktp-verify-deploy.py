#!/usr/bin/env python3
"""KTP fleet deploy verification — Tier 2 first cut.

Catches the 2026-04-21 `.new`-swap-didn't-happen regression class plus its
neighbors:
  - .new files lingering after a nightly restart → swap script gap
  - Plugin/.so hash drift across instances → manual deploy that missed a host
  - Plugin/.so missing on a host → deploy never reached this region
  - Extra plugins/.so not in reference → stale leftover from old plugin

Reference-host design: ATL1:27015 is the canonical baseline. Whatever's
deployed there (sha256 of every .amxx + .so under addons/ktpamx/{plugins,dlls,
modules}) is compared against every other instance in the fleet. No external
baseline manifest to maintain — if ATL1 has a bug, the whole fleet flags
(self-correcting on the next correct deploy).

Aggregation aligned with ktp-soak-verify's Status enum:
  - GREEN: every host matches reference, zero .new files
  - YELLOW: extras on target, or per-instance reachability issues
  - RED: hash drift, missing-on-target, or .new files lingering

Output: JSON report to --out (or stdout if --out=-). When invoked from
ktp-soak-verify's `post-restart` suite, the JSON is parsed and rolled
into the suite's per-check rows.

Usage:
  ktp-verify-deploy [--reference <host>:<port>] [--out report.json]
                    [--scope plugins|dlls|modules|all]
                    [--include-engine]   (also check serverfiles/*.so engine + steam_api)

Defaults:
  --reference  74.91.121.9:27015 (ATL1)
  --out        -                  (stdout)
  --scope      all
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Optional

import paramiko


# ──────────────────────────────────────────────────────────────────────────
# Fleet topology — mirrors ktp-soak-verify and precache_audit.py
# ──────────────────────────────────────────────────────────────────────────

GAME_HOSTS = [
    {"name": "ATL", "host": "74.91.121.9",     "ports": [27015, 27016, 27017, 27018, 27019]},
    {"name": "DAL", "host": "74.91.126.55",    "ports": [27015, 27016, 27017, 27018, 27019]},
    {"name": "DEN", "host": "66.163.114.109",  "ports": [27015, 27016, 27017, 27018, 27019]},
    {"name": "NYC", "host": "74.91.123.64",    "ports": [27015, 27016, 27017, 27018, 27019]},
    {"name": "CHI", "host": "172.238.176.101", "ports": [27015, 27016, 27017, 27018]},
]
GAME_USER = "dodserver"
GAME_PASS = "REDACTED"

# What to walk under each instance's addons/ktpamx/. Glob patterns relative
# to the dod/ root. Engine check (serverfiles/*.so) is opt-in via --include-engine.
SCOPE_GLOBS = {
    "plugins": ["addons/ktpamx/plugins/*.amxx"],
    "dlls":    ["addons/ktpamx/dlls/*.so"],
    "modules": ["addons/ktpamx/modules/*.so"],
}
ENGINE_GLOBS = ["../engine_i486.so", "../hlds_linux", "../libsteam_api.so"]

# Paths intentionally NOT deployed to the full fleet. Missing-on-target for
# these is reported as INFO (informational, not drift). Maintain explicitly
# here — if you want a plugin to be considered "must-be-everywhere," remove
# it from this set.
KNOWN_PARTIAL_DEPLOYS: set[str] = {
    # Jimmy's external-contributor plugin. Released at his pace, deployed
    # only to a subset of instances (currently ATL1, DAL1, DEN5 per
    # 2026-05-02 verify-deploy first run). Not a deploy gap.
    "addons/ktpamx/plugins/KTPHudObserver.amxx",
}


# ──────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────

def ssh_connect(host: str, user: str = GAME_USER, password: Optional[str] = GAME_PASS,
                retries: int = 3) -> Optional[paramiko.SSHClient]:
    """Connect with retry. Returns None if all attempts fail."""
    for attempt in range(retries):
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            if password:
                ssh.connect(host, username=user, password=password, timeout=15)
            else:
                ssh.connect(host, username=user, timeout=15)
            return ssh
        except Exception as e:
            if attempt == retries - 1:
                print(f"[verify-deploy] {host} unreachable after {retries} attempts: {e}",
                      file=sys.stderr)
                return None
    return None


def collect_artifacts(ssh: paramiko.SSHClient, port: int, scope: str,
                      include_engine: bool) -> dict[str, str]:
    """Return {relative_path: sha256} for every artifact under the instance.

    Relative paths are normalized: addons/ktpamx/plugins/foo.amxx (for plugins),
    addons/ktpamx/dlls/foo.so (for dlls), engine/foo.so (for engine binaries).
    """
    base = f"/home/dodserver/dod-{port}/serverfiles/dod"
    globs: list[str] = []
    if scope in ("all", "plugins"):
        globs.extend(SCOPE_GLOBS["plugins"])
    if scope in ("all", "dlls"):
        globs.extend(SCOPE_GLOBS["dlls"])
    if scope in ("all", "modules"):
        globs.extend(SCOPE_GLOBS["modules"])
    if include_engine:
        globs.extend(ENGINE_GLOBS)

    results: dict[str, str] = {}
    # Single SSH command: hash every file matching the globs.
    glob_args = " ".join(f"{base}/{g}" for g in globs)
    # Use sh -c to expand globs even when they don't match (set -- with shopt)
    cmd = (
        f"shopt -s nullglob 2>/dev/null; "
        f"for f in {glob_args}; do "
        f'  if [ -f "$f" ]; then '
        f'    h=$(sha256sum "$f" 2>/dev/null | awk \'{{print $1}}\'); '
        f'    rel="${{f#{base}/}}"; '
        f'    [ "$rel" != "$f" ] && echo "${{h}}  ${{rel}}"; '
        f'  fi; '
        f"done"
    )
    _, out, _ = ssh.exec_command(cmd, timeout=60)
    for line in out.read().decode(errors="replace").splitlines():
        line = line.strip()
        if not line or "  " not in line:
            continue
        sha, path = line.split("  ", 1)
        if len(sha) == 64:
            results[path] = sha
    return results


def list_new_files(ssh: paramiko.SSHClient, port: int) -> list[str]:
    """List any *.new files lingering — these indicate a swap-script gap."""
    base = f"/home/dodserver/dod-{port}/serverfiles"
    cmd = (
        f"find {base}/dod/addons/ktpamx -name '*.new' 2>/dev/null; "
        f"find {base} -maxdepth 1 -name '*.new' 2>/dev/null"
    )
    _, out, _ = ssh.exec_command(cmd, timeout=20)
    paths = [l.strip() for l in out.read().decode().splitlines() if l.strip()]
    # Trim the prefix for readability.
    return [p.replace(base + "/", "") for p in paths]


# ──────────────────────────────────────────────────────────────────────────
# Verification
# ──────────────────────────────────────────────────────────────────────────

def verify_fleet(reference: str, scope: str, include_engine: bool) -> dict:
    """Build reference manifest from <ref_host>:<ref_port>, diff every other
    instance against it, return aggregated report."""
    ref_host, ref_port = reference.split(":")
    ref_port = int(ref_port)

    print(f"[verify-deploy] reference: {ref_host}:{ref_port}", file=sys.stderr)
    ssh = ssh_connect(ref_host)
    if ssh is None:
        return {"error": f"reference host {ref_host} unreachable"}
    ref_manifest = collect_artifacts(ssh, ref_port, scope, include_engine)
    ref_new = list_new_files(ssh, ref_port)
    ssh.close()

    print(f"[verify-deploy] reference manifest: {len(ref_manifest)} files",
          file=sys.stderr)
    if not ref_manifest:
        return {"error": f"reference {reference} returned empty manifest"}

    # Iterate every host × port (except the reference).
    instances: dict[str, dict] = {}
    ref_label = None
    for h in GAME_HOSTS:
        ssh = ssh_connect(h["host"])
        if ssh is None:
            for port in h["ports"]:
                label = f"{h['name']}{port - 27014}"
                instances[label] = {"status": "unreachable", "reason": "ssh failed"}
            continue
        for port in h["ports"]:
            label = f"{h['name']}{port - 27014}"
            is_ref = (h["host"] == ref_host and port == ref_port)
            if is_ref:
                ref_label = label

            try:
                manifest = collect_artifacts(ssh, port, scope, include_engine)
                new_files = list_new_files(ssh, port)
            except Exception as e:
                instances[label] = {"status": "error", "reason": str(e)}
                continue

            inst_data = {
                "status": "green",
                "files_count": len(manifest),
                "missing": [],         # in ref, not in target (RED)
                "missing_partial": [], # in ref, not in target, but on KNOWN_PARTIAL_DEPLOYS allowlist (INFO)
                "drift": [],           # in both, hash differs (RED)
                "extra": [],           # in target, not in ref (YELLOW)
                "new_files": new_files,
            }

            ref_paths = set(ref_manifest.keys())
            tgt_paths = set(manifest.keys())

            for p in sorted(ref_paths - tgt_paths):
                if p in KNOWN_PARTIAL_DEPLOYS:
                    inst_data["missing_partial"].append(p)
                else:
                    inst_data["missing"].append(p)
            for p in sorted(tgt_paths - ref_paths):
                inst_data["extra"].append(p)
            for p in sorted(ref_paths & tgt_paths):
                if ref_manifest[p] != manifest[p]:
                    inst_data["drift"].append({
                        "path": p,
                        "expected_sha": ref_manifest[p][:16],
                        "actual_sha": manifest[p][:16],
                    })

            # Status classification — KNOWN_PARTIAL_DEPLOYS missing doesn't
            # count toward drift severity (it's expected partial coverage).
            if new_files or inst_data["missing"] or inst_data["drift"]:
                inst_data["status"] = "red"
            elif inst_data["extra"]:
                inst_data["status"] = "yellow"
            else:
                inst_data["status"] = "green"
            # Reference instance is by definition "green" — it's the baseline.
            if is_ref:
                inst_data["status"] = "green"
                inst_data["is_reference"] = True
                # But record any .new files at the reference itself as RED:
                # the reference shouldn't have unswapped artifacts either.
                if new_files:
                    inst_data["status"] = "red"

            instances[label] = inst_data
        ssh.close()

    # Aggregate
    overall = "green"
    counts = defaultdict(int)
    for label, d in instances.items():
        s = d.get("status", "unknown")
        counts[s] += 1
        if s == "red":
            overall = "red"
        elif s == "yellow" and overall != "red":
            overall = "yellow"
        elif s in ("unreachable", "error") and overall == "green":
            overall = "yellow"

    return {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "reference": {
            "host": ref_host, "port": ref_port, "label": ref_label,
            "manifest_size": len(ref_manifest),
            "lingering_new_files": ref_new,
        },
        "scope": scope,
        "include_engine": include_engine,
        "overall": overall,
        "counts": dict(counts),
        "instances": instances,
    }


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--reference", default="74.91.121.9:27015",
                    help="<host>:<port> to use as the canonical baseline (default: ATL1)")
    ap.add_argument("--scope", choices=["plugins", "dlls", "modules", "all"], default="all")
    ap.add_argument("--include-engine", action="store_true",
                    help="Also verify engine_i486.so + hlds_linux + libsteam_api.so")
    ap.add_argument("--out", default="-",
                    help="Output JSON path (default: - = stdout)")
    args = ap.parse_args()

    report = verify_fleet(args.reference, args.scope, args.include_engine)

    out_text = json.dumps(report, indent=2)
    if args.out == "-":
        print(out_text)
    else:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out_text)
        print(f"[verify-deploy] report saved: {args.out}", file=sys.stderr)

    # Print a short human summary to stderr regardless
    overall = report.get("overall", "?").upper()
    counts = report.get("counts", {})
    print(f"\n[verify-deploy] overall={overall} {dict(counts)}", file=sys.stderr)
    if "error" in report:
        print(f"[verify-deploy] FATAL: {report['error']}", file=sys.stderr)
        return 2
    return 0 if overall == "GREEN" else 1


if __name__ == "__main__":
    sys.exit(main())
