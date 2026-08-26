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
#define BD_TASK_KILL_POLL 77131
#define BD_TASK_RESTART_ARM_POLL 77132
#define BD_TASK_RESTART_POLL 77133
#define BD_TASK_RESTART_FINISH 77134
#define BD_TASK_ISOLATION_HOLD 77135
#define BD_TASK_ISOLATION_END 77136
#define BD_TASK_UNPROTECT_BASE 77140
#define BD_WALKOFF_MAX_POLLS 2400
#define BD_KILL_MAX_POLLS 600
#define BD_FAR_KILL_MAX_POLLS BD_WALKOFF_MAX_POLLS
#define BD_RESTART_MAX_POLLS 60
#define BD_RESTART_TIMER_SECS 1.0
#define BD_BREAK_CANDIDATE_SECS 2.5
#define BD_OFFPOINT_DEATH_QUIET_SECS 4.1
#define BD_KILL_ISOLATION_SECS 7.5
#define BD_WALKOFF_DEATH_QUIET_SECS 5.0
#define BD_WALKOFF_PROTECT_SECS 5.0

new g_bdWalkoffPolls = 0
new g_bdKillPolls = 0
new bool:g_bdKillNear = true
new Float:g_bdLastTeamDeath[3]
new g_bdRestartArmPolls = 0
new g_bdRestartPolls = 0
new g_bdRestartSeq = 0
new g_bdRestartFlag = -1
new g_bdRestartTeam = 0
new g_bdRestartKiller = 0
new g_bdRestartKillerUserid = 0
new g_bdRestartCountBefore = 0
new g_bdRestartCountQueued = 0
new g_bdRestartCountAfter = 0
new g_bdRestartFrozenCount = 0
new g_bdRestartOwnerBefore = 0
new g_bdRestartOwnerAfter = 0
new bool:g_bdRestartActive = false
new bool:g_bdRestartSyntheticDispatch = false
new bool:g_bdRestartRebased = false
new bool:g_bdRestartClockComplete = false
new bool:g_bdRestartContaminated = false
new Float:g_bdRestartRoundBefore = -1.0
new Float:g_bdRestartRoundPeak = -1.0
new Float:g_bdRestartRoundAfter = -1.0
new Float:g_bdRestartRoundLimit = -1.0
new Float:g_bdRestartTimerSaved = -1.0
new Float:g_bdRestartTimerUsed = -1.0
new bool:g_bdRestartTimerPending = false
new g_bdRestartFlagName[32]
new g_bdRestartKillerName[32]
new bool:g_bdIsolationHeld[33]
new bool:g_bdIsolationWasFrozen[33]
new bool:g_bdIsolationWasGodmode[33]
new g_bdIsolationUserid[33]
new bool:g_bdIsolationActive = false

public plugin_init() {
	register_plugin(PLUGIN, VERSION, AUTHOR)
	register_srvcmd("ktp_bd_scan", "cmd_scan")
	register_srvcmd("ktp_bd_kill", "cmd_kill")
	register_srvcmd("ktp_bd_arm_kill", "cmd_arm_kill")
	register_srvcmd("ktp_bd_disarm_kill", "cmd_disarm_kill")
	register_srvcmd("ktp_bd_arm_restart", "cmd_arm_restart")
	register_srvcmd("ktp_bd_clock_preflight", "cmd_clock_preflight")
	register_srvcmd("ktp_bd_walkoff", "cmd_walkoff")
	register_srvcmd("ktp_bd_arm_walkoff", "cmd_arm_walkoff")
	log_amx("[BD] loaded — NOT FOR PRODUCTION")
}

public plugin_end() {
	remove_task(BD_TASK_KILL_POLL)
	remove_task(BD_TASK_WALKOFF_POLL)
	remove_task(BD_TASK_RESTART_ARM_POLL)
	remove_task(BD_TASK_RESTART_POLL)
	remove_task(BD_TASK_RESTART_FINISH)
	bd_end_test_isolation(false)
	bd_restore_restart_timer()
}

