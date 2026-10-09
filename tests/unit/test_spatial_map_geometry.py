"""World-to-overview projection: the origin lands on the image centre, the
inverse round-trips, malformed overviews fail closed, and the derived matrices
reproduce the ones the website ships -- which is the regression that proves
replacing the hand-maintained table is a no-op.

Both sides of that equality are now READ, not retyped. The generator's inputs
come from `config/analytics/spatial_maps/`, and the expected output comes from
a byte-for-byte copy of the website's own fixture under
`tests/fixtures/site_map_geometry/`, pinned by sha256 in its `PIN.json`.

Until 2026-10-08 the expected matrices were hand-copied literals in this file,
commented "Hand-derived", while a comment named the real source three lines
above. So the test compared the generator against a transcription of the site's
table rather than the table: all three copies could drift together, and a
mistyped matrix was invisible. A tripwire that restates the contract is not
checking it.

What the vendored copy can and cannot prove is spelled out in `PIN.json`, and
the short version is that this repo is public while `searse/keep-the-prac` is
private, so no job here can read the upstream path. Drift in OUR table is caught
at PR time; drift introduced upstream is the one residual hole and it is named
rather than papered over. The deployable table in `config/analytics/spatial_maps/`
stays authoritative over the payload either way.

Equality is not endorsement, and it reads like one. `registry.json` marks every
review flag true for `dod_anzio` only. `dod_thunder2` ships a config with its
review flags at their false defaults, so there the equality proves the shipped
table matches the generator -- NOT that either is right for that map.
`dod_lennon5_b1` is shipped by the site with no config here; it is deferred by
operator ruling and asserted as shipped-but-unconfigured, never silently skipped.
"""
import hashlib
import json
import math
import unittest
from pathlib import Path

from scripts.make_overview_descriptor import project as descriptor_project
from scripts.spatial_map_geometry import (
    SCHEME, UnsupportedOverview, geometry_version, overview_matrices, project)

REPO = Path(__file__).resolve().parents[2]
SPATIAL_MAPS = REPO / "config/analytics/spatial_maps"
SITE_FIXTURE_DIR = REPO / "tests/fixtures/site_map_geometry"

# The site rounds pixel_to_world to about twelve significant figures, so an exact
# compare is impossible; world_to_pixel ships unrounded and agrees far tighter.
# Anything a wrong overview block produces is orders of magnitude coarser.
MATRIX_REL_TOL = 1e-9
MATRIX_ABS_TOL = 1e-9

MATRIX_KEYS = ("world_to_pixel", "pixel_to_world")


def _read_pin():
    return json.loads((SITE_FIXTURE_DIR / "PIN.json").read_text(encoding="utf-8"))


def _read_shipped_bytes():
    # Normalized, so a clone with core.autocrlf=true cannot fail the pin for a
    # line ending nobody changed.
    return (SITE_FIXTURE_DIR / "map-geometry.json").read_bytes().replace(b"\r\n", b"\n")


PIN = _read_pin()
SHIPPED = json.loads(_read_shipped_bytes().decode("utf-8"))

# PIN.json carries one coverage note per map the site ships at the pinned blob,
# so the expected set has a single home and travels with a refresh.
SHIPPED_MAPS = set(PIN["coverage_caveat"])


def committed_overviews():
    """Every overview block this repo actually deploys, keyed by map name."""
    found = {}
    for path in sorted(SPATIAL_MAPS.glob("dod_*.json")):
        config = json.loads(path.read_text(encoding="utf-8-sig"))
        if config.get("overview"):
            found[str(config["map_name"]).lower()] = config["overview"]
    return found


COMMITTED = committed_overviews()
# Intersected against what the file actually holds, not against PIN.json's record
# of it, so a shrinking fixture fails a named assertion below instead of raising
# KeyError out of the middle of a comparison.
COMPARABLE = sorted(set(COMMITTED) & set(SHIPPED))
ANZIO = COMMITTED.get("dod_anzio")


