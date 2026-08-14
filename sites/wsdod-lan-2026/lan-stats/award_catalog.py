#!/usr/bin/env python3
"""The award catalogue: every stat that can carry an award, in both directions.

Titles and stings here are DEFAULTS. Once an operator renames an award the
override lives in `lan_award_types` and wins forever after, including at the
next LAN — which is why rename_awards.py can retire: a rename finally has
somewhere upstream to live.

Where an award already ran at Philly 2026 its published title and blurb are
carried verbatim, so a regeneration does not quietly rewrite a card the
community already knows.
"""

FMT_INT = "int"          # 1,204
FMT_RATE = "rate"        # 2.35
FMT_RATIO = "ratio"      # 1.91
FMT_KTPR = "ktpr"        # 1.388
FMT_CLOCK = "clock"      # m:ss


class Stat:
    """A number a player can top, and what it is called at each end."""

    def __init__(self, key, label, fmt, *, high=None, low=None, source="stats"):
        self.key = key
        self.label = label
        self.fmt = fmt
        self.high = high      # (title, sting) for most-of-it, None to not generate
        self.low = low        # (title, sting) for least-of-it
        self.source = source  # 'stats' = lan-stats.json, 'frags' = frag log, 'hud'


# Weekend scope. A low-direction award only makes sense behind the played-enough
# floor, or the winner is whoever showed up least.
WEEKEND = [
    Stat("kills", "Kills", FMT_INT,
         high=("The Fragger", "Most kills across the weekend."),
         low=("Conscientious Objector", "Fewest kills of anyone who played the weekend out.")),
    Stat("deaths", "Deaths", FMT_INT,
         high=("Bullet Magnet", "Died more than anyone. Kept coming back."),
         low=("Hard To Kill", "Fewest deaths across the weekend.")),
    Stat("kd", "K/D", FMT_RATIO,
         high=("K/D Is Life", "Highest kill/death ratio, 20 halves minimum."),
         low=("Negative Equity", "Lowest kill/death ratio across the weekend.")),
    Stat("kills_per_half", "Kills/half", FMT_RATE,
         high=("Piece Work", "Most kills per half — paid by the frag."),
         low=("Union Break", "Fewest kills per half. Pace yourself.")),
    Stat("flags", "Flags", FMT_INT,
         high=("The Flagger", "Most flags across the weekend."),
         low=("Allergic To Objectives", "Fewest flags of anyone who played the weekend out.")),
    Stat("flags_per_half", "Flags/half", FMT_RATE,
         high=("Touch Grass", "Most flags per half — and he actually does. The Calebsod award."),
         low=("Homebody", "Fewest flags per half. The spawn was fine, actually.")),
    Stat("headshots", "Headshot kills", FMT_INT,
         high=("Straight Between The Eyes", "Most headshot kills."),
         low=("Center Mass", "Fewest headshot kills. It still counts.")),
    Stat("assists", "Assists", FMT_INT,
         high=("The Setup Man", "Most assists."),
         low=("Solo Queue", "Fewest assists. Finished his own work.")),
    Stat("damage_hlstatsx", "Damage", FMT_INT,
         high=("Occupational Hazard", "Most damage dealt across the weekend."),
         low=("Love Taps", "Least damage dealt of anyone who played the weekend out.")),
    Stat("cap_breaks", "Breaks", FMT_INT,
         high=("Party Pooper", "Most enemy captures broken up."),
         low=("Let Them Cook", "Fewest enemy captures broken up. Live and let live.")),
    Stat("obj_score", "Objective score", FMT_INT,
         high=("Does The Paperwork", "Highest objective score — the work nobody clips."),
         low=("Not In The Job Description", "Lowest objective score. He was busy.")),
    Stat("nade_kills", "Grenade kills", FMT_INT,
         high=("Area Of Effect", "Most grenade kills across the weekend."),
         low=("Pin Still In", "Fewest grenade kills. Carried them the whole way.")),
    Stat("gun_kills", "Gun kills", FMT_INT,
         high=("Iron Sights", "Most kills with a gun, the honest way."), low=None),
    Stat("hits", "Hits landed", FMT_INT,
         high=("Volume Shooter", "Most shots that actually connected."), low=None),
    Stat("hs_hits", "Headshot hits", FMT_INT,
         high=("Aim For The Hat", "Most shots landed on a head, kill or not."), low=None),
    Stat("best_streak", "Best streak", FMT_INT,
         high=("Unanswered", "Longest kill streak of the weekend."),
         low=("One And Done", "Shortest best streak. Every kill was a fresh start.")),
    Stat("prone_seconds", "Time prone", FMT_CLOCK,
         high=("Carpet Inspector", "Most time on the deck — someone has to check it. The Milo award."),
         low=("Standing Room Only", "Least time prone. Never once hit the deck.")),
    Stat("prone_events", "Times prone", FMT_INT,
         high=("Up, Down, Up, Down", "Went prone more times than anyone."), low=None),
    # caps_hud carries no award — see RETIRED below.
    Stat("matches", "Matches", FMT_INT,
         high=("Iron Man", "Played more matches than anyone."), low=None),
]

