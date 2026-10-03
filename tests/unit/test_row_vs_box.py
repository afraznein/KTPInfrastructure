"""ktp-row-vs-box: a data-server version row against the file on the box.

No network. The box is a fake that answers the checker's own remote command
from a path -> hash map, so the command text is exercised as well as the
verdicts. The fixture rows are the table's real shapes, trimmed.
"""
from __future__ import annotations

import importlib.util
import os
import re
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load():
    spec = importlib.util.spec_from_file_location(
        "ktp_row_vs_box", os.path.join(_ROOT, "scripts", "ktp-row-vs-box.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["ktp_row_vs_box"] = mod
    spec.loader.exec_module(mod)
    return mod


rvb = _load()

HLS = "1eb7469f80438a0c3fdfced8bfb42f31"
HLS_OLD = "427772bb2b2eefc2e6f481fc4627b9c3"
AGG = "a7c02ee929bbce9e4880f2d21b9aa69a8b960b9da606c5b65ba482a63a39614f"
DIST = "5da50e3366d449b4829c8a381107a7a9"

TABLE = f"""\
| Component | Live | Since | Verified hash · rollback pin · live-state notes |
|---|---|---|---|
| KTPHLStatsX | `origin/main` **`6d6a779`** | 09-29 | **`{HLS}`** · 297,242 B on `/opt/hlstatsx/scripts/hlstats.pl` — swapped. 📌 **ROLLBACK PIN: `{HLS_OLD}` · 296,762 B at `/root/hlstats.pl.bak`** |
| KTPProfileAggregator | `9667b63` | 09-11 | sha256 **`{AGG}`** — measured on the `ExecStart` path |
| KTPFileDistributor | **1.2.2** | 09-28 | **`{DIST}`** · 39,264,512 B — measured on `/proc/692393/exe`, restarted |
| KTPAntiCheat (API) | 0.8.3 | 10-01 | no hash recorded on this row |
"""

NO_PATH_ROWS = ("KTPProfileAggregator", "KTPFileDistributor", "KTPAntiCheat (API)")


class Box:
    """Answers remote_command() the way a shell on the box would."""

    def __init__(self, files, fail=None, drop_last=False, control_hash=None):
        self.files, self.fail, self.drop_last, self.control_hash = files, fail, drop_last, control_hash
        self.commands = []

    def __call__(self, cmd):
        self.commands.append(cmd)
        if self.fail:
            raise self.fail
        out = []
        for tool, path, idx in re.findall(
                r'h=\$\((md5sum|sha256sum) -- (\S+) 2>/dev/null\) && echo "(\d+)', cmd):
            if path == rvb.CONTROL_PATH and self.control_hash:
                out.append(f"{idx} {self.control_hash}")
                continue
            got = self.files.get(path)
            if got is None:
                out.append(f"{idx} ERR")
            else:
                assert (len(got) == 64) == (tool == "sha256sum"), "wrong tool for the hash"
                out.append(f"{idx} {got}")
        if self.drop_last:
            out = out[:-1]
        return "\n".join(out) + "\n"


def by_name(rows):
    return {r.component: r for r in rows}


# --- parsing -------------------------------------------------------------------


def test_the_live_hash_and_its_own_path_are_read():
    r = rvb.parse_row(TABLE, "KTPHLStatsX")
    assert (r.status, r.expected, r.path, r.algo) == (
        "", HLS, "/opt/hlstatsx/scripts/hlstats.pl", "md5")


def test_a_later_clause_path_is_not_taken_for_the_live_file():
    """The rollback pin's `/root/...bak` must never stand in for a row with no path."""
    text = TABLE.replace(" · 297,242 B on `/opt/hlstatsx/scripts/hlstats.pl`", "")
    r = rvb.parse_row(text, "KTPHLStatsX")
    assert r.status == "UNPARSEABLE"
    assert r.path is None


def test_a_row_without_a_path_is_unparseable_not_guessed():
    r = rvb.parse_row(TABLE, "KTPProfileAggregator")
    assert r.status == "UNPARSEABLE"
    assert r.expected == AGG


def test_a_proc_pid_path_is_unparseable():
    r = rvb.parse_row(TABLE, "KTPFileDistributor")
    assert r.status == "UNPARSEABLE"
    assert "process id" in r.detail


def test_a_row_with_no_hash_is_unparseable():
    assert rvb.parse_row(TABLE, "KTPAntiCheat (API)").status == "UNPARSEABLE"


def test_a_component_with_no_row_is_missing():
    assert rvb.parse_row(TABLE, "KTPNoSuchThing").status == "ROW_MISSING"


def test_path_override_supplies_a_path_and_keeps_the_hash_kind():
    r = rvb.parse_row(TABLE, "KTPProfileAggregator", "/opt/agg/aggregator.py")
    assert (r.status, r.path, r.algo) == ("", "/opt/agg/aggregator.py", "sha256")


# --- verdicts -------------------------------------------------------------------


def test_a_matching_box_is_ok():
    rows, distrust = rvb.check(TABLE, ("KTPHLStatsX",), {},
                               Box({"/opt/hlstatsx/scripts/hlstats.pl": HLS}))
    assert distrust == []
    assert by_name(rows)["KTPHLStatsX"].status == "OK"


def test_a_deliberately_wrong_md5_on_the_row_is_caught():
    wrong = TABLE.replace(HLS, "0" + HLS[1:])
    rows, distrust = rvb.check(wrong, ("KTPHLStatsX",), {},
                               Box({"/opt/hlstatsx/scripts/hlstats.pl": HLS}))
    assert distrust == []
    r = by_name(rows)["KTPHLStatsX"]
    assert (r.status, r.actual) == ("ROW_STALE", HLS)


def test_a_row_two_deploys_behind_is_stale():
    """The case this exists for: the box moved on and the row still names the old build."""
    rows, _ = rvb.check(TABLE, ("KTPHLStatsX",), {},
                        Box({"/opt/hlstatsx/scripts/hlstats.pl": "f" * 32}))
    assert by_name(rows)["KTPHLStatsX"].status == "ROW_STALE"


def test_sha256_rows_are_hashed_with_sha256():
    box = Box({"/opt/agg/aggregator.py": AGG})
    rows, distrust = rvb.check(TABLE, ("KTPProfileAggregator",),
                               {"KTPProfileAggregator": "/opt/agg/aggregator.py"}, box)
    assert distrust == []
    assert by_name(rows)["KTPProfileAggregator"].status == "OK"
    assert "sha256sum -- /opt/agg/aggregator.py" in box.commands[0]


def test_an_unhashable_path_is_unreadable_not_stale():
    rows, distrust = rvb.check(TABLE, ("KTPHLStatsX",), {}, Box({}))
    assert by_name(rows)["KTPHLStatsX"].status == "UNREADABLE"
    assert distrust == []


# --- the check distrusting itself -----------------------------------------------


def test_ssh_failure_is_distrust():
    rows, distrust = rvb.check(TABLE, ("KTPHLStatsX",), {}, Box({}, fail=OSError("refused")))
    assert any("SSH failed" in d for d in distrust)
    assert by_name(rows)["KTPHLStatsX"].status == "UNREADABLE"


def test_a_short_reply_is_distrust():
    rows, distrust = rvb.check(TABLE, ("KTPHLStatsX",), {},
                               Box({"/opt/hlstatsx/scripts/hlstats.pl": HLS}, drop_last=True))
    assert any("did not account" in d for d in distrust)


def test_a_box_that_hashes_a_nonexistent_path_fails_the_control():
    """If a failed read can come back as a hash, no OK on this run means anything."""
    rows, distrust = rvb.check(TABLE, ("KTPHLStatsX",), {},
                               Box({"/opt/hlstatsx/scripts/hlstats.pl": HLS}, control_hash="e" * 32))
    assert any("control failed" in d for d in distrust)


def test_the_wrong_hash_control_runs_through_the_parser(monkeypatch):
    """Break where the claim comes from and the per-row control must notice."""
    real = rvb.parse_row

    def sticky(text, component, override=None):
        r = real(TABLE, component, override)       # ignores the text it was given
        return r

    monkeypatch.setattr(rvb, "parse_row", sticky)
    _, distrust = rvb.check(TABLE, ("KTPHLStatsX",), {},
                            Box({"/opt/hlstatsx/scripts/hlstats.pl": HLS}))
    assert any("still read as OK" in d for d in distrust)


def test_nothing_checkable_is_distrust():
    _, distrust = rvb.check(TABLE, NO_PATH_ROWS, {}, Box({}))
    assert any("no row carried" in d for d in distrust)


def test_an_override_for_an_unchecked_component_is_distrust():
    _, distrust = rvb.check(TABLE, ("KTPHLStatsX",), {"KTPTypo": "/x"},
                            Box({"/opt/hlstatsx/scripts/hlstats.pl": HLS}))
    assert any("KTPTypo" in d for d in distrust)


# --- exit codes ------------------------------------------------------------------


@pytest.fixture
def rows_file(tmp_path):
    p = tmp_path / "SKILL.md"
    p.write_text(TABLE, encoding="utf-8")
    return p


def _main(monkeypatch, argv, box):
    monkeypatch.setattr(rvb, "run_ssh", lambda target, cmd, key: box(cmd))
    return rvb.main(argv)


def test_exit_0_when_every_checked_row_is_ok(monkeypatch, rows_file):
    box = Box({"/opt/hlstatsx/scripts/hlstats.pl": HLS})
    assert _main(monkeypatch, [str(rows_file), "--host", "u@h", "--component", "KTPHLStatsX"], box) == 0


def test_exit_1_on_a_stale_row(monkeypatch, rows_file):
    box = Box({"/opt/hlstatsx/scripts/hlstats.pl": "f" * 32})
    assert _main(monkeypatch, [str(rows_file), "--host", "u@h", "--component", "KTPHLStatsX"], box) == 1


def test_exit_2_when_any_row_cannot_be_checked(monkeypatch, rows_file):
    box = Box({"/opt/hlstatsx/scripts/hlstats.pl": HLS})
    assert _main(monkeypatch, [str(rows_file), "--host", "u@h"], box) == 2


def test_a_failed_control_outranks_a_stale_row(monkeypatch, rows_file):
    box = Box({"/opt/hlstatsx/scripts/hlstats.pl": "f" * 32}, control_hash="e" * 32)
    assert _main(monkeypatch, [str(rows_file), "--host", "u@h", "--component", "KTPHLStatsX"], box) == 2


def test_exit_2_on_a_file_with_no_table(monkeypatch, tmp_path):
    p = tmp_path / "notes.md"
    p.write_text("# just prose\n", encoding="utf-8")
    assert _main(monkeypatch, [str(p), "--host", "u@h"], Box({})) == 2


def test_exit_2_on_a_relative_override(monkeypatch, rows_file):
    assert _main(monkeypatch, [str(rows_file), "--host", "u@h",
                               "--path", "KTPHLStatsX=relative/path"], Box({})) == 2

