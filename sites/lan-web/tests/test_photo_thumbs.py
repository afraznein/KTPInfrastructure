"""Thumbnails are a nicety, so every path here degrades rather than fails."""
from dataclasses import replace

import pytest

from app import config, photos


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "settings",
                        replace(config.settings, photo_dir=str(tmp_path), photo_thumb_px=64))
    monkeypatch.setattr(photos, "settings", config.settings)
    return tmp_path


def _png(path, size=(300, 200)):
    Image = pytest.importorskip("PIL.Image")
    Image.new("RGB", size, (90, 100, 40)).save(path, "PNG")


def test_a_thumbnail_is_made_and_is_smaller(store):
    _png(store / "000001.png")
    assert photos.make("000001.png") is True
    assert photos.has_thumb("000001.png")
    assert photos.thumb_path("000001.png").stat().st_size < (store / "000001.png").stat().st_size


def test_it_fits_inside_the_box(store):
    Image = pytest.importorskip("PIL.Image")
    _png(store / "000002.png", (1200, 400))
    photos.make("000002.png")
    with Image.open(photos.thumb_path("000002.png")) as im:
        assert max(im.size) <= 64


def test_a_missing_original_is_false_not_an_exception(store):
    assert photos.make("nope.png") is False
    assert photos.has_thumb("nope.png") is False


def test_a_corrupt_image_is_false_not_an_exception(store):
    (store / "000003.jpg").write_bytes(b"this is not an image")
    assert photos.make("000003.jpg") is False
    assert photos.has_thumb("000003.jpg") is False


def test_no_pillow_degrades_rather_than_breaking_uploads(store, monkeypatch):
    """The dependency is optional; without it an upload must still succeed."""
    import builtins
    real = builtins.__import__

    def no_pil(name, *a, **k):
        if name.startswith("PIL"):
            raise ImportError("no PIL")
        return real(name, *a, **k)

    _png(store / "000004.png")
    monkeypatch.setattr(builtins, "__import__", no_pil)
    assert photos.make("000004.png") is False


def test_thumb_path_never_collides_with_the_original(store):
    assert photos.thumb_path("000001.jpeg").name != "000001.jpeg"
    assert photos.thumb_path("000001.jpeg").name.endswith(photos.THUMB_SUFFIX)