# Weekend awards that need their own query rather than a lan-stats.json column.
WEEKEND_DERIVED = [
    Stat("melee_kills", "Melee kills", FMT_INT, source="frags",
         high=("Welcome to Philly", "Most melee kills all weekend — spade, knife, bayonet and rifle butt."),
         low=None),
    Stat("nemesis_pair", "Kills on one opponent", FMT_INT, source="frags",
         high=("Restraining Order", "Most kills on one specific opponent, all weekend."), low=None),
    Stat("pistol_kills", "Pistol kills", FMT_INT, source="frags",
         high=("Backup Plan", "Most pistol kills across the weekend."), low=None),
]

# Single-match scope. Published titles are carried where the award already ran;
# the rest follow the same house voice.
MATCH = [
    Stat("kills", "Kills", FMT_INT,
         high=("One Man Army", "Most kills in a single match."),
         low=None),
    Stat("deaths", "Deaths", FMT_INT,
         high=("Hurt Me Daddy", "Most deaths in a single match."), low=None),
    Stat("kd", "K/D", FMT_RATIO,
         high=("Difficulty: Tourist", "Best K/D in a single match, 30-kill minimum."),
         low=("Difficulty: Realism", "Worst K/D in a single match, 30-death minimum.")),
    Stat("headshots", "Headshot kills", FMT_INT,
         high=("Headhunter", "Most headshot kills in a single match."), low=None),
    Stat("assists", "Assists", FMT_INT,
         high=("Helping Hand", "Most assists in a single match."), low=None),
    Stat("damage_dealt", "Damage dealt", FMT_INT,
         high=("Heavy Hitter", "Most damage dealt in a single match."), low=None),
    Stat("damage_taken", "Damage taken", FMT_INT,
         high=("Human Shield", "Most damage taken in a single match."),
         low=("Don't Touch Me", "Least damage taken in a single match.")),
    Stat("nade_kills", "Grenade kills", FMT_INT,
         high=("Amazon Delivery", "Most grenade kills in a single match."), low=None),
    Stat("teamkills", "Team kills", FMT_INT,
         high=("Benedict Arnold", "Most team kills in a single match."), low=None),
    # hud_kills, not the frag log: hlstats_Events_Suicides is empty for this
    # event and ktp_match_stats.suicides sums to zero across the whole set.
    Stat("suicides", "Suicides", FMT_INT, source="hud",
         high=("Own Worst Enemy", "Most suicides in a single match."), low=None),
    Stat("pistol_kills", "Pistol kills", FMT_INT, source="frags",
         high=("Sidearm Specialist", "Most pistol kills in a single match."), low=None),
    Stat("cap_breaks", "Breaks", FMT_INT,
         high=("No Cap For You", "Most enemy captures broken up in a single match."), low=None),
    Stat("best_streak", "Best streak", FMT_INT, source="frags",
         high=("On A Tear", "Longest kill streak in a single match."), low=None),
    Stat("prone_seconds", "Time prone", FMT_CLOCK,
         high=("Professional Horizontal", "Most time prone in a single match."), low=None),
    Stat("obj_score", "Objective score", FMT_INT,
         high=("Match Ball", "Highest objective score in a single match."), low=None),
    Stat("flags", "Flags", FMT_INT,
         high=("Land Grab", "Most flags in a single match."), low=None),
]

