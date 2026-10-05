### Fixed
- Match analytics decides per-hit damage per match. A match that ended before `ktp_damage_events` began, built against the live database, now publishes Statsme damage dealt and `null` for damage taken, team, self and grenade damage instead of a per-hit `0`. Team damage totals with an unknown member are `null`. Report schema 25, DTO contract `analytics-report-dto-v1.11.0`.
