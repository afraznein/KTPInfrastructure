/**
 * KTPBreakDrive — stage cap-break scenarios on demand.
 *
 * Lane B produces a cap_break in about half its runs, by luck. That is enough
 * to show the positive path works and useless for the negatives, which are the
 * ones that matter: the deployment plan's own note says a false-positive break
 * is worse than a missed one, because it silently inflates a player's
 * objective rating and nothing ever contradicts it.
 *
 * Bots cannot be told "let this cap finish cleanly" or "walk off the point".
 * This plugin drives those situations directly, so the four negatives become
 * deterministic instead of a thing someone eyeballs on a live server.
 *
 * ## Why this stages rather than simulates
 *
 * The break detector's trigger is a REAL drop in `CA_num_allies`/`CA_num_axis`
 * read out of the game's own capture-area data. A synthetic forward cannot
 * produce that — the body has to actually leave the zone. So every scenario
 * here uses real bots in real zones, and only the *attribution* is injected:
 *
 *   dodx_test_dispatch_client_death(killer, victim, ...)   <- queues the candidate
 *   dod_user_kill(victim)                                  <- drops the count
 *
 * Order is load-bearing and mirrors production. `ksc_queue_break_candidate`
 * reads the in-zone count at queue time to set its baseline, so the dispatch
 * must happen while the victim is still standing in the zone. Kill first and
 * the baseline is already the post-death value, no drop is ever seen, and the
 * scenario silently tests nothing.
 *
 * `dod_user_kill` alone is not enough: it is a self-kill, and
 * `ksc_queue_break_candidate` rejects `killer == victim` — correctly, since a
 * suicide on a point is not somebody else breaking the cap.
 *
 * ## Why 2D distance
 *
 * `CP_VALUE` exposes `CP_origin_x` and `CP_origin_y` but no z, so proximity is
 * measured in the XY plane. That is fine for picking who is standing on a
 * flag: DoD capture zones are wide and flat relative to their height, and the
 * alternative — reading the area entity's bounds — needs fakemeta, which is
 * deliberately not in the production module set.
 *
 * ## Not for production
 *
 * Diagnostic only. It is never in `plugins.ini` on the fleet; Lane B appends
 * it at run time, the same way KTPTeamProbe is used. It kills players on
 * command, which is not a thing that should be loadable anywhere real.
 */

#include <amxmodx>
#include <dodx>
#include <reapi>

#define PLUGIN  "KTP Break Drive"
#define VERSION "0.1"
#define AUTHOR  "KTP"

#define BD_MAX_FLAGS  32
// Generous: DoD capture zones are large, and picking someone standing just
// outside the trigger would make a positive scenario look like a detector bug.
// Cross-checked at run time against whether the count actually drops.
#define BD_NEAR_RADIUS 300.0
// "Far" has to be unambiguous — a player this distance away cannot be inside
// the zone, so their death must NOT be credited as a break.
#define BD_FAR_RADIUS  900.0

#define BD_TEAM_ALLIES 1
#define BD_TEAM_AXIS   2
#define BD_TASK_WALKOFF_POLL 77130
#define BD_TASK_UNPROTECT_BASE 77140
#define BD_WALKOFF_MAX_POLLS 2400
#define BD_WALKOFF_DEATH_QUIET_SECS 5.0
#define BD_WALKOFF_PROTECT_SECS 5.0

new g_bdWalkoffPolls = 0
new Float:g_bdLastTeamDeath[3]

public plugin_init() {
	register_plugin(PLUGIN, VERSION, AUTHOR)
	register_srvcmd("ktp_bd_scan", "cmd_scan")
	register_srvcmd("ktp_bd_kill", "cmd_kill")
	register_srvcmd("ktp_bd_walkoff", "cmd_walkoff")
	register_srvcmd("ktp_bd_arm_walkoff", "cmd_arm_walkoff")
	log_amx("[BD] loaded — NOT FOR PRODUCTION")
}

public client_death(killer, victim, wpnindex, hitplace, TK) {
	new team = get_user_team(victim)
	if (team == BD_TEAM_ALLIES || team == BD_TEAM_AXIS)
		g_bdLastTeamDeath[team] = get_gametime()
}

// ---------------------------------------------------------------------------

