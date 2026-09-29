/* Spike S0 of KTPR_SPATIAL_PLAN.md: does ReAPI get_entvar work on DoD in
 * extension mode, and is a capture zone's absmin/absmax usable as geometry?
 * Spec: docs/handover/SPIKE_ENTVAR_GEOMETRY.md. Local stack only.
 *
 * Every read is checked against a second, independent source. A native that
 * registers and returns without error is not proof that it returns the truth.
 *
 *   entvar_static   T1 + T2 + T3 + "also worth grabbing", with controls
 *   entvar_neg      out-of-range index and unknown member id (both must error)
 *   entvar_poll <s> T4: sample every <s> seconds until entvar_stop
 *   entvar_summary  T4 counters for the current map
 *   entvar_reset    zero the T4 counters (extension mode keeps globals across maps)
 *
 * Output goes to log_message (game log) and addons/ktpamx/logs/ktp_entvar_spike.log,
 * every line prefixed [ENTVAR].
 */
#include <amxmodx>
#include <dodx>
#include <reapi>

#define MAX_CP 16
#define DETAIL_CAP 40

new const LOGFILE[] = "ktp_entvar_spike.log";

new Float:g_poll_interval = 0.5;
new bool:g_polling = false;

// Per-map T4 counters. Index 0 = origin-in-AABB, 1 = player-bbox-overlaps-AABB,
// 2 = bbox overlap counting dead players too, 3 = negative control (AABB shifted
// 4096u on x, must disagree whenever a zone is occupied), 4/5 = 1/2 but not
// counting the team that already owns the flag.
#define METHODS 6
new g_samples;
new g_occupied;
new g_mismatch[METHODS];
new g_mismatch_occ[METHODS];
new g_over[METHODS];
new g_under[METHODS];
new g_bbox_reads;
new g_bbox_diff;
new g_details;
new g_polls;

// Lag-tolerant view of the bbox method: the engine's count is updated on its own
// schedule, so a sample only counts as a mismatch here if the engine's count
// matches none of our counts over the last LAG_WIN polls.
#define LAG_WIN 10
new g_hist_a[MAX_CP][LAG_WIN], g_hist_x[MAX_CP][LAG_WIN], g_hist_n[MAX_CP], g_hist_pos[MAX_CP];
new g_cp_occ[MAX_CP], g_cp_mis[MAX_CP], g_cp_over[MAX_CP], g_cp_lagmis[MAX_CP];
new g_lag_mis, g_lag_over, g_lag_under, g_lag_mixed, g_lag_samples;

stock say_log(const fmt[], any:...) {
    static buf[512];
    vformat(buf, charsmax(buf), fmt, 2);
    log_message("[ENTVAR] %s", buf);
    log_to_file(LOGFILE, "[ENTVAR] %s", buf);
}

public plugin_init() {
    register_plugin("KTP Entvar Spike", "1.0", "KTP");
    register_srvcmd("entvar_static", "cmd_static");
    register_srvcmd("entvar_neg", "cmd_neg");
    register_srvcmd("entvar_poll", "cmd_poll");
    register_srvcmd("entvar_stop", "cmd_stop");
    register_srvcmd("entvar_summary", "cmd_summary");
    register_srvcmd("entvar_reset", "cmd_reset");
    register_srvcmd("entvar_dump", "cmd_dump");
}

stock map_name(out[], len) {
    get_mapname(out, len);
}

stock bool:veq(const Float:a[3], const Float:b[3], Float:tol) {
    for (new k = 0; k < 3; k++) {
        if (floatabs(a[k] - b[k]) > tol) return false;
    }
    return true;
}

stock bool:vzero(const Float:a[3]) {
    return a[0] == 0.0 && a[1] == 0.0 && a[2] == 0.0;
}

stock bool:point_in(const Float:p[3], const Float:mn[3], const Float:mx[3]) {
    for (new k = 0; k < 3; k++) {
        if (p[k] < mn[k] || p[k] > mx[k]) return false;
    }
    return true;
}

