"""The generated award board: the publish gate, the two staff writes, and the
orders each audience gets.

The gate is the load-bearing test. `awards_published` = 0 must mean the award
tables are never read, not that the page is trusted to hide what it was sent.
The vote tally is withheld from non-master staff the same way, and tested the
same way — on the serialised body, with a positive control."""
import re
from decimal import Decimal

import pytest

from app import db, stat_awards
from conftest import sign_in

EDITION = "philly-2026"
DID = 218890328273321984          # in the master-admin fallback list
OTHER = 486227681885683721        # staff, never master
THIRD = 749415733393621101        # the other master, for a two-voter tally

TYPES = [
    # Deliberately first in the operator's own order, so a staff response that
    # merely echoed sort_order would still lead with it.
    {"slug": "tie-award", "scope": "weekend", "kind": "player",
     "default_title": "Most Team Kills", "default_sting": "Generated sting.",
     "title": None, "sting": None, "sort_order": 0},
    {"slug": "clean-award", "scope": "weekend", "kind": "player",
     "default_title": "Most Kills", "default_sting": "Most kills across the weekend.",
     "title": None, "sting": None, "sort_order": 1},
    {"slug": "renamed-award", "scope": "weekend", "kind": "team",
     "default_title": "Best Team", "default_sting": "Generated sting.",
     "title": "The Fragger", "sting": "Most kills.", "sort_order": 2},
]


def cand(slug, rank, who, num, alias=None, where=None, role=None, slot=None, match=""):
    return {"award_slug": slug, "match_key": match, "rank_pos": rank, "who": who,
            "who_alias": alias, "role": role, "slot": slot,
            "value_num": Decimal(str(num)), "value_text": str(num), "where_text": where}


CANDIDATES = (
    [cand("tie-award", 1, f"player{i}", 3) for i in range(28)]
    + [cand("tie-award", 29, "laggard", 1)]
    + [cand("clean-award", 1, "hildebrand", 100), cand("clean-award", 2, "piff", 80)]
    + [cand("renamed-award", 1, "dicE", 42)]
)

# The role panel, in the page's display order — which is deliberately not the
# order you get by sorting on (role, slot).
PANEL_SLOTS = [("Rifle", 1), ("Heavy", 1), ("3rd", 1),
               ("Rifle", 2), ("Heavy", 2), ("Sniper", 1)]


@pytest.fixture
def board_db(fake_db, monkeypatch):
    fake_db.flags = {}                      # lan_settings, keyed by flag name
    fake_db.admins = []                     # lan_admins rows
    fake_db.types = {t["slug"]: dict(t) for t in TYPES}
    fake_db.selected = {"clean-award", "renamed-award"}
    fake_db.rows = list(CANDIDATES)
    fake_db.reads = {}
    fake_db.votes = {}                      # (edition, match_key, slug) -> voter ids

    def record(name, params):
        fake_db.reads.setdefault(name, []).append(params)

    fake_db.add("FROM lan_admins ORDER BY added_at", lambda p: fake_db.admins)
    fake_db.add("FROM lan_settings WHERE k",
                lambda p: {"v": fake_db.flags[p[0]]} if p[0] in fake_db.flags else None)
    fake_db.add("SELECT p.id AS player_id", None)
    fake_db.add("FROM lan_award_types WHERE retired", lambda p: list(fake_db.types.values()))
    # A copy, because a real row is a snapshot — an alias would hide a route
    # that read its "old" value after writing the new one.
    fake_db.add("FROM lan_award_types WHERE slug",
                lambda p: dict(fake_db.types[p[0]]) if p[0] in fake_db.types else None)
    fake_db.add("SELECT award_slug FROM lan_award_selections",
                lambda p: [{"award_slug": s} for s in sorted(fake_db.selected)])
    fake_db.add("SELECT selected FROM lan_award_selections",
                lambda p: {"selected": 1 if p[1] in fake_db.selected else 0})
    # Filters on match_key the way the real query does — a fake that ignored it
    # would let a per-match row pass for a weekend card and hide the very bug
    # the single-match tests are here to catch.
    fake_db.add("FROM lan_award_candidates WHERE edition",
                lambda p: (record("candidates", p),
                           [r for r in fake_db.rows if r["match_key"] == p[1]])[1])

    # Staff nominations. Keyed by scope as well as slug, because a per-match
    # vote must not light up the weekend card.
    fake_db.add("SELECT award_slug FROM lan_award_staff_votes",
                lambda p: [{"award_slug": s} for (e, m, s), v in sorted(fake_db.votes.items())
                           if (e, m) == (p[0], p[1]) and int(p[2]) in v])
    fake_db.add("COUNT(*) AS n FROM lan_award_staff_votes",
                lambda p: [{"award_slug": s, "n": len(v)} for (e, m, s), v in
                           sorted(fake_db.votes.items()) if (e, m) == (p[0], p[1]) and v])
    fake_db.add("SELECT 1 AS voted FROM lan_award_staff_votes",
                lambda p: {"voted": 1}
                if int(p[3]) in fake_db.votes.get((p[0], p[2], p[1]), set()) else None)

    # A retitle and a nomination both have to land somewhere for the round trip
    # to mean anything.
    plain_execute = fake_db.execute

    def execute(sql, params=None):
        n = plain_execute(sql, params)
        flat = " ".join(sql.split())
        if flat.startswith("UPDATE lan_award_types SET title"):
            t = fake_db.types[params[3]]
            t["title"], t["sting"] = params[0], params[1]
        elif flat.startswith("INSERT INTO lan_award_staff_votes"):
            edition, slug, match_key, voter = params
            fake_db.votes.setdefault((edition, match_key, slug), set()).add(int(voter))
        elif flat.startswith("DELETE FROM lan_award_staff_votes"):
            edition, slug, match_key, voter = params
            fake_db.votes.get((edition, match_key, slug), set()).discard(int(voter))
        return n

    monkeypatch.setattr(db, "execute", execute)
    return fake_db


