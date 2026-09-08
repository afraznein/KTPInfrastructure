"""The sanitizer's forbidden-key list may grow, never shrink.

`FORBIDDEN_KEY_PARTS` is the only thing stopping identity and positional keys
reaching the public report DTO, and it is a plain tuple any PR can edit. The
guard was silently shortened once (KTPInfrastructure#265 dropped "position" in
the same patch that added the block needing it gone), so removals get their own
test rather than a reviewer's attention.

Adding an entry is expected and passes. Removing or renaming one fails here.
"""
import unittest

from scripts.analytics_report_dto import FORBIDDEN_KEY_PARTS, assert_sanitized

# Ratcheted baseline, 2026-09-07. Extend when the guard grows; never trim to
# make a red test pass — a removal is the thing this file exists to catch.
BASELINE = frozenset({
    "player_id", "steam_id", "steamid", "event_id", "unix", "pos_",
    "private", "life_", "timeline", "break_reel",
})


class ForbiddenKeyPartsLock(unittest.TestCase):
    def test_baseline_entries_all_survive(self):
        missing = sorted(BASELINE - set(FORBIDDEN_KEY_PARTS))
        self.assertEqual(
            missing, [],
            "FORBIDDEN_KEY_PARTS lost {}. The sanitizer no longer blocks these "
            "key names in the public DTO. If the removal is deliberate it needs "
            "a second maintainer's sign-off and a matching edit to BASELINE "
            "here — do not trim BASELINE to go green.".format(missing))

    def test_growth_is_allowed(self):
        # States the direction of the ratchet, so a reader does not "fix" the
        # test above into an equality assertion the next time an entry is added.
        self.assertTrue(BASELINE.issubset(set(FORBIDDEN_KEY_PARTS)))

    def test_entries_are_lowercase_and_nonempty(self):
        # The scan at analytics_report_dto.py lowercases each key before the
        # substring test, so an uppercase entry can never match anything.
        for part in FORBIDDEN_KEY_PARTS:
            self.assertTrue(part, "empty entry matches every key")
            self.assertEqual(part, part.lower(), "unmatchable entry: " + part)

    def test_the_guard_actually_rejects_every_baseline_key(self):
        # Control: proves each entry is wired to live behaviour, so the lock
        # above defends a real check rather than an unused constant.
        # assert_sanitized() is the scan; sanitize_report() is a whitelist
        # builder that would silently DROP an unknown key and prove nothing.
        for part in sorted(BASELINE):
            with self.assertRaises(ValueError, msg="not rejected: " + part):
                assert_sanitized({part + "x": 1})

    def test_control_a_benign_key_passes(self):
        # Negative control: without it, an assert_sanitized() that raised on
        # everything would make the test above pass vacuously.
        assert_sanitized({"map_name": "dod_anzio", "kills": 3})


if __name__ == "__main__":
    unittest.main()
