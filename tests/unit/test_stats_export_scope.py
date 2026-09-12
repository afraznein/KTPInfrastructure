"""Offline tests for scripts/ktp-stats-export.py's scope and resend guard.

Two defects this covers, both seen in production on 2026-09-12: the 48-hour
window carried every match type, so pracc and 12-man play reached the site as
results; and nothing recorded what had been sent, so the same 26 matches were
re-POSTed every ten minutes for the endpoint to answer "unchanged".
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "ktp-stats-export.py"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("_ktp_stats_export", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class _Db:
    """Captures the SQL instead of running it."""

    def __init__(self):
        self.sql = []

    def json_rows(self, sql):
        self.sql.append(sql)
        return []


def test_official_types_match_the_report_pipeline(mod):
    """The duplicate constant must not drift from its canonical copy."""
    sys.path.insert(0, str(REPO))
    from scripts.report_scope import OFFICIAL_MATCH_TYPES
    assert mod.OFFICIAL_MATCH_TYPES == OFFICIAL_MATCH_TYPES


def test_window_is_league_play_only(mod):
    db = _Db()
    mod.fetch_matches(db, 48, None)
    where = db.sql[0]
    assert "match_type in (0, 4)" in where
    assert "interval 48 hour" in where


def test_explicit_match_id_ignores_the_type_filter(mod):
    """An operator asking for one match by id means that match, whatever it is."""
    db = _Db()
    mod.fetch_matches(db, 48, "1.3-6776-NY1")
    assert "match_type" not in db.sql[0]
    assert "1.3-6776-NY1" in db.sql[0]


def test_digest_is_stable_and_content_sensitive(mod):
    a = {"gameMatchId": "m1", "players": [{"k": 1}]}
    assert mod.payload_digest(a) == mod.payload_digest(dict(a))
    assert mod.payload_digest(a) != mod.payload_digest(
        {"gameMatchId": "m1", "players": [{"k": 2}]})


def test_state_round_trips(mod, tmp_path, monkeypatch):
    path = tmp_path / "nested" / "sent.json"
    monkeypatch.setattr(mod, "STATE_PATH", str(path))
    mod.save_sent({"m1": "abc"})
    assert mod.load_sent() == {"m1": "abc"}


def test_unreadable_state_is_empty_not_an_error(mod, tmp_path, monkeypatch):
    """A missing or corrupt file costs a redundant POST, never a lost match."""
    path = tmp_path / "sent.json"
    monkeypatch.setattr(mod, "STATE_PATH", str(path))
    assert mod.load_sent() == {}
    path.write_text("{ not json", encoding="utf-8")
    assert mod.load_sent() == {}
    path.write_text('["a list"]', encoding="utf-8")
    assert mod.load_sent() == {}


def test_unwritable_state_warns_and_does_not_raise(mod, tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "STATE_PATH", str(tmp_path / "sent.json"))
    monkeypatch.setattr(mod.os, "replace",
                        lambda *a: (_ for _ in ()).throw(OSError("read-only")))
    mod.save_sent({"m1": "abc"})  # must not raise


def test_state_file_is_json_object_keyed_by_match(mod, tmp_path, monkeypatch):
    path = tmp_path / "sent.json"
    monkeypatch.setattr(mod, "STATE_PATH", str(path))
    mod.save_sent({"1.3-6776-NY1": "deadbeef"})
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "1.3-6776-NY1": "deadbeef"}
