"""Guards for the host-to-host drift sections of `scripts/audit-fleet-drift.py`.

The two host-to-host sections ("Baremetal-only drift", "Fleet-wide drift") had
never been read end to end until 2026-08-24. When they were, 34 of 34 baremetal
items and 87 of 87 fleet-wide items turned out to be either per-host-by-
construction facts (root=UUID, BOOT_IMAGE), the same tuning line written against
a different NIC name, or the same line with different indentation and quoting.
Exactly one item in the 34 was real -- and it was a bare 0x01 byte, which the
markdown renderer emitted as an empty table cell. The single real finding was
the one the report could not show.

So these tests pull in two directions at once, and both directions matter:

  * the suppression rules must actually suppress the noise classes, and
  * they must NOT swallow a real divergence. Every suppression test below has a
    partner asserting that something genuinely different still reports.

A filter that quietly over-matches turns this audit into a green light that
means nothing, which is worse than the noise it replaced.

Loaded by path, with `paramiko` stubbed: the audit script imports paramiko and
reads a fleet config at import time, and neither is needed to exercise the pure
comparison functions. Keeping the stub here means the Tier 1 gate does not grow
an SSH dependency.
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import types
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "audit-fleet-drift.py"

RC_LOCAL = "/etc/rc.local (non-comment, sorted)"
GRUB = "GRUB CMDLINE"
CRONTAB = "DODSERVER CRONTAB (non-comment, sorted)"


def _load_module(tmp_path):
    """Import the audit script without paramiko and without /etc/ktp."""
    cfg = tmp_path / "fleet.json"
    cfg.write_text(json.dumps({"hosts": [
        {"name": "Atlanta", "host": "10.0.0.1", "user": "u", "password": "p",
         "group": "baremetal"},
        {"name": "Dallas", "host": "10.0.0.2", "user": "u", "password": "p",
         "group": "baremetal"},
        {"name": "Chicago", "host": "10.0.0.3", "user": "u", "password": "p",
         "group": "vps"},
    ]}))

    sys.modules.setdefault("paramiko", types.ModuleType("paramiko"))
    saved_stdout = sys.stdout
    prev = os.environ.get("KTP_AUDIT_FLEET_CONFIG")
    os.environ["KTP_AUDIT_FLEET_CONFIG"] = str(cfg)
    try:
        spec = importlib.util.spec_from_file_location("_ktp_audit_drift", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        # The script rebinds sys.stdout at import; do not leak that into pytest.
        sys.stdout = saved_stdout
        if prev is None:
            os.environ.pop("KTP_AUDIT_FLEET_CONFIG", None)
        else:
            os.environ["KTP_AUDIT_FLEET_CONFIG"] = prev
    return mod


@pytest.fixture(scope="module")
def audit(tmp_path_factory):
    return _load_module(tmp_path_factory.mktemp("auditcfg"))


def _snap(**sections):
    """Build one host's parsed snapshot: {section: [(line, None), ...]}."""
    return {name: [(line, None) for line in lines] for name, lines in sections.items()}


# --------------------------------------------------------------- positive control

def test_module_exposes_the_functions_under_test(audit):
    """If the loader silently produced a stub, every assertion below passes
    vacuously. Fail here instead."""
    for name in ("normalize_list_fact", "is_ignored_key", "visible",
                 "compute_drift", "render_drift_section"):
        assert callable(getattr(audit, name, None)), f"{name} missing from module"
    assert audit.IGNORED_KEY_PATTERNS, "IGNORED_KEY_PATTERNS is empty"
    assert RC_LOCAL in audit.NORMALIZED_LIST_SECTIONS


# ------------------------------------------------------------------- normalisation

@pytest.mark.parametrize("iface", ["enp1s0f0", "enp2s0f0", "eth0", "eno1", "ens18"])
def test_nic_name_normalises_to_one_fact(audit, iface):
    """Denver's NIC is enp2s0f0 and Chicago's is eth0; the ethtool line is
    otherwise identical, and used to report as two facts (present here /
    absent there) per host variant."""
    line = f"ethtool -G {iface} rx 4096 tx 4096 2>/dev/null"
    assert audit.normalize_list_fact(RC_LOCAL, line) == \
        "ethtool -G $IFACE rx 4096 tx 4096 2>/dev/null"


def test_indent_and_quoting_normalise(audit):
    """Chicago indents its NOTRACK block inside an `if command -v iptables`
    guard and writes $IFACE unquoted; the baremetals do neither."""
    indented = '    ethtool -K "$IFACE" gro off 2>/dev/null'
    flat = "ethtool -K $IFACE gro off 2>/dev/null"
    assert audit.normalize_list_fact(RC_LOCAL, indented) == \
        audit.normalize_list_fact(RC_LOCAL, flat)


