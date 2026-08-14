"""Build the multi-page WSDoD site from design/prototype.html.

The prototype is one self-contained file carrying every edition. That is right
for review and wrong for publishing: a visitor reading 2026 downloaded 2025 too,
and — the reason this exists — an edition could not be linked to at all. The
switcher never touched the URL, so every edition shared one address and one
Discord preview.

This emits a page per edition, each carrying only its own data, with the edition
bar as real links. Sections are flat in the source (verified: max nesting depth
1), so they can be routed by their data-ed attribute without an HTML parser.

  dist/index.html          Philly 2026   (the default edition lives at the root)
  dist/2025/index.html     Philly 2025
  dist/next/index.html     Coming soon
  dist/assets/site.css     shared, cached across editions
  dist/assets/site.js

CSS and JS move to shared files rather than being inlined three times: the point
of a multi-page site is that moving between editions re-fetches only the page.
The single-file build still exists for the artifact preview — see the scratchpad
build_artifact.py — and is unaffected.
"""
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "design", "prototype.html")
DIST = os.path.join(HERE, "dist")

# Which data blocks belong to which edition. Anything not listed is shared.
OWNED = {
    "philly-2026": ["lan-data", "lanboard-data", "player-names", "demo-urls",
                    "awards-data", "veto-data", "match-teams", "match-notes",
                    "uploads"],
    "philly-2025": ["lan-data-2025"],
    "next": [],
}

# Keys to keep from a data block, by block id -- everything else in that block
# is dropped at publish time rather than trusted to stay trimmed at the source.
# awards-data's page renderer reads only .vote/.ballots (the live-voting
# ballots, still fed from this static block); .decided/.positions/.single_match
# are dead now that GET /api/awards/candidates drives that content, and they
# carried player stats -- shipping them anyway put ~46 players' names and
# figures past the stats_published gate regardless of its state. Trimming here,
# not by hand-editing the source block, means the trim survives whatever
# regenerates that JSON.
TRIM_KEYS = {
    "awards-data": ["vote", "ballots"],
}
PAGE = {                       # slug, title, description
    "philly-2026": ("", "Philly 2026",
                    "The World Series of Day of Defeat, Philadelphia 2026: "
                    "ten companies, 100 matches, full player stats, brackets and demos."),
    "philly-2025": ("2025", "Philly 2025",
                    "DoD LAN 2025, Philadelphia: twelve teams, the Sunday bracket, "
                    "and the player stats Jane compiled by hand."),
    "next": ("next", "Coming soon",
             "The next World Series of Day of Defeat — dates and venue publish here."),
}


_ROW_RE = re.compile(
    r'(<tr><td>\d+</td><td>[\d:]+</td><td class="map">)(dod_[a-z0-9_]+)(</td>.*?'
    r'data-match="([\w-]+)".*?</tr>)', re.S)


def linkify_match_log(html, slugs):
    """Wraps each match-log row's map cell in a link to its page (Results
    §Discovery: the log is the only entry point, match pages aren't in the
    nav). A row whose match_id has no slug -- the two aborted starts -- is
    left exactly as it prints today; there's no page to send it to."""
    def sub(m):
        pre, dod_map, post, mid = m.groups()
        slug = slugs.get(mid)
        if not slug:
            return m.group(0)
        return '%s<a href="match/%s/">%s</a>%s' % (pre, slug, dod_map, post)
    out, n = _ROW_RE.subn(sub, html)
    linked = len(re.findall(r'<a href="match/', out))
    if linked != len(slugs):
        sys.exit("match log: linked %d rows but have %d slugs -- a row's shape "
                  "changed under _ROW_RE" % (linked, len(slugs)))
    return out


def rel(from_slug, to_slug):
    """Link between edition pages, both directions, from a nested or root page."""
    up = "" if not from_slug else "../"
    return (up + (to_slug + "/" if to_slug else "")) or "./"


