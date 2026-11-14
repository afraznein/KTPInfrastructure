"""`maps/*.bsp` stays out of manifest scope even when a map's `.res` names it.

The generator documents maps as an excluded bucket -- a stated gap on hashing cost, not a
ruling that a BSP edit is harmless -- but nothing enforced it. The `.res` route accepts any
listed `.bsp`, so a map whose resource list names itself put its own world file in scope at
severity `violation`. Coverage of the largest wallhack surface was then decided by how each
`.res` happened to be written, and a widely shared older build of one such map scored as
`modified_game_files` on unrelated players.

Same harness as `test_res_file_exclusion.py`: loaded by path with `paramiko` stubbed.
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "build-game-files-manifest.py"

DOD = "/srv/dod"

# The map's real asset. It must stay in scope: excluding the resource list must not
# exclude what the resource list is for.
MAP_ASSET = "models/mapmodels/anjou_bakery.mdl"
# A stock path via ktp_file.ini, so the assembled manifest is not made only of .res.
FILELIST_PATH = "sound/player/pl_step1.wav"

# A .res that lists its own map. The live manifest carried exactly this shape for three
# maps, and one of them charged players holding a shared older copy of that map.
SELF_BSP = "maps/dod_anjou.bsp"
SELF_BSP_UPPER = "maps/DOD_ANJOU2.BSP"


@pytest.fixture(scope="module")
def mod():
    sys.modules.setdefault("paramiko", types.ModuleType("paramiko"))
    spec = importlib.util.spec_from_file_location("_ktp_manifest_bsp_exclusion", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class _Out:
    def __init__(self, text):
        self._text = text

    def read(self):
        return self._text.encode()


class FakeSSH:
    def __init__(self, res_files, files):
        self._res_files = res_files
        self._files = files
        self.hashed = []

    def exec_command(self, cmd, timeout=None):
        if cmd.startswith("ls "):
            return None, _Out("\n".join(f"{DOD}/maps/{n}.res" for n in self._res_files)), None
        if cmd.startswith("cat "):
            name = cmd.split("/")[-1].rstrip("'").replace(".res", "")
            return None, _Out("\n".join(self._res_files[name])), None
        if cmd.startswith("sha256sum "):
            rel = cmd.split("'")[1][len(DOD) + 1:]
            self.hashed.append(rel)
            if rel not in self._files:
                return None, _Out(""), None
            body = self._files[rel]
            sha = hashlib.sha256(body.encode()).hexdigest()
            return None, _Out(f"{sha}  {DOD}/{rel}\n{len(body)}\n"), None
        raise AssertionError(f"unexpected command: {cmd}")


REFERENCED = [MAP_ASSET, SELF_BSP, SELF_BSP_UPPER]


@pytest.fixture
def built(mod, tmp_path):
    ini = tmp_path / "ktp_file.ini"
    ini.write_text("// header\n" + FILELIST_PATH[len("sound/"):] + "\n")
    on_disk = {p.lower(): f"bytes-of-{p}" for p in REFERENCED}
    on_disk[FILELIST_PATH] = "bytes-of-footsteps"
    ssh = FakeSSH({"dod_anjou": REFERENCED}, on_disk)
    entries = mod.build_manifest(ssh, DOD, str(ini))
    return mod.assemble_manifest(entries, "fake", DOD), ssh


def test_the_fixture_actually_feeds_a_bsp(built):
    """Negative control on the fixture: every assertion below is "no .bsp in the output"."""
    manifest, _ = built
    assert any(p.lower().endswith(".bsp") for p in REFERENCED)
    assert manifest["files"], "the fixture produced an empty manifest"


def test_a_res_listed_bsp_is_not_a_manifest_entry(built):
    manifest, _ = built
    offenders = [e["path"] for e in manifest["files"] if e["path"].lower().endswith(".bsp")]
    assert not offenders, (
        f"{offenders} in scope via a .res. Maps are an excluded bucket; enforcing only the "
        f"ones whose .res names itself is coverage chosen by accident"
    )


def test_the_maps_own_assets_stay_in_scope(built):
    manifest, _ = built
    paths = {e["path"] for e in manifest["files"]}
    assert MAP_ASSET in paths, "excluding .bsp dropped the map asset the .res is for"
    assert FILELIST_PATH in paths, "ktp_file.ini route collaterally dropped"


def test_an_excluded_bsp_is_never_hashed(built):
    """A map is tens of MB; hashing it to throw the answer away is the cost the gap exists to avoid."""
    _, ssh = built
    hashed = [p for p in ssh.hashed if p.lower().endswith(".bsp")]
    assert not hashed, f"hashed a path it then excluded: {hashed}"


def test_the_artifact_still_says_bsp_is_excluded(built):
    manifest, _ = built
    buckets = " ".join(manifest["_meta"]["excluded_buckets"]).lower()
    assert "maps/*.bsp" in buckets


def test_bsp_is_in_the_declared_policy(mod):
    assert ".bsp" in mod.EXCLUDED_EXTENSIONS
