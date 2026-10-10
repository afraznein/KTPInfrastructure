"""The exporter must file a half-leaver on his own team, not the opponent's.

`ktp_match_players.team` is the side held in the LAST half a player appeared
in, and DoD swaps sides at the break -- so a player who leaves at half keeps a
side that by then belongs to the other team. KTPInfrastructure#496 corrected
the match report and deliberately stopped there; the site reads this
exporter's `gameTeam` and nothing else, which is why
https://ktpleague.gg/player/las1k64 still filed him under `uD` -- and, because
he is registered elsewhere, marked the stint a RINGER for the team he played
against. Coordination: infra-half-side-correction.
"""
import importlib.util
import random
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "ktp-stats-export.py"


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("_ktp_stats_export", SCRIPT)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def canonical_impl():
    """The canonical implementation the exporter's copy must agree with."""
    sys.path.insert(0, str(REPO))
    from scripts.roster_teams import canonical_teams
    return canonical_teams


class _Db:
    """Answers each query by what it asks for. Order matters: the box-score and
    objective queries both mention ktp_life_events in their restart CTE, so the
    side feed is recognised by the column list it actually selects."""

    def __init__(self, *, roster, sides, box=(), events=(), points=()):
        self.roster, self.sides = roster, sides
        self.box, self.events, self.points = box, events, points
        self.sql = []

    def json_rows(self, sql):
        self.sql.append(sql)
        if "'playerId', player_id, 'team', team" in sql:
            return list(self.sides)
        if "ktp_match_players" in sql:
            return list(self.roster)
        if "ktp_match_stats" in sql:
            return list(self.box)
        if "hlstats_Events_Teamkills" in sql:
            return list(self.events)
        if "ktp_flag_captures" in sql:
            return list(self.points)
        return []


def _sides(rows):
    """(half, player_id, engine side) -> the exporter's row shape."""
    return [{"half": h, "playerId": p, "team": t} for h, p, t in rows]


# The real specimen, 1789952635-NY1 (2026-09-20, official). `[ o_o ]` held
# engine side 2 in half 1 and side 1 in half 2; Las1K64 (900) played half 1
# only and was subbed out at the break, so his roster row says side 2 -- which
# in half 2 is `uD`.
SPECIMEN = _sides(
    [(1, 900, 2)]
    + [(1, p, 2) for p in (901, 902, 903, 904, 905, 906)]
    + [(1, p, 1) for p in (910, 911, 912, 913, 914, 915)]
    + [(2, p, 1) for p in (901, 902, 903, 904, 905, 906)]
    + [(2, p, 2) for p in (910, 911, 912, 913, 914, 915)]
)


def _build(mod, roster, sides):
    db = _Db(roster=roster, sides=sides,
             box=[{"playerId": r["playerId"], "kills": 1, "deaths": 1}
                  for r in roster],
             events=[{"playerId": r["playerId"], "kills": 1, "deaths": 1}
                     for r in roster])
    match = {"gameMatchId": "1789952635-NY1", "serverId": 1,
             "mapName": "dod_donner", "startedAt": 0, "endedAt": 1,
             "halfCount": 2}
    return db, mod.build_match(db, match, True)


def test_a_half_leaver_is_exported_on_his_own_team(mod):
    roster = [{"steamId": "0:900", "playerName": "Las1K64", "team": 2,
               "playerId": 900}]
    roster += [{"steamId": f"0:{p}", "playerName": str(p), "team": 1,
                "playerId": p} for p in (901, 902, 903, 904, 905, 906)]
    _, match = _build(mod, roster, SPECIMEN)
    by_id = {p["steamId64"]: p for p in match["players"]}
    leaver = by_id[mod.steamid64("0:900")]
    teammate = by_id[mod.steamid64("0:901")]
    # The whole point: he ships on the same side as the clanmates he played with.
    assert leaver["gameTeam"] == teammate["gameTeam"] == 1


def test_everyone_present_at_match_end_is_untouched(mod):
    """`gameTeam` keeps its meaning -- the side held at match end -- so only the
    rows the roster got wrong may move. A no-op for every full-match player."""
    roster = [{"steamId": f"0:{p}", "playerName": str(p), "team": t,
               "playerId": p}
              for p, t in [(901, 1), (902, 1), (910, 2), (911, 2)]]
    _, match = _build(mod, roster, SPECIMEN)
    got = {p["steamId64"]: p["gameTeam"] for p in match["players"]}
    for p, t in [(901, 1), (902, 1), (910, 2), (911, 2)]:
        assert got[mod.steamid64(f"0:{p}")] == t


def test_a_one_half_match_leaves_the_roster_alone(mod):
    """With no second half there is nothing to compare, so the roster's own
    team is as good as it gets -- never a guess."""
    roster = [{"steamId": "0:901", "playerName": "a", "team": 2,
               "playerId": 901}]
    _, match = _build(mod, roster, _sides([(1, 901, 2), (1, 910, 1)]))
    assert match["players"][0]["gameTeam"] == 2


def test_a_missing_life_feed_leaves_the_roster_alone(mod):
    roster = [{"steamId": "0:901", "playerName": "a", "team": 2,
               "playerId": 901}]
    _, match = _build(mod, roster, [])
    assert match["players"][0]["gameTeam"] == 2


def test_the_side_feed_carries_the_same_guards_as_the_report(mod):
    """Both must reach the same answer, so both must read the same rows --
    sql/analytics/life_boundary_fact.sql."""
    db = _Db(roster=[], sides=[])
    mod.fetch_life_sides(db, "1789952635-NY1")
    sql = db.sql[0]
    assert "from ktp_life_events" in sql
    assert "half > 0" in sql
    assert "game_time >= 0" in sql
    assert "event_epoch > 0" in sql
    assert "1789952635-NY1" in sql


def test_the_vendored_copy_agrees_with_roster_teams(mod, canonical_impl):
    """The duplicate algorithm must not drift from its canonical copy.

    Same guard as test_official_types_match_the_report_pipeline, but behavioural:
    the exporter deploys standalone to /usr/local/bin and cannot import it.
    """
    rng = random.Random(20260920)
    for _ in range(400):
        rows = []
        players = list(range(900, 900 + rng.randint(2, 12)))
        for half in range(1, rng.randint(2, 4)):
            flip = rng.random() < 0.7
            for pid in players:
                if rng.random() < 0.15:
                    continue  # absent that half
                side = 1 if pid % 2 else 2
                if flip and half % 2 == 0:
                    side = 2 if side == 1 else 1
                rows.append((half, pid, side))
        mine = mod.canonical_teams(_sides(rows))
        theirs = canonical_impl(
            [{"half": h, "player_id": p, "team": t} for h, p, t in rows])
        assert mine == theirs


def test_both_copies_shrug_off_a_malformed_row(mod, canonical_impl):
    """Neither may raise on a row the other would skip, or the agreement above
    is only true for the inputs that happen to be clean."""
    junk = [(None, 900, 1), (1, None, 1), (1, 901, "x"), (1, 902, 3), (0, 903, 1)]
    good = [(1, 910, 1), (1, 911, 2), (2, 910, 2), (2, 911, 1)]
    mine = mod.canonical_teams(_sides(junk + good))
    theirs = canonical_impl(
        [{"half": h, "player_id": p, "team": t} for h, p, t in junk + good])
    assert mine == theirs == {910: 2, 911: 1}
