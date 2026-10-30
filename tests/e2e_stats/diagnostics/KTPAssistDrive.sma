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
	register_srvcmd("ktp_ad_postmatch_frag", "cmd_postmatch_frag")
	register_srvcmd("ktp_vc_run", "cmd_voice")
	register_srvcmd("ktp_vm_run", "cmd_voice_menu")
	register_srvcmd("ktp_ow_run", "cmd_own_weapon")
	register_event("TextMsg", "on_textmsg", "b")
	log_amx("[AD] loaded -- NOT FOR PRODUCTION")
}

stock ad_player_str(id, out[], len) {
	new name[32], authid[32], team[16]
	get_user_name(id, name, charsmax(name))
	get_user_authid(id, authid, charsmax(authid))
	get_user_info(id, "team", team, charsmax(team))
	if (team[0] >= 'a' && team[0] <= 'z')
		team[0] -= 32
	formatex(out, len, "%s<%d><%s><%s>", name, get_user_userid(id), authid, team)
}

public cmd_postmatch_frag() {
	new players[32], num, killer = 0, victim = 0
	get_players(players, num, "a")
	for (new i = 0; i < num && !victim; i++) {
		for (new j = 0; j < num; j++) {
			if (get_user_team(players[i]) != get_user_team(players[j])) {
				killer = players[i]
				victim = players[j]
				break
			}
		}
	}
	if (!killer || !victim) {
		log_amx("[AD] POSTMATCH ABORT need two live opponents")
		return PLUGIN_HANDLED
	}

	new kstr[96], vstr[96]
	ad_player_str(killer, kstr, charsmax(kstr))
	ad_player_str(victim, vstr, charsmax(vstr))
	log_amx("[AD] POSTMATCH FRAG killer=%d victim=%d", killer, victim)
	log_message("^"%s^" killed ^"%s^" with ^"garand^"", kstr, vstr)
	return PLUGIN_HANDLED
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

// Five live bots: three pick a voice-menu command, two give a hand signal. amxclient_cmd runs the
// command server-side exactly as a real pick arrives: the client_command
// forward fires once (stats_logging's hook logs the line) and the game DLL
// then handles it. Bots never do this on their own, so without this the
// voice check is never exercised and reports not_exercised forever.
public cmd_voice() {
	new const cmds[][] = { "voice_negative", "voice_grenade", "voice_sniper", "signal_yes", "signal_grenade" }
	new players[32], num, issued = 0
	get_players(players, num, "a")
	for (new i = 0; i < num && issued < sizeof(cmds); i++) {
		new team = get_user_team(players[i])
		if (team != 1 && team != 2)
			continue
		amxclient_cmd(players[i], cmds[issued++])
	}
	ad_flush_stats_capture()
	log_amx("[VC] END issued=%d", issued)
	return PLUGIN_HANDLED
}

// Voice MENU drive (stats_logging 1.33.0). Bots open voice menu N and pick slot K for all 27
// slots, one pick every 1.5 s rotating through the live bots of both teams so the game's own voice
// cooldown never swallows a pick. Each pick is bracketed by a [VM] PICK line; every
// #Voice_subtitle_* TextMsg the game sends to teammates is logged as [VM] SUB, which is the game's
// own statement of which voice that slot played.
new g_vmBots[32], g_vmNumBots, g_vmPick

public cmd_voice_menu() {
	new players[32], num
	get_players(players, num, "a")
	g_vmNumBots = 0
	for (new i = 0; i < num; i++) {
		new t = get_user_team(players[i])
		if (t == 1 || t == 2)
			g_vmBots[g_vmNumBots++] = players[i]
	}
	if (g_vmNumBots < 2) {
		log_amx("[VM] ABORT need two live bots on teams")
		return PLUGIN_HANDLED
	}
	g_vmPick = 0
	set_task(1.5, "vm_next", 77301)
	return PLUGIN_HANDLED
}

public vm_next() {
	if (g_vmPick >= 27) {
		ad_flush_stats_capture()
		log_amx("[VM] END picks=%d", g_vmPick)
		return
	}
	new bot = g_vmBots[g_vmPick % g_vmNumBots]
	if (!is_user_connected(bot)) {
		log_amx("[VM] ABORT bot %d left", bot)
		return
	}
	new menu = g_vmPick / 9 + 1, slot = g_vmPick % 9 + 1, name[32], cmd[16], arg[4]
	get_user_name(bot, name, charsmax(name))
	g_vmPick++
	log_amx("[VM] PICK n=%d bot=%d bname=%s menu=%d slot=%d", g_vmPick, bot, name, menu, slot)
	formatex(cmd, charsmax(cmd), "voice_menu%d", menu)
	amxclient_cmd(bot, cmd)
	num_to_str(slot, arg, charsmax(arg))
	amxclient_cmd(bot, "menuselect", arg)
	ad_flush_stats_capture()
	set_task(1.5, "vm_next", 77301)
}

public on_textmsg(id) {
	new arg[64]
	for (new i = 2; i <= read_datanum() && i <= 6; i++) {
		read_data(i, arg, charsmax(arg))
		if (equal(arg, "#Voice_subtitle_", 16)) {
			log_amx("[VM] SUB to=%d text=%s", id, arg)
			return
		}
	}
}

// Own-weapon kill drive (stats_logging 1.34.0). Two live teammates A and B carrying different
// primaries. A dies for real (user_kill), so the game drops A's gun; B presses the drop key and is
// put on A's body, so the game's own touch hands B that gun. Every dod_client_weaponpickup the
// DODX poll fires for B is logged as [OW] FWD -- the game-side claim this scenario exists to
// observe. If no real pickup arrives in 5 s, stats_logging's handler is called directly instead
// ([OW] SYNTHETIC) so the ledger is still tested, and the verdict says the engine half was not.
// The kill itself is a dispatched TEAMKILL: no frag_context marker, so no expected no-row diagnostic.
new g_owA, g_owB, g_owWpn, g_owPolls, bool:g_owActive, bool:g_owPicked
new Float:g_owAOrigin[3]

stock bool:ow_is_primary(w) {
	switch (w) {
		case DODW_GARAND, DODW_SCOPED_KAR, DODW_THOMPSON, DODW_STG44, DODW_SPRINGFIELD,
			DODW_KAR, DODW_BAR, DODW_MP40, DODW_M1_CARBINE, DODW_GREASEGUN, DODW_FG42, DODW_K43:
			return true
	}
	return false
}

stock ow_primary(id) {
	new wpns[32], num
	new bits = get_user_weapons(id, wpns, num)
	for (new w = 1; w < 32; w++)
		if ((bits & (1 << w)) && ow_is_primary(w))
			return w
	return 0
}

public cmd_own_weapon() {
	new players[32], num
	get_players(players, num, "a")
	g_owA = g_owB = 0
	for (new i = 0; i < num && !g_owB; i++) {
		new wa = ow_primary(players[i]), t = get_user_team(players[i])
		if (!wa || (t != 1 && t != 2))
			continue
		for (new j = 0; j < num; j++) {
			new wb = ow_primary(players[j])
			if (j != i && get_user_team(players[j]) == t && wb && wb != wa) {
				g_owA = players[i]
				g_owB = players[j]
				g_owWpn = wa
				break
			}
		}
	}
	if (!g_owB) {
		log_amx("[OW] ABORT need two live teammates carrying different primaries")
		return PLUGIN_HANDLED
	}
	new aname[32], bname[32], wname[32]
	get_user_name(g_owA, aname, charsmax(aname))
	get_user_name(g_owB, bname, charsmax(bname))
	xmod_get_wpnlogname(g_owWpn, wname, charsmax(wname))
	log_amx("[OW] BEGIN a=%d aname=%s b=%d bname=%s wpn=%s", g_owA, aname, g_owB, bname, wname)
	g_owActive = true
	g_owPicked = false
	user_kill(g_owA)
	set_task(0.3, "ow_drop", 77302)
	return PLUGIN_HANDLED
}

public ow_drop() {
	if (!is_user_connected(g_owA) || !is_user_connected(g_owB) || !dodx_get_user_origin(g_owA, g_owAOrigin)) {
		g_owActive = false
		log_amx("[OW] ABORT a or b left")
		return
	}
	amxclient_cmd(g_owB, "drop")
	set_task(0.5, "ow_touch", 77302)
}

public ow_touch() {
	dodx_set_user_origin(g_owB, g_owAOrigin)
	log_amx("[OW] TOUCH b=%d at %.0f %.0f %.0f", g_owB, g_owAOrigin[0], g_owAOrigin[1], g_owAOrigin[2])
	g_owPolls = 0
	set_task(0.25, "ow_poll", 77302)
}

public ow_poll() {
	if (!g_owPicked && ++g_owPolls < 20) {
		set_task(0.25, "ow_poll", 77302)
		return
	}
	if (!g_owPicked) {
		log_amx("[OW] SYNTHETIC no real pickup in 5 s")
		if (callfunc_begin("dod_client_weaponpickup", "stats_logging.amxx") == 1) {
			callfunc_push_int(g_owB)
			callfunc_push_int(g_owWpn)
			callfunc_push_int(1)
			callfunc_end()
		}
	}
	dodx_test_dispatch_client_death(g_owB, g_owA, g_owWpn, 2, 1)
	ad_flush_stats_capture()
	g_owActive = false
	log_amx("[OW] END mode=%s", g_owPicked ? "real" : "synthetic")
}

public dod_client_weaponpickup(id, weapon, value) {
	if (!g_owActive || id != g_owB)
		return
	log_amx("[OW] FWD id=%d wpn=%d value=%d", id, weapon, value)
	if (value && weapon == g_owWpn)
		g_owPicked = true
}
