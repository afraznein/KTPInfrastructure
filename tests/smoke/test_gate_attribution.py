"""Does the shared Tier 1 gate still tell a regression from its own breakage?

The fixtures are the VERBATIM `amx modules` / `amx plugins` output of the run
that prompted this code — JimmyLockhart65616/DoD-hud-observer run 34476842145,
2026-09-10 — where the change under test loaded fine and the job went red on
`stats_loggi=bad load`, a plugin the base image had failed to ship.

Every case is asserted in both directions: a real regression in the plugin
under test must still be fatal, and an unrelated plugin must not be.

Run from KTPInfrastructure root:
    python -m unittest tests.smoke.test_gate_attribution
"""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from . import cli
from .asserts import (
    InfrastructureFault,
    assert_no_failed_modules,
    assert_no_failed_plugins,
)

# --- Captured verbatim. Column alignment is load-bearing: parse.py slices by
# fixed width, so re-indenting these strings breaks the parser, not the test.
MODULES_REAL = (
    "Currently loaded modules:\n"
    "      name                    version     author               status     \n"
    " [ 1] ReAPI                   5.29.0.368  Asmodai & s1lent     running    \n"
    " [ 2] DoDX                    2.7.33.1    AMX Mod X Dev Team   running    \n"
    " [ 3] KTP CURL AMXX           1.3.17-ktp  Polarhigh / KTP      running    \n"
    "3 modules, 3 correct\n"
)

PLUGINS_REAL_STATS_BAD = (
    "Currently loaded plugins:\n"
    "       id  name                    version     author            url                              file         status   \n"
    " [  1] 0   Admin Base              1.10.0-man  AMXX Dev Team                                      admin.amxx   running  \n"
    " [  2] 1   unknown                 unknown     unknown           unknown                          stats_loggi  bad load \n"
    " [  3] 2   KTP Admin Audit         2.7.20      Nein_                                              KTPAdminAud  debug    \n"
    " [  4] 3   KTP Cvar Checker        7.39        Nein_                                              ktp_cvar.am  debug    \n"
    " [  5] 4   KTP File Checker        2.9         Nein_                                              ktp_file.am  debug    \n"
    " [  6] 5   KTP Match Handler       0.10.170    Nein_                                              KTPMatchHan  debug    \n"
    " [  7] 6   KTP HLTV Recorder       1.7.3       Nein_                                              KTPHLTVReco  debug    \n"
    " [  8] 7   KTP Practice Mode       1.4.9       Nein_                                              KTPPractice  debug    \n"
    " [  9] 8   KTP Grenade Loadout     1.0.12      Nein_                                              KTPGrenadeL  debug    \n"
    " [ 10] 9   KTP Grenade Damage      1.0.5       Nein_                                              KTPGrenadeD  debug    \n"
    " [ 11] 10  KTP HUD Observer        2.9.1       cadaver                                            KTPHudObser  debug    \n"
    '(  2) Load fails: Plugin file open error (plugin "stats_logging.amxx")\n'
    "11 plugins, 10 running\n"
)


def _flip_status(output: str, filename: str, new_status: str) -> str:
    """Rewrite one row's status in place, preserving every column boundary.

    Both the old and new status must fit AMXX's `%-9.8s`, and the rebuilt line
    is length-checked — a fixture that silently shifts the columns would make
    the parser read garbage and the test pass for the wrong reason.
    """
    lines = output.split("\n")
    hits = [i for i, line in enumerate(lines) if f" {filename} " in line]
    if len(hits) != 1:
        raise AssertionError(f"{filename!r} matched {len(hits)} rows, need exactly 1")
    if len(new_status) > 8:
        raise AssertionError(f"{new_status!r} exceeds AMXX's 8-char status field")
    i = hits[0]
    # `%-12.11s %-9.8s`: the filename field is 12 wide however short the name,
    # then one literal space, then status. Deriving the offset from the name's
    # own length is the trap — `admin.amxx` is 10 chars in the same 12 columns.
    start = lines[i].index(f" {filename} ") + 1 + 12 + 1
    rewritten = lines[i][:start] + f"{new_status:<{len(lines[i]) - start}}"
    if len(rewritten) != len(lines[i]):
        raise AssertionError("rewrite changed the line width")
    lines[i] = rewritten
    return "\n".join(lines)


