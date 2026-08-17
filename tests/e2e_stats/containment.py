"""Keep a Lane B match inside the container.

Lane B drives a *real* match through the real state machine: the same forwards
fire, the same log lines are emitted, the same Discord and HLTV code paths are
entered. That is the point — a synthetic match that skipped those would not be
testing the thing production does.

It also means the only thing standing between a nightly CI job and a message in
a real Discord channel is configuration.

## Today that configuration is right by accident

`config/local` happens to leave `discord_relay_url` and `hltv_api_url` blank,
and the HUD observer happens to POST at a `localhost` that does not answer
inside the container. Nothing escapes. But nothing *checks* either, so a config
that later grows a URL — a copy-paste from `config/online`, a new field with a
default — would have CI posting to production with no signal at all.

Accidental safety is not safety. These checks turn it into a precondition that
fails loudly at run start, before a server boots, rather than a surprise
afterwards.

## What this deliberately does NOT do

It does not stub, mock or disable the integrations. The plugins load, the code
paths run, the `curl` calls are attempted against an empty URL and no-op. That
is production's own behaviour for an unconfigured server, so the lane keeps
testing the real path — it just cannot reach anything.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


class ContainmentError(RuntimeError):
    """A Lane B run could reach something outside the container. Fatal, and
    checked before anything boots — the whole point is to fail before the
    thing that would send, not to notice afterwards."""


# Keys whose value being non-empty means the run could reach a real service.
# Matched case-insensitively against `key = value` lines.
_OUTBOUND_KEYS = (
    "discord_relay_url",
    "discord_auth_secret",
    "hltv_api_url",
    "hltv_api_key",
)

# Plugins that talk to something outside the process and have no business in a
# test lane. KTPHudObserver is a local-dev addition, not part of production's
# plugin set, and it POSTs on a timer — inside the container that is several
# hundred `[HUD] POST failed (code 7)` lines burying the output that matters.
_DROP_PLUGINS = ("KTPHudObserver.amxx",)

_KV_RE = re.compile(r"^\s*([A-Za-z0-9_]+)\s*=\s*(.*?)\s*$")


def _value(line: str) -> tuple[str, str] | None:
    m = _KV_RE.match(line)
    if not m:
        return None
    key, val = m.group(1), m.group(2)
    # Strip the quoting styles these .ini files mix.
    val = val.strip().strip('"').strip("'").strip()
    return key.lower(), val


@dataclass
class ContainmentReport:
    checked: list[str] = field(default_factory=list)
    dropped_plugins: list[str] = field(default_factory=list)
    match_id: str = ""


def assert_no_outbound_config(config_dir: Path) -> list[str]:
    """Every outbound URL/secret in the lane's config must be empty.

    Raises rather than warning. A warning in a nightly is a line nobody reads;
    the failure mode being guarded against is "CI posted to Discord for three
    weeks and nobody noticed".
    """
    offenders: list[str] = []
    checked: list[str] = []
    for ini in sorted(config_dir.glob("*.ini")):
        for raw in ini.read_text(encoding="utf-8", errors="replace").splitlines():
            if raw.lstrip().startswith((";", "#")):
                continue
            kv = _value(raw)
            if not kv:
                continue
            key, val = kv
            if key in _OUTBOUND_KEYS:
                checked.append(f"{ini.name}:{key}")
                if val:
                    offenders.append(f"{ini.name}: {key} = {val!r}")
    if offenders:
        raise ContainmentError(
            "Lane B config would let this run reach a real service:\n  "
            + "\n  ".join(offenders)
            + "\n\nThis lane drives a real match through the real state "
              "machine, so those code paths WILL be entered. Blank the values "
              "or point the lane at a different config directory."
        )
    if not checked:
        # Nothing matched, which means either the keys were renamed or the
        # wrong directory was passed. Either way this check is now vacuous, and
        # a vacuous containment check is worse than none — it reads as proof.
        raise ContainmentError(
            f"no outbound keys found in {config_dir} — expected at least one of "
            f"{', '.join(_OUTBOUND_KEYS)}. Either the config keys were renamed "
            f"(update _OUTBOUND_KEYS) or this is the wrong directory. Refusing "
            f"to treat 'found nothing' as 'found nothing bad'."
        )
    return checked


def strip_outbound_plugins(plugins_ini: str) -> tuple[str, list[str]]:
    """Remove the plugins that phone out. Returns (new text, what was dropped).

    Comment lines are left alone so the file still reads as the production one
    with an explicit subtraction, rather than a quietly different list.
    """
    dropped: list[str] = []
    out: list[str] = []
    for line in plugins_ini.splitlines():
        # Strip the comment first, then take the first token. Checking the raw
        # line for emptiness is not enough: a comment-only line has content but
        # no code, and splitting it yields nothing to index.
        code = line.split(";", 1)[0].strip()
        name = code.split()[0] if code else ""
        if name in _DROP_PLUGINS:
            dropped.append(name)
            out.append(f"; [lane-b] removed {name}: posts outside the process")
            continue
        out.append(line)
    return "\n".join(out) + "\n", dropped


def assert_test_match_id(match_id: str) -> str:
    """A driven match must be identifiably synthetic.

    KTPMatchHandler's test-mode setup builds `<systime>-TEST`. Asserting the
    suffix means that if this ever reaches a real database — a
    misconfigured host, a shared schema — the rows are recognisable as test
    data rather than silently joining the season.
    """
    if not match_id:
        raise ContainmentError(
            "the match driver returned an empty match_id, so nothing can be "
            "asserted about what these rows would be tagged with"
        )
    if not match_id.endswith("-TEST"):
        raise ContainmentError(
            f"match_id {match_id!r} does not end in -TEST. Either this is not "
            f"a test-mode build, or the id shape changed — in both cases these "
            f"rows would be indistinguishable from a real match."
        )
    return match_id
