"""Instance configs the provisioning scripts write must carry the fleet's console-log retention.

LinuxGSM's _default.cfg ships logdays="7", so an instance rebuilt from these
scripts without its own line silently falls back to a week of console logs.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

PROVISION = Path(__file__).parents[2] / "provision"

# Heredocs that write a per-instance LinuxGSM cfg; common.cfg is shared, not per-instance.
_INSTANCE_HEREDOC = re.compile(
    r'cat > "\$[A-Z_]+(?:/lgsm/config-lgsm/dodserver/\$EXEC_NAME\.cfg|/lgsm/config-lgsm/dodserver/dodserver\.cfg)?"?'
    r' << EOF\n(?P<body>.*?)\nEOF\n',
    re.S,
)


def _bodies(name: str) -> list[str]:
    text = (PROVISION / name).read_text(encoding="utf-8")
    return [m.group("body") for m in _INSTANCE_HEREDOC.finditer(text)
            if 'port="' in m.group("body") and "common.cfg" not in m.group(0)]


@pytest.mark.parametrize("script,expected", [
    ("install-linuxgsm.sh", 2),
    ("clone-ktp-stack.sh.example", 1),
])
def test_every_instance_cfg_sets_logdays(script: str, expected: int) -> None:
    bodies = _bodies(script)
    assert len(bodies) >= expected, f"{script}: instance cfg heredocs not found"
    for body in bodies:
        assert re.search(r'^logdays="21"$', body, re.M), body