def as_staff(fdb, client, did=DID):
    fdb.admins = [{"discord_id": did, "label": "nein"}]
    sign_in(client, did)


def as_master(fdb, client):
    as_staff(fdb, client, DID)


def cast(fdb, slug, *voters, edition=EDITION, match=""):
    """Seed nominations directly, for tests about reading the tally."""
    fdb.votes.setdefault((edition, match, slug), set()).update(voters)


def board(client, match=""):
    q = f"/api/awards/candidates?edition={EDITION}" + (f"&match={match}" if match else "")
    return client.get(q).json()


# ── the gate ──────────────────────────────────────────────────────────────
def test_unpublished_public_never_reads_the_award_tables(client, fake_db):
    """No fake rule for any award table is registered here, so a query that got
    past the gate would raise rather than quietly answer — the response being
    well-formed is itself the proof nothing was read."""
    fake_db.add("FROM lan_admins ORDER BY added_at", [])
    fake_db.add("FROM lan_settings WHERE k", None)
    r = client.get(f"/api/awards/candidates?edition={EDITION}")
    assert r.status_code == 200
    assert r.json() == {"published": False, "awards": []}


def test_unpublished_public_body_carries_no_award_text(client, board_db):
    r = client.get(f"/api/awards/candidates?edition={EDITION}")
    assert r.json() == {"published": False, "awards": []}
    for leak in ("hildebrand", "clean-award", "Most Kills", "The Fragger", "player0"):
        assert leak not in r.text


def test_a_signed_in_non_staff_player_is_still_public(client, board_db):
    sign_in(client, OTHER)
    assert client.get(f"/api/awards/candidates?edition={EDITION}").json() == {
        "published": False, "awards": []}


def test_unpublished_staff_see_every_candidate(client, board_db):
    as_staff(board_db, client)
    b = board(client)
    assert b["published"] is False and b["is_staff"] is True and b["edition"] == EDITION
    assert {a["slug"] for a in b["awards"]} == {"tie-award", "clean-award", "renamed-award"}


def test_published_public_see_only_the_ticked_ones(client, board_db):
    board_db.flags["awards_published"] = "1"
    b = board(client)
    assert b["published"] is True and b["is_staff"] is False
    assert [a["slug"] for a in b["awards"]] == ["clean-award", "renamed-award"]
    assert all(a["selected"] for a in b["awards"])


def test_publishing_is_the_awards_flag_alone(client, board_db):
    """Publishing the stats board must not carry the awards with it."""
    board_db.flags["stats_published"] = "1"
    assert board(client) == {"published": False, "awards": []}