# ---------------------------------------------------------------------------
# Per-match pages. Static shell (teams, map, day, round, score, veto, demos,
# notes -- all baked, none gated, per MATCH_PAGES_SPEC.md), fetched scoreboard
# and awards strip. Slugs and the score/round derivation are frozen data --
# see lan-stats/freeze_match_slugs.py and lan-stats/build_match_extras.py for
# how match-slugs.json/match-extras.json were built and why; this function
# only reads them.
# ---------------------------------------------------------------------------

def _esc(s):
    if s is None:
        return ""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def _half_table(teams, cols, decides=False):
    """Two club rows against per-half columns.

    `cols` is [(heading, [club_a, club_b] | None), ...]; a None column prints an
    em dash, which is how a half nobody has a figure for renders without the
    reader taking a blank for a nil.

    `decides` puts gold on whoever leads the last column, and belongs only to
    the table that settles the match. Flags captured led a different club in
    four matches -- all of them one- or two-flag margins -- so a gold row there
    would contradict the score panel directly above it.
    """
    a, b = teams
    final = cols[-1][1] if decides else None
    win = "" if final is None or final[0] == final[1] else ("a" if final[0] > final[1] else "b")

    def cells(i):
        return "".join('<td class="r%s">%s</td>'
                       % ("" if v else " na", _esc(v[i]) if v else "&mdash;")
                       for _h, v in cols)
    return (
        '<table class="scoretable"><thead><tr><th></th>%s</tr></thead><tbody>'
        '<tr class="%s"><td>%s</td>%s</tr>'
        '<tr class="%s"><td>%s</td>%s</tr></tbody></table>'
        % ("".join('<th class="r">%s</th>' % h for h, _v in cols),
           "m1" if win == "a" else "", _esc(a), cells(0),
           "m1" if win == "b" else "", _esc(b), cells(1)))


def _points_table(teams, points):
    """The match score -- team score, what the match was decided on.

    Half 2 is the half's own points, not the cumulative figure the in-game
    scoreboard shows at the whistle; that cumulative reading is the Final
    column. lan-stats/build_match_extras.py has the derivation.
    """
    if points is None:
        return ('<p class="hint">Not recorded — no score survived for this '
                'match.</p>')
    table = _half_table(teams, [("Half 1", points["h1"]), ("Half 2", points["h2"]),
                                ("Final", points["total"])], decides=True)
    if points["total"] is None:
        table += ('<p class="hint mt16">Half 2 never started — this match was '
                  'abandoned at the break, so there is no final.</p>')
    return table


def _score_table(teams, score):
    """Flags captured per half -- NOT the match score, which is above it on the
    page. These are capture events per club; both figures are real and they do
    not track each other, so the panel headings have to keep them apart.
    """
    if score is None:
        return ('<p class="hint">Not recorded — logging ended before this '
                'match closed. What survived (half boundaries, players, the map) '
                'is above; the flag count is not.</p>')
    return _half_table(teams, [("Half 1", score["h1"]), ("Half 2", score["h2"]),
                               ("Final", score["final"])])


VETO_ACTION_WORD = {"ban": "banned", "pick": "picked", "decider": "decider"}


def _veto_list(steps, ts_name, ls_name):
    if not steps:
        return ""
    rows = []
    for st in steps:
        actor = ts_name if st["actor"] == "TS" else ls_name
        word = VETO_ACTION_WORD.get(st["action"], st["action"])
        side = (" · " + _esc(st["side"])) if st.get("side") else ""
        rows.append('<li><span class="rn">%s</span> %s <b>%s</b>%s</li>'
                    % (_esc(actor), word, _esc(st["map"]), side))
    return ('<div class="panel"><div class="head">Veto sequence</div><div class="body">'
            '<ol class="runners tied">%s</ol></div></div>' % "".join(rows))


def _demo_list(urls):
    if not urls:
        return '<p class="hint">No demos on file for this match.</p>'
    items = "".join(
        '<li><a href="%s">Half %d demo</a></li>' % (_esc(u), i + 1)
        for i, u in enumerate(urls))
    return '<ul class="crit" style="flex-direction:column;align-items:flex-start">%s</ul>' % items


