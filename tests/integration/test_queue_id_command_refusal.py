"""Tier-2 contract: the 12man Queue-ID prompt refuses a chat command.

Why this file exists at all. On 2026-10-24 (ATL1) a captain answered the
Queue-ID prompt with `.confirm` twice. The prompt's own wording invited it, the
sanitizer strips `.`, so "confirm" became the Queue ID and the match ran as
`1.3-confirm-NY1` — an id no fixture can carry, and the stats daemon refused
every capture line of the match. KTPMatchHandler#57 added the guard; the Tier-2
pin moved to it on 2026-10-29 (KTPInfrastructure#766). Nothing then asserted the
guard, and a deploy row was carried as discharged on the belief that a Tier-2
suite did.

What this asserts, and what it does NOT. These are STRUCTURAL assertions over
the pinned KTPMatchHandler source with comments stripped — not a running-server
assertion. Driving the real refusal needs a client in the Queue-ID input state,
and there is no way to get one from this repo: the state is entered only through
an AMXX menu selection, the interception requires `id == g_13CaptainId`, and
KTPMatchHandler's own `match_start_with_args` comment records that fake-client
`engclient_cmd("say")` does not traverse the registered chat handler. A
behavioural test needs a `KTP_TEST_MODE` rcon in KTPMatchHandler that calls
`handle_13_queue_id_input` directly; none exists, so that gap is named here
rather than papered over with a weaker test that reads like a strong one.

The assertions are ordering facts, which is what the incident actually turned
on: the guard has to sit ahead of the sanitizer (or a `.`-prefixed token still
becomes a Queue ID) and ahead of both input-state branches (or it only covers
one of the two inputs the captain types). Both halves of the 2026-10-24 incident
were state-2 and state-1 respectively, so "it refuses `.confirm`" understates
the guard twice over: it refuses every `.`/`/` token, in both states.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

_WORKSPACE = Path(__file__).resolve().parents[2]
_FUNC = "handle_13_queue_id_input"

# Candidate homes for the KTPMatchHandler source, in resolution order. The
# Tier-2 workflow checks the reviewed pin out at `.tier2/KTPMatchHandler`, which
# is the one that matters: these assertions are about the build the gate
# compiles, not about whatever tree a workstation happens to hold.
_SRC_CANDIDATES = (
    ("KTP_MATCHHANDLER_SRC", None),
    (None, _WORKSPACE / ".tier2" / "KTPMatchHandler" / "KTPMatchHandler.sma"),
    (None, _WORKSPACE.parent / "KTPMatchHandler" / "KTPMatchHandler.sma"),
)


def _resolve_source() -> Path:
    tried = []
    for env_var, path in _SRC_CANDIDATES:
        candidate = Path(os.environ[env_var]) if env_var and os.environ.get(env_var) else path
        if candidate is None:
            continue
        tried.append(str(candidate))
        if candidate.is_file():
            return candidate
    where = "\n  ".join(tried)
    # In CI an unresolvable source is a broken gate, not an absent dependency:
    # the workflow checks the pin out before pytest runs, so skipping here would
    # retire the assertion silently.
    if os.environ.get("GITHUB_ACTIONS"):
        pytest.fail(f"KTPMatchHandler source not found; looked in:\n  {where}")
    pytest.skip(
        "KTPMatchHandler source not found (set KTP_MATCHHANDLER_SRC to a "
        f"checkout's KTPMatchHandler.sma); looked in:\n  {where}"
    )


def strip_comments(src: str) -> str:
    """Drop `//` and `/* */`, keep string and char literals. Pawn escapes with
    `^`, not `\\`, and the guard under test is written with char literals, so a
    stripper that mishandles either would be comparing the wrong text."""
    out: list[str] = []
    i, n = 0, len(src)
    while i < n:
        ch = src[i]
        if ch in "\"'":
            quote = ch
            out.append(ch)
            i += 1
            while i < n and src[i] != quote:
                if src[i] == "^":
                    out.append(src[i])
                    i += 1
                    if i < n:
                        out.append(src[i])
                        i += 1
                    continue
                out.append(src[i])
                i += 1
            if i < n:
                out.append(src[i])
                i += 1
            continue
        if src.startswith("//", i):
            while i < n and src[i] != "\n":
                i += 1
            continue
        if src.startswith("/*", i):
            end = src.find("*/", i + 2)
            i = n if end < 0 else end + 2
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _balanced(text: str, start: int, opener: str, closer: str) -> tuple[int, int]:
    depth = 0
    for i in range(start, len(text)):
        if text[i] == opener:
            depth += 1
        elif text[i] == closer:
            depth -= 1
            if depth == 0:
                return start, i
    raise AssertionError(f"unbalanced {opener!r} from offset {start}")


def function_body(src: str, name: str) -> str:
    m = re.search(r"\bstock\s+" + re.escape(name) + r"\s*\(", src)
    assert m, f"{name} not found in the pinned source"
    open_brace = src.index("{", m.end())
    _, close = _balanced(src, open_brace, "{", "}")
    return src[open_brace + 1:close]


def if_branches(body: str):
    """(offset, condition, block) for every `if` in `body`, outer and nested."""
    for m in re.finditer(r"\bif\s*\(", body):
        lpar = m.end() - 1
        _, rpar = _balanced(body, lpar, "(", ")")
        cursor = rpar + 1
        while cursor < len(body) and body[cursor].isspace():
            cursor += 1
        if cursor < len(body) and body[cursor] == "{":
            _, end = _balanced(body, cursor, "{", "}")
            block = body[cursor + 1:end]
        else:
            semi = body.find(";", cursor)
            block = body[cursor:semi + 1] if semi >= 0 else body[cursor:]
        yield m.start(), " ".join(body[lpar + 1:rpar].split()), block


@pytest.fixture(scope="module")
def body() -> str:
    text = strip_comments(_resolve_source().read_text(encoding="utf-8", errors="replace"))
    out = function_body(text, _FUNC)
    # Every assertion below reads this text, so prove the stripping happened on
    # it: a claim that only ever held in a comment must not be able to pass.
    assert "//" not in out and "/*" not in out, "comments survived stripping"
    return out


def _offset(body: str, predicate) -> int:
    hits = [off for off, cond, _ in if_branches(body) if predicate(cond)]
    assert hits, "no `if` in the function matched"
    return min(hits)


def _is_prefix_guard(cond: str) -> bool:
    return "input[0]" in cond and "'.'" in cond and "'/'" in cond


def _guard(body: str) -> tuple[int, str]:
    hits = [(off, block) for off, cond, block in if_branches(body) if _is_prefix_guard(cond)]
    assert len(hits) == 1, f"expected exactly one chat-command prefix guard, found {len(hits)}"
    return hits[0]


# ---------------------------------------------------------------------------
# Controls. The stripper is what makes every other assertion here a claim about
# code, so it gets its own fixture rather than being trusted.
# ---------------------------------------------------------------------------

def test_stripper_removes_comments_and_keeps_literals():
    src = (
        'a();  // if (input[0] == \'.\' || input[0] == \'/\') commented\n'
        '/* if (input[0] == \'.\' || input[0] == \'/\') blocked */\n'
        'b("a // b /* c */ d");\n'
        "c('.');\n"
    )
    out = strip_comments(src)
    assert "commented" not in out and "blocked" not in out
    assert '"a // b /* c */ d"' in out, "a comment marker inside a string was eaten"
    assert "c('.');" in out


def test_function_is_present_and_carries_both_input_states(body):
    # Positive control for everything below: an empty or wrongly-sliced body
    # would satisfy most "X is absent" assertions for the wrong reason.
    assert _offset(body, lambda c: "g_13InputState == 1" in c) > 0
    assert _offset(body, lambda c: "g_13InputState == 2" in c) > 0


# ---------------------------------------------------------------------------
# The guard
# ---------------------------------------------------------------------------

def test_both_chat_command_prefixes_are_refused(body):
    """`.` and `/` both. The incident was `.confirm`, but every KTP chat command
    has a `/` twin, so a guard covering one prefix would leave `/confirm`
    landing as the Queue ID `confirm`."""
    _guard(body)


def test_guard_precedes_the_sanitizer(body):
    """Order is the whole fix. The sanitizer strips `.` from the input, so a
    guard placed after it can never see a command prefix."""
    loops = [m.start() for m in re.finditer(r"\bfor\s*\(", body)]
    assert len(loops) == 1, f"expected one loop (the sanitizer), found {len(loops)}"
    guard_at, _ = _guard(body)
    assert guard_at < loops[0]


def test_guard_precedes_both_input_state_branches(body):
    """Reachable from BOTH inputs the captain types. 2026-10-24 needed both: the
    first `.confirm` was stored in state 1, the second matched it in state 2."""
    guard_at, _ = _guard(body)
    assert guard_at < _offset(body, lambda c: "g_13InputState == 1" in c)
    assert guard_at < _offset(body, lambda c: "g_13InputState == 2" in c)


def test_cancel_still_aborts_despite_its_dot(body):
    """`.cancel` is the deliberate exception and it works by sitting ahead of
    the guard, so the ordering is load-bearing in both directions."""
    cancel_at = _offset(body, lambda c: 'equali(input, ".cancel")' in c)
    guard_at, _ = _guard(body)
    assert cancel_at < guard_at


def test_refusal_tells_the_captain_and_leaves_the_state_alone(body):
    """Refuse and keep waiting: the prompt must still be open afterwards, or a
    mistyped command would abort the entry a captain is in the middle of."""
    _, block = _guard(body)
    assert re.search(r"client_print\s*\(\s*id\s*,\s*print_chat", block), "captain is not told"
    for touched in ("g_13InputState", "g_13QueueIdFirst", "g_13QueueId", "g_is13CommunityMatch"):
        assert not re.search(rf"\b{touched}\b\s*(\[[^\]]*\])?\s*=", block), \
            f"the refusal assigns {touched}; it must leave the prompt open"
    assert "PLUGIN_HANDLED" in block, "the rejected command would be broadcast to chat"


def test_refusal_is_recoverable_from_a_match_log(body):
    """The only durable evidence a refusal happened. `input_state` is in it
    because that is what says which of the two inputs was rejected."""
    _, block = _guard(body)
    log = re.search(r"log_ktp\s*\(\s*\"([^\"]*)\"", block)
    assert log, "the refusal emits no log_ktp line"
    fmt = log.group(1)
    assert "event=" in fmt and "REJECTED" in fmt
    assert "input_state=" in fmt
