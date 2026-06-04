"""Map pick/ban veto for BO3 bracket matches — captain-driven, turn-gated.

KTP TS-advantage model, generalised to any pool size: bans = pool - 3 (two map
picks + one decider). The top seed (TS) bans first AND last so it controls the
decider; the lower seed (LS) fills the bans in the middle. The team that PICKS a
map also picks its side; TS picks the decider's side. State is the replayed
action log in lan_veto; when complete the maps are written to lan_bracket.map.
"""
from __future__ import annotations

SIDES = ["Allies", "Axis"]


def pool_maps() -> list[str]:
    """The veto map pool — the configured LAN map list. The sequence adapts to
    however many maps it holds."""
    from . import schedule as sched
    return list(sched.COMP_MAPS)


def sequence(pool_size: int) -> list[dict]:
    """Ordered BO3 veto steps for `pool_size` maps. Each step: {actor, action}.
    TS bans first + last; LS bans the middle; two picks then a decider."""
    bans = pool_size - 3
    if bans < 0:
        return []
    ts_bans = min(2, bans)
    ls_bans = bans - ts_bans
    steps: list[dict] = []
    if ts_bans >= 1:
        steps.append({"actor": "TS", "action": "ban"})      # TS opens
    if ls_bans >= 1:
        steps.append({"actor": "LS", "action": "ban"})      # one LS ban before picks
    steps.append({"actor": "TS", "action": "pick"})
    steps.append({"actor": "LS", "action": "pick"})
    for _ in range(max(0, ls_bans - 1)):                    # remaining LS bans
        steps.append({"actor": "LS", "action": "ban"})
    if ts_bans >= 2:
        steps.append({"actor": "TS", "action": "ban"})      # TS bans last -> controls decider
    steps.append({"actor": "TS", "action": "decider"})
    return steps


def _ts_ls(team_a: int, team_b: int) -> tuple[int, int]:
    """(TS team id, LS team id) by playoff seed — lower rank number is the top seed."""
    from . import bracket
    seed_of = {tid: rank for rank, tid in bracket._stored_rank_map().items()}
    ra, rb = seed_of.get(team_a, 999), seed_of.get(team_b, 999)
    return (team_a, team_b) if ra <= rb else (team_b, team_a)


def get_state(mkey: str):
    """Full veto state for a match, or None if the match key is unknown."""
    from . import bracket, db
    meta = bracket.BY_KEY.get(mkey)
    if not meta:
        return None
    if meta["best_of"] != 3:
        return {"mkey": mkey, "label": meta["label"], "supported": False, "ready": False}
    row = db.query_one(
        "SELECT b.team_a_id, b.team_b_id, ta.name AS a_name, tb.name AS b_name "
        "FROM lan_bracket b LEFT JOIN lan_teams ta ON ta.id=b.team_a_id "
        "LEFT JOIN lan_teams tb ON tb.id=b.team_b_id WHERE b.mkey=%s", (mkey,)
    )
    base = {"mkey": mkey, "label": meta["label"], "supported": True, "ready": False}
    if not row or not row["team_a_id"] or not row["team_b_id"]:
        return base
    ts_id, ls_id = _ts_ls(row["team_a_id"], row["team_b_id"])
    names = {row["team_a_id"]: row["a_name"], row["team_b_id"]: row["b_name"]}
    pool = pool_maps()
    seq = sequence(len(pool))
    actions = db.query_all("SELECT * FROM lan_veto WHERE mkey=%s ORDER BY step_no", (mkey,))
    used = {a["map"] for a in actions if a["map"]}
    remaining = [m for m in pool if m not in used]
    step_no = len(actions)
    current = seq[step_no] if step_no < len(seq) else None
    complete = bool(seq) and step_no >= len(seq)
    result = [a["map"] for a in actions if a["action"] in ("pick", "decider")]
    # per-map display status for the board tiles
    map_status, order = {}, 0
    for a in actions:
        if not a["map"]:
            continue
        if a["action"] in ("pick", "decider"):
            order += 1
            map_status[a["map"]] = {"kind": "pick", "actor": a["actor"], "side": a["side"], "order": order}
        else:
            map_status[a["map"]] = {"kind": "ban", "actor": a["actor"]}
    current_team = None
    if current:
        current_team = ts_id if current["actor"] == "TS" else ls_id
    base.update(
        ready=True, ts_id=ts_id, ls_id=ls_id,
        ts_name=names.get(ts_id), ls_name=names.get(ls_id),
        pool=pool, remaining=remaining, used=used,
        seq=seq, actions=actions, step_no=step_no,
        current=current, current_team=current_team, map_status=map_status,
        complete=complete, result_maps=result, sides=SIDES,
    )
    return base


def act(mkey: str, by_discord, mapname, side):
    """Record the current step's action (validated against the live state).
    Finalises maps onto the bracket row when the sequence completes."""
    from . import db
    st = get_state(mkey)
    if not st or not st.get("ready"):
        raise ValueError("This veto isn't ready yet.")
    if st["complete"]:
        raise ValueError("This veto is already complete.")
    cur = st["current"]
    action = cur["action"]
    if action == "decider":
        if len(st["remaining"]) != 1:
            raise ValueError("Decider isn't down to one map yet.")
        mapname, side = st["remaining"][0], (side or "").strip()
        if side not in SIDES:
            raise ValueError("Pick a side for the decider.")
    elif action == "ban":
        if mapname not in st["remaining"]:
            raise ValueError("That map isn't available to ban.")
        side = None
    elif action == "pick":
        if mapname not in st["remaining"]:
            raise ValueError("That map isn't available to pick.")
        side = (side or "").strip()
        if side not in SIDES:
            raise ValueError("Pick a side for your map.")
    db.execute(
        "INSERT INTO lan_veto (mkey, step_no, actor, action, map, side, by_discord) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (mkey, st["step_no"], cur["actor"], action, mapname, side, by_discord),
    )
    after = get_state(mkey)
    if after["complete"]:
        from . import bracket
        bracket.set_map(mkey, " / ".join(after["result_maps"])[:96] or None)


def reset(mkey: str):
    """Admin: wipe a veto so it can be re-run."""
    from . import db
    db.execute("DELETE FROM lan_veto WHERE mkey=%s", (mkey,))
