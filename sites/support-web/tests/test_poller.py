"""Poller tests.

The disclosure test is the important one here: `public.json` is served to anyone
on the internet, so a field leaking into it is a real exposure, not a cosmetic
bug. It asserts on the serialised bytes rather than on dict keys, because a
nested value would pass a key check and still ship the address.
"""

import json
import os

import pytest

from app import poller as P
from app.a2s import ServerInfo
from app.hostname import parse


def _ok(label, region, hostname, players=8, mx=13, bots=0, ip="10.9.8.7", port=27015):
    info = ServerInfo(hostname, "dod_donner", players, mx, bots)
    return {
        "instance": P.Instance(region, label, ip, port),
        "up": True, "degraded": False, "misses": 0,
        "info": info, "name": parse(hostname), "last_ok": 1000.0,
    }


def _down(label, region, misses=P.DOWN_AFTER, ip="10.9.8.7", port=27016):
    return {
        "instance": P.Instance(region, label, ip, port),
        "up": misses < P.DOWN_AFTER, "degraded": True, "misses": misses,
        "error": "timeout", "last_ok": 500.0,
    }


def test_fleet_is_24_instances_on_the_expected_ports():
    f = P.fleet()
    assert len(f) == 24
    assert sum(1 for i in f if i.region == "Chicago") == 4
    assert {i.port for i in f} <= {27015, 27016, 27017, 27018, 27019}
    assert max(i.port for i in f if i.region == "Chicago") == 27018


def test_public_document_carries_the_game_endpoint_and_nothing_else():
    """The one deliberate exception to the no-topology rule.

    Game endpoints are public by nature -- a player types `connect ip:port` to
    join, and the server browser lists them anyway. Everything else about the
    fleet stays out: internal service ports, unit names, miss counts, error
    strings, timestamps.
    """
    results = [
        _ok("Atlanta 1", "Atlanta", "KTP - Atlanta 1 - 12MAN - LIVE - 2ND HALF",
            ip="74.91.121.9", port=27015),
        _down("Dallas 2", "Dallas", ip="74.91.126.55", port=27016),
    ]
    doc = P.public_document(results)
    blob = json.dumps(doc)

    # Present, deliberately, and only as the connect field.
    assert doc["servers"][0]["connect"] == "74.91.121.9:27015"
    assert doc["servers"][1]["connect"] == "74.91.126.55:27016"

    # Still absent. `8087` is the HLTV API, which must never surface publicly.
    for secret in ("timeout", "misses", "last_ok", "address", "8087",
                   "hltv-api", "hltv-demo-renamer", ".service", "consecutive"):
        assert secret not in blob, f"public.json leaked {secret!r}"


def test_public_document_carries_map_players_and_match_state():
    doc = P.public_document(
        [_ok("Atlanta 1", "Atlanta", "KTP - Atlanta 1 - 12MAN - LIVE - 2ND HALF", players=9)]
    )
    s = doc["servers"][0]
    # max_players is 12, not the 13 A2S reports: one slot is the HLTV proxy's
    # and is reserved whether or not it is attached (see the capacity tests).
    assert s == {"region": "Atlanta", "label": "Atlanta 1", "up": True,
                 "connect": "10.9.8.7:27015",
                 "map": "dod_donner", "players": 9, "max_players": 12,
                 "match_type": "12MAN", "state": "LIVE - 2ND HALF"}


def test_idle_server_reports_no_match_fields():
    s = P.public_document([_ok("Denver 3", "Denver", "KTP - Denver 3")])["servers"][0]
    assert "match_type" not in s and "state" not in s
    assert s["map"] == "dod_donner"


def test_down_server_exposes_only_the_fact_that_it_is_down():
    s = P.public_document([_down("Dallas 2", "Dallas")])["servers"][0]
    # connect is still emitted -- the endpoint exists whether or not it answers,
    # and a player retrying is a reasonable thing to let them do.
    assert s == {"region": "Dallas", "label": "Dallas 2", "up": False,
                 "connect": "10.9.8.7:27016"}


def test_summary_counts_humans_not_slots():
    results = [_ok("A 1", "Atlanta", "KTP - Atlanta 1", players=5, bots=2),
               _ok("A 2", "Atlanta", "KTP - Atlanta 2", players=3, bots=0),
               _down("A 3", "Atlanta")]
    doc = P.public_document(results)
    assert doc["summary"] == {"up": 2, "total": 3, "players": 6}


