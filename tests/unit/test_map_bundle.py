"""Unit tests for scripts/build_map_bundle.py.

The end-to-end test drives a stub in place of RESGen so the suite needs no
binary; what it proves is the orchestration -- cwd, overview ordering, line
endings, manifest -- not RESGen's own parsing.
"""

import json
import os
import struct
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts.build_map_bundle import (  # noqa: E402
    CUSTOM_HUD_ICON_MIN,
    bsp_wads,
    custom_icon_entries,
    entity_hud_icon_indices,
    merge_entries,
    rebuild_res,
    stock_paths,
    check_res,
    classify,
    delta,
    main,
    manifest,
    md5_file,
    parse_res_entries,
    read_worldspawn,
    res_version,
    to_crlf,
    to_lf,
)

SHIPPED = (
    "// dod_saints2_b3e.res - created with RESGen v2.0.2.\r\n"
    "// RESGen is made by Jeroen \"ShadowLord\" Bogers,\r\n"
    "// with serveral improvements and additions by Zero3Cool.\r\n"
    "// For more info go to http://resgen.hltools.com\r\n"
    "\r\n"
    "// .res entries (3):\r\n"
    "armory.wad\r\n"
    "models/mapmodels/bell.mdl\r\n"
    "overviews/dod_saints2_b3e.bmp\r\n"
)


def fake_bsp(entities: str) -> bytes:
    """A Half-Life BSP header with a real entity lump and fifteen lump slots."""
    header = 4 + 15 * 8
    ents = entities.encode("latin-1")
    out = bytearray(struct.pack("<i", 30))
    out += struct.pack("<ii", header, len(ents))
    out += struct.pack("<ii", 0, 0) * 14
    assert len(out) == header
    out += ents
    return bytes(out)


class ParseRes(unittest.TestCase):
    def test_header_and_crlf_are_stripped(self):
        self.assertEqual(
            parse_res_entries(SHIPPED),
            ["armory.wad", "models/mapmodels/bell.mdl", "overviews/dod_saints2_b3e.bmp"],
        )

    def test_a_res_with_only_a_header_has_no_entries(self):
        self.assertEqual(parse_res_entries("// nothing here\r\n\r\n"), [])

    def test_version_comes_off_the_header(self):
        self.assertEqual(res_version(SHIPPED), "2.0.2")
        self.assertIsNone(res_version("armory.wad\n"))

    def test_comment_markers_inside_a_path_are_not_a_header(self):
        self.assertEqual(parse_res_entries("sound/a//b.wav\n"), ["sound/a//b.wav"])


class LineEndings(unittest.TestCase):
    def test_crlf_is_idempotent(self):
        once = to_crlf("a\nb\n")
        self.assertEqual(once, "a\r\nb\r\n")
        self.assertEqual(to_crlf(once), once)

    def test_lf_round_trips(self):
        self.assertEqual(to_lf(to_crlf("a\nb\n")), "a\nb\n")

    def test_the_fleet_corpus_is_crlf(self):
        # Every .res on the fleet is CRLF; a converter that dropped the \r would
        # still look right in a terminal, so assert on the bytes.
        self.assertIn("\r\n", SHIPPED)
        self.assertEqual(to_crlf(to_lf(SHIPPED)), SHIPPED)


class Worldspawn(unittest.TestCase):
    def test_wad_and_skyname(self):
        ws = read_worldspawn(fake_bsp(
            '{\n"wad" "dod_saints.wad;armory.wad;"\n"skyname" "grnplsnt"\n}\n'
            '{\n"classname" "info_player_start"\n}\n'))
        self.assertEqual(ws["skyname"], "grnplsnt")
        self.assertEqual(bsp_wads(ws), ["dod_saints.wad", "armory.wad"])

    def test_absent_wad_key_is_no_wads_not_an_error(self):
        # dod_armory_b6 ships exactly this shape -- no "wad" key at all -- and its
        # .res correctly lists no wad.
        ws = read_worldspawn(fake_bsp('{\n"skyname" "grnplsnt"\n}\n'))
        self.assertEqual(bsp_wads(ws), [])

    def test_windows_authored_wad_paths_reduce_to_basenames(self):
        ws = read_worldspawn(fake_bsp('{\n"wad" "C:\\\\halflife\\\\dod\\\\armory.wad;"\n}\n'))
        self.assertEqual(bsp_wads(ws), ["armory.wad"])

    def test_only_worldspawn_is_read(self):
        ws = read_worldspawn(fake_bsp(
            '{\n"skyname" "a"\n}\n{\n"skyname" "b"\n"wad" "late.wad;"\n}\n'))
        self.assertEqual(ws["skyname"], "a")
        self.assertNotIn("wad", ws)

    def test_non_hl_bsp_version_is_rejected(self):
        bad = bytearray(fake_bsp('{\n}\n'))
        bad[:4] = struct.pack("<i", 29)
        with self.assertRaises(ValueError):
            read_worldspawn(bytes(bad))

    def test_lump_running_past_eof_is_rejected(self):
        bad = bytearray(fake_bsp('{\n}\n'))
        bad[8:12] = struct.pack("<i", 1 << 20)
        with self.assertRaises(ValueError):
            read_worldspawn(bytes(bad))


