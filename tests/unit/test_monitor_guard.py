"""ktp-monitor-guard.sh: never restart into a host-level network outage, never block a real one.

LinuxGSM's per-minute monitor restarted all five Dallas instances when the host
lost carrier: the static address went with the link, gsquery failed five times,
and every restarted process died binding an address the host no longer had.
The link came back four minutes later and the next tick restarted all five
again. The guard skips the monitor for the tick when the host's own network is
down, and otherwise execs it unchanged.

Every case drives the shipped script against a sandbox: a fake instance tree
with real LinuxGSM-shaped configs, a stub `ip` on PATH, a fake sysfs, and a stub
control script that records whether the monitor ran. Nothing on a host is
touched.

The installer half extracts `monitor_cron_line` from the shipped installer and
checks the lines it emits against the patterns the nightly restart and the
fleet-health count actually use, read from those scripts rather than restated.
"""
from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
GUARD = ROOT / "monitoring" / "monitor-guard" / "ktp-monitor-guard.sh"
INSTALLER = ROOT / "provision" / "install-linuxgsm.sh"
RESTART = ROOT / "scripts" / "ktp-scheduled-restart.sh.example"
FLEET_HEALTH = ROOT / "monitoring" / "fleet-health" / "ktp-fleet-health.sh"

# On Windows `bash` from subprocess resolves to WSL's launcher, which cannot see C:/ paths
# or the stubs on PATH; CI runs these on Linux.
pytestmark = pytest.mark.skipif(
    shutil.which("bash") is None or os.name == "nt", reason="needs a POSIX bash"
)

BIND_IP = "192.0.2.10"
ADDR_LINE = f"2: enp1s0f0    inet {BIND_IP}/24 brd 192.0.2.255 scope global enp1s0f0\\       valid_lft forever preferred_lft forever\n"
ROUTE_LINE = "default via 192.0.2.254 dev enp1s0f0 proto static\n"

IP_STUB = r"""#!/bin/bash
[ -e "$FAKE_NET/ip_fail" ] && exit 1
case "$*" in
    "-4 route show default") cat "$FAKE_NET/route" 2>/dev/null ;;
    "-o -4 addr show to "*) grep -F " inet $6/" "$FAKE_NET/addr" 2>/dev/null ;;
    *) echo "unexpected ip $*" >&2; exit 2 ;;
esac
exit 0
"""

CTL_STUB = """#!/bin/bash
echo "$0 $*" >> "$RAN_LOG"
exit "${CTL_EXIT:-0}"
"""


def _write(p: pathlib.Path, text: str, mode: int | None = None) -> pathlib.Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")
    if mode is not None:
        p.chmod(mode)
    return p


class Host:
    """One sandboxed game host with a single instance (dodserver2 by default)."""

    def __init__(self, tmp: pathlib.Path, self_name: str = "dodserver2", dirname: str = "dod-27016"):
        self.tmp = tmp
        self.bin = tmp / "bin"
        self.net = tmp / "net"
        self.sys = tmp / "sys"
        self.state = tmp / "state"
        self.log = tmp / "log" / "monitor-guard.log"
        self.ran = tmp / "ran.log"
        self.ctl = tmp / dirname / self_name
        self.cfgdir = tmp / dirname / "lgsm" / "config-lgsm" / "dodserver"
        _write(self.bin / "ip", IP_STUB, 0o755)
        _write(self.bin / "logger", "#!/bin/bash\nexit 0\n", 0o755)
        _write(self.ctl, CTL_STUB, 0o755)
        _write(self.cfgdir / "_default.cfg", 'ip="0.0.0.0"\nport="27015"\n')
        _write(self.cfgdir / "common.cfg", "")
        _write(self.cfgdir / f"{self_name}.cfg", f'port="27016"\nclientport="27006"\nip="{BIND_IP}"\n')
        self.net.mkdir()
        self.healthy()

    def healthy(self):
        self.set_addr(ADDR_LINE)
        self.set_route(ROUTE_LINE)
        self.set_link("enp1s0f0", carrier="1", operstate="up")

    def link_lost(self):
        """What networkd does on carrier loss without KeepConfiguration: address and route go."""
        self.set_addr("")
        self.set_route("")
        self.set_link("enp1s0f0", carrier="0", operstate="down")

    def set_addr(self, text):
        _write(self.net / "addr", text)

    def set_route(self, text):
        _write(self.net / "route", text)

    def set_link(self, dev, carrier=None, operstate=None):
        d = self.sys / dev
        d.mkdir(parents=True, exist_ok=True)
        for name, val in (("carrier", carrier), ("operstate", operstate)):
            f = d / name
            if val is None:
                f.unlink(missing_ok=True)
            else:
                _write(f, val + "\n")

    def tick(self, *args: str, ctl: pathlib.Path | None = None, extra_env=None):
        env = dict(os.environ)
        env.update(
            PATH=f"{self.bin.as_posix()}{os.pathsep}{env.get('PATH', '')}",
            FAKE_NET=self.net.as_posix(),
            RAN_LOG=self.ran.as_posix(),
            KTP_MONITOR_GUARD_SYS_NET=self.sys.as_posix(),
            KTP_MONITOR_GUARD_STATE_DIR=self.state.as_posix(),
            KTP_MONITOR_GUARD_LOG=self.log.as_posix(),
        )
        if extra_env:
            env.update(extra_env)
        target = (ctl or self.ctl).as_posix()
        argv = ["bash", GUARD.as_posix(), target, *(args or ("monitor",))]
        return subprocess.run(argv, capture_output=True, text=True, env=env, timeout=60)

    def runs(self) -> list[str]:
        return self.ran.read_text(encoding="utf-8").splitlines() if self.ran.exists() else []

    def log_lines(self) -> list[str]:
        return self.log.read_text(encoding="utf-8").splitlines() if self.log.exists() else []


