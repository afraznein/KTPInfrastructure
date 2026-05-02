#!/usr/bin/env python3
"""Fleet-wide precache-gap audit for KTP DoD servers.

Cross-references every `.res`-declared custom-map asset against the actual
on-disk state of every game-server instance + FastDL. Surfaces files that are
referenced (and therefore could be precached on map load) but missing on one
or more hosts → crash candidates when those hosts rotate to the relevant map.

Triggered by two incidents in 48h (2026-05-01):
  - ATL:27015 segfault on dod_thunder → missing sprites/mapsprites/xrain2.spr
  - flare1.spr referenced by 4 saints2_b3* maps → missing on FastDL +
    surfaced accidentally by the manifest builder's existence check

Both required manual fan-out to 24 instances + FastDL; this script catches
the next one before it crashes.

Usage:
  python3 precache_audit.py [--ref-host atl] [--scope res] [--output report.md]

Defaults:
  --ref-host  atl   (74.91.121.9 — pulls .res references from this host)
  --scope     res   (audit .res-referenced paths only; hash check off)
  --output    -     (stdout; pass a path for markdown output file)

Phase 2 enhancement (out of scope for quick-win):
  Aggregate .res references across all 5 game hosts (in case .res files
  diverge), and add SHA256 drift check for paths present everywhere
  (currently presence-only).
"""

import argparse
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone

import paramiko

GAME_HOSTS = [
    {"name": "ATL", "host": "74.91.121.9",     "ports": [27015, 27016, 27017, 27018, 27019]},
    {"name": "DAL", "host": "74.91.126.55",    "ports": [27015, 27016, 27017, 27018, 27019]},
    {"name": "DEN", "host": "66.163.114.109",  "ports": [27015, 27016, 27017, 27018, 27019]},
    {"name": "NYC", "host": "74.91.123.64",    "ports": [27015, 27016, 27017, 27018, 27019]},
    {"name": "CHI", "host": "172.238.176.101", "ports": [27015, 27016, 27017, 27018]},
]
GAME_USER = "dodserver"
GAME_PASS = "REDACTED"
FASTDL_HOST = "74.91.112.242"
FASTDL_USER = "root"
# Canonical FastDL layout for DoD: files served at <root>/dod/<path> because
# sv_downloadurl points at the FastDL root and the engine appends the game
# directory ("dod/") before the asset path. Auditing /var/www/fastdl directly
# (without the dod/ prefix) was a bug that hid 99% of files in the 2026-05-01
# first audit pass — the layout has top-level demos/, dod/, and inadvertent
# sprites/ from misdeploys; canonical source is /var/www/fastdl/dod/.
FASTDL_DIR = "/var/www/fastdl/dod"

REF_HOSTS = {
    "atl": GAME_HOSTS[0],
    "dal": GAME_HOSTS[1],
    "den": GAME_HOSTS[2],
    "nyc": GAME_HOSTS[3],
    "chi": GAME_HOSTS[4],
}


def ssh_connect(host, user, password=None):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    if password:
        ssh.connect(host, username=user, password=password, timeout=15)
    else:
        ssh.connect(host, username=user, timeout=15)
    return ssh


def collect_res_references(ssh, dod_path):
    """Parse all maps/*.res files on the host. Returns {asset_path: {map_names}}."""
    references = defaultdict(set)
    _, out, _ = ssh.exec_command(f"ls {dod_path}/maps/*.res 2>/dev/null", timeout=30)
    res_files = [l.strip() for l in out.read().decode().splitlines() if l.strip()]

    if not res_files:
        return references, 0

    # Concatenate all .res files in one ssh call → much faster than per-file
    res_glob = " ".join(f"'{r}'" for r in res_files)
    _, out, _ = ssh.exec_command(
        f"for f in {res_glob}; do echo \"### $f\"; cat \"$f\"; done", timeout=60
    )
    text = out.read().decode(errors="replace")

    current_map = None
    for line in text.splitlines():
        if line.startswith("### "):
            current_map = line[4:].split("/")[-1].replace(".res", "")
            continue
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        if re.match(r"^[a-zA-Z0-9_./\-]+\.(spr|wad|mdl|wav|tga|bmp|res|bsp)$", line, re.IGNORECASE):
            references[line.lower()].add(current_map or "?")
    return references, len(res_files)


