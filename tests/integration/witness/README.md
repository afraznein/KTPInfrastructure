# KTPWitness — test-only forward observer

A 50-LoC AMX plugin that registers as a CONSUMER of KTPMatchHandler's
`ktp_match_start` and `ktp_match_end` multi-forwards and writes one JSONL
line per fire to `addons/ktpamx/logs/witness.jsonl`.

## Why this exists

The Tier 2 match-flow integration tests need a way to assert "the forward
fired with these args." Options considered:

1. **Scrape `log_ktp` `event=HALF_START` / `event=MATCH_END` lines.** Rejected
   because those are state-transition events emitted from KTPMatchHandler's
   internal codepaths — they fire at the same time as the forward but they
   don't *prove* the forward fired. A regression where ExecuteForward runs
   but a consumer crashes before its handler returns would pass a log-based
   assertion incorrectly.

2. **Add a test-only diagnostic native to KTPAMXX that reads forward-fire
   counts.** Heavyweight; touches the engine bridge for a test concern.

3. **Witness plugin (chosen).** Lightweight, lives entirely in the AMXX
   plugin layer, never touches production code. As a real consumer it
   exercises the same forward-dispatch path as KTPHLTVRecorder.

## Output format

`addons/ktpamx/logs/witness.jsonl` — one JSONL row per forward fire:

```jsonl
{"event":"ktp_match_start","ts":1777677796,"matchId":"1777677796-ATL2","map":"dod_anzio","matchType":0,"half":1}
{"event":"ktp_match_end","ts":1777678450,"matchId":"1777677796-ATL2","map":"dod_anzio","matchType":0,"score1":5,"score2":3}
```

Field reference:

| Key | Type | Source |
|---|---|---|
| `event` | string | `ktp_match_start` or `ktp_match_end` |
| `ts` | int | `get_systime()` at fire time (Unix epoch, server clock) |
| `matchId` | string | KTPMatchHandler's `g_matchId` |
| `map` | string | Current map name |
| `matchType` | int | `MatchType` enum: 0=COMP, 1=SCRIM, 2=12MAN, 3=DRAFT, 4=KTP_OT, 5=DRAFT_OT |
| `half` | int | (start only) `1`/`2` for regulation, `101+` for OT rounds |
| `score1` | int | (end only) Final team1 score |
| `score2` | int | (end only) Final team2 score |

## Compile

```bash
bash compile.sh
# → compiled/KTPWitness.amxx
```

No `KTP_TEST_MODE` flag needed — this plugin is itself the test-mode artifact.

## Production safety

This binary **must never** appear in any production server's `plugins.ini`.
The integration-test docker-compose setup will mount it into the test
container's plugins directory only. The `.amxx` lives under
`KTPInfrastructure/tests/integration/witness/compiled/` which is not a
production deploy path.

If the witness ever appears on a production host:
- Symptoms: `addons/ktpamx/logs/witness.jsonl` accumulates indefinitely
- Operational impact: minimal (each fire is a few-hundred-byte file append).
- Removal: `rm` the .amxx + remove from plugins.ini + `restart-all-servers.sh`

## See also

- `KTPInfrastructure/TEST_INFRASTRUCTURE_PLAN.md` § Tier 2 — full integration-test roadmap
- `KTPMatchHandler/CHANGELOG.md` 0.10.122 — test-mode build flag this depends on
- `KTPHLTVRecorder.sma` — production consumer example using the same forward-handler pattern
