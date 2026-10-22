"""Offline tests for the one-shot --rederive switch in scripts/ktp-stats-export.py.

The site has honoured `rederive` since keep-the-prac#1008 -- `payload.ts`
accepts it and `ingest.ts` widens the re-derive list with it -- but nothing
produced it: the exporter greps zero for it on both the deployed copy and
origin/main, so dpl-833b's deliverable was unreachable rather than forgotten.

Two things are worth holding here, and neither is the flag's spelling:

  1. An ordinary export is byte-unchanged. If `rederive` leaked into every
     body, the site would re-derive every fixture on every tick, which costs
     reads and makes the flag meaningless.
  2. A re-derive is never filtered out by the sent-state dedup. The flag exists
     FOR the unchanged case, so a run that skips as "nothing new to export"
     would report success and do nothing -- the same silent shape as the field
     defaulting to false.
"""
import importlib.util
import sys
import types
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


def _args(**kw):
    base = dict(resend=False, dry_run=False, match_id=None, rederive=False)
    base.update(kw)
    return types.SimpleNamespace(**base)


class TestBuildPayload:
    def test_an_ordinary_export_carries_no_rederive_key_at_all(self, mod):
        body = mod.build_payload([{"gameMatchId": "1"}])
        assert "rederive" not in body
        assert sorted(body) == ["exportedAt", "matches", "source"]

    def test_the_flag_reaches_the_wire_when_asked_for(self, mod):
        body = mod.build_payload([{"gameMatchId": "1"}], rederive=True)
        assert body["rederive"] is True

    def test_the_matches_are_passed_through_untouched(self, mod):
        chunk = [{"gameMatchId": "1"}, {"gameMatchId": "2"}]
        assert mod.build_payload(chunk, rederive=True)["matches"] == chunk


class TestSkipsSentState:
    def test_an_ordinary_run_honours_the_dedup(self, mod):
        assert mod.skips_sent_state(_args()) is False

    def test_a_rederive_is_never_filtered_as_unchanged(self, mod):
        """The one that matters. A re-derive of an UNCHANGED payload is the
        entire use case, so the dedup must not swallow it."""
        assert mod.skips_sent_state(_args(rederive=True)) is True

    @pytest.mark.parametrize("flag,value", [
        ("resend", True), ("dry_run", True), ("match_id", "1790186507-NY1"),
    ])
    def test_the_pre_existing_bypasses_still_bypass(self, mod, flag, value):
        """Named separately so extracting this function cannot quietly drop one."""
        assert mod.skips_sent_state(_args(**{flag: value})) is True


class TestScoping:
    def test_rederive_without_a_match_id_is_refused_before_any_db_work(
            self, mod, monkeypatch):
        """Scoped by construction: re-deriving a whole window has no named
        beneficiary. The refusal must come BEFORE load_config/Db, so a
        mis-invocation cannot touch the database -- asserted by making both
        explode if reached."""
        def boom(*a, **k):
            raise AssertionError("reached the database on a refused invocation")

        monkeypatch.setattr(mod, "load_config", boom)
        monkeypatch.setattr(mod, "Db", boom)
        monkeypatch.setattr(sys, "argv", ["ktp-stats-export.py", "--rederive"])
        assert mod.main() == 2

    def test_rederive_with_a_match_id_gets_past_the_scope_guard(
            self, mod, monkeypatch):
        """The positive control for the test above: the same invocation plus
        --match-id is NOT refused, so that 2 means the guard and not something
        incidental."""
        reached = []

        def conf():
            reached.append("config")
            return {"STATS_INGEST_URL": "http://x", "STATS_INGEST_SECRET": "y"}

        def db(*a, **k):
            reached.append("db")
            raise SystemExit(99)

        monkeypatch.setattr(mod, "load_config", conf)
        monkeypatch.setattr(mod, "Db", db)
        monkeypatch.setattr(sys, "argv",
                            ["ktp-stats-export.py", "--rederive",
                             "--match-id", "1790186507-NY1"])
        with pytest.raises(SystemExit) as exc:
            mod.main()
        assert exc.value.code == 99
        assert reached == ["config", "db"]
