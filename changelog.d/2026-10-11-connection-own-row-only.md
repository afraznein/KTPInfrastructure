### `analytics`: `connection.players[]` leaves the public report (DTO v1.14.0) (2026-10-11)

Drew revised the ruling the same day the block shipped: a player's connection numbers are
visible only to that player, on their own stats page. The public `connection` block now carries
the server-level `match` figures, `instruments` and a `privacy` sentence, and no per-player row.
The producer's report (schema 30, unchanged) still builds `connection.players[]` for the private
player tier to serve to the signed-in player.

Caught before anything reached the site: at the time of the change Supabase held zero
v1.13.0 rows (the schema-30 regeneration had only reached 12-mans, which `report_sync` holds
back). The report timer was paused while this merged so the first regenerated official could
not sync with the old DTO; the DTO is applied at sync time, so no second regeneration is needed.