# ── the gate's controls ───────────────────────────────────────────────────
@pytest.mark.parametrize("flag", ["stats_published", "awards_published"])
def test_each_new_flag_flips_through_the_existing_publish_route(client, board_db, flag):
    as_staff(board_db, client)
    r = client.post("/admin/publish", data={"flag": flag, "publish": "1"},
                    follow_redirects=False)
    assert r.status_code == 303
    assert board_db.writes[0][1] == (flag, "1")
    client.post("/admin/publish", data={"flag": flag}, follow_redirects=False)
    assert board_db.writes[1][1] == (flag, "0")


def test_both_flags_have_a_toggle_on_the_admin_home(client, board_db, monkeypatch):
    from app import bracket
    from app import schedule as sched
    monkeypatch.setattr(sched, "seeds_locked", lambda: False)
    monkeypatch.setattr(sched, "matches_exist", lambda: False)
    monkeypatch.setattr(bracket, "bracket_exists", lambda: False)
    board_db.add("FROM lan_teams ORDER BY", [])
    board_db.add("SELECT p.discord_id, p.display_name", [])
    as_staff(board_db, client)
    page = client.get("/admin").text
    for flag in ("stats_published", "awards_published"):
        assert f'name="flag" value="{flag}"' in page
    assert "Staff action log" in page


# ── card shape ────────────────────────────────────────────────────────────
def test_a_card_carries_winners_as_an_array_and_its_runners(client, board_db):
    as_staff(board_db, client)
    a = {x["slug"]: x for x in board(client)["awards"]}["clean-award"]
    assert a["winners"] == [{"who": "hildebrand", "alias": None, "value": "100", "where": None}]
    assert a["runners"] == [{"rank": 2, "who": "piff", "value": "80", "where": None}]
    assert a["scope"] == "weekend" and a["kind"] == "player"


def test_a_match_scope_reads_that_match_key(client, board_db):
    as_staff(board_db, client)
    board(client)
    board(client, match="sat-r1-harrington")
    assert board_db.reads["candidates"] == [(EDITION, ""), (EDITION, "sat-r1-harrington")]


def test_an_edition_is_required_of_a_caller_who_may_see_the_board(client, board_db):
    as_staff(board_db, client)
    assert client.get("/api/awards/candidates").status_code == 400


# ── renaming ──────────────────────────────────────────────────────────────
def test_an_override_ships_in_place_of_the_generated_default(client, board_db):
    as_staff(board_db, client)
    by = {a["slug"]: a for a in board(client)["awards"]}
    assert by["renamed-award"]["title"] == "The Fragger"
    assert by["renamed-award"]["sting"] == "Most kills."
    assert by["renamed-award"]["is_renamed"] is True
    assert by["clean-award"]["title"] == "Most Kills"
    assert by["clean-award"]["is_renamed"] is False


def test_a_rename_persists_and_is_global_to_the_award_type(client, board_db):
    as_staff(board_db, client)
    r = client.post("/api/awards/rename",
                    json={"slug": "clean-award", "title": "The Fragger", "sting": "Most kills."})
    assert r.json() == {"ok": True, "slug": "clean-award", "is_renamed": True,
                        "title": "The Fragger", "sting": "Most kills."}
    sql, params = board_db.writes[0]
    assert sql.startswith("UPDATE lan_award_types SET title=%s, sting=%s")
    assert params[0] == "The Fragger" and params[1] == "Most kills." and params[3] == "clean-award"
    assert "edition" not in sql          # 2027 inherits it; that is the point
    by = {a["slug"]: a for a in board(client)["awards"]}
    assert by["clean-award"]["title"] == "The Fragger"
    assert by["clean-award"]["is_renamed"] is True


def test_clearing_a_rename_restores_the_generated_default(client, board_db):
    as_staff(board_db, client)
    r = client.post("/api/awards/rename", json={"slug": "renamed-award", "title": "", "sting": ""})
    assert r.json() == {"ok": True, "slug": "renamed-award", "is_renamed": False,
                        "title": "Best Team", "sting": "Generated sting."}
    assert board_db.writes[0][1][:2] == (None, None)
    by = {a["slug"]: a for a in board(client)["awards"]}
    assert by["renamed-award"]["title"] == "Best Team"
    assert by["renamed-award"]["is_renamed"] is False


def test_a_rename_is_audited_with_both_values(client, board_db):
    as_staff(board_db, client)
    client.post("/api/awards/rename", json={"slug": "renamed-award", "title": "Top Gun"})
    sql, params = board_db.writes[1]
    assert sql.startswith("INSERT INTO lan_admin_audit")
    assert params[0] == DID and params[2] == "award_rename" and params[3] == "renamed-award"
    assert "The Fragger" in params[4] and "Top Gun" in params[5]