// Inclusive, the same test as the engine's BoundsIntersect.
stock bool:box_overlap(const Float:amn[3], const Float:amx[3], const Float:bmn[3], const Float:bmx[3]) {
    for (new k = 0; k < 3; k++) {
        if (amn[k] > bmx[k] || amx[k] < bmn[k]) return false;
    }
    return true;
}

// ------------------------------------------------------------------ T1-T3

public cmd_static() {
    new map[32];
    map_name(map, charsmax(map));
    say_log("static begin map=%s maxplayers=%d cp_identity_resolved=%d",
        map, get_maxplayers(), dodx_cp_identity_resolved());

    run_t1();
    run_t2();
    run_t3();

    say_log("static end map=%s", map);
    return PLUGIN_HANDLED;
}

run_t1() {
    new maxp = get_maxplayers();
    new tested = 0, pass = 0, zero = 0, negctl_caught = 0;
    say_log("T1 begin");
    for (new id = 1; id <= maxp; id++) {
        if (!is_user_connected(id)) continue;
        new name[32], cls[32];
        get_user_name(id, name, charsmax(name));

        new Float:ev[3], Float:dx[3], Float:ang[3];
        new rv = get_entvar(id, var_origin, ev);
        new rc = get_entvar(id, var_classname, cls, charsmax(cls));
        new dr = dodx_get_user_origin(id, dx);
        get_entvar(id, var_angles, ang);
        new pevteam = get_entvar(id, var_team);
        new amxteam = get_user_team(id);
        new alive = is_user_alive(id);

        tested++;
        if (vzero(ev)) zero++;
        new bool:ok = dr && veq(ev, dx, 0.001);
        if (ok) pass++;
        // Negative control: angles are not the origin. If this "matches", the
        // comparison is not discriminating and the pass above means nothing.
        new bool:neg_match = veq(ang, dx, 0.001);
        if (!neg_match) negctl_caught++;

        say_log("T1 id=%d name=%s alive=%d cls=%s(rc=%d) get_entvar_origin=(%.3f %.3f %.3f) rv=%d dodx_origin=(%.3f %.3f %.3f) dr=%d match=%d negctl_angles_match=%d pev_team=%d get_user_team=%d",
            id, name, alive, cls, rc, ev[0], ev[1], ev[2], rv, dx[0], dx[1], dx[2], dr, ok ? 1 : 0, neg_match ? 1 : 0, pevteam, amxteam);
    }
    say_log("T1 end tested=%d match=%d zero_vectors=%d negctl_discriminated=%d/%d", tested, pass, zero, negctl_caught, tested);
}

