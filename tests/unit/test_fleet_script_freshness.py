"""The freshness guard on the fleet-writing entry points.

Two things are locked here.

FIRST, the guard behaves. Every case runs against a real pair of git repos built
in a tmpdir -- an "upstream" and a clone of it -- because the whole point is that
git answers the question, not a hash recomputed by hand. The checkouts on this
estate set `core.autocrlf=input` and carry a `.gitattributes`, so a file whose
stored blob holds CRLF hashes differently from its bytes on disk and a hand-rolled
comparison reports drift on files that are identical. `git diff` against the ref
is the primitive for that reason, and a fixture that stubbed git would prove
nothing about it.

SECOND, the coverage does not rot. Every `scripts/*.py` that imports paramiko is
either guarded or carries a written reason not to be. A new one that is neither
fails here, which is the half an allow-list gets wrong: a list of what IS covered
is blind to the thing that was never added to it. A declared name that no longer
exists fails too, so the reasons cannot outlive their scripts.

The boundary the exempt list draws is not squeamishness. `audit-fleet-drift.py`
and `precache_audit.py` run from cron out of `/opt/ktp-infra`, a checkout that is
deliberately never auto-pulled. A fail-closed gate there would turn a stale-data
problem into a no-data problem: the weekly audit would stop producing anything,
and an audit that does not run is the failure this guard exists to prevent, one
level up. Guarded scripts are the ones a person invokes from a working checkout.
"""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPTS = os.path.join(_ROOT, "scripts")