def test_rename_is_staff_only_and_an_unknown_slug_is_a_404(client, board_db):
    sign_in(client, OTHER)
    assert client.post("/api/awards/rename", json={"slug": "clean-award", "title": "x"}).status_code == 403
    assert board_db.writes == []
    as_staff(board_db, client)
    assert client.post("/api/awards/rename", json={"slug": "no-such", "title": "x"}).status_code == 404
    assert client.post("/api/awards/rename", json={}).status_code == 400
    assert board_db.writes == []


# ── selecting ─────────────────────────────────────────────────────────────
def test_ticking_an_award_upserts_and_audits(client, board_db):
    as_staff(board_db, client)
    r = client.post("/api/awards/select",
                    json={"edition": EDITION, "slug": "tie-award", "selected": True})
    assert r.json() == {"ok": True, "selected": True}
    sql, params = board_db.writes[0]
    assert sql.startswith("INSERT INTO lan_award_selections")
    assert "ON DUPLICATE KEY UPDATE" in sql
    assert params[:4] == (EDITION, "tie-award", "", 1)
    sql, params = board_db.writes[1]
    assert sql.startswith("INSERT INTO lan_admin_audit")
    assert params[0] == DID and params[1] == "nein" and params[2] == "award_select"
    assert params[3] == f"{EDITION}:tie-award"
    assert (params[4], params[5]) == ("0", "1")


def test_unticking_audits_the_state_it_came_from(client, board_db):
    as_staff(board_db, client)
    client.post("/api/awards/select",
                json={"edition": EDITION, "slug": "clean-award", "selected": False})
    assert board_db.writes[0][1][3] == 0
    assert board_db.writes[1][1][4:6] == ("1", "0")


def test_a_match_scoped_tick_is_audited_against_that_match(client, board_db):
    as_staff(board_db, client)
    client.post("/api/awards/select", json={"edition": EDITION, "slug": "clean-award",
                                            "match_key": "sat-r1-harrington", "selected": True})
    assert board_db.writes[0][1][2] == "sat-r1-harrington"
    assert board_db.writes[1][1][3] == f"{EDITION}:clean-award@sat-r1-harrington"


def test_select_is_staff_only_and_writes_nothing_otherwise(client, board_db):
    sign_in(client, OTHER)
    r = client.post("/api/awards/select",
                    json={"edition": EDITION, "slug": "clean-award", "selected": True})
    assert r.status_code == 403
    assert board_db.writes == []


def test_a_string_false_unticks_rather_than_ticking(client, board_db):
    as_staff(board_db, client)
    client.post("/api/awards/select",
                json={"edition": EDITION, "slug": "clean-award", "selected": "false"})
    assert board_db.writes[0][1][3] == 0


def test_select_refuses_a_slug_no_award_type_owns(client, board_db):
    as_staff(board_db, client)
    r = client.post("/api/awards/select",
                    json={"edition": EDITION, "slug": "invented", "selected": True})
    assert r.status_code == 404
    assert board_db.writes == []


# ── ordering ──────────────────────────────────────────────────────────────
def test_staff_sort_puts_a_clean_winner_above_a_wide_tie(client, board_db):
    as_staff(board_db, client)
    by = {a["slug"]: a for a in board(client)["awards"]}
    order = [a["slug"] for a in board(client)["awards"]]
    assert by["clean-award"]["tie_width"] == 1 and by["tie-award"]["tie_width"] == 28
    assert order.index("clean-award") < order.index("tie-award")
    assert order.index("renamed-award") < order.index("tie-award")


def test_public_sort_is_the_operator_order(client, board_db):
    board_db.selected = {"tie-award", "clean-award", "renamed-award"}
    board_db.flags["awards_published"] = "1"
    assert [a["slug"] for a in board(client)["awards"]] == [
        "tie-award", "clean-award", "renamed-award"]


def test_decisiveness_is_the_gap_to_the_next_distinct_value(client, board_db):
    as_staff(board_db, client)
    by = {a["slug"]: a for a in board(client)["awards"]}
    assert by["clean-award"]["decisiveness"] == pytest.approx(0.2)      # 100 v 80
    assert by["tie-award"]["decisiveness"] == pytest.approx(0.6667)     # 3 v 1
    assert by["renamed-award"]["decisiveness"] == 0.0                   # nothing follows


