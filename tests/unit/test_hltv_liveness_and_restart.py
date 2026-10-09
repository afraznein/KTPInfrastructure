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
import shutil
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
# FAKE_SYSTEMCTL_HANG names a verb that never answers. A D-Bus round-trip to a
# sick PID 1 is exactly the call the alert path makes when PID 1 is sick.
[ "${FAKE_SYSTEMCTL_HANG:-}" = "$1" ] && sleep 30
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
[ -n "${FAKE_SS_HANG:-}" ] && sleep 30
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
    # Emulates the parts of curl's contract the alert path now relies on:
    # --max-time caps the wait and exits 28, an HTTP error under --fail exits 22,
    # and an unbounded call really does sit there (FAKE_CURL_SLEEP is not capped
    # unless a --max-time was passed). The log holds DELIVERED payloads only.
    "curl": r"""#!/bin/bash
maxt=0; data=""; want_fail=0; bad=0
while [ $# -gt 0 ]; do
  case "$1" in
    --max-time) maxt="$2"; shift ;;
    --fail) want_fail=1 ;;
    -d) data="$2"; shift ;;
  esac
  shift
done
nap="${FAKE_CURL_SLEEP:-0}"
if [ "$maxt" -gt 0 ] && [ "$nap" -gt "$maxt" ]; then sleep "$maxt"; exit 28; fi
[ "$nap" -gt 0 ] && sleep "$nap"
[ "${FAKE_CURL_HTTP:-200}" -ge 400 ] && bad=1
case "$data" in
  *"\"channelId\": \"${FAKE_CURL_FAIL_CHANNEL:-__nochannel__}\""*) bad=1 ;;
esac
# Without --fail an HTTP error exits 0 and the caller records an alert nobody
# received. That is the production defect, so the stub reproduces it.
[ "$bad" = 1 ] && [ "$want_fail" = 1 ] && exit 22
[ "$bad" = 1 ] && exit 0
printf '%s\x1e' "$data" >> "$FAKE_CURL_LOG"
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
        HLTV_RESTART_STATE=str(tmp_path / "restart.state"),
        KTP_ALERT_SPOOL_DIR=str(tmp_path / "spool"),
    )
    d["env"] = env
    d["conf"] = conf
    d["state_file"] = d["state"] / "state"
    d["curl_log"] = tmp_path / "curl.log"
    d["restart_state"] = tmp_path / "restart.state"
    d["spool"] = tmp_path / "spool" / "ops-daily.jsonl"
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


# -- liveness: a page that could not be sent --------------------------------
# This path is reached only once something is already wrong, so every wait on it
# has to end and every failure on it has to leave a mark. Exit 4 is withheld from
# the unit's SuccessExitStatus on purpose: a wedged or silenced run reads green on
# the timer leg, the failed-unit leg and OnFailure= all at once, so the exit is
# the only surface left once the script cannot speak for itself.

def one_proxy_stale(box, port="27020"):
    all_fresh(box)
    demo(box, port, 3 * 3600)


def test_a_relay_that_rejects_the_alert_is_not_recorded_as_sent(box):
    """Without --fail, curl exits 0 on a 503: the page was refused, the run
    recorded it as sent, and the next three hours of reminders were muted."""
    one_proxy_stale(box)
    box["env"]["FAKE_CURL_HTTP"] = "503"
    run(box, LIVENESS)
    second = run(box, LIVENESS)
    assert second.returncode == 4, second.stderr
    assert "FAILED (curl exit 22)" in second.stderr
    assert payloads(box) == []
    assert "LAST_ALERT=0" in box["state_file"].read_text(), "the remind window was consumed"


def test_the_bounds_still_add_up_to_less_than_the_unit_backstop():
    """The whole point of the in-script bounds is to fire BEFORE
    `TimeoutStartSec=`, which kills without explaining. That is an arithmetic
    relationship between two files, so it is asserted rather than described:
    loosen any one default past the backstop and the script goes back to being
    killed silently on the one run that had something to say."""
    src = open(LIVENESS, encoding="utf-8").read()
    unit = os.path.join(_ROOT, "scripts", "systemd", "ktp-hltv-liveness.service")
    spec = open(unit, encoding="utf-8").read()

    def default(name):
        m = re.search(rf'^{name}="\$\{{{name}:-(\d+)\}}"', src, re.M)
        assert m, f"{name} lost its env-overridable default"
        return int(m.group(1))

    m = re.search(r"^TimeoutStartSec=(\d+)min$", spec, re.M)
    assert m, "the unit stopped declaring a start timeout in minutes"
    backstop = int(m.group(1)) * 60

    # One ss dump, one unit enumeration, one is-active per down proxy at the
    # fleet's full width, and a POST per channel.
    worst = (default("SS_SECONDS") + default("SYSTEMCTL_SECONDS")
             + default("SYSTEMCTL_SECONDS") * len(PORTS)
             + default("RELAY_MAX_SECONDS") * 2)
    assert worst < backstop, f"worst case {worst}s exceeds the {backstop}s backstop"
    assert worst < backstop / 2, (
        f"worst case {worst}s leaves no room under the {backstop}s backstop for the "
        "deliberately unbounded demo scan")


def test_a_relay_that_never_answers_is_bounded_and_still_reports(box):
    """The unit's start timeout would kill this run without explaining it. The
    script's own bound has to fire first, and say which channel went nowhere."""
    one_proxy_stale(box)
    box["env"].update(FAKE_CURL_SLEEP="30", RELAY_MAX_SECONDS="2")
    run(box, LIVENESS)
    start = time.monotonic()
    second = run(box, LIVENESS)
    elapsed = time.monotonic() - start
    assert elapsed < 20, f"the relay POST was not bounded: {elapsed:.0f}s"
    assert second.returncode == 4, second.stderr
    assert "FAILED (curl exit 28)" in second.stderr
    assert payloads(box) == []


