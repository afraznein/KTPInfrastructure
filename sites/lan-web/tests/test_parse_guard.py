"""isdigit() is not a guard for int(), everywhere the pattern appeared.

The three cases are not one failure, they are two. '²' is isdigit()-true and
int() RAISES on it — the 500. '٠' and '1٢3' are isdigit()-true and int()
SUCCEEDS, returning 0 and 123 — values nobody typed, landing in a discord_id.
The second half is the quiet one and it is why the guard is isascii() rather
than isdecimal().

Every test here carries a real-value control, because a guard that refuses
everything passes the rejection half and is still broken.
"""
from dataclasses import replace

import pytest

from app import auth, config, notify, parse
from app.routes import demo_routes
from conftest import sign_in

DID = 218890328273321984
REAL = "486227681885683721"          # jrod, the positive control everywhere below

CRASHES = "²"                        # isdigit() yes, int() raises
SILENT = {"٠": 0, "1٢3": 123}        # isdigit() yes, int() yes, wrong number
UNICODE_DIGITS = [CRASHES, *SILENT]
NOT_NUMBERS = ["", "  ", "not-a-number", "12x", "-1"]
BAD = UNICODE_DIGITS + NOT_NUMBERS


def test_the_premise_still_holds_in_this_python():
    """If a future Python narrowed isdigit(), every test below would pass for
    the wrong reason. Assert both traps exist before testing the guard."""
    assert CRASHES.isdigit()
    with pytest.raises(ValueError):
        int(CRASHES)
    for s, silently in SILENT.items():
        assert s.isdigit() and int(s) == silently, s


# ── the helper itself ─────────────────────────────────────────────────────
@pytest.mark.parametrize("bad", BAD)
def test_as_int_refuses_what_int_would_raise_on(bad):
    assert parse.as_int(bad) is None
    assert parse.as_int(bad, default=-7) == -7


def test_as_int_still_parses_a_real_number():
    assert parse.as_int(REAL) == int(REAL)
    assert parse.as_int("  4  ") == 4
    assert parse.snowflake(REAL) == int(REAL)
    assert parse.is_snowflake(REAL) is True


@pytest.mark.parametrize("bad", BAD)
def test_bounded_refuses_the_same_and_keeps_its_range(bad):
    assert parse.bounded(bad, 1, 5) is None


def test_bounded_accepts_inside_and_refuses_outside():
    assert parse.bounded("1", 1, 5) == 1 and parse.bounded("5", 1, 5) == 5
    assert parse.bounded("0", 1, 5) is None and parse.bounded("6", 1, 5) is None


# ── config: the allowlist parser runs at import, so this one is a crash ────
def test_the_admin_allowlist_survives_a_superscript_and_keeps_the_real_ids():
    assert config._parse_ids(f"² {REAL} ٠ 1٢3") == frozenset({int(REAL)})


def test_an_allowlist_of_nothing_but_rubbish_is_empty_not_an_exception():
    assert config._parse_ids("² ٠") == frozenset()


# ── auth.is_owner: a bad env value must not 500 every award-close ─────────
class _Req:
    def __init__(self, did):
        self.session = {"discord_id": did}


@pytest.mark.parametrize("bad", UNICODE_DIGITS)
def test_a_junk_owner_id_denies_rather_than_raising(monkeypatch, bad):
    monkeypatch.setattr(auth, "settings", replace(config.settings, owner_discord_id=bad))
    assert auth.is_owner(_Req(DID)) is False


def test_a_real_owner_id_still_matches(monkeypatch):
    monkeypatch.setattr(auth, "settings", replace(config.settings, owner_discord_id=REAL))
    assert auth.is_owner(_Req(int(REAL))) is True
    assert auth.is_owner(_Req(DID)) is False


# ── notify / relay: no int() here, so the failure was a bogus mention ─────
@pytest.mark.parametrize("bad", UNICODE_DIGITS)
def test_a_junk_ping_id_is_dropped_from_allowed_mentions(bad):
    assert notify.relay_payload("1", "hi", bad)["allowed_mentions"]["users"] == []


def test_a_real_ping_id_still_resolves():
    assert notify.relay_payload("1", "hi", REAL)["allowed_mentions"]["users"] == [REAL]


