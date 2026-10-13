"""The analytics schema-decision gate, held to the two pull requests that created it.

THE CLOSING CONDITION IS THE FIXTURE, NOT THE GATE. #693 and #696 both passed full
CI green, so any gate that would also have passed them is not the gate -- and the
only way to know is to judge their REAL diffs and bodies. `tests/fixtures/
analytics_schema_gate/` holds them as GitHub served them: every changed file with
its `status` and its `patch` verbatim, and each body as written. Nothing in them is
reflowed, so a reader can diff a fixture against the API and see it is the same
payload.

#697, the repair, is the positive control in the other direction: same repository,
same file, same week, and it must PASS. A gate that fails all three is as useless as
one that passes all three, and only the pair of fixtures tells them apart.

WHAT WOULD HAVE PASSED THEM, measured off the fixtures rather than guessed. Both PRs
ship a `changelog.d/` fragment and both add real unit tests -- #696 adds five test
files -- so a gate keyed on "is there a changelog entry" or "did the tests move" is
satisfied by both and changes nothing. `test_the_cheap_signals_are_present_and_do_not
_satisfy_the_gate` pins exactly that, because those are the two gates somebody would
reach for first.

AND NOT THE ONE I ASSUMED. The gate requires the bump to appear as an ADDED line,
which reads like a reconstruction of how these two slipped through -- the constant's
line is two kilobytes of version history, so any hunk reaching line 116 carries it in
context. Measured: neither generator patch mentions `SCHEMA_VERSION` at all. Their
hunks start at line 58 and stop well short of it, so the context trap played no part.
It is a guard against a near miss that has not happened yet, and
`test_693_patch_does_not_mention_the_constant_at_all` keeps that straight so nobody
later cites it as the incident's mechanism.
"""
from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "tests" / "fixtures" / "analytics_schema_gate"
CHECKER = REPO / "scripts" / "check-analytics-schema-decision.py"


def _load():
    spec = importlib.util.spec_from_file_location("ktp_analytics_schema_gate", CHECKER)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gate = _load()


@pytest.fixture(scope="module")
def path_sets():
    return gate.output_path(str(REPO))


def pr(number: int):
    files = json.loads((FIXTURES / f"pr{number}-files.json").read_text(encoding="utf-8"))
    body = (FIXTURES / f"pr{number}-body.md").read_text(encoding="utf-8")
    return files, body


def answer(number: int, path_sets):
    files, body = pr(number)
    return gate.verdict(files, body, *path_sets)


# ----------------------------------------------------------- the closing condition

@pytest.mark.parametrize("number", [693, 696])
def test_the_two_merged_prs_that_caused_this_are_failed(number, path_sets):
    """The item's own closing condition: a gate that would have passed these is not
    the gate. Both merged green with full CI."""
    verdict, why, hits = answer(number, path_sets)
    assert verdict == "nothing", (
        f"#{number} changed the analytics output path, did not bump SCHEMA_VERSION and "
        f"declared nothing -- this gate answered {verdict!r} ({why})")
    assert "scripts/match_analytics.py" in hits


def test_697_the_repair_passes(path_sets):
    verdict, why, _ = answer(697, path_sets)
    assert verdict == "bumped", f"#697 bumps 30 -> 31; gate said {verdict!r} ({why})"
    assert "31" in why


@pytest.mark.parametrize("number", [693, 696])
def test_693_patch_does_not_mention_the_constant_at_all(number):
    """Keeps the gate's own story straight.

    The added-line requirement looks like a reconstruction of how these two slipped
    through. It is not: the constant appears nowhere in either generator patch, so
    the context trap is insurance against a future hunk, not the mechanism here."""
    files, _ = pr(number)
    patch = next(f["patch"] for f in files
                 if f["filename"] == "scripts/match_analytics.py")
    assert "SCHEMA_VERSION" not in patch
    assert not gate.ADDED_VERSION.search(patch)
    assert re.search(r"^@@ -58,", patch, re.M) or "@@ -" in patch


@pytest.mark.parametrize("number", [693, 696])
def test_the_cheap_signals_are_present_and_do_not_satisfy_the_gate(number, path_sets):
    """The two gates somebody would reach for first, refuted on the real payload.

    Both PRs carry a changelog fragment and both add unit tests. A gate keyed on
    either is green on both and the 237 reports still happen."""
    files, _ = pr(number)
    names = [f["filename"] for f in files]
    assert any(n.startswith("changelog.d/") for n in names), names
    assert any(n.startswith("tests/") for n in names), names
    assert answer(number, path_sets)[0] == "nothing"