stock bool:bd_flag_origin(f, Float:out[3]) {
	new x = dodx_objective_get_data(f, CP_origin_x)
	new y = dodx_objective_get_data(f, CP_origin_y)
	if (x == 0 && y == 0)
		return false
	out[0] = float(x)
	out[1] = float(y)
	out[2] = 0.0
	return true
}

stock Float:bd_dist2d(const Float:a[3], const Float:b[3]) {
	new Float:dx = a[0] - b[0]
	new Float:dy = a[1] - b[1]
	return floatsqroot(dx * dx + dy * dy)
}

stock bd_zone_count(f, team) {
	return dodx_area_get_data(f, (team == BD_TEAM_ALLIES) ? CA_num_allies : CA_num_axis)
}

/**
 * A flag with a cap actually in progress right now, or -1.
 *
 * Chosen here rather than passed in from the harness. Caps on a 16-bot server
 * start and stop in seconds, so a flag that was capturing when the harness
 * scanned is routinely finished by the time its rcon arrives ~1s later — every
 * scenario in one whole run aborted with "not capturing" for exactly that
 * reason. Picking at command time removes the gap instead of racing it.
 */
stock bd_find_capturing() {
	new n = dodx_objectives_get_num()
	if (n > BD_MAX_FLAGS) n = BD_MAX_FLAGS

	for (new f = 0; f < n; f++) {
		if (!dodx_area_get_data(f, CA_is_capturing))
			continue
		new team = dodx_area_get_data(f, CA_capturing_team)
		if (team != BD_TEAM_ALLIES && team != BD_TEAM_AXIS)
			continue
		if (bd_zone_count(f, team) >= 1)
			return f
	}
	return -1
}

/** Resolve a flag argument: a number, or "auto" for whatever is capturing. */
stock bd_resolve_flag(const arg[]) {
	if (equal(arg, "auto"))
		return bd_find_capturing()
	new f = str_to_num(arg)
	return (f >= 0 && f < dodx_objectives_get_num()) ? f : -1
}

/**
 * Nearest (want_near) or farthest (!want_near) live player of `team` from the
 * flag, subject to the radius gate. Returns 0 if nobody qualifies — the caller
 * must report that rather than substituting a different player, or the run
 * would quietly test the opposite scenario.
 */
stock bd_pick(f, team, bool:want_near, &Float:out_dist) {
	new Float:flag[3]
	if (!bd_flag_origin(f, flag))
		return 0

	new best = 0
	new Float:best_d = want_near ? 999999.0 : 0.0
	new players[32], num
	get_players(players, num)

	for (new i = 0; i < num; i++) {
		new id = players[i]
		if (!is_user_connected(id) || !is_user_alive(id))
			continue
		if (get_user_team(id) != team)
			continue

		new Float:origin[3]
		if (!dodx_get_user_origin(id, origin))
			continue
		new Float:d = bd_dist2d(origin, flag)

		if (want_near) {
			if (d <= BD_NEAR_RADIUS && d < best_d) {
				best = id
				best_d = d
			}
		} else {
			if (d >= BD_FAR_RADIUS && d > best_d) {
				best = id
				best_d = d
			}
		}
	}
	out_dist = best ? best_d : 0.0
	return best
}

/** Any live enemy of `team`, to attribute the kill to. */
stock bd_pick_enemy(team) {
	new players[32], num
	get_players(players, num)
	for (new i = 0; i < num; i++) {
		new id = players[i]
		if (is_user_connected(id) && is_user_alive(id) && get_user_team(id) != team)
			return id
	}
	return 0
}

// ---------------------------------------------------------------------------

public cmd_scan() {
	new n = dodx_objectives_get_num()
	if (n > BD_MAX_FLAGS) n = BD_MAX_FLAGS

	for (new f = 0; f < n; f++) {
		new name[32]
		dodx_objective_get_data(f, CP_name, name, charsmax(name))
		log_amx("[BD] flag %d name=%s owner=%d capping=%d capteam=%d allies=%d axis=%d ox=%d oy=%d",
			f, name,
			dodx_area_get_data(f, CA_owning_team),
			dodx_area_get_data(f, CA_is_capturing),
			dodx_area_get_data(f, CA_capturing_team),
			dodx_area_get_data(f, CA_num_allies),
			dodx_area_get_data(f, CA_num_axis),
			dodx_objective_get_data(f, CP_origin_x),
			dodx_objective_get_data(f, CP_origin_y))
	}
	log_amx("[BD] scan done flags=%d", n)
	return PLUGIN_HANDLED
}