run_t2() {
    new Float:mn[3], Float:mx[3], Float:smn[3], Float:smx[3], Float:org[3];
    new cls[32], model[64];
    say_log("T2 begin");
    new r1 = get_entvar(0, var_absmin, mn);
    new r2 = get_entvar(0, var_absmax, mx);
    get_entvar(0, var_mins, smn);
    get_entvar(0, var_maxs, smx);
    get_entvar(0, var_origin, org);
    get_entvar(0, var_classname, cls, charsmax(cls));
    get_entvar(0, var_model, model, charsmax(model));
    new solid = get_entvar(0, var_solid);
    new modelindex = get_entvar(0, var_modelindex);
    say_log("T2 world cls=%s model=%s solid=%d modelindex=%d absmin=(%.1f %.1f %.1f) absmax=(%.1f %.1f %.1f) r=%d,%d mins=(%.1f %.1f %.1f) maxs=(%.1f %.1f %.1f) origin=(%.1f %.1f %.1f) extent=(%.1f %.1f %.1f)",
        cls, model, solid, modelindex, mn[0], mn[1], mn[2], mx[0], mx[1], mx[2], r1, r2,
        smn[0], smn[1], smn[2], smx[0], smx[1], smx[2], org[0], org[1], org[2],
        mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2]);
    // Entity 0 is never linked (SV_LinkEdict skips the world), so its abs box
    // cannot be map extents. Collect what Pawn CAN reach instead: the union of
    // every in-use entity's origin and abs box, and the spawn-point centroids.
    new Float:umn[3] = { 99999.0, 99999.0, 99999.0 }, Float:umx[3] = { -99999.0, -99999.0, -99999.0 };
    new Float:sa[3], Float:sx[3], na = 0, nx = 0, used = 0;
    for (new e = 1; e < 900; e++) {
        new ec[32];
        ec[0] = 0;
        get_entvar(e, var_classname, ec, charsmax(ec));
        if (!ec[0]) continue;
        used++;
        new Float:eo[3], Float:emn[3], Float:emx[3];
        get_entvar(e, var_origin, eo);
        get_entvar(e, var_absmin, emn);
        get_entvar(e, var_absmax, emx);
        for (new k = 0; k < 3; k++) {
            if (eo[k] < umn[k]) umn[k] = eo[k];
            if (eo[k] > umx[k]) umx[k] = eo[k];
            if (emx[k] - emn[k] > 0.0) {
                if (emn[k] < umn[k]) umn[k] = emn[k];
                if (emx[k] > umx[k]) umx[k] = emx[k];
            }
        }
        if (equal(ec, "dod_capture_area")) {
            new tg[64], tn[64];
            get_entvar(e, var_target, tg, charsmax(tg));
            get_entvar(e, var_targetname, tn, charsmax(tn));
            say_log("T2 capture_area ent=%d target=%s targetname=%s box=(%.1f %.1f %.1f)-(%.1f %.1f %.1f)",
                e, tg, tn, emn[0], emn[1], emn[2], emx[0], emx[1], emx[2]);
        }
        if (equal(ec, "info_player_allies") || equal(ec, "info_initial_player_allies")) {
            for (new k = 0; k < 3; k++) sa[k] += eo[k];
            na++;
        } else if (equal(ec, "info_player_axis") || equal(ec, "info_initial_player_axis")) {
            for (new k = 0; k < 3; k++) sx[k] += eo[k];
            nx++;
        }
    }
    if (na) for (new k = 0; k < 3; k++) sa[k] /= float(na);
    if (nx) for (new k = 0; k < 3; k++) sx[k] /= float(nx);
    say_log("T2 entity-union in_use=%d min=(%.0f %.0f %.0f) max=(%.0f %.0f %.0f) extent=(%.0f %.0f %.0f)",
        used, umn[0], umn[1], umn[2], umx[0], umx[1], umx[2], umx[0] - umn[0], umx[1] - umn[1], umx[2] - umn[2]);
    say_log("T2 spawns allies n=%d centroid=(%.0f %.0f %.0f) axis n=%d centroid=(%.0f %.0f %.0f)",
        na, sa[0], sa[1], sa[2], nx, sx[0], sx[1], sx[2]);
    say_log("T2 end");
}

