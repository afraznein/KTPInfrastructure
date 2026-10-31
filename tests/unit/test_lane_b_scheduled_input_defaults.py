"""An input DEFAULT does not reach a scheduled run, so the `env:` fallback is it.

`inputs` is empty on a `schedule` event. Only `workflow_dispatch` and
`workflow_call` populate it, so a `default:` on an input is invisible to the
nightly, and the `env:` expression's own fallback is the entire value the
nightly sees. Every value in Lane B's `env:` block carries a literal fallback
for exactly that reason.

`LANE_B_SECCOMP` did not. It was added as `inputs.seccomp || ''` while the input
was an experiment whose default was also `''`; when the narrow i386 seccomp
profile became the input default, the env fallback stayed empty. So the change
that makes `hlds` boot at all on the current hosted-runner kernel armed every
trigger except the one nobody dispatches, and the nightly kept dying at boot
with `socket: Function not implemented` for five consecutive nights while the
fix was on `main` and verified present in both input blocks.

Why a test and not a comment: the two halves live forty lines apart, the symptom
is a container that cannot open a UDP socket, and there is no surface on which a
correct input default and an empty env fallback look different.

Regex rather than a YAML parse on purpose -- `tier 1` CI installs pytest,
jsonschema, paramiko and openskill, and an `importorskip('yaml')` would make
this file skip silently in the one job that runs it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/lane-b-stats-e2e.yml"
PROFILE = "ci/seccomp/lane-b-i386.json"

# An input declaration: a 6-space-indented name, then its 8-space body.
_INPUT_RE = re.compile(
    r"^      (?P<name>[a-z][a-z0-9_]*):\n(?P<body>(?:^ {8}.*\n|^\n)*)",
    re.MULTILINE,
)
# `default: <value>` inside one of those bodies, quoted or bare.
_DEFAULT_RE = re.compile(r"^ {8}default:[ \t]*(?P<value>.*?)[ \t]*$", re.MULTILINE)
# A job-level env assignment whose value is an expression.
_ENV_RE = re.compile(
    r"^      (?P<name>[A-Z][A-Z0-9_]*):[ \t]*\$\{\{(?P<expr>.*?)\}\}[ \t]*$",
    re.MULTILINE,
)


def _text() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def _input_defaults() -> dict[str, set[str]]:
    """input name -> every declared default across both input blocks.

    Union, not last-wins: a non-empty default in either block means a caller can
    be given one, and the question here is only whether the nightly gets it.
    """
    out: dict[str, set[str]] = {}
    for m in _INPUT_RE.finditer(_text()):
        found = _DEFAULT_RE.search(m.group("body"))
        if found:
            raw = found.group("value").strip()
            if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "'\"":
                raw = raw[1:-1]
            out.setdefault(m.group("name"), set()).add(raw)
    return out


def _env_exprs() -> dict[str, str]:
    return {m.group("name"): m.group("expr").strip()
            for m in _ENV_RE.finditer(_text())}


# ----------------------------------------------------------------- controls
def test_the_workflow_parses_into_inputs_and_env() -> None:
    """Without this, every assertion below passes on an empty dict."""
    assert WORKFLOW.is_file()
    defaults = _input_defaults()
    env = _env_exprs()
    # `lane` is the proof that the union is the right reading: the two input
    # blocks declare DIFFERENT defaults for it (`workflow_call` corpus,
    # `workflow_dispatch` full), and the nightly gets neither -- it gets the
    # env fallback, which is `full`, which is what the job name says.
    assert defaults.get("lane") == {"corpus", "full"}, defaults.get("lane")
    assert re.search(r"\|\|\s*'full'", env["LANE"]), env["LANE"]
    assert "LANE_B_SECCOMP" in env
    assert "LANE" in env
    assert len(defaults) >= 5 and len(env) >= 8


def test_an_empty_default_is_recognised_as_empty() -> None:
    """`engine_ref` is the deliberate empty-default case -- its env fallback is
    allowed to be '' because nothing is being lost. If the parse read it as
    non-empty, the rule below would flag a correct line and get relaxed."""
    assert _input_defaults().get("engine_ref") == {""}


# -------------------------------------------------------------- the property
def test_no_env_fallback_discards_a_non_empty_input_default() -> None:
    defaults = _input_defaults()
    env = _env_exprs()
    offenders = []
    for name, expr in env.items():
        ref = re.search(r"inputs\.([a-z][a-z0-9_]*)", expr)
        if not ref:
            continue
        declared = {d for d in defaults.get(ref.group(1), set()) if d}
        if not declared:
            continue
        # Branching on the event is the other correct shape, and the only one
        # available when '' is itself a meaningful value a caller may pass.
        if "github.event_name" in expr:
            continue
        if re.search(r"\|\|\s*''\s*$", expr):
            offenders.append((name, ref.group(1), sorted(declared), expr))
    assert not offenders, (
        "these env values fall back to '' while the input declares a real "
        "default, so a scheduled run gets neither: %r" % (offenders,)
    )


def test_the_scheduled_seccomp_value_is_the_profile_the_inputs_declare() -> None:
    """Three copies of one path. A fix that armed two of them is what this file
    exists to catch, so they are asserted equal rather than merely present."""
    expr = _env_exprs()["LANE_B_SECCOMP"]
    assert "github.event_name == 'schedule'" in expr
    assert PROFILE in expr
    assert _input_defaults()["seccomp"] == {PROFILE}
    assert (ROOT / PROFILE).is_file()


@pytest.mark.parametrize("name", ["LANE", "MAP_NAME", "PLAY_SECONDS",
                                  "SHOT_DETAIL", "SHOT_DETAIL_TYPES"])
def test_the_values_that_already_had_literal_fallbacks_still_do(name) -> None:
    """The regression would be silent in the other direction too: dropping one
    of these to `inputs.x` alone gives the nightly an empty string."""
    expr = _env_exprs()[name]
    assert re.search(r"\|\|\s*'[^']+'", expr), expr
