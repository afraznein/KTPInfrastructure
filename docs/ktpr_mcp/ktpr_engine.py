"""
KTPR engine — pure stdlib, no external deps.

This is the *source of truth* for the KTPR calculation, replacing the 40-line
Excel formula. It reproduces both the OLD and CURRENT (newer) Excel formulas
exactly, and is the foundation for designing the redesigned "new" KTPR.

Column contract (matches Book1.csv, which mirrors the Excel sheet):
    A Players       -> name
    C KTPRn         -> the sheet's KTPR output (used only to regression-test us)
    D Matches       -> participation (drives the "regular player" filter)
    I K/D Ratio     -> capped skill baseline (min 1.1)
    K Kills/Half    -> kill production (normalized to median of regulars)
    M Deaths/Half   -> death penalty (vs median of regulars)
    O Flags/Half    -> objective bonus (vs median of regulars)

The KTPR skeleton (shared by old & current):
    KTPR = SCALE
         * [ min(K/D, 1.1) * (Kills/Half / median_regulars(Kills/Half)) ]   # core
         * ( 1 + flag_bonus )                                               # objective, capped
         * ( 1 - death_penalty )                                            # deaths, capped
"""

from __future__ import annotations

import csv
import math
import os
import tomllib
from dataclasses import dataclass, field, fields, replace

WEIGHTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "weights.toml")


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class Player:
    name: str
    matches: float        # D
    kd_ratio: float       # I  (column I = total kills / total deaths, used by old/current)
    kills_half: float     # K
    deaths_half: float    # M
    flags_half: float     # O
    ktprn_sheet: float | None = None  # C, only for verification
    # --- new stats (0 until MySQL data arrives; gated by use_* flags) ---
    assists_half: float = 0.0
    damage_half: float = 0.0
    breaks_half: float = 0.0
    role: str = "?"       # Rifle | Sniper | Heavy | SMG (for within-class normalization)
    team: str = "?"       # fixed tournament roster, inferred from match co-occurrence
    match_id: str | None = None       # set only on per-match rows (see load_match_player_stats)
    won: bool | None = None           # set only on per-match rows: did pl.team win this match?
    opponent_team: str | None = None  # set only on per-match rows: the other team that match
    margin_ratio: float | None = None  # (my_score - opp_score) / (my_score + opp_score), -1..1
    map_name: str | None = None       # set only on per-match rows
    side: str | None = None           # set only on per-half rows (see load_half_player_stats): axis|allies


@dataclass
class RawMatchStats:
    """One (player, match) row of RAW, undivided counts — not a per-half rate
    like Player. Lets season totals minus one match be computed by plain
    subtraction (see ktpr_mysql.load_raw_match_stats / compute_prediction_accuracy)."""
    steam_id: str
    name: str
    match_id: str
    role: str
    team: str
    kills: float
    deaths: float
    assists: float
    damage: float
    flags: float
    breaks: float
    halves: int        # HLstatsX halves for this match (the primary participation basis)
    hud_halves: int    # HUD's own halves count for this match (assists/damage/breaks divisor)


# ---------------------------------------------------------------------------
# Formula parameters — the knobs that differ between old and current
# ---------------------------------------------------------------------------

@dataclass
class KtprParams:
    # --- core knobs (all profiles) ---
    scale: float = 0.75              # final multiplier
    flag_w_regular: float = 0.30     # relative-flag weight for regular players
    flag_w_nonregular: float = 0.20  # relative-flag weight for non-regulars
    flag_cap: float = 0.35           # cap on total flag bonus
    death_w: float = 0.20            # death penalty weight
    death_cap: float = 0.15          # death penalty cap
    part_floor: float = 0.0          # floor on the participation threshold
    guard_zero_median: bool = False  # guard median==0 -> 1
    kd_cap: float = 1.1              # cap on K/D baseline
    flag_log_base: float = 25.0      # LOG(O+1)/LOG(base)
    # --- new-dimension knobs (only used by redesigned "new" profile) ---
    assist_weight: float = 0.30
    damage_w: float = 0.15
    damage_cap: float = 0.15
    break_w: float = 0.20
    break_cap: float = 0.15
    use_assists: bool = False
    use_damage: bool = False
    use_breaks: bool = False
    # --- formula selector + additive-mode knobs (artifact-style) ---
    formula: str = "excel"           # "excel" | "additive" | "team"
    norm: str = "median"             # "median" or "mean" for the additive baseline
    additive_regulars_only: bool = False
    add_kd: float = 1.0              # additive term weights
    add_kills: float = 1.0
    add_flags: float = 0.25
    add_assists: float = 0.0
    add_damage: float = 0.0
    add_breaks: float = 0.0
    # --- "team" formula knobs (sum-of-contributions, team-player oriented) ---
    kill_exp: float = 0.6            # <1 = diminishing returns on kills (normalizes fraggers)
    tw_kill: float = 1.0             # contribution weights
    tw_kd: float = 0.9               # K/D efficiency term (rewards fraggers who don't die)
    tw_assist: float = 0.7
    tw_damage: float = 0.6
    tw_flag: float = 0.7
    tw_break: float = 0.8
    dmg_interaction: float = 0.6     # how much low kills amplify the damage term
    assist_interaction: float = 0.6  # how much low kills amplify the assist term
    dmg_scale_min: float = 0.3       # clamp on the low-kill amplifier (high fraggers)
    dmg_scale_max: float = 1.8       # clamp on the low-kill amplifier (low fraggers)
    ratio_cap: float = 2.5           # cap each normalized ratio (tames noisy/rare stats)
    ratio_floor: float = 0.55        # floor each ratio: weakness in one stat can't drag too far
    break_smooth_k: float = 0.0      # Laplace-style smoothing added to both sides of the breaks
                                      # ratio: (x+k)/(median+k). Breaks have a near-zero median, so
                                      # small absolute counts otherwise produce extreme ratios; k
                                      # tempers that without disabling the stat. 0 = no smoothing.
    team_death_up_cap: float = 0.10  # max bonus for below-median deaths
    death_kill_relief: float = 0.0   # softens the death penalty for above-median killers: an
                                      # aggressive player trading deaths for kills is pushing, not
                                      # failing. adj_rx = rx / (1 + relief*max(0, rk-1)); only ever
                                      # reduces the penalty (never increases it for low-kill players).
                                      # 0 = no relief (raw death rate penalized regardless of kills).
    class_normalize: bool = False    # normalize each player vs the median of their own role
    class_min_size: int = 4          # min regulars in a role to use its own baseline
    role_weights: dict = field(default_factory=dict)  # per-role final multiplier (e.g. Heavy: 1.05)
    team_placements: dict = field(default_factory=dict)   # team -> final tournament placement (1=first)
    team_placement_weight: float = 0.0                    # max multiplicative boost for 1st place;
                                                            # 0 = off. Linear taper to +0% at last place.

    @classmethod
    def from_dict(cls, d: dict) -> "KtprParams":
        known = {f.name for f in fields(cls)}
        unknown = set(d) - known
        if unknown:
            raise KeyError(f"unknown weight keys in weights.toml: {sorted(unknown)}")
        return cls(**{k: v for k, v in d.items() if k in known})