def test_one_miss_is_not_down():
    assert P.public_document([_down("A 1", "Atlanta", misses=1)])["servers"][0]["up"] is True
    assert P.public_document([_down("A 1", "Atlanta", misses=2)])["servers"][0]["up"] is True
    assert P.public_document([_down("A 1", "Atlanta", misses=3)])["servers"][0]["up"] is False


def test_documents_are_timestamped_so_staleness_is_detectable():
    assert P.public_document([], now=1234)["generated"] == 1234
    assert P.detail_document([], now=1234)["generated"] == 1234


def test_detail_document_keeps_what_public_drops():
    blob = json.dumps(P.detail_document([_down("Dallas 2", "Dallas", ip="74.91.126.55")]))
    assert "74.91.126.55:27016" in blob and "timeout" in blob


def test_write_atomic_leaves_no_partial_file(tmp_path):
    target = tmp_path / "public.json"
    P.write_atomic(str(target), {"generated": 1, "servers": []})
    assert json.loads(target.read_text())["generated"] == 1
    P.write_atomic(str(target), {"generated": 2, "servers": []})
    assert json.loads(target.read_text())["generated"] == 2
    assert list(tmp_path.glob("*.tmp")) == []


def test_write_atomic_does_not_clobber_on_serialise_failure(tmp_path):
    target = tmp_path / "public.json"
    P.write_atomic(str(target), {"generated": 1})
    with pytest.raises(TypeError):
        P.write_atomic(str(target), {"bad": object()})
    assert json.loads(target.read_text())["generated"] == 1   # previous doc intact
    assert list(tmp_path.glob("*.tmp")) == []


def test_roster_count_wins_over_the_a2s_slot_count():
    # A2S says 1 (the HLTV proxy); the roster says 0 humans. The page must not
    # advertise a player on an empty server -- measured on production 2026-08-05.
    r = _ok("Dallas 1", "Dallas", "KTP - Dallas 1", players=1, bots=0)
    r["humans"] = 0
    assert P.public_document([r])["servers"][0]["players"] == 0


def test_falls_back_to_slot_count_when_the_roster_query_fails():
    r = _ok("Dallas 1", "Dallas", "KTP - Dallas 1", players=5, bots=0)
    r["humans"] = None
    assert P.public_document([r])["servers"][0]["players"] == 5


def test_summary_players_uses_the_roster_too():
    rs = []
    for i, humans in enumerate((0, 9, 0)):
        r = _ok(f"A {i}", "Atlanta", f"KTP - Atlanta {i}", players=humans + 1)
        r["humans"] = humans
        rs.append(r)
    assert P.public_document(rs)["summary"]["players"] == 9


def test_capacity_excludes_the_hltv_slot_and_flags_it():
    # A2S reports 13 slots, one of which the proxy holds. 12 people can join.
    r = _ok("Dallas 1", "Dallas", "KTP - Dallas 1", players=1, mx=13)
    r["humans"], r["hltv"] = 0, 1
    s = P.public_document([r])["servers"][0]
    assert (s["players"], s["max_players"], s["hltv"]) == (0, 12, True)


def test_capacity_holds_at_12_while_the_proxy_is_bouncing():
    # `hltv-restart.timer` bounces all 24 proxies at 03:00 and 11:00. Capacity
    # must not advertise the freed slot for those windows -- it is reserved,
    # not vacant. The flag still drops, because that one reports what is
    # actually attached.
    r = _ok("Dallas 1", "Dallas", "KTP - Dallas 1", players=0, mx=13)
    r["humans"], r["hltv"] = 0, 0
    s = P.public_document([r])["servers"][0]
    assert s["max_players"] == 12 and "hltv" not in s


def test_capacity_never_goes_negative_on_a_tiny_slot_count():
    r = _ok("Dallas 1", "Dallas", "KTP - Dallas 1", players=0, mx=0)
    r["humans"], r["hltv"] = 0, 0
    s = P.public_document([r])["servers"][0]
    assert s["max_players"] == 0


@pytest.mark.skipif(os.name != "posix", reason="Windows ignores POSIX file modes")
def test_write_atomic_applies_the_mode_it_was_given(tmp_path):
    import stat
    pub, det = tmp_path / "public.json", tmp_path / "detail.json"
    P.write_atomic(str(pub), {"generated": 1}, mode=0o644)
    P.write_atomic(str(det), {"generated": 1}, mode=0o600)
    # nginx serves public.json directly, so world-readable is required, not cosmetic.
    assert stat.S_IMODE(os.stat(pub).st_mode) & 0o044
    assert not stat.S_IMODE(os.stat(det).st_mode) & 0o077


