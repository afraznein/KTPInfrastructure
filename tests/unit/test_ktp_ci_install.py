"""ktp-ci-install: CI may install allowlisted scripts from verified main, and nothing else.

The point of the design is least privilege, so most of these tests are refusals,
and each refusal is paired with a control that the same file installs when the one
condition under test is lifted -- a refusal that fires for any reason proves nothing.
"""

from __future__ import annotations

import hashlib
import importlib.machinery
import importlib.util
import os
import re
import subprocess
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOL = os.path.join(_ROOT, "scripts", "ktp-ci-install")
KTP_INSTALL = os.path.join(_ROOT, "scripts", "ktp-install")
ALLOWLIST = os.path.join(_ROOT, "config", "ci-install-allowlist.tsv")
SUDOERS = os.path.join(_ROOT, "config", "sudoers.d", "ktp-ci-install")
WORKFLOW = os.path.join(_ROOT, ".github", "workflows", "ci-install.yml")

_loader = importlib.machinery.SourceFileLoader("ktp_ci_install", TOOL)
_spec = importlib.util.spec_from_loader("ktp_ci_install", _loader)
ci = importlib.util.module_from_spec(_spec)
_loader.exec_module(ci)

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="ktp-install uses fcntl and POSIX modes")


def md5(b):
    return hashlib.md5(b).hexdigest()


def read(path):
    with open(path, "rb") as f:
        return f.read()


# --- the scope as committed -------------------------------------------------

def test_committed_allowlist_parses_and_every_source_exists():
    entries = ci.parse_allowlist(read(ALLOWLIST).decode("utf-8"))
    assert entries, "an empty allowlist would make the workflow a no-op that reads as green"
    for dest, src in entries:
        assert os.path.isfile(os.path.join(_ROOT, src)), "%s is allowlisted but %s is gone" % (dest, src)


def test_committed_sudoers_is_exactly_what_the_allowlist_generates():
    entries = ci.parse_allowlist(read(ALLOWLIST).decode("utf-8"))
    assert read(SUDOERS) == ci.emit_sudoers(entries).encode("ascii"), \
        "regenerate: scripts/ktp-ci-install --emit-sudoers --repo . --ref HEAD > config/sudoers.d/ktp-ci-install"


def test_sudoers_grants_one_exact_wrapper_command_per_allowlisted_path_and_nothing_else():
    text = read(SUDOERS).decode("ascii")
    assert "\r" not in text
    entries = ci.parse_allowlist(read(ALLOWLIST).decode("utf-8"))
    rules = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
    defaults = [ln for ln in rules if ln.startswith("Defaults")]
    grants = [ln for ln in rules if not ln.startswith("Defaults")]
    assert defaults == ['Defaults:ktp-ci env_reset, secure_path="/usr/sbin:/usr/bin:/sbin:/bin"']
    exact = re.compile(r"ktp-ci ALL=\(root\) NOPASSWD: /usr/local/sbin/ktp-ci-install --install "
                       r"/usr/local/bin/[A-Za-z0-9][A-Za-z0-9._-]*\Z")
    assert all(exact.match(g) for g in grants), grants
    assert [g.rsplit(" ", 1)[1] for g in grants] == [d for d, _ in entries]
    for token in ("*", "?", "[", "!", "sudoedit", "SETENV", "%"):
        assert token not in "\n".join(grants), token


@pytest.mark.parametrize("name", sorted(ci.DENY))
def test_the_installer_and_the_witnesses_can_never_be_allowlisted(name):
    with pytest.raises(ci.Untrusted):
        ci.parse_allowlist("/usr/local/bin/%s\tscripts/%s\n" % (name, name))


@pytest.mark.parametrize("line", [
    "/usr/local/bin/../sbin/x\tscripts/x.sh",
    "/usr/local/bin/sub/x\tscripts/x.sh",
    "/usr/local/sbin/x\tscripts/x.sh",
    "/etc/cron.d/x\tscripts/x.sh",
    "/usr/local/bin/x*\tscripts/x.sh",
    "/usr/local/bin/x\t../x.sh",
    "/usr/local/bin/x\tscripts/../x.sh",
    "/usr/local/bin/x\tsites/x.py",
    "/usr/local/bin/x\tscripts/x.conf.example",
    "/usr/local/bin/x\tscripts/x.sh\textra",
    "/usr/local/bin/x",
])
def test_allowlist_refuses_anything_but_a_plain_name_in_bin_from_scripts(line):
    with pytest.raises(ci.Untrusted):
        ci.parse_allowlist(line + "\n")


