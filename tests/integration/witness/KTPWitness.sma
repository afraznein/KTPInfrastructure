/* KTP Witness — test-only plugin for Tier 2 integration tests.
 *
 * Records forward dispatches into `addons/ktpamx/logs/witness.jsonl` so that
 * integration tests can assert "the forward fired with these args" by tailing
 * a single file rather than scraping log_ktp output (which only captures
 * state transitions, not per-forward fires).
 *
 * Two surfaces covered:
 *
 *   1. Match-flow multi-forwards from KTPMatchHandler — `ktp_match_start`
 *      and `ktp_match_end`. The witness is a CONSUMER of these multi-forwards
 *      (Pawn auto-subscribes any plugin that declares a `public` matching the
 *      multi-forward name, so no register_forward call needed).
 *
 *   2. DODX engine forwards — `controlpoints_init` (Phase 1; further forwards
 *      added in subsequent phases per DODX_FORWARD_FIRING_DESIGN.md). Same
 *      consumer pattern as match-flow forwards: declare `public <name>` and
 *      AMXX routes the DODX-side ExecuteForward dispatch here automatically.
 *
 * JSONL row shape:
 *   - All rows have `event` (string, the witness's labelled name) and `ts`
 *     (unix epoch seconds via get_systime()).
 *   - Match-flow rows inline forward args as top-level keys (matchId, map,
 *     matchType, half/score1/score2).
 *   - DODX rows nest forward args under `args` ({} when the forward has no
 *     args, like controlpoints_init). Empty `args` is preserved (not omitted)
 *     so tests can rely on key presence.
 *
 * NEVER INSTALLED IN PRODUCTION. The KTPInfrastructure integration setup
 * stages this .amxx into the test container's plugins/ directory only;
 * production plugins.ini files in this repo do not list it.
 *
 * Dependencies:
 *   - KTPMatchHandler 0.10.1+ (for the match-flow forwards)
 *   - KTPAMXX 2.6.2+ (for fopen/fputs/fclose, get_systime)
 *   - dodx module loaded (for controlpoints_init dispatch — the forward only
 *     fires when DODX is registered as a module, which is always true in the
 *     KTP fleet)
 *
 * See KTPInfrastructure/TEST_INFRASTRUCTURE_PLAN.md § Tier 2 and
 * tests/integration/DODX_FORWARD_FIRING_DESIGN.md.
 */

#include <amxmodx>
#include <dodx>