def load_params(profile: str, path: str = WEIGHTS_PATH) -> KtprParams:
    """Load a named weight profile (old / current / new / ...) from weights.toml."""
    with open(path, "rb") as f:
        cfg = tomllib.load(f)
    profiles = cfg.get("profiles", {})
    if profile not in profiles:
        raise KeyError(f"profile '{profile}' not in {path}; have {list(profiles)}")
    return KtprParams.from_dict(profiles[profile])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2.0


def _safe_median(values: list[float], guard: bool) -> float:
    m = _median(values)
    if guard and m == 0:
        return 1.0
    return m


def _participation_threshold(players: list[Player], p: KtprParams) -> float:
    """MAX(part_floor, MAX(D:D) * 0.66)."""
    max_d = max((pl.matches for pl in players), default=0.0)
    return max(p.part_floor, max_d * 0.66)


# ---------------------------------------------------------------------------
# Core calculation
# ---------------------------------------------------------------------------

def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _stdev(values: list[float]) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    m = _mean(values)
    return (sum((x - m) ** 2 for x in values) / (n - 1)) ** 0.5


def _team_baselines(players: list["Player"], p: KtprParams):
    """Return baseline_for(player) -> median-set dict, matching compute_team's
    normalization (per-role medians when class_normalize, else global)."""
    threshold = _participation_threshold(players, p)
    named = [pl for pl in players if pl.name]
    regs = [pl for pl in named if pl.matches >= threshold] or named

    def med(vals: list[float]) -> float:
        m = _median(vals)
        return m if m else 1.0

    def bset(group: list["Player"]) -> dict:
        return {
            "K": med([pl.kills_half for pl in group]),
            "A": med([pl.assists_half for pl in group]),
            "D": med([pl.damage_half for pl in group]),
            "F": med([pl.flags_half for pl in group]),
            "B": med([pl.breaks_half for pl in group]),
            "X": med([pl.deaths_half for pl in group]),
            "KD": med([pl.kd_ratio for pl in group]),
        }

    global_med = bset(regs)
    role_med: dict[str, dict] = {}
    if p.class_normalize:
        by_role: dict[str, list] = {}
        for pl in regs:
            by_role.setdefault(pl.role, []).append(pl)
        for role, members in by_role.items():
            if len(members) >= p.class_min_size:
                role_med[role] = bset(members)

    def baseline_for(pl: "Player") -> dict:
        return role_med.get(pl.role, global_med) if p.class_normalize else global_med

    return baseline_for


# quantifier tiers by KTPR percentile (top -> bottom). Military/DoD flavor.
STYLE_TIERS = [(0.15, "Ace"), (0.40, "Veteran"), (0.70, "Regular"), (1.01, "Recruit")]


def _archetype(r_kd, r_k, r_a, r_d, r_f, r_b, hi=1.12, lead=0.12):
    """Playstyle by profile SHAPE (which axis a player leans on), independent of
    overall quality (the tier captures that). Axes: fragging / objective / support.
    Objective leans on flags (breaks have a tiny, noisy median), so flags dominate."""
    frag = 0.5 * r_kd + 0.5 * r_k
    obj = 0.7 * r_f + 0.3 * r_b
    sup = 0.6 * r_a + 0.4 * r_d
    axes = {"Fragger": frag, "Flagger": obj, "Support": sup}
    if sum(v >= hi for v in axes.values()) >= 2:
        return "All-rounder"
    (top, tv), (_, sv) = sorted(axes.items(), key=lambda kv: -kv[1])[:2]
    if tv - sv < lead:                       # flat profile, no clear lean
        return "Generalist"
    if top == "Fragger":
        return "Sharpshooter" if r_kd >= r_k + 0.30 else "Fragger"
    return top                               # "Flagger" or "Support"


def classify_styles(players: list["Player"], p: KtprParams) -> list[str]:
    """Return a '<tier> <archetype>' style label per player (e.g. 'Elite Fragger').
    Tier = overall KTPR percentile (role-aware, matches the score). Archetype =
    profile shape vs the GLOBAL median (absolute playstyle, not role-relative)."""
    vals = compute_ktpr(players, p)
    ranked = sorted([i for i, v in enumerate(vals) if v is not None], key=lambda i: -vals[i])
    n = len(ranked) or 1
    tier_of = {i: next(name for cut, name in STYLE_TIERS if pos / n < cut)
               for pos, i in enumerate(ranked)}

    # global baseline (over regulars) for the archetype axes
    threshold = _participation_threshold(players, p)
    named = [pl for pl in players if pl.name]
    regs = [pl for pl in named if pl.matches >= threshold] or named

    def med(vs):
        m = _median(vs)
        return m if m else 1.0
    g = {"K": med([x.kills_half for x in regs]), "A": med([x.assists_half for x in regs]),
         "D": med([x.damage_half for x in regs]), "F": med([x.flags_half for x in regs]),
         "B": med([x.breaks_half for x in regs]), "KD": med([x.kd_ratio for x in regs])}

    styles: list[str] = []
    for i, pl in enumerate(players):
        if not pl.name or vals[i] is None:
            styles.append("")
            continue
        arch = _archetype(pl.kd_ratio / g["KD"], pl.kills_half / g["K"],
                          pl.assists_half / g["A"], pl.damage_half / g["D"],
                          pl.flags_half / g["F"], pl.breaks_half / g["B"])
        styles.append(f"{tier_of[i]} {arch}")
    return styles