def test_normalisation_does_not_merge_genuinely_different_lines(audit):
    """The control that matters. A guard present on one host and absent on
    another is a real difference and must survive normalisation."""
    guarded = '[ -f /sys/kernel/mm/ksm/run ] && echo 0 > /sys/kernel/mm/ksm/run'
    unguarded = 'echo 0 > /sys/kernel/mm/ksm/run 2>/dev/null'
    assert audit.normalize_list_fact(RC_LOCAL, guarded) != \
        audit.normalize_list_fact(RC_LOCAL, unguarded)


def test_normalisation_is_scoped_to_rc_local(audit):
    """Over-reach guard: an interface name in a GRUB flag or a cron line is
    not a NIC-naming artefact and must be left alone."""
    grub = "BOOT_IMAGE=/boot/vmlinuz-6.8.0-110-lowlatency"
    assert audit.normalize_list_fact(GRUB, grub) == grub
    cron = "* * * * * ~/dod-27015/dodserver monitor > /dev/null 2>&1"
    assert audit.normalize_list_fact(CRONTAB, cron) == cron
    # ...including a section that really does mention eth0.
    assert audit.normalize_list_fact(GRUB, "net.ifnames=0") == "net.ifnames=0"


# ------------------------------------------------------------------ ignore patterns

@pytest.mark.parametrize("key", [
    "GRUB CMDLINE > root=UUID=1e8bf55b-72bd-4d7f-8fd8-0ff15824a667",
    "GRUB CMDLINE > root=UUID=56231ae1-f8ae-41e4-9bca-55dc38601944",
    "GRUB CMDLINE > BOOT_IMAGE=/boot/vmlinuz-6.8.0-110-lowlatency",
    "GRUB CMDLINE > BOOT_IMAGE=/vmlinuz-6.8.0-110-lowlatency",
])
def test_per_host_grub_facts_are_ignored(audit, key):
    assert audit.is_ignored_key(key)


@pytest.mark.parametrize("key", [
    "GRUB CMDLINE > isolcpus=2,3,4,5,6,7",
    "GRUB CMDLINE > nohz_full=2,3,4,5,6,7",
    "GRUB CMDLINE > mitigations=off",
    "GRUB CMDLINE > \x01",
    "DODSERVER CRONTAB (non-comment, sorted) > * * * * * ~/dod-27015/dodserver monitor",
])
def test_real_facts_are_not_ignored(audit, key):
    """A CPU-isolation flag going missing on one baremetal is the exact thing
    this audit exists to catch. So is the stray 0x01."""
    assert not audit.is_ignored_key(key)


def test_literal_ignored_keys_still_work(audit):
    """The glob path must not have replaced the exact-match path."""
    assert audit.is_ignored_key("HOST > hostname")
    assert audit.is_ignored_key("HOST > cpu-microcode")
    assert not audit.is_ignored_key("HOST > kernel")


# -------------------------------------------------------------- control characters

def test_visible_escapes_control_characters(audit):
    assert audit.visible("\x01") == "\\x01"
    assert audit.visible("ro \x01 quiet") == "ro \\x01 quiet"
    assert audit.visible("\x7f") == "\\x7f"


def test_visible_leaves_ordinary_text_alone(audit):
    """Including the non-ASCII the report already carries."""
    for text in ("isolcpus=2,3,4,5,6,7", "net.core.rmem_max = 26214400",
                 "Matching: 3 / 4 — ignored", "tab\tseparated"):
        assert audit.visible(text) == text


def test_control_character_fact_is_visible_in_the_rendered_report(audit):
    """Regression for the finding this whole audit turned on: Atlanta and
    Dallas carried a bare 0x01 in /proc/cmdline, and the report rendered it as
    an empty cell -- indistinguishable from a formatting bug."""
    snaps = {
        "Atlanta": _snap(**{GRUB: ["\x01", "isolcpus=2,3"]}),
        "Dallas": _snap(**{GRUB: ["\x01", "isolcpus=2,3"]}),
        "Denver": _snap(**{GRUB: ["isolcpus=2,3"]}),
    }
    lines, items = audit.render_drift_section("t", audit.compute_drift(snaps))
    body = "\n".join(lines)
    assert len(items) == 1, f"expected the 0x01 to be the only item, got {items}"
    assert "\\x01" in body
    assert "\x01" not in body


# --------------------------------------------------------------------- end-to-end

