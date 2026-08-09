# KTPR MCP Server

An MCP server that computes **KTPR** (a KTP player-performance rating) and exposes
it as tools for an agent. Self-contained: engine + weights + data layer + docs.

## What's in here

| File | Purpose |
|------|---------|
| `ktpr_mcp.py` | The MCP server (entry point). |
| `ktpr_engine.py` | The KTPR calculation. Pure Python stdlib, no deps. |
| `ktpr_mysql.py` | Live data layer — pulls tournament stats over SSH. |
| `weights.toml` | **All tunable weights.** Nothing is hard-coded; edit here. |
| `roster.csv` | `steam_id,name,team_name,matches` map for clean display names/teams (live data). **Not tracked in git** — it maps every player's SteamID to every alias they've used, so it stays out of this public repo. Supply your own copy; without it the tools fall back to a name-tag heuristic. |
| `sample_stats.csv` | A legacy CSV for a zero-config smoke test (no DB needed). |
| `KTPR_SPEC.md` | Full spec: formulas, column contract, data model. |
| `KTPR_KNOBS.md` | Knob-by-knob reference for the active team formula: the calculation, what each weight does, and its measured impact. |
| `.mcp.json` | Registration snippet (edit the path). |

## Requirements

- **Python 3.11+** (uses stdlib `tomllib`).
- `pip install -r requirements.txt` (installs the `mcp` SDK).

## Tools exposed

| Tool | Description |
|------|-------------|
| `list_profiles()` | Weight profiles in `weights.toml` (`old`, `current`, `artifact`, `new`). |
| `get_weights(profile)` | The knobs for one profile. |
| `compute_ktpr(profile="new", source="mysql")` | Ranked players with `ktpr`, `style`, `kd`, `kda`, `role`. |
| `compare_profiles(profiles, source="mysql")` | Side-by-side ranks + biggest movers. |
| `team_impact(profile="new", source="mysql")` | Value-over-replacement: swing to team average if a player were subbed for a role-typical replacement. **mysql only.** |
| `clutch_report(profile="new", source="mysql")` | Per-match KTPR split by win/loss, margin of victory, and opponent strength, plus a consistency (stdev) score. **mysql only.** |
| `map_report(profile="new", source="mysql")` | Role x map average KTPR — which roles run hot/cold on which maps. **mysql only.** |
| `side_report(profile="new", source="mysql")` | Per-player axis vs allies KTPR split. **mysql only.** |
| `predict_accuracy(profile="new", source="mysql")` | Leave-one-out: does team KTPR predict who wins, vs a raw-K/D baseline? **mysql only.** |
| `match_avg_vs_season(profile="new", source="mysql")` | Season-total KTPR vs mean-of-per-match KTPR — where the two aggregations disagree. **mysql only.** |
| `shrunk_ktpr(profile="new", source="mysql", shrink_matches=3.0)` | Sample-size-aware KTPR, shrunk toward the role median for low-match players. |
| `map_adjusted_ktpr(profile="new", source="mysql")` | Season KTPR scored against role x map medians instead of season-wide medians. **mysql only.** |
| `weight_sensitivity(profile="new", source="mysql", perturb=0.10)` | How much the ranking moves when each weight knob is perturbed ±10%. |

`profile="new"` is the live redesigned **team formula**; `old`/`current` are the
legacy Excel formulas; `artifact` is an alternate additive formula.

## Data sources (the `source` argument)

- **`"mysql"` (default) — live tournament data.** Requires SSH access to the
  stats host, with the key loaded into your SSH agent. Set `KTPR_SSH_HOST`
  (`user@host`) — it's an env var, not a constant, so this file can live in a
  public repo; override the database with `KTPR_DB`. On Windows, load the key once:
  `Set-Service ssh-agent -StartupType Automatic; Start-Service ssh-agent; ssh-add <key>`.
  Queries run over `ssh <host> "mysql ..."` — **no local MySQL driver needed.**
- **`"sample_stats.csv"` (or any CSV path) — offline.** Works with no DB. Note the
  bundled sample is *legacy Excel data* (no assists/damage/breaks and no role
  info), so the team formula degrades gracefully but isn't meaningful — it's only
  for verifying the server runs. See `KTPR_SPEC.md` for the CSV column contract.

## Run it

```bash
pip install -r requirements.txt
python ktpr_mcp.py                 # starts the MCP server (stdio)
```

Quick offline check without an MCP client:

```bash
python -c "import ktpr_mcp as M; print(M.compute_ktpr(source='sample_stats.csv')[:3])"
```

## Register with Claude Code

```bash
claude mcp add ktpr -- python /abs/path/to/ktpr_mcp.py
```

…or drop `.mcp.json` at your project root (update the absolute path in it first).

## Tuning

All behavior lives in `weights.toml` under `[profiles.new]` — contribution
weights (`tw_kd`, `tw_break`, …), the low-kill amplifiers, per-role multipliers,
within-class normalization, etc. Edit and re-call the tools; no code changes
needed. `KTPR_SPEC.md` §4 documents every knob.

## Notes / handoff caveats

- **Two telemetry systems:** KTPR uses **HLstatsX** for kills/deaths/flags
  (authoritative) and **HUD** for assists/damage/breaks (newer, ~4–6% under
  HLstatsX on overlapping stats). See `KTPR_SPEC.md` §5.
- **Scope:** live data is filtered to the Sat/Sun `match_type=0` tournament
  matches (constants `TOURNAMENT_MATCH_TYPES` / `TOURNAMENT_DAYS` in
  `ktpr_mysql.py`).
- **Styles** (e.g. "Ace Sharpshooter") are descriptive labels; they don't feed
  back into the KTPR value.