#!/usr/bin/env python3
"""build_map_bundle.py -- one entry point from "a new .bsp landed" to a deployable bundle.

    maps/<map>.bsp          given
    maps/<map>.res          RESGen
    overviews/<map>.txt     make_overview_descriptor.py
    overviews/<map>.bmp     render_overview_bmp.py
    MANIFEST.json           md5 of each of the four, for the post-deploy sweep

The bundle is written to a staging directory and NOTHING here touches a server.
Deploying is the operator's act; docs/MAP_DEPLOY.md is the other half.

Two facts the ordering depends on, both measured against the live fleet:

RESGen adds `overviews/<map>.txt` + `.bmp` only when both already exist on disk
next to the map (`<bundle>/overviews/`), so the overview has to be rendered
BEFORE the .res is generated. Ten of the eleven deltas in the 44-map fleet
replay were exactly this -- a .res generated on one side of its overview's
existence. Nothing reports the omission; the client just has no minimap.

RESGen writes CRLF on Windows and LF on Linux. All 47 .res files on the fleet
are CRLF, so that is the proven-safe default here regardless of build host.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

HEADER_RE = re.compile(r"^\s*//")
VERSION_RE = re.compile(r"created with RESGen v(\d+(?:\.\d+)*)")
BSP_VERSION_HL = 30

# Entry classes whose absence the engine turns into a visible or fatal failure.
# .mdl/.spr can Sys_Error out of Mod_LoadModel -- see scripts/validate-map-assets.sh.
CRITICAL_EXT = (".mdl", ".spr")

# Per-map HUD icon indices start here; 0-17 are the stock set every client has.
CUSTOM_HUD_ICON_MIN = 18
ENTRY_COUNT_RE = re.compile(r"(//\s*\.res entries \()(\d+)(\):)")
STOCK_PATHS_REL = Path("data") / "dod-depot31-stock-paths.txt"


# ----------------------------------------------------------------- pure helpers

def parse_res_entries(text: str) -> list[str]:
    """Entry list of a .res, with the header block and line endings normalised away."""
    out = []
    for line in text.replace("\r\n", "\n").split("\n"):
        line = line.strip()
        if line and not HEADER_RE.match(line):
            out.append(line)
    return out


def res_version(text: str) -> str | None:
    m = VERSION_RE.search(text)
    return m.group(1) if m else None


def to_crlf(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\n", "\r\n")


def to_lf(text: str) -> str:
    return text.replace("\r\n", "\n")


def read_worldspawn(bsp: bytes) -> dict[str, str]:
    """worldspawn keys of a Half-Life BSP. Raises ValueError on anything else."""
    if len(bsp) < 12:
        raise ValueError("too short to be a BSP")
    version = struct.unpack("<i", bsp[:4])[0]
    if version != BSP_VERSION_HL:
        raise ValueError(f"BSP version {version}, expected {BSP_VERSION_HL}")
    off, length = struct.unpack("<ii", bsp[4:12])
    if off < 0 or length < 0 or off + length > len(bsp):
        raise ValueError("entity lump runs past end of file")
    ents = bsp[off:off + length].decode("latin-1")
    first = ents.split("}", 1)[0]
    keys = {}
    for k, v in re.findall(r'"([^"]*)"\s+"([^"]*)"', first):
        keys.setdefault(k, v)
    return keys


def bsp_wads(worldspawn: dict[str, str]) -> list[str]:
    """WAD basenames from the worldspawn "wad" key. Absent key means none, not an error."""
    raw = worldspawn.get("wad", "")
    out = []
    for part in raw.replace("\\", "/").split(";"):
        part = part.strip()
        if part:
            out.append(part.rsplit("/", 1)[-1])
    return out


def check_res(entries: list[str], mapname: str, *, require_overviews: bool = True) -> list[str]:
    """Everything wrong with an entry list. Empty return means it passed."""
    problems = []
    if not entries:
        problems.append("no entries at all")
    if len(set(entries)) != len(entries):
        dupes = sorted({e for e in entries if entries.count(e) > 1})
        problems.append(f"duplicate entries: {', '.join(dupes)}")
    if entries != sorted(entries, key=str.lower):
        # RESGen sorts case-insensitively. Asserting a case-SENSITIVE order here
        # failed the fleet's own dod_saints.res on sound/ambience/Opera.wav.
        problems.append("entries are not in ascending order")
    for e in entries:
        if "\\" in e:
            problems.append(f"backslash in path: {e}")
        if e.startswith("/") or re.match(r"^[A-Za-z]:", e):
            problems.append(f"absolute path: {e}")
        if ".." in e.split("/"):
            problems.append(f"parent traversal in path: {e}")
        if e != e.strip():
            problems.append(f"leading or trailing whitespace: {e!r}")
    if require_overviews:
        for ext in (".bmp", ".txt"):
            want = f"overviews/{mapname}{ext}"
            if want not in entries:
                problems.append(f"missing {want} -- was the overview rendered before RESGen ran?")
    return problems


def delta(new: list[str], old: list[str]) -> tuple[list[str], list[str]]:
    """(added, removed) between two entry lists, each sorted."""
    return sorted(set(new) - set(old)), sorted(set(old) - set(new))


def entity_hud_icon_indices(bsp: bytes) -> set[int]:
    """Every `point_hud_icon_*` value in the whole entity lump.

    read_worldspawn stops at the first entity by design, and control points sit
    further in, so this cannot reuse it.
    """
    if len(bsp) < 12:
        raise ValueError("too short to be a BSP")
    version = struct.unpack("<i", bsp[:4])[0]
    if version != BSP_VERSION_HL:
        raise ValueError(f"BSP version {version}, expected {BSP_VERSION_HL}")
    off, length = struct.unpack("<ii", bsp[4:12])
    if off < 0 or length < 0 or off + length > len(bsp):
        raise ValueError("entity lump runs past end of file")
    ents = bsp[off:off + length].decode("latin-1")
    out = set()
    for _, value in re.findall(r'"(point_hud_icon_[a-z]*)"\s+"([^"]*)"', ents):
        try:
            out.add(int(value))
        except ValueError:
            continue
    return out


def custom_icon_entries(game_root: Path, mapname: str) -> list[str]:
    """The map's own `sprites/obj_icons/<map>/` directory, as .res entries.

    Listed, never derived from the index. The arithmetic that turns an index
    into `custom<N>_<team>` reproduces dod_solitude2 and dod_saints and then
    fails on dod_falaise, with no slot for the `_brit` variants dod_zalec
    ships; the real table lives in the client, not here.
    """
    d = game_root / "sprites" / "obj_icons" / mapname
    if not d.is_dir():
        return []
    return sorted(f"sprites/obj_icons/{mapname}/{p.name}"
                  for p in d.iterdir() if p.is_file())


def stock_paths(scripts_dir: Path) -> set[str]:
    """Game-relative paths the DoD client already ships, lowercased."""
    f = scripts_dir / STOCK_PATHS_REL
    if not f.exists():
        return set()
    return {ln.strip().replace("\\", "/").lower()
            for ln in f.read_text(encoding="utf-8", errors="replace").splitlines()
            if ln.strip()}


def merge_entries(entries: list[str], extra: list[str]) -> list[str]:
    """Merge and sort the way RESGen does, which is case-insensitively.

    Sorting case-sensitively here would leave check_res disagreeing with the
    file this just wrote.
    """
    have = {e.lower() for e in entries}
    return sorted(entries + [e for e in extra if e.lower() not in have],
                  key=str.lower)


def rebuild_res(text: str, entries: list[str]) -> str:
    """Re-emit a .res with a new entry list, keeping RESGen's header block.

    The `// .res entries (N):` count goes with it: a stale count is a silent
    lie about a file whose whole job is to be a complete list.
    """
    head = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if line.strip() and not HEADER_RE.match(line.strip()):
            break
        head.append(ENTRY_COUNT_RE.sub(rf"\g<1>{len(entries)}\g<3>", line))
    return "\n".join(head + entries) + "\n"


def classify(entries: list[str]) -> dict[str, list[str]]:
    """Group entries by the kind of failure a missing one produces."""
    groups: dict[str, list[str]] = {"critical": [], "other": []}
    for e in entries:
        key = "critical" if e.lower().endswith(CRITICAL_EXT) else "other"
        groups[key].append(e)
    return groups


def md5_file(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest(bundle: Path, mapname: str) -> dict:
    """md5 of every file the bundle ships, keyed by its game-relative path."""
    files = {}
    for rel in (f"maps/{mapname}.bsp", f"maps/{mapname}.res",
                f"overviews/{mapname}.txt", f"overviews/{mapname}.bmp"):
        p = bundle / rel
        if p.exists():
            files[rel] = {"md5": md5_file(p), "bytes": p.stat().st_size}
    return {"map": mapname, "files": files}


# ------------------------------------------------------------------ orchestration

def run_resgen(resgen: str, maps_dir: Path, mapname: str) -> str:
    """Generate <map>.res in maps_dir and return its text.

    Runs with the working directory inside maps_dir because RESGen resolves the
    overview as `<cwd of the bsp>/../overviews/` -- an absolute -f path finds no
    overview and silently produces a .res without one.
    """
    out = maps_dir / f"{mapname}.res"
    if out.exists():
        out.unlink()
    proc = subprocess.run(
        [resgen, "-o", "-v", "-f", f"{mapname}.bsp"],
        cwd=maps_dir, capture_output=True, text=True, timeout=600,
    )
    if not out.exists():
        raise RuntimeError(
            f"RESGen produced no .res for {mapname}\n"
            f"  stdout: {proc.stdout.strip()}\n  stderr: {proc.stderr.strip()}"
        )
    return out.read_text(encoding="utf-8", errors="replace")


def make_overviews(scripts_dir: Path, bsp: Path, overviews: Path, mapname: str) -> None:
    """Render the overview pair with the two descriptor/BMP scripts."""
    descriptor = scripts_dir / "make_overview_descriptor.py"
    renderer = scripts_dir / "render_overview_bmp.py"
    missing = [p.name for p in (descriptor, renderer) if not p.exists()]
    if missing:
        raise SystemExit(
            f"ERROR: {', '.join(missing)} not found in {scripts_dir}.\n"
            "       They arrive with KTPInfrastructure PRs #395 and #396. Until those\n"
            "       merge, render the overviews separately and pass --overviews-from."
        )
    overviews.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, str(descriptor), str(bsp),
                    "--out", str(overviews / f"{mapname}.txt")], check=True)
    subprocess.run([sys.executable, str(renderer), str(bsp),
                    "--descriptor", str(overviews / f"{mapname}.txt"),
                    "--out", str(overviews / f"{mapname}.bmp")], check=True)


def copy_overviews(src: Path, overviews: Path, mapname: str) -> None:
    overviews.mkdir(parents=True, exist_ok=True)
    for ext in (".txt", ".bmp"):
        s = src / f"{mapname}{ext}"
        if not s.exists():
            raise SystemExit(f"ERROR: {s} not found (--overviews-from)")
        shutil.copy2(s, overviews / f"{mapname}{ext}")


def build_one(bsp: Path, out: Path, args, scripts_dir: Path) -> dict:
    mapname = bsp.stem
    maps_dir = out / "maps"
    overviews = out / "overviews"
    maps_dir.mkdir(parents=True, exist_ok=True)

    worldspawn = read_worldspawn(bsp.read_bytes())

    staged_bsp = maps_dir / f"{mapname}.bsp"
    if not (staged_bsp.exists() and staged_bsp.samefile(bsp)):
        shutil.copy2(bsp, staged_bsp)

    if args.overviews_from:
        copy_overviews(Path(args.overviews_from), overviews, mapname)
    elif not args.no_overviews:
        make_overviews(scripts_dir, staged_bsp, overviews, mapname)
    else:
        overviews.mkdir(parents=True, exist_ok=True)

    text = run_resgen(args.resgen, maps_dir, mapname)
    entries = parse_res_entries(text)

    # RESGen harvests entity VALUES that look like paths, which is why
    # point_reset_model and point_*_capsound are already covered. A
    # `point_hud_icon_*` value is an INTEGER, so there is no path in the BSP for
    # it to find -- the files are reachable only through the index, and from the
    # index only by listing the directory.
    wants_custom_icons = any(i >= CUSTOM_HUD_ICON_MIN
                             for i in entity_hud_icon_indices(bsp.read_bytes()))
    hud_icons: list[str] = []
    if wants_custom_icons:
        stock = stock_paths(scripts_dir)
        hud_icons = [e for e in custom_icon_entries(bsp.parent.parent, mapname)
                     if e.lower() not in stock]
        if hud_icons:
            entries = merge_entries(entries, hud_icons)
            text = rebuild_res(text, entries)

    body = to_crlf(text) if args.line_endings == "crlf" else to_lf(text)
    (maps_dir / f"{mapname}.res").write_bytes(body.encode("utf-8"))

    problems = check_res(entries, mapname, require_overviews=not args.no_overviews)

    # A map that needs custom icons and has none beside it must not pass
    # quietly: that is the dod_solitude2 case, where the icons were on every
    # server and FastDL and absent only from the list that tells a client to
    # fetch them, so the two middle flags rendered blank.
    if wants_custom_icons and not hud_icons:
        problems.append(
            f"uses custom HUD icon indices but no non-stock file was found in "
            f"{bsp.parent.parent / 'sprites' / 'obj_icons' / mapname} -- those "
            f"flags render blank for any client that does not already have them")

    result = {
        "map": mapname,
        "resgen_version": res_version(text),
        "entries": len(entries),
        "wads_in_bsp": bsp_wads(worldspawn),
        "skyname": worldspawn.get("skyname", ""),
        "hud_icons_added": hud_icons,
        "problems": problems,
        "manifest": manifest(out, mapname),
    }

    if args.compare_against:
        prev = Path(args.compare_against)
        cands = sorted(prev.glob("*.res"))
        match = next((c for c in cands if c.stem == args.predecessor), None) if args.predecessor \
            else (cands[0] if len(cands) == 1 else None)
        if match:
            old = parse_res_entries(match.read_text(encoding="utf-8", errors="replace"))
            added, removed = delta(entries, old)
            result["compared_to"] = match.stem
            result["added"] = added
            result["removed"] = removed
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("bsp", nargs="+", help="path to each new .bsp")
    ap.add_argument("--out", required=True, help="bundle staging directory (never a server path)")
    ap.add_argument("--resgen", default=os.environ.get("KTP_RESGEN", "resgen"),
                    help="resgen binary; build it with scripts/build_resgen.sh")
    ap.add_argument("--overviews-from", help="copy an already-rendered overview pair from here "
                                             "instead of rendering one")
    ap.add_argument("--no-overviews", action="store_true",
                    help="skip the overview entirely; also drops the overview-pair check")
    ap.add_argument("--line-endings", choices=("crlf", "lf"), default="crlf",
                    help="default crlf -- what every .res on the fleet already uses")
    ap.add_argument("--compare-against", help="directory holding the predecessor's .res")
    ap.add_argument("--predecessor", help="predecessor map name, when --compare-against holds several")
    ap.add_argument("--json", action="store_true", help="machine-readable report on stdout")
    args = ap.parse_args(argv)

    scripts_dir = Path(__file__).resolve().parent
    out = Path(args.out)
    results = [build_one(Path(b), out, args, scripts_dir) for b in args.bsp]

    # Merge, don't replace: one map per invocation is the normal way to use this,
    # and a replacing write would drop the maps already staged in this bundle.
    mf = out / "MANIFEST.json"
    combined = json.loads(mf.read_text(encoding="utf-8")) if mf.exists() else {}
    combined.update({r["map"]: r["manifest"]["files"] for r in results})
    mf.write_text(json.dumps(combined, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for r in results:
            print(f"\n{r['map']}  ({r['entries']} entries, RESGen v{r['resgen_version']})")
            print(f"  wads in bsp : {', '.join(r['wads_in_bsp']) or '(none)'}")
            print(f"  skyname     : {r['skyname'] or '(none)'}")
            if "compared_to" in r:
                print(f"  vs {r['compared_to']}:")
                crit = set(classify(r["removed"])["critical"])
                for a in r["added"]:
                    print(f"    + {a}")
                for d in r["removed"]:
                    # A dropped model or sprite is the delta that reads as a broken
                    # map rather than a missing resource. Say so at the line.
                    print(f"    - {d}" + ("   <- dropped model/sprite; confirm against the map"
                                          if d in crit else ""))
            for p in r["problems"]:
                print(f"  PROBLEM: {p}")
        print(f"\nbundle: {out}")
        print("Nothing was deployed. docs/MAP_DEPLOY.md is the operator half.")

    return 1 if any(r["problems"] for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
