#!/usr/bin/env python3
"""Generate styled index pages for /dod (client downloads) and the fleet demo tree.

Same approach as the LAN archive: `index index.html` means a generated index.html replaces
nginx's autoindex, so these get real structure instead of a flat file list.

Two very different trees:
  /dod            static game assets, 1.3 GB. Clients fetch by direct path and never read a
                  directory listing, so a landing page here is purely for humans. Only the top
                  level is generated -- nobody hand-browses /dod/maps/.
  /demos/<SRV>/   the fleet archive, ~11 new demos a day. MUST be regenerated on a schedule or
                  it goes stale; hooked into the 04:00 organizer cron.

LAN-PHILLY2026 is skipped -- it has its own generator that knows the team names.

Idempotent: only ever writes index.html. Usage: fastdl_indexes.py [--apply]
"""
import argparse, collections, html, os, re, time

FASTDL = "/var/www/fastdl"
DEMOS = "/home/hltvserver/hlds/dod/demos"
SKIP = {"LAN-PHILLY2026"}
CITY = {"ATL": "Atlanta", "DAL": "Dallas", "DEN": "Denver", "NY": "New York", "CHI": "Chicago"}
TYPE_LABEL = {"ktp": "League (.ktp)", "scrim": "Scrims", "draft": "Drafts", "12man": "12-man"}
RETENTION = {"ktp": "180 days", "draft": "180 days", "12man": "90 days", "scrim": "90 days"}