def build_match_pages(dist, data, editions):
    """Returns the match_id -> slug map (empty if the two lan-stats/ inputs
    aren't there yet), so the Results match-log linkifier and this function
    agree on the exact same set without loading the file twice."""
    lan_stats = os.path.join(HERE, "lan-stats")
    slugs_path = os.path.join(lan_stats, "match-slugs.json")
    extras_path = os.path.join(lan_stats, "match-extras.json")
    if not (os.path.exists(slugs_path) and os.path.exists(extras_path)):
        print("match pages: skipped -- run freeze_match_slugs.py and "
              "build_match_extras.py first (lan-stats/)")
        return {}

    slugs = json.load(open(slugs_path, encoding="utf-8"))
    extras = json.load(open(extras_path, encoding="utf-8"))
    # bracket.json's team_a is consistently the higher (numerically lower)
    # seed -- verified against the Final (team_a=icyHOT, seed 1; team_b=NATO,
    # seed 3) -- which is what veto.json's "TS"/"LS" actor codes mean.
    bracket_by_mkey = {s["mkey"]: s for s in json.load(
        open(os.path.join(lan_stats, "bracket.json"), encoding="utf-8"))}
    match_teams = json.loads(data["match-teams"])
    demo_urls = json.loads(data["demo-urls"]) if "demo-urls" in data else {}
    veto_data = json.loads(data["veto-data"]) if "veto-data" in data else {}
    match_notes = json.loads(data["match-notes"]) if "match-notes" in data else {}

    missing_extras = [m for m in slugs if m not in extras]
    if missing_extras:
        sys.exit("match pages: %d slug(s) have no match-extras.json entry: %s"
                  % (len(missing_extras), missing_extras))

    DAY_NAME = {"sat": "Saturday", "sun": "Sunday"}

    built = 0
    for mid, slug in slugs.items():
        teams = match_teams[mid]
        ex = extras[mid]
        day = DAY_NAME.get(slug.split("-", 1)[0], slug.split("-", 1)[0])
        title = "%s vs %s · %s · WSDoD Philly 2026" % (teams[0], teams[1], ex["map"][4:])
        desc = ("%s vs %s, %s (%s) — %s. WSDoD Philly 2026 match record."
                % (teams[0], teams[1], ex["map"][4:], day, ex["round"]))

        veto_steps = veto_data.get(ex["mkey"]) if ex.get("mkey") else None
        bseries = bracket_by_mkey.get(ex.get("mkey"))
        ts_name, ls_name = (bseries["team_a"], bseries["team_b"]) if bseries else ("Team A", "Team B")
        note = match_notes.get(mid)
        note_html = ('<div class="note-box"><b>%s</b></div>'
                     % _esc(note["why"])) if note else ""

        body = (
            '<div class="wrap">'
            '<p class="hint mt16"><a href="../../#results">&larr; Results</a></p>'
            '<header class="hero" style="padding-top:16px">'
            '<h1>%s <span style="color:var(--faint)">vs</span> %s</h1>'
            '<p class="lede">%s &middot; %s &middot; %s</p>'
            '</header>'
            '%s'
            '<div class="panel mt16"><div class="head">Score'
            '<span class="n">team score &middot; per half</span></div>'
            '<div class="body">%s</div></div>'
            '<div class="panel mt16"><div class="head">Flags captured'
            '<span class="n">per half &middot; not the match score</span></div>'
            '<div class="body">%s</div></div>'
            '%s'
            '<div class="panel mt16"><div class="head">Demos</div><div class="body">%s</div></div>'
            '<section style="padding-top:32px"><div class="sec-head"><h2>Scoreboard</h2></div>'
            '<div id="match-scoreboard"><p class="formstat work">Loading…</p></div></section>'
            '<section style="padding-top:32px"><div class="sec-head"><h2>Records</h2>'
            '<span class="meta">this match\'s own single-match candidates</span></div>'
            '<div id="match-awards"></div></section>'
            '<footer class="mt16" style="padding:24px 0"><p class="hint">'
            'WSDoD Philly 2026 &middot; <a href="../../">dodworldseries.com</a></p></footer>'
            '</div>'
            % (_esc(teams[0]), _esc(teams[1]), _esc(ex["map"]), day, _esc(ex["round"]),
               note_html, _points_table(teams, ex.get("points")),
               _score_table(teams, ex["score"]),
               _veto_list(veto_steps, ts_name, ls_name), _demo_list(demo_urls.get(mid)))
        )

        page = (
            "<!doctype html>\n<html lang=\"en\">\n<head>\n"
            "<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            "<title>%s</title>\n"
            "<meta name=\"description\" content=\"%s\">\n"
            "<meta property=\"og:title\" content=\"%s\">\n"
            "<meta property=\"og:description\" content=\"%s\">\n"
            "<link rel=\"canonical\" href=\"https://dodworldseries.com/match/%s/\">\n"
            "<link rel=\"stylesheet\" href=\"../../assets/site.css\">\n"
            "</head>\n<body data-match-key=\"%s\">\n"
            "%s\n"
            "<script src=\"../../assets/site.js\"></script>\n</body>\n</html>\n"
            % (_esc(title), _esc(desc), _esc(title), _esc(desc), slug, mid, body)
        )

        path = os.path.join(dist, "match", slug, "index.html")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w", encoding="utf-8", newline="").write(page)

        # Raw match key -> slug redirect. Same title/OG tags as the real page
        # so a link built from the key (anything that predates the slug)
        # still unfurls correctly even though the visit bounces onward.
        redirect = (
            "<!doctype html>\n<html lang=\"en\">\n<head>\n"
            "<meta charset=\"utf-8\">\n"
            "<meta http-equiv=\"refresh\" content=\"0; url=../%s/\">\n"
            "<title>%s</title>\n"
            "<meta property=\"og:title\" content=\"%s\">\n"
            "<meta property=\"og:description\" content=\"%s\">\n"
            "<link rel=\"canonical\" href=\"https://dodworldseries.com/match/%s/\">\n"
            "</head>\n<body><p><a href=\"../%s/\">%s</a></p></body>\n</html>\n"
            % (slug, _esc(title), _esc(title), _esc(desc), slug, slug, _esc(title))
        )
        rpath = os.path.join(dist, "match", mid, "index.html")
        os.makedirs(os.path.dirname(rpath), exist_ok=True)
        open(rpath, "w", encoding="utf-8", newline="").write(redirect)

        built += 1

    print("match pages: %d built (dist/match/<slug>/, plus a redirect per raw key)" % built)
    return slugs


