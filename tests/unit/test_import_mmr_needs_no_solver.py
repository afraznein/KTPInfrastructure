"""`import-mmr` must run on a box that has no rating solver installed.

The ladder runs in CI; the data server holds no `openskill` and no package
manager to install one, by decision -- the import command exists precisely so
the box never needs the solver. KTPInfrastructure #495 then put the methodology
guards in a module that imports `ladder`, the command imported it transitively,
and the operator's run died with ModuleNotFoundError. Nothing noticed, because
CI installs openskill and the box is where the command runs.

So this does not read imports and judge them. It derives the modules
`cmd_import_mmr` imports from its own source, then imports them in a child
interpreter with `openskill` made unimportable and runs the guards there. A
lazy import inside a callee, a re-coupled schema module, or a caller switched
back to `methodology` all fail it the same way.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SOURCE = REPO / "scripts" / "report_service.py"

# Runs in the child: block the solver, import what the command imports, exercise
# every guard it reaches. Reports rather than asserts, so a failure here arrives
# as a message instead of a traceback with no context.
CHILD = r'''
import importlib, json, sys


class NoSolver:
    """A box that has never had openskill installed, wherever this runs."""

    def find_spec(self, fullname, path=None, target=None):
        if fullname == "openskill" or fullname.startswith("openskill."):
            raise ModuleNotFoundError("No module named %r" % fullname, name=fullname)
        return None


sys.meta_path.insert(0, NoSolver())

repo, names = sys.argv[1], [n for n in sys.argv[2].split(",") if n]
sys.path[:0] = [repo, repo + "/scripts", repo + "/scripts/mmr"]

out = {"solver_blocked": False, "imported": [], "guarded_kinds": [],
       "toothless_guards": [], "error": None}
try:
    importlib.import_module("openskill")
except ModuleNotFoundError:
    out["solver_blocked"] = True

try:
    for name in names:
        module = importlib.import_module(name)
        out["imported"].append(name)
        guard = getattr(module, "validate_for_import", None)
        if guard is None:
            continue
        kind = getattr(module, "AGGREGATE_KIND", name)
        out["guarded_kinds"].append(kind)
        if not guard(None):
            out["toothless_guards"].append(kind)
except BaseException as exc:
    out["error"] = "%s: %s" % (type(exc).__name__, exc)

print(json.dumps(out))
'''


def _imports_inside(function: ast.FunctionDef) -> list[str]:
    names: set[str] = set()
    for node in ast.walk(function):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            names.add(node.module)
    return sorted(names)


def _cmd_import_mmr() -> ast.FunctionDef:
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"), str(SOURCE))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "cmd_import_mmr":
            return node
    raise AssertionError(f"cmd_import_mmr is not a top-level function of {SOURCE.name}")


def _run_without_the_solver(names: list[str]) -> dict:
    proc = subprocess.run([sys.executable, "-c", CHILD, REPO.as_posix(), ",".join(names)],
                          capture_output=True, text=True)
    assert proc.returncode == 0, f"probe itself failed: {proc.stderr}"
    return json.loads(proc.stdout)


def test_the_import_command_runs_where_no_solver_is_installed():
    names = _imports_inside(_cmd_import_mmr())
    assert names, "cmd_import_mmr imports nothing; the probe would prove nothing"

    result = _run_without_the_solver(names)

    # The control: everything below is vacuous if the child could import the
    # solver anyway, which it can on any runner that pip-installed it.
    assert result["solver_blocked"], (
        "openskill was importable in the child, so this test proves nothing "
        "about a box without it")

    assert result["error"] is None, (
        "cmd_import_mmr imports %s, and reaching them needs the OpenSkill solver: %s. "
        "The data server has none and is not getting one -- the import command is what "
        "lets the ladder stay in CI. Move whatever the command needs into a module that "
        "does not import `ladder`." % (names, result["error"]))

    assert sorted(result["guarded_kinds"]) == ["mmr_openskill", "rating_methodology"], (
        "both aggregate kinds' guards must be reachable without the solver; reached %s"
        % result["guarded_kinds"])

    assert not result["toothless_guards"], (
        "%s accepted a payload of None, so it guards the production write with nothing"
        % result["toothless_guards"])
