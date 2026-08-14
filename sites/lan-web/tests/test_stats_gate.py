"""`stats_published` = 0 must mean the dataset is not in the bytes.

Every assertion here reads the served response body, because the failure this
guards against is silent: a strip that stops matching leaves the page rendering
normally, the data still in view-source, and nothing raising. Each absence
assertion is paired with the same assertion form finding the data where it
belongs — a test that reports ABSENT for everything is broken, not passing."""
import importlib
import json
import re
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config, site_gate
from conftest import sign_in

DID = 218890328273321984
PLAYER = "iH.hildebrand?"
DAMAGE = "42895"
# Everything else on the page, so a test can tell "stripped" from "broke it".
KEEP = ("RESULTS SECTION", "FEEDBACK SECTION")

PAGE_2026 = """<!doctype html>
<html lang="en"><head><title>Philly 2026</title></head>
<body data-stats="on" data-edition="philly-2026">
<nav><a href="#stats" data-stats-link data-ed="philly-2026">Stats</a></nav>
<section id="results" data-ed="philly-2026">RESULTS SECTION</section>
<section id="stats" data-ed="philly-2026"><table id="lb-table"></table></section>
<section id="feedback">FEEDBACK SECTION</section>
<script id="editions" type="application/json">{"default":"philly-2026",\
"order":["philly-2026","philly-2025"],"editions":{"philly-2026":{"label":"Philly 2026",\
"markup":true,"statsPublished":true},"philly-2025":{"label":"Philly 2025","href":"2025/"}}}</script>
<script id="lan-data" type="application/json">{"days":[{"key":"08-01","players":\
[{"n":"%s","k":305,"dm":%s}]}]}</script>
<script id="lanboard-data" type="application/json">{"teams":[["icyHOT","icyHOT"]]}</script>
<script id="player-names" type="application/json">{"%s":"hildebrand?"}</script>
<script id="awards-data" type="application/json">{"vote":[]}</script>
<script src="assets/site.js"></script></body></html>
""" % (PLAYER, DAMAGE, PLAYER)

PAGE_2025 = """<!doctype html>
<html lang="en"><head><title>Philly 2025</title></head>
<body data-stats="on" data-edition="philly-2025">
<section id="stats-25" data-ed="philly-2025">RESULTS SECTION FEEDBACK SECTION</section>
<script id="editions" type="application/json">{"default":"philly-2025",\
"order":["philly-2026","philly-2025"],"editions":{"philly-2025":{"label":"Philly 2025",\
"statsPublished":true},"philly-2026":{"label":"Philly 2026","href":"../"}}}</script>
<script id="lan-data-2025" type="application/json">{"days":[{"players":[{"n":"seanality"}]}]}</script>
</body></html>
"""

PAGE_NEXT = """<!doctype html>
<html lang="en"><head><title>Coming soon</title></head>
<body data-stats="on" data-edition="next">
<section id="soon">RESULTS SECTION FEEDBACK SECTION</section>
<script id="editions" type="application/json">{"default":"next","order":["next"],\
"editions":{"next":{"label":"Coming soon"}}}</script>
</body></html>
"""

# Every URL the mounts answer with the 2026 page: the root mount and the /2026
# one, each with and without the index filename.
ENTRY_URLS = ["/", "/index.html", "/2026/", "/2026/index.html"]


@pytest.fixture
def site(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "assets" / "site.js").write_text("//", encoding="utf-8")
    (dist / "index.html").write_text(PAGE_2026, encoding="utf-8")
    (dist / "2025").mkdir()
    (dist / "2025" / "index.html").write_text(PAGE_2025, encoding="utf-8")
    (dist / "next").mkdir()
    (dist / "next" / "index.html").write_text(PAGE_NEXT, encoding="utf-8")
    # A deploy backup really is sitting in the live docroot.
    (dist / "index.html.bak-pre-heading").write_text(PAGE_2026, encoding="utf-8")
    monkeypatch.setattr(config, "settings",
                        replace(config.settings, site_dir=str(dist), site_mount="/2026",
                                site_at_root=True))
    site_gate._cache.clear()
    import app.main
    return TestClient(importlib.reload(app.main).app)


@pytest.fixture
def flags(fake_db):
    """lan_settings and lan_admins, so the gate can be flipped either way."""
    fake_db.flags = {}
    fake_db.admins = []
    fake_db.add("FROM lan_admins ORDER BY added_at", lambda p: fake_db.admins)
    fake_db.add("FROM lan_settings WHERE k",
                lambda p: {"v": fake_db.flags[p[0]]} if p[0] in fake_db.flags else None)
    return fake_db