# ── group and render ──────────────────────────────────────────────────────
def add_award(fdb, slug, scope, kind, rows, sort_order=99):
    fdb.types[slug] = {"slug": slug, "scope": scope, "kind": kind,
                       "default_title": slug, "default_sting": "Generated sting.",
                       "title": None, "sting": None, "sort_order": sort_order}
    fdb.rows.extend(rows)


def panel_rows(slug="weekend-positions"):
    """Six slots at rank_pos 1..6 — the panel's display order, which is not what
    sorting on (role, slot) would give."""
    return [cand(slug, i + 1, f"pick{i}", 1.4 - i / 100, role=role, slot=slot, where="Sat")
            for i, (role, slot) in enumerate(PANEL_SLOTS)]


def test_every_group_is_derived_from_scope_and_kind(client, board_db):
    add_award(board_db, "team-award", "weekend", "team", [cand("team-award", 1, "dicE", 9)])
    add_award(board_db, "match-award", "match", "player",
              [cand("match-award", 1, "piff", 44, where="harrington · Sat")])
    add_award(board_db, "weekend-positions", "weekend", "player", panel_rows())
    as_staff(board_db, client)
    by = {a["slug"]: a["group"] for a in board(client)["awards"]}
    assert by["clean-award"] == "weekend"
    assert by["team-award"] == "team"
    assert by["match-award"] == "single-match"
    assert by["weekend-positions"] == "positions"


def test_a_day_scope_award_groups_with_the_weekend_totals(client, board_db):
    """MVP renormalises per day so it can only be a day award, and there is no
    day section — it falls through rather than vanishing."""
    add_award(board_db, "day-ktpr-high", "day", "player",
              [cand("day-ktpr-high", 1, "hildebrand", 1.388, where="Sat")])
    as_staff(board_db, client)
    by = {a["slug"]: a["group"] for a in board(client)["awards"]}
    assert by["day-ktpr-high"] == "weekend"


def test_an_ordinary_award_renders_as_a_card(client, board_db):
    as_staff(board_db, client)
    assert {a["render"] for a in board(client)["awards"]} == {"card"}


def test_group_of_invents_no_fifth_section():
    assert stat_awards.group_of("weekend", "player", "card") == "weekend"
    assert stat_awards.group_of("weekend", "team", "card") == "team"
    assert stat_awards.group_of("match", "player", "card") == "single-match"
    assert stat_awards.group_of("day", "player", "card") == "weekend"
    # render wins: the panel is scope weekend / kind player and would otherwise
    # be filed with the totals
    assert stat_awards.group_of("weekend", "player", "positions") == "positions"


# ── the role panel ────────────────────────────────────────────────────────
def test_the_panel_is_one_card_carrying_six_role_slots(client, board_db):
    add_award(board_db, "weekend-positions", "weekend", "player", panel_rows())
    as_staff(board_db, client)
    cards = [a for a in board(client)["awards"] if a["slug"] == "weekend-positions"]
    assert len(cards) == 1                      # one card, one checkbox
    panel = cards[0]
    assert panel["render"] == "positions" and panel["group"] == "positions"
    assert [(w["role"], w["slot"]) for w in panel["winners"]] == PANEL_SLOTS
    assert [w["who"] for w in panel["winners"]] == [f"pick{i}" for i in range(6)]
    assert panel["runners"] == []


def test_the_panel_reports_no_tie_width_and_no_margin(client, board_db):
    """Six slots is the panel's shape, not a six-way tie, and the six values are
    KTPR at different positions — neither number exists for it."""
    add_award(board_db, "weekend-positions", "weekend", "player", panel_rows())
    as_staff(board_db, client)
    panel = {a["slug"]: a for a in board(client)["awards"]}["weekend-positions"]
    assert panel["tie_width"] is None and panel["decisiveness"] is None


def test_the_staff_sort_does_not_bury_the_panel_behind_a_wide_tie(client, board_db):
    add_award(board_db, "weekend-positions", "weekend", "player", panel_rows())
    as_staff(board_db, client)
    order = [a["slug"] for a in board(client)["awards"]]
    assert order[0] == "weekend-positions"
    assert order.index("weekend-positions") < order.index("tie-award")


