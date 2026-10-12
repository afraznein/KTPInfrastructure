"""The emitter that turns the deployable spatial configs back into the site's
`map-geometry.json`, and the pin field that decides how strict the equality is.

`test_spatial_map_geometry.py` proves the derivation reproduces the shipped
table under a relative tolerance, because the shipped `pixel_to_world` is
hand-rounded to about twelve significant figures. That proof is one-way: it
says the generator agrees, and it cannot make the site's file be the
generator's output. This file covers the other direction.

Two failure shapes it exists to stop, both of which look like progress:

Minting a descriptor. `registry.json` records `overview_transform_reviewed`
for `dod_anzio` alone -- absent, not false, on the other five -- while the
site's table marks all three of its maps `technical_validation: passed`. A
generator that wrote whole descriptors would have to invent that field, which
turns a derivation into a review claim for maps nothing has reviewed. So the
emitter owns four geometry fields and carries every other key through verbatim,
and refuses outright to add a map the base table does not already hold.

A silently stale gate. Regenerating the site's table is an upstream hand-edit,
which `PIN.json`'s own `drift_directions` records as NOT CAUGHT -- the vendored
copy then describes bytes the site no longer ships and the suite stays green.
`equality_grade` closes that: `--refresh-pin` sets it by comparing, and the
exact-equality leg below is live only at `generated`. So the pin move upgrades
the check rather than just recording itself.
"""
import json
import unittest
from collections import OrderedDict
from pathlib import Path

from scripts import emit_site_map_geometry as emitter
from scripts.spatial_map_geometry import overview_matrices

REPO = Path(__file__).resolve().parents[2]

PIN = json.loads(emitter.PIN.read_text(encoding="utf-8"))
VENDORED_BYTES = emitter.VENDORED.read_bytes().replace(b"\r\n", b"\n")
VENDORED = json.loads(VENDORED_BYTES.decode("utf-8"), object_pairs_hook=OrderedDict)
GENERATED_BYTES, REPORT = emitter.emit()
GENERATED = json.loads(GENERATED_BYTES.decode("utf-8"), object_pairs_hook=OrderedDict)
GRADES = ("rounded", "generated")


class NonVacuity(unittest.TestCase):
    """Every assertion below compares two tables. An empty one passes them all."""

    def test_the_emitter_produced_a_table(self):
        self.assertTrue(GENERATED, "the emitter returned an empty table")
        self.assertGreaterEqual(len(GENERATED), 3)

    def test_the_vendored_base_was_read(self):
        self.assertTrue(VENDORED, f"nothing parsed from {emitter.VENDORED}")

    def test_something_was_actually_generated(self):
        self.assertTrue(REPORT["generated"],
                        "no map has a spatial_config, so the emitter rewrote nothing "
                        "and every equality here is vacuous")
        self.assertEqual(set(REPORT["generated"]), {"dod_anzio", "dod_thunder2"},
                         "the configured set moved -- a map gained or lost a "
                         "spatial_config and this file has to say so")

    def test_at_least_one_field_still_differs_from_the_hand_typed_table(self):
        """While the grade is `rounded` the emitter MUST disagree with the site's
        bytes. If it agreed, the regeneration this tool exists for already landed
        and the grade is the thing that is stale."""
        if PIN["equality_grade"] == "rounded":
            self.assertTrue(REPORT["changed_fields"],
                            "the emitter reproduces the vendored bytes exactly, so "
                            "equality_grade should be 'generated'. Re-run "
                            "--refresh-pin.")


class GeneratorOwnsGeometryOnly(unittest.TestCase):

    def test_the_review_field_is_carried_through_verbatim(self):
        """The one field the site keeps that this generator has no source for."""
        self.assertIn("technical_validation", REPORT["carried_through"])
        for name, descriptor in VENDORED.items():
            if "technical_validation" not in descriptor:
                continue
            self.assertEqual(GENERATED[name]["technical_validation"],
                             descriptor["technical_validation"],
                             f"{name}: the emitter changed a review claim")

    def test_no_key_is_added_or_dropped_from_any_descriptor(self):
        for name, descriptor in VENDORED.items():
            self.assertEqual(list(GENERATED[name]), list(descriptor),
                             f"{name}: descriptor keys or their order moved, which "
                             "makes the site diff larger than the numbers")

    def test_no_map_is_added_or_dropped(self):
        self.assertEqual(list(GENERATED), list(VENDORED))

    def test_a_configured_map_absent_from_the_base_is_refused(self):
        """The guard that stops the generator minting `technical_validation` for
        the five maps registry.json records no review for."""
        base = OrderedDict(
            (name, descriptor) for name, descriptor in VENDORED.items()
            if name != "dod_thunder2")
        overviews = emitter.configured_maps(
            json.loads(emitter.REGISTRY.read_text(encoding="utf-8-sig")))
        with self.assertRaises(emitter.UnbackedDescriptor) as caught:
            emitter.build_table(base, overviews)
        self.assertIn("dod_thunder2", str(caught.exception))
        self.assertIn("technical_validation", str(caught.exception))

    def test_a_base_descriptor_missing_a_geometry_field_is_refused(self):
        base = OrderedDict(
            (name, OrderedDict(
                (key, value) for key, value in descriptor.items()
                if not (name == "dod_anzio" and key == "pixel_to_world")))
            for name, descriptor in VENDORED.items())
        overviews = emitter.configured_maps(
            json.loads(emitter.REGISTRY.read_text(encoding="utf-8-sig")))
        with self.assertRaises(emitter.UnbackedDescriptor) as caught:
            emitter.build_table(base, overviews)
        self.assertIn("pixel_to_world", str(caught.exception))


