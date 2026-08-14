/**
 * KTPAssistDrive -- deterministic assist-attribution regression scenario.
 *
 * DODX can report a degraded killer for projectile deaths even though the
 * immediately preceding damage forward named the real attacker. This stages
 * exactly that sequence with three live bots. It never performs a real kill.
 * Lane B compiles and loads this diagnostic only inside its disposable server.
 */

#include <amxmodx>
#include <dodx>

#define PLUGIN  "KTP Assist Drive"
#define VERSION "0.1"
#define AUTHOR  "KTP"

public plugin_init() {
	register_plugin(PLUGIN, VERSION, AUTHOR)
	register_srvcmd("ktp_ad_run", "cmd_run")
	log_amx("[AD] loaded -- NOT FOR PRODUCTION")
}

stock ad_flush_stats_capture() {
	if (callfunc_begin("ksc_flush_task", "stats_logging.amxx") == 1)
		callfunc_end()
}

public cmd_run() {
	new players[32], num
	get_players(players, num, "a")

	new victim = 0, killer = 0, assister = 0
	for (new i = 0; i < num && !victim; i++) {
		new candidate = players[i]
		new victim_team = get_user_team(candidate)
		if (victim_team != 1 && victim_team != 2)
			continue

		for (new j = 0; j < num; j++) {
			new enemy = players[j]
			if (get_user_team(enemy) == victim_team)
				continue
			if (!killer)
				killer = enemy
			else if (enemy != killer) {
				assister = enemy
				victim = candidate
				break
			}
		}
		if (!victim)
			killer = 0
	}

	if (!victim || !killer || !assister) {
		log_amx("[AD] ABORT need one victim and two live enemies")
		return PLUGIN_HANDLED
	}

	new vname[32], kname[32], aname[32]
	get_user_name(victim, vname, charsmax(vname))
	get_user_name(killer, kname, charsmax(kname))
	get_user_name(assister, aname, charsmax(aname))

	log_amx("[AD] BEGIN victim=%d vname=%s killer=%d kname=%s assister=%d aname=%s",
		victim, vname, killer, kname, assister, aname)

	// A third party crosses the assist threshold, then the real killer lands
	// the final hit. The death callback deliberately degrades killer to zero,
	// reproducing the projectile path that credited the killer as an assister.
	dodx_test_dispatch_client_spawn(victim)
	dodx_test_dispatch_damage(assister, victim, 60, 6, 2, 0)
	dodx_test_dispatch_damage(killer, victim, 100, 27, 2, 0)
	dodx_test_dispatch_client_death(0, victim, 27, 2, 0)

	// Force the capture buffer into the log before END, giving the Python
	// assertion exact boundaries despite the normal five-second flush task.
	ad_flush_stats_capture()
	log_amx("[AD] END")
	return PLUGIN_HANDLED
}
