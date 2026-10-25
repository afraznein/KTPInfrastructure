### `analytics`: private connection rows carry the player's league alias (schema 37, DTO v1.18.0) (2026-10-25)

Ruled 2026-10-25 (drew, coordination `netcode-player-settings`): netcode reports name players by
league alias, resolved from SteamID, with the in-game name beside it; a player with no league
account keeps the in-game name and is marked not a league player.

- New `scripts/league_registry.py` reads the website's `player_steam` (status `current`) and
  `player` tables once per process with the `KTP_SUPABASE_URL` / `KTP_SUPABASE_SECRET_KEY` the report
  service already has for `report_sync`. Read-only; no new secret, no new grant.
- `connection.players[]` (private tier) gains `league_alias` and `league_registered`. When the
  registry cannot be read -- no env, network, HTTP error -- the report still builds and both read
  `null` (unknown), never `false`; `connection.instruments.league` says `unavailable`. A row with no
  SteamID (bots) is `null` too.
- Public block unchanged. `SCHEMA_VERSION` 36 -> 37, contract v1.18.0.
- A registration made after a report was built shows up at the next schema bump, not before:
  the generator only rebuilds a report whose schema is behind.
