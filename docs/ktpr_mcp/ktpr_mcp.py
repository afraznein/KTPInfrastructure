"""
KTPR MCP server — exposes the KTPR calculation as tools an agent can call.

Tools:
  list_profiles()                     -> weight profiles in weights.toml
  get_weights(profile)                -> the knobs for one profile
  compute_ktpr(profile, source)       -> ranked players w/ KTPR, style, K/D, KDA
  compare_profiles(profiles, source)  -> side-by-side ranks + biggest movers
  team_impact(profile, source)        -> value-over-replacement per player (mysql only)
  clutch_report(profile, source)      -> win/loss + margin + opponent-strength + consistency splits (mysql only)
  map_report(profile, source)         -> role x map average KTPR (mysql only)
  side_report(profile, source)        -> axis vs allies KTPR split per player (mysql only)
  predict_accuracy(profile, source)   -> leave-one-out win prediction accuracy vs K/D baseline (mysql only)
  match_avg_vs_season(profile, source) -> season-total KTPR vs mean-of-per-match KTPR (mysql only)
  shrunk_ktpr(profile, source, shrink_matches) -> sample-size-shrunk KTPR toward role median
  map_adjusted_ktpr(profile, source)  -> season KTPR scored against role x map medians (mysql only)
  weight_sensitivity(profile, source, perturb) -> rank-correlation sensitivity per weight knob

Data source (the `source` arg on the compute tools):
  "mysql"  (default) -> live tournament data over SSH. Requires ssh access to
                        the stats host loaded in your ssh-agent (see README.md).
  "<file.csv>"       -> a stats CSV (see KTPR_SPEC.md for the column contract).

Run standalone:  python ktpr_mcp.py
Register:        claude mcp add ktpr -- python <abs path>/ktpr_mcp.py
                 (or drop the bundled .mcp.json into the project)
"""

from __future__ import annotations

import os
import tomllib

from mcp.server.fastmcp import FastMCP

import ktpr_engine as E

HERE = os.path.dirname(os.path.abspath(__file__))
mcp = FastMCP("ktpr")


def _load(source: str):
    """source == 'mysql' -> live tournament data; else treat as a CSV path."""
    if source == "mysql":
        import ktpr_mysql as Q  # lazy: only needed (and only imports SSH helper) for live data
        return Q.load_players_from_mysql()
    path = source if os.path.isabs(source) else os.path.join(HERE, source)
    return E.load_players_from_csv(path)


def _kda(pl):
    return (pl.kills_half + pl.assists_half) / pl.deaths_half if pl.deaths_half else pl.kills_half + pl.assists_half


def _ranked(players, profile: str) -> list[dict]:
    p = E.load_params(profile)
    vals = E.compute_ktpr(players, p)
    styles = E.classify_styles(players, p) if p.formula == "team" else [""] * len(players)
    rows = []
    for i, (pl, v) in enumerate(zip(players, vals)):
        if v is None or not pl.name:
            continue
        rows.append({
            "player": pl.name, "role": pl.role, "ktpr": round(v, 3),
            "style": styles[i], "kd": round(pl.kd_ratio, 2), "kda": round(_kda(pl), 2),
        })
    rows.sort(key=lambda r: -r["ktpr"])
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


@mcp.tool()
def list_profiles() -> list[str]:
    """List the KTPR weight profiles defined in weights.toml (old, current, artifact, new)."""
    with open(E.WEIGHTS_PATH, "rb") as f:
        cfg = tomllib.load(f)
    return list(cfg.get("profiles", {}).keys())


@mcp.tool()
def get_weights(profile: str) -> dict:
    """Return the full set of weights/knobs for a given profile."""
    with open(E.WEIGHTS_PATH, "rb") as f:
        cfg = tomllib.load(f)
    return cfg.get("profiles", {}).get(profile, {})


