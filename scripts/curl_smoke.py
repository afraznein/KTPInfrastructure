#!/usr/bin/env python3
"""KTPAmxxCurl before/after crash-class smoke on the tier-2 runner.

Boots hlds_linux from the runner serverfiles, drives boot -> changelevel -> quit
(graceful shutdown = the CU-01 curl_global_cleanup ordering path), and asserts:
  rc==0, zero new /tmp cores, clean KTP_ExtensionShutdown + module detach,
  no curl WARNING / segfault / abort lines.

Usage: set -a; . /etc/ktp/tier2-test-rcon.env; set +a; curl_smoke.py <label>
Prints a JSON result line prefixed RESULT_JSON: for machine parse.
"""
import json, os, signal, socket, subprocess, sys, time, glob
from pathlib import Path

# Checked before the runner-path import so a missing value is the error you see.
RCON_PW = os.environ.get("KTP_TEST_RCON_PASSWORD", "")
if not RCON_PW:
    sys.exit("curl_smoke: KTP_TEST_RCON_PASSWORD is not set "
             "(on the tier-2 runner: set -a; . /etc/ktp/tier2-test-rcon.env; set +a)")

REPO = "/opt/ktp-tier2-runner/actions-runner/_work/KTPInfrastructure/KTPInfrastructure"
SF = Path("/opt/ktp-tier2-runner/serverfiles")
sys.path.insert(0, REPO)
from tests.smoke.rcon import RconClient, wait_until_responsive, RconError  # noqa: E402

LABEL = sys.argv[1] if len(sys.argv) > 1 else "run"


def free_udp():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


def cores_now():
    return set(glob.glob("/tmp/core.*"))


def main():
    port = free_udp()
    log = SF / f"smoke-curl-{LABEL}-{port}.log"
    argv = ["./hlds_linux", "-game", "dod", "-strictportbind",
            "+ip", "127.0.0.1", "-port", str(port), "+clientport", str(port - 10),
            "+map", "dod_anzio", "+maxplayers", "13", "-pingboost", "2",
            "+rcon_password", RCON_PW, "+sv_lan", "1",
            "+servercfgfile", "test_server.cfg"]
    env = dict(os.environ)
    ld = f"{SF}:{Path.home()/'.steam'/'sdk32'}"
    env["LD_LIBRARY_PATH"] = ld + ":" + env.get("LD_LIBRARY_PATH", "")

    cores_before = cores_now()
    res = {"label": LABEL, "port": port, "rc": None, "ready": False,
           "changelevel_ok": False, "new_cores": [], "shutdown_clean": False,
           "curl_warnings": [], "bad_lines": [], "steps": []}

    lh = log.open("wb")
    proc = subprocess.Popen(argv, cwd=str(SF), stdout=lh, stderr=subprocess.STDOUT,
                            stdin=subprocess.DEVNULL, env=env,
                            preexec_fn=os.setsid)
    try:
        # wait for ready (rcon responsive)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                res["steps"].append(f"died early rc={proc.returncode}")
                break
            try:
                wait_until_responsive("127.0.0.1", port, RCON_PW,
                                      overall_timeout=3, poll_interval=0.5)
                res["ready"] = True
                break
            except Exception:
                continue
        if res["ready"]:
            res["steps"].append("booted dod_anzio")
            cl = RconClient(host="127.0.0.1", port=port, password=RCON_PW, timeout=3)
            try:
                cl.execute("changelevel dod_flash")
            except RconError:
                pass
            time.sleep(10)
            # confirm alive on new map
            try:
                wait_until_responsive("127.0.0.1", port, RCON_PW,
                                      overall_timeout=15, poll_interval=0.5)
                out = RconClient(host="127.0.0.1", port=port, password=RCON_PW,
                                 timeout=3).execute("mapname")
                res["changelevel_ok"] = True
                res["steps"].append(f"changelevel dod_flash ok (mapname->{out.strip()[:40]})")
            except Exception as e:
                res["steps"].append(f"changelevel check failed: {e}")
            # graceful quit -> exercises shutdown/detach path
            try:
                RconClient(host="127.0.0.1", port=port, password=RCON_PW,
                           timeout=3).execute("quit")
            except RconError:
                pass
            res["steps"].append("sent quit")
        # wait for exit
        try:
            proc.wait(timeout=25)
        except subprocess.TimeoutExpired:
            res["steps"].append("did NOT exit on quit; SIGTERM")
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait(timeout=10)
        res["rc"] = proc.returncode
    finally:
        if proc.poll() is None:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except Exception:
                pass
        lh.close()

    time.sleep(1.5)
    res["new_cores"] = sorted(cores_now() - cores_before)

    text = log.read_text(errors="replace")
    for ln in text.splitlines():
        low = ln.lower()
        if "[curl]" in low and "warning" in low:
            res["curl_warnings"].append(ln.strip())
        if any(k in low for k in ("segfault", "sigsegv", "abort", "double free",
                                  "corruption", "assertion")):
            res["bad_lines"].append(ln.strip())
    res["shutdown_clean"] = ("KTP_ExtensionShutdown" in text) and \
                            ("detaching modules" in text or "Extension shutdown" in text)
    res["log_tail"] = "\n".join(text.splitlines()[-35:])

    print("RESULT_JSON:" + json.dumps(res))


if __name__ == "__main__":
    main()