@pytest.fixture
def host(tmp_path):
    return Host(tmp_path)


# --- the incident ------------------------------------------------------------


def test_healthy_host_runs_the_monitor_unchanged(host):
    r = host.tick()
    assert r.returncode == 0, r.stderr
    assert host.runs() == [f"{host.ctl.as_posix()} monitor"]
    assert host.log_lines() == []


def test_a_hung_server_on_a_healthy_host_still_gets_the_monitor_and_its_exit_code(host):
    r = host.tick(extra_env={"CTL_EXIT": "3"})
    assert r.returncode == 3
    assert len(host.runs()) == 1


def test_link_loss_holds_the_monitor_instead_of_restarting_into_it(host):
    host.link_lost()
    r = host.tick()
    assert r.returncode == 0, r.stderr
    assert host.runs() == [], "the monitor ran while the bind address was gone"
    (line,) = host.log_lines()
    assert "HOLD monitor" in line and BIND_IP in line and "not configured" in line


def test_a_hold_logs_once_not_every_minute(host):
    host.link_lost()
    for _ in range(4):
        host.tick()
    assert host.runs() == []
    assert len(host.log_lines()) == 1


def test_recovery_resumes_the_monitor_and_logs_once(host):
    host.link_lost()
    host.tick()
    host.tick()
    host.healthy()
    host.tick()
    host.tick()
    assert len(host.runs()) == 2
    lines = host.log_lines()
    assert len(lines) == 2
    assert "HOLD" in lines[0] and "RESUME" in lines[1]
    assert list(host.state.iterdir()) == []


# --- each condition on its own ----------------------------------------------


def test_no_carrier_holds_even_when_the_address_is_kept(host):
    """KeepConfiguration/ignore-carrier keeps the address; the dead link is still dead."""
    host.set_link("enp1s0f0", carrier="0", operstate="down")
    host.tick()
    assert host.runs() == []
    assert "enp1s0f0 has no carrier" in host.log_lines()[0]


def test_admin_down_link_with_unreadable_carrier_holds(host):
    host.set_link("enp1s0f0", carrier=None, operstate="down")
    host.tick()
    assert host.runs() == []
    assert "enp1s0f0 is down" in host.log_lines()[0]


def test_no_default_route_holds(host):
    host.set_route("")
    host.tick()
    assert host.runs() == []
    assert "no IPv4 default route" in host.log_lines()[0]


def test_the_address_interface_is_checked_not_only_the_default_route_interface(host):
    host.set_addr(ADDR_LINE.replace("enp1s0f0", "enp1s0f1"))
    host.set_link("enp1s0f1", carrier="0", operstate="down")
    host.tick()
    assert host.runs() == []
    assert "enp1s0f1 has no carrier" in host.log_lines()[0]


def test_wildcard_bind_falls_back_to_the_default_route_interface(host):
    (host.cfgdir / "dodserver2.cfg").write_text('port="27016"\n', encoding="utf-8")
    host.set_addr("")  # would hold if the guard wrongly looked up 0.0.0.0
    host.tick()
    assert len(host.runs()) == 1
    host.set_link("enp1s0f0", carrier="0", operstate="down")
    host.tick()
    assert len(host.runs()) == 1
    assert "enp1s0f0 has no carrier" in host.log_lines()[0]


# --- fails open --------------------------------------------------------------


def test_a_failing_ip_command_runs_the_monitor(host):
    host.link_lost()
    (host.net / "ip_fail").write_text("", encoding="utf-8")
    host.tick()
    assert len(host.runs()) == 1
    assert host.log_lines() == []