def compute_ktpr(players: list[Player], p: KtprParams) -> list[float | None]:
    """Dispatch on formula type: 'excel' (mult.), 'additive' (artifact), 'team'."""
    if p.formula == "additive":
        return compute_additive(players, p)
    if p.formula == "team":
        return compute_team(players, p)
    return compute_excel(players, p)


def compute_team(players: list[Player], p: KtprParams, baseline_for=None) -> list[float | None]:
    """
    Team-player-oriented KTPR: a weighted average of per-dimension contributions,
    each normalized to the median of regulars (1.0 = an average LAN player).

      kill_term  = (kills/half / median) ** kill_exp          # concave -> normalize fraggers
      dmg_term   = damage_ratio * amplifier(kills)            # bigger when kills are low
      score      = Σ w_i * contribution_i  /  Σ w_i
      KTPR       = scale * score * death_adjust

    Because contributions ADD, a low-kill/high-support player is lifted by the
    assist/damage/flag/break terms instead of being crushed by low kills. A
    one-dimensional fragger is pulled toward the middle (normalized, not punished)
    because they are below average on the other four contributions.

    baseline_for: optional precomputed closure from _team_baselines, e.g. to score
    single-match rows against season-wide medians instead of re-deriving noisy
    medians from the match itself (see load_match_player_stats / clutch report).
    """
    if baseline_for is None:
        baseline_for = _team_baselines(players, p)

    def R(x: float, m: float, k: float = 0.0) -> float:
        return min(max((x + k) / (m + k), p.ratio_floor), p.ratio_cap)

    W = (p.tw_kill + p.tw_kd + p.tw_assist + p.tw_damage + p.tw_flag + p.tw_break) or 1.0
    n_teams = len(p.team_placements)

    out: list[float | None] = []
    for pl in players:
        if not pl.name:
            out.append(None)
            continue
        mb = baseline_for(pl)
        rk = R(pl.kills_half, mb["K"])
        ra = R(pl.assists_half, mb["A"])
        rd = R(pl.damage_half, mb["D"])
        rf = R(pl.flags_half, mb["F"])
        # breaks get an optional smoothing constant: their median is near zero, so a
        # plain ratio turns small absolute counts into extreme swings (see KTPR_KNOBS.md).
        rb = R(pl.breaks_half, mb["B"], p.break_smooth_k)
        rx = pl.deaths_half / mb["X"]
        mKD = mb["KD"]

        rkd = R(pl.kd_ratio, mKD)
        kill_term = rk ** p.kill_exp
        # low-kill amplifiers: reward damage & assists more when kills are low
        # (contribution the kills didn't capture). >1 for low fraggers, <1 for high.
        amp_d = min(max(1 + p.dmg_interaction * (1 - rk), p.dmg_scale_min), p.dmg_scale_max)
        amp_a = min(max(1 + p.assist_interaction * (1 - rk), p.dmg_scale_min), p.dmg_scale_max)
        dmg_term = rd * amp_d
        assist_term = ra * amp_a

        score = (p.tw_kill * kill_term
                 + p.tw_kd * rkd
                 + p.tw_assist * assist_term
                 + p.tw_damage * dmg_term
                 + p.tw_flag * rf
                 + p.tw_break * rb) / W

        # gentle death normalization: penalty (capped) above median, small bonus below.
        # death_kill_relief softens the death RATE used here for above-median killers
        # (rk>1) -- dying while also fragging above the pack is aggression, not failure.
        # Below-median killers (rk<=1) are unaffected, so this never adds punishment.
        adj_rx = rx / (1 + max(0.0, p.death_kill_relief * (rk - 1)))
        death_adj = 1 - min(max(p.death_w * (adj_rx - 1), -p.team_death_up_cap), p.death_cap)

        role_w = p.role_weights.get(pl.role, 1.0) if p.role_weights else 1.0

        # final-standing boost: 1st place gets the full team_placement_weight bonus,
        # last place gets none, linear in between. Off (1.0) for an unresolved team
        # or when team_placement_weight is 0 (default).
        team_boost = 1.0
        if p.team_placement_weight and n_teams > 1:
            place = p.team_placements.get(pl.team)
            if place:
                team_boost = 1 + p.team_placement_weight * (n_teams - place) / (n_teams - 1)

        out.append(p.scale * score * death_adj * role_w * team_boost)
    return out


# ---------------------------------------------------------------------------
# Team-value analyses (idea 1: sub-out impact; idea 2: win/loss split)
# ---------------------------------------------------------------------------

def compute_sub_impact(players: list[Player], p: KtprParams) -> list[dict]:
    """
    For each player, the swing to their fixed tournament team's average KTPR if
    they were subbed out for a role-typical replacement (median KTPR among
    other *regular* players sharing their role; falls back to the global
    regular pool if the role has too few other regulars). Requires `pl.team`
    (fixed roster, see ktpr_mysql._infer_teams) and `pl.role`.
    """
    vals = compute_ktpr(players, p)
    threshold = _participation_threshold(players, p)

    regulars: list[tuple[Player, float]] = [
        (pl, v) for pl, v in zip(players, vals)
        if pl.name and v is not None and pl.matches >= threshold
    ]
    by_role: dict[str, list[tuple[Player, float]]] = {}
    for pl, v in regulars:
        by_role.setdefault(pl.role, []).append((pl, v))

    def replacement_for(pl: Player) -> float:
        pool = [v for (other, v) in by_role.get(pl.role, []) if other is not pl]
        if len(pool) < 2:   # too few same-role regulars to trust a role-specific median
            pool = [v for (other, v) in regulars if other is not pl]
        return _median(pool) if pool else 0.0

    by_team: dict[str, list[float]] = {}
    for pl, v in zip(players, vals):
        if pl.name and v is not None and pl.team and pl.team != "?":
            by_team.setdefault(pl.team, []).append(v)
    team_avg = {team: _mean(vs) for team, vs in by_team.items()}
    team_size = {team: len(vs) for team, vs in by_team.items()}

    out: list[dict] = []
    for pl, v in zip(players, vals):
        if not pl.name or v is None:
            continue
        repl = replacement_for(pl)
        size = team_size.get(pl.team, 0)
        out.append({
            "player": pl.name, "team": pl.team, "role": pl.role,
            "ktpr": round(v, 3), "replacement_ktpr": round(repl, 3),
            "value_over_replacement": round(v - repl, 3),
            "team_avg_ktpr": round(team_avg[pl.team], 3) if pl.team in team_avg else None,
            "team_size": size,
            "team_avg_delta_if_subbed": round((repl - v) / size, 4) if size else None,
        })
    return out


