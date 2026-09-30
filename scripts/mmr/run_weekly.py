"""Weekly MMR update: predict, score the predictions, update ratings, report.

Runs the whole loop the user described: take each newly-completed league
match, compute each side's strength from its players' current ratings,
predict the winner BEFORE looking at the result, then compare against what
actually happened and update every player's rating accordingly. Over weeks
this is what makes the rating converge.

Everything it needs is public website data (anon key): official results from
ktp.match, rosters from season_team_member, divisions from division. No
game-server credentials -- which is what makes running this in CI practical.
Richer performance-weighted updates (KTPR v2 components) need game-server
data and stay a separate, later step.

Outputs, all written next to this script:
  ratings_current.json   -- ratings after this run (the operative set)
  weekly_digest.md       -- human-readable report for the week
  weekly_summary.json    -- machine-readable, for the CI job to open an issue

Deliberately recomputes the whole ladder from scratch every run rather than
incrementally updating a stored state: the corpus is small, ratings are
path-dependent, and a full deterministic replay means a bad week can never
silently corrupt the running state -- rerun and you get the same answer.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.request
import urllib.error
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import ladder as L
import match_binding as MB
import performance as PF
import dossier as DOSSIER
import mmr_payload as MMRP

HERE = Path(__file__).parent
DATA = HERE / "data"
PROJECT_URL = "https://yxpjfenpnwksvvquqlde.supabase.co"
STEAM64_BASE = 76561197960265728
CONFIDENT_MISS = 0.70  # same threshold as phase3_lite.py


def fetch(key: str, table: str, select: str, extra: str = "") -> list[dict]:
    url = f"{PROJECT_URL}/rest/v1/{table}?select={select}&limit=1000{extra}"
    req = urllib.request.Request(url, headers={
        "apikey": key, "Authorization": f"Bearer {key}", "Accept-Profile": "ktp",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{table}: HTTP {e.code} -- {e.read().decode('utf-8','replace')[:300]}") from e


def steam64_to_hlstats(steam_id64: str) -> str:
    n = int(steam_id64) - STEAM64_BASE
    return f"{n % 2}:{n // 2}"


def load_bridge() -> dict[str, int] | None:
    """steam "authserver:accountid" -> hlstatsx player_id, if the local file
    from the game server is present. Optional on purpose: in CI it is absent,
    and the ladder keys on the website's own player_id instead. That keeps
    Steam IDs out of the repo entirely and keeps the scheduled job dependent
    on nothing but public website data. Locally the bridge is used so ratings
    line up with the S9 research corpus, which is keyed on hlstatsx ids."""
    path = DATA / "hlstats_player_unique_ids.tsv"
    if not path.exists():
        return None
    bridge = {}
    for line in open(path, encoding="utf-8"):
        parts = line.rstrip("\n").split("\t")
        if len(parts) == 2 and parts[1] != "uniqueId":
            bridge[parts[1]] = int(parts[0])
    return bridge


def actual_participants(key: str, fixtures, rosters):
    """{fixture_id: binding} for fixtures whose game match can be identified.

    The ladder needs who PLAYED, not who is registered. See match_binding for
    why that distinction is the difference between a player rating and a team
    rating. Only website player ids are usable here (game_match_player carries
    those), so this runs on the CI identity path.
    """
    completed = [f for f in fixtures if f.get("home_score") is not None]
    if not completed:
        return {}
    earliest = min(f["scheduled_at"] for f in completed if f.get("scheduled_at"))
    window_start = str(earliest)[:10]
    games = fetch(key, "game_match", "id,game_match_id,started_at,map_name,player_count",
                  f"&started_at=gte.{window_start}&order=started_at")
    if not games:
        return {}
    ids = ",".join(str(g["id"]) for g in games)
    people = fetch(key, "game_match_player",
                   "game_match_id,player_id,game_team,player_name",
                   f"&game_match_id=in.({ids})")
    by_game = defaultdict(list)
    for row in people:
        by_game[row["game_match_id"]].append(row)
    bound, unbound = MB.bind(completed, games, by_game, rosters)
    for miss in unbound:
        print(f"  fixture {miss['fixture_id']}: {miss['reason']} "
              f"-- falling back to the registered roster")
    return bound


def performance_scores(key: str, bindings) -> dict:
    """{fixture_id: {player_id: blended z-score}} from the match reports.

    Only fixtures already bound to a game match can be looked up, since the
    report is keyed by the game match id. A fixture with no report, or a
    report whose KTPR block is unavailable, simply yields nothing and that
    match falls back to an even split -- never to zeros, which would read as
    "everyone played badly".

    Report player names are website ALIASES, so the join is
    alias -> ktp.player.id. Verified on real S10 data: joining instead on
    game_match_player.player_name (the in-game name, clan tag and all) hits
    0 of 12; joining on alias hits 12 of 12.
    """
    if not bindings:
        return {}
    alias_to_id = {}
    for row in fetch(key, "player", "id,alias"):
        alias = PF.normalize_name(row.get("alias"))
        if alias and alias not in alias_to_id:   # ambiguous alias -> resolve to nobody
            alias_to_id[alias] = row["id"]
        elif alias:
            alias_to_id[alias] = None
    wanted = {b["game_match_id"] for b in bindings.values() if b.get("game_match_id")}
    if not wanted:
        return {}
    quoted = ",".join(f'"{m}"' for m in sorted(wanted))
    reports = fetch(key, "match_report", "match_id,revision,payload",
                    f"&match_id=in.({quoted})&order=revision")
    latest = {r["match_id"]: r for r in reports}   # ordered by revision, last wins
    out = {}
    for fixture_id, binding in bindings.items():
        report = latest.get(binding.get("game_match_id"))
        if not report:
            continue
        by_alias = PF.components_by_alias(report.get("payload"))
        scores = PF.player_scores(by_alias)
        by_id = {alias_to_id[a]: z for a, z in scores.items()
                 if alias_to_id.get(a) is not None}
        if by_id:
            out[fixture_id] = by_id
    return out


def upset_dossiers(key, upsets, bindings, matches):
    """Markdown explaining each confident miss in terms of who played how.

    Built for reporting regardless of whether performance weighting is
    enabled: explaining a miss is useful even when the rating is not yet
    using that signal. Degrades to nothing if the reports are unavailable.
    """
    if not upsets or not bindings:
        return []
    try:
        scores_by_fixture = performance_scores(key, bindings)
        names = {row["id"]: row.get("alias") for row in fetch(key, "player", "id,alias")}
    except RuntimeError as exc:      # reporting must never break the run
        print(f"  dossiers unavailable: {exc}")
        return []
    # The digest rows carry no rosters -- only the source matches do -- so
    # rejoin by match_id rather than widening every row with two player lists.
    rosters = {m["match_id"]: m for m in matches}
    built = []
    for row in upsets:
        source = rosters.get(row["match_id"])
        if not source:
            continue
        fixture_id = int(str(row["match_id"]).rsplit("-", 1)[-1])
        context = {**row, "t1": source["t1"], "t2": source["t2"]}
        d = DOSSIER.build(context, scores_by_fixture.get(fixture_id) or {}, names)
        if d:
            built.append(d)
    return DOSSIER.render(built)


def apply_performance(key, matches, bindings, strength):
    """Attach per-player shares to each match that has a usable report.

    Returns how many matches got them, so the digest can say what fraction of
    the week was actually split by performance rather than evenly -- a number
    that silently drops to zero if the report pipeline stalls is exactly the
    kind of thing that should be visible, not assumed.
    """
    scores_by_fixture = performance_scores(key, bindings)
    applied = 0
    for m in matches:
        fixture_id = int(str(m["match_id"]).rsplit("-", 1)[-1])
        scores = scores_by_fixture.get(fixture_id)
        if not scores:
            continue
        home, away = PF.match_shares(m["t1"], m["t2"], scores, strength)
        m["shares"] = {**home, **away}
        applied += 1
    return applied


def build_league_matches(key: str) -> tuple[list[dict], dict]:
    """Completed league matches with both scores, newest last."""
    bridge = load_bridge()
    # identity merges are keyed on hlstatsx ids, so they only apply on the
    # local path; in CI (website ids) there is nothing to merge against.
    merges = L.load_identity_merges() if bridge is not None else {}
    matches_raw = fetch(key, "match", "id,season_id,week_id,division_id,home_season_team_id,"
                                       "away_season_team_id,scheduled_at,status,home_score,away_score,"
                                       "winner_season_team_id", "&order=scheduled_at")
    season_teams = {t["id"]: t for t in fetch(key, "season_team", "id,season_id,team_id,division_id,status")}
    teams = {t["id"]: t["name"] for t in fetch(key, "team", "id,name")}
    divisions = {d["id"]: d["name"] for d in fetch(key, "division", "id,name,season_id")}
    steam_by_pid = {p["player_id"]: p["steam_id64"]
                    for p in fetch(key, "player_steam", "player_id,steam_id64,status")
                    if p["status"] == "current"}

    rosters = defaultdict(set)
    # Division per player, for the seeding prior. Built HERE, in the same loop,
    # deliberately: the resolved pid differs between the CI path (website ids)
    # and the local path (hlstatsx ids via the bridge), and a label keyed in the
    # wrong space silently matches nobody. division_history.py cannot serve this
    # -- it keys on hlstatsx ids and needs the data server's identity bridge,
    # which CI does not have.
    div_by_pid, div_season = {}, {}
    for row in fetch(key, "season_team_member", "season_team_id,player_id,left_at"):
        if row.get("left_at"):
            continue
        st = season_teams.get(row["season_team_id"]) or {}
        dname = divisions.get(st.get("division_id"))
        season = st.get("season_id") or 0
        if bridge is None:
            # CI path: key on the website's own player_id, no Steam ID needed.
            pid = row["player_id"]
            rosters[row["season_team_id"]].add(pid)
        else:
            steam64 = steam_by_pid.get(row["player_id"])
            if not steam64:
                continue
            pid = bridge.get(steam64_to_hlstats(steam64))
            if pid is None:
                continue
            pid = merges.get(pid, pid)
            rosters[row["season_team_id"]].add(pid)
        # Most recent season wins: a promoted player is seeded where they play
        # now, not where they came from.
        if dname and season >= div_season.get(pid, -1):
            div_by_pid[pid], div_season[pid] = dname, season

    # Who ACTUALLY played, where we can establish it. Falls back to the
    # registered roster per fixture, which is recorded so the digest can say
    # how much of the week was rated on real participation.
    played = actual_participants(key, matches_raw, rosters) if bridge is None else {}

    out, pending, used_actual, ringer_appearances = [], 0, 0, 0
    for m in matches_raw:
        if m["home_score"] is None or m["away_score"] is None or m["home_score"] == m["away_score"]:
            pending += 1
            continue
        binding = played.get(m["id"])
        if binding:
            home, away = set(binding["home_players"]), set(binding["away_players"])
            used_actual += 1
            ringer_appearances += len(binding.get("ringers", []))
        else:
            home = rosters.get(m["home_season_team_id"], set())
            away = rosters.get(m["away_season_team_id"], set())
        if len(home) < 4 or len(away) < 4:
            continue
        st_home = season_teams.get(m["home_season_team_id"], {})
        st_away = season_teams.get(m["away_season_team_id"], {})
        out.append(dict(
            match_id=f"league-{m['id']}", when=m["scheduled_at"] or "",
            map=divisions.get(m["division_id"], "?"),
            home_team=teams.get(st_home.get("team_id"), "?"),
            away_team=teams.get(st_away.get("team_id"), "?"),
            division=divisions.get(m["division_id"], "?"),
            t1=sorted(home), t2=sorted(away),
            y=1.0 if m["home_score"] > m["away_score"] else 0.0,
            margin=abs(m["home_score"] - m["away_score"]),
            home_score=m["home_score"], away_score=m["away_score"],
            actual_roster=bool(binding),
            shares=None,   # filled in by apply_performance() when enabled
            # Recorded but excluded from t1/t2 -- see match_binding._ringers.
            # Kept on the row, not just the aggregate count, so a specific
            # match's ringer(s) can be traced back from the digest/summary.
            ringers=sorted(binding.get("ringers", [])) if binding else [],
        ))
    out.sort(key=lambda m: m["when"])
    return out, dict(pending=pending, total_scheduled=len(matches_raw),
                     rated_on_actual_participants=used_actual, bindings=played,
                     ringer_appearances=ringer_appearances,
                     division_labels=div_by_pid)


def season_rosters(key: str, season_number: int):
    """(rosters, current_division, division_sizes) for one season.

    Shared with seeding_report.py so both read rosters the same way -- a
    second loader would be a second set of filter decisions to keep in step.
    Player keys match whatever run_weekly rated on (website player ids in CI,
    hlstatsx ids locally when the Steam bridge is present).
    """
    bridge = load_bridge()
    merges = L.load_identity_merges() if bridge is not None else {}
    seasons = {s["id"]: s["number"] for s in fetch(key, "season", "id,number")}
    season_ids = [sid for sid, num in seasons.items() if num == season_number]
    if not season_ids:
        return {}, {}, []
    sid = season_ids[0]

    divisions = {d["id"]: d["name"] for d in fetch(key, "division", "id,name,season_id")
                 if d["season_id"] == sid}
    teams = {t["id"]: t["name"] for t in fetch(key, "team", "id,name")}
    steam_by_pid = {p["player_id"]: p["steam_id64"]
                    for p in fetch(key, "player_steam", "player_id,steam_id64,status")
                    if p["status"] == "current"}
    season_teams = {t["id"]: t for t in fetch(key, "season_team", "id,season_id,team_id,division_id,status")
                    if t["season_id"] == sid}

    rosters, current = defaultdict(list), {}
    for row in fetch(key, "season_team_member", "season_team_id,player_id,left_at"):
        st = season_teams.get(row["season_team_id"])
        if not st or row.get("left_at"):
            continue
        name = teams.get(st["team_id"], f"team-{st['team_id']}")
        current[name] = divisions.get(st["division_id"])
        if bridge is None:
            rosters[name].append(row["player_id"])
            continue
        steam64 = steam_by_pid.get(row["player_id"])
        if not steam64:
            continue
        pid = bridge.get(steam64_to_hlstats(steam64))
        if pid is not None:
            rosters[name].append(merges.get(pid, pid))

    counts = Counter(d for d in current.values() if d)
    # Order divisions strongest-first; the league's own tier order is not in
    # this payload, so fall back to the conventional Gold/Silver/Bronze.
    rank = {"Gold": 0, "Silver": 1, "Bronze": 2}
    sizes = sorted(counts.items(), key=lambda kv: rank.get(kv[0], 99))
    return dict(rosters), current, sizes


def load_division_offsets():
    """division -> mu offset, from the committed `division_offsets.json`.

    Fitted by `division_fit.py` on the data server, because the offsets are
    measured on 12-mans and CI sees only official website results. Returns {}
    when the file is absent, which disables seeding for that run rather than
    failing it -- the file is committed, so absence means someone is running
    from a tree that predates it, not that the season is misconfigured.

    The LABELS are not read here: they come from build_league_matches, which
    resolves them into whichever player-id space the ladder is using.
    """
    path = HERE / "division_offsets.json"
    if not path.exists():
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    return {k: v["mu_offset"] for k, v in doc.get("divisions", {}).items()
            if v.get("mu_offset")}


def run(matches, model_factory, division_seed=None):
    """Predict each match before applying it, then update. Returns per-match
    rows and the metrics over all predictions made.

    `division_seed` is (labels, offsets) and seeds starting mu BEFORE any match
    is applied, so the prior is in place for the first prediction rather than
    arriving after the pool has already drifted.
    """
    model = model_factory()
    if division_seed:
        labels, offsets = division_seed
        model.seed_from_divisions(labels, offsets)
        print(f"division seeding ON: {len(labels)} players labelled, offsets {offsets}")
    rows, preds, ys = [], [], []
    for m in matches:
        p = model.predict(m["t1"], m["t2"])
        # The lean survives damping; the confidence does not. Scoring uses the
        # damped value (it is what we actually claim), but "did it pick the
        # right side" reads the lean, so a fully-damped 0.500 is not silently
        # counted as a pick for the away team.
        raw = model.predict_raw(m["t1"], m["t2"]) if hasattr(model, "predict_raw") else p
        evidence = model.evidence(m["t1"], m["t2"]) if hasattr(model, "evidence") else None
        rows.append(dict(match_id=m["match_id"], when=m["when"], home=m["home_team"], away=m["away_team"],
                          division=m["division"], p_home=round(p, 3), p_raw=round(raw, 3),
                          evidence=round(evidence, 2) if evidence is not None else None,
                          y=m["y"], home_score=m["home_score"], away_score=m["away_score"],
                          correct=bool((raw > 0.5) == (m["y"] == 1.0)), margin=m["margin"]))
        preds.append(p)
        ys.append(m["y"])
        model.update(m["t1"], m["t2"], m["y"], shares=m.get("shares"))
    return model, rows, (L.metrics(preds, ys) if preds else None)


def challengers(matches, holdout_n):
    """Champion vs challengers on the most recent holdout_n matches, none of
    which any variant saw while fitting. Only reports; never auto-adopts."""
    if len(matches) < holdout_n + 10:
        return []
    train, holdout = matches[:-holdout_n], matches[-holdout_n:]
    variants = {
        "champion (openskill default)": L.OpenSkill,
        "openskill beta x1.5": lambda: L.OpenSkill(beta=25 / 6 * 1.5),
        "openskill beta x2": lambda: L.OpenSkill(beta=25 / 6 * 2),
        "elo chess-anchored": L.Elo,
        "elo K=30/provisional 15": lambda: L.Elo(30, 50, 15),
    }
    results = []
    for name, factory in variants.items():
        model = factory()
        for m in train:
            model.update(m["t1"], m["t2"], m["y"])
        preds, ys = [], []
        for m in holdout:
            preds.append(model.predict(m["t1"], m["t2"]))
            ys.append(m["y"])
            model.update(m["t1"], m["t2"], m["y"])
        results.append(dict(name=name, **L.metrics(preds, ys)))
    return sorted(results, key=lambda r: r["log_loss"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--key", default=os.environ.get("NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY"))
    ap.add_argument("--holdout", type=int, default=10, help="matches held out for champion/challenger")
    ap.add_argument("--use-performance", action="store_true",
                    help="split each result between team-mates by their KTPR v2 performance "
                         "in that match, instead of crediting everyone equally. OFF by default: "
                         "the plumbing is in place but the weighting is untuned, and tuning it "
                         "against a handful of matches would fit noise. Turn it on only once a "
                         "held-out comparison says it helps.")
    ap.add_argument("--performance-strength", type=float, default=PF.DEFAULT_STRENGTH,
                    help="how hard performance tilts the split (0 = even, today's behaviour)")
    ap.add_argument("--no-division-seed", action="store_true",
                    help="do NOT seed starting mu by division. Seeding is on by default "
                         "(drew's ruling 2026-09-30) because divisions never play each "
                         "other, so an unseeded ladder orders the pools only by chance. "
                         "The prior is weak and decays as results land. NOTE the consequence: "
                         "a seeded rating is partly an echo of the division it was seeded "
                         "from, so MMR can no longer independently validate promotion and "
                         "relegation -- use this flag for that comparison.")
    args = ap.parse_args()
    if not args.key:
        raise SystemExit("No key. Pass --key or set NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY.")

    matches, counts = build_league_matches(args.key)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"{len(matches)} completed league matches with rosters "
          f"({counts['pending']} scheduled/unplayed of {counts['total_scheduled']} total)")

    counts["performance_weighted"] = 0
    if args.use_performance:
        counts["performance_weighted"] = apply_performance(
            args.key, matches, counts.get("bindings") or {}, args.performance_strength)
        print(f"performance weighting ON (strength {args.performance_strength}): "
              f"{counts['performance_weighted']} of {len(matches)} matches split by KTPR; "
              f"the rest fall back to an even split")

    if not matches:
        digest = [f"# MMR weekly digest -- {now}\n",
                  "No completed league matches with reportable results yet.",
                  f"{counts['pending']} fixtures are scheduled and awaiting results.\n",
                  "The pipeline ran clean; there is simply nothing to rate yet. "
                  "This is the expected state before the season's first results are in."]
        (HERE / "weekly_digest.md").write_text("\n".join(digest) + "\n", encoding="utf-8")
        (HERE / "weekly_summary.json").write_text(json.dumps(
            dict(generated_at=now, completed_matches=0, pending=counts["pending"],
                 has_findings=False, headline="No completed matches yet"), indent=1), encoding="utf-8")
        print("wrote weekly_digest.md (no matches yet)")
        return

    # Seeding is ON by default (drew's ruling 2026-09-30): divisions never play
    # each other, so without a prior the pools are only ordered by chance. It is
    # weak and decays -- see ladder.seed_from_divisions.
    seed = None
    if not args.no_division_seed:
        offsets = load_division_offsets()
        labels = counts.get("division_labels") or {}
        if offsets and labels:
            seed = (labels, offsets)
        else:
            print(f"division seeding SKIPPED: "
                  f"{len(offsets)} offsets, {len(labels)} labelled players")
    # Whether a run was seeded is a PUBLISHED fact, not a log line: a reader
    # comparing weeks has to be able to tell which ratings carried the prior.
    seed_state = dict(enabled=bool(seed),
                      offsets=(seed[1] if seed else {}),
                      labelled_players=len(seed[0]) if seed else 0)
    model, rows, metrics = run(matches, L.OpenSkill, division_seed=seed)
    ratings = model.ratings()
    (HERE / "ratings_current.json").write_text(json.dumps(
        {str(p): r for p, r in sorted(ratings.items(), key=lambda kv: -kv[1]["ordinal"])}, indent=1), encoding="utf-8")

    # The website-ready payload, built every run so the operator step is a
    # single command over a file rather than a job that recomputes ratings on
    # a box with no business recomputing them. Nothing here publishes it --
    # see report_service.py import-mmr.
    try:
        played = Counter(pid for m in matches for pid in m["t1"] + m["t2"])
        aliases = {row["id"]: row.get("alias") for row in fetch(args.key, "player", "id,alias")}
        payload = MMRP.build(ratings, played, aliases,
                             generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                             source_report_count=counts.get("rated_on_actual_participants", 0))
        (HERE / "mmr_openskill_payload.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"wrote mmr_openskill_payload.json ({len(payload['players'])} players "
              f"with an alias, min_matches={payload['min_matches']})")
    except RuntimeError as exc:      # publishing aid must never fail the run
        print(f"  mmr payload unavailable: {exc}")

    upsets = [r for r in rows if abs(r["p_home"] - r["y"]) > CONFIDENT_MISS]
    cand = challengers(matches, args.holdout)
    beat_champion = [c for c in cand if cand and c["name"] != "champion (openskill default)"
                     and c["log_loss"] < next(x["log_loss"] for x in cand
                                              if x["name"] == "champion (openskill default)") - 0.01]

    digest = [f"# MMR weekly digest -- {now}\n",
              f"**{len(matches)} completed league matches** rated so far; "
              f"{counts['pending']} fixtures still scheduled.\n"]
    if counts.get("ringer_appearances"):
        digest.append(
            f"{counts['ringer_appearances']} ringer appearance(s) recorded this week -- a "
            "player who played for a team other than the one they're registered to. Recorded, "
            "but excluded from every rating those matches would otherwise have moved.\n")
    digest += ["## Prediction accuracy to date\n",
              f"| Metric | Value |", "|---|---|",
              f"| Matches predicted | {metrics['n']} |",
              f"| Accuracy | {metrics['acc']:.1%} |",
              f"| Log-loss | {metrics['log_loss']:.4f} |",
              f"| Brier | {metrics['brier']:.4f} |",
              f"| Calibration error (ECE) | {metrics['ece']:.4f} |",
              "",
              "Baseline for comparison: a coin flip scores 0.693 log-loss, 0.25 Brier, 50% accuracy.",
              "",
              "**Lean** is the side the ladder favours. **Confidence** is how much of that lean it",
              "has earned: it is pulled toward 50% by how few matches back the thinner of the two",
              "rosters, so early in a season most calls read near 50% on purpose. A confident wrong",
              "call costs far more than an uncertain one, so the ladder does not claim certainty it",
              "cannot support.",
              "",
              "## Most recent results vs predictions\n",
              "| Match | Division | Lean | Confidence | Result | Side called |",
              "|---|---|---|---|---|---|"]
    for r in rows[-10:]:
        lean = r["home"] if r["p_raw"] > 0.5 else r["away"]
        conf = max(r["p_home"], 1 - r["p_home"])
        ev = "" if r["evidence"] is None else f" · {r['evidence']:.0f} match{'' if r['evidence'] == 1 else 'es'} of evidence"
        winner = r["home"] if r["y"] == 1.0 else r["away"]
        digest.append(f"| {r['home']} vs {r['away']} | {r['division']} | {lean} | {conf:.0%}{ev} | "
                      f"{winner} {r['home_score']}-{r['away_score']} | {'yes' if r['correct'] else 'NO'} |")
    if upsets:
        digest += ["", f"## Upsets worth a look ({len(upsets)})\n",
                   "Matches the model called confidently and got wrong -- confident meaning after "
                   "damping, so these are misses it actually had the evidence to avoid. Each is "
                   "either a real signal the rating is missing or a genuine surprise.\n",
                   "| Match | Lean | Confidence | Actually won | Margin |", "|---|---|---|---|---|"]
        for r in upsets[-8:]:
            lean = r["home"] if r["p_raw"] > 0.5 else r["away"]
            winner = r["home"] if r["y"] == 1.0 else r["away"]
            digest.append(f"| {r['home']} vs {r['away']} | {lean} | "
                          f"{max(r['p_home'], 1-r['p_home']):.0%} | {winner} | {r['margin']} |")
        digest += upset_dossiers(args.key, upsets[-8:], counts.get("bindings") or {}, matches)
    if cand:
        digest += ["", "## Tuning check (champion vs challengers)\n",
                   f"Each variant trained on all but the last {args.holdout} matches, then scored "
                   "on those held-out matches it never saw. Nothing is adopted automatically.\n",
                   "| Variant | Log-loss | Brier | Accuracy |", "|---|---|---|---|"]
        for c in cand:
            digest.append(f"| {c['name']} | {c['log_loss']:.4f} | {c['brier']:.4f} | {c['acc']:.1%} |")
        if beat_champion:
            digest += ["", f"**A challenger beat the champion**: {beat_champion[0]['name']} "
                           f"({beat_champion[0]['log_loss']:.4f} vs champion). Worth a human look "
                           "before adopting -- one week is a small sample."]
    (HERE / "weekly_digest.md").write_text("\n".join(digest) + "\n", encoding="utf-8")
    summary = dict(
        generated_at=now, completed_matches=len(matches), pending=counts["pending"],
        ringer_appearances=counts.get("ringer_appearances", 0),
        accuracy=metrics["acc"], log_loss=metrics["log_loss"], brier=metrics["brier"], ece=metrics["ece"],
        upsets=len(upsets), challenger_beat_champion=bool(beat_champion),
        challenger_name=beat_champion[0]["name"] if beat_champion else None,
        has_findings=bool(upsets or beat_champion),
        division_seeded=seed_state["enabled"],
        division_offsets=seed_state["offsets"],
        headline=(f"{len(matches)} matches rated, {metrics['acc']:.0%} accuracy"
                  + (f", {len(upsets)} upsets" if upsets else "")
                  + (", challenger beat champion" if beat_champion else "")),
    )
    (HERE / "weekly_summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(f"accuracy={metrics['acc']:.1%} log_loss={metrics['log_loss']:.4f} upsets={len(upsets)}")
    print("wrote weekly_digest.md, weekly_summary.json, ratings_current.json")

    # The transparency document: equations, variables and current per-map
    # values, read from the code and from momentum_params.json (refit by
    # momentum_report.py). Same publish path as the ratings payload.
    #
    # Built here, after this run's summary exists, because the document carries
    # the week-by-week accuracy history and the prior weeks come from the
    # payload the last run published (restored from `mmr-ratings` by the
    # workflow). Read the prior BEFORE writing over it.
    try:
        import methodology as METH
        prior_history = METH.load_prior_history()
        doc = METH.build(METH.load_params(),
                         generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                         source_report_count=counts.get("rated_on_actual_participants", 0),
                         summary=summary, prior_history=prior_history,
                         division_seed=seed_state)
        (HERE / "rating_methodology_payload.json").write_text(
            json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"wrote rating_methodology_payload.json ({len(doc['momentum']['maps'])} maps, "
              f"{len(doc['version_history'])} week(s) of history)")
    except (RuntimeError, OSError, KeyError) as exc:
        print(f"  methodology payload unavailable: {exc}")


if __name__ == "__main__":
    main()
