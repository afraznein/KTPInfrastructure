#!/usr/bin/env python3
"""Shape-based redaction for fleet-audit output.

WHY THIS EXISTS. `fleet-drift-snapshot.sh` captures root's crontab and
`/etc/rc.local` VERBATIM, and `.github/workflows/fleet-audit.yml` publishes the
resulting report to a GitHub issue and a run artifact on a repository that is
PUBLIC. A credential ever placed in a cron line would publish itself on the
first run, and a published artifact cannot be unpublished. The same report is
also written world-readable to `/var/log/ktp-audit-*.md` on the data server, so
redacting here narrows that path too.

Redaction is by SHAPE, never against a list of today's credentials: a denylist
goes stale at the next rotation, and it goes stale in the direction that leaks.

THE PROPERTY THIS GUARANTEES. No value survives a redacted line that is

  * the userinfo half of a URL (`scheme://user:pass@host`),
  * the right-hand side of an assignment whose NAME names a credential
    (`*password*`, `*secret*`, `*token*`, `*api_key*`, `*auth*`, `*rcon*`, ...),
    whether written with `=` or `:`,
  * the right-hand side of ANY shell env assignment inside root's crontab, or
  * a standalone opaque token: at least 20 characters of `[A-Za-z0-9+=_-]`
    mixing upper case, lower case and digits, or at least 32 hex characters.

A shell variable reference (`$SECRET`, `${SECRET}`) is kept deliberately: it is
not a value, and whether a host inlines a credential or reads one is exactly the
drift worth seeing.

WHAT IT DELIBERATELY LEAVES ALONE, and why. The audit's correctness checks
compare live facts against `provision/expected-*.conf`, so the value half of
those facts IS the contract: GRUB flags (`isolcpus=2,3,4,5,6,7` is matched
literally), sysctl values, 16-character binary md5 prefixes, LinuxGSM monitor
states, and the `/etc/rc.local` tuning lines the glob patterns in
`expected-rc-local.conf` match on. `/` and `.` are excluded from the opaque-token
character class for the same reason -- with them, every filesystem path is an
opaque token, and rc.local is mostly paths. A rule that blanked those would turn
the audit green by blinding it, which is the worse failure.

KNOWN LIMIT, stated rather than hidden: outside the crontab section, a short
all-lower-case secret assigned to a variable whose name does not name a
credential survives. Shape cannot see that one. Neither can a denylist after a
rotation, which is why shape is still the better gate.
"""
from __future__ import annotations

import re
import sys

PLACEHOLDER = "<redacted>"

# The `=== NAME ===` header fleet-drift-snapshot.sh emits before each block.
_SECTION_RE = re.compile(r"^=== (.+?) ===$")

# Root's crontab. Nothing downstream compares the value half of an assignment
# here -- there is no expected-crontab.conf -- so this one section gets the
# broad env-assignment rule on top of the shape rules.
CRONTAB_SECTION = "DODSERVER CRONTAB (non-comment, sorted)"

_URL_USERINFO_RE = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)[^\s/?#@]*@")

# Credential-naming words. The surrounding `[A-Za-z0-9_.-]*` is what lets this
# catch `X-Relay-Auth`, `HLTV_API_KEY` and `hlstats_rcon_password` alike, so the
# name is bounded by the separator rather than by a word boundary.
_CREDENTIAL_WORDS = (
    r"passw(?:or)?d|passwd|secret|token|api[_-]?key|auth|bearer|credential"
    r"|rcon|priv(?:ate)?[_-]?key|access[_-]?key|webhook|cookie"
)
_QUOTED_OR_BARE = r"\"[^\"]*\"|'[^']*'|[^\s\"';|&]+"

_CREDENTIAL_ASSIGN_RE = re.compile(
    r"(?i)(?P<name>[A-Za-z0-9_.-]*(?:" + _CREDENTIAL_WORDS + r")[A-Za-z0-9_.-]*)"
    r"(?P<sep>\s*[=:]\s*)"
    r"(?P<value>" + _QUOTED_OR_BARE + r")"
)

# `NAME=value`, the shell env-assignment shape. The lookbehind keeps it off
# `--flag=value`, which is an argument rather than a place a credential is set.
_ENV_ASSIGN_RE = re.compile(
    r"(?<![\w.\-])(?P<name>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?P<sep>=)"
    r"(?P<value>\"[^\"]*\"|'[^']*'|[^\s\"';|&]*)"
)

_VAR_REF_RE = re.compile(r"^\$(?:\{[A-Za-z_]\w*\}|[A-Za-z_]\w*)$")

# `/` is excluded in the lookarounds too, so base64 adjacent to a `/` (a PEM body line) is never redacted.
_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9+=_/.\-])[A-Za-z0-9+=_-]{20,}(?![A-Za-z0-9+=_/.\-])"
)
_HEX_RE = re.compile(r"\A[0-9a-fA-F]{32,}\Z")

# Diagnostics only. A paramiko exception carries the address it failed to reach;
# the report has no use for it, and this repository writes fleet addresses as
# placeholders everywhere else.
_IPV4_RE = re.compile(r"(?<![\w.])\d{1,3}(?:\.\d{1,3}){3}(?![\w.])")


def _is_opaque(token: str) -> bool:
    """True for a token that carries no meaning a reader could check."""
    if _HEX_RE.match(token):
        return True
    return (any(c.islower() for c in token)
            and any(c.isupper() for c in token)
            and any(c.isdigit() for c in token))


def _replace_assignment(match: "re.Match[str]") -> str:
    value = match.group("value")
    if _VAR_REF_RE.match(value.strip("\"'")):
        return match.group(0)
    return match.group("name") + match.group("sep") + PLACEHOLDER


def _redact_tokens(text: str) -> str:
    return _TOKEN_RE.sub(
        lambda m: PLACEHOLDER if _is_opaque(m.group(0)) else m.group(0), text)


def redact_line(line: str, section: str | None = None) -> str:
    """Redact one line. `section` is the snapshot section it came from."""
    out = _URL_USERINFO_RE.sub(lambda m: m.group(1) + PLACEHOLDER + "@", line)
    out = _CREDENTIAL_ASSIGN_RE.sub(_replace_assignment, out)
    if section == CRONTAB_SECTION:
        out = _ENV_ASSIGN_RE.sub(_replace_assignment, out)
    return _redact_tokens(out)


def redact_text(text: str, section: str | None = None) -> str:
    """Redact free text that carries no section structure."""
    return "\n".join(redact_line(line, section) for line in text.splitlines())


def redact_snapshot(text: str) -> str:
    """Redact a whole `fleet-drift-snapshot.sh` capture, section by section.

    Header lines pass through untouched: the orchestrator keys every fact off
    them, so rewriting one would read as every section vanishing at once.
    """
    out = []
    section = None
    for line in text.splitlines():
        header = _SECTION_RE.match(line)
        if header:
            section = header.group(1).strip()
            out.append(line)
            continue
        out.append(redact_line(line, section))
    trailer = "\n" if text.endswith("\n") else ""
    return "\n".join(out) + trailer


def redact_diagnostic(text: str) -> str:
    """Redact an exception or stderr string, addresses included."""
    return _IPV4_RE.sub("<host>", redact_text(text))


if __name__ == "__main__":
    sys.stdout.write(redact_snapshot(sys.stdin.read()))