def compute_match_splits(season_players: list[Player], match_rows: list[Player],
                          p: KtprParams) -> list[dict]:
    """
    Per-player match-context splits, each match scored against SEASON-wide role
    medians (not the single match, which would be too noisy a baseline) so
    values stay comparable across matches. Requires `match_rows` from
    ktpr_mysql.load_match_player_stats (`.won`, `.margin_ratio`,
    `.opponent_team` set) and assumes formula='team'.

      win/loss        — avg_ktpr_win vs avg_ktpr_loss (clutch_diff = win - loss)
      margin           — matches split at the median |margin_ratio| into close
                          vs. blowout (close_vs_blowout_diff = close - blowout;
                          positive = performs better under pressure)
      opponent strength — matches split at the median SEASON team KTPR of the
                          opponent faced that match (opponent_adjusted_diff =
                          vs_strong - vs_weak; positive = steps up vs tough teams)
      consistency       — sample stdev of per-match KTPR across ALL matches
                          (lower = more consistent performer)
    """
    baseline_for = _team_baselines(season_players, p)
    match_vals = compute_team(match_rows, p, baseline_for=baseline_for)

    season_vals = compute_ktpr(season_players, p)
    team_ktpr: dict[str, list[float]] = {}
    for pl, v in zip(season_players, season_vals):
        if pl.name and v is not None and pl.team and pl.team != "?":
            team_ktpr.setdefault(pl.team, []).append(v)
    team_strength = {t: _mean(vs) for t, vs in team_ktpr.items()}
    strength_median = _median(list(team_strength.values()))

    margins = [abs(pl.margin_ratio) for pl in match_rows if pl.margin_ratio is not None]
    margin_median = _median(margins)

    by_player: dict[str, dict] = {}
    for pl, v in zip(match_rows, match_vals):
        if not pl.name or v is None or pl.won is None:
            continue
        d = by_player.setdefault(pl.name, {
            "player": pl.name, "role": pl.role, "team": pl.team,
            "win": [], "loss": [], "close": [], "blowout": [],
            "vs_strong": [], "vs_weak": [], "all": [],
        })
        d["all"].append(v)
        (d["win"] if pl.won else d["loss"]).append(v)
        if pl.margin_ratio is not None:
            (d["close"] if abs(pl.margin_ratio) <= margin_median else d["blowout"]).append(v)
        opp_strength = team_strength.get(pl.opponent_team)
        if opp_strength is not None:
            (d["vs_strong"] if opp_strength >= strength_median else d["vs_weak"]).append(v)

    def avg(vs: list[float]) -> float | None:
        return round(_mean(vs), 3) if vs else None

    def diff(a: float | None, b: float | None) -> float | None:
        return round(a - b, 3) if a is not None and b is not None else None

    out: list[dict] = []
    for d in by_player.values():
        win, loss = d.pop("win"), d.pop("loss")
        close, blowout = d.pop("close"), d.pop("blowout")
        vs_strong, vs_weak = d.pop("vs_strong"), d.pop("vs_weak")
        allv = d.pop("all")

        d["matches_won"] = len(win)
        d["matches_lost"] = len(loss)
        d["avg_ktpr_win"] = avg(win)
        d["avg_ktpr_loss"] = avg(loss)
        d["clutch_diff"] = diff(d["avg_ktpr_win"], d["avg_ktpr_loss"])

        d["avg_ktpr_close"] = avg(close)
        d["avg_ktpr_blowout"] = avg(blowout)
        d["close_vs_blowout_diff"] = diff(d["avg_ktpr_close"], d["avg_ktpr_blowout"])

        d["avg_ktpr_vs_strong"] = avg(vs_strong)
        d["avg_ktpr_vs_weak"] = avg(vs_weak)
        d["opponent_adjusted_diff"] = diff(d["avg_ktpr_vs_strong"], d["avg_ktpr_vs_weak"])

        d["ktpr_consistency"] = round(_stdev(allv), 3) if len(allv) >= 2 else None
        out.append(d)
    return out


def compute_map_splits(season_players: list[Player], match_rows: list[Player],
                        p: KtprParams, min_matches: int = 3) -> list[dict]:
    """
    Role x map average per-match KTPR (season-baseline-normalized). Grouped by
    ROLE rather than player to avoid sparsity — most individual players only
    played a handful of matches on any single map. Cells below `min_matches`
    are dropped as too noisy to report.
    """
    baseline_for = _team_baselines(season_players, p)
    match_vals = compute_team(match_rows, p, baseline_for=baseline_for)

    by_role_map: dict[tuple[str, str], list[float]] = {}
    for pl, v in zip(match_rows, match_vals):
        if not pl.name or v is None or not pl.map_name:
            continue
        by_role_map.setdefault((pl.role, pl.map_name), []).append(v)

    out = [
        {"role": role, "map": map_name, "matches": len(vs), "avg_ktpr": round(_mean(vs), 3)}
        for (role, map_name), vs in by_role_map.items() if len(vs) >= min_matches
    ]
    return out