run_t3() {
    new n = dodx_objectives_get_num();
    say_log("T3 begin n=%d", n);
    new agree = 0, contains = 0, sane = 0, distinct_ents = 0;
    new seen[MAX_CP];
    for (new i = 0; i < n && i < MAX_CP; i++) {
        new cptn[64];
        dodx_objective_get_data(i, CP_targetname, cptn, charsmax(cptn));
        new cpname[64], cpcls[32], acls[32], atn[64], atarget[64], amodel[16];
        dodx_objective_get_data(i, CP_name, cpname, charsmax(cpname));
        new cpx = dodx_objective_get_data(i, CP_origin_x);
        new cpy = dodx_objective_get_data(i, CP_origin_y);
        new cpe = dodx_objective_get_data(i, CP_edict);
        new ent = dodx_area_get_data(i, CA_edict);

        new Float:cpo[3];
        new cpr = 0;
        if (cpe > 0) {
            cpr = get_entvar(cpe, var_origin, cpo);
            get_entvar(cpe, var_classname, cpcls, charsmax(cpcls));
        }

        new Float:cmn[3], Float:cmx[3], cmodel[32];
        new csolid = 0;
        if (cpe > 0) {
            get_entvar(cpe, var_absmin, cmn);
            get_entvar(cpe, var_absmax, cmx);
            get_entvar(cpe, var_model, cmodel, charsmax(cmodel));
            csolid = get_entvar(cpe, var_solid);
        }
        say_log("T3 cp=%d cp_edict_box=(%.1f %.1f %.1f)-(%.1f %.1f %.1f) cp_solid=%d cp_model=%s can_touch=%d",
            i, cmn[0], cmn[1], cmn[2], cmx[0], cmx[1], cmx[2], csolid, cmodel, dodx_objective_get_data(i, CP_can_touch));

        if (ent <= 0) {
            say_log("T3 cp=%d name=%s targetname=%s area_edict=%d NO AREA cp_edict=%d cp_cls=%s", i, cpname, cptn, ent, cpe, cpcls);
            continue;
        }

        new dup = 0;
        for (new j = 0; j < i; j++) if (seen[j] == ent) dup = 1;
        seen[i] = ent;
        if (!dup) distinct_ents++;

        new Float:mn[3], Float:mx[3], Float:bmn[3], Float:bmx[3], Float:smn[3], Float:smx[3], Float:ao[3];
        get_entvar(ent, var_absmin, mn);
        get_entvar(ent, var_absmax, mx);
        get_entvar(ent, var_mins, smn);
        get_entvar(ent, var_maxs, smx);
        get_entvar(ent, var_origin, ao);
        get_entvar(ent, var_classname, acls, charsmax(acls));
        get_entvar(ent, var_targetname, atn, charsmax(atn));
        get_entvar(ent, var_target, atarget, charsmax(atarget));
        get_entvar(ent, var_model, amodel, charsmax(amodel));
        new solid = get_entvar(ent, var_solid);
        new br = dodx_area_get_bounds(i, bmn, bmx);

        // Ground truth for the read itself: dodx reads pEdict->v.absmin/absmax in C++.
        new bool:same = br && veq(mn, bmn, 0.0) && veq(mx, bmx, 0.0);
        if (same) agree++;

        new Float:p[3];
        p[0] = float(cpx); p[1] = float(cpy); p[2] = 0.0;
        new bool:inxy = p[0] >= mn[0] && p[0] <= mx[0] && p[1] >= mn[1] && p[1] <= mx[1];
        if (inxy) contains++;

        new Float:vol = (mx[0] - mn[0]) * (mx[1] - mn[1]) * (mx[2] - mn[2]);
        new bool:ok = true;
        for (new k = 0; k < 3; k++) if (mx[k] - mn[k] <= 0.0 || mx[k] - mn[k] > 4096.0) ok = false;
        if (ok) sane++;

        // absmin should be origin + mins - 1 (SV_LinkEdict pads by one unit).
        new Float:exp_mn[3], Float:exp_mx[3];
        for (new k = 0; k < 3; k++) { exp_mn[k] = ao[k] + smn[k] - 1.0; exp_mx[k] = ao[k] + smx[k] + 1.0; }
        new pad_ok = veq(mn, exp_mn, 0.01) && veq(mx, exp_mx, 0.01);

        say_log("T3 cp=%d name=%s area_ent=%d dup=%d cls=%s model=%s solid=%d targetname=%s target=%s absmin=(%.1f %.1f %.1f) absmax=(%.1f %.1f %.1f) size=(%.1f %.1f %.1f) vol=%.0f dodx_bounds=(%.1f %.1f %.1f)-(%.1f %.1f %.1f) br=%d exact_match=%d origin+mins-1=%d",
            i, cpname, ent, dup, acls, amodel, solid, atn, atarget, mn[0], mn[1], mn[2], mx[0], mx[1], mx[2],
            mx[0] - mn[0], mx[1] - mn[1], mx[2] - mn[2], vol, bmn[0], bmn[1], bmn[2], bmx[0], bmx[1], bmx[2], br, same ? 1 : 0, pad_ok);
        say_log("T3 cp=%d CP_origin=(%d %d) in_box_xy=%d cp_edict=%d cp_cls=%s cp_var_origin=(%.2f %.2f %.2f) r=%d cp_origin_xy_agrees=%d",
            i, cpx, cpy, inxy ? 1 : 0, cpe, cpcls, cpo[0], cpo[1], cpo[2], cpr,
            (floatabs(float(floatround(cpo[0], floatround_tozero)) - float(cpx)) <= 1.0 && floatabs(float(floatround(cpo[1], floatround_tozero)) - float(cpy)) <= 1.0) ? 1 : 0);
    }
    say_log("T3 end n=%d distinct_area_ents=%d exact_match_dodx_bounds=%d cp_xy_in_box=%d sane_volume=%d", n, distinct_ents, agree, contains, sane);
}