def test_an_undelivered_page_exits_outside_the_units_success_exit_status(box):
    """The exit code IS the escalation, so the two facts are asserted together --
    a forgiven exit would leave the detected fault with no surface anywhere."""
    unit = os.path.join(_ROOT, "scripts", "systemd", "ktp-hltv-liveness.service")
    with open(unit, encoding="utf-8") as fh:
        forgiven = [ln.split("=", 1)[1].split() for ln in fh.read().splitlines()
                    if ln.startswith("SuccessExitStatus=")]
    assert forgiven, "the unit stopped declaring SuccessExitStatus"
    assert "1" in forgiven[0] and "2" in forgiven[0], "the self-reported exits must stay forgiven"
    assert "4" not in forgiven[0], "forgiving 4 puts the undelivered page back in the dark"
    one_proxy_stale(box)
    box["env"]["FAKE_CURL_HTTP"] = "500"
    run(box, LIVENESS)
    assert run(box, LIVENESS).returncode == 4


def test_an_undelivered_all_clear_keeps_the_state_so_it_retries(box):
    """The all-clear is the one message that ends a page. Clearing state on a lost
    one leaves the page open with nothing left able to close it."""
    for p in PORTS:
        demo(box, p, 0 if p != "27040" else 3 * 3600)
    liveness_twice(box)
    demo(box, "27040", 0)
    box["env"]["FAKE_CURL_HTTP"] = "503"
    lost = run(box, LIVENESS)
    assert lost.returncode == 4, lost.stderr
    assert "all-clear was NOT delivered" in lost.stderr
    box["env"]["FAKE_CURL_HTTP"] = "200"
    retried = run(box, LIVENESS)
    assert retried.returncode == 0, retried.stderr
    assert payloads(box)[-1]["embeds"][0]["title"] == "✅ HLTV proxies recovered"


def test_a_slow_but_answering_relay_is_still_delivered(box):
    """The other direction, and the one a bound gets wrong: a POST that is slow but
    inside the budget must still land and still stamp the remind window. Sized too
    tight, every one of the bounds above turns a busy relay into a false `exit 4`,
    which is the failure the start-timeout work warned about."""
    one_proxy_stale(box)
    box["env"].update(FAKE_CURL_SLEEP="2", RELAY_MAX_SECONDS="15")
    run(box, LIVENESS)
    second = run(box, LIVENESS)
    assert second.returncode == 1, second.stderr
    assert "FAILED" not in second.stderr, "a bound fired on a relay that answered"
    (alert,) = payloads(box)
    assert alert["embeds"][0]["title"] == "🔴 HLTV proxy NOT RECORDING"
    assert "LAST_ALERT=0" not in box["state_file"].read_text(), "a delivered page left the window open"