CSS = """
:root{--bg:#171c0a;--panel:#252a14;--inset:#101407;--border:#3d432b;
--rule:rgba(61,67,43,0.5);--text:#eae7d4;--dim:#b6b299;--faint:#98947c;
--red:#d0513b;--red-soft:#e07a63;--blue:#819746;--blue-soft:#9fb45c;--radius:14px;
--panel-grad:linear-gradient(180deg,var(--panel) 0%,#1e230f 100%);
--mono:"JetBrains Mono",ui-monospace,"Cascadia Code",Consolas,Menlo,monospace;color-scheme:dark}
*{margin:0;padding:0;box-sizing:border-box}
/* Reserve the scrollbar gutter ALWAYS. Without it a short page (no scrollbar) is ~15px
   wider than a long one, so centred content — including the header — shifts sideways
   as you move between pages. That was measured at 7px on the LAN root page. */
html{scrollbar-gutter:stable}
body{background:radial-gradient(120% 80% at 50% -10%,#252a14 0%,rgba(37,42,20,0) 55%),var(--bg);
background-attachment:fixed;color:var(--text);font-family:var(--mono);font-size:15px;
line-height:1.55;-webkit-font-smoothing:antialiased;min-height:100vh}
a{color:var(--blue);text-decoration:none}a:hover{color:var(--blue-soft)}
code{font-family:var(--mono);color:var(--blue-soft)}
::selection{background:var(--red);color:#150b04}
a:focus-visible{outline:2px solid var(--blue-soft);outline-offset:2px}
/* 1180 and 15px are load-bearing: the landing page and /netcode use them, and a different
   value here slides the whole header sideways as you move between pages. */
.wrap{max-width:1180px;margin:0 auto;padding:0 22px;width:100%}
.mt8{margin-top:8px}
/* .card sets display:block, which beats the UA sheet's [hidden] rule — without !important
   the filter hides nothing. */
[hidden]{display:none!important}
nav{border-bottom:1px solid var(--border);background:rgba(16,20,7,0.72);position:static}
nav .row{display:flex;align-items:center;gap:22px;height:58px}
.brand{font-weight:800;letter-spacing:1px;font-size:1.05rem;color:var(--text)}
.brand .k{color:var(--red)}
nav .spacer{flex:1}
nav .navlink{color:var(--dim);font-size:0.82rem;letter-spacing:0.6px}
nav .navlink:hover{color:var(--text)}
@media (max-width:720px){nav .hidesm{display:none}}
.eyebrow{font-size:0.72rem;letter-spacing:2.4px;text-transform:uppercase;color:var(--dim);
display:flex;align-items:center;gap:10px;margin-top:34px}
.eyebrow::before{content:"";width:26px;height:2px;background:var(--blue);display:inline-block;flex:none}
.accent{color:var(--red)}
.sponsor-slot{margin-left:auto;font-size:0.72rem;font-weight:700;letter-spacing:0.4px;
color:var(--red-soft);border:1px solid var(--red);border-radius:999px;padding:4px 13px;
white-space:nowrap;text-transform:none}
.sponsor-slot:hover{background:var(--red);color:#150b04}
h1{font-size:clamp(1.5rem,3.4vw,2.1rem);font-weight:800;letter-spacing:-.6px;margin:14px 0 8px}
.lede{color:var(--dim);max-width:70ch;font-size:.9rem;margin-bottom:1.4rem}
.crumb{color:var(--faint);font-size:.78rem;margin:1.1rem 0 .2rem}
h2{font-size:.74rem;text-transform:uppercase;letter-spacing:1.4px;color:var(--faint);
margin:1.8rem 0 .7rem;padding-bottom:.35rem;border-bottom:1px solid var(--rule)}
.row2{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:.6rem}
.card{display:block;background:var(--panel-grad);border:1px solid var(--border);
border-radius:var(--radius);padding:.8rem .95rem;transition:border-color .15s ease,transform .15s ease}
.card:hover{border-color:var(--blue);transform:translateY(-1px)}
.card .t{color:var(--text);font-weight:700;letter-spacing:.3px}
.card .d{color:var(--faint);font-size:.78rem;margin-top:.25rem}
.match{background:var(--panel-grad);border:1px solid var(--border);border-radius:var(--radius);
padding:.7rem .9rem;margin-bottom:.55rem}
.match:hover{border-color:var(--blue)}
.mh{display:flex;flex-wrap:wrap;gap:.5rem;align-items:baseline;justify-content:space-between}
.teams{font-weight:700}
.meta{color:var(--faint);font-size:.76rem}
.files{margin-top:.5rem;display:flex;flex-wrap:wrap;gap:.4rem}
.f{display:inline-flex;align-items:center;gap:.45rem;background:var(--inset);
border:1px solid var(--rule);border-radius:8px;padding:.24rem .6rem;font-size:.78rem}
.f:hover{border-color:var(--blue)}
.f .h{color:var(--red-soft);font-weight:700}.f .sz{color:var(--faint)}
.note{color:var(--faint);font-size:.78rem;margin:.2rem 0 1rem}
.search{display:flex;align-items:center;gap:.7rem;margin:0 0 1.1rem;flex-wrap:wrap}
.search input{flex:1 1 240px;min-width:0;max-width:420px;background:var(--inset);
border:1px solid var(--border);border-radius:999px;padding:.45rem .95rem;color:var(--text);
font-family:var(--mono);font-size:.84rem}
.search input:focus{outline:none;border-color:var(--blue)}
.search input::placeholder{color:var(--faint)}
.qc{color:var(--faint);font-size:.76rem;white-space:nowrap}
footer{border-top:1px solid var(--border);padding:32px 0 72px;color:var(--dim);
font-size:0.82rem;margin-top:48px}
footer.split{display:flex;flex-wrap:wrap;gap:24px;justify-content:space-between}
footer .col{max-width:46ch}
footer h4{color:var(--text);font-size:0.72rem;letter-spacing:1.6px;text-transform:uppercase;margin-bottom:8px}
footer p{margin:4px 0}
footer .accent{color:var(--red);white-space:nowrap}
"""

