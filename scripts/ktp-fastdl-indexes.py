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

The demo archive also gets /demos/players.html, a SteamID/name lookup joined from
hlstatsx.ktp_match_players. It is the only part that touches a database, so it is the only
part allowed to be missing: if the read fails the page is removed and everything else is
written exactly as before.

The /dod page also publishes overviews/ktp-s10-overviews.zip: every command-map overview
for the current map pool in one archive. Individual links mean a player fetches nine pairs
and then works out where they go, which is the step that loses people. The pool is read
from the fleet's own ktp_maps.ini under /home/dod/distribute, never from a repo checkout --
/opt/ktp-infra is deliberately never auto-pulled, and a map re-cut mid-season (dod_saints2_b3e
became _b5e) would be packed under a name no BSP carries. The archive is byte-deterministic,
so an unchanged pool rewrites nothing; a pool that cannot be resolved in full leaves the
published archive alone rather than replacing it with a partial one.

Idempotent: only ever writes index.html, players.html and that archive (and removes
players.html when the lookup cannot be built). Usage: fastdl_indexes.py [--apply] [--out-root DIR]
"""
import argparse, collections, html, io, json, os, re, subprocess, time, zipfile

FASTDL = "/var/www/fastdl"
DEMOS = "/home/hltvserver/hlds/dod/demos"
# The fleet's own copy of the map list, not the repo's: the distributor sends this file to
# all 24 instances, so it is what the servers actually run.
MAPS_INI = "/home/dod/distribute/addons/ktpamx/configs/ktp_maps.ini"
PACK_NAME = "ktp-s10-overviews.zip"
PACK_NOTE = "KTP-OVERVIEWS-README.txt"

# Stamped into every footer. The archive is a generated static site, so "what is
# on this page" and "what is on disk" are only the same as of the last build --
# a demo finishing at 21:00 was invisible until the next morning before this was
# hourly, and nothing on the page said so.
GENERATED = time.strftime("%Y-%m-%d %H:%M %Z")
SKIP = {"LAN-PHILLY2026"}
CITY = {"ATL": "Atlanta", "DAL": "Dallas", "DEN": "Denver", "NY": "New York", "CHI": "Chicago"}
TYPE_LABEL = {"ktp": "League (.ktp)", "scrim": "Scrims", "draft": "Drafts", "12man": "12-man"}
RETENTION = {"ktp": "180 days", "draft": "180 days", "12man": "90 days", "scrim": "90 days"}

# MATCH_ID_RE from match_analytics minus -TEST: placeholders like 1.3-confirm-NY2 recur across matches.
MATCH_ID = r"(?:\d+|1\.3-\d+)-[A-Z]{2,5}\d+"
MATCH_ID_RE = re.compile(MATCH_ID)
# A second server token after the id is the HLTV that recorded it, not the match.
DEMO_MATCH_RE = re.compile(r"[a-z0-9]+_(" + MATCH_ID + r")(?=[-_])")
STEAM_ID_RE = re.compile(r"[01]:\d{1,10}")
STEAM64_BASE = 76561197960265728
PLAYER_QUERY = ("SELECT match_id, steam_id, HEX(player_name) FROM ktp_match_players"
                " ORDER BY joined_at, id")
PLAYER_LINK_SLOT = "<!--players-link-->"
PLAYER_LINK = ('<p class="note"><a href="/demos/players.html">Find every demo a player appears in'
               ' &rarr;</a></p>')

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
  // The filter is per-page, but browsers restore form state on back/forward
  // (and bfcache restores the whole page), so a term typed on one page came
  // back looking like it had followed you to another. Clear on every show,
  // including bfcache restores, where no 'load' fires.
  function reset(){ if(q.value){ q.value=''; } apply(); }
  window.addEventListener('pageshow', reset);
  reset();
})();
</script>"""