/**
 * ktp_bd_kill <flag> <near|far>
 *
 * `near` is the positive scenario: a capper standing on the point is killed by
 * an enemy, the in-zone count drops, a break must be emitted.
 *
 * `far` is the off-point negative: a player of the *same capping team* who is
 * demonstrably nowhere near the point is killed. A candidate is queued, the
 * count does not drop, and the candidate must age out with no break.
 *
 * Both log the in-zone count before and after, so the assertion can be made
 * against what actually happened rather than against what was intended — if
 * `near` failed to drop the count, that scenario proved nothing and must not
 * be scored as a missing break.
 */
public cmd_kill() {
	new arg_flag[8], arg_mode[8]
	read_argv(1, arg_flag, charsmax(arg_flag))
	read_argv(2, arg_mode, charsmax(arg_mode))

	new f = bd_resolve_flag(arg_flag)
	new bool:want_near = !equal(arg_mode, "far")

	if (f < 0) {
		log_amx("[BD] kill ABORT flag=-1 no flag is capturing right now")
		return PLUGIN_HANDLED
	}
	if (!dodx_area_get_data(f, CA_is_capturing)) {
		log_amx("[BD] kill ABORT flag=%d not capturing", f)
		return PLUGIN_HANDLED
	}

	new team = dodx_area_get_data(f, CA_capturing_team)
	if (team != BD_TEAM_ALLIES && team != BD_TEAM_AXIS) {
		log_amx("[BD] kill ABORT flag=%d capteam=%d", f, team)
		return PLUGIN_HANDLED
	}

	new Float:dist = 0.0
	new victim = bd_pick(f, team, want_near, dist)
	if (!victim) {
		log_amx("[BD] kill ABORT flag=%d mode=%s no qualifying player", f, arg_mode)
		return PLUGIN_HANDLED
	}
	new killer = bd_pick_enemy(team)
	if (!killer) {
		log_amx("[BD] kill ABORT flag=%d no enemy to attribute to", f)
		return PLUGIN_HANDLED
	}

	// Names, not just slots: the break line names its breaker by name, and
	// matching on that is what separates "our staged kill produced this break"
	// from "a bot happened to break a cap in the same six seconds". Without it
	// the scenarios mis-attribute ordinary play, which is exactly what the
	// first run of this did.
	new kname[32], vname[32]
	get_user_name(killer, kname, charsmax(kname))
	get_user_name(victim, vname, charsmax(vname))

	// capteam is reported because the flag is resolved here, not by the caller:
	// with `auto` the harness does not know which flag was picked, so it cannot
	// know which column of the follow-up count report to read.
	new before = bd_zone_count(f, team)
	log_amx("[BD] kill flag=%d capteam=%d mode=%s victim=%d vname=%s killer=%d kname=%s dist=%.0f count_before=%d owner_before=%d",
		f, team, arg_mode, victim, vname, killer, kname, dist, before,
		dodx_area_get_data(f, CA_owning_team))

	// Dispatch first: the detector reads its baseline here, and the victim has
	// to still be in the zone for that baseline to be the pre-death count.
	dodx_test_dispatch_client_death(killer, victim, 1, 0, 0)
	dod_user_kill(victim)

	set_task(1.5, "bd_report_after", f)
	return PLUGIN_HANDLED
}

/**
 * Owner is reported because a completed capture deliberately suppresses the
 * break: the detector clears its queue when `CA_owning_team` flips, so that
 * cappers walking off a point they just took are not credited to whoever last
 * got a kill there. A staged kill that coincides with the cap completing
 * therefore produces no break for correct reasons, and without the owner the
 * harness cannot tell that apart from a missed break.
 */
public bd_report_after(f) {
	log_amx("[BD] after flag=%d allies=%d axis=%d capping=%d owner=%d",
		f, dodx_area_get_data(f, CA_num_allies),
		dodx_area_get_data(f, CA_num_axis),
		dodx_area_get_data(f, CA_is_capturing),
		dodx_area_get_data(f, CA_owning_team))
}

/**
 * ktp_bd_walkoff <flag>
 *
 * The voluntary walk-off negative, and the plan calls it the hardest case: a
 * capper leaves the point under their own power, with no kill involved. The
 * in-zone count drops exactly as it would for a break, so if the baseline
 * latch is over-crediting this is where it shows.
 *
 * The destination is a live team-mate's position rather than a computed one.
 * `CP_VALUE` has no z and there is no fakemeta here to trace the floor, so a
 * synthesised coordinate could drop the bot inside geometry; another player is
 * standing somewhere by definition valid.
 */
