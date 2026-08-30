#!/usr/bin/env python3
"""Build the KTPAntiCheat game-files integrity manifest.

Generates /opt/ktp-ac-api/game_files_manifest.json on the data server (and
locally for review). The manifest defines which game files the AC client
should hash + verify against expected SHA256s during session collection.

Three sources combined:
  1. .res files on the source server (maps/*.res — custom community map assets)
  2. KTPFileChecker ktp_file.ini (the engine consistency-check list the plugin
     actually loads: player models, player sounds — assets NOT referenced by
     any .res because they ship with stock DoD)
  3. Explicit additions (user policy: standard US-vs-Wehrmacht weapon kit
     in p_/w_ primary variants + grenade viewmodels; _l/l pose variants
     pruned 2026-05-13)

Excluded buckets (allowed modification): overviews/*, flag models
(w_aflag/gflag/wflag).

Skyboxes (gfx/env/*) were an excluded bucket until 2026-08-27. They are now IN
scope at severity "review" -- an operator POLICY REVERSAL, not a bug fix. A
skybox mismatch is reported and its bytes captured for an admin, but it does not
count toward a verdict. Reverting = move "gfx/env/" back to
EXCLUDED_PATH_PREFIXES.

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
import os
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import paramiko


# --------------------------------------------------------------------------
# Policy — edit here to change manifest scope
# --------------------------------------------------------------------------

EXCLUDED_PATH_PREFIXES = ("overviews/",)

# Report-only scope. In the manifest, captured and shown to an admin, but the
# client's IsReview branch keeps it out of modified_game_files -- so it never
# flags a player. gfx/env/ added 2026-08-27 (skyboxes, previously excluded).
REVIEW_PATH_PREFIXES = ("gfx/env/",)
EXCLUDED_EXACT = {
    "models/w_aflag.mdl",
    "models/w_gflag.mdl",
    "models/w_wflag.mdl",
}
# (pl_snow* exclusion removed 2026-07-07 — snow footsteps are back in
# ktp_file.ini enforcement, so the manifest must cover them again.)
EXCLUDED_FILELIST_PATTERNS = []

# Operator-curated alternate hashes — files where a community-distributed
# replacement is present on most player installs and should be accepted
# alongside the canonical Valve hash. AC client (0.5.2+) consults this list
# when comparing; mismatches that match an alternate are treated as clean.
#
# 2026-05-25: KTP league score-event ambient sound pack. Same `actual` hashes
# observed across operator's own machine + every player bundle in the corpus
# (Las1K64, arachnid, nein test bundles), confirming a community-standard
# replacement set predating AC. Without alternates these surface as 4
# false-positive violations on every legitimate player.
ALTERNATE_HASHES = {
    "sound/ambience/alliescap.wav": [
        "6a97244af9824daa97333986f2ed8db91f52c7203dd2b2db5aedef2943b79786",
    ],
    "sound/ambience/alliesscore.wav": [
        "1e465577efd267041e6db5a302e43b5fdb506e4d0d67b569bbfc28547c96a41e",
    ],
    "sound/ambience/axiscap.wav": [
        "071a41cc5f3886669ca05962f91bf127acd09d88300ce083ea9c86913a6d78a9",
    ],
    "sound/ambience/axisscore.wav": [
        "e775a4d4623b018da969d29148764b0c82be2c27d0a57e8640c86a85ee20cbe3",
        # Second score-jingle pack on the same path (jarrod / twist / 7735372).
        # Distinct hash, same file, both community content.
        "3f85263a0c68b3f2bdccb3bfe3ec4663c615b87370664a5b55454d9e0f35a1a3",
    ],
    # 2026-07-26: these three were in the AC client's KnownBenignFileVariants but NOT
    # here, and the two viewmodels only came into manifest scope on 2026-07-07. The
    # manifest gate runs FIRST, so without them every bundle carrying these files
    # recorded a Violation that scoring then quietly rescued — the verdict read clean
    # while the evidence file said the player was modified. Corpus prevalence:
    # v_grenade 19 bundles, v_stick 19, dod_siena.wad 24.
    #
    # KEEP IN SYNC with SummaryGenerator.KnownBenignFileVariants. The AC repo has a
    # trait-gated guard (BenignVariantManifestSyncTests) that fails naming any entry
    # present in one and missing from the other.
    "models/v_grenade.mdl": [
        "bb8ac11263e3a9b70e342cf9210c6e2fbd36c071b2ffb985479186f28e122634",
    ],
    "models/v_stick.mdl": [
        "e70850d6e491793e7c89c315dc97d9d4155cf04949ddfa9beae180a3996cd956",
    ],
    "dod_siena.wad": [
        "249f620741e27edcb84df33510b794798d972d81acd197b6eaa4db1aafb0c60f",
    ],
}

# Standard US-vs-Wehrmacht weapon kit. Each tuple: (family, p_base, w_base).
# `.mdl` extension implicit. Primary variants only: the _l/l lowered/left-hand
# pose variants were PRUNED 2026-05-13 (operator call — not stock DoD, likely
# community-mod files; they put MissingFiles noise in every clean-install
# session without contributing verdict weight). Do not re-add without confirming
# they are stock DoD files.
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

# Grenade first-person viewmodels — the one v_* exception to the "viewmodels
# not enforced" policy (ktp_file.ini consistency-checks them; manifest must
# match). Other v_*.mdl stay unenforced.
GRENADE_VIEWMODELS = ["models/v_grenade.mdl", "models/v_mills.mdl", "models/v_stick.mdl"]


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
    """Parse local KTPFileChecker ktp_file.ini (or legacy filelist.ini).
    Handles both bare `player/...` and prefixed `sound/player/...` sound paths.
    Drop excluded patterns."""
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


def severity_for(path):
    """Severity for a manifest path: a violation unless its prefix is report-only."""
    return "review" if any(path.startswith(p) for p in REVIEW_PATH_PREFIXES) else "violation"


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
            "severity": severity_for(path),
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
        if leaf in ("p_grenade", "p_mills", "p_stick", "w_grenade", "w_mills", "w_stick",
                    "v_grenade", "v_mills", "v_stick"):
            cat = "grenade_model"
        entries.append({
            "path": path,
            "sha256": sha,
            "size": size,
            "origin": "filelist.ini",
            "category": cat,
            "severity": severity_for(path),
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
            "severity": severity_for(path),
        })
        seen.add(path)

    # 3b. Grenade viewmodels — guaranteed regardless of filelist content
    print(f"[build] Grenade viewmodels ({len(GRENADE_VIEWMODELS)})...", file=sys.stderr)
    for path in GRENADE_VIEWMODELS:
        if path in seen:
            continue
        result = hash_remote_file(ssh, f"{dod_path}/{path}")
        if result is None:
            print(f"[build]   ⚠ {path} not found on server", file=sys.stderr)
            continue
        sha, size = result
        entries.append({
            "path": path, "sha256": sha, "size": size,
            "origin": "explicit_2026-07-07_grenade_viewmodels",
            "category": "grenade_model",
            "severity": severity_for(path),
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
            rel = f"models/{base}.mdl"
            if rel in seen:
                continue
            result = hash_remote_file(ssh, f"{dod_path}/{rel}")
            if result is None:
                continue
            sha, size = result
            entries.append({
                "path": rel, "sha256": sha, "size": size,
                "origin": "explicit_2026-05-02_full_kit",
                "category": "weapon_player_model" if base.startswith("p_") else "weapon_world_model",
                "severity": severity_for(rel),
                "weapon_family": family,
                "variant": "primary",
            })
            seen.add(rel)
            weapon_added += 1

    print(f"[build]   weapon-kit added: {weapon_added}", file=sys.stderr)

    return entries


def assemble_manifest(entries, source_server_label, dod_path):
    entries.sort(key=lambda e: (e["category"], e.get("severity", "violation"), e["path"]))

    # Apply operator-curated alternate hashes. Logged so re-runs surface any
    # ALTERNATE_HASHES keys that no longer match a manifest path (typo / file
    # removed from scope) — silent application would let the alternate quietly
    # stop having effect.
    alt_applied = 0
    alt_unmatched = []
    paths_in_manifest = {e["path"] for e in entries}
    for path, alts in ALTERNATE_HASHES.items():
        if path not in paths_in_manifest:
            alt_unmatched.append(path)
            continue
    for e in entries:
        alts = ALTERNATE_HASHES.get(e["path"])
        if alts:
            e["allowed_alternate_hashes"] = list(alts)
            alt_applied += 1
    if alt_applied:
        print(f"[build]   alternate hashes applied to {alt_applied} entries", file=sys.stderr)
    if alt_unmatched:
        print(f"[build]   WARNING: ALTERNATE_HASHES keys with no matching manifest entry: {alt_unmatched}", file=sys.stderr)

    cat_counts = Counter(e["category"] for e in entries)
    sev_counts = Counter(e["severity"] for e in entries)
    src_counts = Counter(e.get("origin", "?") for e in entries)
    total_size = sum(e["size"] for e in entries)

    # Include alternates in the version hash so adding/removing them invalidates
    # ETag caches and clients re-fetch. Without this, the version stays the same
    # when an alternate is added and clients on the old cached copy keep
    # false-positive-flagging the file.
    version = hashlib.sha256(
        json.dumps(
            [(e["path"], e["sha256"], tuple(e.get("allowed_alternate_hashes") or [])) for e in entries],
            sort_keys=True,
        ).encode()
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
                "review": "Mismatch surfaces in dossier as 'admin review' item, NOT a violation. Player's local file copied into session bundle's review_files/ subdirectory for admin inspection. Use cases: lowered-carry / left-handed variants where the model legitimately differs across map states or community packs; and skyboxes (gfx/env/*), where custom sky packs are commonplace and legitimate but a transparent or flattened sky is a real visual advantage worth an admin's eyes.",
            },
            "scope_notes": [
                "Standard US-vs-Wehrmacht 6v6 weapon kit. British/commonwealth and paratrooper-class weapons NOT enforced.",
                "v_*.mdl (first-person view models) NOT enforced, EXCEPT grenade viewmodels (v_grenade/v_mills/v_stick) — added 2026-07-07 to match ktp_file.ini.",
                "gfx/env/* (skyboxes) IN scope at severity 'review' since 2026-08-27 (was an excluded bucket). Reported and captured for admin review; never counts toward a verdict. Only skyboxes a map .res references enter scope -- stock skies are unreferenced and stay out.",
                "_l / l-suffix pose variants NOT enforced — pruned 2026-05-13 (non-stock community files; MissingFiles noise on clean installs).",
            ],
            "excluded_buckets": [
                "models/{w_aflag,w_gflag,w_wflag}.mdl (flag — cosmetic, allowed)",
                "overviews/* (top-down map BMPs — cosmetic, allowed)",
                # maps/*.bsp: NOT cosmetic, and this is a stated gap rather than a ruling.
                # A client-side BSP edit that removes cover is a real wallhack — the server
                # stays authoritative for collision, so the player is still blocked, but
                # they SEE through what they deleted. The reason maps are out of scope is
                # cost, not harmlessness: the current 213-entry set hashes ~147MB, and the
                # competitive rotation would add roughly 10-15 files at 10-50MB each, on
                # every scan, twice a session. Revisit with a cheaper design (hash only the
                # loaded map, or sample) rather than by silently bolting the rotation on.
                "maps/*.bsp (NOT cosmetic — real wallhack vector; excluded on hashing cost, see comment)",
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
                                "KTPFileChecker" / "ktp_file.ini"),
                    help="Local path to KTPFileChecker ktp_file.ini (the list the plugin loads)")
    ap.add_argument("--out", default="game_files_manifest.json",
                    help="Output JSON path (default: ./game_files_manifest.json)")
    ap.add_argument("--ssh-password", default=None,
                    help="SSH password for source-user (default: $KTP_FLEET_SSH_PASSWORD "
                         "or ~/.ktp_fleet_ssh_password)")
    args = ap.parse_args()

    if not args.ssh_password:
        args.ssh_password = os.environ.get("KTP_FLEET_SSH_PASSWORD")
    if not args.ssh_password:
        pw_file = Path.home() / ".ktp_fleet_ssh_password"
        if pw_file.exists():
            args.ssh_password = pw_file.read_text().strip()
    if not args.ssh_password:
        sys.exit("SSH password required: --ssh-password, $KTP_FLEET_SSH_PASSWORD, "
                 "or ~/.ktp_fleet_ssh_password")

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