def test_the_panel_is_a_single_publish_decision(client, board_db):
    """Unticked, the whole panel is absent from the public board — not six rows
    to tick one at a time."""
    add_award(board_db, "weekend-positions", "weekend", "player", panel_rows())
    board_db.flags["awards_published"] = "1"
    assert "weekend-positions" not in [a["slug"] for a in board(client)["awards"]]
    board_db.selected.add("weekend-positions")
    panel = {a["slug"]: a for a in board(client)["awards"]}["weekend-positions"]
    assert len(panel["winners"]) == 6


def test_a_panel_missing_its_roles_degrades_to_a_card(client, board_db):
    """If the generator forgets role/slot the award is a plain one-winner card —
    wrong, but visibly wrong, rather than a panel with five slots missing."""
    add_award(board_db, "weekend-positions", "weekend", "player",
              [cand("weekend-positions", i + 1, f"pick{i}", 1.4) for i in range(6)])
    as_staff(board_db, client)
    panel = {a["slug"]: a for a in board(client)["awards"]}["weekend-positions"]
    assert panel["render"] == "card" and panel["tie_width"] == 1
    assert len(panel["winners"]) == 1 and len(panel["runners"]) == 5


# ── single-match records ──────────────────────────────────────────────────
def test_a_match_award_is_one_weekend_card_not_one_card_per_match(client, board_db):
    """scope 'match' means the best single match ANYONE had. The per-match rows
    for the same award sit under their own match_key and must not leak in."""
    add_award(board_db, "match-kills-high", "match", "player", [
        cand("match-kills-high", 1, "piff", 44, where="harrington · Sat · v dicE"),
        cand("match-kills-high", 2, "hildebrand", 41, where="anzio · Sun · v NATO"),
        cand("match-kills-high", 1, "someone-else", 22, where="donner", match="sat-r1"),
        cand("match-kills-high", 2, "another", 19, where="donner", match="sat-r1"),
    ])
    as_staff(board_db, client)
    cards = [a for a in board(client)["awards"] if a["slug"] == "match-kills-high"]
    assert len(cards) == 1
    card = cards[0]
    assert card["group"] == "single-match"
    assert [w["who"] for w in card["winners"]] == ["piff"]
    assert card["winners"][0]["where"] == "harrington · Sat · v dicE"
    assert [r["who"] for r in card["runners"]] == ["hildebrand"]


def test_the_per_match_view_is_the_separate_one(client, board_db):
    add_award(board_db, "match-kills-high", "match", "player", [
        cand("match-kills-high", 1, "piff", 44, where="harrington · Sat · v dicE"),
        cand("match-kills-high", 1, "someone-else", 22, where="donner", match="sat-r1"),
    ])
    as_staff(board_db, client)
    cards = board(client, match="sat-r1")["awards"]
    assert [a["slug"] for a in cards] == ["match-kills-high"]
    assert [w["who"] for w in cards[0]["winners"]] == ["someone-else"]


# ── decisiveness, on its own ──────────────────────────────────────────────
def test_decisiveness_guards_every_division():
    assert stat_awards.decisiveness([100.0, 80.0]) == pytest.approx(0.2)
    assert stat_awards.decisiveness([5.0, 5.0, 5.0]) == 0.0     # no next distinct value
    assert stat_awards.decisiveness([]) == 0.0
    assert stat_awards.decisiveness([0.0, -3.0]) == 0.0         # a share of nothing
    assert stat_awards.decisiveness([None, 3.0]) == 0.0
    assert stat_awards.decisiveness([-2.0, -6.0]) == pytest.approx(2.0)


def test_a_low_is_better_winner_does_not_score_negative():
    """A fastest-time winner sits below its runner-up; a signed margin would
    rank the whole direction as the least decisive on the board."""
    assert stat_awards.decisiveness([10.0, 12.0]) == pytest.approx(0.2)


# ── two tiers: the tally is withheld from staff ───────────────────────────
TALLY_IN_BODY = re.compile(r'"vote_count":\s*[0-9]')


def test_a_non_master_staff_body_carries_no_tally_anywhere(client, board_db):
    """Withheld the way the public board withholds award data: not sent, not
    sent-and-hidden. Asserted on the serialised response, because a page that
    is merely trusted not to render it is one view-source away."""
    cast(board_db, "clean-award", DID, OTHER, THIRD)
    as_staff(board_db, client, OTHER)
    r = client.get(f"/api/awards/candidates?edition={EDITION}")
    assert TALLY_IN_BODY.search(r.text) is None
    assert all(a["vote_count"] is None for a in r.json()["awards"])