def nav(site):
    return ('<nav>\n  <div class="wrap row">\n'
            '    <span class="brand"><span class="k">KTP</span> &mdash; ' + site + '</span>\n'
            '    <span class="spacer"></span>\n'
            '    <a class="navlink hidesm" href="https://fastdl.ktpdod.com/">Downloads</a>\n'
            '    <a class="navlink hidesm" href="https://netcode.ktpdod.com/">Netcode</a>\n'
            '    <a class="navlink hidesm" href="https://profiles.ktpdod.com/">Profiles</a>\n'
            '    <a class="navlink hidesm" href="https://bundles.ktpdod.com/">My Data</a>\n'
            '    <a class="navlink hidesm" href="https://ac.ktpdod.com/">Anti-Cheat</a>\n'
            '    <a class="navlink" href="https://support.ktpdod.com/">Support</a>\n'
            '  </div>\n</nav>\n')

EYEBROW = ('<div class="eyebrow">Keep the Practice &middot; Competitive Day of Defeat'
           '<a class="sponsor-slot" href="https://github.com/sponsors/afraznein">'
           '&#10084; Sponsor KTP</a></div>\n')

SEARCH = ('<div class="search">'
          '<input id="q" type="search" placeholder="Filter this page&hellip;" autocomplete="off"'
          ' spellcheck="false" aria-label="Filter this page" aria-controls="qc">'
          '<span id="qc" class="qc" role="status" aria-live="polite"></span></div>'
          '<p id="qnone" class="note" hidden>Nothing on this page matches that filter.</p>')

# Filters anything carrying data-s (built lowercase at generation time, so no per-keystroke
# text extraction). Terms are AND-ed. Headings hide when their whole group filters out --
# otherwise you get a page of orphan section titles over nothing.
SCRIPT = """<script>
(function(){
  var q=document.getElementById('q'); if(!q) return;
  var items=[].slice.call(document.querySelectorAll('[data-s]'));
  var heads=[].slice.call(document.querySelectorAll('h2'));
  var cnt=document.getElementById('qc'), none=document.getElementById('qnone');
  function apply(){
    var terms=q.value.trim().toLowerCase().split(/\\s+/).filter(Boolean);
    var shown=0;
    items.forEach(function(el){
      var s=el.getAttribute('data-s');
      var ok=terms.every(function(w){return s.indexOf(w)!==-1;});
      el.hidden=!ok; if(ok) shown++;
    });
    heads.forEach(function(h){
      var n=h.nextElementSibling, any=false;
      while(n && n.tagName!=='H2'){
        if(n.hasAttribute('data-s')){ if(!n.hidden) any=true; }
        else if(n.querySelector('[data-s]:not([hidden])')) any=true;
        n=n.nextElementSibling;
      }
      h.hidden = terms.length>0 && !any;
    });
    cnt.textContent = terms.length ? shown+' of '+items.length+' shown'
                                   : items.length+(items.length===1?' item':' items');
    none.hidden = !(terms.length>0 && shown===0);
  }
  q.addEventListener('input',apply);
  apply();
})();
</script>"""


def footer(what):
    return ('<footer class="split">\n  <div class="col">\n    <h4>What this is</h4>\n    <p>'
            + what + '</p>\n  </div>\n  <div class="col">\n    <h4>Keep it running</h4>\n'
            '    <p><a href="https://github.com/sponsors/afraznein">Sponsor the infrastructure</a> '
            '&middot;\n      <a href="https://support.ktpdod.com">Report a problem</a></p>\n'
            '    <p class="mt8"><span class="accent">Keep the Practice</span></p>\n'
            '  </div>\n</footer>\n')

# Root-relative nav hrefs 404 on netcode/profiles/bundles, which each have their own docroot.
# That was fixed on 2026-07-17 and regressed twice, so it is asserted rather than remembered.
def _nav(markup):
    hrefs = re.findall(r'class="navlink[^"]*" href="([^"]+)"', markup)
    bad = [h for h in hrefs if not h.startswith("http")]
    assert hrefs and not bad, "nav href must be absolute, got %s" % (bad or "no navlinks")
    return markup