def main():
    html = open(SRC, encoding="utf-8").read()

    css = "\n".join(m.group(1) for m in re.finditer(r"<style[^>]*>(.*?)</style>", html, re.S))
    js_blocks = re.findall(r"<script(?![^>]*application/json)[^>]*>(.*?)</script>", html, re.S)
    js = "\n;\n".join(js_blocks)
    data = dict(re.findall(
        r'<script id="([a-z0-9_-]+)" type="application/json">(.*?)</script>', html, re.S))
    editions = json.loads(data["editions"])

    body = re.search(r"<body[^>]*>(.*?)</body>", html[html.index("</head>"):], re.S)
    body = body.group(1)
    # strip the blocks that become shared assets or are re-emitted per page
    body = re.sub(r"<script[^>]*>.*?</script>", "", body, flags=re.S)
    # The publication switcher is a reviewer's tool for reading the prototype in
    # both gate states. Production decides server-side, so it must not ship.
    body, gone = re.subn(r'\n?<div class="mock">.*?</div>\s*</div>', "", body, flags=re.S)
    if gone != 1:
        sys.exit("build: expected exactly one mockup switcher to strip, found %d" % gone)

    sections = {}
    for m in re.finditer(r"<section\b([^>]*)>.*?</section>", body, re.S):
        attrs = m.group(1)
        sid = re.search(r'id="([^"]+)"', attrs)
        eds = re.search(r'data-ed="([^"]+)"', attrs)
        sections[sid.group(1) if sid else m.start()] = {
            "html": m.group(0), "eds": (eds.group(1).split() if eds else None)}

    shell = body
    for s in sections.values():
        shell = shell.replace(s["html"], "\x00%s\x00" % id(s), 1)

    if os.path.isdir(DIST):
        shutil.rmtree(DIST)
    os.makedirs(os.path.join(DIST, "assets"))
    open(os.path.join(DIST, "assets", "site.css"), "w", encoding="utf-8").write(css)
    open(os.path.join(DIST, "assets", "site.js"), "w", encoding="utf-8").write(js)

    match_slugs = build_match_pages(DIST, data, editions)

    built = []
    for eid, (slug, title, desc) in PAGE.items():
        out = shell
        for s in sections.values():
            keep = s["eds"] is None or eid in s["eds"]
            out = out.replace("\x00%s\x00" % id(s), s["html"] if keep else "")
        if eid == "philly-2026" and match_slugs:
            out = linkify_match_log(out, match_slugs)

        # Only this edition's payload. Other editions keep just what the bar
        # needs -- label, status and where to go -- so 2025's rosters and
        # bracket do not ride along on the 2026 page.
        eds = {"default": eid, "order": editions["order"], "editions": {}}
        for oid, ed in editions["editions"].items():
            if oid == eid:
                eds["editions"][oid] = dict(ed, href=None)
            else:
                eds["editions"][oid] = {
                    "label": ed.get("label"), "status": ed.get("status"),
                    "markup": False, "href": rel(slug, PAGE[oid][0])}

        blocks = ['<script id="editions" type="application/json">%s</script>'
                  % json.dumps(eds, ensure_ascii=False, separators=(",", ":"))]
        for name in OWNED.get(eid, []):
            if name in data:
                payload = data[name].strip()
                keep = TRIM_KEYS.get(name)
                if keep is not None:
                    obj = json.loads(payload)
                    payload = json.dumps({k: obj[k] for k in keep if k in obj},
                                          ensure_ascii=False, separators=(",", ":"))
                blocks.append('<script id="%s" type="application/json">%s</script>'
                              % (name, payload))

        base = "" if not slug else "../"
        page = (
            "<!doctype html>\n<html lang=\"en\">\n<head>\n"
            "<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            "<title>%s — WSDoD · World Series of Day of Defeat</title>\n"
            "<meta name=\"description\" content=\"%s\">\n"
            "<meta property=\"og:title\" content=\"WSDoD — %s\">\n"
            "<meta property=\"og:description\" content=\"%s\">\n"
            "<link rel=\"stylesheet\" href=\"%sassets/site.css\">\n"
            "</head>\n<body data-stats=\"on\" data-edition=\"%s\">\n"
            "%s\n%s\n<script src=\"%sassets/site.js\"></script>\n</body>\n</html>\n"
            % (title, desc, title, desc, base, eid, out,
               "\n".join(blocks), base))

        path = os.path.join(DIST, slug, "index.html") if slug else os.path.join(DIST, "index.html")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        open(path, "w", encoding="utf-8", newline="").write(page)
        built.append((eid, path, len(page)))

    print("assets: site.css %.0f KB   site.js %.0f KB" % (len(css) / 1024, len(js) / 1024))
    for eid, path, n in built:
        print("  %-14s %-34s %6.0f KB"
              % (eid, os.path.relpath(path, HERE).replace("\\", "/"), n / 1024))
    total = sum(n for _, _, n in built) + len(css) + len(js)
    print("total shipped: %.0f KB (single-file prototype is %.0f KB)"
          % (total / 1024, len(html) / 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