// ------------------------------------------------------------------ negative

public cmd_neg() {
    // Each call is expected to raise a native error, which aborts this callback,
    // so one per invocation: entvar_neg 1 / entvar_neg 2.
    new arg[8];
    read_argv(1, arg, charsmax(arg));
    new which = str_to_num(arg);
    new Float:v[3];
    say_log("NEG begin case=%d", which);
    if (which == 1) {
        new r = get_entvar(-1, var_origin, v);
        say_log("NEG case=1 index=-1 returned=%d (reaching this line means no error was raised)", r);
    } else if (which == 2) {
        new r = get_entvar(100000, var_origin, v);
        say_log("NEG case=2 index=100000 returned=%d (reaching this line means no error was raised)", r);
    } else if (which == 3) {
        new r = get_entvar(1, EntVars:99999, v);
        say_log("NEG case=3 member=99999 returned=%d (reaching this line means no error was raised)", r);
    } else if (which == 4) {
        // A free edict slot: valid index, no entity. Records what comes back.
        new last = 0;
        for (new e = 900; e < 1400; e++) {
            new cls[32];
            cls[0] = 0;
            get_entvar(e, var_classname, cls, charsmax(cls));
            if (!cls[0]) { last = e; break; }
        }
        new r = get_entvar(last, var_origin, v);
        say_log("NEG case=4 free-slot index=%d returned=%d origin=(%.1f %.1f %.1f)", last, r, v[0], v[1], v[2]);
    }
    say_log("NEG end case=%d", which);
    return PLUGIN_HANDLED;
}

// ------------------------------------------------------------------ T4

public cmd_poll() {
    new arg[16];
    read_argv(1, arg, charsmax(arg));
    if (arg[0]) g_poll_interval = str_to_float(arg);
    if (g_poll_interval < 0.05) g_poll_interval = 0.05;
    remove_task(4242);
    set_task(g_poll_interval, "task_poll", 4242, _, _, "b");
    g_polling = true;
    say_log("T4 poll start interval=%.2f", g_poll_interval);
    return PLUGIN_HANDLED;
}

public cmd_stop() {
    remove_task(4242);
    g_polling = false;
    say_log("T4 poll stop");
    return PLUGIN_HANDLED;
}

public cmd_reset() {
    g_samples = 0; g_occupied = 0; g_bbox_reads = 0; g_bbox_diff = 0; g_details = 0; g_polls = 0;
    g_lag_mis = 0; g_lag_over = 0; g_lag_under = 0; g_lag_mixed = 0; g_lag_samples = 0;
    for (new i = 0; i < MAX_CP; i++) { g_hist_n[i] = 0; g_hist_pos[i] = 0; g_cp_occ[i] = 0; g_cp_mis[i] = 0; g_cp_over[i] = 0; g_cp_lagmis[i] = 0; }
    for (new m = 0; m < METHODS; m++) { g_mismatch[m] = 0; g_mismatch_occ[m] = 0; g_over[m] = 0; g_under[m] = 0; }
    say_log("T4 reset");
    return PLUGIN_HANDLED;
}

