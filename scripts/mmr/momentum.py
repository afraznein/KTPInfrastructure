"""Momentum credit: a deposit/payout ledger over a half's kill and flag events.

The question this answers: a 4k at 0:00 that leads to a mid cap at 1:30 and a
capout at 3:00 -- how much of that objective value belongs to the 4k?

The mechanism, in one loop:
  * Every momentum event (multikill, cap, capout) is both a PAYOUT and a
    DEPOSIT for its team's ledger.
  * Payout: the event's objective value is split between the actor(s) and
    the team's outstanding deposits. The momentum share at lag d is the
    attributable fraction AF(d) = 1 - 1/lift(d), where lift(d) is the
    measured ratio P(objective within d of a multikill) / P(objective in any
    window of that length). Fitted, never chosen: see `lag_lift` / `fit_lift`.
  * Deposit: the event enters the ledger with its own value, and PASSES ON a
    fraction rho of anything it is later paid to its own upstream depositors.
    That is the hockey secondary assist -- capout pays the cap (primary), the
    cap forwards rho of it to the 4k (secondary), depth dilutes geometrically.
  * Chain break: an enemy cap clears the team's ledger. Momentum was answered.

Kills themselves earn nothing here -- KTPR already counts them. This is the
objective lift a multikill produced, and only that, so it can be added to the
KTPR components without double counting.

Pure functions over the TSVs `momentum_fetch.py` writes. No network.
"""
from __future__ import annotations

import csv
import math
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from pathlib import Path

DATA = Path(__file__).resolve().parent / "data" / "events"

MULTIKILL_GAP = 10.0     # seconds between consecutive kills for them to chain
MULTIKILL_MIN = 3        # 3k and up
CAP_VALUE = 1.0
CAPOUT_VALUE = 1.0       # on top of the cap that completed it; calibrate vs scoreboard
LAG_BINS = ((0, 15), (15, 30), (30, 45), (45, 60), (60, 90), (90, 120), (120, 180), (180, 240))


# ---------------------------------------------------------------- reading

