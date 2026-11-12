"""Tier-2 behaviour: the 12man Queue-ID prompt refuses a chat command.

`test_queue_id_command_refusal.py` holds the guard's ORDER in the source. This
file runs it: `amx_ktp_test_13_queue_id_input <1|2> <input>` (KTPMatchHandler#64,
test-mode build only) puts the prompt in an input state, calls the real
`handle_13_queue_id_input`, and prints the state it left behind. A refusal
leaves the state where it was and stores nothing; an accepted entry moves it.

The accepted-entry cases are the controls. Without them, "state unchanged"
would also be what a handler that never ran looks like.

Armed by capability, not by version: the rcon carries no version bump of its
own, so the gate is whether the pinned source this workflow compiles registers
it. Below that pin every test here skips with the reason; at or past it they run.
"""
from __future__ import annotations

import re

import pytest

from .test_queue_id_command_refusal import _resolve_source

_RCON = "amx_ktp_test_13_queue_id_input"
_READBACK = re.compile(
    r"KTP_TEST_13_QUEUE_ID: ok input_state=(?P<state>\d+) first=(?P<first>\S*) queue_id=(?P<qid>\S*)"
)


@pytest.fixture(scope="module", autouse=True)
def _pinned_source_has_the_rcon():
    src = _resolve_source()
    if f'"{_RCON}"' not in src.read_text(encoding="utf-8", errors="replace"):
        pytest.skip(f"{_RCON} is not registered in the pinned KTPMatchHandler ({src}); "
                    "it lands with KTPMatchHandler#64")


def _enter(hlds, state: int, text: str) -> dict:
    out = hlds.rcon(f'{_RCON} {state} "{text}"')
    m = _READBACK.search(out)
    assert m, f"no readback from {_RCON} (test-mode build not loaded?): {out!r}"
    return {"state": int(m["state"]), "first": m["first"], "qid": m["qid"]}


@pytest.fixture()
def prompt(hlds):
    yield lambda state, text: _enter(hlds, state, text)
    # A mismatch re-arms the 60 s timeout; close the prompt rather than leave it
    # to fire into the next test's log.
    hlds.rcon("amx_ktp_test_reset")


# ---------------------------------------------------------------------------
# Controls: an ordinary Queue ID is accepted in both states.
# ---------------------------------------------------------------------------

def test_a_queue_id_is_accepted_as_the_first_entry(prompt):
    assert prompt(1, "7102") == {"state": 2, "first": "7102", "qid": ""}


def test_a_queue_id_in_the_confirm_state_reaches_the_comparison(prompt):
    # The rcon enters state 2 with an empty first entry, so this is a mismatch,
    # which drops back to state 1. It proves the input got past the guard.
    assert prompt(2, "7102") == {"state": 1, "first": "", "qid": ""}


# ---------------------------------------------------------------------------
# The refusal
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("state", [1, 2])
@pytest.mark.parametrize("text", [".confirm", "/confirm", ".ready", "/12man"])
def test_a_prefixed_command_is_refused_in_both_states(prompt, state, text):
    assert prompt(state, text) == {"state": state, "first": "", "qid": ""}


@pytest.mark.parametrize("state", [1, 2])
@pytest.mark.parametrize("text", ["confirm", "CONFIRM", "ready", "yes"])
def test_a_bare_command_word_is_refused_in_both_states(prompt, state, text):
    assert prompt(state, text) == {"state": state, "first": "", "qid": ""}


def test_a_word_that_only_starts_like_a_command_is_accepted(prompt):
    # The list matches whole words: "confirmed" is not "confirm".
    assert prompt(1, "confirmed") == {"state": 2, "first": "confirmed", "qid": ""}


@pytest.mark.parametrize("text", ["cancel", ".cancel"])
def test_cancel_still_closes_the_prompt(prompt, text):
    # ".cancel" is the one dotted input that must NOT be refused: it sits ahead of the guard.
    assert prompt(2, text) == {"state": 0, "first": "", "qid": ""}