def test_the_same_request_from_a_master_does_carry_it(client, board_db):
    """The control: without it, an assertion that finds nothing proves nothing."""
    cast(board_db, "clean-award", DID, OTHER, THIRD)
    as_master(board_db, client)
    r = client.get(f"/api/awards/candidates?edition={EDITION}")
    assert TALLY_IN_BODY.search(r.text) is not None
    by = {a["slug"]: a for a in r.json()["awards"]}
    assert by["clean-award"]["vote_count"] == 3
    assert by["tie-award"]["vote_count"] == 0       # nobody voted, not absent


def test_the_public_board_carries_none_of_the_tier_fields(client, board_db):
    cast(board_db, "clean-award", DID)
    board_db.flags["awards_published"] = "1"
    cards = board(client)["awards"]
    assert cards
    for a in cards:
        assert "vote_count" not in a and "my_vote" not in a and "can_select" not in a


def test_my_vote_is_this_caller_and_not_another(client, board_db):
    cast(board_db, "clean-award", DID)
    as_staff(board_db, client, OTHER)
    by = {a["slug"]: a for a in board(client)["awards"]}
    assert by["clean-award"]["my_vote"] is False
    assert by["tie-award"]["my_vote"] is False
    as_master(board_db, client)
    by = {a["slug"]: a for a in board(client)["awards"]}
    assert by["clean-award"]["my_vote"] is True


def test_a_per_match_nomination_does_not_light_up_the_weekend_card(client, board_db):
    cast(board_db, "clean-award", DID, match="sat-r1")
    as_master(board_db, client)
    by = {a["slug"]: a for a in board(client)["awards"]}
    assert by["clean-award"]["my_vote"] is False and by["clean-award"]["vote_count"] == 0


def test_can_select_says_master_and_only_master(client, board_db):
    as_staff(board_db, client, OTHER)
    assert all(a["can_select"] is False for a in board(client)["awards"])
    as_master(board_db, client)
    assert all(a["can_select"] is True for a in board(client)["awards"])


# ── two tiers: who may nominate, who may tick ─────────────────────────────
def test_any_staff_may_nominate_and_it_is_recorded(client, board_db):
    as_staff(board_db, client, OTHER)
    r = client.post("/api/awards/staff-vote",
                    json={"edition": EDITION, "slug": "clean-award", "voted": True})
    assert r.json() == {"ok": True, "voted": True}
    sql, params = board_db.writes[0]
    assert sql.startswith("INSERT INTO lan_award_staff_votes")
    assert params == (EDITION, "clean-award", "", OTHER)
    assert {a["slug"]: a["my_vote"] for a in board(client)["awards"]}["clean-award"] is True


def test_un_voting_deletes_the_row_rather_than_writing_a_false(client, board_db):
    """Presence of the row is the vote, so there is no stale false to reconcile."""
    cast(board_db, "clean-award", OTHER)
    as_staff(board_db, client, OTHER)
    r = client.post("/api/awards/staff-vote",
                    json={"edition": EDITION, "slug": "clean-award", "voted": False})
    assert r.json() == {"ok": True, "voted": False}
    sql, params = board_db.writes[0]
    assert sql.startswith("DELETE FROM lan_award_staff_votes")
    assert params == (EDITION, "clean-award", "", OTHER)
    assert board_db.votes[(EDITION, "", "clean-award")] == set()
    assert {a["slug"]: a["my_vote"] for a in board(client)["awards"]}["clean-award"] is False


def test_a_string_false_withdraws_rather_than_nominating(client, board_db):
    as_staff(board_db, client, OTHER)
    client.post("/api/awards/staff-vote",
                json={"edition": EDITION, "slug": "clean-award", "voted": "false"})
    assert board_db.writes[0][0].startswith("DELETE FROM lan_award_staff_votes")


def test_nominating_never_touches_the_players_ballot(client, board_db):
    """lan_award_votes is a different, live table — one word apart."""
    as_staff(board_db, client, OTHER)
    client.post("/api/awards/staff-vote",
                json={"edition": EDITION, "slug": "clean-award", "voted": True})
    client.post("/api/awards/staff-vote",
                json={"edition": EDITION, "slug": "clean-award", "voted": False})
    for sql, _ in board_db.writes:
        assert "lan_award_votes" not in sql
        assert "lan_awards " not in sql