def compute_side_splits(season_players: list[Player], half_rows: list[Player],
                         p: KtprParams) -> list[dict]:
    """
    Per-player average per-half KTPR split by which side (axis/allies) they
    occupied that half, scored against season-wide role medians. Requires
    `half_rows` from ktpr_mysql.load_half_player_stats (`.side` set).
    """
    baseline_for = _team_baselines(season_players, p)
    half_vals = compute_team(half_rows, p, baseline_for=baseline_for)

    by_player: dict[str, dict] = {}
    for pl, v in zip(half_rows, half_vals):
        if not pl.name or v is None or pl.side not in ("axis", "allies"):
            continue
        d = by_player.setdefault(pl.name, {
            "player": pl.name, "role": pl.role, "team": pl.team, "axis": [], "allies": [],
        })
        d[pl.side].append(v)

    out: list[dict] = []
    for d in by_player.values():
        axis, allies = d.pop("axis"), d.pop("allies")
        d["halves_axis"] = len(axis)
        d["halves_allies"] = len(allies)
        d["avg_ktpr_axis"] = round(_mean(axis), 3) if axis else None
        d["avg_ktpr_allies"] = round(_mean(allies), 3) if allies else None
        d["side_diff"] = (round(d["avg_ktpr_axis"] - d["avg_ktpr_allies"], 3)
                           if axis and allies else None)
        out.append(d)
    return out


# ---------------------------------------------------------------------------
# Formula validation: does KTPR itself hold up, not just what it says
# ---------------------------------------------------------------------------

def _season_totals_by_player(raw_rows: list["RawMatchStats"]) -> dict[str, dict]:
    """steam_id -> summed raw totals across every match (+ name/role/team)."""
    totals: dict[str, dict] = {}
    for r in raw_rows:
        t = totals.setdefault(r.steam_id, {
            "name": r.name, "role": r.role, "team": r.team,
            "kills": 0.0, "deaths": 0.0, "assists": 0.0, "damage": 0.0,
            "flags": 0.0, "breaks": 0.0, "halves": 0, "hud_halves": 0, "matches": 0,
        })
        t["kills"] += r.kills; t["deaths"] += r.deaths
        t["assists"] += r.assists; t["damage"] += r.damage
        t["flags"] += r.flags; t["breaks"] += r.breaks
        t["halves"] += r.halves; t["hud_halves"] += r.hud_halves
        t["matches"] += 1
    return totals


def _player_snapshot(steam_id: str, totals: dict) -> Player:
    """Build a rate-based Player from a raw-totals dict (see _season_totals_by_player)."""
    halves = totals["halves"]
    hud_h = totals["hud_halves"] or halves
    return Player(
        name=totals["name"], matches=float(totals.get("matches", 1)),
        kd_ratio=(totals["kills"] / totals["deaths"]) if totals["deaths"] else totals["kills"],
        kills_half=totals["kills"] / halves if halves else 0.0,
        deaths_half=totals["deaths"] / halves if halves else 0.0,
        flags_half=totals["flags"] / halves if halves else 0.0,
        assists_half=totals["assists"] / hud_h if hud_h else 0.0,
        damage_half=totals["damage"] / hud_h if hud_h else 0.0,
        breaks_half=totals["breaks"] / hud_h if hud_h else 0.0,
        role=totals["role"], team=totals["team"],
    )