@pytest.mark.parametrize("number", [693, 696, 697])
def test_every_fixture_is_the_payload_the_checker_reads(number):
    """Three fields, present on every file, or the fixture is not the subject."""
    files, body = pr(number)
    assert files and isinstance(files, list)
    for f in files:
        assert set(f) == {"filename", "status", "patch"}, f
        assert f["filename"]
    assert body.strip()


# -------------------------------------------------------------- the path derivation

def test_the_path_is_derived_and_contains_every_file_those_prs_touched(path_sets):
    """Both PRs' `scripts/` files must be in the path, and none of their tests or
    changelog fragments. This is the "key on the output path, not on scripts/**"
    requirement, measured both ways."""
    modules, data = path_sets
    path = modules | data
    for number in (693, 696):
        files, _ = pr(number)
        for f in files:
            name = f["filename"]
            if name.startswith("scripts/"):
                assert name in path, f"#{number} touched {name} and it is not in the path"
            else:
                assert name not in path, f"{name} must not be in the analytics path"


def test_the_generator_is_the_root(path_sets):
    modules, _ = path_sets
    assert gate.GENERATOR in modules


def test_the_serving_layer_is_out_of_path_by_construction(path_sets):
    """`analytics_report_dto.py` is reached from report_service/report_sync, never from
    the generator, so it falls outside the closure without an exemption. It is a
    decision -- a change there is re-read on every sync and nothing about it is skipped
    at schema parity -- and a test is the only thing that makes the decision visible if
    somebody later wires it into the generator."""
    modules, _ = path_sets
    assert "scripts/analytics_report_dto.py" not in modules


def test_the_config_data_inputs_are_found(path_sets):
    """Schema 22 and 27 were both bumps for a change to `config/map_coefficients.json`
    and to no code at all, so a path that cannot see it misses a fix class this
    repository has already shipped twice. flag_swing assembles that path through
    pathlib, so this also pins that the joined-literal reader works."""
    _, data = path_sets
    assert "config/map_coefficients.json" in data
    for p in data:
        assert (REPO / p).is_file()


def test_a_path_that_cannot_be_derived_refuses(tmp_path):
    with pytest.raises(gate.PathError):
        gate.output_path(str(tmp_path))


def test_a_closure_of_only_its_root_refuses(tmp_path):
    """The clean-zero shape: a generator whose imports read as empty would put every
    pull request out of scope and pass silently forever."""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "match_analytics.py").write_text(
        "SCHEMA_VERSION = 1\n", encoding="utf-8")
    with pytest.raises(gate.PathError):
        gate.output_path(str(tmp_path))


# ------------------------------------------------------------------ the two routes

def test_controls_pass_against_the_real_path(path_sets):
    """The same controls the CI step runs, so a break shows up here first."""
    assert gate.assert_discriminating(*path_sets) == []


def test_docs_only_and_test_only_are_out_of_scope(path_sets):
    for name in ("docs/DEPLOYING.md", "tests/unit/test_flag_swing.py",
                 "changelog.d/2026-10-12-x.md", "README.md",
                 "scripts/report_service.py"):
        got = gate.verdict([{"filename": name, "status": "modified",
                             "patch": "@@ -1 +1 @@\n-a\n+b\n"}], "", *path_sets)[0]
        assert got == "out-of-path", f"{name} answered {got!r}"


@pytest.mark.parametrize("heading", [
    "## Analytics schema version: values unchanged",
    "### Schema version",
    "## schema bump",
    "## Analytics SCHEMA VERSION",
])
def test_qualifying_headings_open_a_declaration(heading, path_sets):
    body = f"{heading}\n\nA pure rename; stored values are unchanged.\n"
    got, why, _ = gate.verdict(
        [{"filename": gate.GENERATOR, "status": "modified",
          "patch": "@@ -1 +1 @@\n-a\n+b\n"}], body, *path_sets)
    assert got == "declared", why


@pytest.mark.parametrize("heading", [
    "## Schema",            # no version/bump word
    "## Notes",
    "## Scope and safety",
    "## Version",           # no schema word
])
def test_non_qualifying_headings_do_not(heading, path_sets):
    body = f"{heading}\n\nA pure rename; stored values are unchanged.\n"
    got, why, _ = gate.verdict(
        [{"filename": gate.GENERATOR, "status": "modified",
          "patch": "@@ -1 +1 @@\n-a\n+b\n"}], body, *path_sets)
    assert got == "nothing", f"{heading!r} should not qualify"
    assert why and "no heading here qualifies" in why, why


