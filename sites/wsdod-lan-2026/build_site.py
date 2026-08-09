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


def rel(from_slug, to_slug):
    """Link between edition pages, both directions, from a nested or root page."""
    up = "" if not from_slug else "../"
    return (up + (to_slug + "/" if to_slug else "")) or "./"


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

    built = []
    for eid, (slug, title, desc) in PAGE.items():
        out = shell
        for s in sections.values():
            keep = s["eds"] is None or eid in s["eds"]
            out = out.replace("\x00%s\x00" % id(s), s["html"] if keep else "")

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
                blocks.append('<script id="%s" type="application/json">%s</script>'
                              % (name, data[name].strip()))

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
