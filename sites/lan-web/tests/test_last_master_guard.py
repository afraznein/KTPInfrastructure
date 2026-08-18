"""Revoking staff may not reach a state with no master admin left.

Master authority is conjoined with is_admin, so revoking a master's staff row
takes the publish authority with it — and with none left there is no web path
back. Only that terminal state is refused: it changes nobody's authority over
anybody, and every non-last master stays revocable.

Both directions are asserted throughout. A guard that refuses every revocation
would satisfy half these tests and be broken."""
from dataclasses import replace

import pytest

from app import bracket, config
from app import schedule as sched
from app.routes import admin_routes
from conftest import sign_in

ME = 218890328273321984          # the signed-in actor
JROD = 486227681885683721        # the row under the Revoke button
KANGUH = 271799124276412417
CHI = 749415733393621101


@pytest.fixture
def staff_db(fake_db, monkeypatch):
    fake_db.admins = []
    fake_db.add("FROM lan_admins ORDER BY added_at", lambda p: fake_db.admins)
    fake_db.add("SELECT label FROM lan_admins",
                lambda p: next(({"label": a["label"]} for a in fake_db.admins
                                if a["discord_id"] == p[0]), None))
    fake_db.add("FROM lan_players p", [])
    monkeypatch.setattr(sched, "get_matches", lambda: [])
    monkeypatch.setattr(bracket, "get_bracket", lambda: [])
    return fake_db


@pytest.fixture
def world(client, staff_db, monkeypatch):
    """Sets who is staff (env + table) and who is a master, then signs ME in."""
    def setup(*, db_admins, masters, env_admins=()):
        staff_db.admins = [{"discord_id": d, "label": str(d), "added_at": None}
                           for d in db_admins]
        monkeypatch.setattr(
            admin_routes, "settings",
            replace(config.settings,
                    admin_discord_ids=frozenset(env_admins),
                    master_admin_discord_ids=frozenset(masters)))
        sign_in(client, ME)
        return client
    return setup


def revoke(c, did):
    return c.post("/admin/staff/remove", data={"discord_id": str(did)},
                  follow_redirects=False)


def deleted(fdb):
    return [p for sql, p in fdb.writes if sql.startswith("DELETE FROM lan_admins")]


# ── refuses the last one ──────────────────────────────────────────────────
def test_the_last_master_cannot_be_revoked(world, staff_db):
    c = world(db_admins=[ME, JROD], masters=[JROD])
    r = revoke(c, JROD)
    assert r.status_code == 400
    assert "last master" in r.json()["detail"]
    assert staff_db.writes == []            # no delete, and no audit row either


def test_the_last_master_is_refused_even_with_other_staff_around(world, staff_db):
    """Staff who are not masters cannot stand in — publish authority is the
    thing being counted, not headcount."""
    c = world(db_admins=[ME, JROD, KANGUH], masters=[JROD])
    assert revoke(c, JROD).status_code == 400
    assert staff_db.writes == []


# ── permits a non-last one: the control that proves it is not a blanket no ──
def test_a_master_is_revocable_while_another_master_remains(world, staff_db):
    c = world(db_admins=[ME, JROD], masters=[ME, JROD])
    assert revoke(c, JROD).status_code == 303
    assert deleted(staff_db) == [(JROD,)]
    assert any(sql.startswith("INSERT INTO lan_admin_audit")
               for sql, _ in staff_db.writes)


def test_a_db_master_is_revocable_when_the_survivor_is_an_env_master(world, staff_db):
    """Philly-2026's shape: master #1 is an env admin, so he is an effective
    master without a table row and the guard must see him."""
    c = world(db_admins=[ME, JROD], masters=[CHI, JROD], env_admins=[CHI])
    assert revoke(c, JROD).status_code == 303
    assert deleted(staff_db) == [(JROD,)]


def test_revoking_a_non_master_is_untouched_by_the_guard(world, staff_db):
    c = world(db_admins=[ME, JROD], masters=[ME])
    assert revoke(c, JROD).status_code == 303
    assert deleted(staff_db) == [(JROD,)]


def test_a_non_master_is_revocable_even_with_no_masters_at_all(world, staff_db):
    """The guard keys on the row being revoked, not on the count being zero —
    otherwise a misconfigured master list would freeze every revocation."""
    c = world(db_admins=[ME, JROD], masters=[])
    assert revoke(c, JROD).status_code == 303
    assert deleted(staff_db) == [(JROD,)]


# ── the guard does not widen anything ─────────────────────────────────────
def test_a_master_row_is_still_offered_for_revocation(world, staff_db):
    """`removable` is deliberately unchanged: masters stay web-revocable, and
    only the terminal state is forbidden. This is the authority answer NOT
    being taken."""
    world(db_admins=[ME, JROD], masters=[JROD])
    admins, _ = admin_routes._staff_view(ME)
    row = next(a for a in admins if a["discord_id"] == JROD)
    assert row["is_master"] is True and row["removable"] is True


def test_an_env_master_is_still_refused_as_a_config_admin(world, staff_db):
    """The lockout guard answers first, with its own message — the new one must
    not take that refusal over."""
    c = world(db_admins=[ME], masters=[CHI], env_admins=[CHI])
    r = revoke(c, CHI)
    assert r.status_code == 400
    assert "server environment" in r.json()["detail"]


def test_a_master_with_no_row_is_still_a_silent_no_op(world, staff_db):
    """Nothing is revoked, so nothing is refused and nothing is recorded."""
    c = world(db_admins=[ME], masters=[JROD])
    assert revoke(c, JROD).status_code == 303
    assert staff_db.writes == []


def test_you_still_cannot_revoke_yourself(world, staff_db):
    c = world(db_admins=[ME, JROD], masters=[ME, JROD])
    r = revoke(c, ME)
    assert r.status_code == 400 and "your own" in r.json()["detail"]


# ── the counter itself ────────────────────────────────────────────────────
def test_effective_masters_ignores_a_master_who_is_not_staff(world, staff_db):
    """is_master_admin is conjoined with is_admin, so a master with neither an
    env grant nor a row can publish nothing and must not be counted."""
    world(db_admins=[ME], masters=[ME, JROD])
    assert admin_routes._effective_masters() == {ME}
    assert admin_routes._effective_masters(exclude=ME) == set()
