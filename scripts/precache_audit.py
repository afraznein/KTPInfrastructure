#!/usr/bin/env python3
"""Fleet-wide precache-gap audit for KTP DoD servers.

Cross-references every map-declared asset reference against the actual
on-disk state of every game-server instance + FastDL. Surfaces files that
are referenced (and therefore could be precached on map load) but missing
on one or more hosts → crash candidates when those hosts rotate to the
relevant map.

Sources of references:
  1. `.res` files (Phase 1, 2026-05-02). Custom maps' explicit asset
     manifests. Caught the 2026-05-01 xrain2.spr crash on dod_thunder.
  2. BSP `entdata` lump (Phase 2, 2026-05-02). Stock DoD maps don't have
     `.res` files but DO embed precache references in entity definitions
     (env_sprite "model", ambient_generic "message", worldspawn "wad",
     etc.). Phase 1 alone would miss any future stock-map asset crash;
     Phase 2 generalizes the bug class.

Triggered by two incidents in 48h (2026-05-01):
  - ATL:27015 segfault on dod_thunder → missing sprites/mapsprites/xrain2.spr
  - flare1.spr referenced by 4 saints2_b3* maps → missing on FastDL +
    surfaced accidentally by the manifest builder's existence check

Both required manual fan-out to 24 instances + FastDL; this script catches
the next one before it crashes.

Usage:
  python3 precache_audit.py [--ref-host atl] [--scope all] [--output report.md]

Flags:
  --ref-host  atl              Game host to pull references from (default: atl)
  --scope     {res,bsp,all}    res/bsp/all sources (default: all)
  --output    -                stdout; pass *.md path for markdown file output

Phase 3 deferred — SHA256 drift detection (presence-only today). Add only if
a real drift incident shows up; deploys are pretty atomic via FTP fan-out.
"""

import argparse
import json
import os
import re
import sys
import urllib.request
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
GAME_PASS = "ktp"
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


# Phase 2 — BSP entity-lump parser. GoldSrc BSP version 30 layout:
#   header[0..4]  : int32 version (30 for HL1/DoD)
#   header[4..12] : lump 0 entry — int32 fileofs + int32 filelen (LUMP_ENTITIES)
#   ...           : 14 more lump entries we don't read here
# Entity lump is ASCII text; entity blocks are { "key" "value" ... }. Stock
# DoD maps emit their precache list as "model"/"noise"/"message"/"wad" KV
# values on entities like env_sprite, ambient_generic, worldspawn, etc.
#
# Server-side runner: Python one-liner that walks dod/maps/*.bsp, reads each
# BSP's lump 0 entry, dumps the entdata text with a "### MAPNAME" prefix.
# Faster than `dd bs=1 skip=...` + bash arithmetic by an order of magnitude
# on the typical 200-map fleet.

# Server-side BSP entity-lump dumper. Inlined as a string so it ships via
# ssh.exec_command in one shot. Reads each BSP's first 12 bytes (version +
# lump 0 entry), seeks to fileofs, reads filelen bytes, prints prefixed.
_BSP_DUMP_PY = r'''
import struct, sys, glob, os
sys.stdout.reconfigure(line_buffering=False)
# cwd is dod_path (already inside dod/). maps/*.bsp is relative to that.
for path in sorted(glob.glob("maps/*.bsp")):
    name = os.path.basename(path)[:-4]
    try:
        with open(path, "rb") as f:
            hdr = f.read(12)
            if len(hdr) < 12:
                continue
            version, ofs, length = struct.unpack("<iii", hdr)
            if version != 30 or length <= 0 or length > 8 * 1024 * 1024:
                # Not HL1 BSP, or implausibly large entdata — skip rather than
                # blow up the audit. Stock DoD entdata is typically 5-200 KB.
                continue
            f.seek(ofs)
            data = f.read(length)
        sys.stdout.buffer.write(("### " + name + "\n").encode())
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.write(b"\n")
    except Exception as ex:
        # Log per-map failures to stderr; main script aggregates. One bad
        # BSP shouldn't kill the audit for the other 200.
        sys.stderr.write("BSP_DUMP_ERROR " + name + ": " + str(ex) + "\n")
'''