def as_staff(flags, client, did=DID):
    flags.admins = [{"discord_id": did, "label": "nein"}]
    sign_in(client, did)


def carries_dataset(text: str) -> bool:
    return PLAYER in text and DAMAGE in text


# ── the gate, on the served bytes ─────────────────────────────────────────
@pytest.mark.parametrize("url", ENTRY_URLS)
def test_unpublished_public_gets_no_dataset_on_any_entry_point(site, flags, url):
    r = site.get(url)
    assert r.status_code == 200
    assert PLAYER not in r.text, f"{url} still names a player"
    assert DAMAGE not in r.text, f"{url} still carries a stat value"
    assert 'id="lan-data"' not in r.text and 'id="lanboard-data"' not in r.text
    assert 'id="player-names"' not in r.text


@pytest.mark.parametrize("url", ENTRY_URLS)
def test_unpublished_staff_get_the_whole_page(site, flags, url):
    as_staff(flags, site)
    r = site.get(url)
    assert r.status_code == 200 and carries_dataset(r.text)


@pytest.mark.parametrize("url", ENTRY_URLS)
def test_published_public_get_the_whole_page(site, flags, url):
    flags.flags["stats_published"] = "1"
    r = site.get(url)
    assert r.status_code == 200 and carries_dataset(r.text)


@pytest.mark.parametrize("url", ENTRY_URLS)
def test_the_rest_of_the_page_survives_every_state(site, flags, url):
    """Tells "stripped" from "broke the page" — the sections either side of the
    board must be there whoever asks."""
    states = [(False, {}), (False, {"stats_published": "1"}), (True, {})]
    for staff, f in states:
        client = TestClient(site.app)
        flags.flags = dict(f)
        flags.admins = []
        if staff:
            as_staff(flags, client)
        r = client.get(url)
        assert r.status_code == 200, (url, staff, f)
        for keep in KEEP:
            assert keep in r.text, (url, staff, f, keep)


def test_a_signed_in_non_staff_player_is_still_public(site, flags):
    sign_in(site, 486227681885683721)
    assert not carries_dataset(site.get("/").text)


# ── the positive controls ─────────────────────────────────────────────────
def test_the_needles_are_in_the_page_this_test_gates(site, flags):
    """An absence assertion against data that was never there proves nothing."""
    flags.flags["stats_published"] = "1"
    body = site.get("/").text
    assert PLAYER in body and DAMAGE in body
    assert 'id="lan-data"' in body


def test_the_source_file_is_the_thing_being_served(site, flags):
    """Control on the fixture itself: the file on disk carries the dataset, so a
    stripped response is the route's doing and not an empty build."""
    src = Path(config.settings.site_dir, "index.html").read_text(encoding="utf-8")
    assert carries_dataset(src)


# ── degrading honestly ────────────────────────────────────────────────────
def test_the_stripped_page_still_gates_itself(site, flags):
    """The page re-applies the gate from #editions on load. Leave that saying
    published and the board renders empty, which reads as nobody scored."""
    body = site.get("/").text
    assert 'data-stats="off"' in body
    eds = json.loads(re.search(r'<script[^>]*id="editions"[^>]*>(.*?)</script>', body, re.S).group(1))
    assert eds["editions"]["philly-2026"]["statsPublished"] is False


def test_staff_see_the_page_ungated(site, flags):
    as_staff(flags, site)
    body = site.get("/").text
    assert 'data-stats="on"' in body
    eds = json.loads(re.search(r'<script[^>]*id="editions"[^>]*>(.*?)</script>', body, re.S).group(1))
    assert eds["editions"]["philly-2026"]["statsPublished"] is True


# ── the other editions ────────────────────────────────────────────────────
@pytest.mark.parametrize("url", ["/2025/", "/2025/index.html", "/2026/2025/"])
def test_philly_2025_keeps_its_own_board(site, flags, url):
    """A past event's published record, not what this flag governs — and the
    page's CSS gate cannot hide #stats-25, so withholding it would leave exactly
    the empty board this gate exists to avoid."""
    r = site.get(url)
    assert r.status_code == 200 and 'id="lan-data-2025"' in r.text
    assert '<body data-stats="on" data-edition="philly-2025">' in r.text


@pytest.mark.parametrize("prefix", ["", "/2026"])
def test_a_deploy_backup_in_the_docroot_is_gated_too(site, flags, prefix):
    """StaticFiles serves any file in the tree, so a copy of the page left beside
    it is a second door onto the same dataset."""
    url = prefix + "/index.html.bak-pre-heading"
    r = site.get(url)
    assert r.status_code == 200 and "RESULTS SECTION" in r.text
    assert not carries_dataset(r.text)


