"""Gallery thumbnails.

The originals are phone photos — the three filed at Philly average 12 MB — and
the site's grid was loading every one of them at full size. A thumbnail is
generated next to the original on upload.

Everything here is best-effort on purpose: Pillow is an optional dependency and
a thumbnail is a nicety, so a failure must never cost someone their upload. When
there is no thumbnail the API omits the field and the grid falls back to the
original, which is exactly the behaviour that existed before."""
from __future__ import annotations

from pathlib import Path

from .config import settings

# jpeg for photographs; the source may be webp/png but the thumb needn't match.
THUMB_SUFFIX = "-thumb.jpg"


def thumb_path(stored_name: str) -> Path:
    """Where a given photo's thumbnail lives, whether or not it exists."""
    stem = Path(stored_name).stem
    return Path(settings.photo_dir) / f"{stem}{THUMB_SUFFIX}"


def make(stored_name: str) -> bool:
    """Generate the thumbnail. False if it could not be made, never raises."""
    src = Path(settings.photo_dir) / stored_name
    if not src.is_file():
        return False
    try:
        from PIL import Image, ImageOps
    except ImportError:
        return False
    try:
        with Image.open(src) as im:
            # Phone photos carry rotation in EXIF; without this the thumb is
            # sideways while the full-size view looks right.
            im = ImageOps.exif_transpose(im)
            im.thumbnail((settings.photo_thumb_px, settings.photo_thumb_px))
            if im.mode not in ("RGB", "L"):
                im = im.convert("RGB")
            im.save(thumb_path(stored_name), "JPEG", quality=82, optimize=True)
        return True
    except Exception:
        return False


def has_thumb(stored_name: str) -> bool:
    return bool(stored_name) and thumb_path(stored_name).is_file()