# Entity KV regex. Matches `"key" "value"` even with escaped backslashes
# (rare in practice — only seen on Steam-imported maps). Block boundaries
# are tracked by a separate `{`/`}` walk so we don't have to handle nested
# quotes mid-value (HL1 maps don't produce them).
_BSP_KV_RE = re.compile(r'"([^"\\]+)"\s+"([^"\\]*)"')

# Asset-path-shape filter. Same extension set as the .res parser uses;
# adds explicit "/" requirement OR known extension so we drop bare strings
# like "lavafire" or "dod_anzio" that aren't precache references.
_BSP_ASSET_RE = re.compile(
    r'^[a-zA-Z0-9_./\-]+\.(spr|wad|mdl|wav|tga|bmp|res|bsp)$',
    re.IGNORECASE,
)

# Engine semantics for precache references in entdata:
#
# Models/sprites: path is relative to mod root.
#   "model" "sprites/lavafire.spr" → dod/sprites/lavafire.spr
#   "model" "models/mapmodels/foo.mdl" → dod/models/mapmodels/foo.mdl
#   "model" "*N" (brush model index) → not a file, skip
#
# Sounds: path is relative to dod/sound/ subdir. The engine implicitly
# prefixes "sound/" so a literal "ambience/aa3.wav" in entdata resolves
# to dod/sound/ambience/aa3.wav. This is the dominant fix from the first
# Phase 2 run — initial parser missed the prefix and reported every
# sound as "missing on every host."
#   "message" on ambient_generic / "noise[1-3]" on doors/buttons / "soundlist"
#
# `message` is multimodal: on ambient_generic it's a sound path, on every
# other classname it's a HUD text string. Audit only sounds.
#
# WAD files (worldspawn "wad"): semicolon-separated absolute Windows paths
# from the compiler-of-origin. Engine resolves by basename against mod
# search path. Audit only the basename.
#
# Skybox (worldspawn "skyname"): resolves to gfx/env/{name}{u,d,n,e,s,w}.tga.
# Six-suffix expansion has been a low-incidence bug class for us; skip
# for v1 to avoid noise.

# Keys that are model/sprite paths regardless of classname.
_BSP_MODEL_KEYS = frozenset({"model", "displaymodel", "weapon_model"})

# Keys that are sound paths regardless of classname.
_BSP_SOUND_KEYS = frozenset({"noise", "noise1", "noise2", "noise3", "soundlist"})

# Keys that are sound paths only on specific classnames.
_BSP_CLASSNAME_SOUND_KEYS = {
    "ambient_generic": frozenset({"message"}),
}

# Keys that are WAD-list manifests on worldspawn.
_BSP_WAD_KEYS_BY_CLASSNAME = {
    "worldspawn": frozenset({"wad"}),
}


