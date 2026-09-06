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
 * ## Capture-area placement
 *
 * The diagnostic reads each real capture area's absolute bounds through
 * ReAPI and places the required number of bots at its three-dimensional
 * centre. Existing 2D control-point distance is used only to recognise the
 * prepared capper while the game updates the real in-zone count.
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
#define BD_ANCHOR_AREA_MARGIN 128.0

#define BD_TEAM_ALLIES 1
#define BD_TEAM_AXIS   2
#define BD_TASK_WALKOFF_POLL 77130
#define BD_TASK_KILL_POLL 77131
#define BD_TASK_RESTART_ARM_POLL 77132
#define BD_TASK_RESTART_POLL 77133
#define BD_TASK_RESTART_FINISH 77134
#define BD_TASK_ISOLATION_HOLD 77135
#define BD_TASK_ISOLATION_END 77136
#define BD_TASK_CLEAN_CAPTURE_POLL 77137
#define BD_TASK_CLEAN_CAPTURE_FINISH 77138
#define BD_TASK_CANONICAL_FRAG_POLL 77139
#define BD_TASK_UNPROTECT_BASE 77140
#define BD_TASK_REPORT_BASE 77200
#define BD_WALKOFF_MAX_POLLS 100
#define BD_KILL_MAX_POLLS 100
#define BD_RESTART_ARM_MAX_POLLS 300
#define BD_FAR_KILL_MAX_POLLS BD_KILL_MAX_POLLS
#define BD_KILL_ACQUIRE_MAX_POLLS 300
#define BD_KILL_ACQUIRE_STABLE_POLLS 5
#define BD_RESTART_MAX_POLLS 60
#define BD_RESTART_TIMER_SECS 1.0
#define BD_RESTART_ARM_IDLE 0
#define BD_RESTART_ARM_NORMALIZING 1
#define BD_RESTART_ARM_STABILIZING 2
#define BD_RESTART_ARM_PREPARED 3
#define BD_RESTART_POSTRESPAWN_STABLE_POLLS 5
#define BD_RESTART_POSITION_EPSILON 1.0
#define BD_BREAK_CANDIDATE_SECS 2.5
#define BD_OFFPOINT_DEATH_QUIET_SECS 4.1
#define BD_KILL_ISOLATION_SECS 7.5
#define BD_WALKOFF_DEATH_QUIET_SECS 5.0
#define BD_WALKOFF_PROTECT_SECS 5.0
#define BD_PREPARED_CAPTURE_SECS 30
#define BD_CLEAN_CAPTURE_SECS 2
#define BD_CLEAN_CAPTURE_MAX_POLLS 120
#define BD_CLEAN_QUIET_SECS 3.0
#define BD_CLEAN_EVIDENCE_SECS 7.0
#define BD_CLEAN_ARM_MAX_POLLS 300
#define BD_CLEAN_TARGET_STABLE_POLLS 5
#define BD_CANONICAL_FRAG_MAX_POLLS 300
#define BD_CANONICAL_STAGE_STABLE_POLLS 5
#define BD_CANONICAL_FRAG_RESTORE_STABLE_POLLS 3
#define BD_CANONICAL_POSTFLUSH_ACK_POLLS 2
#define BD_IN_ATTACK (1<<0)
#define BD_OWNER_ANY -99
#define BD_CANONICAL_WAIT_STAGE 1
#define BD_CANONICAL_WAIT_ENGINE_FRAG 2
#define BD_CANONICAL_WAIT_POSTFLUSH 3
#define BD_CANONICAL_WAIT_RESTORE 4

new g_bdWalkoffPolls = 0
new bool:g_bdWalkoffAcquiring = false
new g_bdWalkoffAcquirePolls = 0
new g_bdWalkoffStablePolls = 0
new g_bdKillPolls = 0
new bool:g_bdKillNear = true
new bool:g_bdKillAcquiring = false
new g_bdKillAcquirePolls = 0
new g_bdKillStablePolls = 0
new Float:g_bdLastTeamDeath[3]
new g_bdRestartArmPolls = 0
new g_bdRestartArmPhase = BD_RESTART_ARM_IDLE
new bool:g_bdRestartNormalizeRebased = false
new Float:g_bdRestartNormalizeRoundBefore = -1.0
new Float:g_bdRestartNormalizeRoundPeak = -1.0
new Float:g_bdRestartNormalizeRoundLimit = -1.0
new g_bdRestartStablePolls = 0
new g_bdRestartStableFlag = -1
new g_bdRestartStableTeam = 0
new g_bdRestartWaitRoster = 0
new g_bdRestartWaitPlan = 0
new g_bdRestartWaitBegin = 0
new g_bdRestartDrops = 0
new g_bdRestartLastDrop = 0
new g_bdRestartRosterCount = 0
new bool:g_bdRestartRosterSelected[33]
new g_bdRestartRosterUserid[33]
new g_bdRestartRosterTeam[33]
new g_bdRestartRosterSpawnStable[33]
new Float:g_bdRestartRosterOrigin[33][3]
new g_bdSpawnGeneration[33]
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
new g_bdIsolationSpawnGeneration[33]
new Float:g_bdIsolationOrigin[33][3]
new bool:g_bdIsolationOriginSaved[33]
new bool:g_bdIsolationActive = false
new g_bdPreparedFlag = -1
new g_bdPreparedTeam = 0
new g_bdPreparedCapTime = 0
new g_bdPreparedMode[16]
new Float:g_bdPreparedAnchor[3]
new bool:g_bdPreparedAnchorSaved = false
new Float:g_bdPreparedCenter[3]
new bool:g_bdPreparedCenterSaved = false
new bool:g_bdCleanActive = false
new bool:g_bdCleanCompleted = false
new bool:g_bdCleanCappersPlaced = false
new Float:g_bdCleanQuietStarted = 0.0
new g_bdCleanPolls = 0
new g_bdCleanFlag = -1
new g_bdCleanTeam = 0
new g_bdCleanOwnerBefore = 0
new g_bdCleanOwnerAfter = 0
new g_bdCleanRequired = 0
new g_bdCleanIsolated = 0
new g_bdCleanRosterCount = 0
new g_bdCleanTeamDeaths = 0
new bool:g_bdCleanContaminated = false
new bool:g_bdCleanRosterSelected[33]
new g_bdCleanRosterUserid[33]
new g_bdCleanRosterTeam[33]
new g_bdCleanRosterSpawn[33]
new bool:g_bdCleanCapperSelected[33]
new g_bdCleanCapperUserid[33]
new g_bdCleanCapperCount = 0
new g_bdCleanCapperUseridList[512]
new g_bdCleanFlagName[32]
new bool:g_bdCleanArming = false
new g_bdCleanArmPolls = 0
new g_bdCleanWaitPlan = 0
new g_bdCleanTargetChanges = 0
new g_bdCleanStablePolls = 0
new g_bdCleanStableFlag = -1
new g_bdCleanStableTeam = 0
new g_bdCleanStableOwner = BD_OWNER_ANY
new bool:g_bdSeriesRosterSelected[33]
new g_bdSeriesRosterUserid[33]
new g_bdSeriesRosterTeam[33]
new g_bdSeriesRosterCount = 0
new bool:g_bdCanonicalActive = false
new g_bdCanonicalPhase = 0
new g_bdCanonicalPolls = 0
new g_bdCanonicalStablePolls = 0
new g_bdCanonicalKiller = 0
new g_bdCanonicalVictim = 0
new g_bdCanonicalKillerUserid = 0
new g_bdCanonicalVictimUserid = 0
new g_bdCanonicalVictimSpawn = 0
new g_bdCanonicalWeapon = 0
new g_bdCanonicalDeathCount = 0
new g_bdCanonicalPrewindowDeaths = 0
new bool:g_bdCanonicalContaminated = false
new bool:g_bdCanonicalPreflushed = false
new bool:g_bdCanonicalPostflushed = false
new bool:g_bdCanonicalVictimHealthSaved = false
new Float:g_bdCanonicalVictimHealth = 0.0
new g_bdUseridEpoch = 0
new g_bdSeriesUseridEpoch = -1
new g_bdActivationEpoch = 0
new bool:g_bdSeriesActive = false

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
	register_srvcmd("ktp_bd_arm_clean_capture", "cmd_arm_clean_capture")
	register_srvcmd("ktp_bd_stage_canonical_frag", "cmd_stage_canonical_frag")
	register_srvcmd("ktp_bd_begin_series", "cmd_begin_series")
	register_srvcmd("ktp_bd_abort_series", "cmd_abort_series")
	register_srvcmd("ktp_bd_end_series", "cmd_end_series")
	register_logevent("bd_lifecycle_log_boundary", 1, "0&KTP_HALF_END")
	register_logevent("bd_lifecycle_log_boundary", 1, "0&KTP_MATCH_END")
	g_bdActivationEpoch = get_systime()
	log_amx("[BD] loaded — NOT FOR PRODUCTION")
}

public plugin_end() {
	if (g_bdSeriesActive)
		bd_abort_series("plugin_end", false)
	else
		bd_cleanup_tasks()
}

public client_putinserver(id) {
	g_bdSpawnGeneration[id] = 0
	g_bdUseridEpoch++
	if (g_bdSeriesActive)
		bd_abort_series("userid_epoch_change", true)
}

public client_disconnected(id) {
	g_bdSpawnGeneration[id] = 0
	g_bdUseridEpoch++
	if (g_bdSeriesActive)
		bd_abort_series("userid_epoch_change", true)
}

// The normalization restart can lower the round clock before DoD has
// respawned the bot roster.  Track the real DODX spawn forward per slot so the
// restart probe can prove that every selected player belongs to the new round
// generation before it freezes or moves anybody.
public dod_client_spawn(id) {
	if (id >= 1 && id <= 32 && is_user_connected(id))
		g_bdSpawnGeneration[id]++
}

public server_changelevel(map[]) {
	if (g_bdSeriesActive)
		bd_abort_series("changelevel", true)
}

// KTPMatchHandler's explicit forwards are the reliable in-process lifecycle
// signals. Its KTP_HALF_END/KTP_MATCH_END log_message output does not reach
// AMXX register_logevent in extension mode; the Python harness still watches
// those lines as an independent fail-closed boundary.
public ktp_half_end(const matchId[], const map[], matchType, half,
		team1Score, team2Score) {
	if (g_bdSeriesActive)
		bd_abort_series("half_end", true)
}

public ktp_match_end(const matchId[], const map[], matchType,
		team1Score, team2Score) {
	if (g_bdSeriesActive)
		bd_abort_series("match_end", true)
}

public bd_lifecycle_log_boundary() {
	if (g_bdSeriesActive)
		bd_abort_series("match_lifecycle_boundary", true)
}

stock bd_reset_restart_arm_state() {
	g_bdRestartArmPhase = BD_RESTART_ARM_IDLE
	g_bdRestartNormalizeRebased = false
	g_bdRestartNormalizeRoundBefore = -1.0
	g_bdRestartNormalizeRoundPeak = -1.0
	g_bdRestartNormalizeRoundLimit = -1.0
	g_bdRestartStablePolls = 0
	g_bdRestartStableFlag = -1
	g_bdRestartStableTeam = 0
	g_bdRestartWaitRoster = 0
	g_bdRestartWaitPlan = 0
	g_bdRestartWaitBegin = 0
	g_bdRestartDrops = 0
	g_bdRestartLastDrop = 0
	g_bdRestartRosterCount = 0
	for (new id = 1; id <= 32; id++) {
		g_bdRestartRosterSelected[id] = false
		g_bdRestartRosterUserid[id] = 0
		g_bdRestartRosterTeam[id] = 0
		g_bdRestartRosterSpawnStable[id] = 0
		for (new axis = 0; axis < 3; axis++)
			g_bdRestartRosterOrigin[id][axis] = 0.0
	}
}

