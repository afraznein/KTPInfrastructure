"""ktp-install: installs a git blob byte-for-byte and records it in the deploy manifest.

Every verdict is exercised in both directions -- a report that cannot say DRIFT
proves nothing, and neither does an install that cannot refuse.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys

import pytest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TOOL = os.path.join(_ROOT, "scripts", "ktp-install")
HEADER = "\t".join(["installed_path", "md5", "source_repo", "source_commit", "source_path",
                    "deployed_at_iso", "previous_md5", "deployed_by"])

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="uses fcntl and POSIX modes")


def md5(b):
    return hashlib.md5(b).hexdigest()


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


V1 = b"#!/bin/bash\necho v1\n"
V2 = b"#!/bin/bash\necho v2\n"


@pytest.fixture
def env(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "t@example.invalid")
    git(repo, "config", "user.name", "t")
    (repo / "scripts").mkdir()
    (repo / "scripts" / "tool.sh").write_bytes(V1)
    (repo / "scripts" / "conf.sh.example").write_bytes(b"SECRET=\"YOUR_SECRET_HERE\"\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "v1")
    c1 = git(repo, "rev-parse", "HEAD")
    (repo / "scripts" / "tool.sh").write_bytes(V2)
    git(repo, "commit", "-q", "-am", "v2")
    c2 = git(repo, "rev-parse", "HEAD")
    dest = tmp_path / "bin"
    dest.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    e = dict(os.environ, KTP_MANIFEST=str(tmp_path / "share" / "DEPLOYED.tsv"),
             KTP_INSTALL_BACKUPS=str(tmp_path / "backups"), KTP_DEPLOYED_BY="test@host", HOME=str(home))
    return dict(repo=repo, c1=c1, c2=c2, dest=dest, env=e, tmp=tmp_path, home=home,
                manifest=tmp_path / "share" / "DEPLOYED.tsv")


def run(env, *args, extra_env=None):
    e = dict(env["env"], **(extra_env or {}))
    return subprocess.run([sys.executable, TOOL, *args], env=e, capture_output=True, text=True)


def install(env, commit, expect, *extra, dest_name="tool.sh", src="scripts/tool.sh"):
    return run(env, "--repo", str(env["repo"]), "--commit", commit, "--src", src,
               "--dest", str(env["dest"] / dest_name), "--expect-md5", expect, *extra)


def rows(env, path=None):
    lines = (path or env["manifest"]).read_text().splitlines()
    assert lines[0] == HEADER
    return [l.split("\t") for l in lines[1:]]


def test_fresh_install_is_the_blob_and_is_recorded(env):
    p = install(env, env["c1"], "-")
    assert p.returncode == 0, p.stderr
    assert (env["dest"] / "tool.sh").read_bytes() == V1
    r = rows(env)
    assert len(r) == 1
    assert r[0][0] == str(env["dest"] / "tool.sh")
    assert r[0][1] == md5(V1)
    assert r[0][3] == env["c1"] and len(r[0][3]) == 40
    assert r[0][4] == "scripts/tool.sh"
    assert r[0][6] == "-" and r[0][7] == "test@host"
    assert os.stat(env["dest"] / "tool.sh").st_mode & 0o777 == 0o755


def test_upgrade_banks_backup_keeps_mode_and_records_previous_md5(env):
    install(env, env["c1"], "-")
    os.chmod(env["dest"] / "tool.sh", 0o750)
    p = install(env, env["c2"], md5(V1))
    assert p.returncode == 0, p.stderr
    assert (env["dest"] / "tool.sh").read_bytes() == V2
    assert os.stat(env["dest"] / "tool.sh").st_mode & 0o777 == 0o750
    r = rows(env)
    assert [x[3] for x in r] == [env["c1"], env["c2"]]
    assert r[1][6] == md5(V1)
    backups = os.listdir(env["tmp"] / "backups")
    assert len(backups) == 1 and md5(V1)[:8] in backups[0]
    assert md5((env["tmp"] / "backups" / backups[0]).read_bytes()) == md5(V1)
    assert not (env["dest"] / "tool.sh.new").exists()


def test_wrong_expected_md5_refuses_and_changes_nothing(env):
    install(env, env["c1"], "-")
    p = install(env, env["c2"], "0" * 32)
    assert p.returncode != 0 and "not touching it" in p.stderr
    assert (env["dest"] / "tool.sh").read_bytes() == V1
    assert len(rows(env)) == 1


def test_expecting_absent_refuses_when_file_exists(env):
    (env["dest"] / "tool.sh").write_bytes(b"hand edited\n")
    p = install(env, env["c1"], "-")
    assert p.returncode != 0
    assert (env["dest"] / "tool.sh").read_bytes() == b"hand edited\n"
    assert not env["manifest"].exists()


def test_same_bytes_is_not_a_new_install(env):
    install(env, env["c1"], "-")
    p = install(env, env["c1"], md5(V1))
    assert p.returncode != 0 and "nothing to install" in p.stderr
    assert len(rows(env)) == 1


def test_repo_mode_file_must_equal_blob(env):
    other = env["tmp"] / "other.sh"
    other.write_bytes(b"#!/bin/bash\necho tampered\n")
    p = install(env, env["c2"], "-", "--file", str(other))
    assert p.returncode != 0 and "differs" in p.stderr
    assert not (env["dest"] / "tool.sh").exists()


def test_no_repo_mode_needs_blob_md5_and_checks_it(env):
    pushed = env["tmp"] / "pushed.sh"
    pushed.write_bytes(V2)
    base = ["--file", str(pushed), "--source-repo", "KTPInfrastructure", "--commit", env["c2"],
            "--src", "scripts/tool.sh", "--dest", str(env["dest"] / "tool.sh"), "--expect-md5", "-"]
    p = run(env, *base)
    assert p.returncode != 0 and "--blob-md5" in p.stderr
    p = run(env, *base, "--blob-md5", md5(V1))
    assert p.returncode != 0 and "not the blob" in p.stderr
    assert not (env["dest"] / "tool.sh").exists()
    p = run(env, *base, "--blob-md5", md5(V2))
    assert p.returncode == 0, p.stderr
    r = rows(env)[-1]
    assert r[2] == "KTPInfrastructure" and r[3] == env["c2"] and r[1] == md5(V2)


def test_no_repo_mode_refuses_a_short_sha(env):
    pushed = env["tmp"] / "pushed.sh"
    pushed.write_bytes(V2)
    p = run(env, "--file", str(pushed), "--source-repo", "X", "--commit", env["c2"][:12], "--src", "scripts/tool.sh",
            "--blob-md5", md5(V2), "--dest", str(env["dest"] / "tool.sh"), "--expect-md5", "-")
    assert p.returncode != 0 and "40-hex" in p.stderr


def test_template_records_template_source_and_filled_md5(env):
    filled = env["tmp"] / "conf.sh"
    filled.write_bytes(b"SECRET=\"real\"\n")
    p = install(env, env["c2"], "-", "--file", str(filled), "--template",
                dest_name="conf.sh", src="scripts/conf.sh.example")
    assert p.returncode == 0, p.stderr
    r = rows(env)[-1]
    assert r[1] == md5(b"SECRET=\"real\"\n")
    assert r[3] == env["c2"] and r[4] == "scripts/conf.sh.example"


def test_template_flag_and_example_source_must_agree(env):
    filled = env["tmp"] / "conf.sh"
    filled.write_bytes(b"SECRET=\"real\"\n")
    p = install(env, env["c2"], "-", "--file", str(filled), dest_name="conf.sh", src="scripts/conf.sh.example")
    assert p.returncode != 0 and "template" in p.stderr
    p = install(env, env["c2"], "-", "--file", str(filled), "--template", dest_name="conf.sh", src="scripts/tool.sh")
    assert p.returncode != 0 and ".example" in p.stderr
    assert not env["manifest"].exists()


def test_report_ok_then_drift_then_missing(env):
    install(env, env["c1"], "-")
    p = run(env, "--report")
    assert p.returncode == 0 and p.stdout.startswith("OK"), p.stdout
    (env["dest"] / "tool.sh").write_bytes(b"#!/bin/bash\necho hotfix\n")
    p = run(env, "--report")
    assert p.returncode == 1 and p.stdout.startswith("DRIFT"), p.stdout
    os.unlink(env["dest"] / "tool.sh")
    p = run(env, "--report")
    assert p.returncode == 1 and p.stdout.startswith("MISSING"), p.stdout


def test_report_labels_templated_not_drift_and_still_catches_a_changed_fill(env):
    filled = env["tmp"] / "conf.sh"
    filled.write_bytes(b"SECRET=\"real\"\n")
    install(env, env["c2"], "-", "--file", str(filled), "--template", dest_name="conf.sh", src="scripts/conf.sh.example")
    p = run(env, "--report", "--repo", str(env["repo"]))
    assert p.returncode == 0 and p.stdout.startswith("TEMPLATED"), p.stdout
    (env["dest"] / "conf.sh").write_bytes(b"SECRET=\"edited\"\n")
    p = run(env, "--report")
    assert p.returncode == 1 and p.stdout.startswith("DRIFT"), p.stdout


def test_report_uses_the_last_row_per_path(env):
    install(env, env["c1"], "-")
    install(env, env["c2"], md5(V1))
    p = run(env, "--report")
    assert p.returncode == 0, p.stdout
    assert env["c2"][:12] in p.stdout and env["c1"][:12] not in p.stdout


def test_report_with_repo_catches_a_row_whose_commit_does_not_hold_the_bytes(env):
    install(env, env["c1"], "-")
    env["manifest"].write_text(env["manifest"].read_text().replace(env["c1"], env["c2"]))
    assert run(env, "--report").returncode == 0
    p = run(env, "--report", "--repo", str(env["repo"]))
    assert p.returncode == 1 and "SOURCE-MISMATCH" in p.stdout, p.stdout


@pytest.mark.parametrize("content", [
    None,
    "",
    "wrong\theader\n",
    HEADER + "\n",
    HEADER + "\n/x\tshort\n",
    HEADER + "\n/x\t" + "z" * 32 + "\tR\t" + "a" * 40 + "\tp\tt\t-\tw\n",
    "\t".join(["path", "md5", "repo", "commit", "src", "at", "prev", "by"]) + "\n/x\t" + "a" * 32
    + "\tR\t" + "b" * 40 + "\tp\tt\t-\tw\n",
])
def test_report_fails_closed_on_an_untrustworthy_manifest(env, content):
    if content is not None:
        env["manifest"].parent.mkdir(parents=True, exist_ok=True)
        env["manifest"].write_text(content)
    p = run(env, "--report")
    assert p.returncode == 2 and "UNTRUSTED" in p.stdout, (p.returncode, p.stdout)


def test_install_refuses_to_append_under_a_foreign_header(env):
    env["manifest"].parent.mkdir(parents=True, exist_ok=True)
    env["manifest"].write_text("something else\n")
    p = install(env, env["c1"], "-")
    assert p.returncode != 0 and "header" in p.stderr
    assert env["manifest"].read_text() == "something else\n"


@pytest.mark.skipif(os.geteuid() == 0 if hasattr(os, "geteuid") else True, reason="needs a non-root user")
def test_non_root_default_is_the_home_manifest_and_report_reads_it(env):
    e = {"KTP_MANIFEST": "", "KTP_INSTALL_BACKUPS": ""}
    p = run(env, "--repo", str(env["repo"]), "--commit", env["c1"], "--src", "scripts/tool.sh",
            "--dest", str(env["dest"] / "tool.sh"), "--expect-md5", "-", extra_env=e)
    assert p.returncode == 0, p.stderr
    home_manifest = env["home"] / ".ktp" / "DEPLOYED.tsv"
    assert rows(env, home_manifest)[0][1] == md5(V1)
    assert not env["manifest"].exists()
    p = run(env, "--report", extra_env=e)
    assert p.returncode == 0 and p.stdout.startswith("OK"), p.stdout