def collect_bsp_references(ssh, dod_path):
    """Parse all maps/*.bsp entdata lumps. Returns {asset_path: {map_names}}.

    Entity precache references live in the BSP's LUMP_ENTITIES (lump 0) as
    ASCII text. Stock DoD maps have no .res files so this is the only audit
    surface for them. Custom maps usually have BOTH .res AND entity-lump
    refs; the references dict deduplicates so double-counting is harmless.
    """
    references = defaultdict(set)

    # Discover BSP files first so we can report a count even if extraction fails.
    _, out, _ = ssh.exec_command(f"ls {dod_path}/maps/*.bsp 2>/dev/null | wc -l", timeout=30)
    n_bsp = int(out.read().decode().strip() or "0")
    if n_bsp == 0:
        return references, 0

    # Run the inline Python dumper. cd into dod_path first so glob is relative.
    # Bypass quoting noise by feeding the script via stdin to `python3 -`.
    cmd = f"cd '{dod_path}' && python3 -"
    stdin, out, err = ssh.exec_command(cmd, timeout=600)
    stdin.write(_BSP_DUMP_PY)
    stdin.flush()
    stdin.channel.shutdown_write()

    # Read raw bytes (entdata is binary-clean ASCII but we don't want decode
    # to choke on a stray non-UTF-8 byte mid-entdata).
    blob = out.read().decode(errors="replace")
    err_text = err.read().decode(errors="replace")
    if err_text.strip():
        for line in err_text.splitlines():
            print(f"[audit:bsp] {line}", file=sys.stderr)

    # Parse: blocks are separated by "### MAPNAME" headers. Within each
    # block, walk the entity text and collect KV pairs.
    current_map = None
    current_block = []  # accumulated entity text for current_map

    def normalize_path(value):
        """Strip Windows backslashes / leading ./ / leading slashes."""
        return value.replace("\\", "/").lstrip("./").lstrip("/")

    def flush(map_name, text):
        if not map_name or not text:
            return
        # Walk the text in two phases:
        #   1. Bracket walk to delimit entity blocks (depth never > 1).
        #   2. Per block, collect ALL KV pairs into a dict, then dispatch
        #      based on classname (some keys are sound-vs-text dual-use).
        depth = 0
        block_kvs = {}

        def emit_block():
            if not block_kvs:
                return
            classname = block_kvs.get("classname", "").lower()
            for key, value in block_kvs.items():
                if not value:
                    continue
                key_lower = key.lower()
                # Models/sprites — path relative to mod root, no prefix.
                # `*N` brush-model indices skipped.
                if key_lower in _BSP_MODEL_KEYS:
                    if value.startswith("*"):
                        continue
                    normalized = normalize_path(value)
                    if _BSP_ASSET_RE.match(normalized):
                        references[normalized.lower()].add(map_name)
                    continue
                # Sounds — engine prefixes "sound/" before resolving against
                # mod root. Apply it here so the audit's File.Exists check
                # against dod/<path> hits the right location.
                if key_lower in _BSP_SOUND_KEYS or (
                    key_lower in _BSP_CLASSNAME_SOUND_KEYS.get(classname, frozenset())
                ):
                    normalized = normalize_path(value)
                    if not normalized:
                        continue
                    sound_path = "sound/" + normalized
                    if _BSP_ASSET_RE.match(sound_path):
                        references[sound_path.lower()].add(map_name)
                    continue
                # WAD list (worldspawn). Semicolon-separated absolute Windows
                # paths from the compiler. Engine resolves by basename
                # against mod search path; audit checks basename presence.
                if key_lower in _BSP_WAD_KEYS_BY_CLASSNAME.get(classname, frozenset()):
                    for entry in value.split(";"):
                        entry = entry.strip()
                        if not entry:
                            continue
                        basename = normalize_path(entry).rsplit("/", 1)[-1].lower()
                        if _BSP_ASSET_RE.match(basename):
                            references[basename].add(map_name)
                    continue

        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped == "{":
                depth += 1
                block_kvs = {}
                continue
            if stripped == "}":
                if depth == 1:
                    emit_block()
                    block_kvs = {}
                depth = max(0, depth - 1)
                continue
            if depth != 1:
                continue
            for key, value in _BSP_KV_RE.findall(stripped):
                # Last-write-wins on duplicate keys (HL1 entdata occasionally
                # emits "model" twice; first wins per engine semantics, but
                # the duplication is rare enough to not be worth tracking).
                if key not in block_kvs:
                    block_kvs[key] = value

    for line in blob.splitlines():
        if line.startswith("### "):
            if current_map and current_block:
                flush(current_map, "\n".join(current_block))
            current_map = line[4:].strip()
            current_block = []
        else:
            current_block.append(line)
    if current_map and current_block:
        flush(current_map, "\n".join(current_block))

    return references, n_bsp


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


# Cron-mode Discord helpers — same shape as ktp-soak-verify.py for consistency.
# Conf parser strips matching surrounding quotes (RELAY_URL="https://..." or
# RELAY_URL='https://...'). Without this, urllib treats `"https` as a literal
# URL scheme and fails.
def load_relay_conf(path: str = "/etc/ktp/discord-relay.conf") -> dict:
    conf = {}
    if not os.path.exists(path):
        return conf
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                v = v.strip()
                if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
                    v = v[1:-1]
                conf[k.strip()] = v
    return conf


