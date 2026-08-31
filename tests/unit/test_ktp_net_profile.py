"""Guards for three residual defects in `scripts/ktp-net-profile.py`.

`report_lagcomp` being called on both of main()'s exits (:305 and :348) is
already fixed on origin/main and is NOT re-tested here -- it is not a
behavioural fix under test, and there is nothing left to regress.

The three covered here:

  1. `net_detail:` counting ignored `--date` and reported a lifetime-across-
     retention figure instead of a count for the run's date.
  2. `grep -h` over `~/dod-*` merged every instance on a host into one number
     -- "dallas: 719" could not be split back into DAL4 vs DAL1 etc.
  3. `report_lagcomp` printed raw player names, which raised
     `UnicodeEncodeError` on a Windows console (cp1252) for any name outside
     that codec.

Loaded by path, with `paramiko` stubbed: the script imports paramiko at
module level and this suite never touches a real socket.
"""
from __future__ import annotations

import importlib.util
import io
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "ktp-net-profile.py"


def _load_module():
    sys.modules.setdefault("paramiko", types.ModuleType("paramiko"))
    spec = importlib.util.spec_from_file_location("_ktp_net_profile", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def netprof():
    return _load_module()


class _FakeStream:
    def __init__(self, data: bytes):
        self._data = data

    def read(self):
        return self._data


class _FakeSSHClient:
    """Records every exec_command call; answers by matching on cmd content."""

    def __init__(self, responses):
        self.calls = []
        self._responses = responses

    def set_missing_host_key_policy(self, policy):
        pass

    def connect(self, *a, **kw):
        pass

    def exec_command(self, cmd, timeout=None):
        self.calls.append(cmd)
        for needle, data in self._responses:
            if needle in cmd:
                return (None, _FakeStream(data), None)
        return (None, _FakeStream(b""), None)

    def close(self):
        pass


# --------------------------------------------------------------- positive control

def test_module_loaded_the_real_functions(netprof):
    """If the loader silently produced a stub, every assertion below passes
    vacuously. Fail here instead."""
    assert hasattr(netprof, "harvest")
    assert hasattr(netprof, "parse")
    assert hasattr(netprof, "report_lagcomp")
    assert hasattr(netprof, "INSTANCE")


# --------------------------------------------------------- 1. net_detail + --date

def test_net_detail_count_is_scoped_to_date(netprof, monkeypatch):
    """Regression for: the net_detail grep counted every retained log file with
    no date filter at all, so it reported a lifetime figure, not this run's."""
    client = _FakeSSHClient([
        ("net_detail:", b"0\n"),
        ("KTP_PROFILE", b""),
        ("ls ", b"2\n"),
        ("event=LAGCOMP_", b""),
    ])
    monkeypatch.setattr(netprof.paramiko, "SSHClient", lambda: client, raising=False)
    monkeypatch.setattr(netprof.paramiko, "AutoAddPolicy", lambda: None, raising=False)

    netprof.harvest("host", "pw", "08/27/2026", True, 5)

    detail_cmds = [c for c in client.calls if "net_detail:" in c]
    assert detail_cmds, "net_detail command was never issued"
    assert "08/27/2026" in detail_cmds[0], (
        "net_detail count must filter on --date the same way the net: count "
        f"does -- got: {detail_cmds[0]!r}"
    )


def test_net_detail_count_changes_with_a_different_date(netprof, monkeypatch):
    """A date-scoped command must actually vary with --date, or the fix above
    could be a filter that is present but inert."""
    seen_cmds = []

    def make_client():
        c = _FakeSSHClient([
            ("net_detail:", b"0\n"),
            ("KTP_PROFILE", b""),
            ("ls ", b"1\n"),
            ("event=LAGCOMP_", b""),
        ])
        seen_cmds.append(c)
        return c

    monkeypatch.setattr(netprof.paramiko, "SSHClient", make_client, raising=False)
    monkeypatch.setattr(netprof.paramiko, "AutoAddPolicy", lambda: None, raising=False)

    netprof.harvest("host", "pw", "08/27/2026", True, 5)
    netprof.harvest("host", "pw", "08/28/2026", True, 5)

    cmd_27 = next(c for c in seen_cmds[0].calls if "net_detail:" in c)
    cmd_28 = next(c for c in seen_cmds[1].calls if "net_detail:" in c)
    assert cmd_27 != cmd_28
    assert "08/27/2026" in cmd_27
    assert "08/28/2026" in cmd_28


# --------------------------------------------------------- 2. per-instance attribution

def test_harvest_keeps_filenames_for_instance_attribution(netprof, monkeypatch):
    """Regression for: `grep -h` suppressed the source path, so every instance
    on a host collapsed into one number nobody could split back apart."""
    client = _FakeSSHClient([
        ("net_detail:", b"0\n"),
        ("KTP_PROFILE", b""),
        ("ls ", b"2\n"),
        ("event=LAGCOMP_", b""),
    ])
    monkeypatch.setattr(netprof.paramiko, "SSHClient", lambda: client, raising=False)
    monkeypatch.setattr(netprof.paramiko, "AutoAddPolicy", lambda: None, raising=False)

    netprof.harvest("host", "pw", "08/27/2026", True, 5)

    net_cmds = [c for c in client.calls if "KTP_PROFILE" in c]
    assert net_cmds
    # Must be -H, not a bare grep: GNU grep only auto-prefixes the filename
    # when 2+ files match, so a night where the glob happens to match exactly
    # one file would silently lose attribution without forcing it.
    assert "grep -H '\\[KTP_PROFILE\\] net:'" in net_cmds[0]
    assert "grep -h '\\[KTP_PROFILE\\] net:'" not in net_cmds[0]


def test_parse_attributes_each_line_to_its_instance(netprof):
    line_a = (
        "/home/dodserver/dod-27015/serverfiles/dod/logs/L1.log:"
        "L 08/27/2026 - 13:00:02: [KTP_PROFILE] net: clients=6 unlag=1 "
        "lagcomp_off=0 ignorecmd_hits=0 drops=0 latzero=0 choke_peak=0 "
        "loss_worst=0 latency_worst=12.0ms jitter_worst=3.0ms"
    )
    line_b = (
        "/home/dodserver/dod-27016/serverfiles/dod/logs/L1.log:"
        "L 08/27/2026 - 13:05:02: [KTP_PROFILE] net: clients=4 unlag=1 "
        "lagcomp_off=0 ignorecmd_hits=0 drops=0 latzero=0 choke_peak=0 "
        "loss_worst=0 latency_worst=8.0ms jitter_worst=2.0ms"
    )
    v_a = netprof.parse(line_a)
    v_b = netprof.parse(line_b)
    assert v_a["_instance"] == "27015"
    assert v_b["_instance"] == "27016"
    assert v_a["_instance"] != v_b["_instance"]
    # The numeric fields must still parse correctly with the path prefix present.
    assert v_a["clients"] == 6.0
    assert v_b["clients"] == 4.0
    assert v_a["_time"] == "13:00:02"


def test_parse_falls_back_when_no_path_prefix(netprof):
    """A line with no `path:` prefix (e.g. hand-constructed in a test or a
    single-file grep match with no -H) must not crash -- and, critically, must
    not misparse the log line's OWN `HH:MM:SS` colons as a path separator.
    That would silently corrupt the timestamp and clients field alike."""
    line = (
        "L 08/27/2026 - 13:00:02: [KTP_PROFILE] net: clients=1 unlag=1 "
        "lagcomp_off=0 ignorecmd_hits=0 drops=0 latzero=0 choke_peak=0 "
        "loss_worst=0 latency_worst=1.0ms jitter_worst=1.0ms"
    )
    v = netprof.parse(line)
    assert v is not None
    assert v["_instance"] == "?"
    # The real regression: a naive split-on-first-colon eats "13" out of the
    # timestamp as a fake "path" and misses `clients=1` inside the corrupted
    # remainder.
    assert v["clients"] == 1.0
    assert v["_time"] == "13:00:02"


# --------------------------------------------------------- 3. non-cp1252 names

def test_report_lagcomp_survives_a_non_cp1252_name(netprof, monkeypatch):
    """Regression for: a raw print() of a player name crashed the whole
    report with UnicodeEncodeError on a Windows (cp1252) console."""
    lines = [
        "L 08/27/2026 - 13:00:00: event=LAGCOMP_SAMPLER_OK sid=STEAM_0:1:1 map=dod_anzio",
        "L 08/27/2026 - 13:00:01: event=LAGCOMP_OFF sid=STEAM_0:1:2 name=Тест ip=1.2.3.4 lc=0 lw=0",
    ]

    buf = io.BytesIO()
    fake_stdout = io.TextIOWrapper(buf, encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", fake_stdout)
    try:
        netprof.report_lagcomp({"atlanta": lines})
    finally:
        fake_stdout.flush()
        monkeypatch.undo()

    # The un-guarded print() reproduces this exact failure -- proving the test
    # would have caught the original defect, not just exercised the happy path.
    with pytest.raises(UnicodeEncodeError):
        print("name: Тест",
              file=io.TextIOWrapper(io.BytesIO(), encoding="cp1252", errors="strict"))


def test_report_lagcomp_prints_normally_on_a_utf8_console(netprof, capsys):
    """The safety net must not change output on the common (utf-8) path."""
    lines = [
        "L 08/27/2026 - 13:00:00: event=LAGCOMP_SAMPLER_OK sid=STEAM_0:1:1 map=dod_anzio",
        "L 08/27/2026 - 13:00:01: event=LAGCOMP_OFF sid=STEAM_0:1:2 name=Player1 ip=1.2.3.4 lc=0 lw=0",
    ]
    netprof.report_lagcomp({"atlanta": lines})
    out = capsys.readouterr().out
    assert "Player1" in out
    assert "LAGCOMP_OFF: 1" in out