#define PLUGIN_NAME    "KTP Witness (test-only)"
#define PLUGIN_VERSION "1.7.0"
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

    // Phase 2b: kill-trigger rcon for the client_death test path. addbot
    // alone doesn't fire client_death (no attacker), and bot-vs-bot combat
    // is too unreliable for test timing — so the witness exposes a direct
    // rcon that calls user_kill() on a target slot. Test-only; never wired
    // into any production plugin.
    //
    // user_kill() lives in the AMXX core (ktpamx_i386.so itself; native table
    // entry at KTPAMXX/amxmodx/amxmodx.cpp:4962), so no extra module load.
    // register_concmd is also core; matches the same registration pattern
    // KTPMatchHandler uses for its -DKTP_TEST_MODE rcons.
    //
    // Usage from a test: hlds.rcon("amx_witness_kill <slot>") -> user_kill
    // dispatches the death event -> DODX raises client_death -> our public
    // client_death(...) handler below records the row.
    register_concmd("amx_witness_kill", "cmd_witness_kill", -1, "<slot> — test-only: kill the player at <slot> via user_kill()");

    // Phase 3b: forward-dispatch rcons for the hot-path tests
    // (client_damage, dod_grenade_explosion, client_score, dod_score_event).
    // Each rcon parses its args and calls the corresponding
    // dodx_test_dispatch_* native, which in turn fires the forward via
    // MF_ExecuteForward — the same primitive DODX uses for real engine
    // events. The witness's own public handlers below (or any other
    // subscribed plugin's public) catch the dispatch and write the row.
    //
    // Test-only. Production plugins MUST NOT call these natives. See
    // dodx.inc § "TEST-ONLY forward dispatch primitives" for the safety
    // analysis.
    register_concmd("amx_witness_dispatch_damage",   "cmd_witness_dispatch_damage",
        -1, "<attacker> <victim> <damage> <wpnindex> <hitplace> <TA> — test-only");
    register_concmd("amx_witness_dispatch_grenade",  "cmd_witness_dispatch_grenade",
        -1, "<slot> <x> <y> <z> <wpnid> — test-only: dispatch dod_grenade_explosion");
    register_concmd("amx_witness_dispatch_score",    "cmd_witness_dispatch_score",
        -1, "<id> <score_delta> <total> <cp_index> — test-only: dispatch client_score + dod_score_event");
    register_concmd("amx_witness_dispatch_cp_captured", "cmd_witness_dispatch_cp_captured",
        -1, "<cp_index> <new_owner> <old_owner> — test-only: dispatch dod_control_point_captured");

    // Phase 2c (1.7.0): dispatch rcons for the five formerly bot-gated
    // forwards (KTPAMXX 2.7.19+ dodx natives) + the 2.7.18 per-shot
    // weapon-fire forward. Replaces the addbot driver path that never
    // worked (DoD ships no bot AI — see BOT_AI_REQUIRED_REASON history
    // in test_dodx_forward_firing.py).
    register_concmd("amx_witness_dispatch_client_spawn", "cmd_witness_dispatch_client_spawn",
        -1, "<id> — test-only: dispatch dod_client_spawn");
    register_concmd("amx_witness_dispatch_changeteam", "cmd_witness_dispatch_changeteam",
        -1, "<id> <team> <oldteam> — test-only: dispatch dod_client_changeteam");
    register_concmd("amx_witness_dispatch_changeclass", "cmd_witness_dispatch_changeclass",
        -1, "<id> <class> <oldclass> — test-only: dispatch dod_client_changeclass");
    register_concmd("amx_witness_dispatch_client_death", "cmd_witness_dispatch_client_death",
        -1, "<killer> <victim> <wpnindex> <hitplace> <TK> — test-only: dispatch client_death");
    register_concmd("amx_witness_dispatch_stats_flush", "cmd_witness_dispatch_stats_flush",
        -1, "<id> — test-only: dispatch dod_stats_flush");
    register_concmd("amx_witness_dispatch_weapon_fire", "cmd_witness_dispatch_weapon_fire",
        -1, "<id> <weapon> <gametime> — test-only: dispatch dod_client_weapon_fire");

    log_amx("[KTP-WITNESS] Initialized — observing match-flow + DODX forwards (controlpoints_init, client_spawn, client_changeteam, client_changeclass, client_death, client_damage, dod_grenade_explosion, client_score, dod_score_event, dod_stats_flush, dod_control_point_captured, dod_client_weapon_fire) + amx_witness_kill + amx_witness_dispatch_* rcons");
}

// Test-only kill-trigger. Validates the slot, calls user_kill(slot, 0), and
// returns PLUGIN_HANDLED. Bad slots (out of range, not connected) log a
// warning and no-op rather than firing — keeps test failures attributable
// to test logic rather than to the kill primitive itself.
public cmd_witness_kill() {
    new buf[8];
    read_argv(1, buf, charsmax(buf));
    new slot = str_to_num(buf);

    if (slot < 1 || slot > 32) {
        log_amx("[KTP-WITNESS] amx_witness_kill: slot %d out of range (1..32)", slot);
        return PLUGIN_HANDLED;
    }
    if (!is_user_connected(slot)) {
        log_amx("[KTP-WITNESS] amx_witness_kill: slot %d not connected — no-op", slot);
        return PLUGIN_HANDLED;
    }

    user_kill(slot, 0);
    log_amx("[KTP-WITNESS] amx_witness_kill: user_kill(%d, 0) dispatched", slot);
    return PLUGIN_HANDLED;
}

// Phase 3b rcon handlers — read args from the rcon command line and call
// the corresponding dodx_test_dispatch_* native to fire the forward.
// Each rcon does no slot/value validation (the natives short-circuit if
// the forward isn't registered, but otherwise pass args straight through);
// the test layer is responsible for sanity.

public cmd_witness_dispatch_damage() {
    new buf[8];
    read_argv(1, buf, charsmax(buf)); new attacker = str_to_num(buf);
    read_argv(2, buf, charsmax(buf)); new victim   = str_to_num(buf);
    read_argv(3, buf, charsmax(buf)); new damage   = str_to_num(buf);
    read_argv(4, buf, charsmax(buf)); new wpnindex = str_to_num(buf);
    read_argv(5, buf, charsmax(buf)); new hitplace = str_to_num(buf);
    read_argv(6, buf, charsmax(buf)); new TA       = str_to_num(buf);

    dodx_test_dispatch_damage(attacker, victim, damage, wpnindex, hitplace, TA);
    return PLUGIN_HANDLED;
}

