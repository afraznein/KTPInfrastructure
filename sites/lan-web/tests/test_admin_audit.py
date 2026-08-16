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


# ── filtering, because the log is not evenly interesting ─────────────────
@pytest.fixture
def filterable(audit_db):
    """Records the params of every filtered read, so a test can assert what was
    ASKED rather than what a fake chose to answer.

    Rules are matched by substring in registration order, so the narrow needles
    have to come first or the plain ones swallow them."""
    audit_db.seen = []
    audit_db.total = 1
    audit_db.add("GROUP BY action", [{"action": "award_staff_vote", "n": 52},
                                     {"action": "staff_add", "n": 1}])
    audit_db.add("COUNT(*) AS n FROM lan_admin_audit WHERE",
                 lambda p: (audit_db.seen.append(("count", p)), {"n": audit_db.total})[1])
    audit_db.add("FROM lan_admin_audit WHERE",
                 lambda p: (audit_db.seen.append(("rows", p)), [ENTRY])[1])
    audit_db.add("FROM lan_admin_audit ORDER BY", [ENTRY])
    audit_db.add("COUNT(*) AS n FROM lan_admin_audit", {"n": 53})
    return audit_db


def test_the_filter_offers_the_actions_that_are_there_with_counts(client, filterable):
    as_staff(filterable, client)
    text = client.get("/admin/audit-log").text
    assert "award_staff_vote (52)" in text and "staff_add (1)" in text


def test_filtering_by_action_narrows_the_query_not_just_the_page(client, filterable):
    """The point is the staff grant buried under a weekend of award ticks, so
    the filter has to reach the query — paging a filtered-in-Python list would
    still put it on page 2."""
    as_staff(filterable, client)
    client.get("/admin/audit-log?action=staff_add")
    assert ("count", ("staff_add",)) in filterable.seen
    assert ("rows", ("staff_add", 50, 0)) in filterable.seen


def test_filtering_by_target_is_a_prefix_match(client, filterable):
    as_staff(filterable, client)
    client.get("/admin/audit-log?target=player:")
    assert ("rows", ("player:%", 50, 0)) in filterable.seen


def test_a_percent_in_the_target_box_is_escaped_not_a_wildcard(client, filterable):
    """Unescaped, '%' matches everything and reads as no filter at all."""
    as_staff(filterable, client)
    client.get("/admin/audit-log?target=%25")
    assert ("rows", (r"\%%", 50, 0)) in filterable.seen


def test_both_filters_apply_together(client, filterable):
    as_staff(filterable, client)
    client.get("/admin/audit-log?action=player_edit&target=player:1")
    assert ("rows", ("player_edit", "player:1%", 50, 0)) in filterable.seen


def test_an_unfiltered_page_asks_for_no_where_clause(client, filterable):
    """The control: the filter is off by default, so the plain page must not be
    quietly narrowed by an empty string."""
    as_staff(filterable, client)
    client.get("/admin/audit-log")
    assert filterable.seen == []           # nothing hit the WHERE rules


def test_the_pager_carries_the_filter(client, filterable):
    """Otherwise page 2 silently drops back to everything."""
    as_staff(filterable, client)
    filterable.total = 120
    text = client.get("/admin/audit-log?action=staff_add").text
    assert "page=2&amp;action=staff_add" in text


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


#   '²', '٠' and '1٢3' are the load-bearing cases, and they fail differently:
#   isdigit() is True for all three, but int() raises only on '²' — it returns 0
#   and 123 for the other two, so an isdigit()-only guard grants staff to an id
#   nobody typed. Classified in test_parse_guard.py.
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
