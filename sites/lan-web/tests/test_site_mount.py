"""The rebuilt WSDoD site is served by this app so that OAuth, the session
cookie and the upload endpoints stay same-origin with it."""
import importlib
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app import config


@pytest.fixture
def mounted(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<h1>2026</h1>", encoding="utf-8")
    (dist / "assets" / "site.css").write_text("body{}", encoding="utf-8")
    (dist / "2025").mkdir()
    (dist / "2025" / "index.html").write_text("<h1>2025</h1>", encoding="utf-8")
    monkeypatch.setattr(config, "settings",
                        replace(config.settings, site_dir=str(dist), site_mount="/2026"))
    import app.main
    return TestClient(importlib.reload(app.main).app)


def test_the_site_is_served_at_its_mount(mounted):
    r = mounted.get("/2026/")
    assert r.status_code == 200 and "2026" in r.text


def test_nested_editions_and_assets_resolve(mounted):
    assert "2025" in mounted.get("/2026/2025/").text
    assert mounted.get("/2026/assets/site.css").status_code == 200


def test_the_old_site_still_owns_the_root(mounted):
    """The preview mount must not shadow what is live today."""
    assert mounted.get("/2026/").status_code == 200
    assert mounted.get("/").status_code != 404


def test_the_api_is_not_shadowed_by_the_mount(mounted):
    """Same-origin is the whole point — these must still answer under it."""
    assert mounted.get("/api/session").status_code == 200


def test_unset_site_dir_mounts_nothing(monkeypatch):
    """Control: without the setting the app must be exactly as it was, so this
    cannot half-apply on a host where the build was never copied up."""
    monkeypatch.setattr(config, "settings", replace(config.settings, site_dir=""))
    import app.main
    client = TestClient(importlib.reload(app.main).app)
    assert client.get("/2026/").status_code == 404
    assert client.get("/api/session").status_code == 200
