"""HLTV liveness and scheduled-restart checks, run against stubbed system tools.

A proxy can be up, bound and never connected to its game server: it answers
"Not connected." until the next restart and writes no demo. The port check read
that as healthy and the restart summary counted it a success. These tests run
both scripts with systemctl, ss, journalctl and curl replaced by stubs, and every
verdict is exercised in both directions -- a check that cannot fail proves
nothing, and neither does one that cannot pass.
"""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import time

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LIVENESS = os.path.join(_ROOT, "scripts", "ktp-hltv-liveness.sh")
RESTART = os.path.join(_ROOT, "scripts", "hltv-restart-all.sh")
PORTS = [str(p) for p in range(27020, 27044)]
NAMES = dict(zip(PORTS, [f"auto_{r}{i}" for r in ("atl", "dal", "den", "ny") for i in range(1, 6)]
                  + [f"auto_chi{i}" for i in range(1, 5)]))
RS = "\x1e"

STUBS = {
    "systemctl": r"""#!/bin/bash
case "$1" in
  list-units) for p in $FAKE_UNITS; do echo "hltv@$p.service loaded active running KTP HLTV Instance $p"; done ;;
  is-active)  u="${@: -1}"; u="${u#hltv@}"; u="${u%.service}"
              q=0; for a in "$@"; do [ "$a" = "--quiet" ] && q=1; done
              case " $FAKE_INACTIVE " in *" $u "*) [ $q = 1 ] || echo failed; exit 3 ;; esac
              [ $q = 1 ] || echo active ;;
esac
exit 0
""",
    "ss": r"""#!/bin/bash
for p in $FAKE_BOUND; do echo "UNCONN 0 0 0.0.0.0:$p 0.0.0.0:*"; done
""",
    # A port with a `.later` file answers from it once it has been asked before,
    # which is how a proxy that connects on a later poll is modelled.
    "journalctl": r"""#!/bin/bash
while [ $# -gt 0 ]; do [ "$1" = "-u" ] && { u="$2"; shift; }; shift; done
p="${u#hltv@}"; d="$FAKE_JOURNAL_DIR"
if [ -f "$d/$p.later" ] && [ -f "$d/$p.asked" ]; then cat "$d/$p.later"; exit 0; fi
touch "$d/$p.asked"
[ -f "$d/$p" ] && cat "$d/$p"
exit 0
""",
    "curl": r"""#!/bin/bash
while [ $# -gt 0 ]; do [ "$1" = "-d" ] && { printf '%s\x1e' "$2" >> "$FAKE_CURL_LOG"; shift; }; shift; done
exit 0
""",
}

CONNECTED = "Started hltv@{p}.service - KTP HLTV Instance {p}.\nChallenging 192.0.2.1:27015 (1/3).\nReceived baseline with 207 entities.\n"
NOT_CONNECTED = "Started hltv@{p}.service - KTP HLTV Instance {p}.\nExecuting file hltv.cfg.\nNot connected.\n"


@pytest.fixture
def box(tmp_path):
    d = {k: tmp_path / k for k in ("bin", "state", "configs", "demos", "journal")}
    for p in d.values():
        p.mkdir()
    for name, body in STUBS.items():
        f = d["bin"] / name
        f.write_text(body, newline="\n")
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
    conf = tmp_path / "relay.conf"
    conf.write_text("RELAY_URL=http://relay.invalid\nAUTH_SECRET=x\nCHANNEL_HLTV_STATUS=1\n"
                    "CHANNEL_HLTV_STATUS_EXTERNAL=\n", newline="\n")
    for p in PORTS:
        (d["configs"] / f"hltv-{p}.cfg").write_text(f"connect 192.0.2.1:27015\nrecord {NAMES[p]}\n", newline="\n")
    env = dict(os.environ)
    env.update(
        PATH=f"{d['bin']}{os.pathsep}{os.environ['PATH']}",
        FAKE_UNITS=" ".join(PORTS), FAKE_BOUND=" ".join(PORTS), FAKE_INACTIVE="",
        FAKE_JOURNAL_DIR=str(d["journal"]), FAKE_CURL_LOG=str(tmp_path / "curl.log"),
        KTP_RELAY_CONF=str(conf), KTP_HLTV_LIVENESS_STATE_DIR=str(d["state"]),
        HLTV_CONFIG_DIR=str(d["configs"]), HLTV_DEMO_DIR=str(d["demos"]),
        SETTLE_SECONDS="0", POLL_SECONDS="0", CONNECT_WAIT_SECONDS="0",
    )
    d["env"] = env
    d["curl_log"] = tmp_path / "curl.log"
    return d