@mcp.tool()
def compute_ktpr(profile: str = "new", source: str = "mysql") -> list[dict]:
    """
    Compute KTPR for every player under one profile, ranked high to low.
    Returns [{rank, player, role, ktpr, style, kd, kda}].
    profile: old | current | artifact | new (default 'new' = the team formula).
    source:  'mysql' (live tournament data) or a CSV path.
    """
    return _ranked(_load(source), profile)


@mcp.tool()
def compare_profiles(profiles: list[str] | None = None, source: str = "mysql") -> dict:
    """
    Compare several profiles on the same players: per-player KTPR + rank under
    each, plus the biggest rank movers between the first two profiles listed.
    """
    profiles = profiles or ["old", "current", "new"]
    players = _load(source)

    scores = {prof: E.compute_ktpr(players, E.load_params(prof)) for prof in profiles}
    ranks: dict[str, dict[str, int]] = {}
    for prof, vals in scores.items():
        ordered = sorted([(pl.name, v) for pl, v in zip(players, vals) if v is not None],
                         key=lambda t: t[1], reverse=True)
        ranks[prof] = {name: i for i, (name, _) in enumerate(ordered, 1)}

    table = []
    for i, pl in enumerate(players):
        if not pl.name:
            continue
        row = {"player": pl.name, "role": pl.role}
        for prof in profiles:
            v = scores[prof][i]
            row[f"{prof}_ktpr"] = round(v, 3) if v is not None else None
            row[f"{prof}_rank"] = ranks[prof].get(pl.name)
        table.append(row)

    movers = []
    if len(profiles) >= 2:
        a, b = profiles[0], profiles[1]
        for r in table:
            ra, rb = r.get(f"{a}_rank"), r.get(f"{b}_rank")
            if ra and rb:
                movers.append({"player": r["player"], "from": ra, "to": rb, "delta": ra - rb})
        movers.sort(key=lambda m: abs(m["delta"]), reverse=True)

    return {"profiles": profiles, "players": table, "biggest_movers": movers[:10]}


@mcp.tool()
def team_impact(profile: str = "new", source: str = "mysql") -> list[dict]:
    """
    Value-over-replacement per player: the swing to their fixed tournament
    team's average KTPR if they were subbed out for a role-typical replacement
    (median KTPR among other regular players sharing their role). Requires
    'mysql' source (team rosters are inferred from match co-occurrence; a plain
    CSV has no team data). Returns rows sorted by value_over_replacement desc:
    [{player, team, role, ktpr, replacement_ktpr, value_over_replacement,
      team_avg_ktpr, team_size, team_avg_delta_if_subbed}].
    """
    players = _load(source)
    rows = E.compute_sub_impact(players, E.load_params(profile))
    rows.sort(key=lambda r: -r["value_over_replacement"])
    return rows


@mcp.tool()
def clutch_report(profile: str = "new", source: str = "mysql") -> list[dict]:
    """
    Per-player match-context splits: win/loss, margin of victory, opponent
    strength, and consistency — each match scored against season-wide role
    medians so values stay comparable. Requires 'mysql' source. Only
    meaningful for profile='new' (formula='team'); other profiles aren't
    shaped for single-match scoring. Returns rows sorted by clutch_diff desc:
    [{player, role, team,
      matches_won, matches_lost, avg_ktpr_win, avg_ktpr_loss, clutch_diff,
      avg_ktpr_close, avg_ktpr_blowout, close_vs_blowout_diff,
      avg_ktpr_vs_strong, avg_ktpr_vs_weak, opponent_adjusted_diff,
      ktpr_consistency}].
    clutch_diff > 0: plays above baseline in wins. close_vs_blowout_diff > 0:
    performs better in close matches (median-split on |margin|) than blowouts.
    opponent_adjusted_diff > 0: steps up against opponents whose season KTPR
    is above the tournament median. ktpr_consistency: sample stdev of
    per-match KTPR across all matches (lower = steadier performer).
    """
    if source != "mysql":
        raise ValueError("clutch_report requires source='mysql' (per-match + win/loss data)")
    import ktpr_mysql as Q
    season_players = Q.load_players_from_mysql()
    match_rows = Q.load_match_player_stats()
    rows = E.compute_match_splits(season_players, match_rows, E.load_params(profile))
    rows.sort(key=lambda r: (r["clutch_diff"] is None, -(r["clutch_diff"] or 0)))
    return rows