class CheckRes(unittest.TestCase):
    GOOD = ["armory.wad", "models/mapmodels/bell.mdl",
            "overviews/dod_x.bmp", "overviews/dod_x.txt"]

    def test_a_good_list_has_no_problems(self):
        self.assertEqual(check_res(self.GOOD, "dod_x"), [])

    def test_empty_is_a_problem(self):
        self.assertIn("no entries at all", check_res([], "dod_x", require_overviews=False))

    def test_missing_overview_pair_is_named(self):
        got = check_res(["armory.wad"], "dod_x")
        self.assertTrue(any("overviews/dod_x.bmp" in p for p in got))
        self.assertTrue(any("overviews/dod_x.txt" in p for p in got))

    def test_half_an_overview_pair_still_fails(self):
        got = check_res(["overviews/dod_x.txt"], "dod_x")
        self.assertTrue(any("overviews/dod_x.bmp" in p for p in got))

    def test_no_overviews_flag_drops_that_check(self):
        self.assertEqual(check_res(["armory.wad"], "dod_x", require_overviews=False), [])

    def test_backslash_absolute_and_traversal_are_caught(self):
        got = check_res(["models\\a.mdl", "/etc/passwd", "../../a.wav", "z.wad"],
                        "dod_x", require_overviews=False)
        self.assertTrue(any("backslash" in p for p in got))
        self.assertTrue(any("absolute path" in p for p in got))
        self.assertTrue(any("parent traversal" in p for p in got))

    def test_windows_drive_letter_is_absolute(self):
        got = check_res(["C:/dod/a.wad"], "dod_x", require_overviews=False)
        self.assertTrue(any("absolute path" in p for p in got))

    def test_duplicates_are_caught(self):
        got = check_res(["a.wad", "a.wad"], "dod_x", require_overviews=False)
        self.assertTrue(any("duplicate" in p for p in got))

    def test_unsorted_is_caught(self):
        got = check_res(["z.wad", "a.wad"], "dod_x", require_overviews=False)
        self.assertTrue(any("ascending" in p for p in got))


class Delta(unittest.TestCase):
    def test_added_and_removed(self):
        added, removed = delta(["a", "b", "c"], ["b", "c", "d"])
        self.assertEqual((added, removed), (["a"], ["d"]))

    def test_reordering_alone_is_not_a_delta(self):
        self.assertEqual(delta(["a", "b"], ["b", "a"]), ([], []))

    def test_a_dropped_model_shows_up_as_critical(self):
        _, removed = delta(["a.wad"], ["a.wad", "models/mapmodels/bell.mdl"])
        self.assertEqual(classify(removed)["critical"], ["models/mapmodels/bell.mdl"])

    def test_a_dropped_sound_is_not_critical(self):
        self.assertEqual(classify(["sound/ambience/bell.wav"])["critical"], [])


