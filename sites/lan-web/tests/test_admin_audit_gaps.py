"""The mutations that changed things without leaving a record, the fact that a
record now shares its mutation's transaction, and the leftover staff row.

Separate file from test_admin_audit.py, which is the log's own behaviour."""
from dataclasses import replace

import pytest

from app import bracket, config
from app import schedule as sched
from app.routes import admin_routes
from conftest import sign_in

DID = 218890328273321984
OTHER = 486227681885683721


@pytest.fixture
def staff_db(fake_db, monkeypatch):
    fake_db.admins = [{"discord_id": DID, "label": "nein"}]
    fake_db.settings = {}
    fake_db.add("FROM lan_admins ORDER BY added_at", lambda p: fake_db.admins)
    fake_db.add("FROM lan_settings WHERE k",
                lambda p: {"v": fake_db.settings[p[0]]} if p[0] in fake_db.settings else None)
    fake_db.add("FROM lan_settings", None)
    fake_db.add("FROM lan_players p", [])
    monkeypatch.setattr(sched, "get_matches", lambda: [])
    monkeypatch.setattr(bracket, "get_bracket", lambda: [])
    return fake_db


@pytest.fixture
def staff(client, staff_db):
    sign_in(client, DID)
    return client


def audit_rows(fdb):
    return [(sql, p) for sql, p in fdb.writes if sql.startswith("INSERT INTO lan_admin_audit")]


def one_audit(fdb):
    rows = audit_rows(fdb)
    assert len(rows) == 1, rows
    return rows[0][1]           # (actor, actor_name, action, target, old, new)


# ── /admin/announce ───────────────────────────────────────────────────────
def test_setting_the_announcement_is_recorded_with_what_it_replaced(staff, staff_db):
    staff_db.settings["announcement"] = "doors at 9"
    r = staff.post("/admin/announce", data={"announcement": "doors at 10"},
                   follow_redirects=False)
    assert r.status_code == 303
    _, _, action, target, old, new = one_audit(staff_db)
    assert (action, target, old, new) == ("announce", "announcement", "doors at 9", "doors at 10")


def test_clearing_the_announcement_is_recorded_too(staff, staff_db):
    """Taking the strip down is as much a site-wide act as putting it up, and
    it was the easier one to lose — the new value is empty either way."""
    staff_db.settings["announcement"] = "doors at 9"
    staff.post("/admin/announce", data={"announcement": ""}, follow_redirects=False)
    _, _, action, _, old, new = one_audit(staff_db)
    assert action == "announce" and old == "doors at 9" and new is None


def test_re_saving_the_same_words_records_nothing(staff, staff_db):
    """Staff re-save this form routinely; a row per re-save is noise that buries
    the decisions the log exists for."""
    staff_db.settings["announcement"] = "doors at 9"
    staff.post("/admin/announce", data={"announcement": "doors at 9"}, follow_redirects=False)
    assert audit_rows(staff_db) == []


def test_the_announcement_and_its_record_are_one_transaction(staff, staff_db):
    staff_db.settings["announcement"] = ""
    staff.post("/admin/announce", data={"announcement": "hi"}, follow_redirects=False)
    assert len(staff_db.txns) == 1
    assert staff_db.txns[0][0].startswith("INSERT INTO lan_settings")
    assert staff_db.txns[0][1].startswith("INSERT INTO lan_admin_audit")


# ── /admin/player/edit ────────────────────────────────────────────────────
PLAYER = {"display_name": "nein", "steam_id": "STEAM_0:0:1", "discord_id": DID}


def edit(client, **over):
    data = {"player_id": "1", "display_name": "nein", "steam_id": "STEAM_0:0:1",
            "discord_id": str(DID)}
    data.update(over)
    return client.post("/admin/player/edit", data=data, follow_redirects=False)


def test_rewriting_a_roster_discord_id_is_recorded_with_both_ids(staff, staff_db):
    """The one that mattered: a grant's label comes from the roster, so moving
    a discord_id silently re-attributes it. Both ids have to be in the row."""
    staff_db.add("SELECT display_name, steam_id, discord_id FROM lan_players", dict(PLAYER))
    assert edit(staff, discord_id=str(OTHER)).status_code == 303
    _, _, action, target, old, new = one_audit(staff_db)
    assert (action, target) == ("player_edit", "player:1")
    assert str(DID) in old and str(OTHER) in new
    assert str(OTHER) not in old and str(DID) not in new


