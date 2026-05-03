/* KTP Witness — test-only plugin for Tier 2 match-flow integration tests.
 *
 * Registers as a CONSUMER of the multi-forwards that KTPMatchHandler emits
 * (`ktp_match_start`, `ktp_match_end`) and writes one JSONL line per fire to
 * `addons/ktpamx/logs/witness.jsonl`. The integration-test harness tails this
 * file (or rcon-greps after each test) to assert "the forward fired with
 * these args" without needing to scrape `log_ktp` output for forward-firing
 * evidence — log_ktp lines are emitted from KTPMatchHandler's HALF_START /
 * MATCH_START events, but those are state transitions, not forward fires.
 * The witness plugin is the cleanest "another plugin observed this" signal.
 *
 * NEVER INSTALLED IN PRODUCTION. The KTPInfrastructure docker-compose
 * integration setup mounts this .amxx into the test container's plugins/
 * directory only; production plugins.ini files in this repo do not list it.
 *
 * Dependencies:
 *   - KTPMatchHandler 0.10.1+ (for the forwards)
 *   - KTPAMXX 2.6.2+ (for fopen/fputs/fclose, get_systime)
 *
 * See KTPInfrastructure/TEST_INFRASTRUCTURE_PLAN.md § Tier 2.
 */

#include <amxmodx>

#define PLUGIN_NAME    "KTP Witness (test-only)"
#define PLUGIN_VERSION "1.0.0"
#define PLUGIN_AUTHOR  "Nein_"

// JSONL output path. The integration test harness tails this file.
// addons/ktpamx/logs/ already exists in the AMXX standard layout — same
// directory log_amx() writes to — so no extra setup needed.
#define WITNESS_LOG "addons/ktpamx/logs/witness.jsonl"

// Match types — duplicated from KTPMatchHandler.sma so the witness can
// label them in the JSONL output without having to import that header.
// Keep numeric values in sync with KTPMatchHandler.sma's MatchType enum.
#define MT_COMPETITIVE 0
#define MT_SCRIM       1
#define MT_12MAN       2
#define MT_DRAFT       3
#define MT_KTP_OT      4
#define MT_DRAFT_OT    5

public plugin_init() {
    register_plugin(PLUGIN_NAME, PLUGIN_VERSION, PLUGIN_AUTHOR);
    log_amx("[KTP-WITNESS] Initialized — observing ktp_match_start + ktp_match_end forwards");
}

// Consumer for KTPMatchHandler's CreateMultiForward("ktp_match_start", ...).
// Signature must match exactly: (matchId, map, matchType, half).
//
// AMXX routes ExecuteForward → all plugins with a public function of this
// name. No register_forward call is needed here because we're a consumer of
// a multi-forward, not a built-in engine forward.
// Pawn uses ^ (caret) as the string-escape char, not backslash. ^" embeds
// a literal double-quote so we can produce a JSON object.
public ktp_match_start(const matchId[], const map[], matchType, half) {
    new line[256];
    formatex(line, charsmax(line),
        "{^"event^":^"ktp_match_start^",^"ts^":%d,^"matchId^":^"%s^",^"map^":^"%s^",^"matchType^":%d,^"half^":%d}",
        get_systime(), matchId, map, matchType, half);
    write_jsonl(line);
}

// Consumer for ktp_match_end. Args: (matchId, map, matchType, team1Score, team2Score).
public ktp_match_end(const matchId[], const map[], matchType, team1Score, team2Score) {
    new line[256];
    formatex(line, charsmax(line),
        "{^"event^":^"ktp_match_end^",^"ts^":%d,^"matchId^":^"%s^",^"map^":^"%s^",^"matchType^":%d,^"score1^":%d,^"score2^":%d}",
        get_systime(), matchId, map, matchType, team1Score, team2Score);
    write_jsonl(line);
}

// Append one JSONL line to the witness log. Best-effort: if the file can't
// be opened (filesystem full, permissions, etc.), the witness silently
// drops the line — better than crashing the integration test.
write_jsonl(const line[]) {
    new f = fopen(WITNESS_LOG, "at");
    if (!f) return;
    fputs(f, line);
    fputs(f, "^n");
    fclose(f);
}
