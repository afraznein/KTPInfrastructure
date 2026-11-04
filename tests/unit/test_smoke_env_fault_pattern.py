"""The smoke env-fault discriminator must be narrow.

Tier 1 Smoke treats one specific container-log signature as a runner
environment fault and stops it gating a merge. That exemption is only safe
while the signature cannot match a real failure, so the pattern is read out of
the shipped workflow rather than restated here -- a copy would let the two
drift apart silently.
"""

import re
from pathlib import Path

import pytest

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "smoke-callable.yml"
BEGIN = "# smoke-env-fault-pattern-begin"
END = "# smoke-env-fault-pattern-end"

# The signature as the runner actually emitted it, kept verbatim.
REAL = (
    "ktp-game-1-1  | WARNING: UDP_OpenSocket: port: 27015 socket: Function not "
    "implementedFATAL ERROR (shutting down): NET_OpenIP: Couldn't allocate "
    "dedicated server IP port 27015."
)

# Each of these is a genuine failure or a different environment problem. The
# exemption must not reach any of them.
MUST_NOT_MATCH = [
    ("ordinary boot timeout", "ktp-game-1-1  | Server is running but never answered rcon"),
    ("plugin failed to load", "ktp-game-1-1  | [AMXX] Plugin ktp_cvar.amxx failed to load"),
    ("module failed to load", "ktp-game-1-1  | [AMXX] Module dodx failed to attach"),
    # The same syscall, a different errno: a taken port is a real conflict and
    # must still fail, so errno is load-bearing and not decoration.
    ("socket error, port taken",
     "ktp-game-1-1  | WARNING: UDP_OpenSocket: port: 27015 socket: Address already in use"),
    ("permission denied socket",
     "ktp-game-1-1  | WARNING: UDP_OpenSocket: port: 27015 socket: Permission denied"),
    ("unrelated ENOSYS elsewhere",
     "ktp-game-1-1  | mmap failed: Function not implemented"),
    ("empty log", ""),
    ("segfault", "ktp-game-1-1  | Segmentation fault (core dumped)"),
]


def extract_pattern(text):
    """Pull the grep -qE pattern from between the shipped markers."""
    assert text.count(BEGIN) == 1, "exactly one begin marker expected"
    assert text.count(END) == 1, "exactly one end marker expected"
    body = text[text.index(BEGIN) + len(BEGIN):text.index(END)]
    found = re.findall(r"grep -qE '([^']+)'", body)
    assert len(found) == 1, "expected exactly one grep -qE pattern, found %d" % len(found)
    return found[0]


@pytest.fixture(scope="module")
def pattern():
    assert WORKFLOW.is_file(), "workflow not found at %s" % WORKFLOW
    return extract_pattern(WORKFLOW.read_text(encoding="utf-8"))


def test_pattern_matches_the_observed_signature(pattern):
    assert re.search(pattern, REAL), "the pattern no longer matches the log line it was built for"


@pytest.mark.parametrize("label,line", MUST_NOT_MATCH, ids=[c[0] for c in MUST_NOT_MATCH])
def test_pattern_does_not_excuse_a_real_failure(pattern, label, line):
    assert not re.search(pattern, line), "the exemption reaches %r, which is a real failure" % label


def test_pattern_is_not_vacuously_broad(pattern):
    """A pattern that matches everything would pass every case above by luck."""
    assert not re.search(pattern, "x" * 200)
    assert len(pattern) > len("UDP_OpenSocket"), "pattern is no narrower than the syscall name"


def test_errno_is_required_not_just_the_syscall(pattern):
    """Guards the mutation that motivated this file.

    Broadening to the syscall name alone still matches the real line, so the
    happy-path test cannot catch it; only a case carrying a different errno can.
    """
    syscall_only = "UDP_OpenSocket"
    assert re.search(syscall_only, REAL), "fixture sanity: the broad form would match the real line"
    taken = dict(MUST_NOT_MATCH)["socket error, port taken"]
    assert re.search(syscall_only, taken), "fixture sanity: the broad form would also match a conflict"
    assert not re.search(pattern, taken), "the shipped pattern must be narrower than the syscall name"


def test_exemption_is_wired_to_its_own_exit_code():
    """The pattern is only half of it; the verdict must route rc=4 separately.

    If the env-fault return value collided with the image-fault one, this
    exemption would silently inherit the retry-then-warn path built for a
    different cause.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "return 4" in text, "the discriminator must return its own code"
    assert text.count("report_env_fault") == 2, "defined once and called once"
    assert '"$RC" -eq 4' in text, "the verdict must branch on the env-fault code"
    assert '"$RC" -eq 3' in text, "the image-fault verdict must still exist independently"