def test_a_section_survives_a_sub_heading(path_sets):
    body = ("## Analytics schema version\n\n"
            "### Why\n\nA rename only, so values do not change.\n\n"
            "## Something else\n\nunrelated\n")
    got, _, _ = gate.verdict(
        [{"filename": gate.GENERATOR, "status": "modified",
          "patch": "@@ -1 +1 @@\n-a\n+b\n"}], body, *path_sets)
    assert got == "declared"


def test_a_declaration_after_the_section_closes_is_not_read(path_sets):
    body = ("## Analytics schema version\n\nTBD.\n\n"
            "## Notes\n\nStored values are unchanged.\n")
    got, _, _ = gate.verdict(
        [{"filename": gate.GENERATOR, "status": "modified",
          "patch": "@@ -1 +1 @@\n-a\n+b\n"}], body, *path_sets)
    assert got == "nothing"


def test_a_bump_outranks_a_missing_declaration(path_sets):
    patch = "@@ -116 +116 @@\n-SCHEMA_VERSION = 30  # h\n+SCHEMA_VERSION = 31  # h; 31: x\n"
    got, why, _ = gate.verdict(
        [{"filename": gate.GENERATOR, "status": "modified", "patch": patch}],
        "", *path_sets)
    assert got == "bumped" and "30" in why and "31" in why


def test_a_bump_in_another_file_does_not_count(path_sets):
    """Only the generator's own constant is the generator's "already current" test."""
    got, _, _ = gate.verdict(
        [{"filename": "scripts/flag_swing.py", "status": "modified",
          "patch": "@@ -1 +1 @@\n-SCHEMA_VERSION = 1\n+SCHEMA_VERSION = 2\n"}],
        "", *path_sets)
    assert got == "nothing"


def test_a_lowered_version_is_a_finding_not_a_pass(path_sets):
    got, why, _ = gate.verdict(
        [{"filename": gate.GENERATOR, "status": "modified",
          "patch": "@@ -116 +116 @@\n-SCHEMA_VERSION = 30\n+SCHEMA_VERSION = 29\n"}],
        "", *path_sets)
    assert got == "lowered" and "re-skips" in why


def test_a_suppressed_patch_refuses_rather_than_guessing(path_sets):
    got, why, _ = gate.verdict(
        [{"filename": gate.GENERATOR, "status": "modified", "patch": None}],
        "", *path_sets)
    assert got == "suppressed" and "no patch" in why


def test_a_removed_generator_does_not_read_as_suppressed(path_sets):
    got, _, _ = gate.verdict(
        [{"filename": gate.GENERATOR, "status": "removed", "patch": None}],
        "", *path_sets)
    assert got == "out-of-path"


def test_a_data_input_change_alone_needs_a_decision(path_sets):
    _, data = path_sets
    got, _, hits = gate.verdict(
        [{"filename": "config/map_coefficients.json", "status": "modified",
          "patch": "@@ -1 +1 @@\n-1\n+2\n"}], "", *path_sets)
    assert got == "nothing"
    assert hits == ["config/map_coefficients.json"]


# ------------------------------------------------------------------- the exit codes

def _run(args, cwd=None):
    """encoding is not optional. The checker prints this estate's glyphs; a Windows
    default of cp1252 raises in the reader thread and the test fails for the wrong
    reason, which is how this helper first looked."""
    import subprocess
    import sys
    return subprocess.run([sys.executable, "-I", str(CHECKER)] + args,
                          cwd=str(cwd or REPO), capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


@pytest.mark.parametrize("number,code", [(693, 1), (696, 1), (697, 0)])
def test_exit_codes_end_to_end(number, code):
    r = _run(["--root", str(REPO),
              "--files-json", str(FIXTURES / f"pr{number}-files.json"),
              "--body-file", str(FIXTURES / f"pr{number}-body.md"),
              "--pr", str(number)])
    assert r.returncode == code, r.stdout + r.stderr
    assert "controls:" in r.stdout


def test_a_pass_says_it_is_not_a_correctness_claim():
    """The card's second design trap, pinned where it cannot quietly be dropped: a
    green here must not be readable as "the numbers are right"."""
    r = _run(["--root", str(REPO),
              "--files-json", str(FIXTURES / "pr697-files.json"),
              "--body-file", str(FIXTURES / "pr697-body.md"), "--pr", "697"])
    assert r.returncode == 0
    assert "not evidence the numbers are right" in r.stdout


def test_no_subject_is_exit_2():
    r = _run(["--root", str(REPO)])
    assert r.returncode == 2
    assert "measured nothing" in r.stdout


def test_print_path_lists_both_legs():
    r = _run(["--root", str(REPO), "--print-path"])
    assert r.returncode == 0
    assert "module  scripts/match_analytics.py" in r.stdout
    assert "data    config/map_coefficients.json" in r.stdout