def compute_prediction_accuracy(raw_rows: list["RawMatchStats"], match_results: dict,
                                 p: KtprParams, match_rows: list["Player"] | None = None,
                                 map_names: dict[str, str] | None = None,
                                 min_role_map_matches: int = 3) -> dict:
    """
    Leave-one-out validation: for each resolved match, predict the winner as
    the team with the higher average KTPR, computed from each player's SEASON
    totals with that match's own contribution subtracted out first (a match's
    own result must not help predict itself — the naive season-total KTPR is
    circular for this purpose). Compares KTPR's accuracy against a naive
    raw-K/D-ratio baseline computed the same leave-one-out way, on the same
    matches, so the comparison isolates whether KTPR's extra machinery
    (assists/damage/flags/breaks weighting, role normalization, ...) earns its
    complexity over just "who has the better K/D". Also reports a MEDIAN
    team-strength variant (more robust to one very hot/cold performer on a
    small 6-player roster), essentially free from the same per-player values.

    If `match_rows` (per-match Player rows with `.map_name`, e.g. from
    ktpr_mysql.load_match_player_stats) and `map_names` (match_id -> map_name,
    e.g. ktpr_mysql._match_maps) are supplied, ALSO scores a map-adjusted
    variant: each held-out match's team strength is computed against that
    match's own role x map medians (same approach as compute_map_adjusted_ktpr)
    instead of the season-wide role medians, falling back to the season-wide
    baseline when a role x map cell has fewer than `min_role_map_matches`. The
    role x map baselines themselves are NOT leave-one-out (same reasoning as
    role medians below — negligible per-match leakage on an already-small cell).

    Role medians are NOT recomputed leave-one-out — one match's effect on a
    ~60-player median is negligible, and the real circularity risk (a
    player's own performance predicting their own match) is fully addressed
    by leaving out their numerator. Scoped to formula='team' (profile='new'),
    like the other match-level analyses.
    """
    season_totals = _season_totals_by_player(raw_rows)
    season_players = [_player_snapshot(sid, tot) for sid, tot in season_totals.items()]
    baseline_for = _team_baselines(season_players, p)

    role_map_baseline: dict[tuple[str, str], dict] | None = None
    if match_rows is not None:
        by_role_map: dict[tuple[str, str], list["Player"]] = {}
        for pl in match_rows:
            if pl.name and pl.map_name:
                by_role_map.setdefault((pl.role, pl.map_name), []).append(pl)

        def _med(vals: list[float]) -> float:
            m = _median(vals)
            return m if m else 1.0

        def _bset(group: list["Player"]) -> dict:
            return {
                "K": _med([x.kills_half for x in group]), "A": _med([x.assists_half for x in group]),
                "D": _med([x.damage_half for x in group]), "F": _med([x.flags_half for x in group]),
                "B": _med([x.breaks_half for x in group]), "X": _med([x.deaths_half for x in group]),
                "KD": _med([x.kd_ratio for x in group]),
            }

        role_map_baseline = {key: _bset(grp) for key, grp in by_role_map.items()
                              if len(grp) >= min_role_map_matches}

    by_match: dict[str, list["RawMatchStats"]] = {}
    for r in raw_rows:
        by_match.setdefault(r.match_id, []).append(r)

    detail: list[dict] = []
    for match_id, rows in by_match.items():
        mr = match_results.get(match_id)
        if not mr or not mr.get("winner"):
            continue
        team_names = list(mr["team_scores"].keys())
        if len(team_names) != 2:
            continue
        ta, tb = team_names

        loo_players: dict[str, Player] = {}
        kd_loo: dict[str, float] = {}
        for r in rows:
            tot = season_totals[r.steam_id]
            loo = {
                "name": tot["name"], "role": tot["role"], "team": tot["team"],
                "kills": tot["kills"] - r.kills, "deaths": tot["deaths"] - r.deaths,
                "assists": tot["assists"] - r.assists, "damage": tot["damage"] - r.damage,
                "flags": tot["flags"] - r.flags, "breaks": tot["breaks"] - r.breaks,
                "halves": tot["halves"] - r.halves, "hud_halves": tot["hud_halves"] - r.hud_halves,
            }
            if loo["halves"] <= 0:
                continue   # this was the player's only match -> no leave-one-out baseline
            loo_players[r.steam_id] = _player_snapshot(r.steam_id, loo)
            kd_loo[r.steam_id] = (loo["kills"] / loo["deaths"]) if loo["deaths"] else loo["kills"]

        sids = list(loo_players.keys())
        pls = [loo_players[s] for s in sids]
        vals = compute_team(pls, p, baseline_for=baseline_for)
        val_by_sid = dict(zip(sids, vals))

        ktpr_a = [v for s, v in val_by_sid.items() if v is not None and loo_players[s].team == ta]
        ktpr_b = [v for s, v in val_by_sid.items() if v is not None and loo_players[s].team == tb]
        kd_a = [kd_loo[s] for s in sids if loo_players[s].team == ta]
        kd_b = [kd_loo[s] for s in sids if loo_players[s].team == tb]
        if not ktpr_a or not ktpr_b or not kd_a or not kd_b:
            continue

        actual = mr["winner"]
        pred_ktpr = ta if _mean(ktpr_a) > _mean(ktpr_b) else tb
        pred_ktpr_median = ta if _median(ktpr_a) > _median(ktpr_b) else tb
        pred_kd = ta if _mean(kd_a) > _mean(kd_b) else tb
        row = {
            "match_id": match_id, "team_a": ta, "team_b": tb, "actual_winner": actual,
            "ktpr_predicted": pred_ktpr, "ktpr_correct": pred_ktpr == actual,
            "ktpr_median_predicted": pred_ktpr_median, "ktpr_median_correct": pred_ktpr_median == actual,
            "kd_predicted": pred_kd, "kd_correct": pred_kd == actual,
        }

        if role_map_baseline is not None and map_names is not None:
            this_map = map_names.get(match_id)

            def baseline_for_row(pl: Player, _map=this_map) -> dict:
                return (role_map_baseline.get((pl.role, _map)) if _map else None) or baseline_for(pl)

            map_vals = compute_team(pls, p, baseline_for=baseline_for_row)
            map_val_by_sid = dict(zip(sids, map_vals))
            madj_a = [v for s, v in map_val_by_sid.items() if v is not None and loo_players[s].team == ta]
            madj_b = [v for s, v in map_val_by_sid.items() if v is not None and loo_players[s].team == tb]
            if madj_a and madj_b:
                pred_map = ta if _mean(madj_a) > _mean(madj_b) else tb
                row["map_adj_predicted"] = pred_map
                row["map_adj_correct"] = pred_map == actual

        detail.append(row)

    n = len(detail)

    def _acc(key: str) -> float | None:
        vals2 = [r[key] for r in detail if key in r]
        return round(sum(vals2) / len(vals2), 3) if vals2 else None

    return {
        "n_matches": n,
        "accuracy_ktpr": _acc("ktpr_correct"),
        "accuracy_ktpr_median": _acc("ktpr_median_correct"),
        "accuracy_map_adjusted": _acc("map_adj_correct"),
        "accuracy_kd_baseline": _acc("kd_correct"),
        "matches": detail,
    }


def compute_match_avg_ktpr(season_players: list[Player], match_rows: list[Player],
                            p: KtprParams) -> list[dict]:
    """
    Compare the standard season-TOTAL-based KTPR against an alternative: the
    mean/median of each player's PER-MATCH KTPR (each match scored against
    season-wide role medians). Season-total KTPR is sums-of-sums, so a couple
    of heavy matches can dominate it; match-averaging treats each match as one
    equally-weighted observation instead.
    """
    season_vals = compute_ktpr(season_players, p)
    season_ktpr = {pl.name: v for pl, v in zip(season_players, season_vals) if pl.name and v is not None}

    baseline_for = _team_baselines(season_players, p)
    match_vals = compute_team(match_rows, p, baseline_for=baseline_for)
    by_player: dict[str, list[float]] = {}
    for pl, v in zip(match_rows, match_vals):
        if pl.name and v is not None:
            by_player.setdefault(pl.name, []).append(v)

    out: list[dict] = []
    for name, vs in by_player.items():
        season_v = season_ktpr.get(name)
        match_avg = _mean(vs)
        out.append({
            "player": name, "matches": len(vs),
            "season_total_ktpr": round(season_v, 3) if season_v is not None else None,
            "match_avg_ktpr": round(match_avg, 3),
            "match_median_ktpr": round(_median(vs), 3),
            "delta_avg_vs_season": round(match_avg - season_v, 3) if season_v is not None else None,
        })
    return out


def compute_shrunk_ktpr(players: list[Player], p: KtprParams, shrink_matches: float = 3.0) -> list[dict]:
    """
    Empirical-Bayes-style shrinkage toward the player's role median, weighted
    by matches played: shrunk = w*raw + (1-w)*role_prior, where
    w = n / (n + shrink_matches). shrink_matches is "how many matches' worth"
    of role-average prior gets blended in — a player with many more matches
    than that stands almost entirely on their own number; a player with few
    matches gets pulled toward a sane baseline instead of standing on a small,
    possibly-noisy sample with the same apparent confidence as a regular.
    """
    vals = compute_ktpr(players, p)
    threshold = _participation_threshold(players, p)
    named = [(pl, v) for pl, v in zip(players, vals) if pl.name and v is not None]

    by_role: dict[str, list[float]] = {}
    for pl, v in named:
        if pl.matches >= threshold:
            by_role.setdefault(pl.role, []).append(v)
    role_median = {role: _median(vs) for role, vs in by_role.items()}
    global_median = _median([v for _, v in named])

    out: list[dict] = []
    for pl, v in named:
        prior = role_median.get(pl.role, global_median)
        n = pl.matches
        w = n / (n + shrink_matches) if (n + shrink_matches) else 0.0
        shrunk = w * v + (1 - w) * prior
        out.append({
            "player": pl.name, "role": pl.role, "matches": n,
            "raw_ktpr": round(v, 3), "role_prior": round(prior, 3),
            "shrunk_ktpr": round(shrunk, 3), "shrink_weight": round(w, 3),
        })
    return out