def test_allowlist_control_a_plain_row_parses():
    assert ci.parse_allowlist("# c\n\n/usr/local/bin/x.sh\tscripts/x.sh\n") == [("/usr/local/bin/x.sh", "scripts/x.sh")]


def test_allowlist_refuses_a_duplicate_destination():
    with pytest.raises(ci.Untrusted):
        ci.parse_allowlist("/usr/local/bin/x\tscripts/x.sh\n/usr/local/bin/x\tscripts/y.sh\n")


def test_a_missing_allowlist_allows_nothing_rather_than_reading_as_empty():
    with pytest.raises(ci.Untrusted):
        ci.load_allowlist(lambda path: None)


# --- the workflow -----------------------------------------------------------

def _on_block(text):
    lines = text.splitlines()
    start = lines.index("on:")
    block = []
    for ln in lines[start + 1:]:
        if ln and not ln.startswith(" "):
            break
        block.append(ln)
    return "\n".join(block)


def test_workflow_triggers_are_push_to_main_and_dispatch_only():
    on = _on_block(read(WORKFLOW).decode("utf-8"))
    assert "pull_request" not in on and "schedule" not in on
    assert "push:" in on and "branches: [main]" in on and "workflow_dispatch:" in on


def test_workflow_never_runs_on_the_root_runner_and_refuses_uid_0():
    text = read(WORKFLOW).decode("utf-8")
    runs_on = re.findall(r"runs-on: (.*)", text)
    assert runs_on and all(r == "[self-hosted, ktp-ci-install]" for r in runs_on), runs_on
    assert "ktp-tier2" not in "\n".join(runs_on)
    assert '"$(id -u)" -eq 0' in text


def test_workflow_holds_no_privilege_but_the_one_sudo_command():
    text = read(WORKFLOW).decode("utf-8")
    sudo_lines = [ln.strip() for ln in text.splitlines() if re.search(r"\bsudo\b", ln) and not ln.strip().startswith("#")
                  and "::error::" not in ln]
    assert sudo_lines == ['if ! sudo -n %s --install "$d"; then' % ci.WRAPPER], sudo_lines
    assert "permissions:\n  contents: read" in text
    assert text.count("persist-credentials: false") == text.count("actions/checkout@")


# --- installing -------------------------------------------------------------

V1 = b"#!/bin/bash\necho v1\n"
V2 = b"#!/bin/bash\necho v2\n"


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def commit_all(repo, msg):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def box(tmp_path):
    repo = tmp_path / "KTPInfrastructure"
    (repo / "scripts").mkdir(parents=True)
    (repo / "config").mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.invalid")
    git(repo, "config", "user.name", "t")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (repo / "scripts" / "tool.sh").write_bytes(V1)
    (repo / "scripts" / "other.sh").write_bytes(V1)
    (repo / "config" / "ci-install-allowlist.tsv").write_text(
        "%s/tool.sh\tscripts/tool.sh\n" % bindir, newline="\n")
    c1 = commit_all(repo, "v1")
    env = dict(os.environ, KTP_MANIFEST=str(tmp_path / "DEPLOYED.tsv"),
               KTP_INSTALL_BACKUPS=str(tmp_path / "backups"), KTP_DEPLOYED_BY="ktp-ci-install(test)",
               HOME=str(tmp_path))
    b = dict(repo=repo, bin=bindir, c1=c1, env=env, manifest=str(tmp_path / "DEPLOYED.tsv"),
             stage=str(tmp_path / "stage"), tmp=tmp_path)
    for name in ("tool.sh", "other.sh"):
        human_install(b, c1, "scripts/" + name, name)
    (repo / "scripts" / "tool.sh").write_bytes(V2)
    (repo / "scripts" / "other.sh").write_bytes(V2)
    b["c2"] = commit_all(repo, "v2")
    return b


