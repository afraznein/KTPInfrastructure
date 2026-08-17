"""The team, player, award, photo and station mutations that changed things
without leaving a record — and the form ids they read straight off a subscript.

The rules every case here holds to, the same ones the ten already-converted
routes hold to: the record shares the mutation's transaction, and nothing logs a
no-op. A row asserting a change that did not happen is a failure this log has
had once already.

The one that mattered: DELETE FROM lan_teams cascades the roster, so the team
delete took a whole squad out with nothing to show it."""
import pytest

from app import bracket
from app import schedule as sched
from conftest import sign_in

ME = 218890328273321984

JUNK = ["", "²", "٠", "1٢3", "nope", "-1"]


@pytest.fixture
def staff_db(fake_db, monkeypatch):
    fake_db.admins = [{"discord_id": ME, "label": "nein", "added_at": None}]
    fake_db.add("FROM lan_admins ORDER BY added_at", lambda p: fake_db.admins)
    fake_db.add("FROM lan_players p", [])
    monkeypatch.setattr(sched, "get_matches", lambda: [])
    monkeypatch.setattr(bracket, "get_bracket", lambda: [])
    return fake_db


@pytest.fixture
def staff(client, staff_db):
    sign_in(client, ME)
    return client


def audit_rows(fdb):
    return [p for sql, p in fdb.writes if sql.startswith("INSERT INTO lan_admin_audit")]


def one_audit(fdb):
    rows = audit_rows(fdb)
    assert len(rows) == 1, rows
    return rows[0]              # (actor, actor_name, action, target, old, new)


def post(c, path, **data):
    return c.post(path, data=data, follow_redirects=False)


# ── /admin/team/add ───────────────────────────────────────────────────────
def test_creating_a_team_is_recorded(staff, staff_db):
    assert post(staff, "/admin/team/add", name="Tourist", tag="TRS").status_code == 303
    _, _, action, target, old, new = one_audit(staff_db)
    assert (action, target, old) == ("team_add", "team:Tourist", None)
    assert "Tourist" in new and "TRS" in new
    assert len(staff_db.txns) == 1 and len(staff_db.txns[0]) == 2


def test_creating_a_team_without_a_name_records_nothing(staff, staff_db):
    assert post(staff, "/admin/team/add", name=" ").status_code == 400
    assert staff_db.writes == []


# ── /admin/team/edit ──────────────────────────────────────────────────────
def _team(fdb, row):
    fdb.add("SELECT name, tag FROM lan_teams", row)


def test_renaming_a_team_records_what_it_replaced(staff, staff_db):
    _team(staff_db, {"name": "Tourist", "tag": "TRS"})
    assert post(staff, "/admin/team/edit", team_id="3", name="Tourists",
                tag="TRS").status_code == 303
    _, _, action, target, old, new = one_audit(staff_db)
    assert (action, target) == ("team_edit", "team:3")
    assert "Tourist [TRS]" == old and "Tourists [TRS]" == new


def test_an_edit_that_changes_nothing_records_nothing(staff, staff_db):
    _team(staff_db, {"name": "Tourist", "tag": "TRS"})
    assert post(staff, "/admin/team/edit", team_id="3", name="Tourist",
                tag="TRS").status_code == 303
    assert audit_rows(staff_db) == []


def test_editing_a_team_that_is_not_there_records_nothing(staff, staff_db):
    _team(staff_db, None)
    assert post(staff, "/admin/team/edit", team_id="3", name="ghost").status_code == 303
    assert audit_rows(staff_db) == []


@pytest.mark.parametrize("bad", JUNK)
def test_a_junk_team_id_on_edit_is_a_400(staff, staff_db, bad):
    assert post(staff, "/admin/team/edit", team_id=bad, name="x").status_code == 400
    assert staff_db.writes == []


def test_a_missing_team_id_on_edit_is_a_400_not_a_traceback(staff, staff_db):
    assert post(staff, "/admin/team/edit", name="x").status_code == 400
    assert staff_db.writes == []