# Whole-archive search, demos index page only. The per-page filter above can only
# hide what is already rendered, so on the index -- which lists servers, not demos
# -- typing a map name matched nothing and read as "we have no armory demos".
# Rendered from an embedded index rather than ~1800 hidden rows: the rows would
# be dead weight on every visit, and the per-page filter would count them.
GLOBAL_JS = """<script>
(function(){
  var q=document.getElementById('q'), box=document.getElementById('gs'),
      raw=document.getElementById('gsdata');
  if(!q||!box||!raw) return;
  var idx=JSON.parse(raw.textContent), CAP=300;
  function draw(){
    var terms=q.value.trim().toLowerCase().split(/\\s+/).filter(Boolean);
    if(!terms.length){ box.hidden=true; box.innerHTML=''; return; }
    var hits=idx.filter(function(e){
      return terms.every(function(w){ return e[0].indexOf(w)!==-1; });
    });
    box.hidden=false;
    if(!hits.length){
      box.innerHTML='<h2>Across every server</h2><p class="note">No demo anywhere matches that.</p>';
      return;
    }
    var shown=hits.slice(0,CAP), rows=shown.map(function(e){
      return '<a class="card" href="'+e[1]+'"><div class="t">'+e[2]
           +'</div><div class="d">'+e[3]+'</div></a>';
    }).join('');
    box.innerHTML='<h2>Across every server</h2><p class="note">'
      +hits.length+' demo'+(hits.length===1?'':'s')+' match'+(hits.length===1?'es':'')
      +(hits.length>CAP?(' &mdash; showing the newest '+CAP):'')
      +'.</p><div class="row2">'+rows+'</div>';
  }
  q.addEventListener('input',draw);
  window.addEventListener('pageshow',draw);
  draw();
})();
</script>"""


def footer(what):
    return ('<footer class="split">\n  <div class="col">\n    <h4>What this is</h4>\n    <p>'
            + what + '</p>\n  </div>\n  <div class="col">\n    <h4>Keep it running</h4>\n'
            '    <p><a href="https://github.com/sponsors/afraznein">Sponsor the infrastructure</a> '
            '&middot;\n      <a href="https://support.ktpdod.com">Report a problem</a></p>\n'
            '    <p class="mt8"><span class="accent">Keep the Practice</span></p>\n'
            '    <p class="note">File list updated ' + html.escape(GENERATED) + '.<br>'
            'Rebuilt hourly &mdash; a match that just finished may take up to an hour to appear.</p>\n'
            '  </div>\n</footer>\n')

# Root-relative nav hrefs 404 on netcode/profiles/bundles, which each have their own docroot.
# That was fixed on 2026-07-17 and regressed twice, so it is asserted rather than remembered.
def _nav(markup):
    hrefs = re.findall(r'class="navlink[^"]*" href="([^"]+)"', markup)
    bad = [h for h in hrefs if not h.startswith("http")]
    assert hrefs and not bad, "nav href must be absolute, got %s" % (bad or "no navlinks")
    return markup

def page(title, site, body, what, extra_js=""):
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
      SCRIPT, extra_js, '</body></html>', ''])

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


def _no_players(reason):
    print("WARNING: player index omitted: " + reason)
    return None


