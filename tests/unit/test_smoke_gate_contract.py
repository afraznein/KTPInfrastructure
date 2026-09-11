"""The two workflows have to keep opposite halves of one contract.

smoke-callable.yml is reusable, so its red check lands on the CALLER's PR. It
scopes assert-no-failed to the change under test. That is only safe because
publish-base-image.yml runs the same check UNSCOPED before it pushes, so the
class the caller stops failing on still fails somewhere we own.

Break either half and the gate quietly stops checking, which no runtime test
would notice. These assertions are structural on purpose.
"""

from __future__ import annotations

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
