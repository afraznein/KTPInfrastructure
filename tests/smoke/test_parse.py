"""Unit tests for parse.py — runs without booting a server.

Test data uses the EXACT fixed-width formats from KTPAMXX `srvcmd.cpp`:
  modules: ` [%2d] %-23.22s %-11.10s %-20.19s %-11.10s\n`
  plugins: ` [%3d] %-3i %-23.22s %-11.10s %-17.16s %-32.31s %-12.11s %-9.8s\n`

Run from KTPInfrastructure root:
    python -m unittest tests.smoke.test_parse
"""

from __future__ import annotations

import unittest

from .parse import (
    matches_truncated,
    normalise_module_name,
    normalise_plugin_name,
    parse_modules,
    parse_plugins,
)


def _module_row(idx: int, name: str, version: str, author: str, status: str) -> str:
    """Format one row matching ` [%2d] %-23.22s %-11.10s %-20.19s %-11.10s`.

    Note the literal single space between each %-Ns format specifier in the
    C source — these spaces are the column delimiters our parser keys off.
    """
    return (
        f" [{idx:2d}] "
        f"{name[:22]:<23.22} "
        f"{version[:10]:<11.10} "
        f"{author[:19]:<20.19} "
        f"{status[:10]:<11.10}"
    )


def _plugin_row(
    idx: int,
    plugin_id: int,
    name: str,
    version: str,
    author: str,
    url: str,
    filename: str,
    status: str,
) -> str:
    """Format one row matching the plugin format string verbatim.

    Source: ` [%3d] %-3i %-23.22s %-11.10s %-17.16s %-32.31s %-12.11s %-9.8s\n`
    Each specifier is separated by exactly one literal space.
    """
    return (
        f" [{idx:3d}] "
        f"{plugin_id:<3d} "
        f"{name[:22]:<23.22} "
        f"{version[:10]:<11.10} "
        f"{author[:16]:<17.16} "
        f"{url[:31]:<32.31} "
        f"{filename[:11]:<12.11} "
        f"{status[:8]:<9.8}"
    )


MODULES_OUTPUT = "\n".join([
    "Currently loaded modules:",
    "       name             version     author             status",
    _module_row(1, "Fun", "1.10.0", "AMXX Dev Team", "running"),
    _module_row(2, "Engine", "1.10.0", "AMXX Dev Team", "running"),
    _module_row(3, "FakeMeta", "1.10.0", "AMXX Dev Team", "running"),
    _module_row(4, "amxxcurl", "1.3.8-ktp", "KTP Team", "running"),
    _module_row(5, "reapi", "5.29.0", "KTP Team", "running"),
    _module_row(6, "dodx", "2.7.11", "KTP Team", "running"),
    _module_row(7, "dodfun", "2.7.11", "KTP Team", "running"),
    _module_row(8, "HamSandwich", "1.10.0", "AMXX Dev Team", "running"),
    "8 modules, 8 correct",
])

PLUGINS_OUTPUT = "\n".join([
    "Currently loaded plugins:",
    "       id  name                 version    author           url                            file        status",
    _plugin_row(1, 1, "Admin Base", "1.10.0", "AMXX Dev Team", "https://amxmodx.org/", "admin.amxx", "running"),
    _plugin_row(2, 2, "KTP Match Handler", "0.10.114", "KTP Team", "https://ktp.gg/", "KTPMatchHandler.amxx", "running"),
    _plugin_row(3, 3, "KTP HLTV Recorder", "1.5.3", "KTP Team", "https://ktp.gg/", "KTPHLTVRecorder.amxx", "running"),
    _plugin_row(4, 4, "KTP Cvar Checker", "7.23", "KTP Team", "https://ktp.gg/", "ktp_cvar.amxx", "running"),
    _plugin_row(5, 5, "KTP Admin Audit", "2.7.11", "KTP Team", "https://ktp.gg/", "KTPAdminAudit.amxx", "running"),
    "5 plugins, 5 running",
])