public cmd_summary() {
    new map[32];
    map_name(map, charsmax(map));
    say_log("T4 summary map=%s polls=%d zone_samples=%d occupied_samples=%d polling=%d", map, g_polls, g_samples, g_occupied, g_polling ? 1 : 0);
    new const names[METHODS][] = { "origin_in_aabb", "bbox_overlap_aabb", "bbox_overlap_incl_dead", "NEGCTL_shifted_aabb", "bbox_nonowner", "bbox_incl_dead_nonowner" };
    for (new m = 0; m < METHODS; m++) {
        say_log("T4 summary map=%s method=%s mismatch_all=%d/%d mismatch_occupied=%d/%d over(ours>engine)=%d under(ours<engine)=%d",
            map, names[m], g_mismatch[m], g_samples, g_mismatch_occ[m], g_occupied, g_over[m], g_under[m]);
    }
    say_log("T4 summary map=%s method=bbox_overlap_aabb_lagtol(window=%d polls) mismatch_occupied=%d/%d persistent_over=%d persistent_under=%d mixed=%d",
        map, LAG_WIN, g_lag_mis, g_lag_samples, g_lag_over, g_lag_under, g_lag_mixed);
    for (new i = 0; i < MAX_CP; i++) {
        if (!g_cp_occ[i]) continue;
        say_log("T4 summary map=%s cp=%d bbox occupied=%d mismatch=%d over=%d lagtol_mismatch=%d", map, i, g_cp_occ[i], g_cp_mis[i], g_cp_over[i], g_cp_lagmis[i]);
    }
    say_log("T4 summary map=%s player_bbox get_entvar_vs_dodx_get_user_bounds diff=%d/%d",
        map, g_bbox_diff, g_bbox_reads);
    return PLUGIN_HANDLED;
}

public cmd_dump() {
    // One-shot per-zone state with every alive player's distance to each box.
    task_poll_impl(true);
    return PLUGIN_HANDLED;
}

public task_poll() {
    task_poll_impl(false);
}

