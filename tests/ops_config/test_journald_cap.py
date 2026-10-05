"""Guard the tracked copy of the data server's journald size-cap drop-in."""

from __future__ import annotations

import configparser
from pathlib import Path

DROPIN = (
    Path(__file__).resolve().parents[2]
    / "ops" / "data-server" / "journald.conf.d" / "10-ktp-size-cap.conf"
)


def _journal_section() -> dict[str, str]:
    cp = configparser.ConfigParser(interpolation=None)
    cp.optionxform = str
    cp.read_string(DROPIN.read_text(encoding="utf-8"))
    return dict(cp["Journal"])


def test_max_use_is_8g() -> None:
    assert _journal_section()["SystemMaxUse"] == "8G"


def test_keep_free_is_set_and_below_max_use() -> None:
    assert _journal_section()["SystemKeepFree"] == "2G"


def test_comment_carries_no_dated_count() -> None:
    comments = [l for l in DROPIN.read_text().splitlines() if l.startswith("#")]
    assert comments
    assert not any("MB/day" in l or "roughly 4 days" in l for l in comments)