def test_the_bounds_do_not_fire_on_tools_that_answer_normally(box):
    """The no-op control for the three `timeout` wrappers. With nothing hanging,
    a healthy fleet must still read healthy -- a bound that fires here would page
    on every cadence, and `timeout` exits 124 only when it actually killed."""
    all_fresh(box)
    box["env"].update(SYSTEMCTL_SECONDS="1", SS_SECONDS="1")
    r = liveness_twice(box)
    assert r.returncode == 0, r.stderr
    assert payloads(box) == []
    assert "did not answer" not in r.stderr


def test_a_set_but_empty_channel_is_not_a_silent_success(box):
    """It sent nothing and returned success, so a mis-edited conf silenced the
    monitor without a trace."""
    box["conf"].write_text("RELAY_URL=http://relay.invalid\nAUTH_SECRET=x\n"
                           "CHANNEL_HLTV_STATUS=\nCHANNEL_HLTV_STATUS_EXTERNAL=\n", newline="\n")
    one_proxy_stale(box)
    run(box, LIVENESS)
    second = run(box, LIVENESS)
    assert second.returncode == 4, second.stderr
    assert "no HLTV status channel set" in second.stderr
    assert payloads(box) == []


def test_an_absent_channel_name_is_reported_not_a_camouflaged_death(box):
    """Worse than the empty one, and the reason every conf key is read with `:-`:
    `set -u` kills the run mid-send on a name the conf never defines, and bash
    exits 1 doing it -- which is this script's OWN code for "detected it and said
    so", and is forgiven by the unit. The death reads as a report. Measured on the
    pre-fix script: exit 1, curl never called, and the state file still holding
    the previous run's FAILS, because the write is past the point it died."""
    box["conf"].write_text("RELAY_URL=http://relay.invalid\nAUTH_SECRET=x\n", newline="\n")
    one_proxy_stale(box)
    run(box, LIVENESS)
    second = run(box, LIVENESS)
    assert "unbound variable" not in second.stderr, "the run died instead of reporting"
    assert second.returncode == 4, second.stderr
    assert "no HLTV status channel set" in second.stderr
    assert payloads(box) == []
    # The frozen counter is the lasting half: dying before this write pinned FAILS
    # at 1 forever, so the threshold could never be reached again and the monitor
    # was silenced permanently rather than for one cadence.
    assert box["state_file"].exists(), "the run exited before writing its state"
    assert "FAILS=2" in box["state_file"].read_text(), "the failure counter stopped advancing"


def test_an_external_channel_failing_alone_does_not_re_page_the_primary(box):
    """Gating the caller on the LAST channel would let a broken external re-page
    the primary every cadence. It is logged instead."""
    box["conf"].write_text("RELAY_URL=http://relay.invalid\nAUTH_SECRET=x\n"
                           "CHANNEL_HLTV_STATUS=1\nCHANNEL_HLTV_STATUS_EXTERNAL=2\n", newline="\n")
    one_proxy_stale(box)
    box["env"]["FAKE_CURL_FAIL_CHANNEL"] = "2"
    run(box, LIVENESS)
    second = run(box, LIVENESS)
    assert second.returncode == 1, second.stderr
    assert "channel 2 FAILED" in second.stderr
    assert "channel 1 FAILED" not in second.stderr
    assert "LAST_ALERT=0" not in box["state_file"].read_text()
    assert [p["channelId"] for p in payloads(box)] == ["1"]


def test_a_systemctl_that_never_answers_does_not_hang_the_down_alert(box):
    """systemd's opinion is in the embed because it is the thing that lied for
    9h48m -- and asking for it is a round-trip made exactly when it is unwell."""
    all_fresh(box)
    box["env"]["FAKE_BOUND"] = " ".join(p for p in PORTS if p != "27035")
    box["env"].update(FAKE_SYSTEMCTL_HANG="is-active", SYSTEMCTL_SECONDS="1")
    start = time.monotonic()
    second = liveness_twice(box)
    assert time.monotonic() - start < 25, "the is-active call was not bounded"
    assert second.returncode == 1, second.stderr
    (alert,) = payloads(box)
    desc = alert["embeds"][0]["description"]
    assert "port 27035 — unit: unknown (systemctl did not answer)" in desc
    assert "**1 of 24** proxies are not bound" in desc, "the finding itself changed"