public cmd_witness_dispatch_grenade() {
    new buf[16];
    read_argv(1, buf, charsmax(buf)); new slot    = str_to_num(buf);
    read_argv(2, buf, charsmax(buf)); new Float:x = str_to_float(buf);
    read_argv(3, buf, charsmax(buf)); new Float:y = str_to_float(buf);
    read_argv(4, buf, charsmax(buf)); new Float:z = str_to_float(buf);
    read_argv(5, buf, charsmax(buf)); new wpnid   = str_to_num(buf);

    new Float:pos[3];
    pos[0] = x;
    pos[1] = y;
    pos[2] = z;

    dodx_test_dispatch_grenade_explosion(slot, pos, wpnid);
    return PLUGIN_HANDLED;
}

public cmd_witness_dispatch_score() {
    new buf[8];
    read_argv(1, buf, charsmax(buf)); new id          = str_to_num(buf);
    read_argv(2, buf, charsmax(buf)); new score_delta = str_to_num(buf);
    read_argv(3, buf, charsmax(buf)); new total       = str_to_num(buf);
    read_argv(4, buf, charsmax(buf)); new cp_index    = str_to_num(buf);

    dodx_test_dispatch_score(id, score_delta, total, cp_index);
    return PLUGIN_HANDLED;
}

public cmd_witness_dispatch_cp_captured() {
    new buf[8];
    read_argv(1, buf, charsmax(buf)); new cp_index  = str_to_num(buf);
    read_argv(2, buf, charsmax(buf)); new new_owner = str_to_num(buf);
    read_argv(3, buf, charsmax(buf)); new old_owner = str_to_num(buf);

    dodx_test_dispatch_cp_captured(cp_index, new_owner, old_owner);
    return PLUGIN_HANDLED;
}

// Phase 2c rcon handlers (1.7.0) — same pattern as Phase 3b above.

public cmd_witness_dispatch_client_spawn() {
    new buf[8];
    read_argv(1, buf, charsmax(buf)); new id = str_to_num(buf);

    dodx_test_dispatch_client_spawn(id);
    return PLUGIN_HANDLED;
}

public cmd_witness_dispatch_changeteam() {
    new buf[8];
    read_argv(1, buf, charsmax(buf)); new id      = str_to_num(buf);
    read_argv(2, buf, charsmax(buf)); new team    = str_to_num(buf);
    read_argv(3, buf, charsmax(buf)); new oldteam = str_to_num(buf);

    dodx_test_dispatch_changeteam(id, team, oldteam);
    return PLUGIN_HANDLED;
}

public cmd_witness_dispatch_changeclass() {
    new buf[8];
    read_argv(1, buf, charsmax(buf)); new id       = str_to_num(buf);
    read_argv(2, buf, charsmax(buf)); new newclass = str_to_num(buf);
    read_argv(3, buf, charsmax(buf)); new oldclass = str_to_num(buf);

    dodx_test_dispatch_changeclass(id, newclass, oldclass);
    return PLUGIN_HANDLED;
}

public cmd_witness_dispatch_client_death() {
    new buf[8];
    read_argv(1, buf, charsmax(buf)); new killer   = str_to_num(buf);
    read_argv(2, buf, charsmax(buf)); new victim   = str_to_num(buf);
    read_argv(3, buf, charsmax(buf)); new wpnindex = str_to_num(buf);
    read_argv(4, buf, charsmax(buf)); new hitplace = str_to_num(buf);
    read_argv(5, buf, charsmax(buf)); new TK       = str_to_num(buf);

    dodx_test_dispatch_client_death(killer, victim, wpnindex, hitplace, TK);
    return PLUGIN_HANDLED;
}

public cmd_witness_dispatch_stats_flush() {
    new buf[8];
    read_argv(1, buf, charsmax(buf)); new id = str_to_num(buf);

    dodx_test_dispatch_stats_flush(id);
    return PLUGIN_HANDLED;
}