def test_nominating_is_staff_only_and_writes_nothing_otherwise(client, board_db):
    sign_in(client, OTHER)
    r = client.post("/api/awards/staff-vote",
                    json={"edition": EDITION, "slug": "clean-award", "voted": True})
    assert r.status_code == 403
    assert board_db.writes == []


def test_a_nomination_needs_an_edition_and_a_real_award(client, board_db):
    as_staff(board_db, client, OTHER)
    assert client.post("/api/awards/staff-vote", json={"slug": "clean-award"}).status_code == 400
    assert client.post("/api/awards/staff-vote",
                       json={"edition": EDITION, "slug": "invented"}).status_code == 404
    assert board_db.writes == []


def test_selecting_is_master_only_now(client, board_db):
    as_staff(board_db, client, OTHER)
    r = client.post("/api/awards/select",
                    json={"edition": EDITION, "slug": "tie-award", "selected": True})
    assert r.status_code == 403
    assert board_db.writes == []
    as_master(board_db, client)
    r = client.post("/api/awards/select",
                    json={"edition": EDITION, "slug": "tie-award", "selected": True})
    assert r.status_code == 200 and r.json() == {"ok": True, "selected": True}


def test_a_master_id_who_is_not_staff_is_not_a_master(client, board_db):
    """Staff plus, never staff instead — losing staff access loses this too."""
    sign_in(client, THIRD)
    assert client.post("/api/awards/select",
                       json={"edition": EDITION, "slug": "tie-award",
                             "selected": True}).status_code == 403
    assert board_db.writes == []


def test_a_masters_own_vote_is_in_the_tally(client, board_db):
    cast(board_db, "tie-award", OTHER)
    as_master(board_db, client)
    client.post("/api/awards/staff-vote",
                json={"edition": EDITION, "slug": "tie-award", "voted": True})
    card = {a["slug"]: a for a in board(client)["awards"]}["tie-award"]
    assert card["vote_count"] == 2 and card["my_vote"] is True


def test_a_master_may_tick_an_award_nobody_nominated(client, board_db):
    as_master(board_db, client)
    client.post("/api/awards/select",
                json={"edition": EDITION, "slug": "tie-award", "selected": True})
    board_db.selected.add("tie-award")
    card = {a["slug"]: a for a in board(client)["awards"]}["tie-award"]
    assert card["selected"] is True and card["vote_count"] == 0 and card["my_vote"] is False


def test_a_nomination_selects_nothing(client, board_db):
    as_master(board_db, client)
    client.post("/api/awards/staff-vote",
                json={"edition": EDITION, "slug": "tie-award", "voted": True})
    assert not any(w[0].startswith("INSERT INTO lan_award_selections") for w in board_db.writes)
    card = {a["slug"]: a for a in board(client)["awards"]}["tie-award"]
    assert card["my_vote"] is True and card["selected"] is False


def test_both_actions_write_their_own_audit_row(client, board_db):
    as_master(board_db, client)
    client.post("/api/awards/staff-vote",
                json={"edition": EDITION, "slug": "tie-award", "voted": True})
    sql, params = board_db.writes[1]
    assert sql.startswith("INSERT INTO lan_admin_audit")
    assert params[0] == DID and params[2] == "award_staff_vote"
    assert params[3] == f"{EDITION}:tie-award" and (params[4], params[5]) == ("0", "1")
    client.post("/api/awards/select",
                json={"edition": EDITION, "slug": "tie-award", "selected": True})
    assert board_db.writes[3][1][2] == "award_select"


def test_a_withdrawal_audits_the_state_it_came_from(client, board_db):
    cast(board_db, "tie-award", OTHER)
    as_staff(board_db, client, OTHER)
    client.post("/api/awards/staff-vote",
                json={"edition": EDITION, "slug": "tie-award", "voted": False})
    assert board_db.writes[1][1][4:6] == ("1", "0")


def test_a_match_scoped_nomination_is_audited_against_that_match(client, board_db):
    as_staff(board_db, client, OTHER)
    client.post("/api/awards/staff-vote",
                json={"edition": EDITION, "slug": "clean-award",
                      "match_key": "sat-r1-harrington", "voted": True})
    assert board_db.writes[0][1][2] == "sat-r1-harrington"
    assert board_db.writes[1][1][3] == f"{EDITION}:clean-award@sat-r1-harrington"