PLUGINS_ALL_GOOD = _flip_status(PLUGINS_REAL_STATS_BAD, "stats_loggi", "running")
PLUGINS_UNDER_TEST_BAD = _flip_status(PLUGINS_ALL_GOOD, "KTPHudObser", "bad load")
PLUGINS_BOTH_BAD = _flip_status(PLUGINS_REAL_STATS_BAD, "KTPHudObser", "bad load")
PLUGINS_SIBLING_BAD = _flip_status(PLUGINS_ALL_GOOD, "KTPGrenadeD", "bad load")
MODULES_CURL_BAD = MODULES_REAL.replace(
    "KTP CURL AMXX           1.3.17-ktp  Polarhigh / KTP      running    ",
    "KTP CURL AMXX           1.3.17-ktp  Polarhigh / KTP      bad load   ",
)

HUD = ["KTPHudObserver.amxx"]


class StubHandle:
    def __init__(self, modules: str = MODULES_REAL, plugins: str = PLUGINS_ALL_GOOD):
        self._responses = {"amx modules": modules, "amx plugins": plugins}

    def rcon(self, command: str, *, timeout: float = 2.0) -> str:
        return self._responses[command]


class FixtureSanityTests(unittest.TestCase):
    """The fixtures must actually say what the cases below assume."""

    def test_real_output_has_exactly_one_failure_and_it_is_stats_logging(self):
        from .parse import parse_plugins

        rows = parse_plugins(PLUGINS_REAL_STATS_BAD)
        self.assertEqual(len(rows), 11)
        bad = [r for r in rows if not r.is_running]
        self.assertEqual([r.filename for r in bad], ["stats_loggi"])

    def test_flipping_a_status_is_the_only_difference(self):
        from .parse import parse_plugins

        good = {r.filename: r.status for r in parse_plugins(PLUGINS_ALL_GOOD)}
        bad = {r.filename: r.status for r in parse_plugins(PLUGINS_UNDER_TEST_BAD)}
        differing = [k for k in good if good[k] != bad[k]]
        self.assertEqual(differing, ["KTPHudObser"])
        self.assertEqual(bad["KTPHudObser"], "bad load")


class PluginAttributionTests(unittest.TestCase):
    def test_green_when_nothing_failed(self):
        rows = assert_no_failed_plugins(StubHandle(plugins=PLUGINS_ALL_GOOD), HUD)
        self.assertEqual(len(rows), 11)

    def test_unrelated_failure_is_an_image_fault_not_a_caller_failure(self):
        """The incident itself: KTPHudObserver is fine, stats_logging is not."""
        handle = StubHandle(plugins=PLUGINS_REAL_STATS_BAD)
        with self.assertRaises(InfrastructureFault) as ctx:
            assert_no_failed_plugins(handle, HUD)
        msg = str(ctx.exception)
        self.assertIn("stats_loggi", msg)
        self.assertIn("none of them under test", msg)

    def test_failure_in_the_plugin_under_test_is_still_fatal(self):
        """The half that proves the gate did not stop checking."""
        handle = StubHandle(plugins=PLUGINS_UNDER_TEST_BAD)
        with self.assertRaises(AssertionError) as ctx:
            assert_no_failed_plugins(handle, HUD)
        msg = str(ctx.exception)
        self.assertIn("UNDER TEST", msg)
        self.assertIn("KTPHudObser", msg)

    def test_an_image_fault_alongside_a_real_regression_is_still_fatal(self):
        handle = StubHandle(plugins=PLUGINS_BOTH_BAD)
        with self.assertRaises(AssertionError) as ctx:
            assert_no_failed_plugins(handle, HUD)
        # Both named, but the verdict is the caller's regression.
        self.assertIn("KTPHudObser", str(ctx.exception))
        self.assertIn("stats_loggi", str(ctx.exception))

    def test_attribution_does_not_over_match_a_shared_prefix(self):
        """`KTPGrenadeD` and `KTPGrenadeL` share 11 truncated chars up to the
        last one. Claiming the wrong sibling would turn an image fault into a
        fake regression — or, worse, the reverse."""
        handle = StubHandle(plugins=PLUGINS_SIBLING_BAD)
        with self.assertRaises(InfrastructureFault):
            assert_no_failed_plugins(handle, ["KTPGrenadeLoadout.amxx"])
        with self.assertRaises(AssertionError):
            assert_no_failed_plugins(handle, ["KTPGrenadeDamage.amxx"])

    def test_without_an_under_test_set_every_failure_stays_fatal(self):
        """Regression guard on the default. Anything that calls this the old
        way — publish-base-image.yml's pre-push gate included — must keep the
        old contract."""
        handle = StubHandle(plugins=PLUGINS_REAL_STATS_BAD)
        with self.assertRaises(AssertionError) as ctx:
            assert_no_failed_plugins(handle)
        self.assertNotIsInstance(ctx.exception, InfrastructureFault)
        self.assertIn("stats_loggi", str(ctx.exception))

    def test_zero_rows_stays_fatal_even_when_scoped(self):
        """An empty listing means the platform is down, so the under-test
        artifact is not running either — attribution cannot excuse it."""
        handle = StubHandle(plugins="Unknown command: amx\n")
        with self.assertRaises(AssertionError) as ctx:
            assert_no_failed_plugins(handle, HUD)
        self.assertNotIsInstance(ctx.exception, InfrastructureFault)