public cmd_witness_dispatch_weapon_fire() {
    new buf[16];
    read_argv(1, buf, charsmax(buf)); new id             = str_to_num(buf);
    read_argv(2, buf, charsmax(buf)); new weapon         = str_to_num(buf);
    read_argv(3, buf, charsmax(buf)); new Float:gametime = str_to_float(buf);

    dodx_test_dispatch_weapon_fire(id, weapon, gametime);
    return PLUGIN_HANDLED;
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

// ---------------------------------------------------------------------------
// DODX engine forwards
// ---------------------------------------------------------------------------
// DODX dispatches each forward via ExecuteForward (ET_IGNORE) — plugins
// consume by declaring `public <forward_name>(...)` and AMXX routes any
// matching public to that plugin. No register_forward call needed; the
// fan-out is multi-consumer so production hooks (e.g. KTPHLStatsX consuming
// `client_death`) and this test witness coexist without interference.
//
// Witness event labels are `dod_` prefixed for namespace clarity in the
// JSONL log (matches the design doc's per-row contract). Pawn `^"` is the
// embedded-double-quote escape (Pawn uses caret, not backslash, as the
// string-escape char).

// Phase 1: controlpoints_init — fires once per map load, no args.
// Production consumer: KTPHLStatsX.
public controlpoints_init() {
    new line[256];
    formatex(line, charsmax(line),
        "{^"event^":^"dod_controlpoints_init^",^"ts^":%d,^"args^":{}}",
        get_systime());
    write_jsonl(line);
}

// Phase 2: dod_client_spawn(id) — fires when a player spawns into the round.
// Production consumer: KTPPracticeMode (grenade auto-refill).
public dod_client_spawn(id) {
    new line[256];
    formatex(line, charsmax(line),
        "{^"event^":^"dod_client_spawn^",^"ts^":%d,^"args^":{^"id^":%d}}",
        get_systime(), id);
    write_jsonl(line);
}

// Phase 2: dod_client_changeteam(id, team, oldteam) — fires on team switch.
// Initial spectator->team transition on bot/player join also fires this.
// team / oldteam values: 1=Allies, 2=Axis, 3=Spectators.
// Production consumer: KTPMatchHandler (.confirm flow).
public dod_client_changeteam(id, team, oldteam) {
    new line[256];
    formatex(line, charsmax(line),
        "{^"event^":^"dod_client_changeteam^",^"ts^":%d,^"args^":{^"id^":%d,^"team^":%d,^"oldteam^":%d}}",
        get_systime(), id, team, oldteam);
    write_jsonl(line);
}

// Phase 2: dod_client_changeclass(id, class, oldclass) — fires on class
// switch (just after spawn per dodx.inc note). Initial class pick on first
// spawn fires this too with oldclass=0.
// Production consumer: KTPMatchHandler (mid-match audit).
public dod_client_changeclass(id, class, oldclass) {
    new line[256];
    formatex(line, charsmax(line),
        "{^"event^":^"dod_client_changeclass^",^"ts^":%d,^"args^":{^"id^":%d,^"class^":%d,^"oldclass^":%d}}",
        get_systime(), id, class, oldclass);
    write_jsonl(line);
}

// Phase 2: client_death(killer, victim, wpnindex, hitplace, TK) — fires on
// player death. TK=1 if killed by teammate. Note: the forward name has NO
// `dod_` prefix in dodx.inc; we still label the event `dod_client_death` in
// the JSONL log for namespace consistency with the other DODX rows.
// Production consumers: KTPHLStatsX, KTPMatchHandler.
public client_death(killer, victim, wpnindex, hitplace, TK) {
    new line[256];
    formatex(line, charsmax(line),
        "{^"event^":^"dod_client_death^",^"ts^":%d,^"args^":{^"killer^":%d,^"victim^":%d,^"wpnindex^":%d,^"hitplace^":%d,^"TK^":%d}}",
        get_systime(), killer, victim, wpnindex, hitplace, TK);
    write_jsonl(line);
}

// Phase 3: client_damage(attacker, victim, damage, wpnindex, hitplace, TA) —
// fires after every player-to-player attack. TA=1 if teammate damage. This
// is a HOT path — fires hundreds of times per minute on a busy server. In
// test environments with 1-4 bots it fires only when bot AI engages, which
// is non-deterministic; tests for this forward will assert occurrence +
// shape, not exact values.
// Production consumer: KTPHLStatsX.
public client_damage(attacker, victim, damage, wpnindex, hitplace, TA) {
    new line[256];
    formatex(line, charsmax(line),
        "{^"event^":^"dod_client_damage^",^"ts^":%d,^"args^":{^"attacker^":%d,^"victim^":%d,^"damage^":%d,^"wpnindex^":%d,^"hitplace^":%d,^"TA^":%d}}",
        get_systime(), attacker, victim, damage, wpnindex, hitplace, TA);
    write_jsonl(line);
}

// Phase 3: dod_grenade_explosion(id, Float:pos[3], wpnid) — fires when a
// grenade detonates. pos is a 3-float world-coordinate vector (x, y, z).
// JSONL serialization renders the array as [x,y,z] with %.2f precision —
// enough resolution for test assertions, avoids the noise of full %f
// trailing zeros (DoD coords go up to ~16384 per axis).
// Production consumer: KTPPracticeMode (auto-refill).
public dod_grenade_explosion(id, Float:pos[3], wpnid) {
    new line[256];
    formatex(line, charsmax(line),
        "{^"event^":^"dod_grenade_explosion^",^"ts^":%d,^"args^":{^"id^":%d,^"pos^":[%.2f,%.2f,%.2f],^"wpnid^":%d}}",
        get_systime(), id, pos[0], pos[1], pos[2], wpnid);
    write_jsonl(line);
}

// Phase 2c: dod_client_weapon_fire(id, weapon, Float:gametime) — fires on
// every primary-attack actuation incl. pure misses (KTPAMXX 2.7.18+, the
// per-shot forward feeding the future Rule 4.6 cadence detector). gametime
// is gpGlobals->time at the shot; %.2f is plenty for round-trip asserts.
// Production consumer: none yet (dormant until the Season-10 cadence work).
public dod_client_weapon_fire(id, weapon, Float:gametime) {
    new line[256];
    formatex(line, charsmax(line),
        "{^"event^":^"dod_client_weapon_fire^",^"ts^":%d,^"args^":{^"id^":%d,^"weapon^":%d,^"gametime^":%.2f}}",
        get_systime(), id, weapon, gametime);
    write_jsonl(line);
}

// Phase 3: client_score(id, score, total) — fires when a player's score
// changes (frag, suicide, team bonus, cap-credit). Note: the forward name
// has NO `dod_` prefix; we still namespace as `dod_client_score` in the
// JSONL event label.
// Production consumer: KTPScoreTracker.
public client_score(id, score, total) {
    new line[256];
    formatex(line, charsmax(line),
        "{^"event^":^"dod_client_score^",^"ts^":%d,^"args^":{^"id^":%d,^"score^":%d,^"total^":%d}}",
        get_systime(), id, score, total);
    write_jsonl(line);
}

// Phase 3: dod_score_event(id, score_delta, total_score, cp_index) — fires
// alongside client_score with control-point context. cp_index is the CP
// that triggered the score change, or -1 if not CP-related (e.g. a kill
// frag without flag involvement).
// Production consumer: KTPScoreTracker.
public dod_score_event(id, score_delta, total_score, cp_index) {
    new line[256];
    formatex(line, charsmax(line),
        "{^"event^":^"dod_score_event^",^"ts^":%d,^"args^":{^"id^":%d,^"score_delta^":%d,^"total_score^":%d,^"cp_index^":%d}}",
        get_systime(), id, score_delta, total_score, cp_index);
    write_jsonl(line);
}

// Phase 4: dod_stats_flush(id) — fires from KTPMatchHandler's match-end
// sequence (calls dodx_flush_all_stats() per CLAUDE.md "Match Flow"
// section). One row per connected player at flush time.
// Production consumer: KTPMatchHandler ↔ KTPHLStatsX (stats correlation).
public dod_stats_flush(id) {
    new line[256];
    formatex(line, charsmax(line),
        "{^"event^":^"dod_stats_flush^",^"ts^":%d,^"args^":{^"id^":%d}}",
        get_systime(), id);
    write_jsonl(line);
}

// Phase 4: dod_control_point_captured(cp_index, new_owner, old_owner) —
// fires when a flag/CP changes ownership. new_owner / old_owner team
// values: 0=neutral, 1=allies, 2=axis.
// Production consumers: KTPMatchHandler (cap state), KTPScoreTracker.
public dod_control_point_captured(cp_index, new_owner, old_owner) {
    new line[256];
    formatex(line, charsmax(line),
        "{^"event^":^"dod_control_point_captured^",^"ts^":%d,^"args^":{^"cp_index^":%d,^"new_owner^":%d,^"old_owner^":%d}}",
        get_systime(), cp_index, new_owner, old_owner);
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