def test_nic_name_divergence_no_longer_reports_as_drift(audit):
    snaps = {
        "Atlanta": _snap(**{RC_LOCAL: ["ethtool -G enp1s0f0 rx 4096 tx 4096 2>/dev/null"]}),
        "Denver": _snap(**{RC_LOCAL: ["ethtool -G enp2s0f0 rx 4096 tx 4096 2>/dev/null"]}),
        "Chicago": _snap(**{RC_LOCAL: ["    ethtool -G $IFACE rx 4096 tx 4096 2>/dev/null"]}),
    }
    _, items = audit.render_drift_section("t", audit.compute_drift(snaps))
    assert items == [], f"expected no drift, got {items}"


def test_a_missing_tuning_line_still_reports_as_drift(audit):
    """Partner control for the test above: same section, same shape, but one
    host genuinely lacks the line."""
    snaps = {
        "Atlanta": _snap(**{RC_LOCAL: ["ethtool -G enp1s0f0 rx 4096 tx 4096 2>/dev/null"]}),
        "Denver": _snap(**{RC_LOCAL: ["ethtool -G enp2s0f0 rx 4096 tx 4096 2>/dev/null"]}),
        "Chicago": _snap(**{RC_LOCAL: []}),
    }
    _, items = audit.render_drift_section("t", audit.compute_drift(snaps))
    assert len(items) == 1
    section, key, value_map = items[0]
    assert key == "ethtool -G $IFACE rx 4096 tx 4096 2>/dev/null"
    assert value_map["<absent>"] == ["Chicago"]


def test_per_host_grub_lines_drop_out_end_to_end(audit):
    """root=UUID and BOOT_IMAGE produce one distinct fact per host, so they
    used to contribute 2N items to every run."""
    snaps = {
        "Atlanta": _snap(**{GRUB: ["root=UUID=aaaa", "BOOT_IMAGE=/boot/vmlinuz-1", "isolcpus=2,3"]}),
        "Dallas": _snap(**{GRUB: ["root=UUID=bbbb", "BOOT_IMAGE=/boot/vmlinuz-1", "isolcpus=2,3"]}),
        "Denver": _snap(**{GRUB: ["root=UUID=cccc", "BOOT_IMAGE=/vmlinuz-1", "isolcpus=2,3"]}),
    }
    _, items = audit.render_drift_section("t", audit.compute_drift(snaps))
    assert items == [], f"expected no drift, got {items}"


def test_a_missing_isolcpus_flag_still_reports(audit):
    """Partner control: the GRUB section must keep catching a host that lost
    its CPU-isolation flags."""
    snaps = {
        "Atlanta": _snap(**{GRUB: ["root=UUID=aaaa", "isolcpus=2,3"]}),
        "Dallas": _snap(**{GRUB: ["root=UUID=bbbb", "isolcpus=2,3"]}),
        "Denver": _snap(**{GRUB: ["root=UUID=cccc"]}),
    }
    _, items = audit.render_drift_section("t", audit.compute_drift(snaps))
    assert len(items) == 1
    assert items[0][1] == "isolcpus=2,3"


# ------------------------------------------------------------- --include-ignored

def test_include_ignored_renders_the_suppressed_items(audit):
    """`--include-ignored` was parsed, passed to render_report, and dropped on
    the floor -- the documented way to see what the filter ate did nothing."""
    snaps = {
        "Atlanta": _snap(**{GRUB: ["root=UUID=aaaa"]}),
        "Dallas": _snap(**{GRUB: ["root=UUID=bbbb"]}),
    }
    drift = audit.compute_drift(snaps)
    off, _ = audit.render_drift_section("t", drift, include_ignored=False)
    on, _ = audit.render_drift_section("t", drift, include_ignored=True)
    assert "root=UUID=aaaa" not in "\n".join(off)
    assert "root=UUID=aaaa" in "\n".join(on)
    assert "Ignored by rule" in "\n".join(on)


def test_include_ignored_does_not_change_the_drift_count(audit):
    """It is a display switch. If it ever starts adding to `drift_items` it
    would change the exit code, and this audit is used as a CI gate."""
    snaps = {
        "Atlanta": _snap(**{GRUB: ["root=UUID=aaaa", "isolcpus=2,3"]}),
        "Dallas": _snap(**{GRUB: ["root=UUID=bbbb"]}),
    }
    drift = audit.compute_drift(snaps)
    _, off = audit.render_drift_section("t", drift, include_ignored=False)
    _, on = audit.render_drift_section("t", drift, include_ignored=True)
    assert off == on
    assert len(off) == 1