class VendoredReference(unittest.TestCase):
    """The reference copy cannot be edited into agreement without saying so."""

    def test_the_vendored_copy_matches_its_sha256_pin(self):
        raw = _read_shipped_bytes()
        self.assertEqual(
            hashlib.sha256(raw).hexdigest(), PIN["sha256_lf"],
            "tests/fixtures/site_map_geometry/map-geometry.json no longer hashes to "
            "PIN.json's sha256_lf. Either the copy was edited -- restore it -- or it "
            "was refreshed from upstream without updating the pin in the same commit. "
            "See PIN.json 'refresh'.")

    def test_the_pin_records_the_byte_count_it_vendored(self):
        self.assertEqual(len(_read_shipped_bytes()), PIN["bytes"])

    def test_the_pin_names_its_upstream(self):
        self.assertEqual(PIN["upstream_repo"], "searse/keep-the-prac")
        self.assertEqual(PIN["upstream_path"],
                         "src/features/public-match-report/fixtures/map-geometry.json")
        self.assertRegex(PIN["upstream_blob"], r"^[0-9a-f]{40}$")
        self.assertRegex(PIN["upstream_commit"], r"^[0-9a-f]{40}$")


class NonVacuity(unittest.TestCase):
    """A reader that silently finds nothing would pass every comparison below."""

    def test_the_shipped_table_was_found_and_parsed(self):
        self.assertTrue(SHIPPED, f"no shipped descriptors parsed from {SITE_FIXTURE_DIR}")
        self.assertEqual(set(SHIPPED), SHIPPED_MAPS,
                         "the vendored table no longer holds the maps PIN.json records")

    def test_every_shipped_descriptor_carries_both_matrices(self):
        for map_name, descriptor in sorted(SHIPPED.items()):
            for key in MATRIX_KEYS:
                matrix = descriptor.get(key)
                self.assertIsInstance(matrix, list, f"{map_name}.{key}")
                self.assertEqual([len(row) for row in matrix], [3, 3, 3],
                                 f"{map_name}.{key} is not 3x3")

    def test_this_repo_has_overview_blocks_to_compare(self):
        self.assertTrue(COMMITTED,
                        f"no spatial map config with an overview under {SPATIAL_MAPS}")

    def test_the_comparison_covers_every_committed_overview(self):
        self.assertTrue(COMPARABLE, "no committed config covers a map the website ships")
        self.assertEqual(set(COMPARABLE), set(COMMITTED),
                         "a map is deployed here that the website's table does not ship, so "
                         "the equality below silently stops covering it")

    def test_a_map_the_site_ships_without_a_config_here_is_named_not_skipped(self):
        """Deferred by operator ruling 2026-10-08: the generator cannot derive an
        overview without ktp_flag_positions rows, and no capture exists."""
        deferred = SHIPPED_MAPS - set(COMMITTED)
        self.assertEqual(deferred, {"dod_lennon5_b1"},
                         "the shipped-but-unconfigured set moved. If a config was added, drop "
                         "the map from here so it is compared; if the site dropped a map, "
                         "refresh the pin.")


class RegistryPending(unittest.TestCase):
    """The pool maps this equality does NOT cover are named here, so they are
    pending rather than silently absent. Each assertion fails when a map gains a
    config or a review, which is the point: arriving work has to be noticed."""

    REVIEW_FLAGS = ("overview_transform_reviewed", "flag_geometry_reviewed",
                    "objective_topology_reviewed", "bot_waypoints_verified")

    def registry(self):
        path = SPATIAL_MAPS / "registry.json"
        registry = json.loads(path.read_text(encoding="utf-8-sig"))
        self.assertTrue(registry.get("maps"), f"no maps in {path}")
        return registry

    def reviewed(self, entry, registry):
        defaults = registry.get("defaults", {})
        return {flag for flag in self.REVIEW_FLAGS
                if entry.get(flag, defaults.get(flag, False))}

    def test_the_maps_without_a_config_are_named_as_pending(self):
        registry = self.registry()
        pending = {name for name, entry in registry["maps"].items()
                   if not entry.get("spatial_config")}
        self.assertEqual(
            pending,
            {"dod_lennon5_b1", "dod_armory_b6", "dod_harrington", "dod_saints2_b3e"},
            "the set of pool maps with no spatial_config moved. A map that gained one "
            "belongs in the equality above; a map that lost one needs saying out loud.")
        for name in sorted(pending):
            self.assertEqual(self.reviewed(registry["maps"][name], registry), set(),
                             f"{name} has no config yet reports a review")

    def test_the_configured_maps_are_the_ones_compared(self):
        registry = self.registry()
        configured = {name for name, entry in registry["maps"].items()
                      if entry.get("spatial_config")}
        self.assertEqual(configured, set(COMPARABLE),
                         "registry.json and the comparison disagree about which maps have "
                         "an overview to check")

    def test_only_anzio_is_reviewed_so_equality_is_not_read_as_a_review(self):
        """Pins the caveat instead of leaving it in prose: on dod_thunder2 the
        equality proves the shipped table matches the generator, not that either is
        right for that map. If that map is reviewed later, this test says so."""
        registry = self.registry()
        fully_reviewed = {name for name, entry in registry["maps"].items()
                          if self.reviewed(entry, registry) == set(self.REVIEW_FLAGS)}
        self.assertEqual(fully_reviewed, {"dod_anzio"})
        self.assertEqual(self.reviewed(registry["maps"]["dod_thunder2"], registry), set())