@pytest.mark.parametrize("bad", UNICODE_DIGITS)
def test_a_junk_announce_role_never_reaches_the_webhook(monkeypatch, bad):
    sent = {}
    monkeypatch.setattr(notify, "settings",
                        replace(config.settings, discord_webhook_url="http://x/",
                                discord_announce_role_id=bad))
    monkeypatch.setattr(notify.urllib.request, "urlopen",
                        lambda req, timeout=6: sent.setdefault("body", req.data) and None)
    notify.post_announcement("test")
    body = sent["body"].decode()
    assert bad not in body and '"roles": []' in body


# ── demo attach: 'sat:²' is a form value ─────────────────────────────────
@pytest.mark.parametrize("bad", UNICODE_DIGITS)
def test_a_junk_schedule_id_falls_through_instead_of_raising(bad):
    assert demo_routes._parse_match(f"sat:{bad}") == (None, None, "match")


def test_a_real_schedule_id_still_attaches():
    assert demo_routes._parse_match("sat:12") == (12, None, "match")


# ── the admin forms ───────────────────────────────────────────────────────
@pytest.fixture
def staff_db(fake_db):
    fake_db.add("FROM lan_admins ORDER BY added_at", [{"discord_id": DID, "label": "nein"}])
    fake_db.add("FROM lan_settings", None)
    return fake_db


@pytest.fixture
def staff(client, staff_db):
    sign_in(client, DID)
    return client


@pytest.mark.parametrize("bad", UNICODE_DIGITS)
def test_adding_a_player_with_a_junk_discord_id_stores_null(staff, staff_db, bad):
    r = staff.post("/admin/player/add",
                   data={"team_id": "3", "display_name": "nein",
                         "steam_id": "0:1", "discord_id": bad},
                   follow_redirects=False)
    assert r.status_code == 303
    assert staff_db.writes[0][1][2] is None            # discord_id column


def test_adding_a_player_with_a_real_discord_id_stores_it(staff, staff_db):
    r = staff.post("/admin/player/add",
                   data={"team_id": "3", "display_name": "nein",
                         "steam_id": "0:1", "discord_id": REAL},
                   follow_redirects=False)
    assert r.status_code == 303
    assert staff_db.writes[0][1][2] == int(REAL)


@pytest.mark.parametrize("bad", UNICODE_DIGITS)
def test_editing_a_player_with_a_junk_discord_id_clears_the_link(staff, staff_db, bad):
    staff_db.add("SELECT display_name, steam_id, discord_id FROM lan_players",
                 {"display_name": "nein", "steam_id": "STEAM_0:0:1", "discord_id": int(REAL)})
    r = staff.post("/admin/player/edit",
                   data={"player_id": "1", "display_name": "nein",
                         "steam_id": "0:1", "discord_id": bad},
                   follow_redirects=False)
    assert r.status_code == 303
    assert staff_db.writes[0][1][2] is None


@pytest.mark.parametrize("bad", UNICODE_DIGITS)
def test_a_junk_station_is_no_station_not_a_traceback(staff, staff_db, bad):
    staff_db.add("SELECT m.round, m.team_a_id", None)
    r = staff.post("/admin/schedule/station", data={"match_id": "12", "station": bad},
                   follow_redirects=False)
    assert r.status_code == 303
    assert staff_db.writes[0][1][0] is None            # station column


def test_a_real_station_still_lands(staff, staff_db):
    staff_db.add("SELECT m.round, m.team_a_id", None)
    r = staff.post("/admin/schedule/station", data={"match_id": "12", "station": "3"},
                   follow_redirects=False)
    assert r.status_code == 303
    assert staff_db.writes[0][1][0] == 3


@pytest.mark.parametrize("bad", UNICODE_DIGITS)
def test_a_junk_bracket_station_is_no_station(staff, staff_db, bad):
    staff_db.add("SELECT 1 FROM lan_bracket WHERE mkey", {"1": 1})
    r = staff.post("/admin/bracket/station", data={"mkey": "QF1", "station": bad},
                   follow_redirects=False)
    assert r.status_code == 303
    assert staff_db.writes[0][1][0] is None


@pytest.mark.parametrize("bad", UNICODE_DIGITS)
def test_a_junk_placement_is_skipped_and_the_real_ones_publish(staff, staff_db, bad):
    """Partial publish is deliberate, so a junk slot must skip — the control is
    that the ASCII slots either side of it still land, in order."""
    staff_db.add("SELECT COUNT(*) AS n FROM lan_teams", {"n": 3})
    r = staff.post("/admin/placements/set",
                   data={"place_1": "7", "place_2": bad, "place_3": "9"},
                   follow_redirects=False)
    assert r.status_code == 303
    assert staff_db.writes[0][1] == ("final_placements", "[7, 9]")
