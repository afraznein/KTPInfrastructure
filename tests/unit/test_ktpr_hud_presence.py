"""`_hud_tables_present` must answer, not raise.

The HUD tables live only in hlstatsx_lan. Against the season DB a HUD query
fails with "table doesn't exist" rather than returning zero rows, so
`_assist_break_stats` gates its HUD fallback on this check. `_parse_rows` is a
generator function: a bare generator is truthy even when empty AND is not
subscriptable, so `bool(rows) and int(rows[0][0])` raised TypeError on every
call and the gated fallback could never run. No DB here -- run_sql is replaced
with the TSV the remote mysql CLI would have printed.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "docs" / "ktpr_mcp"))

import ktpr_mysql  # noqa: E402


class HudTablesPresent(unittest.TestCase):
    def setUp(self):
        self._real = ktpr_mysql.run_sql
        self.addCleanup(setattr, ktpr_mysql, "run_sql", self._real)

    def _answer(self, tsv):
        ktpr_mysql.run_sql = lambda sql, database=None: tsv
        return ktpr_mysql._hud_tables_present()

    def test_present_when_count_is_one(self):
        self.assertIs(self._answer("1\n"), True)

    def test_absent_when_count_is_zero(self):
        # The load-bearing case: pre-fix this raised TypeError, so the caller
        # could never reach `return {}` and fall back cleanly.
        self.assertIs(self._answer("0\n"), False)

    def test_absent_when_no_rows_at_all(self):
        self.assertIs(self._answer(""), False)

    def test_parse_rows_is_a_generator(self):
        # Guards the reason the list() is there: if _parse_rows ever becomes a
        # list-returner the comment above stops being true, but the cast stays
        # correct either way.
        rows = ktpr_mysql._parse_rows("a\tb\n")
        self.assertFalse(hasattr(rows, "__getitem__"))
        self.assertEqual(list(rows), [["a", "b"]])


if __name__ == "__main__":
    unittest.main()