class ShippedTable(unittest.TestCase):

    def assertMatrixEqual(self, derived, expected, label):
        for row in range(3):
            for col in range(3):
                got, want = derived[row][col], expected[row][col]
                self.assertTrue(
                    math.isclose(got, want, rel_tol=MATRIX_REL_TOL, abs_tol=MATRIX_ABS_TOL),
                    f"{label}[{row}][{col}]: derived {got!r} != shipped {want!r}")

    def test_the_derivation_reproduces_the_shipped_table(self):
        """The equality the generator exists to prove: deriving from the committed
        overview block yields the matrices the website already draws with.

        It does not certify either side for an unreviewed map -- see the module
        docstring and PIN.json's coverage_caveat."""
        for map_name in COMPARABLE:
            derived = overview_matrices(map_name, COMMITTED[map_name])
            shipped = SHIPPED[map_name]
            for key in MATRIX_KEYS:
                self.assertMatrixEqual(derived[key], shipped[key], f"{map_name}.{key}")

    def test_the_derived_dimensions_match_the_shipped_ones(self):
        for map_name in COMPARABLE:
            derived = overview_matrices(map_name, COMMITTED[map_name])
            self.assertEqual(derived["dimensions"], SHIPPED[map_name]["dimensions"], map_name)

    def test_version_strings_are_not_compared_because_the_shipped_ones_are_opaque(self):
        """The site's `geometry_version` carries this scheme's prefix and a digest
        nothing in either repo computes, so it is a label that reads like a derived
        identity. The prefix is all it can support; the matrices are the contract."""
        for map_name in COMPARABLE:
            self.assertTrue(SHIPPED[map_name]["geometry_version"].startswith(f"{SCHEME}-"),
                            map_name)


class Geometry(unittest.TestCase):
    def test_map_origin_lands_on_the_image_centre(self):
        for map_name, overview in sorted(COMMITTED.items()):
            geometry = overview_matrices(map_name, overview)
            px, py = project(geometry["world_to_pixel"],
                             overview["origin_x"], overview["origin_y"])
            self.assertAlmostEqual(px, overview["width"] / 2.0, places=9, msg=map_name)
            self.assertAlmostEqual(py, overview["height"] / 2.0, places=9, msg=map_name)

    def test_inverse_round_trips(self):
        points = [(0.0, 0.0), (-1495.0, -326.0), (2048.5, -3071.25), (307.06, 372.72)]
        for map_name, overview in sorted(COMMITTED.items()):
            geometry = overview_matrices(map_name, overview)
            for world_x, world_y in points:
                px, py = project(geometry["world_to_pixel"], world_x, world_y)
                back_x, back_y = project(geometry["pixel_to_world"], px, py)
                self.assertAlmostEqual(back_x, world_x, places=9, msg=map_name)
                self.assertAlmostEqual(back_y, world_y, places=9, msg=map_name)

    def test_scale_is_zoom_over_eight_world_units(self):
        geometry = overview_matrices("dod_anzio", ANZIO)
        self.assertAlmostEqual(-geometry["world_to_pixel"][0][1], ANZIO["zoom"] / 8.0, places=12)

    def test_source_block_preserves_the_raw_parse(self):
        overview = COMMITTED["dod_thunder2"]
        geometry = overview_matrices("dod_thunder2", overview)
        self.assertEqual(geometry["source"],
                         {"zoom": overview["zoom"], "origin_x": overview["origin_x"],
                          "origin_y": overview["origin_y"], "rotated": False})
        self.assertEqual(geometry["dimensions"],
                         {"width": overview["width"], "height": overview["height"]})
        self.assertEqual(geometry["scheme"], SCHEME)