# ── /admin/team/delete — the roster goes with it ──────────────────────────
def test_deleting_a_team_records_the_roster_it_took_with_it(staff, staff_db):
    _team(staff_db, {"name": "Tourist", "tag": "TRS"})
    staff_db.add("SELECT display_name FROM lan_players WHERE team_id=%s ORDER BY",
                 [{"display_name": "nein"}, {"display_name": "jrod"}])
    assert post(staff, "/admin/team/delete", team_id="3").status_code == 303
    _, _, action, target, old, new = one_audit(staff_db)
    assert (action, target, new) == ("team_delete", "team:3", None)
    assert "Tourist [TRS]" in old and "nein" in old and "jrod" in old
    assert len(staff_db.txns) == 1 and len(staff_db.txns[0]) == 2
    assert staff_db.txns[0][0].startswith("DELETE FROM lan_teams")


def test_deleting_an_empty_team_still_records_the_team(staff, staff_db):
    _team(staff_db, {"name": "Tourist", "tag": None})
    staff_db.add("SELECT display_name FROM lan_players WHERE team_id=%s ORDER BY", [])
    post(staff, "/admin/team/delete", team_id="3")
    _, _, _, _, old, _ = one_audit(staff_db)
    assert old == "Tourist [-]"


def test_deleting_a_team_that_is_not_there_writes_nothing(staff, staff_db):
    _team(staff_db, None)
    assert post(staff, "/admin/team/delete", team_id="3").status_code == 303
    assert staff_db.writes == []


@pytest.mark.parametrize("bad", JUNK)
def test_a_junk_team_id_on_delete_is_a_400(staff, staff_db, bad):
    assert post(staff, "/admin/team/delete", team_id=bad).status_code == 400
    assert staff_db.writes == []


# ── /admin/player/add ─────────────────────────────────────────────────────
def test_adding_a_player_is_recorded_with_both_ids(staff, staff_db):
    r = post(staff, "/admin/player/add", team_id="3", display_name="nein",
             steam_id="0:0:1", discord_id=str(ME))
    assert r.status_code == 303
    _, _, action, target, old, new = one_audit(staff_db)
    assert (action, target, old) == ("player_add", "team:3", None)
    assert "nein" in new and "STEAM_0:0:1" in new and str(ME) in new


def test_adding_a_captain_clears_the_old_one_in_the_same_transaction(staff, staff_db):
    post(staff, "/admin/player/add", team_id="3", display_name="nein",
         steam_id="0:0:1", is_captain="1")
    assert len(staff_db.txns) == 1
    sqls = staff_db.txns[0]
    assert sqls[0].startswith("UPDATE lan_players SET is_captain=0")
    assert sqls[1].startswith("INSERT INTO lan_players")
    assert sqls[2].startswith("INSERT INTO lan_admin_audit")


@pytest.mark.parametrize("bad", JUNK)
def test_a_junk_team_id_on_player_add_is_a_400(staff, staff_db, bad):
    assert post(staff, "/admin/player/add", team_id=bad, display_name="n",
                steam_id="0:0:1").status_code == 400
    assert staff_db.writes == []


# ── /admin/player/delete ──────────────────────────────────────────────────
def _player(fdb, row):
    fdb.add("SELECT display_name, steam_id, discord_id FROM lan_players", row)


def test_deleting_a_player_is_recorded(staff, staff_db):
    _player(staff_db, {"display_name": "nein", "steam_id": "STEAM_0:0:1",
                       "discord_id": ME})
    assert post(staff, "/admin/player/delete", player_id="7").status_code == 303
    _, _, action, target, old, new = one_audit(staff_db)
    assert (action, target, new) == ("player_delete", "player:7", None)
    assert "nein" in old and str(ME) in old
    assert len(staff_db.txns) == 1 and len(staff_db.txns[0]) == 2


def test_deleting_a_player_that_is_not_there_writes_nothing(staff, staff_db):
    _player(staff_db, None)
    assert post(staff, "/admin/player/delete", player_id="7").status_code == 303
    assert staff_db.writes == []


@pytest.mark.parametrize("bad", JUNK)
def test_a_junk_player_id_on_delete_is_a_400(staff, staff_db, bad):
    assert post(staff, "/admin/player/delete", player_id=bad).status_code == 400
    assert staff_db.writes == []


# ── /admin/player/captain ─────────────────────────────────────────────────
def _captain_world(fdb, target, outgoing):
    fdb.add("SELECT display_name, is_captain FROM lan_players", target)
    fdb.add("SELECT display_name FROM lan_players WHERE team_id=%s AND is_captain=1",
            outgoing)