def page(title, site, body, what):
    return "\n".join([
      '<!DOCTYPE html>', '<html lang="en">', '<head>', '<meta charset="utf-8">',
      '<meta name="viewport" content="width=device-width, initial-scale=1">',
      '<meta name="color-scheme" content="dark">',
      '<meta name="theme-color" content="#171c0a">',
      '<meta name="robots" content="noindex, nofollow">',
      '<link rel="icon" href="/favicon.ico" sizes="any">',
      '<link rel="icon" type="image/png" sizes="32x32" href="/favicon-32.png">',
      '<link rel="apple-touch-icon" href="/apple-touch-icon.png">',
      '<title>' + html.escape(title) + '</title>',
      '<style>' + CSS + '</style>', '</head>', '<body>',
      _nav(nav(site)), '<div class="wrap">', EYEBROW, body, footer(what), '</div>',
      SCRIPT, '</body></html>', ''])

def human(n):
    v = float(n)
    for u in ("B", "KB", "MB", "GB"):
        if v < 1024 or u == "GB":
            return ("%.1f %s" % (v, u)) if u == "GB" else ("%.0f %s" % (v, u))
        v /= 1024.0

def searchable(markup, *extra):
    """Lowercase search key built FROM the rendered card, plus anything extra.

    Derived rather than hand-listed on purpose: every visible string, every
    filename in an href and every tooltip in a title becomes searchable by
    construction, so adding a field to a card cannot silently leave it
    unsearchable. `extra` carries what is real but not rendered — alternate date
    spellings, the server, the match type.
    """
    vals = re.findall(r'(?:title|href|alt)="([^"]*)"', markup)
    text = re.sub(r"<[^>]+>", " ", markup)
    blob = html.unescape(" ".join(vals) + " " + text + " " + " ".join(str(x) for x in extra if x))
    # split on punctuation too, so "dod_anzio" is found by "anzio" and
    # "2026-06-11" by "06" — then keep the joined forms as well
    parts = re.split(r"[^0-9a-z]+", blob.lower())
    return " ".join(dict.fromkeys([w for w in parts if w] + blob.lower().split()))


def card(inner, href, *extra, cls="card"):
    """One linked tile whose search key is derived from its own rendered content."""
    return ('<a class="' + cls + '" data-s="'
            + html.escape(searchable(inner, href, *extra), quote=True)
            + '" href="' + html.escape(href) + '">' + inner + '</a>')


ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
args = ap.parse_args()
out = []

# ---------------------------------------------------------------- /dod
DOD_GROUPS = [
    ("Maps and terrain", ["maps", "overviews", "gfx"]),
    ("Models and sprites", ["models", "sprites"]),
    ("Sound", ["sound", "media"]),
    ("Configs and scripts", ["configs", "addons", "cl_dlls", "dlls", "events", "scripts"]),
]
present = {d for d in os.listdir(FASTDL + "/dod") if os.path.isdir(FASTDL + "/dod/" + d)}
cards = []
for label, dirs in DOD_GROUPS:
    have = [d for d in dirs if d in present]
    if not have:
        continue
    cards.append('<h2>' + label + '</h2><div class="row2">' + "".join(
        card('<div class="t">' + d + '/</div><div class="d">'
             + str(len(os.listdir(FASTDL + "/dod/" + d))) + ' entries</div>',
             d + "/", label) for d in have) + '</div>')
loose = sorted(f for f in os.listdir(FASTDL + "/dod") if os.path.isfile(FASTDL + "/dod/" + f))
body = ('<div class="crumb"><a href="/">fastdl</a> / dod</div>'
        '<h1>Client <span class="accent">download</span> files</h1>'
        '<p class="lede">These are the files your client pulls automatically when it joins a KTP '
        'server &mdash; maps, textures, models, sounds. <b>You do not need to download anything '
        'here by hand.</b> The list is browsable if you want to fetch one file directly.</p>'
        '<p class="note">' + str(len(present)) + ' directories, ' + str(len(loose))
        + ' loose files. Served over HTTP as <code>sv_downloadurl</code>.</p>'
        + SEARCH + "".join(cards)
        + '<h2>Other directories</h2><div class="row2">' + "".join(
            card('<div class="t">' + d + '/</div>', d + "/")
            for d in sorted(present - {x for _, ds in DOD_GROUPS for x in ds})) + '</div>')