class Version(unittest.TestCase):
    def facts(self, **overrides):
        base = dict(scheme=SCHEME, map_name="dod_anzio", zoom=float(ANZIO["zoom"]),
                    origin_x=float(ANZIO["origin_x"]), origin_y=float(ANZIO["origin_y"]),
                    rotated=False, width=int(ANZIO["width"]), height=int(ANZIO["height"]))
        base.update(overrides)
        return base

    def test_is_stable_across_runs(self):
        self.assertEqual(geometry_version(self.facts()), geometry_version(self.facts()))

    def test_carries_the_scheme_and_a_digest(self):
        version = geometry_version(self.facts())
        self.assertTrue(version.startswith(f"{SCHEME}-"), version)
        self.assertEqual(len(version), len(SCHEME) + 1 + 12)

    def test_every_input_field_changes_it(self):
        baseline = geometry_version(self.facts())
        for field, value in (("map_name", "dod_thunder2"), ("zoom", 1.12),
                             ("origin_x", 307.07), ("origin_y", 372.73),
                             ("rotated", True), ("width", 1025), ("height", 769)):
            self.assertNotEqual(geometry_version(self.facts(**{field: value})), baseline,
                                msg=field)

    def test_matches_the_matrices_it_is_derived_with(self):
        geometry = overview_matrices("dod_anzio", ANZIO)
        self.assertEqual(geometry["geometry_version"], geometry_version(self.facts()))


class Rotated(unittest.TestCase):
    """ROTATED 1 was refused here as unmeasured until 2026-09-15. It is now read
    off CHudSpectator::DrawOverviewLayer and pinned against the descriptor tool."""

    def test_a_rotated_overview_projects_along_world_x(self):
        overview = dict(ANZIO, rotated=True)
        geometry = overview_matrices("dod_saints2_b3e", overview)
        self.assertTrue(geometry["source"]["rotated"])
        for world_x, world_y in ((0.0, 0.0), (1234.5, -987.25), (-3000.0, 2500.0)):
            derived = project(geometry["world_to_pixel"], world_x, world_y)
            expected = descriptor_project(world_x, world_y, overview["zoom"],
                                          overview["origin_x"], overview["origin_y"], 1,
                                          overview["width"], overview["height"])
            self.assertAlmostEqual(derived[0], expected[0], places=9)
            self.assertAlmostEqual(derived[1], expected[1], places=9)

    def test_the_two_conventions_are_not_the_same_projection(self):
        # Guards the refusal from having been lifted into a no-op: if these agreed,
        # the flag would be decorative and the finding vacuous.
        flat = overview_matrices("dod_x", dict(ANZIO, rotated=False))
        turned = overview_matrices("dod_x", dict(ANZIO, rotated=True))
        self.assertNotEqual(flat["world_to_pixel"], turned["world_to_pixel"])
        self.assertNotEqual(flat["geometry_version"], turned["geometry_version"])

    def test_a_rotated_projection_round_trips(self):
        geometry = overview_matrices("dod_x", dict(ANZIO, rotated=True))
        for world_x, world_y in ((0.0, 0.0), (-1495.0, -326.0), (2048.5, -3071.25)):
            px, py = project(geometry["world_to_pixel"], world_x, world_y)
            back_x, back_y = project(geometry["pixel_to_world"], px, py)
            self.assertAlmostEqual(back_x, world_x, places=6)
            self.assertAlmostEqual(back_y, world_y, places=6)

    def test_a_rotated_map_origin_still_lands_on_the_image_centre(self):
        overview = dict(ANZIO, rotated=True)
        geometry = overview_matrices("dod_x", overview)
        px, py = project(geometry["world_to_pixel"], overview["origin_x"], overview["origin_y"])
        self.assertAlmostEqual(px, overview["width"] / 2.0, places=9)
        self.assertAlmostEqual(py, overview["height"] / 2.0, places=9)

    def test_any_truthy_rotated_value_is_read_as_rotated(self):
        for value in (1, True, "1"):
            geometry = overview_matrices("dod_x", dict(ANZIO, rotated=value))
            self.assertTrue(geometry["source"]["rotated"], value)


class FailClosed(unittest.TestCase):
    def test_missing_fields_are_named(self):
        for field in ("zoom", "origin_x", "origin_y", "width", "height"):
            overview = dict(ANZIO)
            overview.pop(field)
            with self.assertRaises(UnsupportedOverview) as caught:
                overview_matrices("dod_x", overview)
            self.assertIn(field, str(caught.exception))

    def test_a_zero_or_negative_zoom_is_refused(self):
        for zoom in (0.0, -1.11):
            with self.assertRaises(UnsupportedOverview):
                overview_matrices("dod_x", dict(ANZIO, zoom=zoom))

    def test_an_empty_bitmap_is_refused(self):
        with self.assertRaises(UnsupportedOverview):
            overview_matrices("dod_x", dict(ANZIO, width=0))


if __name__ == "__main__":
    unittest.main()
