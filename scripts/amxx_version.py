#!/usr/bin/env python3
"""Read a plugin's version out of a compiled .amxx.

This was long believed impossible -- stage-runner.py's own error text said the
version "is not readable from a compiled .amxx", which is why the stager took it
as a typed argument nobody could verify. The belief came from `strings`/`grep`
returning nothing, and both really do: an .amxx is an XXMA container holding a
zlib-compressed AMX image, and Pawn stores strings one character per 32-bit cell,
so a byte-level search for "1.4.8" finds nothing even though it is certainly
there. Inflate the container and read cell-form and it comes straight out.

Anchoring is not optional. `register_plugin(NAME, VERSION, AUTHOR)` puts the
three literals adjacent in the data section, so the version is the cell-string
following the plugin's display name. Without that anchor ktp_cvar yields eleven
version-shaped strings -- 0.05, 0.5, 0.67, 1.809 and friends, all cvar threshold
literals -- and a bare regex picks one at random. Unanchored extraction is
offered, but it returns None on ambiguity rather than guessing.
"""
from __future__ import annotations

import re
import struct
import zlib

AMXX_MAGIC = 0x414D5858  # "XXMA"

# Display name as passed to register_plugin, keyed by the basename the runner
# holds. Third naming axis: project name, compiled filename and display name all
# differ (KTPCvarChecker -> ktp_cvar.amxx -> "KTP Cvar Checker").
PLUGIN_DISPLAY_NAMES = {
    "KTPMatchHandler.amxx": "KTP Match Handler",
    "KTPPracticeMode.amxx": "KTP Practice Mode",
    "KTPHudObserver.amxx": "KTP HUD Observer",
    "KTPAdminAudit.amxx": "KTP Admin Audit",
    "KTPScoreTracker.amxx": "KTP Score Tracker",
    "KTPGrenadeLoadout.amxx": "KTP Grenade Loadout",
    "KTPGrenadeDamage.amxx": "KTP Grenade Damage",
    "ktp_cvar.amxx": "KTP Cvar Checker",
    "ktp_file.amxx": "KTP File Checker",
}

_VERSION_RE = re.compile(r"\d+\.\d+(?:\.\d+)*(?:[-\w.]*)?$")


def inflate(path: str) -> list[bytes]:
    """Decompressed AMX images from an .amxx container. Empty list if not one."""
    with open(path, "rb") as fh:
        data = fh.read()
    if len(data) < 7 or struct.unpack_from("<I", data, 0)[0] != AMXX_MAGIC:
        return []
    images, off = [], 7
    for _ in range(data[6]):
        if off + 17 > len(data):
            break
        disksize, _imagesize, _memsize, offset = struct.unpack_from("<IIII", data, off + 1)
        off += 17
        try:
            images.append(zlib.decompress(data[offset:offset + disksize]))
        except zlib.error:
            continue  # a plugin that will not inflate simply contributes nothing
    return images


def _cell_form(text: str) -> bytes:
    return b"".join(bytes([ord(c), 0, 0, 0]) for c in text)


def _read_cell_string(image: bytes, pos: int, maxlen: int = 128) -> str:
    chars = []
    for i in range(pos, min(pos + maxlen * 4, len(image) - 3), 4):
        if image[i] == 0 or image[i + 1] or image[i + 2] or image[i + 3]:
            break
        chars.append(chr(image[i]))
    return "".join(chars)


def _version_after(image: bytes, display_name: str) -> str | None:
    anchor = _cell_form(display_name)
    idx = image.find(anchor)
    if idx < 0:
        return None
    pos = idx + len(anchor)
    while pos < len(image) - 3 and image[pos] == 0 and not (
        image[pos + 1] or image[pos + 2] or image[pos + 3]
    ):
        pos += 4
    candidate = _read_cell_string(image, pos)
    return candidate if _VERSION_RE.match(candidate) else None


def _sole_version(image: bytes) -> set[str]:
    found = set()
    for match in re.finditer(rb"(?:[0-9]\x00\x00\x00)(?:[0-9.]\x00\x00\x00)+", image):
        raw = match.group(0)
        text = "".join(chr(raw[i]) for i in range(0, len(raw), 4))
        if _VERSION_RE.match(text) and "." in text:
            found.add(text)
    return found


def extract_version(path: str, display_name: str | None = None) -> str | None:
    """Version from a compiled .amxx, or None if it cannot be established.

    With a display name the answer is anchored and unambiguous. Without one it
    is returned only when the artifact contains exactly one version-shaped
    string -- ambiguity yields None, never a guess.
    """
    images = inflate(path)
    if not images:
        return None
    if display_name:
        for image in images:
            found = _version_after(image, display_name)
            if found:
                return found
        return None
    candidates: set[str] = set()
    for image in images:
        candidates |= _sole_version(image)
    return candidates.pop() if len(candidates) == 1 else None


def extract_for_basename(path: str, basename: str) -> str | None:
    """Anchored on the display name registered for `basename`, when known."""
    return extract_version(path, PLUGIN_DISPLAY_NAMES.get(basename))