def test_a_host_without_ip_runs_the_monitor(host):
    """PATH holds only the tools the guard needs, minus `ip`, so /usr/sbin/ip cannot leak in."""
    isolated = host.tmp / "isolated-bin"
    isolated.mkdir()
    for tool in ("bash", "awk", "grep", "tr", "date", "cat", "basename", "dirname", "mkdir", "rm", "tail"):
        found = shutil.which(tool)
        assert found, tool
        (isolated / tool).symlink_to(found)
    host.link_lost()
    r = host.tick(extra_env={"PATH": isolated.as_posix()})
    assert r.returncode == 0, r.stderr
    assert len(host.runs()) == 1


def test_unreadable_link_state_runs_the_monitor(host):
    host.set_link("enp1s0f0", carrier=None, operstate=None)
    host.tick()
    assert len(host.runs()) == 1


def test_unparseable_bind_address_is_not_treated_as_missing(host):
    (host.cfgdir / "dodserver2.cfg").write_text('ip="${publicip}"\n', encoding="utf-8")
    host.set_addr("")
    host.tick()
    assert len(host.runs()) == 1


# --- config reading ------------------------------------------------------------


def test_instance_config_overrides_default_and_secrets_override_instance(host):
    _write(host.cfgdir / "secrets-dodserver2.cfg", "ip='198.51.100.7'  # moved\n")
    host.tick()
    assert host.runs() == []
    assert "198.51.100.7" in host.log_lines()[0]


def test_another_instances_config_is_not_read(host):
    _write(host.cfgdir / "dodserver3.cfg", 'ip="198.51.100.9"\n')
    host.tick()
    assert len(host.runs()) == 1


def test_two_instances_with_the_same_control_name_hold_separately(host):
    """Warmup's control script is also `dodserver`; one hold must not hide the other."""
    other = host.tmp / "warmup" / "dodserver2"
    _write(other, CTL_STUB, 0o755)
    shutil.copytree(host.cfgdir, host.tmp / "warmup" / "lgsm" / "config-lgsm" / "dodserver")
    host.link_lost()
    host.tick()
    host.tick(ctl=other)
    assert len(host.log_lines()) == 2
    assert len(list(host.state.iterdir())) == 2


def test_extra_arguments_pass_through(host):
    host.tick("monitor", "--extra")
    assert host.runs() == [f"{host.ctl.as_posix()} monitor --extra"]


# --- the crontab contract ----------------------------------------------------


def _between(text: str, begin: str, end: str) -> str:
    assert begin in text and end in text, f"markers {begin!r} gone from the shipped script"
    return text.split(begin, 1)[1].split("\n", 1)[1].split(end, 1)[0]


def _cron_lines(guard: str) -> list[str]:
    fn = _between(INSTALLER.read_text(encoding="utf-8"), "# >>> ktp-monitor-cron-line", "# <<< ktp-monitor-cron-line")
    body = (
        "set -euo pipefail\n"
        f"MONITOR_GUARD='{guard}'\n"
        + fn
        + '\nmonitor_cron_line "~/dod-27015/dodserver"\n'
        + 'monitor_cron_line "~/dod-27016/dodserver2"\n'
        + 'monitor_cron_line "./dodserver" "cd /srv/ktpdata/warmup && "\n'
    )
    r = subprocess.run(["bash", "-s"], input=body, capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return r.stdout.splitlines()


@pytest.mark.parametrize("guard", ["~/ktp-monitor-guard.sh", ""])
def test_installer_lines_stay_visible_to_the_nightly_restart_and_fleet_health(guard):
    restart_match = re.search(r"^MONITOR_CRON_MATCH='([^']+)'", RESTART.read_text(encoding="utf-8"), re.M).group(1)
    fh_match = re.search(r"grep -c '(\^\[\^#\]\*monitor)'", FLEET_HEALTH.read_text(encoding="utf-8")).group(1)
    lines = _cron_lines(guard)
    assert len(lines) == 3
    for line in lines:
        assert re.search(restart_match, line), f"nightly restart would not pause: {line}"
        assert re.search(fh_match, line), f"fleet-health would not count: {line}"
        assert line.endswith(" monitor > /dev/null 2>&1")
        assert line.startswith("* * * * * ")
        assert ("ktp-monitor-guard.sh" in line) == bool(guard)


def test_installed_guard_line_runs_the_guard_on_the_instance():
    line = _cron_lines("~/ktp-monitor-guard.sh")[1]
    assert line == "* * * * * ~/ktp-monitor-guard.sh ~/dod-27016/dodserver2 monitor > /dev/null 2>&1"


def test_guard_parses():
    r = subprocess.run(["bash", "-n", GUARD.as_posix()], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
