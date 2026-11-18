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
#include <reapi>

#define PLUGIN  "KTP Assist Drive"
#define VERSION "0.1"
#define AUTHOR  "KTP"

public plugin_init() {
	register_plugin(PLUGIN, VERSION, AUTHOR)
	register_srvcmd("ktp_ad_run", "cmd_run")
	register_srvcmd("ktp_ad_postmatch_frag", "cmd_postmatch_frag")
	register_srvcmd("ktp_ad_postmatch_damage", "cmd_postmatch_damage")
	register_srvcmd("ktp_vc_run", "cmd_voice")
	register_srvcmd("ktp_vm_run", "cmd_voice_menu")
	register_srvcmd("ktp_ow_run", "cmd_own_weapon")
	register_srvcmd("ktp_dd_run", "cmd_door")
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

// Run after a clean match end: one self-inflicted hit through the real damage
// forward. Self-damage earns no assist credit, so it leaves the next match alone.
public cmd_postmatch_damage() {
	new players[32], num
	get_players(players, num, "a")
	if (!num) {
		log_amx("[AD] PMDMG ABORT need one live player")
		return PLUGIN_HANDLED
	}

	new id = players[0]
	log_amx("[AD] PMDMG BEGIN userid=%d", get_user_userid(id))
	dodx_test_dispatch_damage(id, id, 1, 27, 0, 0)
	ad_flush_stats_capture()
	log_amx("[AD] PMDMG END")
	return PLUGIN_HANDLED
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

// Own-weapon kill drive (stats_logging 1.35.0). Two live teammates A and B carrying different
// primaries. A dies for real (user_kill), so the game drops A's gun; B presses the drop key and is
// put on that dropped gun (not A's body, which it can land well away from), so the game's own touch
// hands B that gun. Every dod_client_weaponpickup the
// DODX poll fires for B is logged as [OW] FWD -- the game-side claim this scenario exists to
// observe. If no real pickup arrives in 8 s, stats_logging's handler is called directly instead
// ([OW] SYNTHETIC) so the ledger is still tested, and the verdict says the engine half was not.
// The kill itself is a dispatched TEAMKILL: no frag_context marker, so no expected no-row diagnostic.
new g_owA, g_owB, g_owWpn, g_owPolls, g_owBits, bool:g_owActive, bool:g_owPicked
new Float:g_owAOrigin[3], g_owBox, g_owBoxCls[40]

stock bool:ow_is_primary(w) {
	switch (w) {
		case DODW_GARAND, DODW_SCOPED_KAR, DODW_THOMPSON, DODW_STG44, DODW_SPRINGFIELD,
			DODW_KAR, DODW_BAR, DODW_MP40, DODW_M1_CARBINE, DODW_GREASEGUN, DODW_FG42, DODW_K43:
			return true
	}
	return false
}

stock ow_bits(id) {
	new wpns[32], num
	return get_user_weapons(id, wpns, num)
}

stock ow_primary(id) {
	new wpns[32], num
	new bits = get_user_weapons(id, wpns, num)
	for (new w = 1; w < 32; w++)
		if ((bits & (1 << w)) && ow_is_primary(w))
			return w
	return 0
}

stock bool:ow_is_player_held(e) {
	new owner = get_entvar(e, var_owner)
	return owner >= 1 && owner <= get_maxplayers() && owner != g_owA
}

// Prefer the weaponbox: a gun packed inside one keeps a stale origin.
stock ow_find_box() {
	new logname[32], wcls[40], best = 0, bool:bestBox = false
	new Float:bestDist = 512.0
	xmod_get_wpnlogname(g_owWpn, logname, charsmax(logname))
	formatex(wcls, charsmax(wcls), "weapon_%s", logname)
	for (new e = get_maxplayers() + 1; e < 900; e++) {
		new ec[40]
		ec[0] = 0
		get_entvar(e, var_classname, ec, charsmax(ec))
		new bool:box = bool:equal(ec, "weaponbox")
		if (!box && !equal(ec, wcls))
			continue
		if (ow_is_player_held(e) || (bestBox && !box))
			continue
		new Float:o[3]
		get_entvar(e, var_origin, o)
		new Float:d = get_distance_f(o, g_owAOrigin)
		if ((box && !bestBox) || d < bestDist) {
			best = e
			bestBox = box
			bestDist = d
			copy(g_owBoxCls, charsmax(g_owBoxCls), ec)
		}
	}
	if (best) {
		new model[64]
		get_entvar(best, var_model, model, charsmax(model))
		log_amx("[OW] GUN ent=%d cls=%s model=%s owner=%d dist=%.0f", best, g_owBoxCls, model,
			get_entvar(best, var_owner), bestDist)
	} else {
		log_amx("[OW] GUN none near a, using a's body")
	}
	return best
}

// The gun can still be sliding when B arrives, so every move re-reads where it is.
stock ow_put_b_on_gun() {
	new Float:o[3]
	if (g_owBox) {
		new ec[40]
		ec[0] = 0
		get_entvar(g_owBox, var_classname, ec, charsmax(ec))
		if (equal(ec, g_owBoxCls)) {
			get_entvar(g_owBox, var_origin, o)
			dodx_set_user_origin(g_owB, o)
			return
		}
	}
	dodx_set_user_origin(g_owB, g_owAOrigin)
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
	// dod.so's drop takes the entity classname; DODX's log name is its suffix.
	new cls[40], logname[32]
	xmod_get_wpnlogname(ow_primary(g_owB), logname, charsmax(logname))
	formatex(cls, charsmax(cls), "weapon_%s", logname)
	// Before B's drop, so B's own gun cannot be the one found.
	g_owBox = ow_find_box()
	g_owBits = ow_bits(g_owB)
	log_amx("[OW] DROP b=%d bits_before=%d cls=%s", g_owB, g_owBits, cls)
	// Extension mode has no Cmd_Argv override, so dod.so reads the engine's last tokenized line,
	// not amxclient_cmd's arguments: tokenize the same line first or the game sees another command.
	server_cmd("drop %s", cls)
	server_exec()
	amxclient_cmd(g_owB, "drop", cls)
	set_task(0.5, "ow_touch", 77302)
}

public ow_touch() {
	log_amx("[OW] DROPPED b=%d bits_after=%d", g_owB, ow_bits(g_owB))
	ow_put_b_on_gun()
	new Float:at[3]
	dodx_get_user_origin(g_owB, at)
	log_amx("[OW] TOUCH b=%d at %.0f %.0f %.0f", g_owB, at[0], at[1], at[2])
	g_owPolls = 0
	set_task(0.25, "ow_poll", 77302)
}

public ow_poll() {
	// Bot AI walks B off the gun; keep it standing on the gun for the whole window.
	new bits = ow_bits(g_owB)
	if (bits != g_owBits) {
		log_amx("[OW] BITS b=%d bits=%d", g_owB, bits)
		g_owBits = bits
	}
	if (!g_owPicked && ++g_owPolls < 32) {
		ow_put_b_on_gun()
		set_task(0.25, "ow_poll", 77302)
		return
	}
	if (!g_owPicked) {
		log_amx("[OW] SYNTHETIC no real pickup in 8 s")
		// The ledger claims by distance, so the claim must happen on the gun.
		ow_put_b_on_gun()
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

// Door hold on dod_thunder2: the door at hinge (-152 -920 -66) is opened from the north by one
// bot, which is then stood south of it, in the leaf's closing arc, facing the given yaw. The
// rotating-door design note (KTP-ReHLDS) models this spot: facing 180 holds, facing 0 does not.
// The bot opens the door and is the door's activator, so its facing is the one DoorGoUp reads.
new const Float:DD_HINGE[3] = { -152.0, -920.0, -66.0 }
new const Float:DD_OPENER[3] = { -124.0, -880.0, -76.0 }
new const Float:DD_VICTIM[3] = { -111.0, -964.0, -76.0 }
// Far enough north that the leaf, finishing a swing to +90 once released, clears the bot.
new const Float:DD_PARK[3] = { -124.0, -820.0, -76.0 }
#define DD_TASK 77303
#define DD_SAMPLES 32

new g_ddDoor, g_ddBot, g_ddLeft, Float:g_ddYaw

stock dd_find_door() {
	for (new e = get_maxplayers() + 1; e < 900; e++) {
		new ec[32]
		ec[0] = 0
		get_entvar(e, var_classname, ec, charsmax(ec))
		if (!equal(ec, "func_door_rotating"))
			continue
		new Float:o[3]
		get_entvar(e, var_origin, o)
		if (get_distance_f(o, DD_HINGE) < 2.0)
			return e
	}
	return 0
}

stock Float:dd_door_yaw() {
	new Float:a[3]
	get_entvar(g_ddDoor, var_angles, a)
	return a[1]
}

// fixangle stops the engine taking a bot's yaw from its usercmd, and nothing clears it for a
// bot because no client data is ever sent to one.
stock dd_face(id, Float:yaw) {
	new Float:a[3]
	a[1] = yaw
	set_entvar(id, var_angles, a)
	set_entvar(id, var_v_angle, a)
	set_entvar(id, var_fixangle, 1)
}

stock dd_put(id, const Float:at[3]) {
	new Float:o[3], Float:still[3]
	o[0] = at[0]
	o[1] = at[1]
	o[2] = at[2]
	dodx_set_user_origin(id, o)
	set_entvar(id, var_velocity, still)
}

stock dd_release(const reason[]) {
	if (is_user_connected(g_ddBot)) {
		set_entvar(g_ddBot, var_fixangle, 0)
		dd_put(g_ddBot, DD_PARK)
	}
	log_amx("[DD] %s", reason)
}

public cmd_door() {
	new arg[16]
	read_argv(1, arg, charsmax(arg))
	g_ddYaw = str_to_float(arg)
	remove_task(DD_TASK)

	g_ddDoor = dd_find_door()
	if (!g_ddDoor) {
		log_amx("[DD] ABORT door not found at the thunder2 hinge")
		return PLUGIN_HANDLED
	}
	new players[32], num
	get_players(players, num, "a")
	if (!num) {
		log_amx("[DD] ABORT need one live player")
		return PLUGIN_HANDLED
	}
	new Float:avel[3]
	get_entvar(g_ddDoor, var_avelocity, avel)
	if (floatabs(dd_door_yaw()) > 1.0 || avel[1] != 0.0) {
		log_amx("[DD] ABORT door not closed door_yaw=%.1f door_avel=%.1f", dd_door_yaw(), avel[1])
		return PLUGIN_HANDLED
	}

	g_ddBot = players[0]
	log_amx("[DD] BEGIN userid=%d door=%d yaw=%.1f", get_user_userid(g_ddBot), g_ddDoor, g_ddYaw)
	// Walk the bot into the closed leaf from the north, facing south: the touch opens it
	// away from him, to -90, and makes him the activator.
	dd_put(g_ddBot, DD_OPENER)
	dd_face(g_ddBot, -90.0)
	new Float:push[3]
	push[1] = -400.0
	set_entvar(g_ddBot, var_velocity, push)
	set_task(1.5, "dd_place", DD_TASK)
	return PLUGIN_HANDLED
}

public dd_place() {
	if (!is_user_alive(g_ddBot)) {
		log_amx("[DD] ABORT the bot died or left")
		return
	}
	new Float:yaw = dd_door_yaw()
	if (yaw > -85.0) {
		dd_release("ABORT door did not open to the south side")
		log_amx("[DD] door_yaw=%.1f", yaw)
		return
	}
	log_amx("[DD] OPENED door_yaw=%.1f", yaw)
	dd_put(g_ddBot, DD_VICTIM)
	dd_face(g_ddBot, g_ddYaw)
	log_amx("[DD] PLACED yaw=%.1f", g_ddYaw)
	g_ddLeft = DD_SAMPLES
	set_task(0.5, "dd_sample", DD_TASK)
}

public dd_sample() {
	if (!is_user_alive(g_ddBot)) {
		log_amx("[DD] ABORT the bot died or left")
		return
	}
	new Float:o[3], Float:a[3], Float:davel[3]
	get_entvar(g_ddBot, var_origin, o)
	get_entvar(g_ddBot, var_angles, a)
	get_entvar(g_ddDoor, var_avelocity, davel)
	log_amx("[DD] SAMPLE door_yaw=%.2f door_avel=%.1f bot=%.1f %.1f %.1f bot_yaw=%.1f",
		dd_door_yaw(), davel[1], o[0], o[1], o[2], a[1])
	if (--g_ddLeft > 0) {
		set_task(0.5, "dd_sample", DD_TASK)
		return
	}
	dd_release("END")
}
