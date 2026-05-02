#!/usr/bin/env python3
"""Build the KTPAntiCheat game-files integrity manifest.

Generates /opt/ktp-ac-api/game_files_manifest.json on the data server (and
locally for review). The manifest defines which game files the AC client
should hash + verify against expected SHA256s during session collection.

Three sources combined:
  1. .res files on the source server (maps/*.res — custom community map assets)
  2. KTPFileChecker filelist.ini (base/stock game files: player models,
     grenade models, player sounds — assets NOT referenced by any .res because
     they ship with stock DoD)
  3. Explicit additions (user policy: standard US-vs-Wehrmacht weapon kit
     in p_/w_ variants + _l/l review-grade variants)

Excluded buckets (allowed modification): gfx/env/* (skybox), overviews/*,
flag models (w_aflag/gflag/wflag), snow footstep sounds.

Usage:
  python3 build-game-files-manifest.py [--source-server <host>] [--out <path>]

Defaults:
  --source-server  74.91.121.9 (ATL1 :27015)
  --out            ./game_files_manifest.json (relative to CWD)

Re-run after a known map deploy or weekly via cron. Manifest then SCP'd to
data server at /opt/ktp-ac-api/game_files_manifest.json; the API serves it
via /api/game-files-manifest with ETag-based caching.
"""

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import paramiko


# --------------------------------------------------------------------------
# Policy — edit here to change manifest scope
# --------------------------------------------------------------------------

EXCLUDED_PATH_PREFIXES = ("gfx/env/", "overviews/")
EXCLUDED_EXACT = {
    "models/w_aflag.mdl",
    "models/w_gflag.mdl",
    "models/w_wflag.mdl",
}
EXCLUDED_FILELIST_PATTERNS = [
    re.compile(r"^sound/player/pl_snow\d+\.wav$"),  # snow footsteps removed by user 2026-05-02
]

# Standard US-vs-Wehrmacht weapon kit. Each tuple: (family, p_base, w_base).
# Builder finds <base>.mdl, <base>_l.mdl, <base>l.mdl variants.
# `.mdl` extension implicit; suffixes for left/lowered variants are
# enforced as severity=review (see severity_semantics in manifest meta).
WEAPON_FAMILIES = [
    ("amerk_grenade",  "p_amerk",   "w_amerk"),
    ("bar",            "p_bar",     "w_bar"),
    ("colt",           "p_colt",    "w_colt"),
    ("garand",         "p_garand",  "w_garand"),
    ("k43",            "p_k43",     "w_k43"),
    ("luger",          "p_luger",   "w_luger"),
    ("m1carb",         "p_m1carb",  "w_m1carb"),
    ("mp40",           "p_mp40",    "w_mp40"),
    ("mp44",           "p_mp44",    "w_mp44"),
    ("k98_unscoped",   "p_k98",     "w_98k"),
    ("k98_scoped",     "p_k98s",    "w_scoped98k"),
    ("spade",          "p_spade",   "w_spade"),
    ("spring",         "p_spring",  "w_spring"),
    ("tommy",          "p_tommy",   "w_tommy"),
]

# Mixed-naming variants the regex doesn't catch (caught explicitly):
EXTRA_K98_VARIANTS = ["p_k98sl", "p_k98s_l"]


# --------------------------------------------------------------------------