@pytest.mark.parametrize("url", ["/next/", "/next/index.html"])
def test_the_coming_soon_page_carries_no_dataset_either_way(site, flags, url):
    assert site.get(url).status_code == 200
    assert not carries_dataset(site.get(url).text)


# ── failing closed ────────────────────────────────────────────────────────
def test_a_strip_that_stops_matching_refuses_to_serve(site, flags, monkeypatch):
    """The whole point. A regex that no longer matches must not fail open — the
    page rendering normally with the data still in it is the silent failure."""
    monkeypatch.setattr(site_gate, "_drop_blocks", lambda html: html)
    r = site.get("/")
    assert r.status_code == 503
    assert not carries_dataset(r.text)


def test_staff_are_unaffected_by_a_broken_strip(site, flags, monkeypatch):
    """Control on the one above: the 503 is the gate refusing, not the route
    being broken for everybody."""
    monkeypatch.setattr(site_gate, "_drop_blocks", lambda html: html)
    as_staff(flags, site)
    assert site.get("/").status_code == 200


def test_a_dead_db_serves_the_public_page(site, flags, monkeypatch):
    from app import db
    monkeypatch.setattr(db, "query_one", lambda *a, **k: 1 / 0)
    monkeypatch.setattr(db, "query_all", lambda *a, **k: 1 / 0)
    r = site.get("/")
    assert r.status_code == 200 and not carries_dataset(r.text)


# ── caching ───────────────────────────────────────────────────────────────
def test_the_response_is_never_stored_by_a_shared_cache(site, flags):
    r = site.get("/")
    assert "no-store" in r.headers["cache-control"]
    assert "private" in r.headers["cache-control"]
    assert "Cookie" in r.headers["vary"]


def test_the_two_variants_do_not_share_a_cache_entry(site, flags):
    """Staff first, so a memo keyed on the file alone would hand the dataset to
    the public request behind it."""
    as_staff(flags, site)
    assert carries_dataset(site.get("/").text)
    anon = TestClient(site.app)
    assert not carries_dataset(anon.get("/").text)
    assert carries_dataset(site.get("/").text)


def test_the_page_is_stripped_once_per_build(site, flags, monkeypatch):
    calls = []
    real = site_gate.withhold
    monkeypatch.setattr(site_gate, "withhold",
                        lambda html: (calls.append(1), real(html))[1])
    for _ in range(3):
        site.get("/")
    assert len(calls) == 1


def test_a_rebuilt_page_invalidates_the_memo(site, flags):
    assert PLAYER not in site.get("/").text
    page = Path(config.settings.site_dir, "index.html")
    page.write_text(PAGE_2026.replace("RESULTS SECTION", "REBUILT SECTION"), encoding="utf-8")
    assert "REBUILT SECTION" in site.get("/").text


# ── the route must not swallow the app ────────────────────────────────────
def test_the_api_is_still_reachable(site, flags):
    assert site.get("/api/session").status_code == 200


def test_the_assets_still_come_off_the_mount(site, flags):
    assert site.get("/assets/site.js").status_code == 200


# ── against the real built page ───────────────────────────────────────────
REAL_DIST = Path(__file__).resolve().parents[2] / "wsdod-lan-2026" / "dist"


def _real(name):
    p = REAL_DIST / name
    if not p.is_file():
        pytest.skip(f"no built site at {p}")
    return p.read_text(encoding="utf-8")


def test_the_strip_matches_the_real_built_markup():
    """The fixture page is written to match; the shipped one is the one that can
    drift. Values below are read out of the real dataset, so this fails if the
    build stops emitting them rather than passing vacuously."""
    raw = _real("index.html")
    blocks = dict(re.findall(
        r'<script id="([a-z0-9_-]+)" type="application/json">(.*?)</script>', raw, re.S))
    data = json.loads(blocks["lan-data"])
    player = data["days"][0]["players"][0]
    name, damage = player["n"], str(player["dm"])
    assert name in raw and damage in raw          # control: present before the strip

    out = site_gate.withhold(raw)
    assert damage not in out, "a real stat value survived the strip"
    for block in site_gate.STATS_BLOCKS:
        assert f'id="{block}"' not in out
    assert 'data-stats="off"' in out
    assert "<section id=\"results\"" in out and "<section id=\"feedback\"" in out


def test_the_real_2025_page_is_left_alone():
    raw = _real("2025/index.html")
    assert site_gate.withhold(raw) == raw