def load_match_players(timeout):
    """{match_id: {steam_id: name}} from hlstatsx, or None when it cannot be trusted.

    None on every failure -- no client, refused login, timeout, non-zero exit, no
    usable row -- so the caller drops the lookup instead of failing the whole run.
    Names are fetched as hex because --batch output is framed by tabs and newlines.
    """
    try:
        import pwd
        # auth_socket checks the OS user, and the client does not reliably send it unasked.
        user = pwd.getpwuid(os.geteuid()).pw_name
        proc = subprocess.run(
            ["mysql", "--batch", "--skip-column-names", "--connect-timeout=5",
             "--user=" + user, "-e", PLAYER_QUERY, "hlstatsx"],
            stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8",
            errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return _no_players("mysql did not answer within %gs" % timeout)
    except (OSError, ImportError, KeyError) as e:
        return _no_players("could not run mysql: %s" % e)
    if proc.returncode != 0:
        return _no_players("mysql exited %d: %s" % (proc.returncode, proc.stderr.strip()[-300:]))
    rosters, malformed = {}, 0
    for line in proc.stdout.splitlines():
        f = line.split("\t")
        if len(f) != 3 or not STEAM_ID_RE.fullmatch(f[1]):
            malformed += 1
            continue
        try:
            name = bytes.fromhex(f[2]).decode("utf-8", "replace").strip()
        except ValueError:
            malformed += 1
            continue
        if MATCH_ID_RE.fullmatch(f[0]):
            # rows arrive oldest first, so a later join in the same match wins the name
            rosters.setdefault(f[0], {})[f[1]] = name or f[1]
    if malformed:
        print("player index: skipped %d malformed rows" % malformed)
    if not rosters:
        return _no_players("no usable rows in ktp_match_players")
    return rosters


def demo_match_key(fname):
    m = DEMO_MATCH_RE.match(fname)
    return m.group(1) if m else None


def steam_spellings(sid):
    """(STEAM_0 display, SteamID64, every spelling someone might paste) for a bare Y:Z id."""
    y, z = sid.split(":")
    s64 = str(STEAM64_BASE + int(z) * 2 + int(y))
    return "STEAM_0:" + sid, s64, ["STEAM_0:" + sid, "STEAM_1:" + sid, sid, s64]


PLAYER_JS = """<script>
(function(){
  var q=document.getElementById('pq'), box=document.getElementById('pr'),
      cnt=document.getElementById('pqc'), raw=document.getElementById('pdata');
  if(!q||!box||!raw) return;
  var d=JSON.parse(raw.textContent), P=d.players, D=d.demos, CAP=50;
  function card(p){
    var chips=p[5].map(function(i){
      var e=D[i];
      return '<a class="f" href="'+e[0]+'"><span class="h">'+e[1]+'</span><span class="sz">'+e[2]+'</span></a>';
    }).join('');
    return '<div class="match"><div class="mh"><span class="teams">'+p[3]+'</span>'
      +'<span class="meta"><a href="#'+p[1]+'">'+p[1]+'</a> &middot; '+p[2]+'</span></div>'
      +(p[4]?'<div class="meta">also played as '+p[4]+'</div>':'')
      +'<div class="meta">'+p[5].length+' demo'+(p[5].length===1?'':'s')+', newest first</div>'
      +'<div class="files">'+chips+'</div></div>';
  }
  function draw(){
    var terms=q.value.trim().toLowerCase().split(/\\s+/).filter(Boolean);
    if(!terms.length){ box.innerHTML=''; cnt.textContent=P.length+' players'; return; }
    var hits=P.filter(function(p){
      return terms.every(function(w){ return p[0].indexOf(w)!==-1; });
    });
    cnt.textContent=hits.length+' of '+P.length+' players';
    if(!hits.length){ box.innerHTML='<p class="note">No player matches that.</p>'; return; }
    box.innerHTML=hits.slice(0,CAP).map(card).join('')
      +(hits.length>CAP?'<p class="note">Showing the first '+CAP+' &mdash; narrow the search.</p>':'');
  }
  // #STEAM_0:1:234 is the permalink for one player's demos.
  function fromHash(){
    var h=''; try{ h=decodeURIComponent(location.hash.slice(1)); }catch(e){}
    if(h) q.value=h;
    draw();
  }
  q.addEventListener('input',draw);
  window.addEventListener('hashchange',fromHash);
  window.addEventListener('pageshow',fromHash);
})();
</script>"""


def player_lookup_page(entries, rosters):
    """players.html for the whole archive, or None when no demo joins a roster.

    `entries` are the whole-archive index rows, newest first, each carrying its
    match key; a player's first name seen is therefore the most recent one.
    """
    demos, people = [], collections.OrderedDict()
    for e in entries:
        roster = rosters.get(e[5]) if e[5] else None
        if not roster:
            continue
        demos.append(e[1:4])
        for sid, name in roster.items():
            p = people.setdefault(sid, {"names": collections.OrderedDict(), "demos": []})
            p["names"][name] = None
            p["demos"].append(len(demos) - 1)
    if not people:
        return _no_players("no archived demo matched a player row")
    rows = []
    for sid, p in people.items():
        shown, s64, spellings = steam_spellings(sid)
        names = list(p["names"])
        rows.append([" ".join(spellings + names).lower(), shown, s64, html.escape(names[0]),
                     html.escape(", ".join(names[1:])), p["demos"]])
    rows.sort(key=lambda r: (html.unescape(r[3]).lower(), r[1]))
    body = ('<div class="crumb"><a href="/">fastdl</a> / <a href="/demos/">demos</a> / players</div>'
            '<h1>Find a <span class="accent">player</span></h1>'
            '<p class="lede">Search by name, SteamID or SteamID64 to list every archived demo a '
            'player appears in. Names are the ones they played under.</p>'
            '<div class="search"><input id="pq" type="search" autocomplete="off" spellcheck="false"'
            ' placeholder="Name, STEAM_0:1:234 or 7656119&hellip;" aria-label="Find a player"'
            ' aria-controls="pqc"><span id="pqc" class="qc" role="status" aria-live="polite"></span></div>'
            '<p class="note">' + str(len(rows)) + ' players across ' + str(len(demos))
            + ' demos. Only matches the stats pipeline recorded a roster for are listed; '
            'the <a href="/demos/">full archive</a> has every demo.</p>'
            '<div id="pr"></div>'
            '<script id="pdata" type="application/json">'
            + json.dumps({"players": rows, "demos": demos}, separators=(",", ":")).replace("</", "<\\/")
            + '</script>')
    return (page("KTP Demo Archive — players", "Demo Archive", body,
                 "Every competitive match on the KTP fleet, recorded by HLTV, searchable by player.",
                 extra_js=PLAYER_JS), len(rows), len(demos))


# ------------------------------------------------- S10 overview pack
# A section heading in ktp_maps.ini is a comment naming MAPS in capitals, and the seasonal
# block runs from its own heading to the next one. Keying on the heading rather than on a
# list of map names is what survives a re-cut: three stems changed mid-S10 and anything
# holding its own copy of the pool shipped the dead ones.
INI_HEADING = re.compile(r"^\s*;\s*(.*\bMAPS\b.*?)\s*$")
INI_SECTION = re.compile(r"^\s*\[([^\]\s]+)\]")


def pool_from_ini(path):
    """Map stems of the seasonal block, in the file's own schedule order."""
    stems, inside = [], False
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            heading = INI_HEADING.match(line)
            if heading:
                if re.search(r"\bSEASONAL\b", heading.group(1), re.I):
                    inside = True
                elif inside:
                    break
                continue
            section = INI_SECTION.match(line)
            if inside and section:
                stems.append(section.group(1))
    return stems


def pack_entries(fastdl, pool):
    """(entries, missing) -- the overview pair for every pool map, or what is absent.

    Both halves or neither: the engine asks for overviews/<map>.txt and overviews/<map>.bmp
    separately, and either one alone draws no usable overview.
    """
    entries, missing = [], []
    for stem in pool:
        names = [stem + ext for ext in (".txt", ".bmp")]
        paths = [os.path.join(fastdl, "dod", "overviews", n) for n in names]
        if all(os.path.isfile(x) for x in paths):
            entries.extend(zip(names, paths))
        else:
            missing.append(stem)
    return entries, missing


def pack_note(entries, stamp):
    """CRLF because this is read in Notepad on the way to a Steam folder."""
    maps = sorted({n.rsplit(".", 1)[0] for n, _ in entries})
    return ("KTP command-map overviews -- ktpleague.gg\r\n\r\n"
            "Copy every .txt and .bmp in here into:\r\n\r\n"
            "    <Steam>\\steamapps\\common\\Day of Defeat\\dod\\overviews\\\r\n\r\n"
            "Nothing needs renaming -- the engine asks for overviews/<mapname>.txt and\r\n"
            "overviews/<mapname>.bmp by name. Overwriting an older copy is safe.\r\n\r\n"
            "Maps in this archive:\r\n"
            + "".join("    " + m + "\r\n" for m in maps)
            + "\r\nAssets dated " + time.strftime("%Y-%m-%d", time.localtime(stamp))
            + ". Rebuilt from https://fastdl.ktpdod.com/dod/overviews/\r\n")


def pack_bytes(entries):
    """A byte-deterministic archive, so "rewrite only when it changed" is a comparison.

    Every member carries its source mtime rather than the build clock. An hourly job that
    stamped now() would hand every visitor a fresh 7 MB download of identical assets.
    """
    stamp = max(int(os.path.getmtime(path)) for _, path in entries)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for arcname, path in list(entries) + [(PACK_NOTE, None)]:
            when = stamp if path is None else int(os.path.getmtime(path))
            info = zipfile.ZipInfo(arcname, time.localtime(when)[:6])
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            if path is None:
                archive.writestr(info, pack_note(entries, stamp))
            else:
                with open(path, "rb") as handle:
                    archive.writestr(info, handle.read())
    return buf.getvalue()


ap = argparse.ArgumentParser()
ap.add_argument("--apply", action="store_true")
ap.add_argument("--fastdl", default=FASTDL)
ap.add_argument("--demos", default=DEMOS)
ap.add_argument("--out-root", help="write pages under this directory instead of in place")
ap.add_argument("--maps-ini", default=MAPS_INI,
                help="ktp_maps.ini whose seasonal block enumerates the pool")
ap.add_argument("--db-timeout", type=float, default=20.0)
args = ap.parse_args()
FASTDL, DEMOS = args.fastdl, args.demos
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


def file_rows(directory, names):
    return "".join(
        card('<span class="h">' + html.escape(f) + '</span><span class="sz">'
             + human(os.path.getsize(os.path.join(directory, f))) + '</span>', f, cls="f")
        for f in names)


# The loose files were counted here and never listed, so a human looking for a
# texture wad found one nowhere on the site. They are not decoration: the engine
# asks for a map's wads at /dod/<name>.wad, one level ABOVE maps/, which is the
# last place anyone browsing for them thinks to look.
wads = [f for f in loose if f.lower().endswith(".wad")]
other_loose = [f for f in loose if f not in set(wads)]
loose_cards = ""
if wads:
    loose_cards += ('<h2 id="wads">' + str(len(wads)) + ' texture WADs</h2>'
                    '<p class="note">A map\'s textures live in these, not in <code>maps/</code> '
                    '&mdash; the engine asks for <code>/dod/&lt;name&gt;.wad</code>. Only custom '
                    'maps need one; <code>halflife.wad</code> ships with the game and is not here '
                    'on purpose.</p>'
                    '<div class="files">' + file_rows(FASTDL + "/dod", wads) + '</div>')
if other_loose:
    loose_cards += ('<h2>' + str(len(other_loose)) + ' other loose files</h2>'
                    '<div class="files">' + file_rows(FASTDL + "/dod", other_loose) + '</div>')

# The ini is the spec. An archive assembled from a map list written anywhere else ships a
# stem the fleet has already re-cut past, which is the one failure this pack must not have.
pack_cards, pack_blob = "", None
pool = pool_from_ini(args.maps_ini) if os.path.isfile(args.maps_ini) else []
if not pool:
    print("WARNING: overview pack omitted: no seasonal block in " + args.maps_ini)
else:
    pack_files, pack_missing = pack_entries(FASTDL, pool)
    if pack_missing:
        # Partial is worse than absent: the page promises every pool map, so a player finds
        # the gap in game, on the one map they were about to play.
        print("WARNING: overview pack omitted: no overview pair for "
              + ", ".join(pack_missing))
    else:
        pack_blob = pack_bytes(pack_files)
        pack_cards = (
            '<h2 id="overviews">Overview pack for the current pool</h2>'
            '<p class="note">Command-map overviews for the maps in rotation, in one archive. '
            'Unzip it into <code>Day of Defeat\\dod\\overviews\\</code> and every map in the '
            'pool has its overview &mdash; nothing to rename, and overwriting an older copy '
            'is safe. Grab the individual files below if you only want one map.</p>'
            '<div class="files">'
            + card('<span class="h">' + PACK_NAME + '</span><span class="sz">'
                   + human(len(pack_blob)) + '</span>', "overviews/" + PACK_NAME,
                   "overview pack archive zip", cls="f")
            + '</div><div class="files">' + "".join(
                card('<span class="h">' + html.escape(n) + '</span><span class="sz">'
                     + human(os.path.getsize(f)) + '</span>', "overviews/" + n, cls="f")
                for n, f in pack_files) + '</div>')

body = ('<div class="crumb"><a href="/">fastdl</a> / dod</div>'
        '<h1>Client <span class="accent">download</span> files</h1>'
        '<p class="lede">These are the files your client pulls automatically when it joins a KTP '
        'server &mdash; maps, textures, models, sounds. <b>You do not need to download anything '
        'here by hand.</b> The list is browsable if you want to fetch one file directly.</p>'
        '<p class="note">' + str(len(present)) + ' directories, ' + str(len(loose))
        + ' loose files. Served over HTTP as <code>sv_downloadurl</code>.</p>'
        + SEARCH + pack_cards + "".join(cards)
        + '<h2>Other directories</h2><div class="row2">' + "".join(
            card('<div class="t">' + d + '/</div>', d + "/")
            for d in sorted(present - {x for _, ds in DOD_GROUPS for x in ds})) + '</div>'
        + loose_cards)
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


def rec_key(fname):
    """Sort key: when this demo was recorded, newest first.

    Filenames sort alphabetically by match id, which is not chronological -- a
    1.3 queue id and a unix timestamp interleave, so the newest match could land
    anywhere on the page. Files with no readable date sort last rather than
    jumping to the top.
    """
    ts = rec_parts(fname)
    return time.strftime("%Y%m%d%H%M", ts) if ts else "0"




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
        'Download one before it ages out.</p>' + PLAYER_LINK_SLOT + SEARCH
        + '<div id="gs" hidden></div>' + "".join(sections))