class ModuleAttributionTests(unittest.TestCase):
    def test_unrelated_module_failure_is_an_image_fault(self):
        handle = StubHandle(modules=MODULES_CURL_BAD)
        with self.assertRaises(InfrastructureFault) as ctx:
            assert_no_failed_modules(handle, ["reapi"])
        self.assertIn("KTP CURL AMXX", str(ctx.exception))

    def test_module_under_test_failure_is_fatal(self):
        handle = StubHandle(modules=MODULES_CURL_BAD)
        with self.assertRaises(AssertionError) as ctx:
            assert_no_failed_modules(handle, ["amxxcurl_ktp_i386.so"])
        self.assertIn("UNDER TEST", str(ctx.exception))

    def test_without_an_under_test_set_every_failure_stays_fatal(self):
        handle = StubHandle(modules=MODULES_CURL_BAD)
        with self.assertRaises(AssertionError) as ctx:
            assert_no_failed_modules(handle)
        self.assertNotIsInstance(ctx.exception, InfrastructureFault)


class CliExitCodeTests(unittest.TestCase):
    """The workflow branches on the exit code, so the exit code is the contract."""

    def _run(self, argv: list[str], **stub_kwargs) -> tuple[int, str, str]:
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(cli, "ServerHandle", lambda **_: StubHandle(**stub_kwargs)):
            with redirect_stdout(out), redirect_stderr(err):
                rc = cli.main(argv)
        return rc, out.getvalue(), err.getvalue()

    BASE = ["assert-no-failed", "--port", "27016"]

    def test_clean_image_exits_zero(self):
        rc, out, _ = self._run(self.BASE + ["--under-test", "KTPHudObserver.amxx"])
        self.assertEqual(rc, cli.EXIT_OK)
        self.assertIn("OK: no failed", out)

    def test_unrelated_failure_exits_three(self):
        rc, _, err = self._run(
            self.BASE + ["--under-test", "KTPHudObserver.amxx"],
            plugins=PLUGINS_REAL_STATS_BAD,
        )
        self.assertEqual(rc, cli.EXIT_IMAGE_FAULT)
        self.assertIn("IMAGE-FAULT", err)
        self.assertIn("stats_loggi", err)

    def test_under_test_failure_exits_one(self):
        rc, _, err = self._run(
            self.BASE + ["--under-test", "KTPHudObserver.amxx"],
            plugins=PLUGINS_UNDER_TEST_BAD,
        )
        self.assertEqual(rc, cli.EXIT_ASSERT)
        self.assertIn("FAIL", err)
        self.assertNotIn("IMAGE-FAULT", err)

    def test_same_failure_exits_one_when_unscoped(self):
        rc, _, err = self._run(self.BASE, plugins=PLUGINS_REAL_STATS_BAD)
        self.assertEqual(rc, cli.EXIT_ASSERT)
        self.assertIn("FAIL", err)

    def test_empty_under_test_set_is_refused_not_treated_as_unscoped(self):
        """`--under-test ,,` reaching the strict path would be a silent
        widening; reaching the scoped path would excuse everything."""
        rc, _, err = self._run(self.BASE + ["--under-test", ",, ,"])
        self.assertEqual(rc, cli.EXIT_INFRA)
        self.assertIn("zero names", err)

    def test_module_and_plugin_names_can_be_passed_together(self):
        rc, _, err = self._run(
            self.BASE + ["--under-test", "KTPHudObserver.amxx,amxxcurl"],
            modules=MODULES_CURL_BAD,
            plugins=PLUGINS_ALL_GOOD,
        )
        self.assertEqual(rc, cli.EXIT_ASSERT)
        self.assertIn("UNDER TEST", err)


if __name__ == "__main__":
    unittest.main()
