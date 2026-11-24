"""Guard the tracked copy of the data server's needrestart override."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

DROPIN = (
    Path(__file__).resolve().parents[2]
    / "ops" / "data-server" / "needrestart" / "conf.d" / "50-ktp-no-auto-restart.conf"
)

PINNED = [
    "ktp-ac-api.service",
    "nginx.service",
    "hltv@27020.service",
    "hltv@27043.service",
    # The stats daemon is one process for the whole fleet; a restart mid-match drops log lines.
    "hlstatsx.service",
    "ktp-admin-bot.service",
]
# Neighbours that share a prefix with a pinned unit and must still restart normally.
NOT_PINNED = [
    "hltv-api.service",
    "hltv-demo-renamer.service",
    "hlstatsx-ingest-monitor.service",
    "ktp-admin-bot-old.service",
    "nginx-debug.service",
    "ktp-ac-api-old.service",
    "ssh.service",
]

# needrestart's own selection: the first override_rc regex that matches decides, default restart.
PERL_DECIDE = r"""
our %nrconf; $nrconf{override_rc} = {};
my $src = do { local $/; open my $fh, '<', $ARGV[0] or die $!; <$fh> };
eval $src; die "parse: $@" if $@;
for my $rc (@ARGV[1..$#ARGV]) {
    my $r = 1;
    foreach my $re (keys %{$nrconf{override_rc}}) { next unless $rc =~ /$re/; $r = $nrconf{override_rc}->{$re}; last }
    print "$rc=$r\n";
}
"""


def _patterns() -> list[str]:
    text = DROPIN.read_text(encoding="utf-8")
    return re.findall(r"^\$nrconf\{override_rc\}->\{qr\((.+)\)\} = 0;$", text, re.M)


def test_file_is_lf_only() -> None:
    assert b"\r" not in DROPIN.read_bytes()


def test_every_statement_is_an_override_to_zero() -> None:
    code = [l for l in DROPIN.read_text(encoding="utf-8").splitlines() if l and not l.startswith("#")]
    assert len(code) == len(_patterns()) == 5


def test_adds_to_override_rc_instead_of_replacing_it() -> None:
    # Assigning the whole hash would drop the stock dbus/getty/systemd-logind entries.
    assert "$nrconf{override_rc} =" not in DROPIN.read_text(encoding="utf-8")


@pytest.mark.parametrize("unit", PINNED)
def test_pinned_units_match(unit: str) -> None:
    assert any(re.search(p, unit) for p in _patterns())


@pytest.mark.parametrize("unit", NOT_PINNED)
def test_neighbours_do_not_match(unit: str) -> None:
    assert not any(re.search(p, unit) for p in _patterns())


@pytest.mark.skipif(shutil.which("perl") is None, reason="perl not installed")
def test_perl_evaluates_it_as_needrestart_does() -> None:
    out = subprocess.run(
        ["perl", "-e", PERL_DECIDE, str(DROPIN), *PINNED, *NOT_PINNED],
        capture_output=True, text=True, check=True,
    ).stdout
    decided = dict(line.split("=") for line in out.split())
    assert {u: decided[u] for u in PINNED} == {u: "0" for u in PINNED}
    assert {u: decided[u] for u in NOT_PINNED} == {u: "1" for u in NOT_PINNED}