demos_index_body = body          # written after the loop below, which fills GLOBAL_INDEX
GLOBAL_INDEX = []                # [search key, href, title, meta] per demo file

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
        # Newest match first. Groups keep insertion order, so ordering the file
        # list orders the page.
        files = sorted((f for f in os.listdir(tp) if f.endswith(".dem")),
                       key=lambda f: (rec_key(f), f), reverse=True)
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
                # Feed the whole-archive search on the demos index. Keyed on the
                # same things a person would type: server, map, match id, date.
                mapname = mp.group(1) if mp else ""
                GLOBAL_INDEX.append([
                    " ".join((s, t, TYPE_LABEL.get(t, t), mid, mapname, rec, f)).lower(),
                    html.escape("/demos/%s/%s/%s" % (s, t, f), quote=True),
                    html.escape("%s — %s" % (s, mapname or mid)),
                    html.escape("%s · %s · %s" % (TYPE_LABEL.get(t, t), rec or "date unknown", lbl)),
                    rec_key(f),      # sort field only; stripped before embedding
                    demo_match_key(f),   # player-lookup join key; also stripped
                ])
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

# Written here, not where its body was built: the whole-archive index is only
# complete once every server/type has been walked. Newest first, so a capped
# result list drops the oldest rather than an arbitrary slice.
GLOBAL_INDEX.sort(key=lambda e: e[4], reverse=True)
_gs = [e[:4] for e in GLOBAL_INDEX]