# Team awards, computed by summing the club's players for that match or weekend.
TEAM = [
    Stat("kills", "Kills", FMT_INT,
         high=("Full Send", "Most kills by a club across the weekend."), low=None),
    Stat("flags", "Flags", FMT_INT,
         high=("Cartographers", "Most flags by a club across the weekend."), low=None),
    Stat("kd", "K/D", FMT_RATIO,
         high=("The Firm", "Best club kill/death ratio across the weekend."), low=None),
    Stat("teamkills", "Team kills", FMT_INT,
         high=("Friendly Fire Incident", "Most team kills by a club across the weekend."), low=None),
]

# KTPR renormalises its averages per day, so a weekend KTPR award would compare
# numbers that are not comparable. MVP stays per-day for exactly that reason.
PER_DAY = [
    Stat("ktpr", "KTPR", FMT_KTPR,
         high=("MVP", "Highest KTPR of the day."), low=None),
]


# Awards deliberately not generated, kept with the measurement that killed them
# so nobody re-adds one without re-running the check. Same convention as
# apply_award_decisions.py's DROP dict.
RETIRED = {
    "weekend-caps-hud-high": (
        "Closer — most flag captures. Operator decision 2026-08-14: it is not a "
        "second award, it is The Flagger read off the weaker source. Same winner "
        "(seanality), the SAME top ten with nobody entering or leaving, and an "
        "event ratio of caps/flags 0.939 — which is just the uniform HUD "
        "undercount measured across every shared stat that day. The only thing "
        "it adds is a reordering: Khoi sits 3rd on flags and 7th on caps, which "
        "invites a reader to infer a habit that is really a dropped count. If a "
        "distinct objective award is wanted, Party Pooper and Touch Grass "
        "already separate people cleanly."
    ),
}


def slug_for(stat_key, scope, direction, kind="player"):
    # Team awards read the same stat at the same scope as their player twin, so
    # the kind has to be in the slug or the two collide on the primary key.
    prefix = scope if kind == "player" else "%s-%s" % (scope, kind)
    return "%s-%s-%s" % (prefix, stat_key.replace("_", "-"), direction)


def iter_definitions():
    """Yield every (slug, scope, kind, stat, direction, title, sting) the build should create."""
    groups = (
        ("weekend", "player", WEEKEND + WEEKEND_DERIVED),
        ("match", "player", MATCH),
        ("weekend", "team", TEAM),
        ("day", "player", PER_DAY),
    )
    for scope, kind, stats in groups:
        for stat in stats:
            for direction, naming in (("high", stat.high), ("low", stat.low)):
                if not naming:
                    continue
                title, sting = naming
                slug = slug_for(stat.key, scope, direction, kind)
                if slug in RETIRED:
                    continue  # re-adding the Stat is not enough; clear RETIRED too
                yield {
                    "slug": slug,
                    "scope": scope,
                    "kind": kind,
                    "stat_key": stat.key,
                    "direction": direction,
                    "default_title": title,
                    "default_sting": sting,
                    "fmt": stat.fmt,
                    "source": stat.source,
                }


def check_unique(defs):
    """Slugs are the primary key and titles are how staff tell cards apart."""
    problems = []
    for field in ("slug", "default_title"):
        seen = {}
        for d in defs:
            seen.setdefault(d[field], []).append(d["slug"])
        for value, owners in sorted(seen.items()):
            if len(owners) > 1:
                problems.append("duplicate %s %r: %s" % (field, value, ", ".join(owners)))
    return problems


if __name__ == "__main__":
    defs = list(iter_definitions())
    dupes = check_unique(defs)
    if dupes:
        import sys
        for line in dupes:
            print("FAIL " + line)
        sys.exit(1)
    by_scope = {}
    for d in defs:
        by_scope.setdefault(d["scope"], []).append(d)
    for scope in sorted(by_scope):
        print("== %s ==" % scope)
        for d in sorted(by_scope[scope], key=lambda x: x["slug"]):
            print("  %-34s %-28s %s" % (d["slug"], d["default_title"], d["default_sting"]))
    print("\ntotal definitions: %d" % len(defs))