def human_install(b, commit, src, name):
    p = subprocess.run([sys.executable, KTP_INSTALL, "--repo", str(b["repo"]), "--commit", commit,
                        "--src", src, "--dest", str(b["bin"] / name), "--expect-md5", "-"],
                       env=b["env"], capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr


def manifest_lines(b):
    return read(b["manifest"]).decode().splitlines()


def ci_install(b, name, ref=None):
    commit, show = ci.repo_show(str(b["repo"]), ref or b["c2"])
    entries = ci.load_allowlist(show, bin_dir=str(b["bin"]))
    return ci.install_one(str(b["bin"] / name), entries, commit, show, b["manifest"],
                          [sys.executable, KTP_INSTALL], b["env"], b["stage"])


@posix_only
def test_a_stale_allowlisted_script_is_installed_from_the_commit_and_recorded(box, capsys):
    assert ci_install(box, "tool.sh") == 0
    assert read(box["bin"] / "tool.sh") == V2
    last = manifest_lines(box)[-1].split("\t")
    assert last[0] == str(box["bin"] / "tool.sh") and last[1] == md5(V2) and last[3] == box["c2"]
    assert last[6] == md5(V1) and last[7] == "ktp-ci-install(test)"
    assert not os.listdir(box["stage"]), "the staged blob must not outlive the install"


@posix_only
def test_a_current_script_writes_nothing(box):
    assert ci_install(box, "tool.sh") == 0
    before = manifest_lines(box)
    assert ci_install(box, "tool.sh") == 0
    assert manifest_lines(box) == before


@posix_only
def test_a_stale_script_off_the_allowlist_is_refused_and_untouched(box, capsys):
    before = manifest_lines(box)
    assert ci_install(box, "other.sh") == ci.EXIT_REFUSED
    assert "NOT-ALLOWLISTED" in capsys.readouterr().out
    assert read(box["bin"] / "other.sh") == V1 and manifest_lines(box) == before
    # Control: the same stale file installs once the allowlist at the commit names it.
    al = box["repo"] / "config" / "ci-install-allowlist.tsv"
    al.write_text(al.read_text() + "%s/other.sh\tscripts/other.sh\n" % box["bin"], newline="\n")
    c3 = commit_all(box["repo"], "allow other")
    assert ci_install(box, "other.sh", ref=c3) == 0
    assert read(box["bin"] / "other.sh") == V2


@posix_only
def test_the_allowlist_is_read_from_the_commit_never_the_work_tree(box):
    al = box["repo"] / "config" / "ci-install-allowlist.tsv"
    al.write_text(al.read_text() + "%s/other.sh\tscripts/other.sh\n" % box["bin"], newline="\n")
    assert ci_install(box, "other.sh") == ci.EXIT_REFUSED
    assert read(box["bin"] / "other.sh") == V1


@posix_only
def test_a_hand_edited_script_is_never_clobbered(box, capsys):
    (box["bin"] / "tool.sh").write_bytes(b"#!/bin/bash\necho hotfix\n")
    before = manifest_lines(box)
    assert ci_install(box, "tool.sh") == ci.EXIT_REFUSED
    assert "DRIFT" in capsys.readouterr().out
    assert read(box["bin"] / "tool.sh") == b"#!/bin/bash\necho hotfix\n" and manifest_lines(box) == before


@posix_only
def test_a_script_with_no_manifest_row_is_a_persons_first_install(box, capsys):
    al = box["repo"] / "config" / "ci-install-allowlist.tsv"
    al.write_text(al.read_text() + "%s/fresh.sh\tscripts/tool.sh\n" % box["bin"], newline="\n")
    c3 = commit_all(box["repo"], "allow fresh")
    (box["bin"] / "fresh.sh").write_bytes(V1)
    assert ci_install(box, "fresh.sh", ref=c3) == ci.EXIT_REFUSED
    assert "NOT-RECORDED" in capsys.readouterr().out and read(box["bin"] / "fresh.sh") == V1


@posix_only
def test_a_script_removed_upstream_is_refused(box, capsys):
    (box["repo"] / "scripts" / "tool.sh").unlink()
    c3 = commit_all(box["repo"], "remove tool")
    assert ci_install(box, "tool.sh", ref=c3) == ci.EXIT_REFUSED
    assert "SOURCE-GONE" in capsys.readouterr().out and read(box["bin"] / "tool.sh") == V1


@posix_only
def test_a_symlinked_destination_is_refused(box, capsys):
    target = box["tmp"] / "elsewhere"
    target.write_bytes(V1)
    (box["bin"] / "tool.sh").unlink()
    os.symlink(target, box["bin"] / "tool.sh")
    assert ci_install(box, "tool.sh") == ci.EXIT_REFUSED
    assert "NOT-REGULAR" in capsys.readouterr().out and read(target) == V1


@posix_only
def test_a_row_from_another_source_path_is_refused(box, capsys):
    al = box["repo"] / "config" / "ci-install-allowlist.tsv"
    al.write_text("%s/tool.sh\tscripts/other.sh\n" % box["bin"], newline="\n")
    c3 = commit_all(box["repo"], "repoint")
    assert ci_install(box, "tool.sh", ref=c3) == ci.EXIT_REFUSED
    assert "SOURCE-MISMATCH" in capsys.readouterr().out


# --- checking ---------------------------------------------------------------

def run_check(b, scope, ref=None):
    commit, show = ci.repo_show(str(b["repo"]), ref or b["c2"])
    entries = ci.load_allowlist(show, bin_dir=str(b["bin"]))
    return ci.check(entries, ci.last_rows(b["manifest"]), show, scope)


@posix_only
def test_check_allowlisted_fails_until_installed_then_passes(box, capsys):
    assert run_check(box, "allowlisted") == 1
    assert ci_install(box, "tool.sh") == 0
    assert run_check(box, "allowlisted") == 0


@posix_only
def test_check_outside_fails_loudly_on_a_stale_script_ci_may_not_install(box, capsys):
    assert run_check(box, "outside") == 1
    out = capsys.readouterr().out
    assert "STALE-OUTSIDE-LIST" in out and "other.sh" in out and "/tool.sh" not in out
    human_install_current(box, "other.sh")
    assert run_check(box, "outside") == 0


def human_install_current(b, name):
    p = subprocess.run([sys.executable, KTP_INSTALL, "--repo", str(b["repo"]), "--commit", b["c2"],
                        "--src", "scripts/" + name, "--dest", str(b["bin"] / name),
                        "--expect-md5", md5(V1)], env=b["env"], capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr


@posix_only
def test_check_outside_catches_a_recorded_script_removed_upstream(box, capsys):
    human_install_current(box, "other.sh")
    (box["repo"] / "scripts" / "other.sh").unlink()
    c3 = commit_all(box["repo"], "remove other")
    assert run_check(box, "outside", ref=c3) == 1
    assert "REMOVED-UPSTREAM" in capsys.readouterr().out


@posix_only
def test_check_ignores_rows_from_other_repos(box, capsys):
    human_install_current(box, "other.sh")
    with open(box["manifest"], "a") as f:
        f.write("\t".join(["/x/elsewhere.py", "0" * 32, "KTPAdminBot", "a" * 40, "bot.py",
                           "2026-01-01T00:00:00+0000", "-", "t"]) + "\n")
    assert run_check(box, "outside") == 0


@posix_only
def test_check_cli_refuses_an_allowlist_outside_bin(box):
    def cli(*args):
        return subprocess.run([sys.executable, TOOL, "--check", "--repo", str(box["repo"]), "--ref", box["c2"],
                               "--manifest", box["manifest"], *args], capture_output=True, text=True)
    # The repo's allowlist names a tmp bin dir, which the CLI's fixed /usr/local/bin refuses.
    p = cli()
    assert p.returncode == 2 and "UNTRUSTED" in p.stdout


# --- the privileged entry point ---------------------------------------------

@pytest.mark.parametrize("extra", [["--repo", "."], ["--ref", "HEAD"], ["--manifest", "/tmp/m"],
                                   ["--scope", "all"], ["--runner-user", "root"]])
def test_install_takes_the_destination_and_nothing_else(extra):
    p = subprocess.run([sys.executable, TOOL, "--install", "/usr/local/bin/x", *extra],
                       capture_output=True, text=True)
    assert p.returncode == 2 and "nothing else" in p.stderr


@pytest.mark.skipif(sys.platform == "win32" or os.geteuid() == 0, reason="needs a non-root POSIX user")
def test_install_refuses_without_root():
    p = subprocess.run([sys.executable, TOOL, "--install", "/usr/local/bin/x"], capture_output=True, text=True)
    assert p.returncode == 2 and "runs as root through sudo" in p.stdout


@posix_only
def test_fetch_verified_pins_the_mirror_to_the_remotes_tip(box, tmp_path):
    commit, show = ci.fetch_verified(str(box["repo"]), str(tmp_path / "state" / "mirror.git"))
    assert commit == box["c2"] and show("scripts/tool.sh") == V2


@posix_only
def test_fetch_verified_refuses_a_mirror_that_is_not_the_tip(box, tmp_path):
    with pytest.raises(ci.Untrusted):
        ci.fetch_verified(str(box["repo"]), str(tmp_path / "state" / "mirror.git"), ls_remote=lambda: box["c1"])