def _hud_entry(**overrides):
    """A realistic /api/hq server entry, including fields that must NOT leak."""
    entry = {
        "hostname": "KTP - Atlanta 1",
        "status": "LIVE", "online": True,
        "lastEventAgeMs": 207, "totalEvents": 1455802,
        "map": "dod_armory_b6", "half": 2, "roundPhase": None, "phase": "live",
        "alliesScore": 3, "axisScore": 1,
        "timeleft": 616.46, "timerFrozen": False,
        "delayActive": True, "delaySeconds": 60,
        "flags": [{"flag_id": 0, "flag_name": "backalley", "owner": "allies"}],
        "allies": [{"user_id": "42", "name": "abe", "kills": 10, "deaths": 4}],
        "axis": [{"user_id": "77", "name": "zed", "kills": 7, "deaths": 9}],
        "playerCount": 2, "matchId": "m-123", "matchType": 2,
    }
    entry.update(overrides)
    return entry


def test_hud_match_block_is_allowlisted():
    """Rosters and scores are published on purpose; identifiers and topology
    must not ride along. Asserted on the serialised bytes, same as the main
    disclosure test, so a nested value cannot pass a key check and still ship."""
    results = [_ok("Atlanta 1", "Atlanta", "KTP - Atlanta 1 - KTP - LIVE - 2ND HALF")]
    hud = {"KTP - Atlanta 1": _hud_entry()}
    doc = P.public_document(results, hud=hud)
    blob = json.dumps(doc)

    m = doc["servers"][0]["match"]
    assert m == {
        "status": "LIVE", "phase": "live", "half": 2,
        "allies_score": 3, "axis_score": 1,
        "timeleft": 616.46, "timer_frozen": False, "delay_seconds": 60,
        "allies": [{"name": "abe", "kills": 10, "deaths": 4}],
        "axis": [{"name": "zed", "kills": 7, "deaths": 9}],
    }
    for secret in ("matchId", "m-123", "user_id", "totalEvents", "lastEventAgeMs",
                   "flag_name", "backalley", "playerCount"):
        assert secret not in blob, f"public.json leaked {secret!r}"


def test_hud_absent_or_down_adds_no_match_block():
    results = [_ok("Atlanta 1", "Atlanta", "KTP - Atlanta 1")]
    assert "match" not in P.public_document(results)["servers"][0]
    assert "match" not in P.public_document(results, hud={})["servers"][0]
    offline = {"KTP - Atlanta 1": _hud_entry(online=False)}
    assert "match" not in P.public_document(results, hud=offline)["servers"][0]


def test_hud_keying_strips_a_mid_match_hostname_rename():
    # The hud feed identifies servers by hostname, and KTPMatchHandler renames
    # the hostname during a match -- fetch_hud must key on the parsed base.
    class _Resp:
        def __init__(self, payload):
            self._p = payload
        def read(self):
            return self._p
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    payload = json.dumps({"generatedAt": "x", "servers": [
        _hud_entry(hostname="KTP - Atlanta 1 - 12MAN - LIVE - 1ST HALF"),
        _hud_entry(hostname="KTP - Denver 5"),
        {"no_hostname": True},
    ]}).encode()
    import urllib.request as _ur
    orig = _ur.urlopen
    _ur.urlopen = lambda url, timeout=None: _Resp(payload)
    try:
        hud = P.fetch_hud()
    finally:
        _ur.urlopen = orig
    assert set(hud) == {"KTP - Atlanta 1", "KTP - Denver 5"}


def test_fetch_hud_swallows_an_unreachable_backend():
    assert P.fetch_hud("http://127.0.0.1:9/api/hq", timeout=0.2) == {}


def test_hud_roster_tolerates_garbage_entries():
    junk = _hud_entry(allies=[{"name": "  "}, "not-a-dict",
                              {"name": "ok", "kills": None, "deaths": 3.5},
                              {"kills": 5}],
                      axis="not-a-list", half=True, delaySeconds="60")
    m = P._hud_match(junk)
    assert m["allies"] == [{"name": "ok", "kills": 0, "deaths": 0}]
    assert m["axis"] == []
    assert m["half"] is None          # bool is not a half number
    assert m["delay_seconds"] is None
