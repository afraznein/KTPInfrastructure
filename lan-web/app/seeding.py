"""Weighted peer-ranking seed computation + ballot storage.

Each captain ranks the OTHER teams (1 = strongest). Ballots are weighted by
the submitting team's own consensus standing, iterated to a fixed point so
the strong teams' opinions count more without being arbitrary. Lower score =
stronger = better seed."""
from __future__ import annotations

# db is imported lazily inside the persistence helpers so the pure algorithm
# below is importable (and unit-testable) without a MySQL driver present.


# ── pure algorithm (no DB; unit-tested) ──────────────────────────────────
def compute_seeds(ballots: dict[int, dict[int, int]], team_ids: list[int],
                  max_iter: int = 25):
    """Returns (standing, score, weight).

    ballots: {voting_team_id: {ranked_team_id: rank}}  (rank 1 = strongest)
    standing: team ids strongest→weakest.  Deterministic fixed point."""
    teams = list(team_ids)
    voters = [v for v in teams if ballots.get(v)]
    weight = {t: 1.0 for t in teams}
    worst = float(len(teams))  # score for a team nobody ranked
    standing = sorted(teams)

    for _ in range(max_iter):
        score = {}
        for j in teams:
            num = den = 0.0
            for v in voters:
                if v == j:
                    continue
                r = ballots[v].get(j)
                if r is None:
                    continue
                num += weight[v] * r
                den += weight[v]
            score[j] = num / den if den else worst
        new_standing = sorted(teams, key=lambda t: (score[t], t))
        pos = {t: i + 1 for i, t in enumerate(new_standing)}
        weight = {t: float(len(teams) + 1 - pos[t]) for t in teams}  # 1st ballot heaviest
        if new_standing == standing:
            return new_standing, score, weight
        standing = new_standing
    return standing, score, weight


# ── persistence ──────────────────────────────────────────────────────────
def save_ballot(voting_team_id: int, ranks: dict[int, int], submitted_by: int | None = None):
    """ranks: {ranked_team_id: rank}. Replaces any prior ballot for this team."""
    from . import db
    with db.get_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM lan_seed_ballots WHERE voting_team_id=%s", (voting_team_id,))
        for ranked_id, rank in ranks.items():
            cur.execute(
                "INSERT INTO lan_seed_ballots (voting_team_id, ranked_team_id, rank_pos, submitted_by) "
                "VALUES (%s, %s, %s, %s)",
                (voting_team_id, ranked_id, rank, submitted_by),
            )


def get_all_ballots() -> dict[int, dict[int, int]]:
    from . import db
    rows = db.query_all("SELECT voting_team_id, ranked_team_id, rank_pos FROM lan_seed_ballots")
    out: dict[int, dict[int, int]] = {}
    for r in rows:
        out.setdefault(r["voting_team_id"], {})[r["ranked_team_id"]] = r["rank_pos"]
    return out


def get_team_ballot(voting_team_id: int) -> dict[int, int]:
    from . import db
    rows = db.query_all(
        "SELECT ranked_team_id, rank_pos FROM lan_seed_ballots WHERE voting_team_id=%s ORDER BY rank_pos",
        (voting_team_id,),
    )
    return {r["ranked_team_id"]: r["rank_pos"] for r in rows}


def compute_and_store():
    """Compute seeds from current ballots and write them onto lan_teams.seed."""
    from . import db
    ids = [t["id"] for t in db.query_all("SELECT id FROM lan_teams")]
    ballots = get_all_ballots()
    standing, score, weight = compute_seeds(ballots, ids)
    with db.get_conn() as conn, conn.cursor() as cur:
        for seed, tid in enumerate(standing, 1):
            cur.execute("UPDATE lan_teams SET seed=%s WHERE id=%s", (seed, tid))
    return standing, score, weight


# ── poll state (lan_settings) ─────────────────────────────────────────────
def get_setting(key: str, default=None):
    from . import db
    row = db.query_one("SELECT v FROM lan_settings WHERE k=%s", (key,))
    return row["v"] if row else default


def set_setting(key: str, value):
    from . import db
    db.execute(
        "INSERT INTO lan_settings (k, v) VALUES (%s, %s) ON DUPLICATE KEY UPDATE v=VALUES(v)",
        (key, str(value)),
    )


def poll_is_open() -> bool:
    return get_setting("poll_open", "0") == "1"


# ── publish gates (staff review before public reveal) ─────────────────────
# Results/schedules are computed the moment a poll closes or a schedule is
# generated, but stay staff-only until an admin explicitly publishes them —
# so staff can eyeball everything before it goes public. Admins always see the
# unpublished view; publishing is a reversible toggle. Same shape as the
# final-placements gate (published-or-nothing for the public).
PUBLISH_FLAGS = frozenset({
    "seeding_results_published",
    "map_skip_results_published",
    "schedule_sat_published",
    "schedule_sun_published",
})


def is_published(flag: str) -> bool:
    return get_setting(flag, "0") == "1"


def reveal_poll_results(is_admin: bool, poll_open: bool, published: bool,
                        viewer_on_team: bool = False) -> bool:
    """Who may see a poll's tally/ballots.

    While voting is OPEN the poll is blind: anyone on a competing team is hidden
    from the results — including staff who are also captains/players — so no one
    peeks before their team votes. Only neutral (teamless) staff may watch it
    fill in. Once voting CLOSES, staff see everything; the public sees it only
    after an admin publishes the result."""
    if poll_open:
        return is_admin and not viewer_on_team
    return is_admin or published


def reveal_schedule(is_admin: bool, published: bool) -> bool:
    """A generated schedule/bracket shows to the public only once staff publish
    it. Staff always see it for review."""
    return is_admin or published