def test_clearing_a_roster_discord_id_is_recorded(staff, staff_db):
    staff_db.add("SELECT display_name, steam_id, discord_id FROM lan_players", dict(PLAYER))
    edit(staff, discord_id="")
    _, _, _, _, old, new = one_audit(staff_db)
    assert str(DID) in old and "discord -" in new


def test_an_edit_that_changes_nothing_records_nothing(staff, staff_db):
    staff_db.add("SELECT display_name, steam_id, discord_id FROM lan_players", dict(PLAYER))
    assert edit(staff).status_code == 303
    assert audit_rows(staff_db) == []


def test_editing_a_player_that_is_not_there_records_nothing(staff, staff_db):
    """The UPDATE matches no row, so a record would assert a change that never
    happened — the same rule /staff/remove keeps."""
    staff_db.add("SELECT display_name, steam_id, discord_id FROM lan_players", None)
    assert edit(staff, display_name="ghost").status_code == 303
    assert audit_rows(staff_db) == []


def test_the_edit_and_its_record_are_one_transaction(staff, staff_db):
    staff_db.add("SELECT display_name, steam_id, discord_id FROM lan_players", dict(PLAYER))
    edit(staff, display_name="nein_")
    assert len(staff_db.txns) == 1
    assert staff_db.txns[0][0].startswith("UPDATE lan_players")
    assert staff_db.txns[0][1].startswith("INSERT INTO lan_admin_audit")


# ── /admin/photo-requests/handled ─────────────────────────────────────────
def test_closing_a_takedown_request_is_recorded(staff, staff_db):
    staff_db.add("SELECT id FROM lan_photo_removal_requests", {"id": 4})
    r = staff.post("/admin/photo-requests/handled", data={"request_id": "4"},
                   follow_redirects=False)
    assert r.status_code == 303
    _, _, action, target, old, new = one_audit(staff_db)
    assert (action, target, old, new) == ("photo_request_handled", "request:4",
                                          "pending", "handled")
    assert len(staff_db.txns) == 1 and len(staff_db.txns[0]) == 2


def test_closing_one_already_handled_records_nothing_and_writes_nothing(staff, staff_db):
    staff_db.add("SELECT id FROM lan_photo_removal_requests", None)
    r = staff.post("/admin/photo-requests/handled", data={"request_id": "4"},
                   follow_redirects=False)
    assert r.status_code == 303
    assert staff_db.writes == []


def test_a_junk_request_id_is_a_400_not_a_traceback(staff, staff_db):
    """int(f["request_id"]) raised on a missing key as well as a bad value."""
    for bad in ("", "²", "1٢3", "nope"):
        assert staff.post("/admin/photo-requests/handled",
                          data={"request_id": bad}).status_code == 400
    assert staff.post("/admin/photo-requests/handled", data={}).status_code == 400
    assert staff_db.writes == []


# ── every audited mutation shares its transaction ─────────────────────────
def test_a_staff_grant_and_its_record_are_one_transaction(staff, staff_db):
    staff_db.add("SELECT display_name FROM lan_players", None)
    staff.post("/admin/staff/add", data={"discord_id": str(OTHER)}, follow_redirects=False)
    assert len(staff_db.txns) == 1
    assert staff_db.txns[0][0].startswith("INSERT INTO lan_admins")
    assert staff_db.txns[0][1].startswith("INSERT INTO lan_admin_audit")


def test_a_revocation_and_its_record_are_one_transaction(staff, staff_db):
    staff_db.add("SELECT label FROM lan_admins", {"label": "jrod"})
    staff.post("/admin/staff/remove", data={"discord_id": str(OTHER)}, follow_redirects=False)
    assert len(staff_db.txns) == 1
    assert staff_db.txns[0][0].startswith("DELETE FROM lan_admins")
    assert staff_db.txns[0][1].startswith("INSERT INTO lan_admin_audit")


def test_a_publish_flip_and_its_record_are_one_transaction(staff, staff_db):
    staff.post("/admin/publish", data={"flag": "stats_published", "publish": "1"},
               follow_redirects=False)
    assert len(staff_db.txns) == 1
    assert staff_db.txns[0][0].startswith("INSERT INTO lan_settings")
    assert staff_db.txns[0][1].startswith("INSERT INTO lan_admin_audit")


