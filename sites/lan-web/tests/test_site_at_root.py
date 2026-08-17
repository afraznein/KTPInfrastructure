"""LAN_SITE_AT_ROOT: the WSDoD site takes "/" and the briefing moves to /lan.

Run in a subprocess. The flag is read at import time, so flipping it in-process
would need sys.modules surgery that leaks into whatever test runs next.

Why this file exists: mounting the site at "/" from the original site-mount
block silently swallowed /api, /auth and /admin — Starlette matches routes in
registration order and Mount("/") matches every path, so the front page worked
while sign-in, uploads, voting and the admin panel all 404'd. The ordering is
load-bearing and nothing else here would catch it moving.
"""
import subprocess
import sys
import textwrap

PROBE = textwrap.dedent(
    """
    import json, os, pathlib, sys, tempfile
    sys.path.insert(0, os.getcwd())
    d = tempfile.mkdtemp()
    pathlib.Path(d, "index.html").write_text("WSDOD-SITE")
    os.environ["LAN_SITE_DIR"] = d
    os.environ["LAN_SITE_MOUNT"] = "/2026"
    os.environ["LAN_SITE_AT_ROOT"] = %(flag)r
    os.environ.setdefault("SECRET_KEY", "test-secret")

    from fastapi.testclient import TestClient
    from app.main import app
    c = TestClient(app)

    out = {}
    for path in ("/", "/lan", "/2026/", "/api/photos", "/logout"):
        try:
            r = c.get(path, follow_redirects=False)
            out[path] = {
                "status": r.status_code,
                "is_site": r.text.strip() == "WSDOD-SITE",
                "location": r.headers.get("location", ""),
            }
        except Exception as exc:
            # The handler ran and hit the absent DB: that is "route reached",
            # which is the thing under test. A shadowed route 404s instead and
            # never raises.
            out[path] = {"status": "reached", "is_site": False, "location": ""}
    print(json.dumps(out))
    """
)


_CACHE = {}


def _probe(flag):
    """One subprocess per flag value, not per assertion; each spawn re-imports
    FastAPI and costs ~9s."""
    if flag not in _CACHE:
        r = subprocess.run([sys.executable, "-c", PROBE % {"flag": flag}],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr[-2000:]
        import json
        _CACHE[flag] = json.loads(r.stdout.strip().splitlines()[-1])
    return _CACHE[flag]


def test_flag_off_is_todays_behaviour():
    r = _probe("")
    assert r["/"]["status"] == 200 and not r["/"]["is_site"]   # LAN briefing
    assert r["/lan"]["status"] == 404
    assert r["/2026/"]["is_site"]


def test_flag_on_serves_the_site_at_root():
    r = _probe("1")
    assert r["/"]["is_site"], "the site should be served at /"
    assert r["/lan"]["status"] == 200, "the LAN briefing should move to /lan"


def test_flag_on_keeps_2026_working():
    # Links already shared point at /2026/; the flip must not break them.
    assert _probe("1")["/2026/"]["is_site"]


def test_flag_on_does_not_shadow_the_api():
    # The whole point. A Mount("/") registered above the routers returns 404
    # here without ever invoking the handler.
    r = _probe("1")
    assert r["/api/photos"]["status"] != 404, (
        "the root mount is shadowing /api — it must be registered after every "
        "include_router in app/main.py")


def test_logout_lands_on_the_front_page_in_both_modes():
    # url_for("index") is the briefing, which moves to /lan under the flag, so
    # logout would land there instead of home.
    for flag in ("", "1"):
        loc = _probe(flag)["/logout"]["location"]
        assert loc.rstrip("/").endswith("testserver") or loc in ("/", ""), (
            f"logout went to {loc!r} with LAN_SITE_AT_ROOT={flag!r}")