class EndToEnd(unittest.TestCase):
    """Drive main() with a stub standing in for RESGen."""

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        self.src = self.tmp / "src"
        self.src.mkdir()
        (self.src / "dod_x.bsp").write_bytes(
            fake_bsp('{\n"wad" "armory.wad;"\n"skyname" "grnplsnt"\n}\n'))
        self.ov = self.tmp / "ov"
        self.ov.mkdir()
        (self.ov / "dod_x.txt").write_text("global\n", encoding="utf-8")
        (self.ov / "dod_x.bmp").write_bytes(b"BM" + b"\0" * 60)

        # The stub asserts its own cwd is the maps dir, which is the property
        # that makes RESGen find ../overviews.
        body = self.tmp / "stub_resgen.py"
        body.write_text(textwrap.dedent("""
            import os, sys
            name = sys.argv[-1][:-4]
            assert os.path.basename(os.getcwd()) == "maps", os.getcwd()
            assert os.path.isdir(os.path.join("..", "overviews")), "no ../overviews"
            entries = ["armory.wad", "models/mapmodels/bell.mdl"]
            if os.path.exists(os.path.join("..", "overviews", name + ".txt")):
                entries += ["overviews/%s.bmp" % name, "overviews/%s.txt" % name]
            entries.sort()
            body = ("// %s.res - created with RESGen v2.0.3.\\n" % name
                    + "// .res entries (%d):\\n" % len(entries)
                    + "".join(e + "\\n" for e in entries))
            open(name + ".res", "w", newline="\\n").write(body)
        """), encoding="utf-8")

        # build_map_bundle execs the --resgen path directly, as it would a real
        # binary, so the stub needs a launcher the OS can actually exec.
        # A second stub that never lists the overview pair, standing in for a
        # generator run that silently omitted it.
        blind = self.tmp / "stub_blind.py"
        blind.write_text(textwrap.dedent("""
            import sys
            name = sys.argv[-1][:-4]
            entries = ["armory.wad", "models/mapmodels/bell.mdl"]
            body = ("// %s.res - created with RESGen v2.0.3.\\n" % name
                    + "".join(e + "\\n" for e in entries))
            open(name + ".res", "w", newline="\\n").write(body)
        """), encoding="utf-8")

        self.stub = self._launcher("stub", body)
        self.stub_blind = self._launcher("stub_blind", blind)

    def _launcher(self, name, script):
        if os.name == "nt":
            p = self.tmp / (name + ".cmd")
            p.write_text(f'@"{sys.executable}" "{script}" %*\r\n', encoding="utf-8")
        else:
            p = self.tmp / (name + ".sh")
            p.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "$@"\n',
                         encoding="utf-8")
            p.chmod(0o755)
        return p

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _run(self, extra):
        out = self.tmp / "bundle"
        rc = main([str(self.src / "dod_x.bsp"), "--out", str(out),
                   "--resgen", str(self.stub), *extra])
        return rc, out

    def test_bundle_has_all_four_files_and_a_manifest(self):
        rc, out = self._run(["--overviews-from", str(self.ov)])
        self.assertEqual(rc, 0)
        for rel in ("maps/dod_x.bsp", "maps/dod_x.res",
                    "overviews/dod_x.txt", "overviews/dod_x.bmp"):
            self.assertTrue((out / rel).exists(), rel)
        m = json.loads((out / "MANIFEST.json").read_text())
        self.assertEqual(sorted(m["dod_x"]), [
            "maps/dod_x.bsp", "maps/dod_x.res",
            "overviews/dod_x.bmp", "overviews/dod_x.txt"])
        self.assertEqual(m["dod_x"]["maps/dod_x.res"]["md5"],
                         md5_file(out / "maps/dod_x.res"))

    def test_written_res_is_crlf_by_default(self):
        _, out = self._run(["--overviews-from", str(self.ov)])
        self.assertIn(b"\r\n", (out / "maps/dod_x.res").read_bytes())

    def test_lf_is_available_and_leaves_no_cr(self):
        _, out = self._run(["--overviews-from", str(self.ov), "--line-endings", "lf"])
        self.assertNotIn(b"\r", (out / "maps/dod_x.res").read_bytes())

    def test_a_res_that_omits_the_overview_pair_fails_the_check(self):
        # The overview files are on disk; the generator just did not list them.
        # Nothing downstream would report that, so the check has to.
        out = self.tmp / "b2"
        rc = main([str(self.src / "dod_x.bsp"), "--out", str(out),
                   "--resgen", str(self.stub_blind),
                   "--overviews-from", str(self.ov)])
        self.assertEqual(rc, 1)
        self.assertNotIn("overviews/dod_x.bmp",
                         parse_res_entries((out / "maps/dod_x.res").read_text()))

    def _custom_icon_bsp(self):
        """A map whose middle CP uses custom HUD icon indices, as solitude2 does."""
        p = self.src / "dod_c.bsp"
        p.write_bytes(fake_bsp(
            '{\n"wad" "armory.wad;"\n}\n'
            '{\n"classname" "dod_control_point"\n'
            '"point_hud_icon_neutral" "18"\n"point_hud_icon_allies" "19"\n'
            '"point_hud_icon_axis" "20"\n}\n'))
        return p

    def test_custom_hud_icons_are_added_and_the_count_re_emitted(self):
        bsp = self._custom_icon_bsp()
        icons = self.tmp / "sprites" / "obj_icons" / "dod_c"
        icons.mkdir(parents=True)
        for n in ("icon_obj_custom1_allies.spr", "icon_obj_custom1_neutral.spr"):
            (icons / n).write_bytes(b"IDSP")
        out = self.tmp / "bc"
        rc = main([str(bsp), "--out", str(out), "--resgen", str(self.stub),
                   "--no-overviews"])
        self.assertEqual(rc, 0)
        body = (out / "maps/dod_c.res").read_text()
        entries = parse_res_entries(body)
        self.assertIn("sprites/obj_icons/dod_c/icon_obj_custom1_allies.spr", entries)
        self.assertIn("sprites/obj_icons/dod_c/icon_obj_custom1_neutral.spr", entries)
        # RESGen never writes these, so a stale count would be the giveaway.
        self.assertIn("// .res entries (%d):" % len(entries), body)

    def test_custom_icons_with_no_directory_beside_the_bsp_fails_loudly(self):
        # The dod_solitude2 shape: the map needs icons RESGen cannot see and
        # none are there to add. Silence here is what shipped blank flags.
        bsp = self._custom_icon_bsp()
        out = self.tmp / "bd"
        rc = main([str(bsp), "--out", str(out), "--resgen", str(self.stub),
                   "--no-overviews"])
        self.assertEqual(rc, 1)

    def test_no_overviews_flag_makes_that_same_bundle_pass(self):
        out = self.tmp / "b3"
        rc = main([str(self.src / "dod_x.bsp"), "--out", str(out),
                   "--resgen", str(self.stub_blind), "--no-overviews"])
        self.assertEqual(rc, 0)

    def test_missing_overview_source_is_refused_before_resgen_runs(self):
        empty = self.tmp / "empty"
        empty.mkdir()
        out = self.tmp / "b5"
        with self.assertRaises(SystemExit):
            main([str(self.src / "dod_x.bsp"), "--out", str(out),
                  "--resgen", str(self.stub), "--overviews-from", str(empty)])
        self.assertFalse((out / "maps/dod_x.res").exists())

    def test_predecessor_delta_is_reported(self):
        prev = self.tmp / "prev"
        prev.mkdir()
        (prev / "dod_w.res").write_text(
            "// dod_w.res - created with RESGen v2.0.2.\r\n"
            "armory.wad\r\nmodels/mapmodels/gone.mdl\r\n", encoding="utf-8")
        out = self.tmp / "b4"
        rc = main([str(self.src / "dod_x.bsp"), "--out", str(out),
                   "--resgen", str(self.stub), "--overviews-from", str(self.ov),
                   "--compare-against", str(prev), "--predecessor", "dod_w",
                   "--json"])
        self.assertEqual(rc, 0)

    def test_a_second_map_is_added_to_the_manifest_not_swapped_in(self):
        (self.src / "dod_y.bsp").write_bytes(fake_bsp('{\n"skyname" "a"\n}\n'))
        for ext in (".txt", ".bmp"):
            (self.ov / f"dod_y{ext}").write_bytes((self.ov / f"dod_x{ext}").read_bytes())
        out = self.tmp / "b6"
        for m in ("dod_x", "dod_y"):
            main([str(self.src / f"{m}.bsp"), "--out", str(out),
                  "--resgen", str(self.stub), "--overviews-from", str(self.ov)])
        self.assertEqual(sorted(json.loads((out / "MANIFEST.json").read_text())),
                         ["dod_x", "dod_y"])

    def test_nothing_is_written_outside_the_out_directory(self):
        _, out = self._run(["--overviews-from", str(self.ov)])
        self.assertFalse((self.src / "dod_x.res").exists())
        self.assertFalse((self.ov / "dod_x.res").exists())