def test_a_publish_no_op_still_writes_the_setting_and_no_record(staff, staff_db):
    staff_db.settings["stats_published"] = "0"
    staff.post("/admin/publish", data={"flag": "stats_published"}, follow_redirects=False)
    assert len(staff_db.txns) == 1 and len(staff_db.txns[0]) == 1
    assert audit_rows(staff_db) == []


# ── the leftover lan_admins row for a config admin ────────────────────────
@pytest.fixture
def env_admin(monkeypatch):
    """OTHER is a config admin. Everything below is about the table row that can
    also exist for them, which grants nothing and used to be unremovable."""
    monkeypatch.setattr(admin_routes, "settings",
                        replace(config.settings, admin_discord_ids=frozenset({OTHER})))


def test_a_config_admin_cannot_be_granted_a_row_in_the_first_place(staff, staff_db, env_admin):
    r = staff.post("/admin/staff/add", data={"discord_id": str(OTHER)})
    assert r.status_code == 400
    assert staff_db.writes == []


def test_a_web_grant_is_still_allowed(staff, staff_db, env_admin):
    """The control: the refusal above is about env ids, not about granting."""
    staff_db.add("SELECT display_name FROM lan_players", None)
    r = staff.post("/admin/staff/add", data={"discord_id": "749415733393621101"},
                   follow_redirects=False)
    assert r.status_code == 303
    assert staff_db.writes[0][0].startswith("INSERT INTO lan_admins")


def test_a_leftover_row_can_be_cleared_and_is_not_logged_as_a_revocation(
        staff, staff_db, env_admin):
    staff_db.add("SELECT label FROM lan_admins", {"label": "jrod"})
    r = staff.post("/admin/staff/clear-row", data={"discord_id": str(OTHER)},
                   follow_redirects=False)
    assert r.status_code == 303
    assert staff_db.writes[0][0].startswith("DELETE FROM lan_admins")
    _, _, action, target, old, new = one_audit(staff_db)
    assert action == "staff_row_clear"          # not staff_remove: nothing was revoked
    assert (target, old, new) == (str(OTHER), "jrod", None)
    assert len(staff_db.txns) == 1 and len(staff_db.txns[0]) == 2


def test_clearing_a_row_leaves_the_config_grant_alone(staff, staff_db, env_admin):
    """The lockout guard is the whole point: they are staff from the environment
    before and after, and the DELETE never touched that."""
    staff_db.admins = []                        # the row is gone after the clear
    admins, _ = admin_routes._staff_view(DID)
    assert [a["discord_id"] for a in admins] == [OTHER]
    assert admins[0]["source"] == "config" and admins[0]["removable"] is False


def test_clear_row_refuses_an_id_that_is_not_a_config_admin(staff, staff_db, env_admin):
    """Otherwise it is a second, unconfirmed revoke button."""
    r = staff.post("/admin/staff/clear-row", data={"discord_id": "749415733393621101"})
    assert r.status_code == 400
    assert staff_db.writes == []


def test_clear_row_with_nothing_to_clear_writes_nothing(staff, staff_db, env_admin):
    staff_db.add("SELECT label FROM lan_admins", None)
    r = staff.post("/admin/staff/clear-row", data={"discord_id": str(OTHER)},
                   follow_redirects=False)
    assert r.status_code == 303
    assert staff_db.writes == []


def test_clear_row_is_staff_only(client, staff_db, env_admin):
    staff_db.admins = []
    sign_in(client, DID)
    assert client.post("/admin/staff/clear-row",
                       data={"discord_id": str(OTHER)}).status_code == 403
    assert staff_db.writes == []


@pytest.mark.parametrize("bad", ["", "²", "٠", "1٢3", "nope"])
def test_clear_row_refuses_a_junk_id(staff, staff_db, env_admin, bad):
    assert staff.post("/admin/staff/clear-row", data={"discord_id": bad}).status_code == 400
    assert staff_db.writes == []


def test_the_staff_page_offers_clear_row_only_for_a_leftover(staff, staff_db, env_admin):
    staff_db.admins = [{"discord_id": OTHER, "label": "jrod", "added_at": None}]
    admins, _ = admin_routes._staff_view(DID)
    row = next(a for a in admins if a["discord_id"] == OTHER)
    assert row["stale_row"] is True and row["removable"] is False

    staff_db.admins = []                        # config admin with no leftover row
    admins, _ = admin_routes._staff_view(DID)
    assert next(a for a in admins if a["discord_id"] == OTHER)["stale_row"] is False
