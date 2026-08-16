"""The staff action log and the two grants that now land in it."""
import datetime
from dataclasses import replace

import pytest

from app import config
from app.routes import admin_routes
from conftest import sign_in

DID = 218890328273321984
OTHER = 486227681885683721
ENTRY = {"id": 9, "actor": DID, "actor_name": "nein", "action": "award_select",
         "target": "philly-2026:weekend-kills-high", "old_value": "0", "new_value": "1",
         "at": datetime.datetime(2026, 8, 14, 19, 4)}


@pytest.fixture
def audit_db(fake_db):
    fake_db.admins = []
    fake_db.add("FROM lan_admins ORDER BY added_at", lambda p: fake_db.admins)
    fake_db.add("FROM lan_settings", None)
    fake_db.add("FROM lan_players p", None)
    return fake_db


def as_staff(fdb, client):
    fdb.admins = [{"discord_id": DID, "label": "nein"}]
    sign_in(client, DID)


def test_the_log_is_staff_only(client, audit_db):
    sign_in(client, OTHER)
    assert client.get("/admin/audit-log").status_code == 403


def test_the_log_renders_an_entry(client, audit_db):
    as_staff(audit_db, client)
    audit_db.add("FROM lan_admin_audit ORDER BY", [ENTRY])
    audit_db.add("COUNT(*) AS n FROM lan_admin_audit", {"n": 1})
    r = client.get("/admin/audit-log")
    assert r.status_code == 200
    assert "award_select" in r.text and "philly-2026:weekend-kills-high" in r.text


def test_paging_walks_backwards_by_offset(client, audit_db):
    as_staff(audit_db, client)
    seen = []
    audit_db.add("FROM lan_admin_audit ORDER BY", lambda p: (seen.append(p), [ENTRY])[1])
    audit_db.add("COUNT(*) AS n FROM lan_admin_audit", {"n": 120})
    client.get("/admin/audit-log")
    client.get("/admin/audit-log?page=3")
    client.get("/admin/audit-log?page=-4")     # a nonsense page is the first one
    assert [p[1] for p in seen] == [0, 100, 0]


def test_the_result_log_stays_a_separate_record(client, audit_db):
    """/admin/audit is match results with an undo; this one is not that."""
    as_staff(audit_db, client)
    audit_db.add("FROM lan_admin_audit ORDER BY", [ENTRY])
    audit_db.add("COUNT(*) AS n FROM lan_admin_audit", {"n": 1})
    assert "Undo" not in client.get("/admin/audit-log").text


def test_granting_staff_is_audited(client, audit_db):
    as_staff(audit_db, client)
    r = client.post("/admin/staff/add", data={"discord_id": str(OTHER), "label": "jrod"},
                    follow_redirects=False)
    assert r.status_code == 303
    assert audit_db.writes[0][0].startswith("INSERT INTO lan_admins")
    sql, params = audit_db.writes[1]
    assert sql.startswith("INSERT INTO lan_admin_audit")
    assert params[0] == DID and params[2] == "staff_add"
    assert params[3] == str(OTHER) and params[5] == "jrod"


def test_revoking_staff_is_audited_with_the_label_it_had(client, audit_db):
    as_staff(audit_db, client)
    audit_db.add("SELECT label FROM lan_admins", {"label": "jrod"})
    r = client.post("/admin/staff/remove", data={"discord_id": str(OTHER)},
                    follow_redirects=False)
    assert r.status_code == 303
    assert audit_db.writes[0][0].startswith("DELETE FROM lan_admins")
    sql, params = audit_db.writes[1]
    assert sql.startswith("INSERT INTO lan_admin_audit")
    assert params[2] == "staff_remove" and params[3] == str(OTHER) and params[4] == "jrod"


def test_revoking_yourself_is_still_refused_and_audits_nothing(client, audit_db):
    """The lockout guard is unchanged by the logging — no row, no delete."""
    as_staff(audit_db, client)
    r = client.post("/admin/staff/remove", data={"discord_id": str(DID)})
    assert r.status_code == 400
    assert audit_db.writes == []


def test_a_non_admin_cannot_grant_and_leaves_no_trace(client, audit_db):
    sign_in(client, OTHER)
    assert client.post("/admin/staff/add", data={"discord_id": "1"}).status_code == 403
    assert audit_db.writes == []


# ── the lockout guard, and what the log is allowed to claim ───────────────
def test_a_config_admin_cannot_be_revoked_and_no_row_claims_otherwise(
        client, audit_db, monkeypatch):
    """The DELETE could never reach an env admin, but it used to audit the
    attempt as a revocation — a log asserting a change that never happened."""
    monkeypatch.setattr(admin_routes, "settings",
                        replace(config.settings, admin_discord_ids=frozenset({OTHER})))
    as_staff(audit_db, client)
    r = client.post("/admin/staff/remove", data={"discord_id": str(OTHER)})
    assert r.status_code == 400
    assert audit_db.writes == []


def test_revoking_someone_who_was_never_granted_writes_nothing(client, audit_db):
    as_staff(audit_db, client)
    audit_db.add("SELECT label FROM lan_admins", None)
    r = client.post("/admin/staff/remove", data={"discord_id": str(OTHER)},
                    follow_redirects=False)
    assert r.status_code == 303
    assert audit_db.writes == []


#   '²' and '٠' are the load-bearing cases: isdigit() is True for both and int()
#   raises on both, so an isdigit()-only guard sends them straight to a 500.
BAD_IDS = ["", "  ", "not-a-number", "12x", "-1", "²", "٠", "1٢3"]


@pytest.mark.parametrize("bad", BAD_IDS)
def test_a_non_numeric_revoke_is_a_400_not_a_500(client, audit_db, bad):
    """/staff/add validated its input and /staff/remove did not, so the same
    typo was a clean refusal on one route and a traceback on the other."""
    as_staff(audit_db, client)
    assert client.post("/admin/staff/remove", data={"discord_id": bad}).status_code == 400
    assert audit_db.writes == []


@pytest.mark.parametrize("bad", BAD_IDS)
def test_the_same_input_is_refused_the_same_way_on_grant(client, audit_db, bad):
    """The two routes have to agree, or the guard is only half applied."""
    as_staff(audit_db, client)
    assert client.post("/admin/staff/add", data={"discord_id": bad}).status_code == 400
    assert audit_db.writes == []


def test_a_real_snowflake_control_still_gets_through(client, audit_db):
    """A guard that refuses everything is broken, not strict."""
    as_staff(audit_db, client)
    audit_db.add("SELECT display_name FROM lan_players", None)
    r = client.post("/admin/staff/add", data={"discord_id": str(OTHER)},
                    follow_redirects=False)
    assert r.status_code == 303
    assert audit_db.writes[0][0].startswith("INSERT INTO lan_admins")