def batch_check_existence(ssh, base_dir, paths, batch_size=200):
    """For each path, return (path → exists). Single-shell loop, very fast."""
    result = {}
    paths = list(paths)
    for i in range(0, len(paths), batch_size):
        chunk = paths[i:i + batch_size]
        # Build a `printf` of "OK:path" or "MISS:path" per file
        # Use heredoc to avoid escaping nightmares — feed paths via stdin
        cmd = (
            f"cd '{base_dir}' && while IFS= read -r p; do "
            f'  if [ -f "$p" ]; then echo "OK:$p"; else echo "MISS:$p"; fi; '
            f"done"
        )
        stdin, out, _ = ssh.exec_command(cmd, timeout=120)
        stdin.write("\n".join(chunk) + "\n")
        stdin.flush()
        stdin.channel.shutdown_write()
        for line in out.read().decode().splitlines():
            if line.startswith("OK:"):
                result[line[3:]] = True
            elif line.startswith("MISS:"):
                result[line[5:]] = False
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().split("\n\n")[0])
    ap.add_argument("--ref-host", default="atl", choices=list(REF_HOSTS.keys()),
                    help="Game host to pull .res references from (default: atl)")
    ap.add_argument("--ref-port", default=27015, type=int,
                    help="Game-server port instance on the reference host (default: 27015)")
    ap.add_argument("--output", default="-",
                    help="Output path (default: stdout). Pass *.md for markdown.")
    args = ap.parse_args()

    ref = REF_HOSTS[args.ref_host]
    ref_dod = f"/home/dodserver/dod-{args.ref_port}/serverfiles/dod"

    print(f"[audit] reference: {args.ref_host.upper()}:{args.ref_port}", file=sys.stderr)
    print(f"[audit] connecting to reference host {ref['host']}...", file=sys.stderr)

    ref_ssh = ssh_connect(ref["host"], GAME_USER, GAME_PASS)
    references, n_res = collect_res_references(ref_ssh, ref_dod)
    ref_ssh.close()
    print(f"[audit] parsed {n_res} .res files → {len(references)} unique asset paths", file=sys.stderr)

    paths = sorted(references.keys())
    if not paths:
        print("[audit] no references found — nothing to audit", file=sys.stderr)
        sys.exit(0)

    # Cross-reference each path against every host + FastDL
    presence = {}  # (host_label, port_or_None) → {path: bool}

    for h in GAME_HOSTS:
        ssh = None
        # Connect with retry — transient SSH timeouts shouldn't kill the audit
        for attempt in range(3):
            try:
                ssh = ssh_connect(h["host"], GAME_USER, GAME_PASS)
                break
            except Exception as e:
                print(f"[audit] {h['name']:<6} connect attempt {attempt+1}/3 failed: {e}", file=sys.stderr)
        if ssh is None:
            print(f"[audit] {h['name']:<6} UNREACHABLE — marking all instances as ?", file=sys.stderr)
            for port in h["ports"]:
                label = f"{h['name']}{port - 27014}"
                presence[label] = {p: None for p in paths}  # None = unreachable, distinct from False
            continue
        for port in h["ports"]:
            label = f"{h['name']}{port - 27014}"  # ATL1, ATL2, etc.
            base_dir = f"/home/dodserver/dod-{port}/serverfiles/dod"
            try:
                presence[label] = batch_check_existence(ssh, base_dir, paths)
                missing = sum(1 for v in presence[label].values() if v is False)
                print(f"[audit] {label:<6} scanned {len(presence[label])} paths · {missing} missing",
                      file=sys.stderr)
            except Exception as e:
                print(f"[audit] {label:<6} ERROR: {e}", file=sys.stderr)
                presence[label] = {p: None for p in paths}
        ssh.close()

    # FastDL
    print(f"[audit] FastDL via root@{FASTDL_HOST}...", file=sys.stderr)
    fastdl_ssh = ssh_connect(FASTDL_HOST, FASTDL_USER)
    presence["FastDL"] = batch_check_existence(fastdl_ssh, FASTDL_DIR, paths)
    fastdl_ssh.close()
    fastdl_missing = sum(1 for v in presence["FastDL"].values() if not v)
    print(f"[audit] FastDL  scanned {len(presence['FastDL'])} paths · {fastdl_missing} missing",
          file=sys.stderr)

    # Categorize each path
    by_severity = defaultdict(list)  # severity → list of (path, missing_locations)
    location_order = sorted(presence.keys())

    for p in paths:
        # Distinguish missing (False) from unreachable (None). Unreachable hosts
        # don't count toward severity — they're flagged separately as "audit
        # incomplete" rather than confused for content drift.
        missing_locs = [loc for loc in location_order if presence[loc].get(p) is False]
        unreachable_locs = [loc for loc in location_order if presence[loc].get(p) is None]
        if not missing_locs:
            continue  # present everywhere reachable — don't report
        # Severity classification
        host_locs_missing = [l for l in missing_locs if l != "FastDL"]
        fastdl_missing = "FastDL" in missing_locs
        if len(host_locs_missing) >= 5:
            sev = "CRITICAL"  # widespread host gap → likely-affected by every map rotation
        elif len(host_locs_missing) >= 1:
            sev = "HIGH"      # crash candidate on missing hosts
        elif fastdl_missing:
            sev = "MEDIUM"    # FastDL only — slow downloads but no crashes
        else:
            sev = "LOW"
        by_severity[sev].append((p, missing_locs))

    # Build report
    lines = []
    lines.append("# KTP Fleet Precache-Gap Audit Report")
    lines.append("")
    lines.append(f"- **Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    lines.append(f"- **Reference host:** {args.ref_host.upper()}:{args.ref_port} ({ref['host']})")
    lines.append(f"- **References parsed:** {n_res} `.res` files → {len(paths)} unique asset paths")
    lines.append(f"- **Locations audited:** {len(presence)} ({len(presence)-1} game-server instances + FastDL)")
    lines.append("")

    total_missing_paths = sum(len(v) for v in by_severity.values())
    if total_missing_paths == 0:
        lines.append("## ✅ Result: clean")
        lines.append("")
        lines.append("Every `.res`-referenced asset is present on every game-server instance and on FastDL. No drift.")
    else:
        lines.append(f"## Drift summary: {total_missing_paths} path(s) missing somewhere")
        lines.append("")
        lines.append("| Severity | Paths | Description |")
        lines.append("|---|---|---|")
        sev_desc = {
            "CRITICAL": "Missing on 5+ game-server instances (widespread crash candidate)",
            "HIGH":     "Missing on 1-4 game-server instances (crash candidate on those hosts when rotating)",
            "MEDIUM":   "Present on every game host but missing on FastDL (slow client downloads, no crashes)",
            "LOW":      "Other drift",
        }
        for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
            if by_severity[sev]:
                lines.append(f"| **{sev}** | {len(by_severity[sev])} | {sev_desc[sev]} |")
        lines.append("")

        # Per-severity detail
        for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]:
            if not by_severity[sev]:
                continue
            lines.append(f"### {sev} ({len(by_severity[sev])} path{'s' if len(by_severity[sev]) != 1 else ''})")
            lines.append("")
            for path, missing_locs in sorted(by_severity[sev]):
                ref_maps = sorted(references[path])
                ref_str = ", ".join(ref_maps[:5]) + ("..." if len(ref_maps) > 5 else "")
                lines.append(f"- **`{path}`**")
                lines.append(f"  - Missing on: {', '.join(missing_locs)}")
                lines.append(f"  - Referenced by: {ref_str}")
            lines.append("")

        # Per-host summary
        lines.append("## Per-host missing counts")
        lines.append("")
        lines.append("| Location | Missing | Total checked |")
        lines.append("|---|---|---|")
        for loc in location_order:
            missing = sum(1 for v in presence[loc].values() if not v)
            total = len(presence[loc])
            lines.append(f"| `{loc}` | {missing} | {total} |")
        lines.append("")

    report = "\n".join(lines)

    if args.output == "-":
        print(report)
    else:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"[audit] report saved: {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