public cmd_clock_preflight() {
	new gamerules = dodx_has_gamerules()
	new Float:round_time = dodx_get_round_time()
	new Float:round_limit = get_cvar_float("mp_timelimit") * 60.0

	// server_print is the authoritative one-shot RCON response consumed by the
	// Python harness. The log copy keeps the artifact independently auditable
	// without creating an HLStatsX event or an orphan exception.
	server_print("KTP_BD_CLOCK_PREFLIGHT gamerules=%d round=%.2f limit=%.2f",
		gamerules, round_time, round_limit)
	log_amx("[BD] clock_preflight gamerules=%d round=%.2f limit=%.2f",
		gamerules, round_time, round_limit)
	return PLUGIN_HANDLED
}

public client_death(killer, victim, wpnindex, hitplace, TK) {
	new team = get_user_team(victim)
	if (team == BD_TEAM_ALLIES || team == BD_TEAM_AXIS)
		g_bdLastTeamDeath[team] = get_gametime()

	// The restart scenario dispatches one synthetic death forward without an
	// engine kill. Every other death between queueing and the authoritative
	// restart completion makes attribution ambiguous, so record it and let the
	// harness discard the window rather than invent a detector failure.
	if (g_bdRestartActive && !g_bdRestartSyntheticDispatch) {
		g_bdRestartContaminated = true
		log_amx("[BD] restart_contamination seq=%d kind=death killer=%d victim=%d",
			g_bdRestartSeq, killer, victim)
	}
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

stock bool:bd_flush_stats_capture() {
	if (callfunc_begin("ksc_flush_task", "stats_logging.amxx") != 1)
		return false
	callfunc_end()
	return true
}

stock bd_restore_restart_timer() {
	if (!g_bdRestartTimerPending)
		return
	set_cvar_float("mp_clan_timer", g_bdRestartTimerSaved)
	g_bdRestartTimerPending = false
}

/** Isolate every currently live test player and remember their prior state.
 *
 * FL_FROZEN only stops movement; a frozen bot can still fire and kill another
 * frozen player. FL_GODMODE closes that hole without changing health or using
 * a production plugin API. `bd_hold_test_players` reapplies both bits every
 * 0.1s, including after a respawn resets entity flags.
 */
stock bd_isolate_test_players() {
	new Float:stopped[3]
	new players[32], num
	new isolated = 0
	get_players(players, num)
	for (new i = 0; i < num; i++) {
		new id = players[i]
		if (!is_user_connected(id) || !is_user_alive(id))
			continue

		new flags = get_entvar(id, var_flags)
		g_bdIsolationHeld[id] = true
		g_bdIsolationWasFrozen[id] = bool:(flags & FL_FROZEN)
		g_bdIsolationWasGodmode[id] = bool:(flags & FL_GODMODE)
		g_bdIsolationUserid[id] = get_user_userid(id)
		set_entvar(id, var_velocity, stopped)
		set_entvar(id, var_flags, flags | FL_FROZEN | FL_GODMODE)
		isolated++
	}
	return isolated
}

stock bd_hold_test_players() {
	new Float:stopped[3]
	new players[32], num
	get_players(players, num)
	for (new i = 0; i < num; i++) {
		new id = players[i]
		if (!is_user_connected(id) || !is_user_alive(id))
			continue

		new userid = get_user_userid(id)
		new flags = get_entvar(id, var_flags)
		if (!g_bdIsolationHeld[id] || g_bdIsolationUserid[id] != userid) {
			g_bdIsolationHeld[id] = true
			g_bdIsolationWasFrozen[id] = bool:(flags & FL_FROZEN)
			g_bdIsolationWasGodmode[id] = bool:(flags & FL_GODMODE)
			g_bdIsolationUserid[id] = userid
		}
		set_entvar(id, var_velocity, stopped)
		set_entvar(id, var_flags, flags | FL_FROZEN | FL_GODMODE)
	}
}

/** Remove only the immunity this diagnostic added from the staged victim.
 *
 * This runs in the same call frame immediately before dod_user_kill. The
 * repeating hold task cannot run between these statements. A player that had
 * godmode before isolation keeps it; the diagnostic must never erase state it
 * did not own.
 */
stock bd_allow_isolated_death(id) {
	if (!g_bdIsolationHeld[id] || !is_user_connected(id) ||
			get_user_userid(id) != g_bdIsolationUserid[id] ||
			g_bdIsolationWasGodmode[id])
		return

	new flags = get_entvar(id, var_flags)
	set_entvar(id, var_flags, flags & ~FL_GODMODE)
}

stock bd_begin_test_isolation() {
	bd_end_test_isolation(false)
	g_bdIsolationActive = true
	new isolated = bd_isolate_test_players()
	set_task(0.1, "bd_isolation_hold", BD_TASK_ISOLATION_HOLD, .flags="b")
	return isolated
}

public bd_isolation_hold() {
	if (g_bdIsolationActive)
		bd_hold_test_players()
	return PLUGIN_HANDLED
}

public bd_isolation_end() {
	bd_end_test_isolation(true)
	return PLUGIN_HANDLED
}

stock bd_end_test_isolation(bool:log_end) {
	remove_task(BD_TASK_ISOLATION_HOLD)
	remove_task(BD_TASK_ISOLATION_END)
	g_bdIsolationActive = false
	bd_restore_isolated_players()
	if (log_end)
		log_amx("[BD] isolation END")
}

stock bd_restore_isolated_players() {
	for (new id = 1; id <= 32; id++) {
		if (!g_bdIsolationHeld[id])
			continue
		if (is_user_connected(id) &&
				get_user_userid(id) == g_bdIsolationUserid[id]) {
			new flags = get_entvar(id, var_flags)
			if (g_bdIsolationWasFrozen[id]) flags |= FL_FROZEN
			else flags &= ~FL_FROZEN
			if (g_bdIsolationWasGodmode[id]) flags |= FL_GODMODE
			else flags &= ~FL_GODMODE
			set_entvar(id, var_flags, flags)
		}
		g_bdIsolationHeld[id] = false
		g_bdIsolationWasFrozen[id] = false
		g_bdIsolationWasGodmode[id] = false
		g_bdIsolationUserid[id] = 0
	}
	g_bdRestartFrozenCount = 0
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
stock bool:bd_execute_kill(f, bool:want_near, bool:log_abort = true) {
	new arg_mode[8]
	copy(arg_mode, charsmax(arg_mode), want_near ? "near" : "far")
	if (f < 0) {
		if (log_abort)
			log_amx("[BD] kill ABORT flag=-1 no flag is capturing right now")
		return false
	}
	if (!dodx_area_get_data(f, CA_is_capturing)) {
		if (log_abort)
			log_amx("[BD] kill ABORT flag=%d not capturing", f)
		return false
	}

	new team = dodx_area_get_data(f, CA_capturing_team)
	if (team != BD_TEAM_ALLIES && team != BD_TEAM_AXIS) {
		if (log_abort)
			log_amx("[BD] kill ABORT flag=%d capteam=%d", f, team)
		return false
	}
	// A real capping-team death can leave a legitimate candidate behind for
	// ~2.5s. Never stage the far negative on top of one: the synthetic count
	// change could drain that organic candidate and falsely blame the radius
	// gate. This also catches an organic death in the same server frame.
	if (!want_near && get_gametime() - g_bdLastTeamDeath[team] <
			BD_OFFPOINT_DEATH_QUIET_SECS)
		return false

	new Float:dist = 0.0
	new victim = bd_pick(f, team, want_near, dist)
	if (!victim) {
		if (log_abort)
			log_amx("[BD] kill ABORT flag=%d mode=%s no qualifying player", f, arg_mode)
		return false
	}
	new killer = bd_pick_enemy(team)
	if (!killer) {
		if (log_abort)
			log_amx("[BD] kill ABORT flag=%d no enemy to attribute to", f)
		return false
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
	// Both kill probes need a closed world. For the positive, an unrelated
	// death can change the same count or emit a same-name break; for the far
	// negative it can create the candidate being tested. Selection happens
	// first so isolation never manufactures a qualifying victim or capture.
	new isolated = bd_begin_test_isolation()
	set_task(BD_KILL_ISOLATION_SECS, "bd_isolation_end",
		BD_TASK_ISOLATION_END)
	log_amx("[BD] kill flag=%d capteam=%d mode=%s victim=%d vname=%s killer=%d kname=%s dist=%.0f count_before=%d owner_before=%d isolated=%d",
		f, team, arg_mode, victim, vname, killer, kname, dist, before,
		dodx_area_get_data(f, CA_owning_team), isolated)

	// Dispatch first: the detector reads its baseline here, and the victim has
	// to still be in the zone for that baseline to be the pre-death count.
	dodx_test_dispatch_client_death(killer, victim, 1, 0, 0)
	bd_allow_isolated_death(victim)
	dod_user_kill(victim)

	set_task(1.5, "bd_report_after", f)
	return true
}

public cmd_kill() {
	new arg_flag[8], arg_mode[8]
	read_argv(1, arg_flag, charsmax(arg_flag))
	read_argv(2, arg_mode, charsmax(arg_mode))
	bd_execute_kill(bd_resolve_flag(arg_flag), !equal(arg_mode, "far"))
	return PLUGIN_HANDLED
}

/**
 * Arm a near/far kill inside HLDS and poll until a capture is stageable.
 * Observing and acting in the same game process removes the short-capture
 * RCON race, matching the established ktp_bd_arm_walkoff design.
 */
public cmd_arm_kill() {
	new arg_mode[8]
	read_argv(1, arg_mode, charsmax(arg_mode))
	if (!equal(arg_mode, "near") && !equal(arg_mode, "far")) {
		log_amx("[BD] kill ABORT flag=-1 mode=%s expected near or far", arg_mode)
		return PLUGIN_HANDLED
	}

	// Rearming is an explicit reset boundary.  A prior bounded attempt must
	// never leave its poll count or task alive to shorten the next attempt.
	remove_task(BD_TASK_KILL_POLL)
	g_bdKillNear = bool:equal(arg_mode, "near")
	g_bdKillPolls = 0
	log_amx("[BD] kill ARMED mode=%s", arg_mode)
	set_task(0.1, "bd_kill_poll", BD_TASK_KILL_POLL, .flags="b")
	return PLUGIN_HANDLED
}

public cmd_disarm_kill() {
	remove_task(BD_TASK_KILL_POLL)
	g_bdKillPolls = 0
	server_print("KTP_BD_KILL_DISARMED")
	log_amx("[BD] kill DISARMED")
	return PLUGIN_HANDLED
}

public bd_kill_poll() {
	g_bdKillPolls++
	new f = bd_find_capturing()
	if (f >= 0 && bd_execute_kill(f, g_bdKillNear, false)) {
		remove_task(BD_TASK_KILL_POLL)
		return PLUGIN_HANDLED
	}

	new max_polls = g_bdKillNear ? BD_KILL_MAX_POLLS : BD_FAR_KILL_MAX_POLLS
	if (g_bdKillPolls >= max_polls) {
		remove_task(BD_TASK_KILL_POLL)
		log_amx("[BD] kill ABORT flag=-1 mode=%s no stageable capture while armed",
			g_bdKillNear ? "near" : "far")
	}
	return PLUGIN_HANDLED
}

/**
 * Queue one REAL cap-break candidate, then restart the round without killing
 * or moving its victim.  The ordinary near-kill helper cannot be reused here:
 * its `dod_user_kill` drops the capture count before the restart and therefore
 * cannot prove that a restart-time collapse is what the detector observed.
 *
 * The stats buffer is synchronously drained before the queue marker. This is
 * the evidence boundary: a cap_break generated by earlier organic play must
 * appear before `restart_queue`, never later with a misleading flush-time
 * timestamp. The tested restart is owned here too, so queueing and the engine
 * command happen in one server frame rather than across an RCON race.
 */
stock bool:bd_execute_restart(f) {
	if (f < 0 || !dodx_area_get_data(f, CA_is_capturing))
		return false

	new team = dodx_area_get_data(f, CA_capturing_team)
	if (team != BD_TEAM_ALLIES && team != BD_TEAM_AXIS)
		return false

	new Float:dist = 0.0
	new victim = bd_pick(f, team, true, dist)
	new killer = bd_pick_enemy(team)
	if (!victim || !killer)
		return false
	// A pre-existing break candidate can outlive a stats-buffer flush. Wait
	// past the detector's ~2.5s TTL with no capping-team death so the
	// queue we create below is the only live candidate in the target window.
	new Float:now_game = get_gametime()
	if (now_game - g_bdLastTeamDeath[team] < 3.0)
		return false

	new before = bd_zone_count(f, team)
	new owner = dodx_area_get_data(f, CA_owning_team)
	// Neutral -> neutral is the load-bearing case. An owned point normally
	// changes back to its default owner on restart, which clears the queue via
	// the ordinary owner-change path and never exercises the suspected gap.
	if (owner == BD_TEAM_ALLIES || owner == BD_TEAM_AXIS)
		return false
	owner = 0
	new Float:limit = get_cvar_float("mp_timelimit") * 60.0
	new Float:round_before = dodx_get_round_time()
	new Float:restart_timer = get_cvar_float("mp_clan_timer")
	if (before < 1 || limit <= 0.0 || round_before < 0.0 ||
			restart_timer < 0.99 || restart_timer > 1.01 ||
			restart_timer >= BD_BREAK_CANDIDATE_SECS ||
			round_before > limit + 0.01)
		return false

	// Flush BEFORE observing/dispatching. A successful queue marker therefore
	// certifies that all older buffered capture events precede this window.
	if (!bd_flush_stats_capture()) {
		log_amx("[BD] restart ABORT flag=%d stats capture flush unavailable", f)
		return false
	}

	g_bdRestartSeq++
	g_bdRestartFlag = f
	g_bdRestartTeam = team
	g_bdRestartKiller = killer
	g_bdRestartKillerUserid = get_user_userid(killer)
	g_bdRestartCountBefore = before
	g_bdRestartOwnerBefore = owner
	g_bdRestartRoundBefore = round_before
	g_bdRestartRoundPeak = round_before
	g_bdRestartRoundAfter = round_before
	g_bdRestartRoundLimit = limit
	g_bdRestartPolls = 0
	g_bdRestartRebased = false
	g_bdRestartClockComplete = false
	g_bdRestartContaminated = false
	g_bdRestartActive = true
	// Stop the whole synthetic world during the one-second test countdown.
	// Freezing only the capping team left them exposed to opposing bots and let
	// opponents alter other flag state. The restart poll reapplies this after
	// respawn; the userid guard prevents restoration from touching a reused slot.
	g_bdRestartFrozenCount = bd_begin_test_isolation()

	// Dispatching the DODX death forward is the production-shaped queue input.
	// Deliberately omit dod_user_kill: the live area count must remain unchanged
	// until the engine restart resets the round.
	g_bdRestartSyntheticDispatch = true
	dodx_test_dispatch_client_death(killer, victim, 1, 0, 0)
	g_bdRestartSyntheticDispatch = false
	g_bdRestartCountQueued = bd_zone_count(f, team)

	new vname[32]
	dodx_objective_get_data(f, CP_name, g_bdRestartFlagName,
		charsmax(g_bdRestartFlagName))
	get_user_name(killer, g_bdRestartKillerName,
		charsmax(g_bdRestartKillerName))
	get_user_name(victim, vname, charsmax(vname))
	log_amx("[BD] restart_queue seq=%d flag=%d fname=%s capteam=%d victim=%d vname=%s killer=%d killer_userid=%d kname=%s dist=%.0f count_before=%d count_queued=%d frozen=%d owner_before=%d restart_timer=%.2f round_before=%.2f drained=1",
		g_bdRestartSeq, f, g_bdRestartFlagName, team, victim, vname,
		killer, g_bdRestartKillerUserid, g_bdRestartKillerName,
		dist, before, g_bdRestartCountQueued, g_bdRestartFrozenCount,
		owner, restart_timer,
		round_before)

	if (g_bdRestartCountQueued != before) {
		g_bdRestartContaminated = true
		log_amx("[BD] restart_contamination seq=%d kind=queue_count_change before=%d after=%d",
			g_bdRestartSeq, before, g_bdRestartCountQueued)
	}

	server_cmd("mp_clan_restartround 1")
	server_exec()
	new Float:after_command = dodx_get_round_time()
	if (after_command > g_bdRestartRoundPeak)
		g_bdRestartRoundPeak = after_command
	set_task(0.1, "bd_restart_poll", BD_TASK_RESTART_POLL, .flags="b")
	return true
}

public cmd_arm_restart() {
	if (g_bdRestartActive) {
		log_amx("[BD] restart ABORT flag=%d previous restart probe still active",
			g_bdRestartFlag)
		return PLUGIN_HANDLED
	}

	remove_task(BD_TASK_RESTART_ARM_POLL)
	remove_task(BD_TASK_RESTART_POLL)
	remove_task(BD_TASK_RESTART_FINISH)
	bd_end_test_isolation(false)
	bd_restore_restart_timer()
	g_bdRestartTimerSaved = get_cvar_float("mp_clan_timer")
	g_bdRestartTimerPending = true
	set_cvar_float("mp_clan_timer", BD_RESTART_TIMER_SECS)
	g_bdRestartTimerUsed = get_cvar_float("mp_clan_timer")
	if (g_bdRestartTimerUsed < 0.99 || g_bdRestartTimerUsed > 1.01) {
		log_amx("[BD] restart ABORT flag=-1 could not pin mp_clan_timer to 1")
		bd_restore_restart_timer()
		return PLUGIN_HANDLED
	}
	g_bdRestartArmPolls = 0
	// Normalize the map first. By the time this LAST scenario runs, naturally
	// neutral points have usually been captured and can never exercise 0 -> 0.
	// The poll's round-clock precondition refuses to stage during this setup
	// countdown; only the later, candidate-backed restart is adjudicated.
	log_amx("[BD] restart ARMED preparing neutral reset timer_before=%.2f timer_used=%.2f",
		g_bdRestartTimerSaved, g_bdRestartTimerUsed)
	server_cmd("mp_clan_restartround 1")
	server_exec()
	set_task(0.1, "bd_restart_arm_poll", BD_TASK_RESTART_ARM_POLL, .flags="b")
	return PLUGIN_HANDLED
}

public bd_restart_arm_poll() {
	g_bdRestartArmPolls++
	new n = dodx_objectives_get_num()
	if (n > BD_MAX_FLAGS) n = BD_MAX_FLAGS
	for (new f = 0; f < n; f++) {
		if (bd_execute_restart(f)) {
			remove_task(BD_TASK_RESTART_ARM_POLL)
			return PLUGIN_HANDLED
		}
	}

	if (g_bdRestartArmPolls >= BD_KILL_MAX_POLLS) {
		remove_task(BD_TASK_RESTART_ARM_POLL)
		log_amx("[BD] restart ABORT flag=-1 no stageable capture while armed")
		bd_restore_restart_timer()
	}
	return PLUGIN_HANDLED
}

public bd_restart_poll() {
	g_bdRestartPolls++
	bd_hold_test_players()
	new Float:now = dodx_get_round_time()
	if (now > g_bdRestartRoundPeak)
		g_bdRestartRoundPeak = now

	if (!g_bdRestartRebased &&
			g_bdRestartRoundPeak > g_bdRestartRoundLimit + 0.01 &&
			g_bdRestartRoundPeak > g_bdRestartRoundBefore + 0.01) {
		g_bdRestartRebased = true
		log_amx("[BD] restart_rebase seq=%d round_before=%.2f round_peak=%.2f round_limit=%.2f",
			g_bdRestartSeq, g_bdRestartRoundBefore, g_bdRestartRoundPeak,
			g_bdRestartRoundLimit)
	}

	new count = bd_zone_count(g_bdRestartFlag, g_bdRestartTeam)
	new owner = dodx_area_get_data(g_bdRestartFlag, CA_owning_team)
	if (owner != BD_TEAM_ALLIES && owner != BD_TEAM_AXIS)
		owner = 0
	if (!g_bdRestartClockComplete) {
		if (g_bdRestartRebased && now >= g_bdRestartRoundLimit - 5.0 &&
				now <= g_bdRestartRoundLimit + 0.01) {
			g_bdRestartClockComplete = true
			g_bdRestartRoundAfter = now
			log_amx("[BD] restart_completion seq=%d round_after=%.2f count=%d owner=%d",
				g_bdRestartSeq, now, count, owner)
		} else if ((count != g_bdRestartCountQueued ||
				owner != g_bdRestartOwnerBefore) && !g_bdRestartContaminated) {
			// The engine can reset a multi-player occupancy counter in stages
			// (2 -> 1 -> 0) just before the sampled clock falls back under the
			// limit. All team members were frozen before queueing, so a monotonic
			// post-rebase decline with unchanged neutral ownership is the expected
			// restart transition. Any increase, insufficient freeze coverage, or
			// owner change remains ambiguous and fails closed.
			if (!(g_bdRestartRebased && count >= 0 &&
					count <= g_bdRestartCountQueued &&
					g_bdRestartFrozenCount >= g_bdRestartCountQueued &&
					owner == g_bdRestartOwnerBefore)) {
				g_bdRestartContaminated = true
				log_amx("[BD] restart_contamination seq=%d kind=state_before_completion count=%d owner=%d",
					g_bdRestartSeq, count, owner)
			}
		}
	}

	// The clock transition proves completion; the 0 count proves the engine's
	// restart, rather than ordinary movement, supplied the tested collapse.
	if (g_bdRestartClockComplete && count == 0) {
		g_bdRestartCountAfter = count
		g_bdRestartOwnerAfter = owner
		remove_task(BD_TASK_RESTART_POLL)
		set_task(1.2, "bd_restart_finish", BD_TASK_RESTART_FINISH)
		return PLUGIN_HANDLED
	}

	if (g_bdRestartPolls >= BD_RESTART_MAX_POLLS) {
		g_bdRestartCountAfter = count
		g_bdRestartOwnerAfter = owner
		g_bdRestartRoundAfter = now
		remove_task(BD_TASK_RESTART_POLL)
		bd_restart_finish()
	}
	return PLUGIN_HANDLED
}

public bd_restart_finish() {
	remove_task(BD_TASK_RESTART_ARM_POLL)
	remove_task(BD_TASK_RESTART_POLL)
	remove_task(BD_TASK_RESTART_FINISH)
	// Give stats_logging's 0.5s detector poll two full chances to observe it,
	// then drain it. Every relevant cap_break is now before restart_result;
	// later organic play cannot be mistaken for this candidate.
	new flushed = bd_flush_stats_capture() ? 1 : 0
	log_amx("[BD] restart_result seq=%d flag=%d fname=%s killer=%d killer_userid=%d kname=%s rebase=%d completion=%d restart_timer=%.2f round_before=%.2f round_peak=%.2f round_after=%.2f round_limit=%.2f count_before=%d count_queued=%d count_after=%d frozen=%d owner_before=%d owner_after=%d contaminated=%d flushed=%d",
		g_bdRestartSeq, g_bdRestartFlag, g_bdRestartFlagName,
		g_bdRestartKiller, g_bdRestartKillerUserid, g_bdRestartKillerName,
		g_bdRestartRebased, g_bdRestartClockComplete, g_bdRestartTimerUsed,
		g_bdRestartRoundBefore, g_bdRestartRoundPeak,
		g_bdRestartRoundAfter, g_bdRestartRoundLimit,
		g_bdRestartCountBefore, g_bdRestartCountQueued,
		g_bdRestartCountAfter, g_bdRestartFrozenCount,
		g_bdRestartOwnerBefore,
		g_bdRestartOwnerAfter, g_bdRestartContaminated, flushed)
	g_bdRestartActive = false
	g_bdRestartSyntheticDispatch = false
	bd_end_test_isolation(false)
	bd_restore_restart_timer()
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
