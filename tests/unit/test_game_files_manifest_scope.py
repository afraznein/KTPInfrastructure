"""Scope + severity guards for `scripts/build-game-files-manifest.py`.

The manifest's severity field is the whole safety margin of the 2026-08-27
skybox policy reversal: `gfx/env/*` came into scope, but at `"review"`, which
the AC client's `IsReview` branch keeps out of `modified_game_files`. If a
future edit lets a `gfx/env/` entry out as `"violation"`, every player running
a custom sky pack -- ordinary, legitimate, extremely common -- starts flagging.

So these run the real `build_manifest` against a fake SSH server rather than
asserting on the helper alone. What broke historically in this script was never
the pure function; it was an emit site that kept its own hardcoded literal after
the policy moved. Four of the five emit sites can never see a `gfx/env/` path,
which is exactly why one of them going stale would be invisible.

The partner assertion matters as much: nothing OUTSIDE `gfx/env/` may become
`"review"`. A rule that only ever downgrades would quietly empty the manifest of
anything that can flag a player.

Loaded by path with `paramiko` stubbed -- the script imports it at module scope
and none of it is reachable here, so the Tier 1 gate does not grow an SSH
dependency.
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
import types
from collections import Counter
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "build-game-files-manifest.py"

DOD = "/srv/dod"


@pytest.fixture(scope="module")
def mod():
    sys.modules.setdefault("paramiko", types.ModuleType("paramiko"))
    spec = importlib.util.spec_from_file_location("_ktp_game_files_manifest", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class _Out:
    def __init__(self, text):
        self._text = text

    def read(self):
        return self._text.encode()


class FakeSSH:
    """Serves a synthetic dod/ tree over the three shell commands the script runs.

    Every path in `files` exists; anything else hashes as absent, which is the
    same answer a real server gives and the path `hash_remote_file` returns None on.
    """

    def __init__(self, res_files, files):
        self._res_files = res_files
        self._files = files

    def exec_command(self, cmd, timeout=None):
        if cmd.startswith("ls "):
            return None, _Out("\n".join(f"{DOD}/maps/{n}.res" for n in self._res_files)), None
        if cmd.startswith("cat "):
            name = cmd.split("/")[-1].rstrip("'").replace(".res", "")
            return None, _Out("\n".join(self._res_files[name])), None
        if cmd.startswith("sha256sum "):
            rel = cmd.split("'")[1][len(DOD) + 1:]
            if rel not in self._files:
                return None, _Out(""), None
            body = self._files[rel]
            sha = hashlib.sha256(body.encode()).hexdigest()
            return None, _Out(f"{sha}  {DOD}/{rel}\n{len(body)}\n"), None
        raise AssertionError(f"unexpected command: {cmd}")


# One skybox is six faces; two packs so a per-file rule cannot pass by accident.
SKYBOX = [f"gfx/env/dod_{sky}{face}.tga"
          for sky in ("kraft", "siena")
          for face in ("up", "dn", "lf", "rt", "ft", "bk")]

# Cosmetic buckets that must STAY out entirely -- the reversal was scoped to skies.
STILL_EXCLUDED = ["overviews/dod_kraftstoff.bmp", "models/w_aflag.mdl"]

RES_REFERENCED = SKYBOX + STILL_EXCLUDED + [
    "models/mapmodels/barrel.mdl",
    "sprites/mapsprites/flame.spr",
    "dod_siena.wad",
]

WEAPON_AND_EXPLICIT = [
    "models/p_garand.mdl", "models/w_garand.mdl",
    "models/p_k98.mdl", "models/w_98k.mdl",
    "models/allied_ammo.mdl", "models/axis_ammo.mdl",
    "models/helmet_us.mdl", "models/player.mdl",
    "models/v_grenade.mdl", "models/v_mills.mdl", "models/v_stick.mdl",
]

FILELIST = ["models/player/gerinf/gerinf.mdl", "sound/player/die1.wav"]


@pytest.fixture
def built(mod, tmp_path):
    ini = tmp_path / "ktp_file.ini"
    ini.write_text("// header\n" + "\n".join(
        # `player/...` sound entries arrive without the sound/ prefix, as on the fleet.
        p[len("sound/"):] if p.startswith("sound/player/") else p for p in FILELIST
    ) + "\n")

    every = RES_REFERENCED + WEAPON_AND_EXPLICIT + FILELIST
    files = {p: f"bytes-of-{p}" for p in every}
    ssh = FakeSSH({"dod_kraftstoff": RES_REFERENCED}, files)
    return mod.build_manifest(ssh, DOD, str(ini))


def _by_path(entries):
    return {e["path"]: e for e in entries}


def test_skyboxes_are_in_scope_and_report_only(built):
    got = _by_path(built)
    missing = [p for p in SKYBOX if p not in got]
    assert not missing, f"skyboxes referenced by a .res must be in the manifest: {missing}"
    assert {got[p]["severity"] for p in SKYBOX} == {"review"}, (
        "a gfx/env/ entry emitted as 'violation' flags every player running a custom "
        "sky pack -- the policy reversal is report-only"
    )


def test_review_severity_is_confined_to_skyboxes(built):
    stray = sorted(e["path"] for e in built
                   if e["severity"] == "review" and not e["path"].startswith("gfx/env/"))
    assert not stray, f"only gfx/env/ is report-only; these were downgraded too: {stray}"


def test_everything_else_still_violates(built):
    for path in WEAPON_AND_EXPLICIT + FILELIST + ["models/mapmodels/barrel.mdl",
                                                  "sprites/mapsprites/flame.spr",
                                                  "dod_siena.wad"]:
        entry = _by_path(built).get(path)
        assert entry is not None, f"{path} dropped out of the manifest"
        assert entry["severity"] == "violation", f"{path} must still count toward a verdict"


def test_the_other_cosmetic_buckets_stayed_excluded(built):
    got = _by_path(built)
    present = [p for p in STILL_EXCLUDED if p in got]
    assert not present, (
        f"the reversal was scoped to skyboxes; these are still allowed modification: {present}"
    )


def test_severity_counts_partition_the_manifest(built):
    counts = Counter(e["severity"] for e in built)
    assert set(counts) == {"violation", "review"}
    assert counts["review"] == len(SKYBOX)
    assert counts["violation"] == len(built) - len(SKYBOX)


def test_severity_for_reads_the_policy_tuple_not_a_literal(mod):
    # Pins the indirection itself: the emit sites must go through severity_for,
    # so editing REVIEW_PATH_PREFIXES is sufficient to change or revert policy.
    assert mod.severity_for("gfx/env/dod_kraftup.tga") == "review"
    assert mod.severity_for("models/p_garand.mdl") == "violation"
    assert mod.severity_for("gfx/shell.spr") == "violation", "prefix must not match loosely"
