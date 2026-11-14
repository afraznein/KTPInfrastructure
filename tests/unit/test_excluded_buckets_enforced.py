"""Every bucket `_meta.excluded_buckets` declares is enforced on every route into the manifest.

`maps/*.bsp` sat in that list for months while the `.res` route admitted it, so the declared
policy and the built artifact disagreed and nothing noticed. The list is now derived from
`EXCLUDED_BUCKETS`, the same tuple `is_excluded()` reads. These tests feed one path per
declared bucket through each route a path can enter by -- a map `.res`, `ktp_file.ini`, and
the hard-coded explicit lists -- and assert none reaches the manifest.

Same harness as `test_bsp_file_exclusion.py`: loaded by path with `paramiko` stubbed.
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

# In scope on every route, so an empty manifest cannot pass as "nothing leaked".
KEEP_RES = "models/mapmodels/barrel.mdl"
KEEP_FILELIST = "sound/player/pl_step1.wav"


@pytest.fixture(scope="module")
def mod():
    sys.modules.setdefault("paramiko", types.ModuleType("paramiko"))
    spec = importlib.util.spec_from_file_location("_ktp_manifest_buckets_enforced", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class _Out:
    def __init__(self, text):
        self._text = text

    def read(self):
        return self._text.encode()


class FakeSSH:
    """Serves a synthetic dod/ tree. Every path in `files` exists, case-insensitively."""

    def __init__(self, res_files, files):
        self._res_files = res_files
        self._files = {k.lower(): v for k, v in files.items()}
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
            body = self._files.get(rel.lower())
            if body is None:
                return None, _Out(""), None
            sha = hashlib.sha256(body.encode()).hexdigest()
            return None, _Out(f"{sha}  {DOD}/{rel}\n{len(body)}\n"), None
        raise AssertionError(f"unexpected command: {cmd}")


def samples_for(bucket):
    """Concrete paths a bucket must cover, built from its own rule so a new bucket is
    exercised without editing this file. Each also appears upper-cased."""
    if bucket.rule == "exact":
        base = list(bucket.values)
    elif bucket.rule == "prefix":
        base = [f"{v}dod_sample.bmp" for v in bucket.values]
    elif bucket.rule == "suffix":
        base = [f"maps/dod_sample{v}" for v in bucket.values]
    else:
        raise AssertionError(f"bucket rule {bucket.rule!r} has no sample generator")
    return base + [p.upper() for p in base]


@pytest.fixture(scope="module")
def samples(mod):
    out = [(b.label, p) for b in mod.EXCLUDED_BUCKETS for p in samples_for(b)]
    assert out, "no excluded buckets declared"
    return out


def _paths(entries):
    return {e["path"].lower() for e in entries}


def _excluded_in(entries, samples):
    got = _paths(entries)
    return sorted({p for _, p in samples if p.lower() in got})


# --------------------------------------------------------------------------
# The declared list is the enforced list
# --------------------------------------------------------------------------

def test_meta_labels_are_the_enforced_buckets(mod):
    manifest = mod.assemble_manifest([], "fake", DOD)
    assert manifest["_meta"]["excluded_buckets"] == [b.label for b in mod.EXCLUDED_BUCKETS]


def test_every_bucket_has_a_rule_is_excluded_applies(mod):
    for b in mod.EXCLUDED_BUCKETS:
        for p in samples_for(b):
            assert mod.is_excluded(p), f"{p!r} not excluded although {b.label!r} is declared"


def test_is_excluded_is_not_a_blanket_yes(mod):
    for p in (KEEP_RES, KEEP_FILELIST, "models/p_garand.mdl", "gfx/env/dod_kraftup.tga",
              "maps/dod_x.txt", "sprites/overviews_icon.spr"):
        assert not mod.is_excluded(p), p


def test_the_derived_views_agree_with_the_buckets(mod):
    assert ".res" in mod.EXCLUDED_EXTENSIONS and ".bsp" in mod.EXCLUDED_EXTENSIONS
    assert "overviews/" in mod.EXCLUDED_PATH_PREFIXES
    assert "models/w_aflag.mdl" in mod.EXCLUDED_EXACT


# --------------------------------------------------------------------------
# Route 1: a map .res
# --------------------------------------------------------------------------

@pytest.fixture
def via_res(mod, samples, tmp_path):
    ini = tmp_path / "ktp_file.ini"
    ini.write_text("// header\n" + KEEP_FILELIST[len("sound/"):] + "\n")
    listed = [KEEP_RES] + [p for _, p in samples]
    files = {p: f"bytes-of-{p}" for p in listed + [KEEP_FILELIST]}
    ssh = FakeSSH({"dod_sample": listed}, files)
    return mod.build_manifest(ssh, DOD, str(ini)), ssh


def test_res_route_admits_no_excluded_bucket(via_res, samples):
    entries, _ = via_res
    assert KEEP_RES in _paths(entries), "fixture control: the .res route emitted nothing"
    assert not _excluded_in(entries, samples)


def test_res_route_never_hashes_an_excluded_path(mod, via_res):
    _, ssh = via_res
    assert not [p for p in ssh.hashed if mod.is_excluded(p)]


# --------------------------------------------------------------------------
# Route 2: ktp_file.ini
# --------------------------------------------------------------------------

@pytest.fixture
def via_filelist(mod, samples, tmp_path):
    ini = tmp_path / "ktp_file.ini"
    lines = [KEEP_FILELIST[len("sound/"):]] + [p for _, p in samples]
    ini.write_text("// header\n" + "\n".join(lines) + "\n")
    files = {p: f"bytes-of-{p}" for p in [KEEP_FILELIST] + [p for _, p in samples]}
    ssh = FakeSSH({}, files)
    return mod.build_manifest(ssh, DOD, str(ini)), ssh


def test_filelist_route_admits_no_excluded_bucket(via_filelist, samples):
    entries, _ = via_filelist
    assert KEEP_FILELIST in _paths(entries), "fixture control: the filelist route emitted nothing"
    assert not _excluded_in(entries, samples)


def test_filelist_parser_drops_every_excluded_bucket(mod, samples, tmp_path):
    ini = tmp_path / "ktp_file.ini"
    ini.write_text("\n".join(p for _, p in samples) + "\n")
    assert mod.parse_filelist_ini(str(ini)) == []


# --------------------------------------------------------------------------
# Route 3: the hard-coded explicit lists
# --------------------------------------------------------------------------

def test_no_explicit_route_names_an_excluded_path(mod):
    assert not [p for p in mod.explicit_paths() if mod.is_excluded(p)]


@pytest.mark.parametrize("attr", ["EXPLICIT_SINGLETONS", "GRENADE_VIEWMODELS"])
def test_the_import_guard_refuses_an_excluded_explicit_path(mod, monkeypatch, attr):
    monkeypatch.setattr(mod, attr, (*getattr(mod, attr), "models/w_gflag.mdl"))
    with pytest.raises(ValueError, match="w_gflag"):
        mod._check_explicit_scope()


def test_the_import_guard_covers_the_weapon_kit(mod, monkeypatch):
    monkeypatch.setattr(mod, "WEAPON_FAMILIES", [*mod.WEAPON_FAMILIES, ("flag", [], ["w_aflag"])])
    with pytest.raises(ValueError, match="w_aflag"):
        mod._check_explicit_scope()


@pytest.mark.parametrize("attr", ["EXPLICIT_SINGLETONS", "GRENADE_VIEWMODELS"])
def test_build_refuses_rather_than_emits_an_excluded_explicit_path(mod, monkeypatch, tmp_path, attr):
    """The backstop: a route that skips the filter (or a guard bypassed by a later edit)
    must stop the build, not ship the path. Not a w_ model: the weapon-kit pass drops
    those by category and would hide the leak."""
    leak = "overviews/dod_sample.bmp"
    monkeypatch.setattr(mod, attr, (*getattr(mod, attr), leak))
    ini = tmp_path / "ktp_file.ini"
    ini.write_text("")
    ssh = FakeSSH({}, {leak: "bytes"})
    with pytest.raises(ValueError, match="overviews/dod_sample"):
        mod.build_manifest(ssh, DOD, str(ini))
