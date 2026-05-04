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
                    [--check-runtime]    (also rcon `amx_ktp_versions` on each instance —
                                          catches "right .amxx on disk, prior version
                                          still loaded because instance hasn't restarted")

Defaults:
  --reference     74.91.121.9:27015 (ATL1)
  --out           -                 (stdout)
  --scope         all
  --check-runtime off (extra UDP rcon traffic per instance)
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
from collections import defaultdict
from dataclasses import dataclass
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
RCON_PASS = "REDACTED_RCON"  # game-server rcon password — uniform fleet-wide per dodserver.cfg

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

# Same allowlist for runtime version checks — but keyed on PLUGIN_NAME (the
# string the plugin passes to KTP_RegisterVersion), not the .amxx filename.
# `KTP_RegisterVersion` emits the display name from the plugin's
# `PLUGIN_NAME` macro, which by convention has spaces (e.g. "KTP HUD Observer"
# vs file `KTPHudObserver.amxx`). Maintain in sync with KNOWN_PARTIAL_DEPLOYS.
KNOWN_PARTIAL_RUNTIME: set[str] = {
    "KTP HUD Observer",
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


# ──────────────────────────────────────────────────────────────────────────
# Minimal GoldSrc UDP rcon client (inlined from tests/smoke/rcon.py).
#
# Why inlined: ktp-verify-deploy is a single-file script deployed to
# /usr/local/bin on the data server. The smoke harness's rcon.py is in a
# pytest-discovered test directory not packaged for runtime use. Inlining
# the ~80 LoC we need (challenge → rcon-quoted-pw → A2A_PRINT drain) lets
# this script stay one-file-deployable without a sys.path detour or a
# parallel /usr/local/lib/ktp/ install. If the wire format changes, both
# places need updating — the canonical reference + protocol notes live in
# tests/smoke/rcon.py.
#
# Wire format (verified against KTPReHLDS rehlds/engine/sv_main.cpp):
#   Challenge request   client -> server   \xff\xff\xff\xffchallenge rcon\n\0
#   Challenge response  server -> client   \xff\xff\xff\xffchallenge rcon <num>\n\0
#   Rcon request        client -> server   \xff\xff\xff\xffrcon <num> "<pass>" <cmd>\n\0
#   Rcon response       server -> client   \xff\xff\xff\xffl<output>\0\0
# ──────────────────────────────────────────────────────────────────────────

_RCON_PREFIX = b"\xff\xff\xff\xff"
_RCON_A2A_PRINT = ord("l")


class RconError(Exception):
    pass


@dataclass
class _RconClient:
    host: str
    port: int
    password: str
    timeout: float = 2.0
    connect_timeout: float = 5.0
    drain_timeout: float = 0.4

    def execute(self, command: str) -> str:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.settimeout(self.connect_timeout)
            challenge = self._challenge(sock)
            sock.settimeout(self.timeout)
            quoted_pw = '"' + self.password.replace('"', '') + '"'
            line = f"rcon {challenge} {quoted_pw} {command}\n"
            sock.sendto(_RCON_PREFIX + line.encode("utf-8") + b"\x00", (self.host, self.port))
            return self._drain(sock)
        finally:
            sock.close()

    def _challenge(self, sock: socket.socket) -> str:
        sock.sendto(_RCON_PREFIX + b"challenge rcon\n\0", (self.host, self.port))
        data, _ = sock.recvfrom(4096)
        if not data.startswith(_RCON_PREFIX):
            raise RconError(f"challenge response missing prefix: {data!r}")
        body = data[len(_RCON_PREFIX):].rstrip(b"\x00\n").decode("utf-8", errors="replace")
        parts = body.split()
        if len(parts) < 3 or parts[0] != "challenge" or parts[1] != "rcon":
            raise RconError(f"unexpected challenge response: {body!r}")
        return parts[2]

    def _drain(self, sock: socket.socket) -> str:
        chunks: list[str] = []
        try:
            data, _ = sock.recvfrom(4096)
        except socket.timeout as exc:
            raise RconError("no rcon response within timeout") from exc
        chunks.append(self._unwrap(data))
        sock.settimeout(self.drain_timeout)
        while True:
            try:
                data, _ = sock.recvfrom(4096)
            except socket.timeout:
                break
            chunks.append(self._unwrap(data))
        return "".join(chunks)

    @staticmethod
    def _unwrap(packet: bytes) -> str:
        if not packet.startswith(_RCON_PREFIX):
            raise RconError(f"response missing prefix: {packet!r}")
        body = packet[len(_RCON_PREFIX):]
        if not body or body[0] != _RCON_A2A_PRINT:
            raise RconError(f"response missing A2A_PRINT 'l' byte: {packet!r}")
        return body[1:].rstrip(b"\x00").decode("utf-8", errors="replace")


def collect_runtime_versions(host: str, port: int, password: str = RCON_PASS,
                             timeout: float = 4.0) -> dict[str, dict[str, str]]:
    """Run `amx_ktp_versions` rcon, return {plugin_display_name: {version, sha, build_time}}.

    Output format from `ktp_version_reporter.inc:110-128` is fixed-column
    (`%-32s %-14s %-10s %s`) — but `%-Ns` minimum-pads not truncates, so the
    SHA column overflows when builds are `-dirty`. Plugin names contain spaces
    ("KTP Match Handler", "KTP HUD Observer"), so split-by-whitespace from
    the right works cleanest: the last 3 tokens are space-free (version, sha,
    build_time), everything before is the name.

    `timeout` bounds the RESPONSE-packet receive phase only (passed through
    to `_RconClient.timeout`). The challenge phase has its own internal
    `connect_timeout` (5.0s default in `_RconClient`) and the post-response
    drain has `drain_timeout` (0.4s default). Worst-case per-instance wall
    time is therefore `connect_timeout + timeout + drain_timeout` ≈ 9.4s
    when defaults are used and the host stalls. For 24 sequential instances
    this caps the run at ~3.75 minutes.

    Raises RconError on connectivity / protocol failure.
    """
    client = _RconClient(host=host, port=port, password=password, timeout=timeout)
    output = client.execute("amx_ktp_versions")
    return _parse_amx_ktp_versions(output)


def _parse_amx_ktp_versions(output: str) -> dict[str, dict[str, str]]:
    plugins: dict[str, dict[str, str]] = {}
    in_table = False
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # Separator line: `--------------------------------  ...` flips us
        # into in_table=True. Column-header line ("Name  Version  SHA  …")
        # appears BEFORE the separator, so the `if not in_table` guard below
        # already skips it — no explicit header-keyword check needed.
        # (Earlier draft had a header-keyword check; removed because a
        # future plugin display name happening to contain "Name", "Version",
        # AND "SHA" would have been silently dropped.)
        if stripped.startswith("---"):
            in_table = True
            continue
        # Footer: `Total: N KTP plugin(s) loaded`
        if stripped.startswith("Total:"):
            in_table = False
            continue
        if not in_table:
            continue
        # Plugin row — last 3 tokens are version, sha, build_time; rest is name.
        parts = stripped.rsplit(maxsplit=3)
        if len(parts) != 4:
            continue
        name, version, sha, build_time = parts
        plugins[name] = {"version": version, "sha": sha, "build_time": build_time}
    return plugins


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

def verify_fleet(reference: str, scope: str, include_engine: bool,
                 check_runtime: bool = False) -> dict:
    """Build reference manifest from <ref_host>:<ref_port>, diff every other
    instance against it, return aggregated report.

    `check_runtime=True` adds a per-instance `amx_ktp_versions` rcon query
    + drift check against the reference instance. This catches the failure
    mode where disk has the right .amxx but the running KTPAMXX has the
    PRIOR build still loaded (e.g., plugin .new staged but instance hasn't
    restarted since — disk-side check passes, runtime-side fails).
    """
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

    # Reference runtime versions — only fetched if --check-runtime. The rcon
    # query is independent of SSH, so we hit the reference's UDP port directly.
    ref_runtime: dict[str, dict[str, str]] = {}
    ref_runtime_error: Optional[str] = None
    if check_runtime:
        try:
            ref_runtime = collect_runtime_versions(ref_host, ref_port)
            print(f"[verify-deploy] reference runtime: {len(ref_runtime)} plugins via amx_ktp_versions",
                  file=sys.stderr)
        except Exception as e:
            ref_runtime_error = f"{type(e).__name__}: {e}"
            print(f"[verify-deploy] reference runtime FAILED: {ref_runtime_error}",
                  file=sys.stderr)

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

            # Per-instance runtime version check (opt-in via --check-runtime).
            # Only useful if reference's own runtime query succeeded.
            if check_runtime and ref_runtime:
                inst_data["runtime_drift"] = []          # version mismatch (RED)
                inst_data["runtime_missing"] = []        # in ref, not in target (RED — plugin failed to load)
                inst_data["runtime_missing_partial"] = []# in ref, not in target, allowlisted (INFO)
                inst_data["runtime_extra"] = []          # in target, not in ref (YELLOW)
                inst_data["runtime_count"] = 0
                inst_data["runtime_error"] = None

                # Reference compares against itself trivially (always empty
                # diffs). Reuse `ref_runtime` instead of issuing a duplicate
                # rcon query against the same host:port.
                tgt_runtime: Optional[dict[str, dict[str, str]]] = None
                if is_ref:
                    tgt_runtime = ref_runtime
                    inst_data["runtime_count"] = len(ref_runtime)
                else:
                    try:
                        tgt_runtime = collect_runtime_versions(h["host"], port)
                        inst_data["runtime_count"] = len(tgt_runtime)
                    except Exception as e:
                        inst_data["runtime_error"] = f"{type(e).__name__}: {e}"

                if tgt_runtime is not None:
                    ref_names = set(ref_runtime.keys())
                    tgt_names = set(tgt_runtime.keys())
                    for name in sorted(ref_names - tgt_names):
                        if name in KNOWN_PARTIAL_RUNTIME:
                            inst_data["runtime_missing_partial"].append(name)
                        else:
                            inst_data["runtime_missing"].append(name)
                    for name in sorted(tgt_names - ref_names):
                        inst_data["runtime_extra"].append(name)
                    for name in sorted(ref_names & tgt_names):
                        rv = ref_runtime[name]
                        tv = tgt_runtime[name]
                        if rv["version"] != tv["version"] or rv["sha"] != tv["sha"]:
                            inst_data["runtime_drift"].append({
                                "plugin": name,
                                "expected_version": rv["version"],
                                "actual_version": tv["version"],
                                "expected_sha": rv["sha"],
                                "actual_sha": tv["sha"],
                            })

            # Status classification — KNOWN_PARTIAL_DEPLOYS missing doesn't
            # count toward drift severity (it's expected partial coverage).
            # Runtime drift (version mismatch on a loaded plugin) is RED;
            # runtime_error is YELLOW (rcon may be transiently flaky).
            runtime_red = (
                check_runtime and ref_runtime and (
                    inst_data.get("runtime_drift") or inst_data.get("runtime_missing")
                )
            )
            runtime_yellow = (
                check_runtime and ref_runtime and (
                    inst_data.get("runtime_extra") or inst_data.get("runtime_error")
                )
            )

            if new_files or inst_data["missing"] or inst_data["drift"] or runtime_red:
                inst_data["status"] = "red"
            elif inst_data["extra"] or runtime_yellow:
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

    report = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "reference": {
            "host": ref_host, "port": ref_port, "label": ref_label,
            "manifest_size": len(ref_manifest),
            "lingering_new_files": ref_new,
        },
        "scope": scope,
        "include_engine": include_engine,
        "check_runtime": check_runtime,
        "overall": overall,
        "counts": dict(counts),
        "instances": instances,
    }
    if check_runtime:
        report["reference"]["runtime_plugins"] = sorted(ref_runtime.keys())
        report["reference"]["runtime_error"] = ref_runtime_error
    return report


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
    ap.add_argument("--check-runtime", action="store_true",
                    help="Also query `amx_ktp_versions` rcon on each instance and "
                         "diff loaded plugin versions against the reference. "
                         "Catches the disk-OK-but-not-yet-restarted-since-deploy gap.")
    ap.add_argument("--out", default="-",
                    help="Output JSON path (default: - = stdout)")
    args = ap.parse_args()

    report = verify_fleet(args.reference, args.scope, args.include_engine,
                          check_runtime=args.check_runtime)

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