stock bd_reset_clean_state() {
	g_bdCleanActive = false
	g_bdCleanArming = false
	g_bdCleanCompleted = false
	g_bdCleanCappersPlaced = false
	g_bdCleanQuietStarted = 0.0
	g_bdCleanPolls = 0
	g_bdCleanArmPolls = 0
	g_bdCleanWaitPlan = 0
	g_bdCleanTargetChanges = 0
	g_bdCleanStablePolls = 0
	g_bdCleanStableFlag = -1
	g_bdCleanStableTeam = 0
	g_bdCleanStableOwner = BD_OWNER_ANY
	g_bdCleanFlag = -1
	g_bdCleanTeam = 0
	g_bdCleanOwnerBefore = 0
	g_bdCleanOwnerAfter = 0
	g_bdCleanRequired = 0
	g_bdCleanIsolated = 0
	g_bdCleanRosterCount = 0
	g_bdCleanCapperCount = 0
	g_bdCleanTeamDeaths = 0
	g_bdCleanContaminated = false
	g_bdCleanFlagName[0] = 0
	g_bdCleanCapperUseridList[0] = 0
	for (new id = 1; id <= 32; id++) {
		g_bdCleanRosterSelected[id] = false
		g_bdCleanRosterUserid[id] = 0
		g_bdCleanRosterTeam[id] = 0
		g_bdCleanRosterSpawn[id] = 0
		g_bdCleanCapperSelected[id] = false
		g_bdCleanCapperUserid[id] = 0
	}
}

stock bd_reset_series_roster() {
	g_bdSeriesRosterCount = 0
	for (new id = 1; id <= 32; id++) {
		g_bdSeriesRosterSelected[id] = false
		g_bdSeriesRosterUserid[id] = 0
		g_bdSeriesRosterTeam[id] = 0
	}
}

/** Pin every connected combat player for the entire diagnostic series.
 *
 * Death/respawn is expected between scenarios, so spawn generation is checked
 * only by the scenario that owns it.  Membership, userid, and team are exact:
 * a partial live view after an abort can never become a smaller "full" roster.
 */
stock bd_snapshot_series_roster() {
	bd_reset_series_roster()
	for (new id = 1; id <= 32; id++) {
		if (!is_user_connected(id))
			continue
		new team = get_user_team(id)
		if (team != BD_TEAM_ALLIES && team != BD_TEAM_AXIS)
			continue
		g_bdSeriesRosterSelected[id] = true
		g_bdSeriesRosterUserid[id] = get_user_userid(id)
		g_bdSeriesRosterTeam[id] = team
		g_bdSeriesRosterCount++
	}
	return g_bdSeriesRosterCount
}

stock bool:bd_series_roster_current(bool:require_alive) {
	if (g_bdSeriesRosterCount < 2)
		return false
	new seen = 0
	for (new id = 1; id <= 32; id++) {
		if (!is_user_connected(id)) {
			if (g_bdSeriesRosterSelected[id])
				return false
			continue
		}
		new team = get_user_team(id)
		if (!g_bdSeriesRosterSelected[id]) {
			if (team == BD_TEAM_ALLIES || team == BD_TEAM_AXIS)
				return false
			continue
		}
		if (get_user_userid(id) != g_bdSeriesRosterUserid[id] ||
				team != g_bdSeriesRosterTeam[id] ||
				(require_alive && !is_user_alive(id)))
			return false
		seen++
	}
	return seen == g_bdSeriesRosterCount
}

stock bd_series_roster_alive_count() {
	new seen = 0
	for (new id = 1; id <= 32; id++) {
		if (g_bdSeriesRosterSelected[id] && is_user_connected(id) &&
				is_user_alive(id) &&
				get_user_userid(id) == g_bdSeriesRosterUserid[id] &&
				get_user_team(id) == g_bdSeriesRosterTeam[id])
			seen++
	}
	return seen
}

/** One-line objective survey for timeout diagnostics: owner, capturing state,
 * and zone occupancy per flag, so a "no plan" timeout names the disqualifier.
 */
stock bd_log_flag_survey(const mode[]) {
	new n = dodx_objectives_get_num()
	if (n > BD_MAX_FLAGS) n = BD_MAX_FLAGS
	new line[192], cell[32]
	for (new f = 0; f < n; f++) {
		formatex(cell, charsmax(cell), " f%d:o%d c%d z%d/%d", f,
			dodx_area_get_data(f, CA_owning_team),
			dodx_area_get_data(f, CA_is_capturing) ? 1 : 0,
			bd_zone_count(f, BD_TEAM_ALLIES),
			bd_zone_count(f, BD_TEAM_AXIS))
		add(line, charsmax(line), cell)
	}
	log_amx("[BD] %s flag survey:%s", mode, line)
}

stock bool:bd_canonical_series_player_current(id) {
	return g_bdSeriesRosterSelected[id] && is_user_connected(id) &&
		get_user_userid(id) == g_bdSeriesRosterUserid[id] &&
		get_user_team(id) == g_bdSeriesRosterTeam[id]
}

stock bd_canonical_clear_attack() {
	new killer = g_bdCanonicalKiller
	if (killer < 1 || killer > 32 || !is_user_connected(killer) ||
			get_user_userid(killer) != g_bdCanonicalKillerUserid)
		return
	new buttons = get_entvar(killer, var_button)
	new oldbuttons = get_entvar(killer, var_oldbuttons)
	set_entvar(killer, var_button, buttons & ~BD_IN_ATTACK)
	set_entvar(killer, var_oldbuttons, oldbuttons & ~BD_IN_ATTACK)
}

/** Put the attacker back on its isolation snapshot once the one factual death
 * has been observed.  The engine callback is the closed evidence boundary;
 * leaving the attacker at an objective centre while waiting for the victim's
 * respawn can let a map world trigger create a second, foreign death before
 * RESULT.  This restores only position, while the isolation hold continues to
 * own freeze and godmode until the exact roster is proven stable again.
 */
stock bool:bd_restore_canonical_killer_origin() {
	new killer = g_bdCanonicalKiller
	if (killer < 1 || killer > 32 || !is_user_connected(killer) ||
			get_user_userid(killer) != g_bdCanonicalKillerUserid ||
			!g_bdIsolationHeld[killer] ||
			g_bdIsolationUserid[killer] != g_bdCanonicalKillerUserid ||
			!g_bdIsolationOriginSaved[killer])
		return false
	return bool:dodx_set_user_origin(killer, g_bdIsolationOrigin[killer])
}

stock bd_canonical_restore_victim_health() {
	new victim = g_bdCanonicalVictim
	if (g_bdCanonicalVictimHealthSaved && victim >= 1 && victim <= 32 &&
			is_user_connected(victim) && is_user_alive(victim) &&
			get_user_userid(victim) == g_bdCanonicalVictimUserid &&
			g_bdSpawnGeneration[victim] == g_bdCanonicalVictimSpawn)
		set_entvar(victim, var_health, g_bdCanonicalVictimHealth)
	g_bdCanonicalVictimHealthSaved = false
	g_bdCanonicalVictimHealth = 0.0
}

stock bd_reset_canonical_state() {
	bd_canonical_clear_attack()
	bd_canonical_restore_victim_health()
	g_bdCanonicalActive = false
	g_bdCanonicalPhase = 0
	g_bdCanonicalPolls = 0
	g_bdCanonicalStablePolls = 0
	g_bdCanonicalKiller = 0
	g_bdCanonicalVictim = 0
	g_bdCanonicalKillerUserid = 0
	g_bdCanonicalVictimUserid = 0
	g_bdCanonicalVictimSpawn = 0
	g_bdCanonicalWeapon = 0
	g_bdCanonicalDeathCount = 0
	g_bdCanonicalPrewindowDeaths = 0
	g_bdCanonicalContaminated = false
	g_bdCanonicalPreflushed = false
	g_bdCanonicalPostflushed = false
}

stock bd_cleanup_tasks() {
	remove_task(BD_TASK_KILL_POLL)
	remove_task(BD_TASK_WALKOFF_POLL)
	remove_task(BD_TASK_RESTART_ARM_POLL)
	remove_task(BD_TASK_RESTART_POLL)
	remove_task(BD_TASK_RESTART_FINISH)
	remove_task(BD_TASK_CLEAN_CAPTURE_POLL)
	remove_task(BD_TASK_CLEAN_CAPTURE_FINISH)
	remove_task(BD_TASK_CANONICAL_FRAG_POLL)
	g_bdKillPolls = 0
	g_bdKillAcquiring = false
	g_bdKillAcquirePolls = 0
	g_bdKillStablePolls = 0
	g_bdWalkoffPolls = 0
	g_bdWalkoffAcquiring = false
	g_bdWalkoffAcquirePolls = 0
	g_bdWalkoffStablePolls = 0
	g_bdRestartArmPolls = 0
	g_bdRestartPolls = 0
	g_bdRestartActive = false
	g_bdRestartSyntheticDispatch = false
	for (new team = BD_TEAM_ALLIES; team <= BD_TEAM_AXIS; team++) {
		new taskid = BD_TASK_UNPROTECT_BASE + team
		if (task_exists(taskid)) {
			remove_task(taskid)
			bd_unprotect_team(taskid)
		}
	}
	for (new f = 0; f < BD_MAX_FLAGS; f++)
		remove_task(BD_TASK_REPORT_BASE + f)
	bd_end_test_isolation(false)
	bd_restore_restart_timer()
	bd_reset_restart_arm_state()
	bd_reset_clean_state()
	bd_reset_canonical_state()
	bd_reset_series_roster()
}

stock bd_abort_series(const reason[], bool:log_abort) {
	g_bdSeriesActive = false
	bd_cleanup_tasks()
	if (log_abort)
		log_amx("[BD] series ABORT reason=%s", reason)
}

stock bool:bd_series_guard(const command[]) {
	if (!g_bdSeriesActive) {
		log_amx("[BD] series ABORT reason=inactive command=%s", command)
		return false
	}
	if (g_bdUseridEpoch != g_bdSeriesUseridEpoch) {
		bd_abort_series("userid_epoch_change", true)
		return false
	}
	if (!bd_series_roster_current(false)) {
		bd_abort_series("combat_roster_change", true)
		return false
	}
	return true
}

public cmd_begin_series() {
	g_bdSeriesActive = false
	bd_cleanup_tasks()
	g_bdSeriesUseridEpoch = g_bdUseridEpoch
	if (bd_snapshot_series_roster() < 2) {
		log_amx("[BD] series ABORT reason=insufficient_combat_roster")
		server_print("KTP_BD_SERIES_ABORTED reason=insufficient_combat_roster")
		return PLUGIN_HANDLED
	}
	g_bdSeriesActive = true
	server_print("KTP_BD_SERIES_BEGUN activation=%d userid_epoch=%d roster=%d",
		g_bdActivationEpoch, g_bdSeriesUseridEpoch, g_bdSeriesRosterCount)
	log_amx("[BD] series BEGIN activation=%d userid_epoch=%d roster=%d",
		g_bdActivationEpoch, g_bdSeriesUseridEpoch, g_bdSeriesRosterCount)
	return PLUGIN_HANDLED
}

public cmd_abort_series() {
	new reason[48]
	read_argv(1, reason, charsmax(reason))
	if (!reason[0]) copy(reason, charsmax(reason), "harness_request")
	bd_abort_series(reason, true)
	server_print("KTP_BD_SERIES_ABORTED reason=%s", reason)
	return PLUGIN_HANDLED
}

