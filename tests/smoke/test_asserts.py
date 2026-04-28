"""Unit tests for asserts.py — drives a stubbed ServerHandle.

Validates the failure-detection paths that would catch real production
incidents (the 04-14 KTPAmxxCurl class: silent module load failure cascades
into all plugins broken).
"""

from __future__ import annotations

import unittest

from .asserts import (
    assert_modules_loaded,
    assert_no_failed_modules,
    assert_no_failed_plugins,
    assert_plugins_running,
)
from .test_parse import (
    MODULES_OUTPUT,
    PLUGINS_OUTPUT,
    PLUGINS_WITH_FAILURE,
    _module_row,
    _plugin_row,
)


class StubHandle:
    """In-memory ServerHandle replacement — answers rcon from a dict."""

    def __init__(self, responses: dict[str, str]):
        self._responses = responses

    def rcon(self, command: str, *, timeout: float = 2.0) -> str:
        try:
            return self._responses[command]
        except KeyError as exc:
            raise AssertionError(f"unexpected rcon command in test: {command}") from exc


class AssertModulesLoadedTests(unittest.TestCase):
    def test_all_present_passes(self):
        handle = StubHandle({"amx modules": MODULES_OUTPUT})
        rows = assert_modules_loaded(handle, ["amxxcurl_ktp_i386.so", "reapi_ktp", "dodx"])
        self.assertEqual(len(rows), 8)

    def test_missing_module_fails_with_name(self):
        handle = StubHandle({"amx modules": MODULES_OUTPUT})
        with self.assertRaises(AssertionError) as ctx:
            assert_modules_loaded(handle, ["amxxcurl", "reapi", "doesnotexist"])
        self.assertIn("doesnotexist", str(ctx.exception))


class AssertPluginsRunningTests(unittest.TestCase):
    def test_full_filenames_match_truncated_output(self):
        # The whole-point test: caller passes the .amxx filename, AMXX returns
        # it truncated, harness still finds it.
        handle = StubHandle({"amx plugins": PLUGINS_OUTPUT})
        rows = assert_plugins_running(
            handle,
            ["KTPMatchHandler.amxx", "KTPHLTVRecorder.amxx", "admin.amxx"],
        )
        self.assertEqual(len(rows), 5)

    def test_display_name_also_works(self):
        handle = StubHandle({"amx plugins": PLUGINS_OUTPUT})
        rows = assert_plugins_running(handle, ["KTP Match Handler"])
        self.assertEqual(len(rows), 5)

    def test_bad_load_detected(self):
        handle = StubHandle({"amx plugins": PLUGINS_WITH_FAILURE})
        with self.assertRaises(AssertionError) as ctx:
            assert_plugins_running(handle, ["KTPMatchHandler.amxx"])
        msg = str(ctx.exception)
        self.assertIn("not running", msg)
        self.assertIn("bad load", msg)


class AssertNoFailedTests(unittest.TestCase):
    def test_clean_output_passes(self):
        h = StubHandle({"amx modules": MODULES_OUTPUT, "amx plugins": PLUGINS_OUTPUT})
        assert_no_failed_modules(h)
        assert_no_failed_plugins(h)

    def test_debug_status_treated_as_running(self):
        """Plugins loaded with the `debug` flag in plugins.ini show status=
        debug instead of running (interpreted VM, no JIT). They're still
        loaded and active — should not fail the assertion."""
        debug_output = "\n".join([
            "Currently loaded plugins:",
            "       id  name                 version    author           url                            file        status",
            _plugin_row(1, 1, "Admin Base", "1.10.0", "AMXX Dev Team", "https://amxmodx.org/", "admin.amxx", "running"),
            _plugin_row(2, 2, "KTP Match Handler", "0.10.116", "Nein_", "https://ktp.gg/", "KTPMatchHandler.amxx", "debug"),
            _plugin_row(3, 3, "KTP HLTV Recorder", "1.5.7", "Nein_", "https://ktp.gg/", "KTPHLTVRecorder.amxx", "debug"),
            "3 plugins, 3 running",
        ])
        h = StubHandle({"amx plugins": debug_output})
        assert_no_failed_plugins(h)
        # Truncation-aware match still works for debug-status plugins.
        assert_plugins_running(h, ["KTPMatchHandler.amxx"])

    def test_failure_in_plugin_is_named(self):
        h = StubHandle({"amx modules": MODULES_OUTPUT, "amx plugins": PLUGINS_WITH_FAILURE})
        with self.assertRaises(AssertionError) as ctx:
            assert_no_failed_plugins(h)
        self.assertIn("KTPMatchHan", str(ctx.exception))
        self.assertIn("bad load", str(ctx.exception))

    def test_failure_in_module_is_named(self):
        # Synthesise a modules dump where one module is in a non-running state.
        broken = "\n".join([
            "Currently loaded modules:",
            "       name           version    author          status",
            _module_row(1, "Fun", "1.10.0", "AMXX Dev Team", "running"),
            _module_row(2, "amxxcurl", "1.3.8-ktp", "KTP Team", "bad load"),
            _module_row(3, "reapi", "5.29.0", "KTP Team", "running"),
            "3 modules, 2 correct",
        ])
        h = StubHandle({"amx modules": broken})
        with self.assertRaises(AssertionError) as ctx:
            assert_no_failed_modules(h)
        self.assertIn("amxxcurl", str(ctx.exception))
        self.assertIn("bad load", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