PLAYERS_PAGE = DEMOS + "/players.html"
player_page = None
rosters = load_match_players(args.db_timeout)
if rosters is not None:
    try:
        player_page = player_lookup_page(GLOBAL_INDEX, rosters)
    except Exception as e:  # a render bug must cost the lookup, never the archive
        player_page = _no_players("could not render: %r" % e)
if player_page:
    print("player index: %d players linked to %d demos" % player_page[1:])
    out.append((PLAYERS_PAGE, player_page[0]))

out.append((DEMOS + "/index.html",
            page("KTP Demo Archive", "Demo Archive",
                 demos_index_body.replace(PLAYER_LINK_SLOT, PLAYER_LINK if player_page else "")
                 + '<script id="gsdata" type="application/json">'
                 + json.dumps(_gs, separators=(",", ":")).replace("</", "<\\/")
                 + '</script>',
                 "Every competitive match on the KTP fleet, recorded by HLTV and kept on a "
                 "per-type retention schedule.",
                 extra_js=GLOBAL_JS)))


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
        cards += ('<h2>' + str(len(fl)) + ' files</h2><div class="files">'
                  + file_rows(root, fl) + '</div>')
    # Browsing maps/ for a texture wad finds none, and the page gave no hint why:
    # they are one level up, because the engine asks for /dod/<name>.wad.
    hint = ''
    if rel == "maps" and wads:
        hint = ('<p class="note">Looking for a map\'s <b>texture WADs</b>? They are not in here '
                '&mdash; the engine asks for <code>/dod/&lt;name&gt;.wad</code>, so all '
                + str(len(wads)) + ' of them are <a href="/dod/#wads">one level up, in '
                '<code>dod/</code></a>.</p>')
    body = ('<div class="crumb">' + " / ".join(crumbs) + '</div>'
            '<h1><span class="accent">' + html.escape(rel) + '</span></h1>'
            '<p class="lede">Client content. Your game fetches these automatically on connect.</p>'
            + hint + SEARCH + cards)
    out.append((os.path.join(root, "index.html"),
                page("KTP FastDL — dod/" + rel, "Client Downloads", body,
                     "Fast content distribution for KTP game servers.")))

