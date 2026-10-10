"""SteamID lookup in scripts/ktp-fastdl-indexes.py.

The generator opened no database before this lookup, so the join is the one way a
database problem could take the public demo archive down with it. These run the
generator end to end against a temp tree and a fake mysql client, and pin that every
failure costs only the lookup page while the rest of the archive renders as before.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / "scripts" / "ktp-fastdl-indexes.py"

pytestmark = pytest.mark.skipif(os.name == "nt", reason="needs pwd and an executable fake mysql")

DEMO_FILES = {
    "ATL4/ktp": ["ktp_1789348148-ATL4_h1-2609132101-dod_thunder2.dem",
                 "ktp_1789348148-ATL4_h2-2609132131-dod_thunder2.dem"],
    "ATL4/scrim": ["scrim_1789345548-ATL4-2609132010-dod_lennon5_b1.dem"],
    # Recorded by ATL1's HLTV for matches played on NY2, plus a reused queue placeholder id.
    "ATL1/12man": ["12man_1786480124-NY2-ATL1_h1-2608111628-dod_anzio.dem",
                   "12man_1.3-6411-NY2-ATL1_h1-2608072029-dod_armory_b6.dem",
                   "12man_1.3-confirm-NY2_h1-2607071915-dod_anzio.dem"],
}

ALPHA, BRAVO, CHARLIE, PLACEHOLDER = "0:192873300", "1:14524361", "0:2180052", "0:77934219"
ROWS = [
    ("1786480124-NY2", ALPHA, "alpha-old"),
    ("1.3-6411-NY2", CHARLIE, "charlie"),
    ("1.3-confirm-NY2", PLACEHOLDER, "placeholder"),
    ("1789348148-ATL4", ALPHA, "alpha"),
    ("1789348148-ATL4", BRAVO, "<b>bravo</b>"),
]

FAKE_MYSQL = """#!{python}
import os, sys, time
with open(os.environ["FAKE_MYSQL_LOG"], "a", encoding="utf-8") as fh:
    fh.write("\\x1f".join(sys.argv[1:]) + "\\n")
mode = os.environ.get("FAKE_MYSQL_MODE", "ok")
if mode == "fail":
    sys.stderr.write("ERROR 2002 (HY000): Can't connect to local MySQL server\\n")
    sys.exit(1)
if mode == "hang":
    time.sleep(30)
with open(os.environ["FAKE_MYSQL_ROWS"], encoding="utf-8") as fh:
    sys.stdout.write(fh.read())