PLUGINS_WITH_FAILURE = "\n".join([
    "Currently loaded plugins:",
    "       id  name                 version    author           url                            file        status",
    _plugin_row(1, 1, "Admin Base", "1.10.0", "AMXX Dev Team", "https://amxmodx.org/", "admin.amxx", "running"),
    _plugin_row(2, 2, "KTP Match Handler", "0.10.114", "KTP Team", "https://ktp.gg/", "KTPMatchHandler.amxx", "bad load"),
    _plugin_row(3, 3, "KTP HLTV Recorder", "1.5.3", "KTP Team", "https://ktp.gg/", "KTPHLTVRecorder.amxx", "running"),
    "3 plugins, 2 running, 1 bad load",
])


class ModuleParserTests(unittest.TestCase):
    def test_parses_all_rows(self):
        rows = parse_modules(MODULES_OUTPUT)
        self.assertEqual(len(rows), 8)

    def test_status_running(self):
        rows = parse_modules(MODULES_OUTPUT)
        for row in rows:
            self.assertEqual(row.status, "running")
            self.assertTrue(row.is_running)

    def test_indexes_match(self):
        rows = parse_modules(MODULES_OUTPUT)
        for i, row in enumerate(rows, 1):
            self.assertEqual(row.index, i)

    def test_module_names_extracted(self):
        rows = parse_modules(MODULES_OUTPUT)
        names = [r.name for r in rows]
        self.assertIn("amxxcurl", names)
        self.assertIn("reapi", names)
        self.assertIn("dodx", names)
        self.assertIn("HamSandwich", names)

    def test_multi_word_author(self):
        rows = parse_modules(MODULES_OUTPUT)
        amxx_devs = [r for r in rows if "AMXX" in r.author]
        self.assertGreater(len(amxx_devs), 0)
        for r in amxx_devs:
            self.assertEqual(r.author, "AMXX Dev Team")


class PluginParserTests(unittest.TestCase):
    def test_parses_all_rows(self):
        rows = parse_plugins(PLUGINS_OUTPUT)
        self.assertEqual(len(rows), 5)

    def test_filename_truncated_to_11(self):
        # `KTPMatchHandler.amxx` is 20 chars; AMXX prints first 11.
        rows = parse_plugins(PLUGINS_OUTPUT)
        match = next(r for r in rows if r.name == "KTP Match Handler")
        # AMXX's `%-12.11s` truncates to 11 chars max. After our parser strips
        # whitespace from the column slice, only the truncated content remains.
        self.assertEqual(match.filename, "KTPMatchHan")

    def test_short_filename_intact(self):
        rows = parse_plugins(PLUGINS_OUTPUT)
        admin = next(r for r in rows if r.filename == "admin.amxx")
        self.assertEqual(admin.name, "Admin Base")

    def test_detects_bad_load(self):
        rows = parse_plugins(PLUGINS_WITH_FAILURE)
        bad = [r for r in rows if not r.is_running]
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0].name, "KTP Match Handler")
        self.assertEqual(bad[0].status, "bad load")


class NormalisationTests(unittest.TestCase):
    def test_module_name_strips_so_suffix(self):
        # Filename forms canonicalise to the bare identity; `amxx` is
        # stripped as a vendor-wrapper token so amxxcurl → curl.
        self.assertEqual(normalise_module_name("amxxcurl_ktp_i386.so"), "curl")
        self.assertEqual(normalise_module_name("reapi_ktp_i386.so"), "reapi")
        self.assertEqual(normalise_module_name("dodx_ktp_i386.so"), "dodx")

    def test_module_name_idempotent(self):
        # Different surface forms of the same module canonicalise the same way.
        self.assertEqual(normalise_module_name("amxxcurl"), "curl")
        self.assertEqual(normalise_module_name("AmxxCurl_ktp"), "curl")
        self.assertEqual(normalise_module_name("curl"), "curl")

    def test_module_name_handles_display_format(self):
        """KTPAMXX `amx modules` rcon output uses `KTP <X> AMXX` display
        names. These should canonicalise to the same key as the filename."""
        self.assertEqual(normalise_module_name("KTP CURL AMXX"), "curl")
        self.assertEqual(normalise_module_name("DoDX"), "dodx")
        self.assertEqual(normalise_module_name("ReAPI"), "reapi")
        self.assertEqual(normalise_module_name("FakeMeta"), "fakemeta")

    def test_plugin_name_strips_amxx_and_normalises_spaces(self):
        self.assertEqual(normalise_plugin_name("KTPMatchHandler.amxx"), "ktpmatchhandler")
        self.assertEqual(normalise_plugin_name("KTP Match Handler"), "ktpmatchhandler")
        self.assertEqual(normalise_plugin_name("KTPMatchHandler"), "ktpmatchhandler")