def test_an_unanswered_enumeration_is_told_apart_from_a_genuine_zero(box):
    """Both fail closed, and they must not read the same: one is a broken probe,
    the other is a fleet with no units left."""
    box["env"].update(FAKE_SYSTEMCTL_HANG="list-units", SYSTEMCTL_SECONDS="1")
    start = time.monotonic()
    hung = run(box, LIVENESS)
    assert time.monotonic() - start < 20, "the enumeration was not bounded"
    assert hung.returncode == 2, hung.stderr
    assert "did not answer within 1s" in hung.stderr

    box["env"].pop("FAKE_SYSTEMCTL_HANG")
    box["env"]["FAKE_UNITS"] = ""
    zero = run(box, LIVENESS)
    assert zero.returncode == 2, zero.stderr
    assert "enumerated 0 hltv@ units" in zero.stderr
    assert "did not answer" not in zero.stderr


def test_an_ss_that_never_answers_pages_rather_than_hanging(box):
    """No bound set reads as a total outage, which is already what the script says
    it should do with one -- both warrant an alert, neither is healthy."""
    all_fresh(box)
    box["env"].update(FAKE_SS_HANG="1", SS_SECONDS="1")
    start = time.monotonic()
    second = liveness_twice(box)
    assert time.monotonic() - start < 25, "the ss dump was not bounded"
    assert second.returncode == 1, second.stderr
    (alert,) = payloads(box)
    assert alert["embeds"][0]["title"] == "🔴 HLTV proxy DOWN"
    assert f"**{len(PORTS)} of {len(PORTS)}** proxies are not bound" in alert["embeds"][0]["description"]


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


def test_all_connected_posts_nothing_and_soak_verify_stays_quiet(box):
    """Silence means healthy. A clean restart of scheduled work is a
    confirmation, not an alert — it used to cost two posts twice a day."""
    restart_journal(box)
    r = run(box, RESTART)
    assert f"{len(PORTS)} succeeded, 0 failed" in r.stdout
    assert "scheduled restart complete" in r.stdout
    assert soak_verify_error_lines(r.stdout) == []
    assert payloads(box) == []
    assert box["restart_state"].read_text().strip() == "info"


def test_a_clean_restart_leaves_a_digest_line_instead_of_a_post(box):
    if shutil.which("jq") is None:
        pytest.skip("the spool line is written with jq")
    restart_journal(box)
    run(box, RESTART)
    (line,) = [json.loads(l) for l in box["spool"].read_text().splitlines() if l.strip()]
    assert line["producer"] == "hltv-restart-all"
    assert line["severity"] == "info"
    assert f"{len(PORTS)}/{len(PORTS)}" in line["text"]


def test_the_first_green_after_a_failure_is_the_all_clear(box):
    """The one green that must be heard. Without it, a page has no end."""
    box["restart_state"].write_text("page\n", newline="\n")
    restart_journal(box)
    run(box, RESTART)
    (embed,) = [p["embeds"][0] for p in payloads(box)]
    assert embed["title"].startswith("🟢")
    assert embed["title"].endswith("HLTV Restart Complete")
    assert embed["color"] == 5763719


def test_the_second_green_after_a_failure_is_silent_again(box):
    box["restart_state"].write_text("page\n", newline="\n")
    restart_journal(box)
    run(box, RESTART)
    before = len(payloads(box))
    run(box, RESTART)
    assert len(payloads(box)) == before, "the all-clear repeated itself"


def test_a_proxy_that_never_connects_is_a_failure_by_port(box):
    restart_journal(box, not_connected={"27020"})
    r = run(box, RESTART)
    assert f"{len(PORTS) - 1} succeeded, 1 failed" in r.stdout
    assert "hltv@27020 is active but failed to connect" in r.stdout
    assert soak_verify_error_lines(r.stdout), "soak-verify would not flag the failure"
    (embed,) = [p["embeds"][0] for p in payloads(box)]
    assert embed["title"].startswith("🟠")
    assert embed["title"].endswith("HLTV Restart - Partial")
    assert embed["color"] == 16763904
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
