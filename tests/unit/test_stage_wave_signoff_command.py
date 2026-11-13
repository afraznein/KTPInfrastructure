"""The morning-after command stage-wave.py prints is the full verify, and it can run.

The wave sign-off is whatever an operator copies out of this epilogue. It used to
print a bare `ktp-verify-deploy.py --check-runtime`, which on a workstation has
neither credential and refuses with exit 4 -- so the runtime leg only ran for
someone who remembered the wrapper, and `--include-engine` only on engine waves.
These pin the printed command to the one that reaches every leg: through the
wrapper, with every flag the verify has, each of which the verify still accepts.
"""

from __future__ import annotations

import importlib.util
import os
import re
import shlex
import sys
import types

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPTS = os.path.join(_ROOT, "scripts")


def _load(mod_name, filename):
    spec = importlib.util.spec_from_file_location(mod_name, os.path.join(_SCRIPTS, filename))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


if "paramiko" not in sys.modules:
    stub = types.ModuleType("paramiko")
    stub.SSHClient = object
    stub.AutoAddPolicy = object
    sys.modules["paramiko"] = stub

wl = _load("ktp_wave_ledger", "ktp-wave-ledger.py")
sw = _load("stage_wave", "stage-wave.py")
rfs = _load("run_fleet_script", "run-fleet-script.py")


def _commands():
    """Each printed line that is a command, split into argv."""
    out = []
    for line in sw.morning_after_commands():
        text = line.strip()
        if text.startswith(sw.SIGNOFF_WRAPPER):
            out.append(shlex.split(text))
    return out


def _command_for(script):
    hits = [argv for argv in _commands() if script in argv]
    assert len(hits) == 1, (script, sw.morning_after_commands())
    return hits[0]


def _flags_accepted_by(filename):
    with open(os.path.join(_SCRIPTS, filename), encoding="utf-8") as fh:
        return set(re.findall(r'add_argument\(\s*"(--[a-z-]+)"', fh.read()))


def test_wrapper_named_in_the_hint_is_the_real_one():
    argv = shlex.split(sw.SIGNOFF_WRAPPER)
    assert argv[-1] == "scripts/run-fleet-script.py"
    assert os.path.isfile(os.path.join(_ROOT, *argv[-1].split("/")))


def test_every_printed_command_goes_through_the_wrapper():
    for line in sw.morning_after_commands():
        text = line.strip()
        for script in ("ktp-verify-deploy.py", "ktp-wave-ledger.py"):
            if text.startswith(script):
                pytest.fail("bare %s in the hint -- it refuses without the wrapper: %r"
                            % (script, line))


def test_printed_scripts_are_on_the_wrapper_allowlist():
    for argv in _commands():
        script = argv[len(shlex.split(sw.SIGNOFF_WRAPPER))]
        assert script in rfs.RUNNABLE, script


def test_verify_command_is_the_full_verify():
    argv = _command_for("ktp-verify-deploy.py")
    assert "--check-runtime" in argv
    assert "--include-engine" in argv
    i = argv.index("--scope")
    assert argv[i + 1] == "all"


def test_verify_gets_the_rcon_credential_through_that_wrapper():
    # The point of printing the wrapper: --check-runtime refuses without rcon.
    assert "ktp-verify-deploy.py" in rfs.NEEDS_RCON


def test_every_printed_verify_flag_still_exists():
    accepted = _flags_accepted_by("ktp-verify-deploy.py")
    assert {"--check-runtime", "--include-engine", "--scope"} <= accepted  # control
    for tok in _command_for("ktp-verify-deploy.py"):
        if tok.startswith("--"):
            assert tok in accepted, tok


def test_reconcile_is_printed_and_is_a_real_subcommand():
    argv = _command_for("ktp-wave-ledger.py")
    assert argv[-1] == "reconcile"
    with open(os.path.join(_SCRIPTS, "ktp-wave-ledger.py"), encoding="utf-8") as fh:
        assert 'add_parser("reconcile"' in fh.read()


def test_hint_does_not_depend_on_the_wave_kind():
    # The engine leg is always on: a plugin wave's sign-off must still see an
    # out-of-band engine push. The function takes no wave-kind argument at all.
    assert sw.morning_after_commands.__code__.co_argcount == 0