out.append((FASTDL + "/dod/index.html",
            page("KTP FastDL — client downloads", "Client Downloads", body,
                 "Fast content distribution for KTP game servers. Your client fetches from here on "
                 "connect, so joining a server never means hunting for a map pack.")))

# ---------------------------------------------------------------- /demos fleet
servers = sorted(d for d in os.listdir(DEMOS) if os.path.isdir(DEMOS + "/" + d))
by_city = collections.OrderedDict()
for s in servers:
    if s in SKIP:
        continue
    m = re.match(r"([A-Z]+)\d+$", s)
    by_city.setdefault(CITY.get(m.group(1), "Other") if m else "Other", []).append(s)

# The box runs America/New_York, so localtime() is already league time. "ET" and
# not "EST": half the archive is recorded in EDT, and stamping those EST is just
# wrong. Matches how times are written everywhere else in KTP's docs.
TZ_LABEL = "ET"


def clock(ts):
    """'11:38 PM' — 12-hour, no leading zero, portable.

    %-I is glibc-only and this file is edited on Windows; lstrip is safe because
    %I never yields '00' (midnight is 12).
    """
    return time.strftime("%I:%M %p", ts).lstrip("0")


def rec_parts(fname):
    """struct_time from a demo filename's YYMMDDHHMM field, or None.

    That field is when HLTV started recording — near the match id's epoch but not
    equal to it, so the two are shown in different places rather than merged.
    """
    m = re.search(r"-(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})-", fname)
    if not m:
        return None
    yy, mo, dd, hh, mi = m.groups()
    if not ("01" <= mo <= "12" and "01" <= dd <= "31" and hh <= "23"):
        return None    # a 10-digit run that isn't a date — say nothing rather than guess
    try:
        return time.strptime("20%s-%s-%s %s:%s" % (yy, mo, dd, hh, mi), "%Y-%m-%d %H:%M")
    except ValueError:
        return None    # e.g. the 31st of a 30-day month


def rec_stamp(fname):
    """'2026-06-11 9:29 PM ET' for a file's own recording start, or ''."""
    ts = rec_parts(fname)
    return "" if ts is None else time.strftime("%Y-%m-%d ", ts) + clock(ts) + " " + TZ_LABEL




def match_when(mid, files):
    """(display string, [search keys]) for when a match happened.

    Prefers the match id, which IS a unix epoch — that is the match's own clock.
    Falls back to the recording stamp in the filename when the id is not an epoch
    (older names), and to nothing at all when neither parses, because a wrong date
    on an archive is worse than no date.
    """
    ts = None
    if re.fullmatch(r"\d{10}", mid or ""):
        n = int(mid)
        if 1_400_000_000 < n < 2_000_000_000:      # sane range, not a stray 10-digit run
            ts = time.localtime(n)
    if ts is None:
        for f in sorted(files):
            ts = rec_parts(f)
            if ts is not None:
                break
    if ts is None:
        return "", []
    # a literal middot, not the entity: this string goes through html.escape,
    # which would turn "&middot;" into a visible "&amp;middot;"
    disp = time.strftime("%a %d %b %Y · ", ts) + clock(ts) + " " + TZ_LABEL
    # both clock spellings, so "9pm" and "21" both find the same match
    keys = [time.strftime(f, ts) for f in ("%Y-%m-%d", "%d %b %Y", "%b %d", "%B %Y", "%a", "%H:%M")]
    keys.append(clock(ts))
    return disp, keys




def count_dems(p):
    n = 0
    for root, _, fs in os.walk(p):
        n += sum(1 for f in fs if f.endswith(".dem"))
    return n

