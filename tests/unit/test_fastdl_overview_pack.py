"""The /dod page must publish ONE archive holding the current pool's overviews.

Per-map links alone lose people: a player fetches nine pairs and then has to work out
where they go. The archive is the half that helps, so what is locked here is that it
exists, that its contents are the pool and nothing else, and that the pool comes from
the fleet's own ktp_maps.ini rather than from any list of map names.

That last point is the whole reason this is a test and not a config: three S10 stems were
re-cut mid-season (dod_saints2_b3e became _b5e), so an archive built from a remembered
pool ships names no BSP carries, and the player sees a blank overview rather than an
error. The re-cut case is asserted directly -- both the dead and the live stem sit on
disk and only the live one may ship.
"""
from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / "scripts" / "ktp-fastdl-indexes.py"
PACK = "ktp-s10-overviews.zip"
NOTE = "KTP-OVERVIEWS-README.txt"

# Two pool maps and, deliberately, a re-cut pair: _b3e is the dead stem the board still
# quotes and _b5e is what the ini now names. Both are on disk.
POOL = ["dod_thunder2", "dod_saints2_b5e"]
OFF_POOL = ["dod_saints2_b3e", "dod_kalt", "dod_rr2_test"]

INI = """; KTPMatchHandler map list
; ==========================================
; KTP Match Handler - Map Configuration
; ==========================================
;
; ==========================================
; SEASONAL MAPS (S10, in schedule order)
; .changemap lists maps in this file's order, 7 per page.
; ==========================================

[dod_thunder2]
config = ktp_thunder2.cfg
name = Thunder2
type = competitive

[dod_saints2_b5e]
config = ktp_saints.cfg
name = Saints2
type = competitive

; ==========================================
; REMAINING MAPS (alphabetical)
; ==========================================

[dod_kalt]
config = ktp_kalt.cfg
name = Kalt
type = competitive

[dod_saints2_b3e]
config = ktp_saints.cfg
name = Saints2 b3e
type = competitive
"""


def build_tree(tmp_path, stems, ini_text=INI):
    fastdl, demos = tmp_path / "fastdl", tmp_path / "demos"
    (fastdl / "dod" / "overviews").mkdir(parents=True)
    (fastdl / "dod" / "maps").mkdir()
    demos.mkdir()
    for stem in stems:
        (fastdl / "dod" / "overviews" / (stem + ".txt")).write_text(
            "global\n{\n\tZOOM\t1.15\n}\n", encoding="utf-8")
        (fastdl / "dod" / "overviews" / (stem + ".bmp")).write_bytes(b"BM" + bytes(4096))
    ini = tmp_path / "ktp_maps.ini"
    ini.write_text(ini_text, encoding="utf-8")
    return fastdl, demos, ini


