"""Class-limit cvars in the shipped DoD configs must be names the game DLL registers."""

from __future__ import annotations

import re

import pytest

from .conftest import CONFIG_ROOT

CFGS = sorted(CONFIG_ROOT.rglob("*.cfg"))


@pytest.mark.parametrize("path", CFGS, ids=[str(p.relative_to(CONFIG_ROOT)) for p in CFGS])
def test_piat_limit_uses_the_registered_name(path):
    # The DLL only knows mp_limitbritpiat; an unknown cvar is ignored, so the PIAT limit silently falls back to the default.
    text = path.read_text(encoding="utf-8", errors="replace")
    bad = re.findall(r"^\s*(mp_limit\w*piat)\b", text, re.M)
    assert all(name == "mp_limitbritpiat" for name in bad), f"{path.name}: {bad}"


def test_ktpbasic_allows_no_piat():
    text = (CONFIG_ROOT / "local" / "dod-configs" / "ktpbasic.cfg").read_text(encoding="utf-8")
    assert re.search(r"^mp_limitbritpiat 0\b", text, re.M)