def compute_map_adjusted_ktpr(season_players: list[Player], match_rows: list[Player], p: KtprParams,
                               min_role_map_matches: int = 3) -> list[dict]:
    """
    Alternative season KTPR that bakes map context INTO the score instead of
    reporting it as a separate cut (see map_report): each match is scored
    against its own role x map medians (falling back to the season-wide role
    median when a role x map cell is too small to trust — `min_role_map_matches`),
    then averaged per player. A player whose matches happened to land more on
    maps favorable to their role will see this rating pulled down relative to
    the standard season KTPR, and vice versa for an unfavorable map slate.
    """
    season_baseline_for = _team_baselines(season_players, p)

    by_role_map: dict[tuple[str, str], list[Player]] = {}
    for pl in match_rows:
        if pl.name and pl.map_name:
            by_role_map.setdefault((pl.role, pl.map_name), []).append(pl)

    def med(vals: list[float]) -> float:
        m = _median(vals)
        return m if m else 1.0

    def bset(group: list[Player]) -> dict:
        return {
            "K": med([x.kills_half for x in group]), "A": med([x.assists_half for x in group]),
            "D": med([x.damage_half for x in group]), "F": med([x.flags_half for x in group]),
            "B": med([x.breaks_half for x in group]), "X": med([x.deaths_half for x in group]),
            "KD": med([x.kd_ratio for x in group]),
        }

    role_map_baseline = {key: bset(grp) for key, grp in by_role_map.items()
                          if len(grp) >= min_role_map_matches}

    def baseline_for_row(pl: Player) -> dict:
        return role_map_baseline.get((pl.role, pl.map_name)) or season_baseline_for(pl)

    vals = compute_team(match_rows, p, baseline_for=baseline_for_row)

    by_player: dict[str, list[float]] = {}
    for pl, v in zip(match_rows, vals):
        if pl.name and v is not None:
            by_player.setdefault(pl.name, []).append(v)

    season_vals = compute_ktpr(season_players, p)
    season_ktpr = {pl.name: v for pl, v in zip(season_players, season_vals) if pl.name and v is not None}

    out: list[dict] = []
    for name, vs in by_player.items():
        adj = _mean(vs)
        base = season_ktpr.get(name)
        out.append({
            "player": name, "matches": len(vs),
            "season_ktpr": round(base, 3) if base is not None else None,
            "map_adjusted_ktpr": round(adj, 3),
            "delta": round(adj - base, 3) if base is not None else None,
        })
    return out


def _spearman(rank_a: dict[str, int], rank_b: dict[str, int]) -> float:
    common = set(rank_a) & set(rank_b)
    n = len(common)
    if n < 2:
        return 1.0
    d2 = sum((rank_a[k] - rank_b[k]) ** 2 for k in common)
    return 1 - (6 * d2) / (n * (n * n - 1))


def _ranking(players: list[Player], vals: list[float | None]) -> dict[str, int]:
    ordered = sorted([(pl.name, v) for pl, v in zip(players, vals) if pl.name and v is not None],
                      key=lambda t: -t[1])
    return {name: i for i, (name, _) in enumerate(ordered, 1)}


SENSITIVITY_KNOBS = ["tw_kill", "tw_kd", "tw_assist", "tw_damage", "tw_flag", "tw_break",
                     "kill_exp", "dmg_interaction", "assist_interaction", "death_w"]


def compute_weight_sensitivity(players: list[Player], p: KtprParams, perturb: float = 0.10) -> list[dict]:
    """
    For each core 'team'-formula weight, perturb it +/-`perturb` (10% by
    default) and measure how much the player RANKING moves: Spearman rank
    correlation vs. the unperturbed ranking, and the count of players whose
    rank moved >= 3 places. A knob with low correlation / high movement means
    the ranking is sensitive to a somewhat arbitrary hand-tuned number — a
    signal the formula may be less robust than it looks around that knob, not
    that the underlying stat is unimportant. Sorted most-sensitive first.
    """
    base_vals = compute_ktpr(players, p)
    base_rank = _ranking(players, base_vals)

    out: list[dict] = []
    for knob in SENSITIVITY_KNOBS:
        if not hasattr(p, knob):
            continue
        orig = getattr(p, knob)
        rhos, moved = [], []
        for direction in (1 + perturb, 1 - perturb):
            p2 = replace(p, **{knob: orig * direction})
            vals2 = compute_ktpr(players, p2)
            rank2 = _ranking(players, vals2)
            rhos.append(_spearman(base_rank, rank2))
            moved.append(sum(1 for k in base_rank if k in rank2 and abs(base_rank[k] - rank2[k]) >= 3))
        out.append({
            "knob": knob, "base_value": orig, "perturb_pct": perturb,
            "avg_spearman_rho": round(_mean(rhos), 4), "avg_players_moved_3plus": round(_mean(moved), 1),
        })
    out.sort(key=lambda r: r["avg_spearman_rho"])
    return out


