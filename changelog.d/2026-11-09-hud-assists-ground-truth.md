### Documented
- `load_hud.py` now says which of its two assist tables is authoritative.
  `hud_player_stats.assists` under-reports because the producer samples the
  counter mid-increment; `hud_kill_assists`, exploded from the payload, matches
  the events row for row. The miss is spread across nearly every match instead
  of clustering, so a consumer reading the counter is quietly a few percent low
  and has nothing to notice. The note also kills the per-kill-cap theory with
  the structural fact that retires it — every assisted kill carries exactly one
  assister — and records that the `hud_kill_assists` explode joins on a
  non-unique key, which is latent rather than live.