class ManifestShape(unittest.TestCase):
    def test_absent_files_are_omitted_rather_than_nulled(self):
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        (tmp / "maps").mkdir()
        (tmp / "maps" / "dod_x.res").write_bytes(b"armory.wad\r\n")
        m = manifest(tmp, "dod_x")
        self.assertEqual(list(m["files"]), ["maps/dod_x.res"])



TWO_CPS = (
    '{\n"classname" "worldspawn"\n"wad" "armory.wad;"\n}\n'
    '{\n"classname" "dod_control_point"\n"targetname" "flagchurch"\n'
    '"point_hud_icon_neutral" "18"\n"point_hud_icon_allies" "19"\n'
    '"point_hud_icon_axis" "20"\n}\n'
    '{\n"classname" "dod_control_point"\n"targetname" "flagallied"\n'
    '"point_hud_icon_neutral" "0"\n"point_hud_icon_allies" "1"\n'
    '"point_hud_icon_axis" "2"\n}\n'
)


class EntityHudIcons(unittest.TestCase):
    def test_indices_come_from_the_whole_lump_not_just_worldspawn(self):
        bsp = fake_bsp(TWO_CPS)
        self.assertEqual(entity_hud_icon_indices(bsp), {0, 1, 2, 18, 19, 20})
        # Why this cannot reuse read_worldspawn, asserted instead of described.
        self.assertNotIn("point_hud_icon_neutral", read_worldspawn(bsp))

    def test_a_map_with_only_stock_indices_wants_nothing(self):
        bsp = fake_bsp('{\n"classname" "worldspawn"\n}\n'
                       '{\n"point_hud_icon_axis" "5"\n}\n')
        self.assertEqual(
            [i for i in entity_hud_icon_indices(bsp) if i >= CUSTOM_HUD_ICON_MIN],
            [],
        )

    def test_a_non_integer_value_is_skipped_rather_than_fatal(self):
        bsp = fake_bsp('{\n"point_hud_icon_axis" "notanumber"\n'
                       '"point_hud_icon_allies" "21"\n}\n')
        self.assertEqual(entity_hud_icon_indices(bsp), {21})


