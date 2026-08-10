/**
 * KTPMatchDrive — halftime side swap, and a roster readback.
 *
 * A KTP match is two halves with the teams swapped between them. Production
 * does that swap through the map/round machinery with real clients
 * reconnecting; bots do not go through any of it, so a Lane B match would
 * otherwise play both halves with everyone on the same side.
 *
 * That matters for the data this produces, not just for realism. KTPR reads
 * per-half, per-team stats, and a fixture where every player only ever
 * appears on one team cannot exercise:
 *
 *   - a player's stats being split across two teams inside one match
 *   - per-half aggregation actually keying on half rather than on team
 *   - anything that joins a player to "the side they were on at the time"
 *
 * So the swap is part of the fixture being useful, not a cosmetic detail.
 *
 * ## Why dodx_set_user_team and not a team-change command
 *
 * The production module set is amxxcurl + reapi + dodx — no fun, no engine,
 * no fakemeta — and bots do not process client commands. `dodx_set_user_team`
 * is the only lever available, and it is the one DODX exposes for exactly this.
 *
 * Not for production. Diagnostic only; Lane B appends it at run time.
 */

#include <amxmodx>
#include <dodx>

#define PLUGIN  "KTP Match Drive"
#define VERSION "0.1"
#define AUTHOR  "KTP"

#define MD_TEAM_ALLIES 1
#define MD_TEAM_AXIS   2

public plugin_init() {
	register_plugin(PLUGIN, VERSION, AUTHOR)
	register_srvcmd("ktp_md_swap", "cmd_swap")
	register_srvcmd("ktp_md_roster", "cmd_roster")
	log_amx("[MD] loaded — NOT FOR PRODUCTION")
}

/**
 * ktp_md_swap — put every player on the other side.
 *
 * Teams are read first and written second, in two passes. A single pass that
 * read and wrote per player would swap someone to Axis and then, on a later
 * iteration, read that new value and swap them back if the native's write is
 * visible immediately — which would silently leave the roster unchanged for
 * some players and produce a fixture that looks swapped but is not.
 */
public cmd_swap() {
	new players[32], num
	get_players(players, num)

	new want[33]
	new swapped = 0

	for (new i = 0; i < num; i++) {
		new id = players[i]
		want[id] = 0
		if (!is_user_connected(id))
			continue
		new t = get_user_team(id)
		if (t == MD_TEAM_ALLIES)
			want[id] = MD_TEAM_AXIS
		else if (t == MD_TEAM_AXIS)
			want[id] = MD_TEAM_ALLIES
	}

	for (new i = 0; i < num; i++) {
		new id = players[i]
		if (!want[id])
			continue
		dodx_set_user_team(id, want[id], 1)
		swapped++
	}

	log_amx("[MD] swap requested for %d of %d player(s)", swapped, num)
	set_task(2.0, "md_report_roster")
	return PLUGIN_HANDLED
}

public md_report_roster() {
	cmd_roster()
}

/**
 * ktp_md_roster — one line per player, so the harness can prove the swap
 * actually took rather than assuming the native succeeded.
 */
public cmd_roster() {
	new players[32], num
	get_players(players, num)

	new allies = 0, axis = 0
	for (new i = 0; i < num; i++) {
		new id = players[i]
		if (!is_user_connected(id))
			continue
		new name[32]
		get_user_name(id, name, charsmax(name))
		new t = get_user_team(id)
		if (t == MD_TEAM_ALLIES) allies++
		else if (t == MD_TEAM_AXIS) axis++
		log_amx("[MD] player id=%d name=%s team=%d", id, name, t)
	}
	log_amx("[MD] roster allies=%d axis=%d total=%d", allies, axis, num)
	return PLUGIN_HANDLED
}