def _load_guard():
    path = os.path.join(_SCRIPTS, "ktp_script_freshness.py")
    spec = importlib.util.spec_from_file_location("ktp_script_freshness_undertest", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


guard = _load_guard()


# --------------------------------------------------------------------------
# Coverage: who must carry the guard, and why the rest need not.
# --------------------------------------------------------------------------

# Invoked by a person from a working checkout, and either changes remote state or
# produces the record/verdict a wave is judged by.
GUARDED = {
    "stage-wave.py": "stages a wave to all 24 instances",
    "deploy-to-fleet.py": "the raw .new push underneath stage-wave, also run directly",
    "ktp-wave-ledger.py": "writes the ledger reconcile is blind without",
    "ktp-verify-deploy.py": "issues the 24/24 verdict a wave is judged by",
    "deploy-restart-script.py": "replaces the nightly restart script on every game host",
    "stage-mp-logecho.py": "edits dodserver.cfg on every instance",
    "stage-runner.py": "stages artifacts onto the Tier-2 runner",
    "sync-runner-stack.py": "overwrites the Tier-2 runner stack",
    "install-game-files-manifest.py":
        "replaces the manifest every AC client is checked against; a copy predating "
        "the severity gate would install a widening and report success",
}

# Reached over SSH, but not from a working checkout -- so a gate keyed on
# `origin/main` would refuse forever rather than catch anything.
EXEMPT = {
    "audit-fleet-drift.py":
        "weekly cron on the data server out of /opt/ktp-infra, which is "
        "deliberately not auto-pulled; refusing would silence the audit",
    "precache_audit.py":
        "weekly cron (scripts/cron.d/ktp-precache-audit-weekly), same checkout",
    "hltv-demo-renamer.py":
        "a systemd daemon deployed to /home/hltvserver, not run from a checkout",
    "audit_redact.py":
        "library; no entry point to gate",
    "build-game-files-manifest.py":
        "builds a local manifest; its remote reads do not change fleet state",
    "audit-distribute-drift.py":
        "read-only drift probe; also runs as a fleet-audit step, where the "
        "checkout IS the reviewed commit",
    "audit-config-key-drift.py":
        "read-only drift probe, same class and same deployment as "
        "audit-distribute-drift.py: it opens the distribute tree for reading, "
        "cats configs on the instances, and runs as a fleet-audit step where "
        "the checkout IS the reviewed commit",
    "ktp-lan-web-drift.py": "read-only drift probe",
    "ktp-net-profile.py": "read-only netcode probe",
    "ktp-restart-drift.py": "read-only drift probe",
    "ktp-tier2-stack-drift.py": "read-only drift probe",
    "ktp-timezone-drift.py": "read-only drift probe",
    "prep-lan-artifacts.py": "LAN box prep, run against a venue host, not the fleet",
    "verify-veto-week-maps.py": "read-only map presence check",
}


def _paramiko_scripts():
    found = []
    for name in sorted(os.listdir(_SCRIPTS)):
        if not name.endswith(".py"):
            continue
        with open(os.path.join(_SCRIPTS, name), encoding="utf-8", errors="replace") as fh:
            if re.search(r"^\s*import paramiko\b", fh.read(), re.M):
                found.append(name)
    return found


def test_every_ssh_script_is_classified():
    """A new fleet script is covered or it is refused -- never merely absent."""
    classified = set(GUARDED) | set(EXEMPT)
    unclassified = [n for n in _paramiko_scripts() if n not in classified]
    assert not unclassified, (
        "these scripts reach a KTP host over SSH and are in neither GUARDED nor "
        "EXEMPT in this file: %s. Wire ktp_script_freshness.require_current into "
        "each, or add it to EXEMPT with the reason it cannot be gated."
        % ", ".join(unclassified)
    )


def test_no_classification_outlives_its_script():
    """So a reason cannot linger after the thing it excused is gone."""
    missing = [n for n in sorted(set(GUARDED) | set(EXEMPT))
               if not os.path.exists(os.path.join(_SCRIPTS, n))]
    assert not missing, "classified but not on disk: %s" % ", ".join(missing)


@pytest.mark.parametrize("name", sorted(GUARDED))
def test_guarded_scripts_call_the_guard(name):
    with open(os.path.join(_SCRIPTS, name), encoding="utf-8") as fh:
        text = fh.read()
    assert "ktp_script_freshness" in text, f"{name} does not load the guard module"
    calls = re.findall(r"^(\s*)\S*require_current\(", text, re.M)
    # At least one call, and indented: at module scope it would fire on import,
    # which breaks every test that loads these modules to read a constant.
    assert calls, f"{name} loads the guard but never calls require_current()"
    assert any(indent for indent in calls), (
        f"{name} calls require_current() at module scope; it belongs inside main()"
    )


@pytest.mark.parametrize("name", sorted(GUARDED))
def test_the_guard_runs_after_argument_parsing(name):
    """`--help` must answer without a network, and a --dry-run must not."""
    with open(os.path.join(_SCRIPTS, name), encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    parse = next(i for i, ln in enumerate(lines) if "parse_args(" in ln)
    call = next(i for i, ln in enumerate(lines) if "require_current(" in ln and "import" not in ln)
    assert call > parse, (
        f"{name} gates before parse_args, so --help would need the network"
    )


# --------------------------------------------------------------------------
# Behaviour, against real git repos.
# --------------------------------------------------------------------------

_OLD = '''#!/usr/bin/env python3
"""A fleet writer."""
import argparse


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hosts")
    return ap.parse_args()
'''

_NEW = '''#!/usr/bin/env python3
"""A fleet writer."""
import argparse


def pull_live(host, dest):
    return dest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hosts")
    ap.add_argument("--pull-live")
    ap.add_argument("--row-version")
    return ap.parse_args()
'''


def _git(cwd, *args):
    return subprocess.run(
        ["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t",
         "-c", "commit.gpgsign=false", "-C", str(cwd), *args],
        capture_output=True, text=True, check=True,
    )


@pytest.fixture
def repos(tmp_path):
    """An upstream holding the current script, and a clone left behind on it."""
    up = tmp_path / "upstream"
    up.mkdir()
    _git(up, "init", "--initial-branch=main", "-q")
    (up / "scripts").mkdir()
    target = up / "scripts" / "writer.py"
    target.write_text(_OLD, encoding="utf-8")
    _git(up, "add", "-A")
    _git(up, "commit", "-qm", "first cut")
    target.write_text(_NEW, encoding="utf-8")
    _git(up, "add", "-A")
    _git(up, "commit", "-qm", "add --pull-live: the fleet keeps no rollback copies")

    work = tmp_path / "work"
    _git(tmp_path, "clone", "-q", str(up), str(work))
    return up, work


def test_a_current_copy_passes(repos):
    _up, work = repos
    assert guard.check(str(work / "scripts" / "writer.py")) == []


def test_a_stale_copy_is_refused_and_the_loss_is_named(repos):
    _up, work = repos
    script = work / "scripts" / "writer.py"
    script.write_text(_OLD, encoding="utf-8")  # the checkout fell behind

    problems = guard.check(str(script))
    assert len(problems) == 1
    report = problems[0]

    # Names the flags, not just "stale".
    assert "--pull-live" in report
    assert "--row-version" in report
    # And the code that went with them.
    assert "pull_live" in report
    # And which commit did it.
    assert "the fleet keeps no rollback copies" in report
    # Counts are computed from the two files, never written down.
    assert f"{_OLD.count(chr(10))} lines here" in report
    assert f"{_NEW.count(chr(10))} on origin/main" in report


def test_a_copy_that_was_never_on_the_ref_says_so(repos):
    """Worse than behind, and reported differently: a hand-edit has no base."""
    _up, work = repos
    script = work / "scripts" / "writer.py"
    script.write_text(_NEW.replace("--row-version", "--rowversion"), encoding="utf-8")
    report = guard.check(str(script))[0]
    assert "matches NO commit" in report


def test_a_file_outside_any_checkout_is_refused(tmp_path):
    """The `git show origin/main:... > /tmp/x.py` workaround has no provenance."""
    loose = tmp_path / "loose" / "writer.py"
    loose.parent.mkdir()
    loose.write_text(_NEW, encoding="utf-8")
    report = guard.check(str(loose))[0]
    assert "not inside a git checkout" in report


def test_a_path_absent_from_the_ref_is_refused(repos):
    _up, work = repos
    new_file = work / "scripts" / "brand-new-writer.py"
    new_file.write_text(_NEW, encoding="utf-8")
    report = guard.check(str(new_file))[0]
    assert "does not exist at origin/main" in report


def test_a_stale_sibling_fails_a_current_script(repos):
    """A fresh stage-wave.py on top of a stale deploy-to-fleet.py is the same bug."""
    up, work = repos
    # Committed upstream then fetched, rather than pushed: the upstream here is a
    # normal checkout with main checked out, and git refuses a push to that.
    (up / "scripts" / "sibling.py").write_text(_NEW, encoding="utf-8")
    _git(up, "add", "-A")
    _git(up, "commit", "-qm", "add sibling")
    _git(work, "fetch", "-q", "origin", "main")

    sibling = work / "scripts" / "sibling.py"
    sibling.write_text(_OLD, encoding="utf-8")
    problems = guard.check(str(work / "scripts" / "writer.py"), also=["sibling.py"])
    assert len(problems) == 1
    assert "sibling.py DIFFERS" in problems[0]


def test_an_unreachable_remote_refuses_a_clean_copy(repos, monkeypatch):
    """Clean against a ref nothing could refresh is not a verified copy."""
    _up, work = repos
    _git(work, "remote", "set-url", "origin", str(work / "does-not-exist"))
    monkeypatch.delenv("KTP_FRESHNESS_OFFLINE", raising=False)
    report = guard.check(str(work / "scripts" / "writer.py"))[0]
    assert "Could not fetch" in report

    monkeypatch.setenv("KTP_FRESHNESS_OFFLINE", "venue has no uplink")
    assert guard.check(str(work / "scripts" / "writer.py")) == []


def test_an_unreachable_remote_still_reports_real_drift(repos, monkeypatch):
    """Drift against a known-old ref is true without a network to confirm it."""
    _up, work = repos
    (work / "scripts" / "writer.py").write_text(_OLD, encoding="utf-8")
    _git(work, "remote", "set-url", "origin", str(work / "does-not-exist"))
    monkeypatch.delenv("KTP_FRESHNESS_OFFLINE", raising=False)
    report = guard.check(str(work / "scripts" / "writer.py"))[0]
    assert "--pull-live" in report
    assert "Could not fetch" not in report  # the network is not the headline


def test_require_current_exits_rather_than_returning(repos, monkeypatch):
    _up, work = repos
    script = work / "scripts" / "writer.py"
    script.write_text(_OLD, encoding="utf-8")
    # The suite itself is an inert context by design; this is the operator path.
    monkeypatch.setattr(guard, "_inert_context", lambda: None)
    monkeypatch.delenv("KTP_FRESHNESS_BYPASS", raising=False)
    with pytest.raises(SystemExit) as exc:
        guard.require_current(str(script), purpose="stage a wave")
    assert exc.value.code == 3


def test_a_bypass_proceeds_but_is_announced(repos, monkeypatch, capsys):
    _up, work = repos
    script = work / "scripts" / "writer.py"
    script.write_text(_OLD, encoding="utf-8")
    monkeypatch.setattr(guard, "_inert_context", lambda: None)
    monkeypatch.setenv("KTP_FRESHNESS_BYPASS", "github is down, wave is due tonight")
    guard.require_current(str(script), purpose="stage a wave")
    err = capsys.readouterr().err
    assert "BYPASSED ON PURPOSE" in err
    assert "github is down" in err
    assert "--pull-live" in err  # the report is printed anyway


def test_pytest_and_ci_are_inert_but_say_so(monkeypatch, capsys):
    assert guard._inert_context() == "pytest"
    guard.require_current(os.path.join(_SCRIPTS, "stage-wave.py"))
    assert "not gating (pytest)" in capsys.readouterr().err