@mcp.tool()
def map_report(profile: str = "new", source: str = "mysql", min_matches: int = 3) -> list[dict]:
    """
    Role x map average per-match KTPR (season-baseline-normalized). Grouped by
    role rather than player to avoid sparsity (most players only played a
    handful of matches on any one map). Cells with fewer than `min_matches`
    matches are dropped as too noisy. Requires 'mysql' source.
    Returns [{role, map, matches, avg_ktpr}], sorted by role then avg_ktpr desc.
    """
    if source != "mysql":
        raise ValueError("map_report requires source='mysql' (per-match + map data)")
    import ktpr_mysql as Q
    season_players = Q.load_players_from_mysql()
    match_rows = Q.load_match_player_stats()
    rows = E.compute_map_splits(season_players, match_rows, E.load_params(profile), min_matches)
    rows.sort(key=lambda r: (r["role"], -r["avg_ktpr"]))
    return rows


@mcp.tool()
def side_report(profile: str = "new", source: str = "mysql") -> list[dict]:
    """
    Per-player average per-half KTPR split by side (axis vs allies), scored
    against season-wide role medians. Sides swap at halftime within a match,
    so this is computed at per-half granularity (not per-match). Requires
    'mysql' source. Returns rows sorted by |side_diff| desc:
    [{player, role, team, halves_axis, halves_allies, avg_ktpr_axis,
      avg_ktpr_allies, side_diff}]. side_diff = axis - allies; a large
    magnitude flags a player who performs very differently by side.
    """
    if source != "mysql":
        raise ValueError("side_report requires source='mysql' (per-half + side data)")
    import ktpr_mysql as Q
    season_players = Q.load_players_from_mysql()
    half_rows = Q.load_half_player_stats()
    rows = E.compute_side_splits(season_players, half_rows, E.load_params(profile))
    rows.sort(key=lambda r: -abs(r["side_diff"] or 0))
    return rows


@mcp.tool()
def predict_accuracy(profile: str = "new", source: str = "mysql") -> dict:
    """
    Does KTPR actually predict who wins? Leave-one-out validation: for every
    resolved match, predicts the winner as the team with the higher average
    KTPR — computed from each player's season totals with THAT match's own
    contribution subtracted out first, so a match can't help predict itself.
    Also scores two variants for free: team strength by MEDIAN (instead of
    mean, more robust to one hot/cold performer) and MAP-ADJUSTED (each
    match scored against its own role x map medians instead of season-wide
    role medians). Compares all three against a naive raw-K/D-ratio baseline
    on the same matches, to see whether KTPR's extra machinery earns its
    complexity over "who has the better K/D". Requires 'mysql' source; scoped
    to profile='new' (formula='team'). Returns {n_matches, accuracy_ktpr,
    accuracy_ktpr_median, accuracy_map_adjusted, accuracy_kd_baseline,
    matches: [{match_id, team_a, team_b, actual_winner, ktpr_predicted,
    ktpr_correct, ktpr_median_predicted, ktpr_median_correct, kd_predicted,
    kd_correct, map_adj_predicted, map_adj_correct}]}.
    """
    if source != "mysql":
        raise ValueError("predict_accuracy requires source='mysql' (per-match + win/loss data)")
    import ktpr_mysql as Q
    raw_rows = Q.load_raw_match_stats()
    match_results = Q._match_results()
    match_rows = Q.load_match_player_stats()
    map_names = Q._match_maps()
    return E.compute_prediction_accuracy(raw_rows, match_results, E.load_params(profile),
                                          match_rows=match_rows, map_names=map_names)