def demo(box, port, age):
    f = box["demos"] / f"{NAMES[port]}-2609110000-dod_anzio.dem"
    f.write_bytes(b"x")
    t = time.time() - age
    os.utime(f, (t, t))


def all_fresh(box):
    for p in PORTS:
        demo(box, p, 0)


def run(box, script):
    return subprocess.run(["bash", script], env=box["env"], capture_output=True, text=True, timeout=60)


def payloads(box):
    if not box["curl_log"].exists():
        return []
    return [json.loads(p) for p in box["curl_log"].read_text().split(RS) if p.strip()]


def liveness_twice(box):
    run(box, LIVENESS)
    return run(box, LIVENESS)


# -- liveness: the recording check ------------------------------------------

def test_every_proxy_bound_and_recording_is_healthy(box):
    all_fresh(box)
    r = liveness_twice(box)
    assert r.returncode == 0, r.stderr
    assert payloads(box) == []


def test_a_bound_proxy_that_stopped_recording_is_reported_by_name(box):
    all_fresh(box)
    demo(box, "27020", 3 * 3600)
    first = run(box, LIVENESS)
    assert first.returncode == 1
    assert payloads(box) == [], "one sample must not page; the restarts would trip it twice a day"
    second = run(box, LIVENESS)
    assert second.returncode == 1
    (alert,) = payloads(box)
    embed = alert["embeds"][0]
    assert embed["title"] == "🔴 HLTV proxy NOT RECORDING"
    assert "port 27020: auto_atl1 last written 3h00m ago" in embed["description"]
    assert "27021" not in embed["description"], "a fresh proxy was listed"


def test_the_threshold_is_the_boundary(box):
    all_fresh(box)
    box["env"]["STALE_SECONDS"] = "600"
    demo(box, "27030", 300)
    assert liveness_twice(box).returncode == 0
    demo(box, "27030", 900)
    assert liveness_twice(box).returncode == 1


def test_an_empty_demo_dir_fails_closed_on_every_proxy(box):
    r = liveness_twice(box)
    assert r.returncode == 1
    (alert,) = payloads(box)
    desc = alert["embeds"][0]["description"]
    assert f"**{len(PORTS)} of {len(PORTS)}** proxies are bound but not recording" in desc


def test_a_config_without_a_record_line_is_reported_not_skipped(box):
    all_fresh(box)
    (box["configs"] / "hltv-27043.cfg").write_text("connect 192.0.2.1:27015\n", newline="\n")
    liveness_twice(box)
    (alert,) = payloads(box)
    assert "port 27043: no record line in hltv-27043.cfg" in alert["embeds"][0]["description"]


def test_the_demo_name_comes_from_the_config_not_a_port_table(box):
    all_fresh(box)
    (box["configs"] / "hltv-27025.cfg").write_text("record auto_renamed\n", newline="\n")
    liveness_twice(box)
    (alert,) = payloads(box)
    assert "port 27025: no auto_renamed-*.dem" in alert["embeds"][0]["description"]