def generate(tmp_path, fastdl, demos, ini):
    empty = tmp_path / "empty-bin"
    empty.mkdir(exist_ok=True)
    r = subprocess.run([sys.executable, str(SCRIPT), "--apply",
                        "--fastdl", str(fastdl), "--demos", str(demos),
                        "--maps-ini", str(ini)],
                       env=dict(os.environ, PATH=str(empty)),
                       capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stdout + r.stderr
    return r.stdout + r.stderr


@pytest.fixture
def site(tmp_path):
    fastdl, demos, ini = build_tree(tmp_path, POOL + OFF_POOL)
    out = generate(tmp_path, fastdl, demos, ini)
    return fastdl, out


def archive(fastdl):
    return zipfile.ZipFile(fastdl / "dod" / "overviews" / PACK)


def test_the_archive_holds_the_pool_and_only_the_pool(site):
    fastdl, _ = site
    names = archive(fastdl).namelist()
    assert set(names) == {s + e for s in POOL for e in (".txt", ".bmp")} | {NOTE}, names
    # Control in the opposite direction: a stem on disk but outside the seasonal block
    # must not be in here, or the assert above would pass on "pack everything".
    for stem in OFF_POOL:
        assert stem + ".bmp" not in names, stem


def test_a_re_cut_stem_does_not_ship(site):
    """The dead and the live stem both sit on disk; the ini decides which is real."""
    names = archive(site[0]).namelist()
    assert "dod_saints2_b5e.bmp" in names
    assert "dod_saints2_b3e.bmp" not in names


def test_every_member_extracts_to_its_own_name(site):
    """"Without renaming anything" is the pass criterion, so no path prefix and no
    directory entry: every member is the exact filename the engine asks for."""
    for name in archive(site[0]).namelist():
        assert "/" not in name and not name.startswith("dod/"), name


def test_the_archive_is_byte_deterministic_across_runs(tmp_path):
    """An hourly job that stamped the build clock would hand every visitor a fresh
    download of identical assets, and "rewrite only when it changed" would be a lie."""
    fastdl, demos, ini = build_tree(tmp_path, POOL)
    generate(tmp_path, fastdl, demos, ini)
    pack = fastdl / "dod" / "overviews" / PACK
    first, mtime = pack.read_bytes(), pack.stat().st_mtime_ns
    out = generate(tmp_path, fastdl, demos, ini)
    assert pack.read_bytes() == first
    assert pack.stat().st_mtime_ns == mtime, "unchanged assets must not rewrite the file"
    assert "unchanged" in out


def test_the_dod_page_links_the_archive_and_each_pool_file(site):
    fastdl, _ = site
    dod = (fastdl / "dod" / "index.html").read_text(encoding="utf-8")
    assert 'href="overviews/%s"' % PACK in dod
    for stem in POOL:
        for ext in (".txt", ".bmp"):
            assert 'href="overviews/%s%s"' % (stem, ext) in dod, stem + ext
    # Control: the page must not advertise an off-pool stem either, since the archive
    # and the list beside it have to describe the same thing.
    assert 'href="overviews/dod_saints2_b3e.bmp"' not in dod
    assert "dod_zzznope" not in dod


def test_a_pool_map_missing_half_its_pair_publishes_nothing(tmp_path):
    """Partial is worse than absent: the page promises every pool map, so the player
    finds the gap in game, on the one map they were about to play."""
    fastdl, demos, ini = build_tree(tmp_path, POOL)
    (fastdl / "dod" / "overviews" / "dod_saints2_b5e.bmp").unlink()
    out = generate(tmp_path, fastdl, demos, ini)
    assert not (fastdl / "dod" / "overviews" / PACK).exists()
    assert "dod_saints2_b5e" in out and "omitted" in out
    dod = (fastdl / "dod" / "index.html").read_text(encoding="utf-8")
    assert PACK not in dod


def test_an_incomplete_pool_leaves_a_published_archive_alone(tmp_path):
    """The site links this URL. Replacing a good archive with nothing on a bad read
    would turn a stale pack into a 404, which is the worse of the two failures."""
    fastdl, demos, ini = build_tree(tmp_path, POOL)
    generate(tmp_path, fastdl, demos, ini)
    pack = fastdl / "dod" / "overviews" / PACK
    good = pack.read_bytes()
    (fastdl / "dod" / "overviews" / "dod_thunder2.txt").unlink()
    generate(tmp_path, fastdl, demos, ini)
    assert pack.read_bytes() == good


def test_no_seasonal_block_means_no_archive(tmp_path):
    """Keying on the heading is the mechanism; without it there is no pool to ship."""
    headless = INI.replace("SEASONAL MAPS (S10, in schedule order)", "ALL MAPS")
    fastdl, demos, ini = build_tree(tmp_path, POOL, ini_text=headless)
    out = generate(tmp_path, fastdl, demos, ini)
    assert not (fastdl / "dod" / "overviews" / PACK).exists()
    assert "no seasonal block" in out


def test_a_missing_ini_is_survivable(tmp_path):
    """The job's other 177 pages must not fail because one input moved."""
    fastdl, demos, _ = build_tree(tmp_path, POOL)
    out = generate(tmp_path, fastdl, demos, tmp_path / "nope.ini")
    assert "omitted" in out
    assert (fastdl / "dod" / "index.html").exists()


def test_the_note_names_the_destination_and_the_maps(site):
    note = archive(site[0]).read(NOTE).decode("utf-8")
    assert "dod" + chr(92) + "overviews" in note
    for stem in POOL:
        assert stem in note
    assert "dod_saints2_b3e" not in note