class DeferredMap(unittest.TestCase):

    def test_the_unconfigured_map_is_reported_and_left_untouched(self):
        """Operator ruling 2026-10-08: `dod_lennon5_b1` follows when its capture
        exists. The generator cannot derive an overview without flag positions."""
        self.assertEqual(REPORT["deferred"], ["dod_lennon5_b1"])
        self.assertEqual(GENERATED["dod_lennon5_b1"], VENDORED["dod_lennon5_b1"],
                         "the deferred map's descriptor was rewritten")


class EmittedShape(unittest.TestCase):
    """The site file's own formatting, so regenerating it diffs as numbers."""

    def test_the_emitted_bytes_match_the_vendored_formatting(self):
        self.assertEqual(GENERATED_BYTES.count(b"\r\n"), 0, "emitted CRLF")
        self.assertFalse(GENERATED_BYTES.endswith(b"\n"),
                         "upstream's file has no trailing newline")
        self.assertEqual(GENERATED_BYTES.count(b"\n"), VENDORED_BYTES.count(b"\n"),
                         "the emitted line count differs from upstream's, so the "
                         "diff would be the whole file rather than the numbers")
        self.assertTrue(GENERATED_BYTES.splitlines()[1].startswith(b' "'),
                        "indent is not one space")

    def test_the_emitted_matrices_round_trip_through_json(self):
        for name in REPORT["generated"]:
            derived = overview_matrices(
                name, emitter.configured_maps(json.loads(
                    emitter.REGISTRY.read_text(encoding="utf-8-sig")))[name])
            for field in ("world_to_pixel", "pixel_to_world"):
                self.assertEqual(GENERATED[name][field], derived[field],
                                 f"{name}.{field} lost precision through JSON")

    def test_emitting_from_the_emitted_table_is_idempotent(self):
        overviews = emitter.configured_maps(
            json.loads(emitter.REGISTRY.read_text(encoding="utf-8-sig")))
        again, report = emitter.build_table(GENERATED, overviews)
        self.assertEqual(emitter.serialize(again), GENERATED_BYTES)
        self.assertEqual(report["changed_fields"], {},
                         "a second pass still moves fields, so the emitter is not "
                         "a fixed point and the exact gate could never hold")


class EqualityGrade(unittest.TestCase):

    def test_the_pin_declares_a_grade_this_file_knows(self):
        self.assertIn(PIN.get("equality_grade"), GRADES,
                      f"PIN.json equality_grade must be one of {GRADES}")

    def test_at_grade_generated_the_equality_is_exact(self):
        """The leg the pin refresh turns on. At `rounded` it cannot run, and the
        tolerance test in test_spatial_map_geometry.py is the gate instead."""
        if PIN["equality_grade"] != "generated":
            self.skipTest("equality_grade is 'rounded': upstream still ships the "
                          "hand-typed table")
        self.assertEqual(GENERATED_BYTES, VENDORED_BYTES,
                         "equality_grade says upstream is generated output, but the "
                         "vendored bytes are not what this emitter produces. Either "
                         "upstream was hand-edited or the pin was refreshed from the "
                         "wrong commit.")

    def test_the_grade_is_not_a_claim_the_refresh_can_skip(self):
        """`refresh_pin` must decide the grade from a comparison. A refresh that
        copies a human's word for it is the staleness this field exists to stop."""
        source = (REPO / "scripts/emit_site_map_geometry.py").read_text(
            encoding="utf-8")
        body = source.split("def refresh_pin", 1)[1].split("\ndef ", 1)[0]
        self.assertIn("equality_grade", body)
        self.assertIn("generated == normalized", body)


if __name__ == "__main__":
    unittest.main()