class TruncatedMatchingTests(unittest.TestCase):
    def test_truncated_matches_full(self):
        # The exact 04-14-class scenario: caller expects `KTPMatchHandler.amxx`
        # but rcon output shows the truncated `KTPMatchHan`.
        self.assertTrue(matches_truncated("KTPMatchHandler.amxx", "KTPMatchHan"))
        self.assertTrue(matches_truncated("KTPMatchHandler", "KTPMatchHan"))

    def test_full_matches_full(self):
        self.assertTrue(matches_truncated("admin.amxx", "admin.amxx"))

    def test_short_filename_doesnt_falsely_match(self):
        # An 8-char prefix is the floor — shorter expected names need exact match.
        self.assertFalse(matches_truncated("foo.amxx", "KTPMatchHan"))
        self.assertFalse(matches_truncated("admin.amxx", "KTPHLTVReco"))

    def test_distinguishes_similar_prefixes(self):
        # Both KTPHLTVRecorder and KTPHLTVMonitor truncate to 11 chars
        # (KTPHLTVReco / KTPHLTVMoni). 8-char overlap floor catches the right
        # one and rejects the wrong one.
        self.assertTrue(matches_truncated("KTPHLTVRecorder.amxx", "KTPHLTVReco"))
        self.assertTrue(matches_truncated("KTPHLTVMonitor.amxx", "KTPHLTVMoni"))
        # Cross-match: KTPHLTVR (8 from "KTPHLTVRecorder") vs KTPHLTVM (8 from
        # "KTPHLTVMoni") — different at char 8, so reject.
        self.assertFalse(matches_truncated("KTPHLTVRecorder.amxx", "KTPHLTVMoni"))

    def test_shared_long_prefix_does_not_cross_match(self):
        # Regression (2026-07-07): the old 8-char comparison cap matched ANY
        # pair sharing an 8-char prefix — KTPGrenadeLoadout vs KTPGrenadeDamage
        # both normalise to `ktpgrena...`, so assert-plugins could pass off the
        # wrong plugin's row. The shorter string must now prefix-match over its
        # FULL length.
        self.assertFalse(matches_truncated("KTPGrenadeLoadout.amxx", "KTPGrenadeD"))
        self.assertFalse(matches_truncated("KTPGrenadeDamage.amxx", "KTPGrenadeL"))
        # The correct pairings still match (11-char AMXX truncations).
        self.assertTrue(matches_truncated("KTPGrenadeLoadout.amxx", "KTPGrenadeL"))
        self.assertTrue(matches_truncated("KTPGrenadeDamage.amxx", "KTPGrenadeD"))

    def test_short_name_with_sliced_extension(self):
        # Regression (2026-07-08, first caught by KTPFileChecker's smoke): the
        # 11-char truncation slices .amxx mid-way (`ktp_file.am`), and the
        # 2026-07-07 full-length-prefix fix rejected the pair — the expected
        # side normalises to `ktpfile` (7 chars, under the 8-char overlap
        # floor) while the actual kept the `.am` fragment. Partial extension
        # fragments are now stripped in normalise_plugin_name.
        self.assertTrue(matches_truncated("ktp_file", "ktp_file.am"))
        self.assertTrue(matches_truncated("ktp_file.amxx", "ktp_file.am"))
        self.assertTrue(matches_truncated("ktp_cvar", "ktp_cvar.am"))
        # Distinct short names still refuse to cross-match.
        self.assertFalse(matches_truncated("ktp_file", "ktp_cvar.am"))


if __name__ == "__main__":
    unittest.main()