public cmd_end_series() {
	g_bdSeriesActive = false
	bd_cleanup_tasks()
	server_print("KTP_BD_SERIES_ENDED")
	log_amx("[BD] series END")
	return PLUGIN_HANDLED
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

stock bool:bd_pick_canonical_frag_pair(&killer, &victim) {
	killer = 0
	victim = 0
	for (new attacker = 1; attacker <= 32; attacker++) {
		if (!g_bdSeriesRosterSelected[attacker] ||
				!is_user_connected(attacker) || !is_user_alive(attacker) ||
				!g_bdIsolationHeld[attacker] ||
				g_bdIsolationWasGodmode[attacker] ||
				g_bdIsolationWasFrozen[attacker] ||
				dod_get_user_weapon(attacker) <= 0)
			continue
		for (new target = 1; target <= 32; target++) {
			if (!g_bdSeriesRosterSelected[target] || target == attacker ||
					!is_user_connected(target) || !is_user_alive(target) ||
					!g_bdIsolationHeld[target] ||
					g_bdIsolationWasGodmode[target] ||
					g_bdSeriesRosterTeam[target] ==
						g_bdSeriesRosterTeam[attacker])
				continue
			killer = attacker
			victim = target
			return true
		}
	}
	return false
}

/** Put one opposing pair in a known open trigger volume.
 *
 * The same real capture-area centres drive the established BreakDrive
 * scenarios.  ReAPI/DODX positioning and view-angle natives are already part
 * of the Lane B runtime.  No damage or death forward is dispatched here: the
 * bot must fire its actual weapon through the game DLL.
 */
stock bool:bd_prepare_canonical_frag_pair(killer, victim) {
	new n = dodx_objectives_get_num()
	if (n > BD_MAX_FLAGS) n = BD_MAX_FLAGS
	new Float:center[3], Float:killer_origin[3], Float:victim_origin[3]
	new bool:have_center = false
	for (new f = 0; f < n; f++) {
		if (!bd_area_center(f, center))
			continue
		have_center = true
		break
	}
	if (!have_center)
		return false

	for (new axis = 0; axis < 3; axis++) {
		killer_origin[axis] = center[axis]
		victim_origin[axis] = center[axis]
	}
	// Forty-eight units keeps the target inside an ordinary melee swing as
	// well as a gun trace, while avoiding identical overlapping origins.
	killer_origin[0] -= 24.0
	victim_origin[0] += 24.0
	if (!dodx_set_user_origin(killer, killer_origin) ||
			!dodx_set_user_origin(victim, victim_origin))
		return false

	new Float:killer_angles[3], Float:victim_angles[3]
	killer_angles[0] = 0.0
	killer_angles[1] = 0.0
	killer_angles[2] = 0.0
	victim_angles[0] = 0.0
	victim_angles[1] = 180.0
	victim_angles[2] = 0.0
	if (!dodx_set_user_angles(killer, killer_angles) ||
			!dodx_set_user_angles(victim, victim_angles))
		return false

	g_bdCanonicalVictimHealth = get_entvar(victim, var_health)
	g_bdCanonicalVictimHealthSaved = true
	set_entvar(victim, var_health, 1.0)
	return true
}

/** The hold task protects every player except this one exact victim. */
stock bd_allow_canonical_victim_damage() {
	new victim = g_bdCanonicalVictim
	if (!g_bdCanonicalActive ||
			g_bdCanonicalPhase != BD_CANONICAL_WAIT_ENGINE_FRAG ||
			victim < 1 || victim > 32 || !is_user_connected(victim) ||
			!is_user_alive(victim) ||
			get_user_userid(victim) != g_bdCanonicalVictimUserid ||
			g_bdSpawnGeneration[victim] != g_bdCanonicalVictimSpawn)
		return
	new flags = get_entvar(victim, var_flags)
	set_entvar(victim, var_flags, (flags | FL_FROZEN) & ~FL_GODMODE)
}

/** Drive actual bot weapon input; the game DLL still owns hit/death facts.
 *
 * ReHLDS deliberately zeros every usercmd button while FL_FROZEN is set, so
 * the one selected attacker must be the sole movement-lock exception during
 * this phase.  It remains godmode-protected and is velocity-stopped here on
 * every poll. Every other player is both frozen and protected; the exact
 * victim stays frozen and is the only damageable player. Thus no unrelated
 * organic frag can enter the closed factual window.
 */
stock bd_drive_canonical_attacker() {
	new killer = g_bdCanonicalKiller
	if (!g_bdCanonicalActive ||
			g_bdCanonicalPhase != BD_CANONICAL_WAIT_ENGINE_FRAG ||
			killer < 1 || killer > 32 || !is_user_connected(killer) ||
			!is_user_alive(killer) ||
			get_user_userid(killer) != g_bdCanonicalKillerUserid)
		return
	new Float:angles[3]
	new Float:stopped[3]
	angles[0] = 0.0
	angles[1] = 0.0
	angles[2] = 0.0
	set_entvar(killer, var_velocity, stopped)
	new flags = get_entvar(killer, var_flags)
	set_entvar(killer, var_flags, (flags | FL_GODMODE) & ~FL_FROZEN)
	dodx_set_user_angles(killer, angles)
	new buttons = get_entvar(killer, var_button)
	new oldbuttons = get_entvar(killer, var_oldbuttons)
	set_entvar(killer, var_oldbuttons, oldbuttons & ~BD_IN_ATTACK)
	set_entvar(killer, var_button, buttons | BD_IN_ATTACK)
}

stock bd_canonical_frag_abort(const reason[]) {
	remove_task(BD_TASK_CANONICAL_FRAG_POLL)
	log_amx("[BD] canonical_frag ABORT %s", reason)
	bd_reset_canonical_state()
	if (g_bdIsolationActive)
		bd_end_test_isolation(true)
}

/** Stage one real engine frag, then hand the next scenario a complete world.
 *
 * The exact full roster is frozen first, so no organic kill can enter this
 * diagnostic window. One protected bot is aimed at one opposing 1-HP victim;
 * it is the only temporarily unfrozen bot, only that victim loses the
 * diagnostic's godmode, and the bot's actual engine attack input must produce
 * the kill. The product buffer is flushed before BEGIN and synchronously again
 * after the exact DODX death callback. This diagnostic never prints a killed
 * or frag_context product fact itself.
 */
public cmd_stage_canonical_frag() {
	if (!bd_series_guard("stage_canonical_frag"))
		return PLUGIN_HANDLED
	if (g_bdCanonicalActive || g_bdIsolationActive) {
		log_amx("[BD] canonical_frag ABORT mutator already active")
		return PLUGIN_HANDLED
	}
	bd_reset_canonical_state()
	g_bdCanonicalActive = true
	g_bdCanonicalPhase = BD_CANONICAL_WAIT_STAGE
	new acquired = bd_begin_test_isolation()
	log_amx("[BD] canonical_frag ARMED roster=%d acquired=%d",
		g_bdSeriesRosterCount, acquired)
	set_task(0.1, "bd_canonical_frag_poll",
		BD_TASK_CANONICAL_FRAG_POLL, .flags="b")
	return PLUGIN_HANDLED
}

public bd_canonical_frag_poll() {
	if (!g_bdCanonicalActive)
		return PLUGIN_HANDLED
	if (!bd_series_guard("canonical_frag_poll"))
		return PLUGIN_HANDLED
	if (++g_bdCanonicalPolls >= BD_CANONICAL_FRAG_MAX_POLLS) {
		bd_canonical_frag_abort("full live roster was unavailable before deadline")
		return PLUGIN_HANDLED
	}

	if (g_bdCanonicalPhase == BD_CANONICAL_WAIT_STAGE) {
		// Acquire the pinned roster progressively. A member may be dead when the
		// command arrives; every other exact live userid is protected at once,
		// and the hold task acquires the missing member on its next spawn.
		bd_hold_test_players()
		if (!bd_series_roster_current(true) ||
				!bd_isolation_exact_series()) {
			g_bdCanonicalStablePolls = 0
			return PLUGIN_HANDLED
		}
		if (++g_bdCanonicalStablePolls <
				BD_CANONICAL_STAGE_STABLE_POLLS)
			return PLUGIN_HANDLED

		new killer, victim
		if (!bd_pick_canonical_frag_pair(killer, victim))
			return PLUGIN_HANDLED

		g_bdCanonicalKiller = killer
		g_bdCanonicalVictim = victim
		g_bdCanonicalKillerUserid = get_user_userid(killer)
		g_bdCanonicalVictimUserid = get_user_userid(victim)
		g_bdCanonicalVictimSpawn = g_bdSpawnGeneration[victim]

		new isolated = bd_isolation_count()
		if (isolated != g_bdSeriesRosterCount ||
				!bd_isolation_exact_series() ||
				!bd_series_roster_current(true)) {
			bd_canonical_frag_abort("could not freeze the exact live roster")
			return PLUGIN_HANDLED
		}
		if (!bd_prepare_canonical_frag_pair(killer, victim)) {
			bd_canonical_frag_abort("could not stage the factual engine pair")
			return PLUGIN_HANDLED
		}
		if (!bd_flush_stats_capture()) {
			bd_canonical_frag_abort("stats capture preflush unavailable")
			return PLUGIN_HANDLED
		}
		// The preflush is the evidence boundary. Organic deaths while the
		// initially partial roster was being acquired are deliberately outside
		// it; reset only the strict factual-window counters immediately before
		// BEGIN. Every death after BEGIN remains exact-or-contaminated below.
		g_bdCanonicalDeathCount = 0
		g_bdCanonicalWeapon = 0
		g_bdCanonicalContaminated = false
		g_bdCanonicalPreflushed = true
		log_amx("[BD] canonical_frag BEGIN killer=%d killer_userid=%d victim=%d victim_userid=%d roster=%d isolated=%d preflushed=1 prewindow_deaths=%d",
			killer, g_bdCanonicalKillerUserid, victim,
			g_bdCanonicalVictimUserid, g_bdSeriesRosterCount, isolated,
			g_bdCanonicalPrewindowDeaths)
		g_bdCanonicalPhase = BD_CANONICAL_WAIT_ENGINE_FRAG
		g_bdCanonicalStablePolls = 0
		bd_allow_canonical_victim_damage()
		bd_drive_canonical_attacker()
		return PLUGIN_HANDLED
	}

	if (g_bdCanonicalContaminated) {
		bd_canonical_frag_abort("factual frag window contained a foreign death")
		return PLUGIN_HANDLED
	}
	if (g_bdCanonicalPhase == BD_CANONICAL_WAIT_ENGINE_FRAG) {
		if (!is_user_alive(g_bdCanonicalVictim)) {
			bd_canonical_frag_abort("victim died without the exact DODX callback")
			return PLUGIN_HANDLED
		}
		bd_allow_canonical_victim_damage()
		bd_drive_canonical_attacker()
		return PLUGIN_HANDLED
	}
	if (g_bdCanonicalPhase == BD_CANONICAL_WAIT_POSTFLUSH) {
		bd_canonical_clear_attack()
		if (g_bdCanonicalDeathCount != 1 ||
				g_bdCanonicalWeapon <= 0) {
			bd_canonical_frag_abort("exact factual death did not reconcile")
			return PLUGIN_HANDLED
		}
		if (!g_bdCanonicalPostflushed) {
			if (!bd_flush_stats_capture()) {
				bd_canonical_frag_abort("stats capture postflush unavailable")
				return PLUGIN_HANDLED
			}
			g_bdCanonicalPostflushed = true
			g_bdCanonicalStablePolls = 0
			log_amx("[BD] canonical_frag POSTFLUSH killer=%d killer_userid=%d victim=%d victim_userid=%d weapon=%d death_count=1 flush_ack=1",
				g_bdCanonicalKiller, g_bdCanonicalKillerUserid,
				g_bdCanonicalVictim, g_bdCanonicalVictimUserid,
				g_bdCanonicalWeapon)
			return PLUGIN_HANDLED
		}
		if (++g_bdCanonicalStablePolls < BD_CANONICAL_POSTFLUSH_ACK_POLLS)
			return PLUGIN_HANDLED
		log_amx("[BD] canonical_frag FACT killer=%d killer_userid=%d victim=%d victim_userid=%d weapon=%d death_observed=1 preflushed=1 postflushed=1",
			g_bdCanonicalKiller, g_bdCanonicalKillerUserid,
			g_bdCanonicalVictim, g_bdCanonicalVictimUserid,
			g_bdCanonicalWeapon)
		g_bdCanonicalPhase = BD_CANONICAL_WAIT_RESTORE
		g_bdCanonicalStablePolls = 0
		return PLUGIN_HANDLED
	}

	if (g_bdCanonicalPhase != BD_CANONICAL_WAIT_RESTORE ||
			!g_bdCanonicalPreflushed || !g_bdCanonicalPostflushed ||
			g_bdCanonicalDeathCount != 1 || !g_bdIsolationActive ||
			!bd_series_roster_current(true) ||
			!bd_isolation_exact_series() ||
			!is_user_connected(g_bdCanonicalVictim) ||
			get_user_userid(g_bdCanonicalVictim) !=
				g_bdCanonicalVictimUserid ||
			g_bdSpawnGeneration[g_bdCanonicalVictim] <=
				g_bdCanonicalVictimSpawn) {
		g_bdCanonicalStablePolls = 0
		return PLUGIN_HANDLED
	}
	if (++g_bdCanonicalStablePolls <
			BD_CANONICAL_FRAG_RESTORE_STABLE_POLLS)
		return PLUGIN_HANDLED

	new isolated = bd_isolation_count()
	if (isolated != g_bdSeriesRosterCount ||
			!bd_series_roster_current(true) ||
			!bd_isolation_exact_series()) {
		bd_canonical_frag_abort("exact restored roster was not still frozen")
		return PLUGIN_HANDLED
	}
	remove_task(BD_TASK_CANONICAL_FRAG_POLL)
	log_amx("[BD] canonical_frag RESULT killer=%d killer_userid=%d victim=%d victim_userid=%d roster=%d isolated=%d respawned=1 death_count=1 preflushed=1 postflushed=1",
		g_bdCanonicalKiller, g_bdCanonicalKillerUserid,
		g_bdCanonicalVictim, g_bdCanonicalVictimUserid,
		g_bdSeriesRosterCount, isolated)
	bd_reset_canonical_state()
	return PLUGIN_HANDLED
}

public client_death(killer, victim, wpnindex, hitplace, TK) {
	if (g_bdCanonicalActive) {
		if (g_bdCanonicalPhase == BD_CANONICAL_WAIT_STAGE) {
			// This is before the preflush/BEGIN evidence boundary. It may happen
			// while a pinned dead member is respawning; retain it only as an
			// auditable pre-window count and continue progressive acquisition.
			g_bdCanonicalPrewindowDeaths++
		} else {
			g_bdCanonicalDeathCount++
			if (g_bdCanonicalPhase == BD_CANONICAL_WAIT_ENGINE_FRAG &&
				g_bdCanonicalDeathCount == 1 &&
				killer == g_bdCanonicalKiller &&
				victim == g_bdCanonicalVictim &&
				is_user_connected(killer) && is_user_connected(victim) &&
				get_user_userid(killer) == g_bdCanonicalKillerUserid &&
				get_user_userid(victim) == g_bdCanonicalVictimUserid &&
				wpnindex > 0 && !TK) {
			g_bdCanonicalWeapon = wpnindex
			g_bdCanonicalPhase = BD_CANONICAL_WAIT_POSTFLUSH
			g_bdCanonicalStablePolls = 0
			bd_canonical_clear_attack()
			if (!bd_restore_canonical_killer_origin())
				g_bdCanonicalContaminated = true
			} else {
				g_bdCanonicalContaminated = true
			}
		}
	}

	new team = get_user_team(victim)
	if (team == BD_TEAM_ALLIES || team == BD_TEAM_AXIS)
		g_bdLastTeamDeath[team] = get_gametime()
	if (g_bdCleanActive &&
			(team == BD_TEAM_ALLIES || team == BD_TEAM_AXIS)) {
		if (team == g_bdCleanTeam)
			g_bdCleanTeamDeaths++
		g_bdCleanContaminated = true
		log_amx("[BD] clean_capture contamination kind=death killer=%d victim=%d team=%d",
			killer, victim, team)
	}

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
		if (g_bdCanonicalActive &&
				!bd_canonical_series_player_current(id))
			continue

		new flags = get_entvar(id, var_flags)
		g_bdIsolationHeld[id] = true
		g_bdIsolationWasFrozen[id] = bool:(flags & FL_FROZEN)
		g_bdIsolationWasGodmode[id] = bool:(flags & FL_GODMODE)
		g_bdIsolationUserid[id] = get_user_userid(id)
		g_bdIsolationSpawnGeneration[id] = g_bdSpawnGeneration[id]
		g_bdIsolationOriginSaved[id] = bool:dodx_get_user_origin(id,
			g_bdIsolationOrigin[id])
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
		if (g_bdCanonicalActive &&
				!bd_canonical_series_player_current(id))
			continue

		new userid = get_user_userid(id)
		new flags = get_entvar(id, var_flags)
		if (!g_bdIsolationHeld[id] || g_bdIsolationUserid[id] != userid ||
				g_bdIsolationSpawnGeneration[id] != g_bdSpawnGeneration[id]) {
			g_bdIsolationHeld[id] = true
			g_bdIsolationWasFrozen[id] = bool:(flags & FL_FROZEN)
			g_bdIsolationWasGodmode[id] = bool:(flags & FL_GODMODE)
			g_bdIsolationUserid[id] = userid
			g_bdIsolationSpawnGeneration[id] = g_bdSpawnGeneration[id]
			g_bdIsolationOriginSaved[id] = bool:dodx_get_user_origin(id,
				g_bdIsolationOrigin[id])
		}
		set_entvar(id, var_velocity, stopped)
		new held_flags = flags | FL_FROZEN | FL_GODMODE
		if (g_bdCanonicalActive &&
				g_bdCanonicalPhase == BD_CANONICAL_WAIT_ENGINE_FRAG &&
				g_bdSpawnGeneration[id] == g_bdIsolationSpawnGeneration[id]) {
			if (id == g_bdCanonicalKiller &&
					userid == g_bdCanonicalKillerUserid)
				held_flags &= ~FL_FROZEN
			else if (id == g_bdCanonicalVictim &&
					userid == g_bdCanonicalVictimUserid &&
					g_bdSpawnGeneration[id] == g_bdCanonicalVictimSpawn)
				held_flags &= ~FL_GODMODE
		}
		set_entvar(id, var_flags, held_flags)
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
			g_bdSpawnGeneration[id] != g_bdIsolationSpawnGeneration[id] ||
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

stock bd_isolation_count() {
	new count = 0
	for (new id = 1; id <= 32; id++) {
		if (g_bdIsolationHeld[id] && is_user_connected(id) &&
				get_user_userid(id) == g_bdIsolationUserid[id] &&
				g_bdSpawnGeneration[id] == g_bdIsolationSpawnGeneration[id])
			count++
	}
	return count
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
	bd_restore_prepared_capture()
	if (log_end)
		log_amx("[BD] isolation END")
}

stock bd_restore_isolated_players() {
	for (new id = 1; id <= 32; id++) {
		if (!g_bdIsolationHeld[id])
			continue
		if (is_user_connected(id) &&
				get_user_userid(id) == g_bdIsolationUserid[id] &&
				g_bdSpawnGeneration[id] == g_bdIsolationSpawnGeneration[id]) {
			if (g_bdIsolationOriginSaved[id] && is_user_alive(id))
				dodx_set_user_origin(id, g_bdIsolationOrigin[id])
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
		g_bdIsolationSpawnGeneration[id] = 0
		g_bdIsolationOriginSaved[id] = false
	}
	g_bdRestartFrozenCount = 0
}

stock bd_restore_prepared_capture() {
	if (g_bdPreparedFlag >= 0)
		dodx_area_set_data(g_bdPreparedFlag, CA_timetocap,
			g_bdPreparedCapTime)
	g_bdPreparedFlag = -1
	g_bdPreparedTeam = 0
	g_bdPreparedCapTime = 0
	g_bdPreparedMode[0] = 0
	g_bdPreparedAnchorSaved = false
	g_bdPreparedCenterSaved = false
	for (new axis = 0; axis < 3; axis++) {
		g_bdPreparedAnchor[axis] = 0.0
		g_bdPreparedCenter[axis] = 0.0
	}
}

stock bool:bd_area_center(f, Float:center[3]) {
	new area = dodx_area_get_data(f, CA_edict)
	if (area <= 0)
		return false
	new Float:mins[3], Float:maxs[3]
	get_entvar(area, var_absmin, mins)
	get_entvar(area, var_absmax, maxs)
	for (new axis = 0; axis < 3; axis++) {
		if (maxs[axis] <= mins[axis])
			return false
		center[axis] = (mins[axis] + maxs[axis]) * 0.5
	}
	return true
}

stock bd_live_team_count(team) {
	new players[32], num, count = 0
	get_players(players, num)
	for (new i = 0; i < num; i++) {
		new id = players[i]
		if (is_user_connected(id) && is_user_alive(id) &&
				get_user_team(id) == team)
			count++
	}
	return count
}

/** Require that the held live set is exactly the frozen pinned series set. */
stock bool:bd_isolation_exact_series() {
	if (!g_bdIsolationActive || g_bdSeriesRosterCount < 2 ||
			bd_isolation_count() != g_bdSeriesRosterCount)
		return false

	new exact = 0
	for (new id = 1; id <= 32; id++) {
		if (!g_bdSeriesRosterSelected[id]) {
			if (g_bdIsolationHeld[id] && is_user_connected(id) &&
					is_user_alive(id) &&
					get_user_userid(id) == g_bdIsolationUserid[id] &&
					g_bdSpawnGeneration[id] ==
						g_bdIsolationSpawnGeneration[id])
				return false
			continue
		}
		if (!is_user_connected(id) || !is_user_alive(id) ||
				get_user_userid(id) != g_bdSeriesRosterUserid[id] ||
				get_user_team(id) != g_bdSeriesRosterTeam[id] ||
				!g_bdIsolationHeld[id] ||
				g_bdIsolationUserid[id] != g_bdSeriesRosterUserid[id] ||
				g_bdIsolationSpawnGeneration[id] != g_bdSpawnGeneration[id])
			return false
		new flags = get_entvar(id, var_flags)
		if (!(flags & FL_FROZEN) || !(flags & FL_GODMODE))
			return false
		exact++
	}
	return exact == g_bdSeriesRosterCount
}

stock bool:bd_owner_canonical(owner) {
	return owner == 0 || owner == BD_TEAM_ALLIES || owner == BD_TEAM_AXIS
}

/** A shared isolation anchor must not accidentally stage a second objective. */
stock bool:bd_anchor_outside_capture_areas(const Float:origin[3]) {
	new n = dodx_objectives_get_num()
	if (n > BD_MAX_FLAGS) n = BD_MAX_FLAGS
	for (new f = 0; f < n; f++) {
		new area = dodx_area_get_data(f, CA_edict)
		if (area <= 0)
			continue
		new Float:mins[3], Float:maxs[3]
		get_entvar(area, var_absmin, mins)
		get_entvar(area, var_absmax, maxs)
		new bool:inside = true
		for (new axis = 0; axis < 3; axis++) {
			if (maxs[axis] <= mins[axis])
				return false
			if (origin[axis] < mins[axis] - BD_ANCHOR_AREA_MARGIN ||
					origin[axis] > maxs[axis] + BD_ANCHOR_AREA_MARGIN)
				inside = false
		}
		if (inside)
			return false
	}
	return true
}

stock bd_far_anchor(const Float:center[3], Float:anchor[3]) {
	new players[32], num, best = 0
	new Float:best_dist = 0.0, Float:origin[3]
	get_players(players, num)
	for (new i = 0; i < num; i++) {
		new id = players[i]
		if (!is_user_connected(id) || !is_user_alive(id) ||
				!dodx_get_user_origin(id, origin) ||
				!bd_anchor_outside_capture_areas(origin))
			continue
		new Float:dist = bd_dist2d(origin, center)
		if (dist >= BD_FAR_RADIUS && dist > best_dist) {
			best = id
			best_dist = dist
			for (new axis = 0; axis < 3; axis++)
				anchor[axis] = origin[axis]
		}
	}
	return best
}

/** A known walkable origin outside every objective.  Near diagnostics only
 * need to clear the selected capture zone; requiring a far-away bot there
 * makes a perfectly valid capture unstageable while a new round's roster is
 * still clustered at spawn.  Keep the radius requirement in bd_far_anchor()
 * for the one probe whose assertion actually depends on off-point distance.
 */
stock bd_safe_anchor(Float:anchor[3]) {
	new players[32], num, Float:origin[3]
	get_players(players, num)
	for (new i = 0; i < num; i++) {
		new id = players[i]
		if (!is_user_connected(id) || !is_user_alive(id) ||
				!dodx_get_user_origin(id, origin) ||
				!bd_anchor_outside_capture_areas(origin))
			continue
		for (new axis = 0; axis < 3; axis++)
			anchor[axis] = origin[axis]
		return id
	}
	return 0
}

/** Pin the combat roster before the neutralizing restart is issued.
 *
 * A slot is relevant when it is connected and assigned to a combat team at
 * arm time.  The series-level userid epoch guard protects membership, while
 * the per-slot spawn baseline below proves that the same player has respawned
 * into the normalized round before staging begins.
 */
stock bd_snapshot_restart_roster() {
	g_bdRestartRosterCount = 0
	for (new id = 1; id <= 32; id++) {
		g_bdRestartRosterSelected[id] = false
		g_bdRestartRosterUserid[id] = 0
		g_bdRestartRosterTeam[id] = 0
		g_bdRestartRosterSpawnStable[id] = 0
	}

	new players[32], num
	get_players(players, num)
	for (new i = 0; i < num; i++) {
		new id = players[i]
		new team = get_user_team(id)
		if (!is_user_connected(id) ||
				(team != BD_TEAM_ALLIES && team != BD_TEAM_AXIS))
			continue
		g_bdRestartRosterSelected[id] = true
		g_bdRestartRosterUserid[id] = get_user_userid(id)
		g_bdRestartRosterTeam[id] = team
		g_bdRestartRosterCount++
	}
	return g_bdRestartRosterCount
}

/** Fail closed if combat membership changes without a connect/disconnect.
 *
 * The series userid epoch catches new connections, but an already-connected
 * spectator can join Allies/Axis without changing that epoch. Every current
 * combat player must therefore be one of the arm-time selections with the
 * same userid and team. During normalization exactly zero or one newer spawn
 * generation is valid; after the stable snapshot the generation is pinned
 * exactly too.
 */
stock bool:bd_restart_roster_pinned_complete(bool:stable_generation) {
	new players[32], num, seen = 0
	get_players(players, num)
	for (new i = 0; i < num; i++) {
		new id = players[i]
		if (!is_user_connected(id))
			continue
		new team = get_user_team(id)
		if (team != BD_TEAM_ALLIES && team != BD_TEAM_AXIS)
			continue
		if (!g_bdRestartRosterSelected[id] ||
				get_user_userid(id) != g_bdRestartRosterUserid[id] ||
				team != g_bdRestartRosterTeam[id])
			return false
		if (stable_generation) {
			if (g_bdSpawnGeneration[id] !=
						g_bdRestartRosterSpawnStable[id])
				return false
		}
		seen++
	}
	return seen == g_bdRestartRosterCount
}

/** A clan restart does not promise a new spawn callback for every already-live
 * bot. Once the authoritative round clock has rebased, accept the same exact
 * alive roster and snapshot the generations actually observed. Any later
 * generation change remains a hard abort.
 */
stock bool:bd_restart_roster_live() {
	if (g_bdRestartRosterCount < 2 ||
			!bd_restart_roster_pinned_complete(false))
		return false
	new seen = 0
	for (new id = 1; id <= 32; id++) {
		if (!g_bdRestartRosterSelected[id])
			continue
		if (!is_user_connected(id) || !is_user_alive(id) ||
				get_user_userid(id) != g_bdRestartRosterUserid[id] ||
				get_user_team(id) != g_bdRestartRosterTeam[id])
			return false
		seen++
	}
	return seen == g_bdRestartRosterCount
}

stock bd_restart_roster_alive_count() {
	new seen = 0
	for (new id = 1; id <= 32; id++) {
		if (g_bdRestartRosterSelected[id] && is_user_connected(id) &&
				is_user_alive(id) &&
				get_user_userid(id) == g_bdRestartRosterUserid[id] &&
				get_user_team(id) == g_bdRestartRosterTeam[id])
			seen++
	}
	return seen
}

stock bool:bd_restart_roster_generation_current() {
	if (!bd_restart_roster_live() ||
			!bd_restart_roster_pinned_complete(true))
		return false
	for (new id = 1; id <= 32; id++) {
		if (g_bdRestartRosterSelected[id] &&
				g_bdSpawnGeneration[id] !=
					g_bdRestartRosterSpawnStable[id])
			return false
	}
	return true
}

/** Find a neutral, quiescent objective that the frozen new-round roster can
 * stage.  This is intentionally read-only; placement happens only after the
 * post-respawn stability window closes.
 */
stock bool:bd_find_restart_plan(&chosen_flag, &chosen_team) {
	chosen_flag = -1
	chosen_team = 0
	new n = dodx_objectives_get_num()
	if (n > BD_MAX_FLAGS) n = BD_MAX_FLAGS
	new Float:center[3], Float:anchor[3]
	for (new f = 0; f < n; f++) {
		new owner = dodx_area_get_data(f, CA_owning_team)
		if (owner != 0 ||
				dodx_area_get_data(f, CA_is_capturing) ||
				bd_zone_count(f, BD_TEAM_ALLIES) != 0 ||
				bd_zone_count(f, BD_TEAM_AXIS) != 0 ||
				!bd_area_center(f, center) || !bd_far_anchor(center, anchor))
			continue

		for (new team = BD_TEAM_ALLIES; team <= BD_TEAM_AXIS; team++) {
			new needed = dodx_area_get_data(f,
				(team == BD_TEAM_ALLIES) ? CA_allies_numcap : CA_axis_numcap)
			new enemy = (team == BD_TEAM_ALLIES) ?
				BD_TEAM_AXIS : BD_TEAM_ALLIES
			if (needed < 1 || bd_live_team_count(team) < needed ||
					bd_live_team_count(enemy) < 1)
				continue
			chosen_flag = f
			chosen_team = team
			return true
		}
	}
	return false
}

stock bool:bd_restart_same_origin(const Float:a[3], const Float:b[3]) {
	new Float:distance2 = 0.0
	for (new axis = 0; axis < 3; axis++) {
		new Float:delta = a[axis] - b[axis]
		distance2 += delta * delta
	}
	return distance2 <=
		BD_RESTART_POSITION_EPSILON * BD_RESTART_POSITION_EPSILON
}

/** Freeze the proven new-round roster and begin a multi-frame stability
 * sample.  Spawns, identity/team changes, movement, capture-area occupancy,
 * or capture activity invalidate the sample before any player is moved.
 */
stock bool:bd_restart_begin_stability(flag, team) {
	if (!bd_restart_roster_live())
		return false
	// Normalization already froze the roster; reuse that generation instead of
	// ending isolation, which would briefly restore movement mid-window.
	new isolated = g_bdIsolationActive ?
		bd_isolation_count() : bd_begin_test_isolation()
	if (isolated < g_bdRestartRosterCount) {
		bd_end_test_isolation(false)
		return false
	}

	g_bdRestartStableFlag = flag
	g_bdRestartStableTeam = team
	g_bdRestartStablePolls = 0
	for (new id = 1; id <= 32; id++) {
		if (!g_bdRestartRosterSelected[id])
			continue
		g_bdRestartRosterSpawnStable[id] = g_bdSpawnGeneration[id]
		if (!dodx_get_user_origin(id, g_bdRestartRosterOrigin[id])) {
			bd_end_test_isolation(false)
			g_bdRestartStableFlag = -1
			g_bdRestartStableTeam = 0
			return false
		}
	}
	return true
}

/** 0 = stable; 1 = roster/generation changed; 2 = flag no longer neutral and
 * quiet; 3 = a pinned player moved off its snapshot origin.
 */
stock bd_restart_stability_blocker() {
	if (!g_bdIsolationActive || g_bdRestartStableFlag < 0 ||
			!bd_restart_roster_generation_current())
		return 1
	if (dodx_area_get_data(g_bdRestartStableFlag, CA_owning_team) != 0 ||
			dodx_area_get_data(g_bdRestartStableFlag, CA_is_capturing) ||
			bd_zone_count(g_bdRestartStableFlag, BD_TEAM_ALLIES) != 0 ||
			bd_zone_count(g_bdRestartStableFlag, BD_TEAM_AXIS) != 0)
		return 2

	new Float:origin[3]
	for (new id = 1; id <= 32; id++) {
		if (!g_bdRestartRosterSelected[id])
			continue
		if (!dodx_get_user_origin(id, origin) ||
				!bd_restart_same_origin(origin,
					g_bdRestartRosterOrigin[id]))
			return 3
	}
	return 0
}

stock bd_restart_drop_stability() {
	bd_end_test_isolation(false)
	g_bdRestartStablePolls = 0
	g_bdRestartStableFlag = -1
	g_bdRestartStableTeam = 0
}

stock bd_restart_arm_abort(const reason[]) {
	remove_task(BD_TASK_RESTART_ARM_POLL)
	log_amx("[BD] restart ABORT flag=-1 %s", reason)
	bd_end_test_isolation(false)
	bd_restore_restart_timer()
	bd_reset_restart_arm_state()
}

/** Create a real, bounded capture instead of waiting for random bot routing.
 *
 * Every live player is frozen and moved away from one engine capture area;
 * exactly the map-declared number of cappers is then placed at its center.
 * The engine still owns CA_is_capturing/counts and the production detector
 * still observes a real count transition. Only the prerequisite positioning
 * is deterministic. Original positions and cap time are restored at the
 * isolation boundary, guarded by the original userid for every slot.
 */
stock bool:bd_prepare_capture(const mode[], bool:need_far,
		bool:require_neutral, expected_flag = -1, expected_team = 0,
		bool:defer_cappers = false, expected_owner = BD_OWNER_ANY) {
	if (!bd_series_roster_current(true)) {
		log_amx("[BD] %s ABORT flag=-1 exact full live roster unavailable alive=%d/%d",
			mode, bd_series_roster_alive_count(), g_bdSeriesRosterCount)
		return false
	}
	new n = dodx_objectives_get_num()
	if (n > BD_MAX_FLAGS) n = BD_MAX_FLAGS

	new chosen = -1, chosen_team = 0, required = 0
	new Float:center[3], Float:anchor[3]
	for (new f = 0; f < n && chosen < 0; f++) {
		if (expected_flag >= 0 && f != expected_flag)
			continue
		new owner = dodx_area_get_data(f, CA_owning_team)
		if (!bd_owner_canonical(owner) ||
				(expected_owner != BD_OWNER_ANY && owner != expected_owner))
			continue
		if (defer_cappers &&
				(dodx_area_get_data(f, CA_is_capturing) ||
				bd_zone_count(f, BD_TEAM_ALLIES) != 0 ||
				bd_zone_count(f, BD_TEAM_AXIS) != 0))
			continue
		if (require_neutral &&
				(owner == BD_TEAM_ALLIES || owner == BD_TEAM_AXIS))
			continue
		new Float:candidate[3], Float:far_origin[3]
		if (!bd_area_center(f, candidate))
			continue
		if ((need_far && !bd_far_anchor(candidate, far_origin)) ||
				(!need_far && !bd_safe_anchor(far_origin)))
			continue

		for (new team = BD_TEAM_ALLIES; team <= BD_TEAM_AXIS; team++) {
			if (expected_team && team != expected_team)
				continue
			if (owner == team)
				continue
			new needed = dodx_area_get_data(f,
				(team == BD_TEAM_ALLIES) ? CA_allies_numcap : CA_axis_numcap)
			if (needed < 1)
				continue
			if (bd_live_team_count(team) < needed + (need_far ? 1 : 0))
				continue
			chosen = f
			chosen_team = team
			required = needed
			for (new axis = 0; axis < 3; axis++) {
				center[axis] = candidate[axis]
				anchor[axis] = far_origin[axis]
			}
			break
		}
	}
	if (chosen < 0) {
		log_amx("[BD] %s ABORT flag=-1 no deterministic capture area", mode)
		return false
	}

	// Restart readiness already owns a frozen post-respawn roster. Reuse that
	// exact generation instead of ending isolation (which would briefly restore
	// movement) and taking a second, racy snapshot before placement.
	new isolated = g_bdIsolationActive ?
		bd_isolation_count() : bd_begin_test_isolation()
	if (isolated != g_bdSeriesRosterCount ||
			!bd_series_roster_current(true)) {
		log_amx("[BD] %s ABORT flag=%d exact full live isolated roster unavailable isolated=%d expected=%d",
			mode, chosen, isolated, g_bdSeriesRosterCount)
		bd_end_test_isolation(false)
		return false
	}

	g_bdPreparedFlag = chosen
	g_bdPreparedTeam = chosen_team
	copy(g_bdPreparedMode, charsmax(g_bdPreparedMode), mode)
	g_bdPreparedCapTime = dodx_area_get_data(chosen, CA_timetocap)
	dodx_area_set_data(chosen, CA_timetocap, BD_PREPARED_CAPTURE_SECS)
	for (new axis = 0; axis < 3; axis++) {
		g_bdPreparedAnchor[axis] = anchor[axis]
		g_bdPreparedCenter[axis] = center[axis]
	}
	g_bdPreparedAnchorSaved = true
	g_bdPreparedCenterSaved = true

	new players[32], num, placed = 0
	get_players(players, num)
	for (new i = 0; i < num; i++) {
		new id = players[i]
		if (!is_user_connected(id) || !is_user_alive(id))
			continue
		dodx_set_user_origin(id, anchor)
	}
	if (defer_cappers) {
		log_amx("[BD] capture PREPARED mode=%s flag=%d team=%d cappers=0 required=%d isolated=%d deferred=1",
			mode, chosen, chosen_team, required, isolated)
		return true
	}
	for (new i = 0; i < num && placed < required; i++) {
		new id = players[i]
		if (!is_user_connected(id) || !is_user_alive(id) ||
				get_user_team(id) != chosen_team)
			continue
		dodx_set_user_origin(id, center)
		placed++
	}
	if (placed != required) {
		log_amx("[BD] %s ABORT flag=%d placed=%d required=%d",
			mode, chosen, placed, required)
		bd_end_test_isolation(false)
		return false
	}
	log_amx("[BD] capture PREPARED mode=%s flag=%d team=%d cappers=%d isolated=%d",
		mode, chosen, chosen_team, placed, isolated)
	return true
}

stock bd_find_prepared_capture() {
	if (g_bdPreparedFlag < 0 ||
			!dodx_area_get_data(g_bdPreparedFlag, CA_is_capturing) ||
			dodx_area_get_data(g_bdPreparedFlag, CA_capturing_team) !=
				g_bdPreparedTeam ||
			bd_zone_count(g_bdPreparedFlag, g_bdPreparedTeam) < 1)
		return -1
	return g_bdPreparedFlag
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
	if (g_bdPreparedFlag >= 0)
		return bd_find_prepared_capture()
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
	new isolated = g_bdIsolationActive ?
		bd_isolation_count() : bd_begin_test_isolation()
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

	bd_schedule_report_after(f)
	return true
}

public cmd_kill() {
	if (!bd_series_guard("kill"))
		return PLUGIN_HANDLED
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
	if (!bd_series_guard("arm_kill"))
		return PLUGIN_HANDLED
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
	// Live combat rarely offers an instant when every roster member is alive,
	// so preparing here aborted almost every nightly attempt. Freeze the world
	// first and let the hold task acquire dead members as they respawn (the
	// canonical_frag staging model), then prepare once the exact roster holds.
	g_bdKillAcquiring = true
	g_bdKillAcquirePolls = 0
	g_bdKillStablePolls = 0
	// When reusing a previous scenario's live isolation, its bounded end task
	// must not fire mid-acquisition and unfreeze the world under this arm.
	remove_task(BD_TASK_ISOLATION_END)
	if (!g_bdIsolationActive)
		bd_begin_test_isolation()
	log_amx("[BD] kill ARMED mode=%s acquiring exact live roster", arg_mode)
	set_task(0.1, "bd_kill_poll", BD_TASK_KILL_POLL, .flags="b")
	return PLUGIN_HANDLED
}

public cmd_disarm_kill() {
	remove_task(BD_TASK_KILL_POLL)
	g_bdKillPolls = 0
	g_bdKillAcquiring = false
	g_bdKillAcquirePolls = 0
	g_bdKillStablePolls = 0
	bd_end_test_isolation(false)
	server_print("KTP_BD_KILL_DISARMED")
	log_amx("[BD] kill DISARMED")
	return PLUGIN_HANDLED
}

public bd_kill_poll() {
	if (g_bdKillAcquiring) {
		bd_hold_test_players()
		if (++g_bdKillAcquirePolls >= BD_KILL_ACQUIRE_MAX_POLLS) {
			remove_task(BD_TASK_KILL_POLL)
			g_bdKillAcquiring = false
			log_amx("[BD] kill ABORT flag=-1 mode=%s exact full live roster unavailable",
				g_bdKillNear ? "near" : "far")
			bd_end_test_isolation(false)
			return PLUGIN_HANDLED
		}
		if (!bd_series_roster_current(true) ||
				bd_isolation_count() != g_bdSeriesRosterCount) {
			g_bdKillStablePolls = 0
			return PLUGIN_HANDLED
		}
		if (++g_bdKillStablePolls < BD_KILL_ACQUIRE_STABLE_POLLS)
			return PLUGIN_HANDLED
		if (!bd_prepare_capture(g_bdKillNear ? "near" : "far",
				!g_bdKillNear, false)) {
			remove_task(BD_TASK_KILL_POLL)
			g_bdKillAcquiring = false
			bd_end_test_isolation(false)
			return PLUGIN_HANDLED
		}
		g_bdKillAcquiring = false
		g_bdKillPolls = 0
		log_amx("[BD] kill STAGED mode=%s", g_bdKillNear ? "near" : "far")
		return PLUGIN_HANDLED
	}

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
		bd_end_test_isolation(false)
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
	g_bdRestartFrozenCount = g_bdIsolationActive ?
		bd_isolation_count() : bd_begin_test_isolation()

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
	if (!bd_series_guard("arm_restart"))
		return PLUGIN_HANDLED
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
	bd_reset_restart_arm_state()
	g_bdRestartTimerSaved = get_cvar_float("mp_clan_timer")
	g_bdRestartTimerPending = true
	set_cvar_float("mp_clan_timer", BD_RESTART_TIMER_SECS)
	g_bdRestartTimerUsed = get_cvar_float("mp_clan_timer")
	if (g_bdRestartTimerUsed < 0.99 || g_bdRestartTimerUsed > 1.01) {
		log_amx("[BD] restart ABORT flag=-1 could not pin mp_clan_timer to 1")
		bd_restore_restart_timer()
		return PLUGIN_HANDLED
	}
	if (bd_snapshot_restart_roster() < 2) {
		bd_restart_arm_abort("insufficient combat roster before normalization")
		return PLUGIN_HANDLED
	}
	g_bdRestartArmPolls = 0
	g_bdRestartArmPhase = BD_RESTART_ARM_NORMALIZING
	g_bdRestartNormalizeRoundBefore = dodx_get_round_time()
	g_bdRestartNormalizeRoundPeak = g_bdRestartNormalizeRoundBefore
	g_bdRestartNormalizeRoundLimit =
		get_cvar_float("mp_timelimit") * 60.0
	if (g_bdRestartNormalizeRoundBefore < 0.0 ||
			g_bdRestartNormalizeRoundLimit <= 0.0) {
		bd_restart_arm_abort("normalization clock unavailable")
		return PLUGIN_HANDLED
	}
	// Normalize the map first. By the time this LAST scenario runs, naturally
	// neutral points have usually been captured and can never exercise 0 -> 0.
	// The poll must observe this clock's complete rebase, every selected roster
	// member's exact live identity/team roster, and a stable frozen world before
	// it is allowed to prepare the candidate-backed restart. The later stable
	// snapshot still rejects any post-snapshot spawn generation change.
	log_amx("[BD] restart ARMED preparing neutral reset timer_before=%.2f timer_used=%.2f",
		g_bdRestartTimerSaved, g_bdRestartTimerUsed)
	// Take ownership of isolation before the reset. The previous scenario's
	// isolation can still be live here with its bounded bd_isolation_end task
	// pending; reusing it let that task fire mid-normalization, restoring and
	// unfreezing every bot inside the evidence window (observed as restart
	// TIMEOUT roster_alive=7/12). Restore that older state now, in the same
	// frame as the reset, so no combat can run between restore and refreeze.
	remove_task(BD_TASK_ISOLATION_END)
	bd_end_test_isolation(false)
	server_cmd("mp_clan_restartround 1")
	server_exec()
	// Freeze the world for the whole normalization. Free-running bots recapture
	// the map's neutral flags within seconds of the reset, so bd_find_restart_plan
	// never saw a neutral quiet target (nightly restart TIMEOUT stable_flag=-1).
	// The hold task re-freezes every member as the restart respawns it, so the
	// post-reset neutral ownership and empty zones survive until staging.
	bd_begin_test_isolation()
	new Float:after_command = dodx_get_round_time()
	if (after_command > g_bdRestartNormalizeRoundPeak)
		g_bdRestartNormalizeRoundPeak = after_command
	set_task(0.1, "bd_restart_arm_poll", BD_TASK_RESTART_ARM_POLL, .flags="b")
	return PLUGIN_HANDLED
}

public bd_restart_arm_poll() {
	g_bdRestartArmPolls++
	if (!g_bdSeriesActive)
		return PLUGIN_HANDLED
	if (g_bdRestartArmPolls >= BD_RESTART_ARM_MAX_POLLS) {
		log_amx("[BD] restart TIMEOUT phase=%d rebase=%d roster_alive=%d/%d stable_flag=%d wait_roster=%d wait_plan=%d wait_begin=%d drops=%d last_drop=%d",
			g_bdRestartArmPhase, g_bdRestartNormalizeRebased,
			bd_restart_roster_alive_count(), g_bdRestartRosterCount,
			g_bdRestartStableFlag, g_bdRestartWaitRoster,
			g_bdRestartWaitPlan, g_bdRestartWaitBegin,
			g_bdRestartDrops, g_bdRestartLastDrop)
		bd_log_flag_survey("restart")
		bd_restart_arm_abort("no stageable capture while armed")
		return PLUGIN_HANDLED
	}
	new bool:stable_generation =
		g_bdRestartArmPhase == BD_RESTART_ARM_PREPARED ||
		(g_bdRestartArmPhase == BD_RESTART_ARM_STABILIZING &&
			g_bdRestartStableFlag >= 0)
	if (!bd_restart_roster_pinned_complete(stable_generation)) {
		bd_restart_arm_abort("combat roster changed while restart armed")
		return PLUGIN_HANDLED
	}
	if (g_bdIsolationActive)
		bd_hold_test_players()

	new Float:round_now = dodx_get_round_time()
	if (g_bdRestartArmPhase == BD_RESTART_ARM_NORMALIZING) {
		if (round_now > g_bdRestartNormalizeRoundPeak)
			g_bdRestartNormalizeRoundPeak = round_now
		if (!g_bdRestartNormalizeRebased &&
				g_bdRestartNormalizeRoundPeak >
					g_bdRestartNormalizeRoundLimit + 0.01 &&
				g_bdRestartNormalizeRoundPeak >
					g_bdRestartNormalizeRoundBefore + 0.01)
			g_bdRestartNormalizeRebased = true

		if (g_bdRestartNormalizeRebased &&
				round_now >= g_bdRestartNormalizeRoundLimit - 5.0 &&
				round_now <= g_bdRestartNormalizeRoundLimit + 0.01) {
			g_bdRestartArmPhase = BD_RESTART_ARM_STABILIZING
			g_bdRestartStablePolls = 0
		}
		return PLUGIN_HANDLED
	}

	if (g_bdRestartArmPhase == BD_RESTART_ARM_STABILIZING) {
		if (g_bdRestartStableFlag < 0) {
			if (!bd_restart_roster_live()) {
				g_bdRestartWaitRoster++
				return PLUGIN_HANDLED
			}
			new flag, team
			if (!bd_find_restart_plan(flag, team)) {
				g_bdRestartWaitPlan++
				return PLUGIN_HANDLED
			}
			if (!bd_restart_begin_stability(flag, team)) {
				g_bdRestartWaitBegin++
				return PLUGIN_HANDLED
			}
			// Never prepare in the first frame that observes the post-respawn
			// roster. The following polls must independently prove stability.
			return PLUGIN_HANDLED
		}

		bd_hold_test_players()
		new blocker = bd_restart_stability_blocker()
		if (blocker != 0) {
			g_bdRestartDrops++
			g_bdRestartLastDrop = blocker
			bd_restart_drop_stability()
			return PLUGIN_HANDLED
		}
		g_bdRestartStablePolls++
		if (g_bdRestartStablePolls <
				BD_RESTART_POSTRESPAWN_STABLE_POLLS)
			return PLUGIN_HANDLED

		if (!bd_prepare_capture("restart", false, true,
				g_bdRestartStableFlag, g_bdRestartStableTeam)) {
			bd_restart_arm_abort("post-respawn capture preparation failed")
			return PLUGIN_HANDLED
		}
		g_bdRestartArmPhase = BD_RESTART_ARM_PREPARED
		// CA_is_capturing is engine-owned and may update after this callback.
		// Do not dispatch or queue until a later poll observes it active.
		return PLUGIN_HANDLED
	}

	if (g_bdRestartArmPhase == BD_RESTART_ARM_PREPARED) {
		if (!bd_restart_roster_generation_current()) {
			bd_restart_arm_abort("roster respawned after capture preparation")
			return PLUGIN_HANDLED
		}
		new f = bd_find_prepared_capture()
		if (f == g_bdRestartStableFlag && bd_execute_restart(f)) {
			remove_task(BD_TASK_RESTART_ARM_POLL)
			g_bdRestartArmPhase = BD_RESTART_ARM_IDLE
		}
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
	bd_reset_restart_arm_state()
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
stock bd_schedule_report_after(f) {
	if (f < 0 || f >= BD_MAX_FLAGS)
		return
	new taskid = BD_TASK_REPORT_BASE + f
	remove_task(taskid)
	set_task(1.5, "bd_report_after", taskid)
}

public bd_report_after(taskid) {
	if (!g_bdSeriesActive)
		return PLUGIN_HANDLED
	new f = taskid - BD_TASK_REPORT_BASE
	if (f < 0 || f >= BD_MAX_FLAGS)
		return PLUGIN_HANDLED
	log_amx("[BD] after flag=%d allies=%d axis=%d capping=%d owner=%d",
		f, dodx_area_get_data(f, CA_num_allies),
		dodx_area_get_data(f, CA_num_axis),
		dodx_area_get_data(f, CA_is_capturing),
		dodx_area_get_data(f, CA_owning_team))
	return PLUGIN_HANDLED
}

/** Read-only clean-capture target selection.
 *
 * DoD transiently exposes CA_owning_team=-1 around resets.  Only the three
 * canonical owner values may enter the stability latch, and no player is
 * moved until the same flag/team/owner tuple survives several exact-roster
 * polls.
 */
stock bool:bd_find_clean_plan(&chosen_flag, &chosen_team, &chosen_owner) {
	chosen_flag = -1
	chosen_team = 0
	chosen_owner = BD_OWNER_ANY
	if (!bd_series_roster_current(true))
		return false

	new n = dodx_objectives_get_num()
	if (n > BD_MAX_FLAGS) n = BD_MAX_FLAGS
	new Float:center[3], Float:anchor[3]
	for (new f = 0; f < n; f++) {
		new owner = dodx_area_get_data(f, CA_owning_team)
		if (!bd_owner_canonical(owner) ||
				dodx_area_get_data(f, CA_is_capturing) ||
				bd_zone_count(f, BD_TEAM_ALLIES) != 0 ||
				bd_zone_count(f, BD_TEAM_AXIS) != 0 ||
				!bd_area_center(f, center) || !bd_far_anchor(center, anchor))
			continue

		for (new team = BD_TEAM_ALLIES; team <= BD_TEAM_AXIS; team++) {
			if (owner == team)
				continue
			new needed = dodx_area_get_data(f,
				(team == BD_TEAM_ALLIES) ? CA_allies_numcap : CA_axis_numcap)
			if (needed < 1 || bd_live_team_count(team) < needed)
				continue
			chosen_flag = f
			chosen_team = team
			chosen_owner = owner
			return true
		}
	}
	return false
}

/** Pin the complete combat roster for the clean ownership transition.
 *
 * The normal isolation helper follows respawns so other diagnostics can keep
 * running. This scenario is stricter: every combat player must already be
 * alive and held, and userid/team/spawn generation must remain exact until
 * the evidence window closes.
 */
stock bool:bd_clean_snapshot_roster() {
	g_bdCleanRosterCount = 0
	if (!g_bdIsolationActive || !bd_series_roster_current(true) ||
			bd_isolation_count() != g_bdSeriesRosterCount)
		return false
	for (new id = 1; id <= 32; id++) {
		g_bdCleanRosterSelected[id] = false
		g_bdCleanRosterUserid[id] = 0
		g_bdCleanRosterTeam[id] = 0
		g_bdCleanRosterSpawn[id] = 0
		if (!g_bdSeriesRosterSelected[id])
			continue
		new team = get_user_team(id)
		if (!is_user_connected(id) || !is_user_alive(id) ||
				get_user_userid(id) != g_bdSeriesRosterUserid[id] ||
				team != g_bdSeriesRosterTeam[id] ||
				!g_bdIsolationHeld[id] ||
				g_bdIsolationUserid[id] != get_user_userid(id) ||
				g_bdIsolationSpawnGeneration[id] != g_bdSpawnGeneration[id])
			return false
		g_bdCleanRosterSelected[id] = true
		g_bdCleanRosterUserid[id] = get_user_userid(id)
		g_bdCleanRosterTeam[id] = team
		g_bdCleanRosterSpawn[id] = g_bdSpawnGeneration[id]
		g_bdCleanRosterCount++
	}
	return g_bdCleanRosterCount == g_bdSeriesRosterCount
}

/** Pin the exact engine userids that will receive the real capture credit. */
stock bool:bd_clean_pin_cappers() {
	g_bdCleanCapperCount = 0
	g_bdCleanCapperUseridList[0] = 0
	for (new id = 1; id <= 32; id++) {
		g_bdCleanCapperSelected[id] = false
		g_bdCleanCapperUserid[id] = 0
		if (!g_bdCleanRosterSelected[id] ||
				g_bdCleanRosterTeam[id] != g_bdCleanTeam ||
				g_bdCleanCapperCount >= g_bdCleanRequired)
			continue
		new userid = g_bdCleanRosterUserid[id]
		if (userid <= 0)
			return false
		for (new other = 1; other <= 32; other++) {
			if (g_bdCleanCapperSelected[other] &&
					g_bdCleanCapperUserid[other] == userid)
				return false
		}
		g_bdCleanCapperSelected[id] = true
		g_bdCleanCapperUserid[id] = userid
		new token[16]
		num_to_str(userid, token, charsmax(token))
		if (g_bdCleanCapperCount)
			add(g_bdCleanCapperUseridList,
				charsmax(g_bdCleanCapperUseridList), ",")
		add(g_bdCleanCapperUseridList,
			charsmax(g_bdCleanCapperUseridList), token)
		g_bdCleanCapperCount++
	}
	return g_bdCleanCapperCount == g_bdCleanRequired
}

stock bool:bd_clean_roster_current() {
	new seen = 0
	for (new id = 1; id <= 32; id++) {
		if (!is_user_connected(id)) {
			if (g_bdCleanRosterSelected[id])
				return false
			continue
		}
		new team = get_user_team(id)
		if (!g_bdCleanRosterSelected[id]) {
			if (team == BD_TEAM_ALLIES || team == BD_TEAM_AXIS)
				return false
			continue
		}
		if (!is_user_alive(id) ||
				get_user_userid(id) != g_bdCleanRosterUserid[id] ||
				team != g_bdCleanRosterTeam[id] ||
				g_bdSpawnGeneration[id] != g_bdCleanRosterSpawn[id] ||
				!g_bdIsolationHeld[id] ||
				g_bdIsolationUserid[id] != g_bdCleanRosterUserid[id] ||
				g_bdIsolationSpawnGeneration[id] != g_bdCleanRosterSpawn[id])
			return false
		seen++
	}
	return seen == g_bdCleanRosterCount
}

/** Move the still-frozen roster away from the captured point.
 *
 * This supplies the real post-capture count drop whose stale candidate clear
 * is under test. Godmode/freeze remain in place, so no organic combat can own
 * any cap_break observed before the final synchronous buffer drain.
 */
stock bool:bd_clean_move_roster_off_point() {
	if (!g_bdPreparedAnchorSaved || !bd_clean_roster_current())
		return false
	new moved = 0
	new Float:stopped[3]
	for (new id = 1; id <= 32; id++) {
		if (!g_bdCleanRosterSelected[id])
			continue
		dodx_set_user_origin(id, g_bdPreparedAnchor)
		set_entvar(id, var_velocity, stopped)
		new flags = get_entvar(id, var_flags)
		set_entvar(id, var_flags, flags | FL_FROZEN | FL_GODMODE)
		moved++
	}
	return moved == g_bdCleanRosterCount
}

/** Place only the already pinned cappers after the quiet quarantine drains. */
stock bool:bd_clean_place_pinned_cappers() {
	if (!g_bdPreparedCenterSaved || !bd_clean_roster_current() ||
			g_bdCleanCapperCount != g_bdCleanRequired)
		return false
	new placed = 0
	new Float:stopped[3]
	for (new id = 1; id <= 32; id++) {
		if (!g_bdCleanCapperSelected[id])
			continue
		if (get_user_userid(id) != g_bdCleanCapperUserid[id])
			return false
		dodx_set_user_origin(id, g_bdPreparedCenter)
		set_entvar(id, var_velocity, stopped)
		new flags = get_entvar(id, var_flags)
		set_entvar(id, var_flags, flags | FL_FROZEN | FL_GODMODE)
		placed++
	}
	return placed == g_bdCleanRequired
}

stock bd_clean_abort(const reason[]) {
	remove_task(BD_TASK_CLEAN_CAPTURE_POLL)
	remove_task(BD_TASK_CLEAN_CAPTURE_FINISH)
	log_amx("[BD] clean_capture ABORT flag=%d %s", g_bdCleanFlag, reason)
	g_bdCleanActive = false
	bd_end_test_isolation(true)
	bd_reset_clean_state()
}

/** Stage one REAL engine capture and keep a closed evidence world afterward.
 *
 * No product event is fabricated. The command only freezes and positions the
 * live test roster inside an actual map capture area, then waits for the
 * engine's ownership field and ordinary dod_capture_area markers to change.
 */
public cmd_arm_clean_capture() {
	if (!bd_series_guard("arm_clean_capture"))
		return PLUGIN_HANDLED
	remove_task(BD_TASK_CLEAN_CAPTURE_POLL)
	remove_task(BD_TASK_CLEAN_CAPTURE_FINISH)
	bd_end_test_isolation(false)
	bd_reset_clean_state()

	new initial_flushed = bd_flush_stats_capture() ? 1 : 0
	if (!initial_flushed) {
		log_amx("[BD] clean_capture ABORT flag=-1 stats capture preflush unavailable")
		return PLUGIN_HANDLED
	}
	g_bdCleanArming = true
	log_amx("[BD] clean_capture ARMED roster=%d", g_bdSeriesRosterCount)
	set_task(0.1, "bd_clean_capture_poll",
		BD_TASK_CLEAN_CAPTURE_POLL, .flags="b")
	return PLUGIN_HANDLED
}

public bd_clean_capture_poll() {
	if (g_bdCleanArming) {
		if (!g_bdSeriesActive || g_bdUseridEpoch != g_bdSeriesUseridEpoch ||
				!bd_series_roster_current(false)) {
			bd_clean_abort("series/userid/roster boundary changed while arming")
			return PLUGIN_HANDLED
		}
		if (++g_bdCleanArmPolls >= BD_CLEAN_ARM_MAX_POLLS) {
			log_amx("[BD] clean_capture TIMEOUT alive=%d/%d wait_plan=%d target_changes=%d",
				bd_series_roster_alive_count(), g_bdSeriesRosterCount,
				g_bdCleanWaitPlan, g_bdCleanTargetChanges)
			bd_log_flag_survey("clean_capture")
			bd_clean_abort("no stable canonical target with exact full live roster")
			return PLUGIN_HANDLED
		}

		new flag, team, owner
		if (!bd_find_clean_plan(flag, team, owner)) {
			g_bdCleanWaitPlan++
			g_bdCleanStablePolls = 0
			g_bdCleanStableFlag = -1
			g_bdCleanStableTeam = 0
			g_bdCleanStableOwner = BD_OWNER_ANY
			return PLUGIN_HANDLED
		}
		if (flag != g_bdCleanStableFlag || team != g_bdCleanStableTeam ||
				owner != g_bdCleanStableOwner) {
			if (g_bdCleanStableFlag >= 0)
				g_bdCleanTargetChanges++
			g_bdCleanStableFlag = flag
			g_bdCleanStableTeam = team
			g_bdCleanStableOwner = owner
			g_bdCleanStablePolls = 1
			return PLUGIN_HANDLED
		}
		if (++g_bdCleanStablePolls < BD_CLEAN_TARGET_STABLE_POLLS)
			return PLUGIN_HANDLED

		if (!bd_prepare_capture("clean_capture", false, false,
				flag, team, true, owner)) {
			bd_clean_abort("stable target could not freeze exact full roster")
			return PLUGIN_HANDLED
		}
		g_bdCleanFlag = g_bdPreparedFlag
		g_bdCleanTeam = g_bdPreparedTeam
		g_bdCleanOwnerBefore = dodx_area_get_data(
			g_bdCleanFlag, CA_owning_team)
		g_bdCleanRequired = dodx_area_get_data(
			g_bdCleanFlag, (g_bdCleanTeam == BD_TEAM_ALLIES) ?
			CA_allies_numcap : CA_axis_numcap)
		g_bdCleanIsolated = bd_isolation_count()
		dodx_objective_get_data(g_bdCleanFlag, CP_name, g_bdCleanFlagName,
			charsmax(g_bdCleanFlagName))
		if (!bd_owner_canonical(g_bdCleanOwnerBefore) ||
				g_bdCleanOwnerBefore != owner ||
				g_bdCleanOwnerBefore == g_bdCleanTeam ||
				g_bdCleanRequired < 1 ||
				g_bdCleanIsolated != g_bdSeriesRosterCount ||
				!bd_clean_snapshot_roster() || !bd_clean_pin_cappers()) {
			bd_clean_abort("roster/ownership precondition was not exact")
			return PLUGIN_HANDLED
		}

		g_bdCleanArming = false
		g_bdCleanActive = true
		g_bdCleanQuietStarted = get_gametime()
		return PLUGIN_HANDLED
	}
	if (!g_bdCleanActive)
		return PLUGIN_HANDLED
	if (!g_bdSeriesActive || g_bdUseridEpoch != g_bdSeriesUseridEpoch ||
			!bd_clean_roster_current()) {
		bd_clean_abort("series/userid/roster boundary changed")
		return PLUGIN_HANDLED
	}
	if (g_bdCleanTeamDeaths || g_bdCleanContaminated) {
		bd_clean_abort("combat death contaminated evidence window")
		return PLUGIN_HANDLED
	}

	new owner = dodx_area_get_data(g_bdCleanFlag, CA_owning_team)
	if (!bd_owner_canonical(owner)) {
		bd_clean_abort("capture owner became noncanonical")
		return PLUGIN_HANDLED
	}
	if (!g_bdCleanCappersPlaced) {
		if (owner != g_bdCleanOwnerBefore) {
			bd_clean_abort("ownership changed during quiet quarantine")
			return PLUGIN_HANDLED
		}
		if (dodx_area_get_data(g_bdCleanFlag, CA_is_capturing) ||
				bd_zone_count(g_bdCleanFlag, BD_TEAM_ALLIES) != 0 ||
				bd_zone_count(g_bdCleanFlag, BD_TEAM_AXIS) != 0) {
			bd_clean_abort("target capture area was not quiet and empty")
			return PLUGIN_HANDLED
		}
		if (get_gametime() - g_bdCleanQuietStarted < BD_CLEAN_QUIET_SECS)
			return PLUGIN_HANDLED

		new flushed = bd_flush_stats_capture() ? 1 : 0
		if (!flushed || !g_bdSeriesActive ||
				g_bdUseridEpoch != g_bdSeriesUseridEpoch ||
				!bd_clean_roster_current() || g_bdCleanTeamDeaths ||
				g_bdCleanContaminated ||
				dodx_area_get_data(g_bdCleanFlag, CA_is_capturing) ||
				bd_zone_count(g_bdCleanFlag, BD_TEAM_ALLIES) != 0 ||
				bd_zone_count(g_bdCleanFlag, BD_TEAM_AXIS) != 0) {
			bd_clean_abort("quiet boundary or final preflush was contaminated")
			return PLUGIN_HANDLED
		}
		dodx_area_set_data(g_bdCleanFlag, CA_timetocap,
			BD_CLEAN_CAPTURE_SECS)
		if (!bd_clean_place_pinned_cappers()) {
			bd_clean_abort("could not place exact pinned cappers")
			return PLUGIN_HANDLED
		}
		g_bdCleanCappersPlaced = true
		g_bdCleanPolls = 0
		new quiet_ms = floatround(
			(get_gametime() - g_bdCleanQuietStarted) * 1000.0)
		log_amx("[BD] clean_capture BEGIN flag=%d fname=%s capteam=%d owner_before=%d required=%d isolated=%d roster=%d cappers=%s quiet_ms=%d flushed=%d userid_epoch=%d",
			g_bdCleanFlag, g_bdCleanFlagName, g_bdCleanTeam,
			g_bdCleanOwnerBefore, g_bdCleanRequired, g_bdCleanIsolated,
			g_bdCleanRosterCount, g_bdCleanCapperUseridList, quiet_ms,
			flushed, g_bdSeriesUseridEpoch)
		return PLUGIN_HANDLED
	}
	if (g_bdCleanCompleted) {
		if (owner != g_bdCleanTeam) {
			bd_clean_abort("ownership changed after staged completion")
			return PLUGIN_HANDLED
		}
		return PLUGIN_HANDLED
	}

	g_bdCleanPolls++
	if (owner == g_bdCleanTeam) {
		g_bdCleanCompleted = true
		g_bdCleanOwnerAfter = g_bdCleanTeam
		if (!bd_clean_move_roster_off_point()) {
			bd_clean_abort("could not move exact frozen roster off captured point")
			return PLUGIN_HANDLED
		}
		log_amx("[BD] clean_capture TRANSITION flag=%d fname=%s owner_before=%d owner_after=%d",
			g_bdCleanFlag, g_bdCleanFlagName,
			g_bdCleanOwnerBefore, g_bdCleanOwnerAfter)
		set_task(BD_CLEAN_EVIDENCE_SECS, "bd_clean_capture_finish",
			BD_TASK_CLEAN_CAPTURE_FINISH)
		return PLUGIN_HANDLED
	}
	if (owner != g_bdCleanOwnerBefore) {
		bd_clean_abort("ownership changed to an unexpected team")
		return PLUGIN_HANDLED
	}
	if (g_bdCleanPolls >= BD_CLEAN_CAPTURE_MAX_POLLS)
		bd_clean_abort("real engine ownership transition did not complete")
	return PLUGIN_HANDLED
}

public bd_clean_capture_finish() {
	remove_task(BD_TASK_CLEAN_CAPTURE_POLL)
	remove_task(BD_TASK_CLEAN_CAPTURE_FINISH)
	if (!g_bdCleanActive || !g_bdCleanCompleted || !g_bdSeriesActive ||
			g_bdUseridEpoch != g_bdSeriesUseridEpoch ||
			!bd_clean_roster_current() || g_bdCleanTeamDeaths ||
			g_bdCleanContaminated ||
			dodx_area_get_data(g_bdCleanFlag, CA_owning_team) !=
				g_bdCleanTeam) {
		bd_clean_abort("final evidence state was contaminated")
		return PLUGIN_HANDLED
	}
	new count_after = bd_zone_count(g_bdCleanFlag, g_bdCleanTeam)
	if (count_after != 0) {
		bd_clean_abort("frozen cappers did not leave captured point")
		return PLUGIN_HANDLED
	}
	new flushed = bd_flush_stats_capture() ? 1 : 0
	if (!flushed) {
		bd_clean_abort("stats capture final flush unavailable")
		return PLUGIN_HANDLED
	}
	log_amx("[BD] clean_capture RESULT flag=%d fname=%s capteam=%d owner_before=%d owner_after=%d required=%d isolated=%d roster=%d cappers=%s count_after=%d deaths=%d flushed=%d contaminated=%d",
		g_bdCleanFlag, g_bdCleanFlagName, g_bdCleanTeam,
		g_bdCleanOwnerBefore, g_bdCleanOwnerAfter, g_bdCleanRequired,
		g_bdCleanIsolated, g_bdCleanRosterCount,
		g_bdCleanCapperUseridList, count_after,
		g_bdCleanTeamDeaths, flushed, g_bdCleanContaminated)
	g_bdCleanActive = false
	bd_end_test_isolation(true)
	bd_reset_clean_state()
	return PLUGIN_HANDLED
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

	bd_schedule_report_after(f)
	if (g_bdIsolationActive)
		set_task(BD_KILL_ISOLATION_SECS, "bd_isolation_end",
			BD_TASK_ISOLATION_END)
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
	if (!bd_series_guard("walkoff"))
		return PLUGIN_HANDLED
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
	if (!bd_series_guard("arm_walkoff"))
		return PLUGIN_HANDLED
	remove_task(BD_TASK_WALKOFF_POLL)
	g_bdWalkoffPolls = 0
	// Same roster race as arm_kill: freeze first, acquire dead members on
	// respawn, prepare only once the exact live roster is proven stable.
	g_bdWalkoffAcquiring = true
	g_bdWalkoffAcquirePolls = 0
	g_bdWalkoffStablePolls = 0
	// Same ownership rule as arm_kill: a reused isolation's pending end task
	// must not unfreeze the world mid-acquisition.
	remove_task(BD_TASK_ISOLATION_END)
	if (!g_bdIsolationActive)
		bd_begin_test_isolation()
	log_amx("[BD] walkoff ARMED")
	set_task(0.1, "bd_walkoff_poll", BD_TASK_WALKOFF_POLL, .flags="b")
	return PLUGIN_HANDLED
}

public bd_walkoff_poll() {
	if (g_bdWalkoffAcquiring) {
		bd_hold_test_players()
		if (++g_bdWalkoffAcquirePolls >= BD_KILL_ACQUIRE_MAX_POLLS) {
			remove_task(BD_TASK_WALKOFF_POLL)
			g_bdWalkoffAcquiring = false
			log_amx("[BD] walkoff ABORT flag=-1 exact full live roster unavailable")
			bd_end_test_isolation(false)
			return PLUGIN_HANDLED
		}
		if (!bd_series_roster_current(true) ||
				bd_isolation_count() != g_bdSeriesRosterCount) {
			g_bdWalkoffStablePolls = 0
			return PLUGIN_HANDLED
		}
		if (++g_bdWalkoffStablePolls < BD_KILL_ACQUIRE_STABLE_POLLS)
			return PLUGIN_HANDLED
		if (!bd_prepare_capture("walkoff", true, false)) {
			remove_task(BD_TASK_WALKOFF_POLL)
			g_bdWalkoffAcquiring = false
			bd_end_test_isolation(false)
			return PLUGIN_HANDLED
		}
		g_bdWalkoffAcquiring = false
		g_bdWalkoffPolls = 0
		log_amx("[BD] walkoff STAGED")
		return PLUGIN_HANDLED
	}

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
		bd_end_test_isolation(false)
	}
	return PLUGIN_HANDLED
}