def parse_res_files(ssh, dod_path):
    """Aggregate references from all maps/*.res files on the source server."""
    references = defaultdict(set)
    _, out, _ = ssh.exec_command(f"ls {dod_path}/maps/*.res 2>/dev/null", timeout=30)
    res_files = [l.strip() for l in out.read().decode().splitlines() if l.strip()]

    for res in res_files:
        map_name = res.split("/")[-1].replace(".res", "")
        _, out, _ = ssh.exec_command(f"cat '{res}'", timeout=30)
        for line in out.read().decode(errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            # .res entries are plain paths; one per line, lowercase typical
            if re.match(r"^[a-zA-Z0-9_./\-]+\.(spr|wad|mdl|wav|tga|bmp|res|bsp)$", line, re.IGNORECASE):
                references[line.lower()].add(map_name)
    return references, len(res_files)


def parse_filelist_ini(filelist_path):
    """Parse local KTPFileChecker filelist.ini. Drop excluded patterns."""
    paths = []
    with open(filelist_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            # `player/...` entries are sound paths (sound/ prefix implicit in HL)
            if line.startswith("player/"):
                line = "sound/" + line
            # Drop excluded patterns
            if any(p.match(line) for p in EXCLUDED_FILELIST_PATTERNS):
                continue
            paths.append(line)
    return paths


def hash_remote_file(ssh, full_path):
    """Returns (sha256, size) or None if file doesn't exist."""
    _, out, _ = ssh.exec_command(
        f"sha256sum '{full_path}' 2>/dev/null && stat -c '%s' '{full_path}' 2>/dev/null",
        timeout=15,
    )
    lines = out.read().decode().strip().splitlines()
    if len(lines) < 2 or " " not in lines[0]:
        return None
    return lines[0].split()[0], int(lines[1])


def categorize(path):
    """Map a relative path to its category bucket."""
    p = path.lower()
    if p.endswith(".wad"):
        return "wad"
    if p.startswith("models/player/"):
        return "player_model"
    if p.startswith("models/mapmodels/"):
        return "mapmodel"
    if p.startswith("sound/ambience/"):
        return "ambience_sound"
    if p.startswith("sound/player/"):
        return "player_sound"
    if p.startswith("sprites/mapsprites/"):
        return "mapsprite"
    if p.startswith("sprites/"):
        return "sprite"
    if p.startswith("models/"):
        leaf = p.split("/")[-1].replace(".mdl", "")
        if leaf.startswith("p_"):
            return "weapon_player_model"
        if leaf.startswith("w_"):
            return "weapon_world_model"
        if leaf in ("allied_ammo", "axis_ammo"):
            return "ammo_model"
        if leaf in ("hat_axis", "helmet_axis", "helmet_us"):
            return "equipment_model"
        if leaf == "player":
            return "player_model"
        return "model_other"
    return "other"


def is_l_variant(leaf):
    """True if leaf is a _l or l-suffixed lowered/lefty variant."""
    return leaf.endswith("_l") or (
        len(leaf) > 1 and leaf.endswith("l") and leaf[-2] != "_" and not leaf.endswith("ll")
    )


def build_manifest(ssh, dod_path, filelist_path):
    entries = []

    # 1. .res-derived files (custom-map assets)
    print(f"[build] Parsing .res files on {dod_path}...", file=sys.stderr)
    references, res_count = parse_res_files(ssh, dod_path)
    print(f"[build]   {res_count} .res files → {len(references)} unique referenced paths", file=sys.stderr)

    res_added = 0
    res_excluded = 0
    res_missing = []
    for path, ref_maps in sorted(references.items()):
        if any(path.startswith(p) for p in EXCLUDED_PATH_PREFIXES) or path in EXCLUDED_EXACT:
            res_excluded += 1
            continue
        result = hash_remote_file(ssh, f"{dod_path}/{path}")
        if result is None:
            res_missing.append(path)
            continue
        sha, size = result
        entries.append({
            "path": path,
            "sha256": sha,
            "size": size,
            "origin": ".res",
            "category": categorize(path),
            "severity": "violation",
            "referenced_by": sorted(ref_maps),
        })
        res_added += 1

    if res_missing:
        print(f"[build]   ⚠ {len(res_missing)} files referenced but missing on server: {res_missing}",
              file=sys.stderr)
    print(f"[build]   .res added: {res_added} (excluded: {res_excluded})", file=sys.stderr)

    # 2. filelist.ini-derived files (base/stock assets)
    print(f"[build] Parsing filelist.ini at {filelist_path}...", file=sys.stderr)
    filelist_paths = parse_filelist_ini(filelist_path)
    print(f"[build]   {len(filelist_paths)} unique paths after exclusions", file=sys.stderr)

    seen = {e["path"] for e in entries}
    fl_added = 0
    fl_dedup = 0
    for path in filelist_paths:
        if path in seen:
            fl_dedup += 1
            continue
        result = hash_remote_file(ssh, f"{dod_path}/{path}")
        if result is None:
            continue
        sha, size = result
        cat = categorize(path)
        # Override for grenade models from filelist (catches p_grenade/p_mills/etc.)
        leaf = path.split("/")[-1].replace(".mdl", "")
        if leaf in ("p_grenade", "p_mills", "p_stick", "w_grenade", "w_mills", "w_stick"):
            cat = "grenade_model"
        entries.append({
            "path": path,
            "sha256": sha,
            "size": size,
            "origin": "filelist.ini",
            "category": cat,
            "severity": "violation",
        })
        seen.add(path)
        fl_added += 1
    print(f"[build]   filelist.ini added: {fl_added} (dedup'd against .res: {fl_dedup})", file=sys.stderr)

    # 3. Explicit additions: equipment models + ammo + player.mdl
    explicit_singletons = [
        "models/allied_ammo.mdl", "models/axis_ammo.mdl",
        "models/hat_axis.mdl", "models/helmet_axis.mdl", "models/helmet_us.mdl",
        "models/player.mdl",
    ]
    print(f"[build] Explicit equipment/ammo/player.mdl additions...", file=sys.stderr)
    for path in explicit_singletons:
        if path in seen:
            continue
        result = hash_remote_file(ssh, f"{dod_path}/{path}")
        if result is None:
            print(f"[build]   ⚠ {path} not found on server", file=sys.stderr)
            continue
        sha, size = result
        entries.append({
            "path": path, "sha256": sha, "size": size,
            "origin": "explicit_2026-05-01",
            "category": categorize(path),
            "severity": "violation",
        })
        seen.add(path)

    # 4. Weapon kit families — find .mdl + _l.mdl + l.mdl variants
    print(f"[build] Weapon-kit families ({len(WEAPON_FAMILIES)})...", file=sys.stderr)
    # Drop any prior weapon model entries from the .res / filelist sources so
    # the explicit weapon-kit pass owns the per-family categorization (severity,
    # weapon_family, variant fields).
    entries = [e for e in entries
               if e.get("category") not in ("weapon_player_model", "weapon_world_model")]
    seen = {e["path"] for e in entries}

    weapon_added = 0
    for family, p_base, w_base in WEAPON_FAMILIES:
        for base in (p_base, w_base):
            for variant_leaf in (base, base + "_l", base + "l"):
                rel = f"models/{variant_leaf}.mdl"
                if rel in seen:
                    continue
                result = hash_remote_file(ssh, f"{dod_path}/{rel}")
                if result is None:
                    continue
                sha, size = result
                is_review = is_l_variant(variant_leaf) and variant_leaf != base
                entries.append({
                    "path": rel, "sha256": sha, "size": size,
                    "origin": "explicit_2026-05-02_full_kit",
                    "category": "weapon_player_model" if variant_leaf.startswith("p_") else "weapon_world_model",
                    "severity": "review" if is_review else "violation",
                    "weapon_family": family,
                    "variant": "lowered_or_lefthand" if is_review else "primary",
                })
                seen.add(rel)
                weapon_added += 1

    # Mixed-naming k98 left-hand variants
    for leaf in EXTRA_K98_VARIANTS:
        rel = f"models/{leaf}.mdl"
        if rel in seen:
            continue
        result = hash_remote_file(ssh, f"{dod_path}/{rel}")
        if result is None:
            continue
        sha, size = result
        entries.append({
            "path": rel, "sha256": sha, "size": size,
            "origin": "explicit_2026-05-02_full_kit",
            "category": "weapon_player_model",
            "severity": "review",
            "weapon_family": "k98_scoped",
            "variant": "lowered_or_lefthand",
        })
        seen.add(rel)
        weapon_added += 1

    print(f"[build]   weapon-kit added: {weapon_added}", file=sys.stderr)

    return entries


def assemble_manifest(entries, source_server_label, dod_path):
    entries.sort(key=lambda e: (e["category"], e.get("severity", "violation"), e["path"]))

    cat_counts = Counter(e["category"] for e in entries)
    sev_counts = Counter(e["severity"] for e in entries)
    src_counts = Counter(e.get("origin", "?") for e in entries)
    total_size = sum(e["size"] for e in entries)

    version = hashlib.sha256(
        json.dumps([(e["path"], e["sha256"]) for e in entries], sort_keys=True).encode()
    ).hexdigest()[:16]

    return {
        "_meta": {
            "version": version,
            "source_server": source_server_label,
            "source_path": dod_path,
            "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "total_files": len(entries),
            "total_size_bytes": total_size,
            "by_category": dict(cat_counts),
            "by_severity": dict(sev_counts),
            "sources": dict(src_counts),
            "severity_semantics": {
                "violation": "Mismatch is a hard violation. Reported in dossier and counts toward verdict.",
                "review": "Mismatch surfaces in dossier as 'admin review' item, NOT a violation. Player's local file copied into session bundle's review_files/ subdirectory for admin inspection. Use case: lowered-carry / left-handed variants where the model legitimately differs across map states or community packs.",
            },
            "scope_notes": [
                "Standard US-vs-Wehrmacht 6v6 weapon kit. British/commonwealth and paratrooper-class weapons NOT enforced.",
                "v_*.mdl (first-person view models) intentionally NOT enforced.",
                "_l / l-suffix variants enforced as severity=review (lowered-carry / left-handed pose models).",
            ],
            "excluded_buckets": [
                "gfx/env/* (skybox — cosmetic, allowed)",
                "models/{w_aflag,w_gflag,w_wflag}.mdl (flag — cosmetic, allowed)",
                "overviews/* (top-down map BMPs — cosmetic, allowed)",
                "sound/player/pl_snow*.wav (snow footsteps — removed 2026-05-02)",
            ],
        },
        "files": entries,
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().split("\n\n")[0])
    ap.add_argument("--source-server", default="74.91.121.9",
                    help="Game-server SSH host (default: 74.91.121.9 = ATL1)")
    ap.add_argument("--source-user", default="dodserver")
    ap.add_argument("--source-port-dir",
                    default="/home/dodserver/dod-27015/serverfiles/dod",
                    help="dod/ directory on the source server")
    ap.add_argument("--filelist",
                    default=str(Path(__file__).resolve().parent.parent.parent /
                                "KTP DoD Server" / "serverfiles" / "dod" /
                                "addons" / "ktpamx" / "configs" / "filelist.ini"),
                    help="Local path to KTPFileChecker filelist.ini")
    ap.add_argument("--out", default="game_files_manifest.json",
                    help="Output JSON path (default: ./game_files_manifest.json)")
    ap.add_argument("--ssh-password", default="ktp",
                    help="SSH password for source-user (default: ktp)")
    args = ap.parse_args()

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(args.source_server, username=args.source_user, password=args.ssh_password)

    try:
        entries = build_manifest(ssh, args.source_port_dir, args.filelist)
        manifest = assemble_manifest(entries, f"{args.source_server} {args.source_port_dir}",
                                      args.source_port_dir)

        out_path = Path(args.out).resolve()
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        meta = manifest["_meta"]
        print(f"\n=== Manifest built ===", file=sys.stderr)
        print(f"  version:   {meta['version']}", file=sys.stderr)
        print(f"  total:     {meta['total_files']} files ({meta['total_size_bytes']/1024/1024:.1f} MB)",
              file=sys.stderr)
        print(f"  severity:  {meta['by_severity']}", file=sys.stderr)
        print(f"  category:  {meta['by_category']}", file=sys.stderr)
        print(f"  sources:   {meta['sources']}", file=sys.stderr)
        print(f"  output:    {out_path}", file=sys.stderr)
    finally:
        ssh.close()


if __name__ == "__main__":
    main()