stock bd_execute_walkoff(f) {
	if (f < 0) {
		log_amx("[BD] walkoff ABORT flag=-1 no flag is capturing right now")
		return
	}
	if (!dodx_area_get_data(f, CA_is_capturing)) {
		log_amx("[BD] walkoff ABORT flag=%d not capturing", f)
		return
	}
	new team = dodx_area_get_data(f, CA_capturing_team)
	if (team != BD_TEAM_ALLIES && team != BD_TEAM_AXIS) {
		log_amx("[BD] walkoff ABORT flag=%d capteam=%d", f, team)
		return
	}

	new Float:dist = 0.0
	new mover = bd_pick(f, team, true, dist)
	if (!mover) {
		log_amx("[BD] walkoff ABORT flag=%d nobody on the point", f)
		return
	}

	new Float:dest[3]
	new anchor = bd_pick(f, team, false, dist)
	if (!anchor || !dodx_get_user_origin(anchor, dest)) {
		log_amx("[BD] walkoff ABORT flag=%d no distant team-mate to move to", f)
		return
	}

	new before = bd_zone_count(f, team)
	new mname[32]
	get_user_name(mover, mname, charsmax(mname))

	// Diagnostic-only isolation: unrelated bot combat can otherwise kill a
	// capper between this move and the detector's next poll. Protect only the
	// capping team, and only for the short attribution window.
	new players[32], num
	get_players(players, num)
	for (new i = 0; i < num; i++) {
		new id = players[i]
		if (is_user_connected(id) && get_user_team(id) == team)
			set_entvar(id, var_takedamage, DAMAGE_NO)
	}
	remove_task(BD_TASK_UNPROTECT_BASE + team)
	set_task(BD_WALKOFF_PROTECT_SECS, "bd_unprotect_team",
		BD_TASK_UNPROTECT_BASE + team)

	dodx_set_user_origin(mover, dest)
	log_amx("[BD] walkoff flag=%d mover=%d mname=%s anchor=%d capteam=%d count_before=%d",
		f, mover, mname, anchor, team, before)

	set_task(1.5, "bd_report_after", f)
	return
}

public bd_unprotect_team(taskid) {
	new team = taskid - BD_TASK_UNPROTECT_BASE
	new players[32], num
	get_players(players, num)
	for (new i = 0; i < num; i++) {
		new id = players[i]
		if (is_user_connected(id) && get_user_team(id) == team)
			set_entvar(id, var_takedamage, DAMAGE_AIM)
	}
}

public cmd_walkoff() {
	new arg_flag[8]
	read_argv(1, arg_flag, charsmax(arg_flag))
	bd_execute_walkoff(bd_resolve_flag(arg_flag))
	return PLUGIN_HANDLED
}

/**
 * Arm an in-process walkoff. Polling inside the game removes the scan->RCON
 * race: the same server frame that observes a live capture selects and moves
 * its capper. The old two-command path routinely watched a short capture end
 * between those operations.
 */
public cmd_arm_walkoff() {
	remove_task(BD_TASK_WALKOFF_POLL)
	g_bdWalkoffPolls = 0
	log_amx("[BD] walkoff ARMED")
	set_task(0.1, "bd_walkoff_poll", BD_TASK_WALKOFF_POLL, .flags="b")
	return PLUGIN_HANDLED
}

public bd_walkoff_poll() {
	g_bdWalkoffPolls++
	new f = bd_find_capturing()
	if (f >= 0) {
		new team = dodx_area_get_data(f, CA_capturing_team)
		if (get_gametime() - g_bdLastTeamDeath[team] <
				BD_WALKOFF_DEATH_QUIET_SECS)
			return PLUGIN_HANDLED
		remove_task(BD_TASK_WALKOFF_POLL)
		bd_execute_walkoff(f)
		return PLUGIN_HANDLED
	}

	if (g_bdWalkoffPolls >= BD_WALKOFF_MAX_POLLS) {
		remove_task(BD_TASK_WALKOFF_POLL)
		log_amx("[BD] walkoff ABORT flag=-1 no capture started while armed")
	}
	return PLUGIN_HANDLED
}