def dest(p):
    return os.path.join(args.out_root, p.lstrip("/")) if args.out_root else p


print("index pages: %d" % len(out))
if args.apply:
    # An earlier run's roster must not outlive a read that failed.
    if player_page is None and os.path.exists(dest(PLAYERS_PAGE)):
        os.remove(dest(PLAYERS_PAGE))
        print("removed " + dest(PLAYERS_PAGE))
    if pack_blob is not None:
        d = dest(FASTDL + "/dod/overviews/" + PACK_NAME)
        if args.out_root:
            os.makedirs(os.path.dirname(d), exist_ok=True)
        # Deterministic bytes, so an unchanged pool rewrites nothing: the archive keeps its
        # mtime and a player's conditional request stays a 304.
        if os.path.exists(d) and open(d, "rb").read() == pack_blob:
            print("unchanged " + d)
        else:
            open(d, "wb").write(pack_blob)
            os.chmod(d, 0o644)
            print("wrote " + d)
    for p, b in out:
        d = dest(p)
        if args.out_root:
            os.makedirs(os.path.dirname(d), exist_ok=True)
        open(d, "w", encoding="utf-8", newline="\n").write(b)
        os.chmod(d, 0o644)
    print("written.")
else:
    for p, _ in out[:6]:
        print("   " + p)
    print("   ... (%d more)" % max(0, len(out) - 6))
    if pack_blob is not None:
        print("   " + FASTDL + "/dod/overviews/" + PACK_NAME
              + " (%s)" % human(len(pack_blob)))
    print("DRY RUN — nothing written.")