def read(name, data=DATA):
    with open(Path(data) / f"{name}.tsv", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def _f(x):
    return float(x) if x not in (None, "", "NULL") else None


def sides(lives):
    """{(match, half): {player: 1|2}} -- the side a player was on in that half.

    Life boundaries carry the side per row; the mode wins (a mid-half team
    switch is noise for this purpose). The roster table's `team` is the side
    at the END of the match and cannot be used per half.
    """
    votes = defaultdict(lambda: defaultdict(Counter))
    for r in lives:
        team = int(r["team"])
        if team in (1, 2):
            votes[(r["match_id"], int(r["half"]))][int(r["player_id"])][team] += 1
    return {k: {pid: c.most_common(1)[0][0] for pid, c in v.items()} for k, v in votes.items()}


# ---------------------------------------------------------------- events

def multikills(frags, side, gap=MULTIKILL_GAP, min_kills=MULTIKILL_MIN):
    """[{match, half, t, kind:"multikill", team, player, n}] -- one per cluster.

    A cluster is consecutive kills by one player each within `gap` seconds of
    the previous; it ends when the gap is exceeded. t is the LAST kill, which
    is when the numbers advantage is fully realised. Team kills don't count.
    """
    runs = defaultdict(list)
    for r in frags:
        t = _f(r["game_time"])
        if t is None:
            continue
        key = (r["match_id"], int(r["half"]))
        k, v = int(r["killerId"]), int(r["victimId"])
        st = side.get(key, {})
        if k not in st or st.get(v) == st[k]:
            continue
        runs[(key, k)].append(t)
    out = []
    for (key, k), times in runs.items():
        times.sort()
        cluster = [times[0]]
        for t in times[1:] + [math.inf]:
            if t - cluster[-1] <= gap:
                cluster.append(t)
                continue
            if len(cluster) >= min_kills:
                out.append({"match": key[0], "half": key[1], "t": cluster[-1], "kind": "multikill",
                            "team": side[key][k], "player": k, "n": len(cluster)})
            cluster = [t]
    return out


def objectives(flags, captures=()):
    """[{match, half, t, kind:"cap"|"capout", team, players, flag, held, dt}] from flag state.

    Ownership is replayed per half. Rows sharing a game_time are one group:
    a group that sets every flag is a reset (round start / post-capout), and
    a multi-flag group from an all-neutral state is the home-flag seed that
    follows a reset -- neither is an objective. Any other transition to a team
    is a cap by that team; if that team then owns every flag, it is also a
    capout at the same instant.
    """
    # Capture rows are stamped up to a second off the state row (measured:
    # 977 of 1651 unjoined caps sat exactly -1s), so the join tolerates +-1s.
    cappers = defaultdict(list)
    for c in captures:
        at = datetime.fromisoformat(c["event_time"])
        cappers[(c["match_id"], int(c["half"]), c["flag_name"], at)].append(int(c["player_id"]))

    def who_capped(match, half, name, event_time):
        at = datetime.fromisoformat(event_time)
        for skew in (0, -1, 1):
            hit = cappers.get((match, half, name, at + timedelta(seconds=skew)))
            if hit:
                return hit
        return []

    by_half = defaultdict(list)
    for r in flags:
        by_half[(r["match_id"], int(r["half"]))].append(r)

    out = []
    for (match, half), rows in by_half.items():
        n_flags = len({int(r["flag_index"]) for r in rows})
        owners = {}
        groups = defaultdict(list)
        for r in rows:
            groups[_f(r["game_time"])].append(r)
        # A cap "owns" the interval until the next ownership change: `held`
        # flags for `dt` seconds. That is what the cap enabled, and on a
        # hold-scored map it is where the points come from (see fit_scoring).
        open_caps = []
        for t in sorted(groups):
            group = groups[t]
            for cap in open_caps:
                cap["dt"] = t - cap["t"]
            open_caps = []
            all_neutral = owners and all(o == 0 for o in owners.values())
            if len(group) >= n_flags or (len(group) >= 2 and (all_neutral or not owners)):
                for r in group:
                    owners[int(r["flag_index"])] = int(r["owner_team"])
                continue
            for r in group:
                flag, team = int(r["flag_index"]), int(r["owner_team"])
                prev = owners.get(flag)
                owners[flag] = team
                if team not in (1, 2) or team == prev:
                    continue
                who = who_capped(match, half, r["flag_name"], r["event_time"])
                held = sum(1 for o in owners.values() if o == team)
                cap = {"match": match, "half": half, "t": t, "kind": "cap", "team": team,
                       "players": who, "flag": r["flag_name"], "held": held, "dt": 0.0}
                out.append(cap)
                open_caps.append(cap)
                if held == n_flags:
                    out.append({"match": match, "half": half, "t": t, "kind": "capout", "team": team,
                                "players": who, "flag": r["flag_name"]})
    return out


def half_spans(*event_lists):
    """{(match, half): (t0, t1)} -- observed extent of each half."""
    span = {}
    for events in event_lists:
        for e in events:
            key = (e["match"], e["half"])
            lo, hi = span.get(key, (e["t"], e["t"]))
            span[key] = (min(lo, e["t"]), max(hi, e["t"]))
    return span


# ---------------------------------------------------------------- measurement

def lag_lift(multis, objs, spans, kind="cap", bins=LAG_BINS, grid=5.0):
    """Per lag bin: P(team objective in bin | multikill at 0) vs a MATCHED baseline.

    The baseline for each multikill is its own team's rate in that half --
    the probability of that objective in a window of that length starting at
    any grid point. So a strong team's high cap rate does not read as
    momentum; only the excess right after the multikill does.
    Returns [{bin, n, hits, p, base, lift}].
    """
    times = defaultdict(list)
    for o in objs:
        if o["kind"] == kind:
            times[(o["match"], o["half"], o["team"])].append(o["t"])

    def hit(key, t, lo, hi):
        return any(lo < x - t <= hi for x in times.get(key, ()))

    rows = []
    for lo, hi in bins:
        base_of = {}
        for (match, half), (t0, t1) in spans.items():
            for team in (1, 2):
                n = h = 0
                t = t0
                while t + hi <= t1:
                    n += 1
                    h += hit((match, half, team), t, lo, hi)
                    t += grid
                base_of[(match, half, team)] = h / n if n else 0.0
        n = hits = 0
        base = 0.0
        for m in multis:
            key = (m["match"], m["half"], m["team"])
            n += 1
            hits += hit(key, m["t"], lo, hi)
            base += base_of.get(key, 0.0)
        p, base = (hits / n if n else 0.0), (base / n if n else 0.0)
        rows.append({"bin": (lo, hi), "n": n, "hits": hits, "p": p, "base": base,
                     "lift": (p / base) if base else float("nan")})
    return rows


def fit_lift(rows):
    """lift(d) = 1 + A*exp(-lam*d) by least squares on log(lift-1) over bins with lift>1.

    Returns (A, lam). Bins at or below baseline carry no momentum signal and
    are excluded rather than clamped -- they just shorten the fit.
    """
    pts = [((lo + hi) / 2.0, math.log(r["lift"] - 1.0)) for r, (lo, hi) in
           ((r, r["bin"]) for r in rows) if r["lift"] > 1.0]
    if len(pts) < 2:
        return 0.0, 0.0
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    mx, my = sum(xs) / len(xs), sum(ys) / len(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx if sxx else 0.0
    return math.exp(my - slope * mx), -slope


def conditional_lift(multis, objs, window=60.0, follow=(0.0, 120.0)):
    """rho evidence: does a cap that FOLLOWED a multikill lead to a capout more
    often than a cap that did not? Returns (p_with, p_without, n_with, n_without).
    A ratio near 1 says the chain carries nothing beyond the cap itself."""
    mk = defaultdict(list)
    for m in multis:
        mk[(m["match"], m["half"], m["team"])].append(m["t"])
    capouts = defaultdict(list)
    for o in objs:
        if o["kind"] == "capout":
            capouts[(o["match"], o["half"], o["team"])].append(o["t"])
    tally = {True: [0, 0], False: [0, 0]}
    for o in objs:
        if o["kind"] != "cap":
            continue
        key = (o["match"], o["half"], o["team"])
        preceded = any(0 <= o["t"] - t <= window for t in mk.get(key, ()))
        led = any(follow[0] < t - o["t"] <= follow[1] for t in capouts.get(key, ()))
        tally[preceded][0] += 1
        tally[preceded][1] += led
    (nw, hw), (no, ho) = tally[True], tally[False]
    return (hw / nw if nw else 0.0), (ho / no if no else 0.0), nw, no


# ---------------------------------------------------------------- scoring

SCORING_FEATURES = ("cap", "hold3", "hold4", "capout")


def scoring_features(objs, match, half, team):
    """What a team did in a half, in the terms the scoreboard pays for."""
    f = dict.fromkeys(SCORING_FEATURES, 0.0)
    for o in objs:
        if (o["match"], o["half"], o["team"]) != (match, half, team):
            continue
        if o["kind"] == "capout":
            f["capout"] += 1
        else:
            f["cap"] += 1
            if o["held"] in (3, 4):
                f[f"hold{o['held']}"] += o["dt"]
    return f


def _solve(A, b):
    n = len(A)
    M_ = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        pivot = max(range(c, n), key=lambda r: abs(M_[r][c]))
        M_[c], M_[pivot] = M_[pivot], M_[c]
        if abs(M_[c][c]) < 1e-12:
            continue
        for r in range(n):
            if r != c:
                k = M_[r][c] / M_[c][c]
                M_[r] = [x - k * y for x, y in zip(M_[r], M_[c])]
    return [M_[i][n] / M_[i][i] if abs(M_[i][i]) > 1e-12 else 0.0 for i in range(n)]


def fit_scoring(samples):
    """Least squares points = sum(coef * feature), no intercept.

    samples: [(features, points)]. Returns (coef dict, r2). Measured on
    thunder (36 team-halves): ~2.5/cap, ~0.2-0.4 per second holding four
    flags, ~45 per capout, three flags near zero. Fit per map -- lennon and
    harrington score differently and get their own once labelled.
    """
    keys = SCORING_FEATURES
    X = [[f[k] for k in keys] for f, _ in samples]
    y = [p for _, p in samples]
    n = len(keys)
    A = [[sum(X[i][a] * X[i][b] for i in range(len(X))) for b in range(n)] for a in range(n)]
    b = [sum(X[i][a] * y[i] for i in range(len(X))) for a in range(n)]
    coef = dict(zip(keys, _solve(A, b)))
    pred = [sum(coef[k] * f[k] for k in keys) for f, _ in samples]
    ybar = sum(y) / len(y) if y else 0.0
    ss = sum((v - ybar) ** 2 for v in y)
    r2 = 1.0 - sum((v - p) ** 2 for v, p in zip(y, pred)) / ss if ss else 0.0
    return coef, r2


def value(event, scoring):
    """Scoreboard points an objective event is worth under a fitted scoring."""
    if event["kind"] == "capout":
        return max(0.0, scoring["capout"])
    return max(0.0, scoring["cap"] + scoring.get(f"hold{event['held']}", 0.0) * event["dt"])


# ---------------------------------------------------------------- the ledger

def attributable(lag, A, lam):
    """Share of an objective at `lag` seconds that momentum accounts for."""
    lift = 1.0 + A * math.exp(-lam * lag)
    return max(0.0, 1.0 - 1.0 / lift)


class Ledger:
    """One team's outstanding momentum in one half.

    Each deposit remembers who made it and what fed it, so a payout can be
    forwarded upstream. `curves` is {kind: (A, lam)} from `fit_lift`: a cap
    is paid on the fast curve, a capout on the slow one, and a deposit's
    weight at payout time decays with the curve of the objective being paid
    -- the credit is a claim on that lift, so it fades as that lift does.
    """

    def __init__(self, curves, rho):
        self.curves, self.rho = curves, rho
        self.deposits = []          # [{t, value, holders: {pid: share}, upstream: [(deposit, weight)]}]
        self.credit = Counter()     # pid -> everything paid out
        self.momentum = Counter()   # pid -> the part received as a depositor (the momentum credit)

    def _pay(self, d, amount):
        keep = amount * (1.0 - self.rho) if d["upstream"] else amount
        for pid, share in d["holders"].items():
            self.credit[pid] += keep * share
            self.momentum[pid] += keep * share
        forward = amount - keep
        total = sum(w for _, w in d["upstream"]) or 1.0
        for up, w in d["upstream"]:
            self._pay(up, forward * w / total)

    def deposit(self, t, value, holders, upstream=()):
        self.deposits.append({"t": t, "value": value, "holders": dict(holders),
                              "upstream": list(upstream)})

    def event(self, t, kind, value, holders):
        """An objective of `kind` worth `value` at t by `holders` ({pid: share}).

        Pays the momentum share to outstanding deposits, the rest to holders,
        then deposits the event itself with the payers as its upstream.
        """
        A, lam = self.curves[kind]
        weights = [(d, d["value"] * math.exp(-lam * (t - d["t"]))) for d in self.deposits]
        weights = [(d, w) for d, w in weights if w > 0]
        pool = sum(w for _, w in weights)
        share = 0.0
        if pool > 0 and value > 0:
            nearest = min(t - d["t"] for d, _ in weights)
            share = attributable(nearest, A, lam) * value
            for d, w in weights:
                self._pay(d, share * w / pool)
        for pid, s in holders.items():
            self.credit[pid] += (value - share) * s
        self.deposit(t, value, holders, weights)

    def clear(self):
        self.deposits = []


def credit(events, curves, rho, cap_value=CAP_VALUE, capout_value=CAPOUT_VALUE, mk_value=1.0,
           scoring=None):
    """{(match, half): {pid: {"total", "momentum"}}} over merged multikill + objective events.

    `total` is every objective value paid to the player; `momentum` is the
    part received as a depositor -- what this module adds over plain cap
    credit. `total - momentum` is the direct capper share.

    `scoring` ({map: coef} from fit_scoring) prices objectives in scoreboard
    points; without it, or for a map without a fit, cap_value/capout_value.

    A multikill deposits (n-2)*mk_value and is paid nothing itself -- kills
    are already paid in KTPR. A cap pays cap_value; a capout pays
    capout_value on top. An enemy cap clears the ledger.
    """
    by_half = defaultdict(list)
    for e in events:
        by_half[(e["match"], e["half"])].append(e)
    out = {}
    for key, evs in by_half.items():
        ledgers = {1: Ledger(curves, rho), 2: Ledger(curves, rho)}
        for e in sorted(evs, key=lambda e: (e["t"], e["kind"] != "cap")):
            L = ledgers[e["team"]]
            if e["kind"] == "multikill":
                L.deposit(e["t"], (e["n"] - 2) * mk_value, {e["player"]: 1.0})
                continue
            who = e["players"] or []
            holders = {p: 1.0 / len(who) for p in who} if who else {}
            fit = (scoring or {}).get(e.get("map"))
            v = value(e, fit) if fit else (cap_value if e["kind"] == "cap" else capout_value)
            L.event(e["t"], e["kind"], v, holders)
            if e["kind"] == "cap":
                ledgers[3 - e["team"]].clear()
        out[key] = defaultdict(lambda: {"total": 0.0, "momentum": 0.0})
        for L in ledgers.values():
            for pid, v in L.credit.items():
                out[key][pid]["total"] += v
            for pid, v in L.momentum.items():
                out[key][pid]["momentum"] += v
    return out