def test_handing_the_armband_over_records_both_names(staff, staff_db):
    _captain_world(staff_db, {"display_name": "nein", "is_captain": 0},
                   {"display_name": "jrod"})
    assert post(staff, "/admin/player/captain", team_id="3",
                player_id="7").status_code == 303
    _, _, action, target, old, new = one_audit(staff_db)
    assert (action, target, old, new) == ("player_captain", "team:3", "jrod", "nein")
    assert len(staff_db.txns) == 1 and len(staff_db.txns[0]) == 3


def test_the_first_captain_on_a_team_records_an_empty_predecessor(staff, staff_db):
    _captain_world(staff_db, {"display_name": "nein", "is_captain": 0}, None)
    post(staff, "/admin/player/captain", team_id="3", player_id="7")
    _, _, _, _, old, new = one_audit(staff_db)
    assert old is None and new == "nein"


def test_re_setting_the_current_captain_writes_nothing(staff, staff_db):
    _captain_world(staff_db, {"display_name": "nein", "is_captain": 1}, None)
    assert post(staff, "/admin/player/captain", team_id="3",
                player_id="7").status_code == 303
    assert staff_db.writes == []


def test_a_player_who_is_not_on_that_team_no_longer_strips_its_captain(staff, staff_db):
    """The clear-then-set pair ran unconditionally: a stale player_id wiped the
    team's captain and put the badge on somebody else's roster row."""
    _captain_world(staff_db, None, None)
    assert post(staff, "/admin/player/captain", team_id="3",
                player_id="7").status_code == 303
    assert staff_db.writes == []


@pytest.mark.parametrize("field", ["team_id", "player_id"])
def test_a_junk_id_on_captain_is_a_400(staff, staff_db, field):
    data = {"team_id": "3", "player_id": "7", field: "1٢3"}
    assert post(staff, "/admin/player/captain", **data).status_code == 400
    assert staff_db.writes == []


# ── /admin/awards/toggle ──────────────────────────────────────────────────
def test_closing_a_category_is_recorded_with_the_direction(staff, staff_db):
    staff_db.add("SELECT title, is_open FROM lan_awards", {"title": "MVP", "is_open": 1})
    assert post(staff, "/admin/awards/toggle", award_id="5").status_code == 303
    _, _, action, target, old, new = one_audit(staff_db)
    assert (action, target, old, new) == ("award_toggle", "award:5", "open", "closed")


def test_reopening_a_category_is_recorded_the_other_way(staff, staff_db):
    staff_db.add("SELECT title, is_open FROM lan_awards", {"title": "MVP", "is_open": 0})
    post(staff, "/admin/awards/toggle", award_id="5")
    _, _, _, _, old, new = one_audit(staff_db)
    assert (old, new) == ("closed", "open")


def test_toggling_an_award_that_is_not_there_writes_nothing(staff, staff_db):
    staff_db.add("SELECT title, is_open FROM lan_awards", None)
    assert post(staff, "/admin/awards/toggle", award_id="5").status_code == 303
    assert staff_db.writes == []


@pytest.mark.parametrize("bad", JUNK)
def test_a_junk_award_id_on_toggle_is_a_400(staff, staff_db, bad):
    assert post(staff, "/admin/awards/toggle", award_id=bad).status_code == 400
    assert staff_db.writes == []


# ── /admin/awards/delete ──────────────────────────────────────────────────
def test_deleting_an_award_records_its_title_and_drops_the_votes_with_it(staff, staff_db):
    staff_db.add("SELECT title FROM lan_awards", {"title": "MVP"})
    assert post(staff, "/admin/awards/delete", award_id="5").status_code == 303
    _, _, action, target, old, new = one_audit(staff_db)
    assert (action, target, old, new) == ("award_delete", "award:5", "MVP", None)
    assert len(staff_db.txns) == 1 and len(staff_db.txns[0]) == 3


def test_deleting_an_award_that_is_not_there_writes_nothing(staff, staff_db):
    staff_db.add("SELECT title FROM lan_awards", None)
    assert post(staff, "/admin/awards/delete", award_id="5").status_code == 303
    assert staff_db.writes == []