def post_to_discord(embed: dict, channel_id: str, relay_url: str, auth_secret: str):
    """POST a Discord embed via the KTP relay. Relay expects camelCase
    `channelId`, NOT snake_case (memory `scheduled_report_channel.md`)."""
    payload = json.dumps({"channelId": channel_id, "embeds": [embed]}).encode("utf-8")
    req = urllib.request.Request(
        relay_url,
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json", "X-Relay-Auth": auth_secret},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return (200 <= resp.status < 300), resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def build_cron_embed(by_severity: dict, n_paths_total: int, n_locations: int, n_res: int, n_bsp: int) -> dict:
    """Render the audit summary as a Discord embed for the weekly cron.

    Posts only on actionable severity (any of CRITICAL/HIGH/MEDIUM/LOW).
    INFO bucket is skipped — those are stale entdata refs the engine
    tolerates, not drift signals.
    """
    severities_in_order = ["CRITICAL", "HIGH", "MEDIUM", "LOW"]
    counts = {s: len(by_severity.get(s, [])) for s in severities_in_order}
    actionable_total = sum(counts.values())

    if counts["CRITICAL"] > 0:
        color = 15548997  # red
        verdict = "FAIL"
    elif counts["HIGH"] > 0:
        color = 15548997  # red
        verdict = "FAIL"
    elif counts["MEDIUM"] > 0 or counts["LOW"] > 0:
        color = 15844367  # yellow
        verdict = "WARN"
    else:
        color = 5763719   # green (shouldn't happen — only called when actionable)
        verdict = "OK"

    fields = []
    for sev in severities_in_order:
        if counts[sev] == 0:
            continue
        # Show up to 8 paths per severity bucket — keep embed under Discord's
        # 1024-char/field cap. Operator can pull the full report.md from the
        # data server for the long tail.
        sample = by_severity.get(sev, [])[:8]
        lines = []
        for path, missing_locs in sample:
            host_locs = [l for l in missing_locs if l != "FastDL"]
            n_hosts = len(host_locs)
            fastdl = "FastDL" in missing_locs
            tag = f"{n_hosts} host{'s' if n_hosts != 1 else ''}"
            if fastdl:
                tag += " + FastDL"
            lines.append(f"`{path}` — missing on {tag}")
        more = counts[sev] - len(sample)
        if more > 0:
            lines.append(f"... and {more} more")
        fields.append({"name": f"{sev} ({counts[sev]})", "value": "\n".join(lines)[:1024], "inline": False})

    return {
        "title": f"KTP Precache Audit (weekly) — {verdict}",
        "description": (
            f"{actionable_total} actionable path{'s' if actionable_total != 1 else ''} missing.\n"
            f"References parsed: {n_res} `.res` files + {n_bsp} BSP entdata lumps "
            f"→ {n_paths_total} unique asset paths across {n_locations} locations."
        ),
        "color": color,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "footer": {"text": "precache_audit.py · CRITICAL/HIGH = crash candidate · MEDIUM/LOW = drift to investigate"},
        "fields": fields[:25],
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().split("\n\n")[0])
    ap.add_argument("--ref-host", default="atl", choices=list(REF_HOSTS.keys()),
                    help="Game host to pull references from (default: atl)")
    ap.add_argument("--ref-port", default=27015, type=int,
                    help="Game-server port instance on the reference host (default: 27015)")
    ap.add_argument("--scope", default="all", choices=["res", "bsp", "all"],
                    help="Reference source: .res files only / BSP entdata only / both (default: all)")
    ap.add_argument("--output", default="-",
                    help="Output path (default: stdout). Pass *.md for markdown.")
    ap.add_argument("--cron-mode", action="store_true",
                    help="When set, post Discord embed via /etc/ktp/discord-relay.conf if any "
                         "actionable severity (CRITICAL/HIGH/MEDIUM/LOW) found. Silent on green/INFO-only. "
                         "Used by /etc/cron.d/ktp-precache-audit-weekly.")
    ap.add_argument("--channel", default="1498813261263405097",
                    help="Discord channel ID for cron-mode posts (default: #ktp-updates per memory "
                         "scheduled_report_channel.md).")
    args = ap.parse_args()

    ref = REF_HOSTS[args.ref_host]
    ref_dod = f"/home/dodserver/dod-{args.ref_port}/serverfiles/dod"

    print(f"[audit] reference: {args.ref_host.upper()}:{args.ref_port}", file=sys.stderr)
    print(f"[audit] scope: {args.scope}", file=sys.stderr)
    print(f"[audit] connecting to reference host {ref['host']}...", file=sys.stderr)

    ref_ssh = ssh_connect(ref["host"], GAME_USER, GAME_PASS)
    references = defaultdict(set)
    n_res = 0
    n_bsp = 0

    if args.scope in ("res", "all"):
        res_refs, n_res = collect_res_references(ref_ssh, ref_dod)
        for path, maps in res_refs.items():
            references[path].update(maps)
        print(f"[audit] .res    parsed {n_res} files → {len(res_refs)} unique paths", file=sys.stderr)

    if args.scope in ("bsp", "all"):
        bsp_refs, n_bsp = collect_bsp_references(ref_ssh, ref_dod)
        for path, maps in bsp_refs.items():
            references[path].update(maps)
        print(f"[audit] BSP    parsed {n_bsp} entdata lumps → {len(bsp_refs)} unique paths", file=sys.stderr)

    ref_ssh.close()
    print(f"[audit] aggregated → {len(references)} unique asset paths", file=sys.stderr)

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

    # Categorize each path.
    by_severity = defaultdict(list)  # severity → list of (path, missing_locations)
    location_order = sorted(presence.keys())

    # Reference-host label, used to distinguish "drift" (missing on some hosts
    # only, REF host has it) from "stale entdata" (missing on REF too →
    # asset was never part of any deploy, BSP entity references a permanently-
    # missing file that the engine tolerates).
    ref_label = f"{args.ref_host.upper()}{args.ref_port - 27014}"
    n_game_hosts = len(presence) - 1  # exclude FastDL

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
        ref_missing = ref_label in host_locs_missing

        # Phase 2 refinement: an asset missing on the REF host AND every other
        # host (i.e. fleet-wide absent including the host we extracted the
        # reference from) is not "drift" — it's a stale entdata reference
        # the engine tolerates silently. Map has shipped this way forever;
        # an alert wakes nobody. Bucket as INFO so it's still visible in the
        # report (operator can audit), but it doesn't block the cron.
        # Limit to >= 80% to keep the bucket tight; partial gaps stay HIGH/CRITICAL.
        if ref_missing and len(host_locs_missing) >= int(0.8 * n_game_hosts):
            sev = "INFO"
        elif len(host_locs_missing) >= 5:
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
    lines.append(f"- **Scope:** {args.scope}")
    sources = []
    if args.scope in ("res", "all"):
        sources.append(f"{n_res} `.res` files")
    if args.scope in ("bsp", "all"):
        sources.append(f"{n_bsp} BSP entdata lumps")
    lines.append(f"- **References parsed:** {' + '.join(sources)} → {len(paths)} unique asset paths")
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
            "INFO":     "Reference host AND ≥80% of fleet missing — stale entdata reference the engine tolerates (no actionable drift, listed for visibility)",
        }
        for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]:
            if by_severity[sev]:
                lines.append(f"| **{sev}** | {len(by_severity[sev])} | {sev_desc[sev]} |")
        lines.append("")

        # Per-severity detail
        for sev in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]:
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

    # Cron-mode: post Discord embed only if there's an actionable severity.
    # INFO entries (stale entdata, engine-tolerated) and zero-drift cases
    # don't trigger a post. Wakes the operator only when there's drift to
    # investigate.
    if args.cron_mode:
        actionable = sum(len(by_severity.get(s, [])) for s in ("CRITICAL", "HIGH", "MEDIUM", "LOW"))
        if actionable == 0:
            print(f"[audit] cron-mode: 0 actionable paths (INFO={len(by_severity.get('INFO', []))}); silent — no Discord post",
                  file=sys.stderr)
            return
        conf = load_relay_conf()
        relay_url = conf.get("RELAY_URL", "")
        auth_secret = conf.get("AUTH_SECRET", "")
        if not relay_url or not auth_secret:
            print("[audit] cron-mode: /etc/ktp/discord-relay.conf missing RELAY_URL or AUTH_SECRET — skipping post",
                  file=sys.stderr)
            return
        embed = build_cron_embed(by_severity, len(paths), len(presence), n_res, n_bsp)
        ok, resp = post_to_discord(embed, args.channel, relay_url, auth_secret)
        if ok:
            print(f"[audit] cron-mode: posted to channel {args.channel}", file=sys.stderr)
        else:
            print(f"[audit] cron-mode: post FAILED: {resp}", file=sys.stderr)
            sys.exit(2)


if __name__ == "__main__":
    main()