"""


def row(match_id, steam_id, name):
    return "%s\t%s\t%s\n" % (match_id, steam_id, name.encode("utf-8").hex().upper())


class Site:
    def __init__(self, root: Path):
        self.root = root
        self.fastdl = root / "fastdl"
        self.demos = root / "demos"
        self.bin = root / "bin"
        self.log = root / "mysql.log"
        (self.fastdl / "dod" / "maps").mkdir(parents=True)
        (self.fastdl / "dod" / "maps" / "dod_anzio.bsp").write_bytes(b"bsp")
        # The overview pack is part of a clean run, so the tree carries its inputs too:
        # without them the generator warns, and this suite's whole point is a run that
        # warns about nothing. The pack itself is covered in test_fastdl_overview_pack.
        overviews = self.fastdl / "dod" / "overviews"
        overviews.mkdir()
        (overviews / "dod_anzio.txt").write_text("global\n{\n\tZOOM\t1.0\n}\n",
                                                 encoding="utf-8")
        (overviews / "dod_anzio.bmp").write_bytes(b"BM" + bytes(512))
        self.maps_ini = root / "ktp_maps.ini"
        self.maps_ini.write_text(
            "; ==========================================\n"
            "; SEASONAL MAPS (S10, in schedule order)\n"
            "; ==========================================\n\n"
            "[dod_anzio]\nconfig = ktp_anzio.cfg\nname = Anzio\ntype = competitive\n",
            encoding="utf-8")
        for sub, names in DEMO_FILES.items():
            d = self.demos / sub
            d.mkdir(parents=True)
            for n in names:
                (d / n).write_bytes(b"x" * 2048)
        self.bin.mkdir()
        fake = self.bin / "mysql"
        fake.write_text(FAKE_MYSQL.format(python=sys.executable), encoding="utf-8")
        fake.chmod(0o755)

    def run(self, mode="ok", rows=None, text=None, mysql_on_path=True, timeout="20", extra=()):
        rows_file = self.root / "rows.tsv"
        rows_file.write_text(text if text is not None
                             else "".join(row(*r) for r in (ROWS if rows is None else rows)),
                             encoding="utf-8")
        env = dict(os.environ, FAKE_MYSQL_MODE=mode, FAKE_MYSQL_ROWS=str(rows_file),
                   FAKE_MYSQL_LOG=str(self.log))
        empty = self.root / "empty-bin"
        empty.mkdir(exist_ok=True)
        env["PATH"] = str(self.bin if mysql_on_path else empty)
        start = time.monotonic()
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "--apply", "--fastdl", str(self.fastdl),
             "--demos", str(self.demos), "--db-timeout", timeout,
             "--maps-ini", str(self.maps_ini), *extra],
            env=env, capture_output=True, text=True, timeout=90)
        proc.elapsed = time.monotonic() - start
        return proc

    @property
    def players_page(self) -> Path:
        return self.demos / "players.html"

    def pages(self):
        """Every generated page, keyed by path, with the build timestamp removed."""
        found = {}
        for base in (self.fastdl, self.demos):
            for p in base.rglob("*.html"):
                found[str(p.relative_to(self.root))] = re.sub(
                    r"File list updated [^<]*\.", "", p.read_text(encoding="utf-8"))
        return found


def player_data(site: Site):
    m = re.search(r'<script id="pdata" type="application/json">(.*?)</script>',
                  site.players_page.read_text(encoding="utf-8"), re.S)
    assert m, "players.html carries no embedded lookup data"
    data = json.loads(m.group(1))
    return {p[1]: p for p in data["players"]}, data["demos"]


def hrefs_for(site, steam_display):
    players, demos = player_data(site)
    return [demos[i][0] for i in players[steam_display][5]]


def archive_index_entries(site: Site):
    text = (site.demos / "index.html").read_text(encoding="utf-8")
    m = re.search(r'<script id="gsdata" type="application/json">(.*?)</script>', text, re.S)
    return [e[1] for e in json.loads(m.group(1))]


@pytest.fixture
def site(tmp_path):
    return Site(tmp_path / "site")


def test_lookup_links_each_steam_id_to_its_demos(site):
    proc = site.run()
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "WARNING" not in proc.stdout
    players, _ = player_data(site)

    alpha = players["STEAM_0:" + ALPHA]
    assert alpha[2] == "76561198346012328"
    assert alpha[3] == "alpha", "display name must be the newest one"
    assert "alpha-old" in alpha[4]
    assert hrefs_for(site, "STEAM_0:" + ALPHA) == [
        "/demos/ATL4/ktp/ktp_1789348148-ATL4_h2-2609132131-dod_thunder2.dem",
        "/demos/ATL4/ktp/ktp_1789348148-ATL4_h1-2609132101-dod_thunder2.dem",
        "/demos/ATL1/12man/12man_1786480124-NY2-ATL1_h1-2608111628-dod_anzio.dem",
    ]
    for spelling in ("steam_0:" + ALPHA, "steam_1:" + ALPHA, ALPHA, "76561198346012328", "alpha-old"):
        assert spelling in alpha[0]

    assert '/demos/players.html' in (site.demos / "index.html").read_text(encoding="utf-8")


def test_one_read_only_query_per_run(site):
    assert site.run().returncode == 0
    calls = site.log.read_text(encoding="utf-8").splitlines()
    assert len(calls) == 1
    query = next(a for a in calls[0].split("\x1f") if "ktp_match_players" in a)
    assert query.lstrip().upper().startswith("SELECT")
    assert not re.search(r"\b(INSERT|UPDATE|DELETE|REPLACE|DROP|ALTER|CREATE)\b", query, re.I)


def test_cross_server_recording_joins_on_the_match_server(site):
    assert site.run().returncode == 0
    assert hrefs_for(site, "STEAM_0:" + CHARLIE) == [
        "/demos/ATL1/12man/12man_1.3-6411-NY2-ATL1_h1-2608072029-dod_armory_b6.dem"]


def test_placeholder_match_id_never_joins(site):
    assert site.run().returncode == 0
    players, demos = player_data(site)
    assert "STEAM_0:" + PLACEHOLDER not in players
    assert not any("1.3-confirm" in d[0] for d in demos)
    assert not any("placeholder" in p[0] for p in players.values())


def test_demo_without_players_still_appears(site):
    assert site.run().returncode == 0
    scrim = "/demos/ATL4/scrim/scrim_1789345548-ATL4-2609132010-dod_lennon5_b1.dem"
    assert scrim in archive_index_entries(site)
    assert "scrim_1789345548" in (site.demos / "ATL4" / "scrim" / "index.html").read_text(encoding="utf-8")
    _, demos = player_data(site)
    assert scrim not in [d[0] for d in demos]


def test_player_names_are_escaped(site):
    assert site.run().returncode == 0
    page = site.players_page.read_text(encoding="utf-8")
    assert "<b>bravo</b>" not in page
    players, _ = player_data(site)
    assert players["STEAM_0:" + BRAVO][3] == "&lt;b&gt;bravo&lt;/b&gt;"


def test_malformed_rows_are_skipped(site):
    text = ("only\ttwo\n"
            + "1789348148-ATL4\tSTEAM_ID_LAN\t414243\n"
            + "1789348148-ATL4\t0:555\tZZ-not-hex\n"
            + "1789348148-ATL4\t0:1:2\t41\n"
            + row("1789348148-ATL4", ALPHA, "alpha"))
    proc = site.run(text=text)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    players, _ = player_data(site)
    assert list(players) == ["STEAM_0:" + ALPHA]
    assert "malformed" in proc.stdout


FAILURES = {
    "exits-nonzero": dict(mode="fail"),
    "times-out": dict(mode="hang", timeout="1"),
    "client-missing": dict(mysql_on_path=False),
    "no-rows": dict(rows=[]),
    "only-garbage": dict(text="<html>proxy error</html>\n\n"),
    "nothing-joins": dict(rows=[("1700000000-DEN1", ALPHA, "nobody")]),
}


@pytest.mark.parametrize("failure", sorted(FAILURES))
def test_database_failure_keeps_the_archive_and_omits_the_lookup(tmp_path, failure):
    good = Site(tmp_path / "good")
    assert good.run().returncode == 0
    bad = Site(tmp_path / "bad")
    bad.players_page.write_text("stale roster from an earlier run", encoding="utf-8")

    proc = bad.run(**FAILURES[failure])

    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "WARNING: player index omitted" in proc.stdout
    assert proc.elapsed < 20
    assert not bad.players_page.exists(), "an earlier roster must not outlive a failed read"

    good_pages, bad_pages = good.pages(), bad.pages()
    good_pages.pop("demos/players.html")
    assert set(bad_pages) == set(good_pages)
    for name, text in good_pages.items():
        if name == "demos/index.html":
            continue
        assert bad_pages[name] == text, name
    assert archive_index_entries(bad) == archive_index_entries(good)
    assert "players.html" not in (bad.demos / "index.html").read_text(encoding="utf-8")


def test_out_root_writes_nothing_in_place(site, tmp_path):
    out = tmp_path / "out"
    proc = site.run(extra=("--out-root", str(out)))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert not list(site.demos.rglob("*.html"))
    assert not list(site.fastdl.rglob("*.html"))
    mirrored = out / str(site.demos).lstrip("/")
    assert (mirrored / "players.html").is_file()
    assert (mirrored / "index.html").is_file()
