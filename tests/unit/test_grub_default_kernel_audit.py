"""Fixture tests for scripts/fix-grub-default-kernel.sh (audit mode only).

Each fixture reproduces a GRUB state measured on the fleet 2026-08-25, down to
the line shapes the script parses. --fix is never exercised here -- it calls
grub-set-default, which only makes sense on a real host.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / "scripts" / "fix-grub-default-kernel.sh"
# CI runs plain bash; on a Windows workstation "bash" resolves to WSL's, which
# cannot see these paths -- point KTP_TEST_BASH at Git Bash there.
BASH = os.environ.get("KTP_TEST_BASH", "bash")

MENU_HEAD = """\
if [ "${next_entry}" ] ; then
   set default="${next_entry}"
else
   set default="%s"
fi
menuentry 'Ubuntu' --class ubuntu --class gnu-linux $menuentry_id_option 'gnulinux-simple-x' {
}
submenu 'Advanced options for Ubuntu' $menuentry_id_option 'gnulinux-advanced-x' {
"""


def make_cfg(default: str, kernels: list[str]) -> str:
    cfg = MENU_HEAD % default
    for k in kernels:
        cfg += f"\tmenuentry 'Ubuntu, with Linux {k}' --class ubuntu $menuentry_id_option 'gnulinux-{k}-advanced-x' {{\n\t}}\n"
        cfg += f"\tmenuentry 'Ubuntu, with Linux {k} (recovery mode)' --class ubuntu $menuentry_id_option 'gnulinux-{k}-recovery-x' {{\n\t}}\n"
    cfg += "}\n"
    return cfg


def run_audit(tmp_path: Path, cfg: str, etc_default: str, grubenv: str | None,
              boot_kernels: list[str], uname: str):
    (tmp_path / "grub.cfg").write_text(cfg)
    (tmp_path / "default-grub").write_text(etc_default)
    envfile = tmp_path / "grubenv"
    if grubenv is not None:
        envfile.write_text(grubenv)
    boot = tmp_path / "boot"
    boot.mkdir()
    for k in boot_kernels:
        (boot / f"vmlinuz-{k}").write_text("")
    return subprocess.run(
        [BASH, SCRIPT.as_posix()],
        env={
            **os.environ,
            "KTP_GRUB_CFG": (tmp_path / "grub.cfg").as_posix(),
            "KTP_GRUB_DEFAULT_FILE": (tmp_path / "default-grub").as_posix(),
            "KTP_GRUB_ENV": envfile.as_posix(),
            "KTP_BOOT_DIR": boot.as_posix(),
            "KTP_UNAME_R": uname,
        },
        capture_output=True, text=True,
    )


def test_atlanta_literal_title_pin_is_two_findings(tmp_path):
    """The incident shape: saved_entry pins the old kernel by menu title."""
    r = run_audit(
        tmp_path,
        make_cfg("${saved_entry}",
                 ["6.8.0-138-lowlatency", "6.8.0-138-generic", "6.8.0-110-lowlatency"]),
        'GRUB_DEFAULT=saved\n',
        "# GRUB Environment Block\nsaved_entry=Advanced options for Ubuntu>Ubuntu, with Linux 6.8.0-110-lowlatency\n",
        ["6.8.0-110-lowlatency", "6.8.0-138-generic", "6.8.0-138-lowlatency"],
        "6.8.0-110-lowlatency",
    )
    assert r.returncode == 1, r.stdout + r.stderr
    assert "LITERAL TITLE pin" in r.stdout
    assert "not the newest lowlatency kernel (6.8.0-138-lowlatency)" in r.stdout


def test_dallas_saved_positional_is_clean(tmp_path):
    """The healthy control: GRUB_DEFAULT=saved + saved_entry=1>0."""
    r = run_audit(
        tmp_path,
        make_cfg("${saved_entry}", ["6.8.0-138-lowlatency", "6.8.0-138-generic"]),
        'GRUB_DEFAULT=saved\n',
        "# GRUB Environment Block\nsaved_entry=1>0\n",
        ["6.8.0-138-generic", "6.8.0-138-lowlatency"],
        "6.8.0-138-lowlatency",
    )
    assert r.returncode == 0, r.stdout + r.stderr
    assert "FINDING" not in r.stdout
    assert "next boot       : Ubuntu, with Linux 6.8.0-138-lowlatency" in r.stdout


def test_denver_etc_default_disagrees_with_baked(tmp_path):
    """GRUB_DEFAULT literal '1>2' (= the OLD kernel) while grub.cfg still bakes
    '1>0' -- boots right today, downgrades after the next update-grub."""
    r = run_audit(
        tmp_path,
        make_cfg("1>0", ["6.8.0-138-lowlatency", "6.8.0-110-lowlatency"]),
        'GRUB_DEFAULT="1>2"\n',
        None,
        ["6.8.0-110-lowlatency", "6.8.0-138-lowlatency"],
        "6.8.0-138-lowlatency",
    )
    assert r.returncode == 1, r.stdout + r.stderr
    assert "positional literal" in r.stdout
    assert "disagrees with the baked" in r.stdout
    # today's boot is still fine -- the finding is the pending re-bake
    assert "next boot       : Ubuntu, with Linux 6.8.0-138-lowlatency" in r.stdout
    assert "'1>2' -> 'Ubuntu, with Linux 6.8.0-110-lowlatency'" in r.stdout


def test_chicago_baked_positional_hits_generic(tmp_path):
    """GRUB_DEFAULT='1>2' baked as-is: submenu[2] is 138-generic, so the next
    reboot silently drops the lowlatency flavour."""
    r = run_audit(
        tmp_path,
        make_cfg("1>2", ["6.8.0-138-lowlatency", "6.8.0-138-generic"]),
        'GRUB_DEFAULT="1>2"\n',
        None,
        ["6.8.0-138-generic", "6.8.0-138-lowlatency"],
        "6.8.0-138-lowlatency",
    )
    assert r.returncode == 1, r.stdout + r.stderr
    assert "positional literal" in r.stdout
    assert "disagrees" not in r.stdout
    assert "next boot ('Ubuntu, with Linux 6.8.0-138-generic') is not the newest lowlatency" in r.stdout


@pytest.mark.parametrize("bad", ["", "garbage>9"])
def test_unresolvable_default_is_a_finding_not_a_pass(tmp_path, bad):
    """A zero must not read as clean: an unresolvable default still exits 1."""
    r = run_audit(
        tmp_path,
        make_cfg(bad or "9>9", ["6.8.0-138-lowlatency"]),
        'GRUB_DEFAULT="9>9"\n',
        None,
        ["6.8.0-138-lowlatency"],
        "6.8.0-138-lowlatency",
    )
    assert r.returncode == 1, r.stdout + r.stderr
    assert "could not resolve" in r.stdout
