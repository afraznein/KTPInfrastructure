### `research`, `scripts`: KTPR v1 tuning research and the Discord draft extractor move in from local checkouts (2026-09-19)

`research/ktpr-v1-tuning-2026-08/` holds the five August-2026 Philly LAN tuning documents
(LAN comparison, sensitivity sweep, `tw_kd` x `tw_break` sweep, team-formula tuning view,
HLstatsX-vs-HUD data quality) and the scripts that produced them, previously only in the
untracked `ktpeffort` checkout. `scripts/discord_drafts/` is the Discord match-channel crawler
and regex pick/ban extractor from `ktp_stats/ktp_metadata`, code only: its crawl cache and
`.env` are gitignored. `docs/ktpr_mcp/` is confirmed the one home of the KTPR v1 engine; the
local copies are superseded (infra-ktpr-consolidation).
