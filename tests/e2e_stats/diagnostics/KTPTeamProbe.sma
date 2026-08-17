/* Diagnostic: what does get_user_team() actually return for bots?
 *
 * Both the assist path and the cap-break path in ktp_stats_capture.inc gate on
 * get_user_team():
 *
 *   assist:    if (get_user_team(a) == victim_team) continue
 *   cap break: new vt = get_user_team(victim)  ... compared against CA_num_allies/axis
 *
 * If it returns the same value (or 0) for every bot, the assist loop skips
 * every candidate and the break path picks the wrong zone counter — which
 * would explain both emitting zero from one root cause.
 *
 * Writes with log_message so the output lands in the game log the harness
 * already reads (AMXX console output does not reach rcon in extension mode).
 */
#include <amxmodx>

public plugin_init() {
    register_plugin("KTP Team Probe", "1.0", "KTP");
    register_srvcmd("ktp_team_dump", "cmd_dump");
}

public cmd_dump() {
    new players[32], num;
    get_players(players, num);
    log_message("[TEAMPROBE] get_players reports %d", num);

    // Sweep every slot regardless of get_players(). If the engine has bots in
    // these slots but AMXX reports is_user_connected=0, then AMXX never saw
    // their ClientPutInServer — and every emit path in ktp_stats_capture.inc
    // is gated on exactly that native.
    new seen = 0;
    for (new id = 1; id <= 32; id++) {
        new name[32], infoteam[32];
        get_user_name(id, name, charsmax(name));
        new conn = is_user_connected(id) ? 1 : 0;
        new conning = is_user_connecting(id) ? 1 : 0;
        // A non-empty name means the ENGINE has someone in this slot, whatever
        // AMXX thinks. That is the comparison that matters: engine says yes,
        // AMXX says no.
        if (!conn && !conning && name[0] == 0)
            continue;
        seen++;
        get_user_info(id, "team", infoteam, charsmax(infoteam));
        log_message("[TEAMPROBE] id=%d connected=%d connecting=%d team=%d info_team=%s bot=%d name=%s",
                    id, conn, conning, get_user_team(id), infoteam,
                    is_user_bot(id) ? 1 : 0, name);
    }
    log_message("[TEAMPROBE] slots with any presence: %d", seen);
    return PLUGIN_HANDLED;
}
