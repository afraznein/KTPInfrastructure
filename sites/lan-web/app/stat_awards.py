"""Generated stat awards — the candidates a stats build produced, plus the
operator intent (a tick, a retitle) kept in tables of its own so a regeneration
can never clobber it.

Distinct from awards.py, which is the players' post-event vote. Nothing here
reads or writes that ballot."""
from __future__ import annotations

import json

from . import db

WEEKEND = ""  # the match_key an event-wide award carries


def ref(edition: str, slug: str, match_key: str = WEEKEND) -> str:
    """Audit target for one award in one edition."""
    return f"{edition}:{slug}" + (f"@{match_key}" if match_key else "")


def override_note(title, sting) -> str:
    """Both halves of an operator retitle, as one audit value."""
    return json.dumps({"title": title, "sting": sting}, ensure_ascii=False)


def decisiveness(values: list) -> float:
    """How far clear the winner is, as a share of the winning value.

    Magnitude, not signed, so a fastest-time award scores the same way a
    most-kills one does — `values` arrives already ordered with the winner
    first. 0.0 when nothing distinct follows, and when the winner is 0: a share
    of nothing is not a margin."""
    if not values or values[0] is None:
        return 0.0
    v1 = values[0]
    nxt = next((v for v in values[1:] if v is not None and v != v1), None)
    if nxt is None or v1 == 0:
        return 0.0
    return abs(v1 - nxt) / abs(v1)


def _num(v):
    """value_num is a Decimal from MySQL, or NULL on an unrankable row."""
    return None if v is None else float(v)


def award_types() -> dict[str, dict]:
    return {r["slug"]: r for r in db.query_all(
        "SELECT slug, scope, kind, default_title, default_sting, title, sting, sort_order "
        "FROM lan_award_types WHERE retired=0 ORDER BY sort_order, slug"
    )}


def award_type(slug: str) -> dict | None:
    return db.query_one(
        "SELECT slug, default_title, default_sting, title, sting "
        "FROM lan_award_types WHERE slug=%s",
        (slug,),
    )


def candidates(edition: str, match_key: str = WEEKEND) -> list[dict]:
    """One award's rows for one scope.

    A match-scope award at match_key '' is the best single match ANYONE had all
    weekend — one card, with where_text naming the match it happened in. Passing
    a real match_key is the separate per-match view."""
    return db.query_all(
        "SELECT award_slug, rank_pos, who, who_alias, role, slot, "
        "       value_num, value_text, where_text "
        "FROM lan_award_candidates WHERE edition=%s AND match_key=%s "
        "ORDER BY award_slug, rank_pos, who",
        (edition, match_key),
    )


def selected_slugs(edition: str, match_key: str = WEEKEND) -> set[str]:
    return {r["award_slug"] for r in db.query_all(
        "SELECT award_slug FROM lan_award_selections "
        "WHERE edition=%s AND match_key=%s AND selected=1",
        (edition, match_key),
    )}


def voted_slugs(edition: str, match_key: str, voter) -> set[str]:
    """What one staff member has nominated in this scope."""
    return {r["award_slug"] for r in db.query_all(
        "SELECT award_slug FROM lan_award_staff_votes "
        "WHERE edition=%s AND match_key=%s AND voter=%s",
        (edition, match_key, int(voter)),
    )}


def vote_counts(edition: str, match_key: str) -> dict[str, int]:
    """The tally, master admins only. Awards nobody voted for are absent."""
    return {r["award_slug"]: int(r["n"]) for r in db.query_all(
        "SELECT award_slug, COUNT(*) AS n FROM lan_award_staff_votes "
        "WHERE edition=%s AND match_key=%s GROUP BY award_slug",
        (edition, match_key),
    )}


def vote_state(edition: str, slug: str, match_key: str, voter) -> bool:
    r = db.query_one(
        "SELECT 1 AS voted FROM lan_award_staff_votes "
        "WHERE edition=%s AND award_slug=%s AND match_key=%s AND voter=%s",
        (edition, slug, match_key, int(voter)),
    )
    return r is not None


def set_vote(edition: str, slug: str, match_key: str, voted: bool, voter) -> None:
    """The row's presence is the vote, so un-voting deletes rather than writing
    a false there is no later pass to reconcile."""
    if not voted:
        db.execute(
            "DELETE FROM lan_award_staff_votes "
            "WHERE edition=%s AND award_slug=%s AND match_key=%s AND voter=%s",
            (edition, slug, match_key, int(voter)),
        )
        return
    db.execute(
        "INSERT INTO lan_award_staff_votes (edition, award_slug, match_key, voter) "
        "VALUES (%s,%s,%s,%s) ON DUPLICATE KEY UPDATE voted_at=voted_at",
        (edition, slug, match_key, int(voter)),
    )


def group_of(scope: str, kind: str, render: str) -> str:
    """Which section of the page an award belongs in.

    Falls through to 'weekend' rather than inventing a fifth section, so a
    day-scope player award (MVP renormalises per day, so it can only be a day
    award) lands with the weekend totals instead of vanishing."""
    if render == "positions":
        return "positions"
    if kind == "team":
        return "team"
    if scope == "match":
        return "single-match"
    return "weekend"