# ── /admin/gallery/delete ─────────────────────────────────────────────────
def test_removing_a_photo_records_who_posted_it(staff, staff_db):
    staff_db.add("FROM lan_photos", {"stored_name": "000004.jpg",
                                     "caption": "the wall", "uploaded_by": ME})
    assert post(staff, "/admin/gallery/delete", photo_id="4").status_code == 303
    _, _, action, target, old, new = one_audit(staff_db)
    assert (action, target, new) == ("photo_delete", "photo:4", None)
    assert "000004.jpg" in old and "the wall" in old and str(ME) in old


def test_removing_a_photo_that_is_gone_writes_nothing(staff, staff_db):
    staff_db.add("FROM lan_photos", None)
    assert post(staff, "/admin/gallery/delete", photo_id="4").status_code == 303
    assert staff_db.writes == []


@pytest.mark.parametrize("bad", JUNK)
def test_a_junk_photo_id_is_a_400(staff, staff_db, bad):
    assert post(staff, "/admin/gallery/delete", photo_id=bad).status_code == 400
    assert staff_db.writes == []


# ── /admin/station/delete and /admin/stream/delete ────────────────────────
def test_deleting_a_station_is_recorded(staff, staff_db):
    staff_db.add("FROM lan_stations", {"label": "Station 1", "connect": "10.0.0.5:27015"})
    assert post(staff, "/admin/station/delete", station_id="2").status_code == 303
    _, _, action, target, old, new = one_audit(staff_db)
    assert (action, target, new) == ("station_delete", "station:2", None)
    assert "Station 1" in old and "10.0.0.5:27015" in old


def test_deleting_a_station_that_is_not_there_writes_nothing(staff, staff_db):
    staff_db.add("FROM lan_stations", None)
    assert post(staff, "/admin/station/delete", station_id="2").status_code == 303
    assert staff_db.writes == []


def test_deleting_a_stream_is_recorded(staff, staff_db):
    staff_db.add("FROM lan_streams", {"label": "main", "url": "https://twitch.tv/ktp"})
    assert post(staff, "/admin/stream/delete", stream_id="2").status_code == 303
    _, _, action, target, old, new = one_audit(staff_db)
    assert (action, target, new) == ("stream_delete", "stream:2", None)
    assert "main" in old and "twitch.tv/ktp" in old


def test_deleting_a_stream_that_is_not_there_writes_nothing(staff, staff_db):
    staff_db.add("FROM lan_streams", None)
    assert post(staff, "/admin/stream/delete", stream_id="2").status_code == 303
    assert staff_db.writes == []


@pytest.mark.parametrize("path,field", [("/admin/station/delete", "station_id"),
                                        ("/admin/stream/delete", "stream_id"),
                                        ("/admin/station/edit", "station_id"),
                                        ("/admin/stream/edit", "stream_id")])
def test_a_junk_station_or_stream_id_is_a_400(staff, staff_db, path, field):
    assert post(staff, path, **{field: "1٢3", "label": "x",
                                "url": "https://x"}).status_code == 400
    assert staff_db.writes == []


# ── every one of these is still staff-only ────────────────────────────────
@pytest.mark.parametrize("path,data", [
    ("/admin/team/add", {"name": "x"}),
    ("/admin/team/edit", {"team_id": "3", "name": "x"}),
    ("/admin/team/delete", {"team_id": "3"}),
    ("/admin/player/add", {"team_id": "3", "display_name": "n", "steam_id": "0:0:1"}),
    ("/admin/player/delete", {"player_id": "7"}),
    ("/admin/player/captain", {"team_id": "3", "player_id": "7"}),
    ("/admin/awards/toggle", {"award_id": "5"}),
    ("/admin/awards/delete", {"award_id": "5"}),
    ("/admin/gallery/delete", {"photo_id": "4"}),
    ("/admin/station/delete", {"station_id": "2"}),
    ("/admin/stream/delete", {"stream_id": "2"}),
])
def test_the_swept_routes_are_staff_only(client, staff_db, path, data):
    staff_db.admins = []
    sign_in(client, ME)
    assert client.post(path, data=data, follow_redirects=False).status_code == 403
    assert staff_db.writes == []
