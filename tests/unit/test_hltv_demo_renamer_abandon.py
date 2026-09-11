"""Abandon-path tests for scripts/hltv-demo-renamer.py.

The plugin sends MATCH_WINDOW_CLOSE only at match end, so a cancelled or
force-reset match leaves its window open. The renamer used to drop such a window
at the abandon timeout without renaming anything, and the cleanup sweep then
deleted the demo. These drive the service's ingest and process steps against a
temp demos dir and a fake clock -- no SSH, no real files outside tmp_path.
"""
from __future__ import annotations

import importlib.util
import logging
import os
import re
import sys
import types
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "hltv-demo-renamer.py"
ORGANIZER = ROOT / "scripts" / "ktp-organize-hltv-demos.sh"

T0 = 1789000000
ABANDON = 4 * 3600


def _load():
    try:
        import paramiko  # noqa: F401
    except ImportError:
        # CI installs pytest only; the tailer is never instantiated here.
        sys.modules["paramiko"] = types.ModuleType("paramiko")
    spec = importlib.util.spec_from_file_location("hltv_demo_renamer_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class Harness:
    def __init__(self, mod, demos: Path):
        self.mod = mod
        self.demos = demos
        self.now = T0
        svc = mod.Service.__new__(mod.Service)
        svc.state = mod.State()
        svc.renamer = mod.Renamer()
        svc._stop = False
        self.svc = svc

    def demo(self, friendly: str, started: int, last_write: int, map_: str) -> Path:
        stamp = datetime.fromtimestamp(started).strftime("%y%m%d%H%M")
        p = self.demos / f"auto_{friendly}-{stamp}-{map_}.dem"
        p.write_bytes(b"x")
        os.utime(p, (last_write, last_write))
        return p

    def touch(self, p: Path, last_write: int) -> None:
        os.utime(p, (last_write, last_write))

    def open(self, match, half, port, t, mtype="12man", map_="dod_harrington"):
        self.svc._ingest_lines([
            f"L 09/09/2026 - 20:54:06: [KTPHLTVRecorder.amxx] [KTP HLTV] MATCH_WINDOW_OPEN "
            f"match_id={match} half={half} match_type={mtype} map={map_} hltv_port={port} "
            f"wall_time={t} enabled=1"
        ])

    def close(self, match, port, t, mtype="12man", map_="dod_harrington"):
        self.svc._ingest_lines([
            f"L 09/09/2026 - 21:37:45: [KTPHLTVRecorder.amxx] [KTP HLTV] MATCH_WINDOW_CLOSE "
            f"match_id={match} match_type={mtype} map={map_} hltv_port={port} "
            f"wall_time={t} score=1-0"
        ])

    def process(self, now: int) -> None:
        self.now = now
        self.svc._process_closed_windows()

    def names(self) -> list[str]:
        return sorted(p.name for p in self.demos.iterdir())


@pytest.fixture
def h(tmp_path, monkeypatch):
    mod = _load()
    harness = Harness(mod, tmp_path)
    monkeypatch.setattr(mod, "DEMOS_DIR", tmp_path)
    monkeypatch.setattr(mod, "time", types.SimpleNamespace(time=lambda: harness.now))
    return harness


def _stamp(t: int) -> str:
    return datetime.fromtimestamp(t).strftime("%y%m%d%H%M")


def test_cancelled_half_is_renamed_when_the_next_match_opens(h):
    # 1.3-6704-NY1 shape: h1 played, h2 never started, a different match followed.
    f = h.demo("ny1", T0, T0 + 1500, "dod_harrington")
    g = h.demo("ny1", T0 + 1800, T0 + 1900, "dod_harrington")
    h.open("1.3-6704-NY1", "h1", 27035, T0)
    h.open("1.3-6706-NY1", "h1", 27035, T0 + 1800)
    h.process(T0 + 1900)

    assert f"12man_1.3-6704-NY1-{_stamp(T0)}-dod_harrington.dem" in h.names()
    assert g.exists(), "the later match's live recording must not be taken"
    assert [w.match_id for w in h.svc.state.open_windows] == ["1.3-6706-NY1"]


def test_false_start_claims_nothing_from_the_real_match(h):
    # 1789004811-DAL1 was a false start re-generated as 1789005000-DAL1, whose h1
    # recording began before the new OPEN and ran long past it.
    f = h.demo("dal1", T0 + 120, T0 + 300, "dod_lennon5_b1")
    h.open("1789004811-DAL1", "h1", 27025, T0, "scrim", "dod_lennon5_b1")
    h.open("1789005000-DAL1", "h1", 27025, T0 + 215, "scrim", "dod_lennon5_b1")
    h.process(T0 + 300)  # the orphan defers on F while HLTV is still writing it

    h.touch(f, T0 + 1200)
    g = h.demo("dal1", T0 + 1200, T0 + 2400, "dod_lennon5_b1")
    h.demo("dal1", T0 + 2400, T0 + 2500, "dod_lennon5_b1")
    h.open("1789005000-DAL1", "h2", 27025, T0 + 1200, "scrim", "dod_lennon5_b1")
    h.close("1789005000-DAL1", 27025, T0 + 2400, "scrim", "dod_lennon5_b1")
    h.process(T0 + 2500)
    h.process(T0 + 2500 + ABANDON + 1)

    names = h.names()
    assert not any("1789004811" in n for n in names), names
    assert f"scrim_1789005000-DAL1_h1-{_stamp(T0 + 120)}-dod_lennon5_b1.dem" in names
    assert f"scrim_1789005000-DAL1_h2-{_stamp(T0 + 1200)}-dod_lennon5_b1.dem" in names
    assert not g.exists()
    assert h.svc.state.open_windows == []


def test_stale_abandon_flushes_only_the_recording_live_at_open(h):
    # 1.3-6706-NY1 shape: h1 played, h2 never started, nothing followed on the port.
    before = h.demo("ny1", T0 - 3000, T0 - 200, "dod_harrington")
    live = h.demo("ny1", T0 - 60, T0 + 2000, "dod_harrington")
    idle1 = h.demo("ny1", T0 + 2000, T0 + 4000, "dod_anzio")
    idle2 = h.demo("ny1", T0 + 4000, T0 + ABANDON, "dod_anzio")
    h.open("1.3-6706-NY1", "h1", 27035, T0)
    h.process(T0 + ABANDON + 1)

    assert f"12man_1.3-6706-NY1-{_stamp(T0 - 60)}-dod_harrington.dem" in h.names()
    assert not live.exists()
    assert before.exists() and idle1.exists() and idle2.exists()
    assert h.svc.state.open_windows == []


def test_stale_abandon_never_reclaims_an_already_renamed_demo(h):
    done = h.demos / f"12man_1.3-9999-NY1_h1-{_stamp(T0)}-dod_harrington.dem"
    done.write_bytes(b"x")
    os.utime(done, (T0 + 1500, T0 + 1500))
    h.open("1.3-7000-NY1", "h1", 27035, T0)
    h.process(T0 + ABANDON + 1)

    assert h.names() == [done.name]
    assert h.svc.state.open_windows == []


def test_normal_match_is_unchanged(h):
    f1 = h.demo("atl1", T0, T0 + 1300, "dod_railroad2_s9a")
    f2 = h.demo("atl1", T0 + 1300, T0 + 2600, "dod_railroad2_s9a")
    f3 = h.demo("atl1", T0 + 2600, T0 + 2700, "dod_railroad2_s9a")
    h.open("1.3-6783-ATL1", "h1", 27020, T0, map_="dod_railroad2_s9a")
    h.open("1.3-6783-ATL1", "h2", 27020, T0 + 1300, map_="dod_railroad2_s9a")
    h.close("1.3-6783-ATL1", 27020, T0 + 2600, map_="dod_railroad2_s9a")
    h.process(T0 + 2700)

    names = h.names()
    assert f"12man_1.3-6783-ATL1_h1-{_stamp(T0)}-dod_railroad2_s9a.dem" in names
    assert f"12man_1.3-6783-ATL1_h2-{_stamp(T0 + 1300)}-dod_railroad2_s9a.dem" in names
    assert f3.exists() and not f1.exists() and not f2.exists()
    assert not any(w.orphaned for w in h.svc.state.open_windows)


def test_no_candidate_is_a_warning(h, caplog):
    h.open("1.3-6774-ATL1", "h1", 27020, T0)
    h.close("1.3-6774-ATL1", 27020, T0 + 1300)
    with caplog.at_level(logging.INFO):
        h.process(T0 + 1400)
    hits = [r for r in caplog.records if "no matching auto-* files" in r.getMessage()]
    assert hits and all(r.levelno == logging.WARNING for r in hits)


_BRANCH = re.compile(r'\[\[\s*"\$demo"\s*=~\s*(\^\S+\$)\s*\]\]')


@pytest.mark.parametrize("window_args, friendly", [
    (("1.3-6704-NY1", "h1", "12man"), "NY1"),
    (("1789004811-DAL1", "h1", "scrim"), "DAL1"),
    (("1.3-q12man-ATL3", "h2", "12man"), "ATL3"),
])
def test_half_less_names_are_filed_by_the_organizer(h, window_args, friendly):
    match_id, half, mtype = window_args
    w = h.mod.OpenWindow(hltv_port=27020, match_id=match_id, half=half,
                         match_type=mtype, map="dod_harrington", open_unix=T0)
    name = h.mod.Renamer._build_target_name(w, friendly, _stamp(T0), "dod_harrington",
                                            segment=0, omit_half=True)
    assert "_h1" not in name and "_h2" not in name
    pats = _BRANCH.findall(ORGANIZER.read_text(encoding="utf-8"))
    assert len(pats) >= 5, "organizer branch patterns not extracted"
    hit = next((re.fullmatch(p, name) for p in pats if re.fullmatch(p, name)), None)
    assert hit is not None, f"organizer would skip {name}"
    assert friendly in hit.groups(), f"filed under the wrong host: {hit.groups()}"