@mcp.tool()
def match_avg_vs_season(profile: str = "new", source: str = "mysql") -> list[dict]:
    """
    Compares the standard season-TOTAL-based KTPR against an alternative: the
    mean/median of each player's PER-MATCH KTPR. Season-total KTPR is a
    sum-of-sums, so a couple of heavy matches can dominate it; match-averaging
    weights every match equally. Requires 'mysql' source. Returns rows sorted
    by |delta_avg_vs_season| desc: [{player, matches, season_total_ktpr,
    match_avg_ktpr, match_median_ktpr, delta_avg_vs_season}] — a large delta
    flags a player whose rating shape depends heavily on which aggregation you
    trust.
    """
    if source != "mysql":
        raise ValueError("match_avg_vs_season requires source='mysql' (per-match data)")
    import ktpr_mysql as Q
    season_players = Q.load_players_from_mysql()
    match_rows = Q.load_match_player_stats()
    rows = E.compute_match_avg_ktpr(season_players, match_rows, E.load_params(profile))
    rows.sort(key=lambda r: -abs(r["delta_avg_vs_season"] or 0))
    return rows


@mcp.tool()
def shrunk_ktpr(profile: str = "new", source: str = "mysql", shrink_matches: float = 3.0) -> list[dict]:
    """
    Sample-size-aware KTPR: shrinks each player's rating toward their role's
    median, weighted by how many matches they played (shrink_matches = how
    many matches' worth of role-average prior gets blended in). A player with
    3 matches and one with 11 matches read as equally confident under plain
    KTPR; this pulls the low-sample player toward a sane baseline instead.
    Returns rows sorted by |shrunk_ktpr - raw_ktpr| desc: [{player, role,
    matches, raw_ktpr, role_prior, shrunk_ktpr, shrink_weight}].
    """
    players = _load(source)
    rows = E.compute_shrunk_ktpr(players, E.load_params(profile), shrink_matches)
    rows.sort(key=lambda r: -abs(r["shrunk_ktpr"] - r["raw_ktpr"]))
    return rows


@mcp.tool()
def map_adjusted_ktpr(profile: str = "new", source: str = "mysql") -> list[dict]:
    """
    Alternative season KTPR that bakes map context INTO the score (unlike
    map_report, which reports it as a separate cut): each match is scored
    against its own role x map medians instead of the season-wide role
    median. A player whose matches landed more on maps favorable to their
    role sees this pulled down relative to the standard season KTPR, and vice
    versa. Requires 'mysql' source. Returns rows sorted by |delta| desc:
    [{player, matches, season_ktpr, map_adjusted_ktpr, delta}].
    """
    if source != "mysql":
        raise ValueError("map_adjusted_ktpr requires source='mysql' (per-match + map data)")
    import ktpr_mysql as Q
    season_players = Q.load_players_from_mysql()
    match_rows = Q.load_match_player_stats()
    rows = E.compute_map_adjusted_ktpr(season_players, match_rows, E.load_params(profile))
    rows.sort(key=lambda r: -abs(r["delta"] or 0))
    return rows


@mcp.tool()
def weight_sensitivity(profile: str = "new", source: str = "mysql", perturb: float = 0.10) -> list[dict]:
    """
    For each core weight in the 'team' formula, perturbs it +/-`perturb`
    (10% by default) and measures how much the player RANKING moves: Spearman
    rank correlation vs. the unperturbed ranking, and how many players' ranks
    moved >= 3 places. Low correlation / high movement = the ranking is
    sensitive to that (somewhat arbitrary, hand-tuned) knob. Returns rows
    sorted most-sensitive first: [{knob, base_value, perturb_pct,
    avg_spearman_rho, avg_players_moved_3plus}].
    """
    players = _load(source)
    return E.compute_weight_sensitivity(players, E.load_params(profile), perturb)


if __name__ == "__main__":
    mcp.run()