def _card(t: dict, rows: list[dict], selected: bool) -> dict | None:
    # A row carrying a role marks the whole award as the six-slot panel. Derived
    # from the data, not from the slug, so the panel is not one magic string.
    positions = any(r.get("role") for r in rows)
    winners = rows if positions else [r for r in rows if r["rank_pos"] == 1]
    if not winners:
        return None
    render = "positions" if positions else "card"

    def entry(r: dict) -> dict:
        e = {"who": r["who"], "alias": r["who_alias"],
             "value": r["value_text"], "where": r["where_text"]}
        if positions:
            e["role"], e["slot"] = r.get("role"), r.get("slot")
        return e

    return {
        "slug": t["slug"],
        "title": t["title"] or t["default_title"],
        "sting": t["sting"] or t["default_sting"],
        "is_renamed": bool(t["title"]),
        "scope": t["scope"],
        "kind": t["kind"],
        "group": group_of(t["scope"], t["kind"], render),
        "render": render,
        "selected": selected,
        # Six role slots are the panel's shape, not a six-way tie, and the two
        # margins compare KTPR across different positions. null says "does not
        # apply" where a number would read as a plausible answer.
        "tie_width": None if positions else len(winners),
        "decisiveness": None if positions else round(
            decisiveness([_num(r["value_num"]) for r in rows]), 4),
        "winners": [entry(r) for r in winners],
        "runners": [] if positions else [
            {"rank": r["rank_pos"], "who": r["who"],
             "value": r["value_text"], "where": r["where_text"]}
            for r in rows if r["rank_pos"] > 1],
    }


def staff_sort_key(card: dict, rank: int) -> tuple:
    """Clean winner above wide tie, decisive above marginal, operator order last.

    The role panel sorts ahead of every card: neither half of that ordering
    means anything for it, and a tie width of six would otherwise file the one
    award staff most need to look at as the most indecisive on the board."""
    if card["render"] == "positions":
        return (0, 0, 0.0, rank)
    return (1, card["tie_width"], -card["decisiveness"], rank)


def board(edition: str, match_key: str = WEEKEND, staff: bool = False,
          voter=None, master: bool = False) -> list[dict]:
    """Award cards for one edition, ready to render.

    Staff get every candidate the build produced; everyone else gets only what
    staff ticked. Staff order surfaces the awards worth reviewing first — a
    clean single winner above a wide tie, decisive above marginal — while the
    public order is the operator's own.

    The two tiers ride along per card: a staff member's own nomination, and —
    for a master admin only — the tally and the right to tick."""
    types = award_types()
    picked = selected_slugs(edition, match_key)
    # Guarded so a public request never touches the vote table at all, and a
    # non-master never reads the tally even to discard it.
    mine = voted_slugs(edition, match_key, voter) if staff and voter else set()
    counts = vote_counts(edition, match_key) if staff and master else {}
    grouped: dict[str, list[dict]] = {}
    for r in candidates(edition, match_key):
        grouped.setdefault(r["award_slug"], []).append(r)

    order = {slug: i for i, slug in enumerate(types)}
    out = []
    for slug, rows in grouped.items():
        t = types.get(slug)
        if t is None:  # retired, or a slug this build invented
            continue
        is_sel = slug in picked
        if not (staff or is_sel):
            continue
        card = _card(t, rows, is_sel)
        if not card:
            continue
        if staff:
            card["my_vote"] = slug in mine
            # Withheld the way award data is withheld from the public: a
            # non-master is sent no tally, not a tally the page is trusted to
            # hide. Never derived from `selected` — the two are independent.
            card["vote_count"] = counts.get(slug, 0) if master else None
            card["can_select"] = master
        out.append(card)

    if staff:
        out.sort(key=lambda a: staff_sort_key(a, order[a["slug"]]))
    else:
        out.sort(key=lambda a: order[a["slug"]])
    return out


def selection_state(edition: str, slug: str, match_key: str = WEEKEND) -> bool:
    r = db.query_one(
        "SELECT selected FROM lan_award_selections "
        "WHERE edition=%s AND award_slug=%s AND match_key=%s",
        (edition, slug, match_key),
    )
    return bool(r and r["selected"])


def set_selected(edition: str, slug: str, match_key: str, selected: bool, actor) -> None:
    db.execute(
        "INSERT INTO lan_award_selections "
        "(edition, award_slug, match_key, selected, selected_by, selected_at) "
        "VALUES (%s,%s,%s,%s,%s,NOW()) "
        "ON DUPLICATE KEY UPDATE selected=VALUES(selected), "
        "selected_by=VALUES(selected_by), selected_at=VALUES(selected_at)",
        (edition, slug, match_key, 1 if selected else 0, int(actor)),
    )


def rename(slug: str, title: str | None, sting: str | None, actor) -> None:
    """Global to the award type, so next year's edition inherits it. NULL means
    "use the generated default", which is how a retitle is cleared."""
    db.execute(
        "UPDATE lan_award_types SET title=%s, sting=%s, updated_by=%s WHERE slug=%s",
        (title, sting, int(actor), slug),
    )