sections = []
lan = DEMOS + "/LAN-PHILLY2026"
if os.path.isdir(lan):
    sections.append('<h2>Event archive</h2><div class="row2">'
                    + card('<div class="t">WSDoD Philly 2026</div><div class="d">'
                           + str(count_dems(lan)) + ' demos &middot; kept indefinitely</div>',
                           "LAN-PHILLY2026/", "wsdod philly 2026 lan event archive")
                    + '</div>')
for city, srvs in by_city.items():
    sections.append('<h2>' + city + '</h2><div class="row2">' + "".join(
        card('<div class="t">' + s + '</div><div class="d">'
             + str(count_dems(DEMOS + "/" + s)) + ' demos</div>', s + "/", city, s)
        for s in srvs) + '</div>')
body = ('<div class="crumb"><a href="/">fastdl</a> / demos</div>'
        '<h1>Demo <span class="accent">archive</span></h1>'
        '<p class="lede">Every match HLTV records across the 24-server fleet, sorted by server and '
        'match type. <b>League and draft matches are kept 180 days; pickups and scrims 90.</b> '
        'Download one before it ages out.</p>' + SEARCH + "".join(sections))
out.append((DEMOS + "/index.html",
            page("KTP Demo Archive", "Demo Archive", body,
                 "Every competitive match on the KTP fleet, recorded by HLTV and kept on a "
                 "per-type retention schedule.")))

# ---------------------------------------------------------------- per server / per type
for s in servers:
    if s in SKIP:
        continue
    sp = DEMOS + "/" + s
    types = sorted(t for t in os.listdir(sp) if os.path.isdir(sp + "/" + t))
    body = ('<div class="crumb"><a href="/">fastdl</a> / <a href="/demos/">demos</a> / ' + s + '</div>'
            '<h1>' + s + ' <span class="accent">demos</span></h1>'
            '<p class="lede">Recorded matches on ' + s + ', by match type.</p>'
            + SEARCH + '<div class="row2">' + "".join(
              card('<div class="t">' + html.escape(TYPE_LABEL.get(t, t))
                   + '</div><div class="d">' + str(count_dems(sp + "/" + t))
                   + ' demos &middot; kept ' + RETENTION.get(t, "90 days") + '</div>',
                   t + "/", t, s) for t in types) + '</div>')
    out.append((sp + "/index.html", page("KTP demos — " + s, "Demo Archive", body,
                "Every competitive match on the KTP fleet, recorded by HLTV.")))

    for t in types:
        tp = sp + "/" + t
        files = sorted(f for f in os.listdir(tp) if f.endswith(".dem"))
        groups = collections.OrderedDict()
        for f in files:
            m = re.search(r"([\w.\-]+?)-(?:[A-Z]+\d+)(?:_h\d)?-\d{10}-", f)
            groups.setdefault(m.group(1).split("_", 1)[-1] if m else f, []).append(f)
        cards = []
        for mid, fl in groups.items():
            first = sorted(fl)[0]
            mp = re.search(r"-\d{10}-(.+?)(?:_part\d)?\.dem$", first)
            when, when_keys = match_when(mid, fl)
            chips = []
            for f in sorted(fl):
                hm = re.search(r"_(h\d)-", f)
                pm = re.search(r"_part(\d)", f)
                lbl = (hm.group(1) if hm else "dem") + (("·p" + pm.group(1)) if pm else "")
                rec = rec_stamp(f)
                chips.append('<a class="f" href="' + html.escape(f) + '"'
                             + (' title="recorded ' + html.escape(rec, quote=True) + '"' if rec else "")
                             + '><span class="h">' + lbl + '</span><span class="sz">'
                             + human(os.path.getsize(tp + "/" + f)) + '</span></a>')
            inner = ('<div class="mh"><span class="teams">'
                     + html.escape(when or mid) + '</span><span class="meta">'
                     + html.escape(mp.group(1) if mp else "")
                     + ('  &middot;  ' + html.escape(mid) if when else "")
                     + '</span></div><div class="files">' + "".join(chips) + '</div>')
            # everything on the card, plus what is true but not shown: the other
            # date spellings, the server and the match type
            key = searchable(inner, *(when_keys + [s, t, TYPE_LABEL.get(t, t)]))
            cards.append('<div class="match" data-s="' + html.escape(key, quote=True)
                         + '">' + inner + '</div>')
        body = ('<div class="crumb"><a href="/">fastdl</a> / <a href="/demos/">demos</a> / '
                '<a href="/demos/' + s + '/">' + s + '</a> / ' + t + '</div>'
                '<h1>' + s + ' &mdash; <span class="accent">'
                + html.escape(TYPE_LABEL.get(t, t)) + '</span></h1>'
                '<p class="lede">' + str(len(files)) + ' demos in ' + str(len(groups))
                + ' matches. Kept ' + RETENTION.get(t, "90 days")
                + ' from recording, then deleted.</p>' + SEARCH + "".join(cards))
        out.append((tp + "/index.html", page("KTP demos — " + s + " " + t, "Demo Archive", body,
                    "Every competitive match on the KTP fleet, recorded by HLTV.")))