task_poll_impl(bool:verbose) {
    static Float:org[33][3], Float:pmn[33][3], Float:pmx[33][3];
    static bool:valid[33], bool:alive[33], team[33];
    new maxp = get_maxplayers();
    if (maxp > 32) maxp = 32;

    g_polls++;
    for (new id = 1; id <= maxp; id++) {
        valid[id] = bool:is_user_connected(id);
        if (!valid[id]) continue;
        alive[id] = bool:is_user_alive(id);
        team[id] = get_user_team(id);
        get_entvar(id, var_origin, org[id]);
        get_entvar(id, var_absmin, pmn[id]);
        get_entvar(id, var_absmax, pmx[id]);
        new Float:dmn[3], Float:dmx[3];
        if (dodx_get_user_bounds(id, dmn, dmx)) {
            g_bbox_reads++;
            if (!veq(dmn, pmn[id], 0.0) || !veq(dmx, pmx[id], 0.0)) g_bbox_diff++;
        }
    }

    new n = dodx_objectives_get_num();
    for (new i = 0; i < n && i < MAX_CP; i++) {
        new ent = dodx_area_get_data(i, CA_edict);
        if (ent <= 0) continue;
        new Float:amn[3], Float:amx[3], Float:smn[3], Float:smx[3];
        get_entvar(ent, var_absmin, amn);
        get_entvar(ent, var_absmax, amx);
        for (new k = 0; k < 3; k++) { smn[k] = amn[k]; smx[k] = amx[k]; }
        smn[0] += 4096.0; smx[0] += 4096.0;

        new owner = dodx_objective_get_data(i, CP_owner);
        new ea = dodx_area_get_data(i, CA_num_allies);
        new ex = dodx_area_get_data(i, CA_num_axis);

        new ca[METHODS], cx[METHODS];
        for (new m = 0; m < METHODS; m++) { ca[m] = 0; cx[m] = 0; }
        for (new id = 1; id <= maxp; id++) {
            if (!valid[id]) continue;
            new t = team[id];
            if (t != 1 && t != 2) continue;
            new bool:in[METHODS];
            in[0] = alive[id] && point_in(org[id], amn, amx);
            in[1] = alive[id] && box_overlap(pmn[id], pmx[id], amn, amx);
            in[2] = box_overlap(pmn[id], pmx[id], amn, amx);
            in[3] = alive[id] && box_overlap(pmn[id], pmx[id], smn, smx);
            in[4] = in[1] && t != owner;
            in[5] = in[2] && t != owner;
            for (new m = 0; m < METHODS; m++) {
                if (!in[m]) continue;
                if (t == 1) ca[m]++; else cx[m]++;
            }
        }

        g_samples++;
        new bool:occ = (ea + ex) > 0;
        for (new m = 0; m < 3; m++) if (ca[m] + cx[m] > 0) occ = true;
        if (occ) g_occupied++;

        for (new m = 0; m < METHODS; m++) {
            new bool:mis = (ca[m] != ea) || (cx[m] != ex);
            if (!mis) continue;
            g_mismatch[m]++;
            if (occ) g_mismatch_occ[m]++;
            if (ca[m] + cx[m] > ea + ex) g_over[m]++;
            else if (ca[m] + cx[m] < ea + ex) g_under[m]++;
        }

        if (!verbose) {
            new hp = g_hist_pos[i];
            g_hist_a[i][hp] = ca[1]; g_hist_x[i][hp] = cx[1];
            g_hist_pos[i] = (hp + 1) % LAG_WIN;
            if (g_hist_n[i] < LAG_WIN) g_hist_n[i]++;
            if (occ && g_hist_n[i] == LAG_WIN) {
                g_lag_samples++;
                new bool:hit = false, nover = 0, nunder = 0;
                for (new h = 0; h < LAG_WIN; h++) {
                    if (g_hist_a[i][h] == ea && g_hist_x[i][h] == ex) hit = true;
                    new tot = g_hist_a[i][h] + g_hist_x[i][h];
                    if (tot > ea + ex) nover++; else if (tot < ea + ex) nunder++;
                }
                if (!hit) {
                    g_lag_mis++;
                    g_cp_lagmis[i]++;
                    if (nover == LAG_WIN) g_lag_over++;
                    else if (nunder == LAG_WIN) g_lag_under++;
                    else g_lag_mixed++;
                }
            }
        }

        new bool:mis1 = (ca[1] != ea) || (cx[1] != ex);
        if (!verbose && occ) {
            g_cp_occ[i]++;
            if (mis1) { g_cp_mis[i]++; if (ca[1] + cx[1] > ea + ex) g_cp_over[i]++; }
        }
        if (verbose || (mis1 && g_details < DETAIL_CAP)) {
            if (!verbose) g_details++;
            say_log("T4 %s cp=%d owner=%d ca_owner=%d capping=%d/%d engine=%d/%d origin_pt=%d/%d bbox=%d/%d bbox_incl_dead=%d/%d negctl=%d/%d nonowner=%d/%d box=(%.0f %.0f %.0f)-(%.0f %.0f %.0f)",
                verbose ? "dump" : "mismatch", i, owner, dodx_area_get_data(i, CA_owning_team), dodx_area_get_data(i, CA_is_capturing), dodx_area_get_data(i, CA_capturing_team),
                ea, ex, ca[0], cx[0], ca[1], cx[1], ca[2], cx[2], ca[3], cx[3], ca[4], cx[4],
                amn[0], amn[1], amn[2], amx[0], amx[1], amx[2]);
            // Players near this box: who we count and how far outside the box they are.
            for (new id = 1; id <= maxp; id++) {
                if (!valid[id] || (team[id] != 1 && team[id] != 2)) continue;
                new Float:gap = 0.0;
                for (new k = 0; k < 3; k++) {
                    new Float:d = 0.0;
                    if (pmx[id][k] < amn[k]) d = amn[k] - pmx[id][k];
                    else if (pmn[id][k] > amx[k]) d = pmn[id][k] - amx[k];
                    if (d > gap) gap = d;
                }
                if (gap > 128.0) continue;
                say_log("T4   id=%d team=%d alive=%d origin=(%.1f %.1f %.1f) bbox=(%.1f %.1f %.1f)-(%.1f %.1f %.1f) gap=%.1f pt_in=%d",
                    id, team[id], alive[id] ? 1 : 0, org[id][0], org[id][1], org[id][2],
                    pmn[id][0], pmn[id][1], pmn[id][2], pmx[id][0], pmx[id][1], pmx[id][2], gap,
                    point_in(org[id], amn, amx) ? 1 : 0);
            }
        }
    }
}