def compute_additive(players: list[Player], p: KtprParams) -> list[float | None]:
    """
    Artifact-style KTPR: a weighted average of per-dimension ratios to the
    population baseline (mean or median). Terms with weight 0 are skipped, so
    absent stats never break it.
        KTPR = ( Σ w_i * x_i / baseline(x_i) ) / Σ w_i
    """
    threshold = _participation_threshold(players, p)
    named = [pl for pl in players if pl.name]
    pop = [pl for pl in named if pl.matches >= threshold] if p.additive_regulars_only else named
    base = _mean if p.norm == "mean" else _median

    def B(vals: list[float]) -> float:
        b = base(vals)
        return b if b else 1.0

    # (weight, per-player accessor). kd uses the ratio directly; others per-half.
    terms = [
        (p.add_kd,      lambda pl: pl.kd_ratio),
        (p.add_kills,   lambda pl: pl.kills_half),
        (p.add_flags,   lambda pl: pl.flags_half),
        (p.add_assists, lambda pl: pl.assists_half),
        (p.add_damage,  lambda pl: pl.damage_half),
        (p.add_breaks,  lambda pl: pl.breaks_half),
    ]
    active = [(w, acc, B([acc(pl) for pl in pop])) for (w, acc) in terms if w]
    total_w = sum(w for (w, _, _) in active) or 1.0

    out: list[float | None] = []
    for pl in players:
        if not pl.name:
            out.append(None)
            continue
        s = sum(w * (acc(pl) / baseline) for (w, acc, baseline) in active)
        out.append(s / total_w)
    return out


def compute_excel(players: list[Player], p: KtprParams) -> list[float | None]:
    """Return KTPR for each player under the given params. None == "-" (blank/guarded)."""
    threshold = _participation_threshold(players, p)
    regulars = [pl for pl in players if pl.matches >= threshold]

    med_K_reg = _safe_median([pl.kills_half for pl in regulars], p.guard_zero_median)
    med_M_reg = _safe_median([pl.deaths_half for pl in regulars], p.guard_zero_median)
    med_O_reg = _safe_median([pl.flags_half for pl in regulars], p.guard_zero_median)
    med_O_all = _safe_median([pl.flags_half for pl in players], p.guard_zero_median)
    # new-dimension medians (regulars). Guard against all-zero (data absent):
    # if a stat's median is 0 the dimension is simply skipped, so old/current
    # and a no-data "new" run behave identically to before.
    med_dmg_reg = _median([pl.damage_half for pl in regulars])
    med_brk_reg = _median([pl.breaks_half for pl in regulars])

    out: list[float | None] = []
    for pl in players:
        if not pl.name:
            out.append(None)
            continue

        # --- core skill ratio ---
        # old/current: capped column-I K/D. redesigned "new": fold assists in
        # as a discounted kill -> KDA = (kills + w*assists)/deaths.
        if p.use_assists and pl.deaths_half > 0:
            skill = (pl.kills_half + p.assist_weight * pl.assists_half) / pl.deaths_half
        else:
            skill = pl.kd_ratio
        core = min(skill, p.kd_cap) * (pl.kills_half / med_K_reg)

        # --- flag bonus (objective) ---
        log_part = math.log(pl.flags_half + 1) / math.log(p.flag_log_base)
        if pl.matches >= threshold:
            rel = (pl.flags_half / med_O_reg - 1) * p.flag_w_regular
        else:
            rel = (pl.flags_half / med_O_all - 1) * p.flag_w_nonregular
        flag_bonus = min(log_part + rel, p.flag_cap)

        # --- break bonus (objective/utility) — redesigned only ---
        break_bonus = 0.0
        if p.use_breaks and med_brk_reg > 0:
            break_bonus = min((pl.breaks_half / med_brk_reg - 1) * p.break_w, p.break_cap)

        # --- damage bonus — redesigned only; small (correlated with kills) ---
        damage_bonus = 0.0
        if p.use_damage and med_dmg_reg > 0:
            damage_bonus = min((pl.damage_half / med_dmg_reg - 1) * p.damage_w, p.damage_cap)

        # --- death penalty ---
        death_pen = min((pl.deaths_half / med_M_reg - 1) * p.death_w, p.death_cap)

        ktpr = (p.scale * core
                * (1 + flag_bonus)
                * (1 + break_bonus)
                * (1 + damage_bonus)
                * (1 - death_pen))

        # current formula: if the (x0.8) test value is 0 -> "-". We mirror the
        # "blank/zero -> -" behavior: a genuine zero core yields None.
        if p.guard_zero_median and ktpr == 0:
            out.append(None)
        else:
            out.append(ktpr)
    return out


# ---------------------------------------------------------------------------
# CSV loader (the data-source abstraction; MySQL loader slots in here later)
# ---------------------------------------------------------------------------

def _to_float(s: str) -> float:
    s = (s or "").strip().replace("%", "")
    if s == "":
        return 0.0
    return float(s)


def load_players_from_csv(path: str) -> list[Player]:
    players: list[Player] = []
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        for row in reader:
            if not row or not (row[0] or "").strip():
                continue
            # A=0 name, C=2 KTPRn, D=3 matches, I=8 K/D, K=10 kills/half,
            # M=12 deaths/half, O=14 flags/half
            try:
                players.append(Player(
                    name=row[0].strip(),
                    ktprn_sheet=_to_float(row[2]) if len(row) > 2 and row[2].strip() else None,
                    matches=_to_float(row[3]),
                    kd_ratio=_to_float(row[8]),
                    kills_half=_to_float(row[10]),
                    deaths_half=_to_float(row[12]),
                    flags_half=_to_float(row[14]),
                ))
            except (IndexError, ValueError):
                continue
    return players


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="Compute KTPR from a stats CSV.")
    ap.add_argument("csv", nargs="?", default="Book1.csv")
    ap.add_argument("--profile", default=None,
                    help="single profile to show (old/current/new). Default: show all three.")
    args = ap.parse_args()

    players = load_players_from_csv(args.csv)
    print(f"Loaded {len(players)} players from {args.csv}\n")

    if args.profile:
        vals = compute_ktpr(players, load_params(args.profile))
        print(f"{'player':<16}{args.profile:>10}")
        for pl, v in zip(players, vals):
            print(f"{pl.name:<16}{(f'{v:.2f}' if v is not None else '-'):>10}")
    else:
        old = compute_ktpr(players, load_params("old"))
        cur = compute_ktpr(players, load_params("current"))
        new = compute_ktpr(players, load_params("new"))
        print(f"{'player':<16}{'sheet':>7}{'old':>8}{'current':>9}{'new':>8}")
        for pl, o, c, n in zip(players, old, cur, new):
            f = lambda x: f"{x:.2f}" if x is not None else "-"
            ss = f(pl.ktprn_sheet)
            print(f"{pl.name:<16}{ss:>7}{f(o):>8}{f(c):>9}{f(n):>8}")
