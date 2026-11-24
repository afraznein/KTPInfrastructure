"""The two workflows have to keep opposite halves of one contract.

smoke-callable.yml is reusable, so its red check lands on the CALLER's PR. It
scopes assert-no-failed to the change under test. That is only safe because
publish-base-image.yml runs the same check UNSCOPED before it pushes, so the
class the caller stops failing on still fails somewhere we own.

Break either half and the gate quietly stops checking, which no runtime test
would notice. These assertions are structural on purpose.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
SMOKE = WORKFLOWS / "smoke-callable.yml"
PUBLISH = WORKFLOWS / "publish-base-image.yml"

BOOT_STEP = "Boot, wait, and assert (with single retry on fast-path)"


def _steps(path: Path, job: str) -> list[dict]:
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    steps = doc["jobs"][job]["steps"]
    assert steps, f"{path.name}:{job} has no steps — wrong job name?"
    return steps


def _named_step(path: Path, job: str, name: str) -> dict:
    for step in _steps(path, job):
        if step.get("name") == name:
            return step
    raise AssertionError(f"{path.name} has no step named {name!r}")


@pytest.fixture(scope="module")
def boot_script() -> str:
    return _named_step(SMOKE, "smoke", BOOT_STEP)["run"]


class TestCallerFacingGateIsScoped:
    def test_it_passes_the_under_test_names_through(self, boot_script):
        step = _named_step(SMOKE, "smoke", BOOT_STEP)
        assert step["env"]["ASSERT_PLUGIN"] == "${{ inputs.assert_plugin }}"
        assert step["env"]["ASSERT_MODULE"] == "${{ inputs.assert_module }}"
        assert "--under-test" in boot_script

    def test_it_keeps_an_unscoped_branch_for_callers_that_name_nothing(self, boot_script):
        """A caller asserting nothing must not get a gate that excuses
        everything: with UNDER_TEST empty the call has to drop the flag."""
        scoped = [
            line for line in boot_script.splitlines() if "--under-test" in line
        ]
        assert scoped, "no scoped invocation at all"
        assert 'if [ -n "$UNDER_TEST" ]; then' in boot_script
        assert boot_script.count("assert-no-failed") >= 2, (
            "expected both a scoped and an unscoped assert-no-failed call"
        )

    def test_exit_3_is_reported_and_survived_not_ignored(self, boot_script):
        assert "report_image_fault" in boot_script
        assert '"$RC" -eq 3' in boot_script
        # The warning has to name the owner, or a caller has nowhere to go.
        assert "afraznein/KTPInfrastructure" in boot_script
        assert "GITHUB_STEP_SUMMARY" in boot_script

    def test_a_real_regression_still_ends_the_job(self, boot_script):
        assert "::error::Retry also failed" in boot_script
        assert boot_script.rstrip().endswith("exit 1")


class TestOwningWorkflowKeepsTheStrictCheck:
    def test_it_asserts_no_failed_without_scoping(self):
        steps = _steps(PUBLISH, "publish")
        runs = [s.get("run", "") for s in steps]
        strict = [r for r in runs if "assert-no-failed" in r]
        assert strict, "publish-base-image.yml no longer boots and checks the image"
        for r in strict:
            assert "--under-test" not in r, (
                "the publishing gate must stay unscoped — every plugin in the "
                "image it builds is ours"
            )

    def test_the_check_runs_before_the_push(self):
        steps = _steps(PUBLISH, "publish")
        check = next(
            i for i, s in enumerate(steps) if "assert-no-failed" in s.get("run", "")
        )
        push = next(
            i for i, s in enumerate(steps) if "docker push" in s.get("run", "")
        )
        assert check < push, (
            f"boot check is step {check}, push is step {push} — a failing image "
            "would already be on :latest by the time anything noticed"
        )

    def test_it_has_the_python_the_check_needs(self):
        uses = [s.get("uses", "") for s in _steps(PUBLISH, "publish")]
        assert any(u.startswith("actions/setup-python@") for u in uses)


def _logical_lines(script: str) -> list[str]:
    """Shell lines with backslash continuations joined, so a wrapped command is one line."""
    out, cur = [], ""
    for line in script.splitlines():
        if line.rstrip().endswith("\\"):
            cur += line.rstrip()[:-1] + " "
            continue
        out.append(cur + line)
        cur = ""
    if cur:
        out.append(cur)
    return out


class TestTheServerCanOpenItsSocket:
    """ubuntu-latest moved to a docker whose default seccomp profile refuses the i386
    socketcall multiplexer, so hlds died before any assertion ran and every call of this
    workflow went green on an env-fault exemption that asserted nothing."""

    REPO = Path(__file__).resolve().parents[2]

    def test_every_boot_carries_the_seccomp_override(self, boot_script):
        ups = [l for l in _logical_lines(boot_script) if "docker compose" in l and " up " in l]
        assert ups, "no `docker compose ... up` in the boot step -- wrong step?"
        for line in ups:
            assert '-f "$SMOKE_COMPOSE_OVERRIDE"' in line, (
                f"a boot without the i386 seccomp profile dies on ENOSYS: {line.strip()}"
            )

    def test_the_override_names_a_real_profile(self, boot_script):
        rel = "ci/seccomp/lane-b-i386.json"
        assert f'SMOKE_SECCOMP="$PWD/{rel}"' in boot_script
        prof = json.loads((self.REPO / rel).read_text(encoding="utf-8"))
        subs = [s for a in prof["archMap"] for s in a.get("subArchitectures", [])]
        assert "SCMP_ARCH_X86" in subs, "without the x86 sub-arch the profile covers nothing for i386"
        assert '"seccomp=%s"' in boot_script and "security_opt" in boot_script

    def test_a_missing_profile_fails_the_step(self, boot_script):
        lines = boot_script.splitlines()
        i = next(n for n, l in enumerate(lines) if "json.load" in l and "SMOKE_SECCOMP" in l)
        assert lines[i].lstrip().startswith("if ! ")
        assert "exit 1" in "\n".join(lines[i:i + 4])

    def test_no_unescaped_backtick_inside_a_double_quoted_echo(self, boot_script):
        """An unescaped backtick in `echo "..."` is command substitution: the summary
        ran `main` as a command and printed its error instead of the fence."""
        bad = [
            l.strip() for l in boot_script.splitlines()
            if l.lstrip().startswith('echo "') and re.search(r"(?<!\\)`", l)
        ]
        assert not bad, f"unescaped backtick(s) in a double-quoted echo: {bad}"