class CustomIconEntries(unittest.TestCase):
    def test_an_absent_directory_is_empty_not_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(custom_icon_entries(Path(d), "dod_nope"), [])

    def test_files_are_listed_game_relative_sorted_and_without_subdirs(self):
        with tempfile.TemporaryDirectory() as d:
            icons = Path(d) / "sprites" / "obj_icons" / "dod_x"
            icons.mkdir(parents=True)
            for n in ("b.spr", "a.spr"):
                (icons / n).write_bytes(b"x")
            (icons / "sub").mkdir()
            self.assertEqual(
                custom_icon_entries(Path(d), "dod_x"),
                ["sprites/obj_icons/dod_x/a.spr", "sprites/obj_icons/dod_x/b.spr"],
            )


class StockPaths(unittest.TestCase):
    def test_the_depot_list_covers_saints_and_not_solitude(self):
        # Why dod_saints needs nothing and dod_solitude2 does, pinned against
        # the depot manifest rather than remembered: saints is a stock map and
        # every client already has its nine icons.
        stock = stock_paths(REPO / "scripts")
        self.assertEqual(sum(1 for p in stock if "obj_icons/dod_saints/" in p), 9)
        self.assertEqual(sum(1 for p in stock if "solitude" in p), 0)


class MergeEntries(unittest.TestCase):
    def test_the_sort_matches_resgens_case_insensitive_order(self):
        self.assertEqual(
            merge_entries(["sound/m.wav", "sound/u.wav"], ["sound/Opera.wav"]),
            ["sound/m.wav", "sound/Opera.wav", "sound/u.wav"],
        )

    def test_an_entry_already_present_in_another_case_is_not_duplicated(self):
        self.assertEqual(merge_entries(["sprites/A.spr"], ["sprites/a.spr"]),
                         ["sprites/A.spr"])


class RebuildRes(unittest.TestCase):
    HEAD = ("// dod_x.res - created with RESGen v2.0.2.\n"
            "// For more info go to http://resgen.hltools.com\n"
            "\n"
            "// .res entries (1):\n"
            "armory.wad\n")

    def test_the_count_is_re_emitted_with_the_list(self):
        out = rebuild_res(self.HEAD, ["armory.wad", "sprites/x.spr"])
        self.assertIn("// .res entries (2):", out)
        self.assertNotIn("(1):", out)
        self.assertEqual(parse_res_entries(out), ["armory.wad", "sprites/x.spr"])

    def test_the_resgen_header_survives(self):
        self.assertEqual(res_version(rebuild_res(self.HEAD, ["armory.wad"])), "2.0.2")


class CheckResOrdering(unittest.TestCase):
    def test_a_mixed_case_list_in_resgen_order_passes(self):
        # The fleet's own dod_saints.res failed this check on
        # sound/ambience/Opera.wav while RESGen had written it in its own,
        # case-insensitive, order.
        entries = ["sound/ambience/mill.wav", "sound/ambience/Opera.wav",
                   "sound/ambience/usareasecure.wav"]
        self.assertEqual(
            [p for p in check_res(entries, "x", require_overviews=False)
             if "ascending" in p],
            [],
        )

    def test_a_genuinely_unsorted_list_still_fails(self):
        problems = check_res(["b.wav", "a.wav"], "x", require_overviews=False)
        self.assertTrue(any("ascending" in p for p in problems))

if __name__ == "__main__":
    unittest.main()