def test_an_unbound_proxy_is_down_and_not_listed_twice(box):
    all_fresh(box)
    box["env"]["FAKE_BOUND"] = " ".join(p for p in PORTS if p != "27035")
    demo(box, "27035", 3 * 3600)
    liveness_twice(box)
    (alert,) = payloads(box)
    embed = alert["embeds"][0]
    assert embed["title"] == "🔴 HLTV proxy DOWN"
    assert "port 27035 — unit: active" in embed["description"]
    assert "not recording" not in embed["description"]


def test_recovery_is_announced_once(box):
    demo(box, "27040", 3 * 3600)
    for p in PORTS[:-4] + PORTS[-3:]:
        demo(box, p, 0)
    liveness_twice(box)
    demo(box, "27040", 0)
    assert run(box, LIVENESS).returncode == 0
    assert run(box, LIVENESS).returncode == 0
    titles = [p["embeds"][0]["title"] for p in payloads(box)]
    assert titles == ["🔴 HLTV proxy NOT RECORDING", "✅ HLTV proxies recovered"]


def test_no_units_is_a_broken_probe_not_a_healthy_fleet(box):
    box["env"]["FAKE_UNITS"] = ""
    assert run(box, LIVENESS).returncode == 2


# -- restart: active is not connected -----------------------------------------

def restart_journal(box, not_connected=(), old_connect_then_silent=()):
    for p in PORTS:
        body = NOT_CONNECTED if p in not_connected else CONNECTED
        if p in old_connect_then_silent:
            body = "Connected to Game Server 192.0.2.1:27015, Delay 60\n" + NOT_CONNECTED
        (box["journal"] / p).write_text(body.format(p=p), newline="\n")


def soak_verify_error_lines(stdout):
    """The filter `ktp-soak-verify.py` applies to the hltv-restart journal."""
    return [ln for ln in stdout.splitlines()
            if not re.search(r"succeeded, 0 failed$", ln) and re.search(r"error|failed|fatal", ln, re.I)]


def test_all_connected_is_green_and_soak_verify_stays_quiet(box):
    restart_journal(box)
    r = run(box, RESTART)
    assert f"{len(PORTS)} succeeded, 0 failed" in r.stdout
    assert "scheduled restart complete" in r.stdout
    assert soak_verify_error_lines(r.stdout) == []
    (embed,) = [p["embeds"][0] for p in payloads(box)]
    assert embed["title"].endswith("HLTV Restart Complete")
    assert embed["color"] == 65280


def test_a_proxy_that_never_connects_is_a_failure_by_port(box):
    restart_journal(box, not_connected={"27020"})
    r = run(box, RESTART)
    assert f"{len(PORTS) - 1} succeeded, 1 failed" in r.stdout
    assert "hltv@27020 is active but failed to connect" in r.stdout
    assert soak_verify_error_lines(r.stdout), "soak-verify would not flag the failure"
    (embed,) = [p["embeds"][0] for p in payloads(box)]
    assert embed["title"].endswith("HLTV Restart - Partial")
    assert "**Up but not connected, recording nothing:** 27020" in embed["description"]


def test_a_connect_line_from_before_the_restart_does_not_count(box):
    restart_journal(box, old_connect_then_silent={"27031"})
    r = run(box, RESTART)
    assert "hltv@27031 is active but failed to connect" in r.stdout


def test_a_proxy_that_connects_on_a_later_poll_is_counted(box):
    restart_journal(box, not_connected={"27022"})
    (box["journal"] / "27022.later").write_text(CONNECTED.format(p="27022"), newline="\n")
    box["env"]["CONNECT_WAIT_SECONDS"] = "30"
    r = run(box, RESTART)
    assert f"{len(PORTS)} succeeded, 0 failed" in r.stdout


def test_an_inactive_proxy_is_still_a_failure_and_is_not_polled(box):
    restart_journal(box)
    box["env"]["FAKE_INACTIVE"] = "27043"
    r = run(box, RESTART)
    assert "hltv@27043 restarted but is not active" in r.stdout
    assert f"{len(PORTS) - 1} succeeded, 1 failed" in r.stdout
    assert not (box["journal"] / "27043.asked").exists()