# ---------------------------------------------------------------- /dod subdirectories
# Skips anything nginx now 404s: addons/ held the rcon password, the HLTV API key and the
# Discord relay secret in plain text, and dlls/cl_dlls/logs are server-side too. Generating
# a browsable index for a blocked path would only advertise it.
DOD_BLOCKED = {"addons", "dlls", "cl_dlls", "logs"}
for root, dirs, files in os.walk(FASTDL + "/dod"):
    rel = os.path.relpath(root, FASTDL + "/dod")
    if rel == ".":
        continue
    top = rel.split(os.sep)[0]
    if top in DOD_BLOCKED:
        dirs[:] = []
        continue
    subs = sorted(d for d in dirs)
    fl = sorted(f for f in files if f != "index.html")
    crumbs = ['<a href="/">fastdl</a>', '<a href="/dod/">dod</a>']
    acc = ""
    for part in rel.split(os.sep)[:-1]:
        acc += part + "/"
        crumbs.append('<a href="/dod/' + acc + '">' + html.escape(part) + '</a>')
    crumbs.append(html.escape(rel.split(os.sep)[-1]))
    cards = ""
    if subs:
        cards += '<h2>Folders</h2><div class="row2">' + "".join(
            card('<div class="t">' + html.escape(x) + '/</div><div class="d">'
                 + str(len(os.listdir(os.path.join(root, x)))) + ' entries</div>',
                 x + "/") for x in subs) + '</div>'
    if fl:
        rows = "".join(
            card('<span class="h">' + html.escape(f) + '</span><span class="sz">'
                 + human(os.path.getsize(os.path.join(root, f))) + '</span>',
                 f, cls="f") for f in fl)
        cards += ('<h2>' + str(len(fl)) + ' files</h2><div class="files">' + rows + '</div>')
    body = ('<div class="crumb">' + " / ".join(crumbs) + '</div>'
            '<h1><span class="accent">' + html.escape(rel) + '</span></h1>'
            '<p class="lede">Client content. Your game fetches these automatically on connect.</p>'
            + SEARCH + cards)
    out.append((os.path.join(root, "index.html"),
                page("KTP FastDL — dod/" + rel, "Client Downloads", body,
                     "Fast content distribution for KTP game servers.")))

print("index pages: %d" % len(out))
if args.apply:
    for p, b in out:
        open(p, "w", encoding="utf-8", newline="\n").write(b)
        os.chmod(p, 0o644)
    print("written.")
else:
    for p, _ in out[:6]:
        print("   " + p)
    print("   ... (%d more)" % max(0, len(out) - 6))
    print("DRY RUN — nothing written.")
